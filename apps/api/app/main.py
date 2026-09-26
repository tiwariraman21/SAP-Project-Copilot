import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import flag_modified

from .agents import AGENT_CAPABILITIES
from .config import get_settings, settings
from .database import Base, SessionLocal, engine, get_db
from .fsd_template import get_fsd_template
from .models import AIUsageEvent, Artifact, BRDKnowledge, Document, DocumentChunk, Project, ProjectStatus, Requirement, ReviewStatus
from .schemas import (
    CompanionAsk,
    CompanionAnswerOut,
    CompanionContextOut,
    JiraConfigIn,
    JiraConfigStatusOut,
    JiraTestConnectionOut,
    JiraSyncIn,
    JiraSyncResultOut,
    ProjectOut,
    RequirementCreate,
    RequirementUpdate,
)
from .services.companion_chat import answer_companion_question, companion_context, store_companion_turn
from .services.documents import extract_document
from .services.brd_intelligence import extract_brd_knowledge
from .services.downstream import BUILDERS
from .services.functional_design import build_functional_specification
from .services.fsd_export import export_fsd_files
from .services.fsd_validation import FSDValidationError, validate_fsd_document
from .services.jira_sync import JiraClient, _generate_jira_project_key, export_jira_csv, export_jira_test_cases_csv
from .services.openai_support import AIServiceError, Usage
from .services.project_identity import business_project_name
from .services.requirement_intelligence import extract_requirements
from .services.quality_test_export import export_quality_tests
from .services.resource_distribution import export_resource_distribution, suggest_resource_distribution
from .services.sprint_plan_export import export_sprint_plan
from .services.starter_code import _slug, build_starter_code_zip
from .services.technical_design_export import export_technical_design
from .services.timing import start_timing_session, stop_timing_session

app = FastAPI(title="SAP Project Copilot API", version="0.1.0")
logger = logging.getLogger("uvicorn.error")
job_lock = Lock()
processing_jobs: dict[str, dict] = {}
artifact_jobs: dict[str, dict] = {}
app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["Content-Disposition"])
Base.metadata.create_all(engine)
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
Path(settings.artifact_dir).mkdir(parents=True, exist_ok=True)


def load_project(db: Session, project_id: str) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id).options(
        selectinload(Project.document).selectinload(Document.chunks), selectinload(Project.brd_knowledge), selectinload(Project.requirements), selectinload(Project.artifacts)))
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def serialize(project: Project) -> ProjectOut:
    return ProjectOut(id=project.id, name=project.name, status=project.status.value, created_at=project.created_at,
        filename=project.document.filename, page_count=project.document.page_count, chunks=project.document.chunks,
        requirements=sorted(project.requirements, key=lambda r: r.requirement_key), artifacts=project.artifacts)


def save_usage(db: Session, project_id: str, call_type: str, usage: Usage | None) -> None:
    if usage:
        db.add(AIUsageEvent(project_id=project_id, call_type=call_type, **usage.as_dict()))




def _file_sha256(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()

def brd_knowledge_sha256(project: Project) -> str:
    knowledge = getattr(project, "brd_knowledge", None)
    if not knowledge or not isinstance(knowledge.payload, dict):
        return "none"
    return hashlib.sha256(
        json.dumps(knowledge.payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def extract_and_store_brd_knowledge(db: Session, project: Project, chunks: list[DocumentChunk],
                                    progress=None) -> Usage | None:
    """Analyze the complete BRD once and persist reusable structured context."""
    if not settings.openai_api_key:
        return None
    source_path = Path(project.document.storage_path)
    source_hash = _file_sha256(source_path)
    existing = getattr(project, "brd_knowledge", None)
    if (existing and existing.source_sha256 == source_hash
            and existing.extraction_version == "brd-knowledge-v1"
            and existing.model == settings.openai_brd_model
            and isinstance(existing.payload, dict) and existing.payload):
        if progress:
            progress("Reusing persisted BRD knowledge; source and extraction version are unchanged", 34)
        return None

    if progress:
        progress("Extracting complete BRD knowledge (tables, screens, data, integrations and NFRs)", 12)
    chunk_payload = [{"id": c.id, "page": c.page, "locator": c.locator, "text": c.text} for c in chunks]
    knowledge, usage, input_mode = extract_brd_knowledge(
        project.document.storage_path, project.document.filename, chunk_payload
    )
    if existing is None:
        existing = BRDKnowledge(project_id=project.id)
        db.add(existing)
    existing.extraction_version = "brd-knowledge-v1"
    existing.model = settings.openai_brd_model
    existing.input_mode = input_mode
    existing.source_sha256 = source_hash
    existing.coverage_percent = 100.0
    existing.payload = knowledge.model_dump()
    save_usage(db, project.id, "brd_knowledge_extraction", usage)
    if progress:
        progress(f"BRD knowledge extracted with 100% source-input coverage using {input_mode} mode", 34)
    return usage


def fsd_baseline_sha256(project: Project) -> str:
    approved = sorted((item for item in project.requirements if item.review_status == ReviewStatus.approved),
                      key=lambda item: item.requirement_key)
    baseline = {
        "project_name": project.name,
        "source_document": project.document.filename,
        "brd_knowledge_sha256": brd_knowledge_sha256(project),
        "requirements": [{
            "id": item.requirement_key, "title": item.title, "statement": item.statement,
            "type": item.requirement_type, "priority": item.priority, "rationale": item.rationale,
            "acceptance_criteria": item.acceptance_criteria, "assumptions": item.assumptions,
            "source_quote": item.source_quote,
        } for item in approved],
    }
    return hashlib.sha256(json.dumps(baseline, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def fsd_generation_metadata(project: Project, usage: Usage | None, *, cache_hit: bool = False,
                            model_override: str | None = None, duration_seconds: float | None = None) -> dict:
    template = get_fsd_template()
    approved = sorted((item for item in project.requirements if item.review_status == ReviewStatus.approved),
                      key=lambda item: item.requirement_key)
    knowledge = getattr(project, "brd_knowledge", None)
    return {
        **template.provenance(),
        "model": model_override or (usage.model if usage else "local-demo"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_document": project.document.filename,
        "brd_knowledge_sha256": brd_knowledge_sha256(project),
        "brd_knowledge_version": knowledge.extraction_version if knowledge else None,
        "brd_knowledge_model": knowledge.model if knowledge else None,
        "brd_knowledge_coverage_percent": knowledge.coverage_percent if knowledge else None,
        "approved_requirement_ids": [item.requirement_key for item in approved],
        "requirement_baseline_sha256": fsd_baseline_sha256(project),
        "cache_hit": cache_hit,
        "duration_seconds": round(duration_seconds, 2) if duration_seconds is not None else None,
    }


def fsd_cached_document(project: Project, artifact: Artifact) -> dict | None:
    payload = artifact.payload if isinstance(artifact.payload, dict) else {}
    document = payload.get("document")
    generation = payload.get("generation") if isinstance(payload.get("generation"), dict) else {}
    template = get_fsd_template()
    expected_model = settings.openai_fsd_model if settings.openai_api_key else "local-demo"
    if (not isinstance(document, dict)
            or generation.get("requirement_baseline_sha256") != fsd_baseline_sha256(project)
            or generation.get("template_version") != template.template_version
            or generation.get("schema_version") != template.schema_version
            or generation.get("prompt_version") != template.prompt_version
            or generation.get("model") != expected_model):
        return None
    return document


def database_busy(exc: OperationalError) -> HTTPException:
    logger.warning("Database write could not complete: %s", exc)
    return HTTPException(503, "The project database is busy. Please wait a few seconds and try once more.")


def update_job(project_id: str, *, status: str | None = None, stage: str | None = None,
               progress: int | None = None, message: str | None = None,
               level: str = "info", error: str | None = None) -> None:
    with job_lock:
        job = processing_jobs.setdefault(project_id, {"project_id": project_id, "status": "processing",
            "stage": "Queued", "progress": 0, "logs": [], "error": None})
        if status is not None: job["status"] = status
        if stage is not None: job["stage"] = stage
        if progress is not None and progress > 0: job["progress"] = progress
        if error is not None: job["error"] = error
        if message:
            job["logs"].append({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "level": level, "message": message})
            job["logs"] = job["logs"][-100:]
    if message:
        log_method = logger.error if level == "error" else logger.warning if level == "warning" else logger.info
        log_method("[project %s] %s", project_id, message)


def update_artifact_job(project_id: str, kind: str, *, status: str | None = None,
                        stage: str | None = None, progress: int | None = None,
                        message: str | None = None, level: str = "info",
                        error: str | None = None) -> None:
    key = f"{project_id}:{kind}"
    with job_lock:
        job = artifact_jobs.setdefault(key, {"project_id": project_id, "kind": kind, "status": "processing",
            "stage": "Queued", "progress": 0, "logs": [], "error": None})
        if status is not None: job["status"] = status
        if stage is not None: job["stage"] = stage
        if progress is not None and progress > 0: job["progress"] = progress
        if error is not None: job["error"] = error
        if message:
            job["logs"].append({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "level": level, "message": message})
            job["logs"] = job["logs"][-100:]
    if message:
        log_method = logger.error if level == "error" else logger.warning if level == "warning" else logger.info
        log_method("[project %s] [%s] %s", project_id, kind, message)


async def persist_project_upload(name: str, file: UploadFile, db: Session) -> tuple[Project, list[DocumentChunk], Path]:
    content = await file.read()
    if not content or len(content) > 20 * 1024 * 1024:
        raise HTTPException(400, "Document must be between 1 byte and 20 MB")
    try:
        page_count, extracted = extract_document(file.filename or "document", content)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not extracted:
        raise HTTPException(422, "No usable text was found in the document")
    project = Project(name=name.strip() or Path(file.filename or "BRD").stem)
    db.add(project); db.flush()
    stored = Path(settings.upload_dir) / f"{project.id}-{Path(file.filename or 'brd').name}"
    stored.write_bytes(content)
    document = Document(project_id=project.id, filename=file.filename or "BRD", storage_path=str(stored), page_count=page_count)
    db.add(document); db.flush()
    chunks = [DocumentChunk(document_id=document.id, page=c.page, locator=c.locator, text=c.text) for c in extracted]
    db.add_all(chunks)
    try:
        db.commit()
    except OperationalError as exc:
        db.rollback()
        stored.unlink(missing_ok=True)
        raise database_busy(exc) from exc
    logger.info("[project %s] Document stored: %s, %s pages, %s chunks", project.id, file.filename, page_count, len(chunks))
    return project, chunks, stored


def process_project_requirements(project_id: str) -> None:
    update_job(project_id, stage="Requirement extraction", progress=12,
               message="Background worker started; database upload transaction is closed")
    with SessionLocal() as db:
        try:
            project = load_project(db, project_id)
            chunks = sorted(project.document.chunks, key=lambda c: (c.page, c.locator))
            update_job(project_id, stage="BRD knowledge extraction", progress=11,
                       message=f"Loaded {len(chunks)} document chunks and the original BRD for full-context analysis")

            def brd_report(message: str, percent: int) -> None:
                update_job(project_id, stage="OpenAI BRD understanding", progress=percent, message=message)

            try:
                extract_and_store_brd_knowledge(db, project, chunks, brd_report)
                db.commit()
            except AIServiceError as exc:
                if not settings.openai_allow_demo_fallback:
                    raise
                update_job(project_id, stage="BRD knowledge extraction", progress=35,
                           message=f"BRD knowledge extraction skipped after error; continuing in fallback mode: {exc}", level="warning")

            def report(message: str, percent: int) -> None:
                mapped = 35 + int(percent * 0.58)
                update_job(project_id, stage="OpenAI requirement extraction", progress=mapped, message=message)

            requirements, usage = extract_requirements(
                [{"id": c.id, "page": c.page, "locator": c.locator, "text": c.text} for c in chunks], report)
            update_job(project_id, stage="Saving requirements", progress=97,
                       message=f"Saving {len(requirements)} validated requirements to SQLite")
            db.add_all([Requirement(project_id=project_id, requirement_key=f"REQ-{i:03}", **item.model_dump())
                        for i, item in enumerate(requirements, 1)])
            save_usage(db, project_id, "requirements_extraction", usage)
            db.commit()
            usage_message = f" Token usage: {usage.total_tokens}." if usage else ""
            update_job(project_id, status="completed", stage="Ready for human review", progress=100,
                       message=f"Analysis complete — {len(requirements)} requirements are ready.{usage_message}")
        except Exception as exc:
            db.rollback()
            safe_error = str(exc)
            update_job(project_id, status="failed", stage="Analysis failed", progress=100,
                       message=f"Analysis failed: {safe_error}", level="error", error=safe_error)
            logger.exception("Background requirement extraction failed for project %s", project_id)


def process_fsd_generation(project_id: str) -> None:
    started = time.perf_counter()
    timings: list[dict] = []

    def record_timing(event: dict) -> None:
        timings.append(event)
        with job_lock:
            job = artifact_jobs.get(f"{project_id}:fsd")
            if job is not None:
                job["timings"] = list(timings)
        update_artifact_job(project_id, "fsd", message=f"{event['function']} finished in {event['duration_ms'] / 1000:.2f}s", level="error" if event["status"] == "failed" else "info")

    timing_token = start_timing_session(record_timing)
    update_artifact_job(project_id, "fsd", stage="Preparing functional design", progress=10,
                        message="FSD background worker started from the approved baseline")
    with SessionLocal() as db:
        try:
            project = load_project(db, project_id)
            artifact = next((a for a in project.artifacts if a.kind == "fsd"), None)
            if not artifact:
                raise AIServiceError("FSD artifact contract was not found")

            def report(message: str, percent: int) -> None:
                update_artifact_job(project_id, "fsd", stage="Generating combined FSD", progress=percent, message=message)

            cached = fsd_cached_document(project, artifact)
            usage = None
            if cached:
                document = cached
                update_artifact_job(project_id, "fsd", stage="Using cached functional design", progress=82,
                                    message="Approved baseline and template are unchanged; skipped the OpenAI request")
            else:
                model_started = time.perf_counter()
                document, usage = build_functional_specification(project, report)
                update_artifact_job(project_id, "fsd", stage="Expanding approved baseline", progress=88,
                                    message=f"Compact model design completed in {time.perf_counter() - model_started:.1f}s; expanding full coverage locally")
            update_artifact_job(project_id, "fsd", stage="Validating functional design", progress=91,
                                message="Checking schema, requirement coverage, evidence and traceability")
            document, validation = validate_fsd_document(document, project)
            previous_generation = artifact.payload.get("generation", {}) if cached else {}
            generation = fsd_generation_metadata(
                project, usage, cache_hit=bool(cached),
                model_override=previous_generation.get("model") if cached else None,
                duration_seconds=time.perf_counter() - started,
            )
            # Persist the validated document before file rendering. If rendering
            # fails, Retry can reuse this cache instead of paying for another AI call.
            artifact.payload = {**artifact.payload, "document": document, "generation": generation,
                                "validation": validation, "timings": timings, "render_pending": True, "error": None}
            db.commit()
            update_artifact_job(project_id, "fsd", stage="Rendering document and diagrams", progress=93,
                                message="Creating process flow, screen navigation, and screen wireframes")
            render_started = time.perf_counter()
            files = export_fsd_files(document, business_project_name(project), project.id, settings.artifact_dir)
            update_artifact_job(project_id, "fsd", stage="Finalizing downloads", progress=98,
                                message=f"DOCX and PDF files rendered in {time.perf_counter() - render_started:.1f}s")
            artifact.status = "generated"
            artifact.payload = {**artifact.payload, "message": "Generated from the approved requirement baseline.",
                                "document": document, "usage": usage.as_dict() if usage else None,
                                "generation": generation, "validation": validation,
                                "timings": timings,
                                "render_pending": False,
                                "downloads": {
                                    "docx": f"/api/projects/{project_id}/artifacts/fsd/download/docx",
                                    "pdf": f"/api/projects/{project_id}/artifacts/fsd/download/pdf",
                                },
                                "figures": {"process_flow": Path(files["process_image"]).name if files["process_image"] else None,
                                            "screen_navigation": Path(files["navigation_image"]).name if files["navigation_image"] else None}}
            save_usage(db, project_id, "fsd_generation", usage)
            db.commit()
            usage_message = f" Token usage: {usage.total_tokens}." if usage else " OpenAI request skipped by cache."
            update_artifact_job(project_id, "fsd", status="completed", stage="Functional design ready", progress=100,
                                message=f"FSD generated in {time.perf_counter() - started:.1f}s with screens, flows, tests, and traceability.{usage_message}")
        except Exception as exc:
            db.rollback()
            safe_error = str(exc)
            try:
                project = load_project(db, project_id)
                artifact = next((a for a in project.artifacts if a.kind == "fsd"), None)
                if artifact:
                    artifact.status = "failed"
                    artifact.payload = {**artifact.payload, "message": "FSD generation failed.", "error": safe_error,
                                        "timings": timings,
                                        **({"validation": exc.report} if isinstance(exc, FSDValidationError) else {})}
                    db.commit()
            except Exception:
                db.rollback()
            update_artifact_job(project_id, "fsd", status="failed", stage="FSD generation failed", progress=100,
                                message=f"FSD generation failed: {safe_error}", level="error", error=safe_error)
            logger.exception("Background FSD generation failed for project %s", project_id)
        finally:
            stop_timing_session(timing_token)


def queue_fsd_generation(project_id: str, db: Session, background_tasks: BackgroundTasks, force: bool = False) -> Project:
    project = load_project(db, project_id)
    artifact = next((a for a in project.artifacts if a.kind == "fsd"), None)
    if not artifact:
        raise HTTPException(404, "FSD artifact contract was not found")
    key = f"{project_id}:fsd"
    if not force and artifact.status == "generated" and fsd_cached_document(project, artifact):
        with job_lock:
            artifact_jobs[key] = {"project_id": project_id, "kind": "fsd", "status": "completed",
                "stage": "Functional design ready", "progress": 100, "error": None,
                "timings": artifact.payload.get("timings", []),
                "logs": [{"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "level": "info",
                          "message": "Cache hit: approved baseline and FSD template are unchanged; existing downloads reused"}]}
        return project
    with job_lock:
        current = artifact_jobs.get(key)
        if current and current["status"] == "processing":
            return project
        artifact_jobs[key] = {"project_id": project_id, "kind": "fsd", "status": "processing",
            "stage": "Queued", "progress": 5, "error": None, "timings": [],
            "logs": [{"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "level": "info",
                      "message": "FSD generation queued automatically after baseline approval"}]}
    artifact.status = "generating"
    artifact.payload = {**artifact.payload, "message": "Generating the combined FSD from approved requirements..."}
    db.commit()
    background_tasks.add_task(process_fsd_generation, project_id)
    logger.info("[project %s] [fsd] Generation queued", project_id)
    return load_project(db, project_id)


@app.get("/health")
def health():
    template = get_fsd_template()
    return {"status": "ok", "ai_mode": "openai" if settings.openai_api_key else "demo",
            "brd_model": settings.openai_brd_model if settings.openai_api_key else None,
            "requirements_model": settings.openai_requirements_model if settings.openai_api_key else None,
            "fsd_model": settings.openai_fsd_model if settings.openai_api_key else None,
            "fsd_pipeline": "brd_knowledge_plus_approved_requirements_plus_local_expansion",
            "fsd_max_output_tokens": settings.openai_fsd_max_output_tokens,
            "fsd_timeout_seconds": settings.openai_fsd_timeout_seconds,
            "fsd_template_version": template.template_version, "fsd_schema_version": template.schema_version}


@app.post("/api/projects", response_model=ProjectOut)
async def create_project(name: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    project, chunks, stored = await persist_project_upload(name, file, db)
    try:
        # Analyze the original BRD once so later agents reuse durable context.
        if settings.openai_api_key:
            brd_knowledge, brd_usage, input_mode = await run_in_threadpool(
                extract_brd_knowledge,
                stored, project.document.filename,
                [{"id": c.id, "page": c.page, "locator": c.locator, "text": c.text} for c in chunks],
            )
            db.add(BRDKnowledge(
                project_id=project.id, extraction_version="brd-knowledge-v1", model=settings.openai_brd_model,
                input_mode=input_mode, source_sha256=hashlib.sha256(stored.read_bytes()).hexdigest(),
                coverage_percent=100.0, payload=brd_knowledge.model_dump(),
            ))
            save_usage(db, project.id, "brd_knowledge_extraction", brd_usage)
        # The OpenAI SDK is synchronous. Keep it off the event loop so health
        # checks and other requests still work during requirement extraction.
        requirements, usage = await run_in_threadpool(
            extract_requirements,
            [{"id": c.id, "page": c.page, "locator": c.locator, "text": c.text} for c in chunks],
        )
    except AIServiceError as exc:
        logger.error("Requirement extraction failed for project %s: %s", project.id, exc)
        db.rollback()
        failed_project = db.get(Project, project.id)
        if failed_project:
            db.delete(failed_project)
            db.commit()
        stored.unlink(missing_ok=True)
        raise HTTPException(502, str(exc)) from exc
    db.add_all([Requirement(project_id=project.id, requirement_key=f"REQ-{i:03}", **item.model_dump()) for i, item in enumerate(requirements, 1)])
    save_usage(db, project.id, "requirements_extraction", usage)
    try:
        db.commit()
    except OperationalError as exc:
        db.rollback()
        raise database_busy(exc) from exc
    return serialize(load_project(db, project.id))


@app.post("/api/projects/start", status_code=202)
async def start_project_analysis(background_tasks: BackgroundTasks, name: str = Form(...),
                                 file: UploadFile = File(...), db: Session = Depends(get_db)):
    project, chunks, _stored = await persist_project_upload(name, file, db)
    with job_lock:
        processing_jobs[project.id] = {"project_id": project.id, "status": "processing",
            "stage": "Document extracted", "progress": 10, "error": None,
            "logs": [{"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "level": "info",
                      "message": f"POST /api/projects/start accepted — {file.filename}, {len(chunks)} chunks"}]}
    logger.info("[project %s] POST /api/projects/start accepted; scheduling background extraction", project.id)
    background_tasks.add_task(process_project_requirements, project.id)
    return {"project_id": project.id, "status": "processing", "status_url": f"/api/projects/{project.id}/processing-status"}


@app.get("/api/projects/{project_id}/processing-status")
def project_processing_status(project_id: str, db: Session = Depends(get_db)):
    with job_lock:
        job = processing_jobs.get(project_id)
        if job:
            return {**job, "logs": list(job["logs"])}
    project = load_project(db, project_id)
    if project.requirements:
        return {"project_id": project_id, "status": "completed", "stage": "Ready for human review",
                "progress": 100, "error": None, "logs": []}
    return {"project_id": project_id, "status": "unknown", "stage": "No active worker", "progress": 0,
            "error": "The server restarted while this job was running. Please start the analysis again.", "logs": []}


@app.get("/api/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    return serialize(load_project(db, project_id))


@app.get("/api/projects/{project_id}/brd-knowledge")
def get_brd_knowledge(project_id: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    knowledge = project.brd_knowledge
    if not knowledge:
        raise HTTPException(404, "No persisted BRD knowledge is available for this project")
    return {
        "project_id": project_id,
        "extraction_version": knowledge.extraction_version,
        "model": knowledge.model,
        "input_mode": knowledge.input_mode,
        "coverage_percent": knowledge.coverage_percent,
        "source_sha256": knowledge.source_sha256,
        "payload": knowledge.payload,
    }


@app.get("/api/projects/{project_id}/usage")
def get_project_usage(project_id: str, db: Session = Depends(get_db)):
    load_project(db, project_id)
    events = db.scalars(select(AIUsageEvent).where(AIUsageEvent.project_id == project_id).order_by(AIUsageEvent.created_at)).all()
    return {"project_id": project_id, "events": [{"call_type": e.call_type, "model": e.model, "input_tokens": e.input_tokens,
        "output_tokens": e.output_tokens, "total_tokens": e.total_tokens, "created_at": e.created_at} for e in events],
        "total_tokens": sum(e.total_tokens for e in events)}


@app.get("/api/usage")
def get_all_usage(db: Session = Depends(get_db)):
    events = db.scalars(select(AIUsageEvent).order_by(AIUsageEvent.created_at.desc())).all()
    return {"events": [{"project_id": e.project_id, "call_type": e.call_type, "model": e.model,
        "input_tokens": e.input_tokens, "output_tokens": e.output_tokens, "total_tokens": e.total_tokens,
        "created_at": e.created_at} for e in events], "total_tokens": sum(e.total_tokens for e in events)}


@app.patch("/api/requirements/{requirement_id}", response_model=ProjectOut)
def update_requirement(requirement_id: str, update: RequirementUpdate, db: Session = Depends(get_db)):
    req = db.get(Requirement, requirement_id)
    if not req:
        raise HTTPException(404, "Requirement not found")
    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(req, key, ReviewStatus(value) if key == "review_status" else value)
    db.commit()
    db.expire_all()
    logger.info("[project %s] Updated requirement %s (%s)", req.project_id, req.requirement_key, requirement_id)
    return serialize(load_project(db, req.project_id))


@app.post("/api/projects/{project_id}/requirements", response_model=ProjectOut)
def create_requirement(project_id: str, req_in: RequirementCreate, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    existing_keys = [r.requirement_key for r in project.requirements]
    max_num = 0
    prefix = "REQ"
    for k in existing_keys:
        match = re.search(r"(\d+)", k)
        if match:
            max_num = max(max_num, int(match.group(1)))
        if "-" in k:
            prefix = k.split("-")[0]
    next_key = f"{prefix}-{max_num + 1:03d}"

    new_req = Requirement(
        project_id=project_id,
        requirement_key=next_key,
        title=req_in.title,
        statement=req_in.statement,
        requirement_type=req_in.requirement_type,
        priority=req_in.priority,
        rationale=req_in.rationale or "",
        acceptance_criteria=req_in.acceptance_criteria or ["Requirement criteria verified"],
        assumptions=req_in.assumptions or [],
        source_chunk_ids=[],
        source_quote=req_in.source_quote or "Manually specified requirement",
        confidence=1.0,
        review_status=ReviewStatus(req_in.review_status),
        reviewer_note=req_in.reviewer_note or "",
    )
    db.add(new_req)
    db.commit()
    db.expire_all()
    logger.info("[project %s] Added new requirement %s: %s", project_id, next_key, req_in.title)
    return serialize(load_project(db, project_id))


@app.delete("/api/requirements/{requirement_id}", response_model=ProjectOut)
def delete_requirement(requirement_id: str, db: Session = Depends(get_db)):
    req = db.get(Requirement, requirement_id)
    if not req:
        raise HTTPException(404, "Requirement not found")
    project_id = req.project_id
    db.delete(req)
    db.commit()
    db.expire_all()
    logger.info("[project %s] Deleted requirement %s (%s)", project_id, req.requirement_key, requirement_id)
    return serialize(load_project(db, project_id))


@app.post("/api/projects/{project_id}/requirements/approve-all", response_model=ProjectOut)
def approve_all_requirements(project_id: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    if project.status == ProjectStatus.approved:
        raise HTTPException(409, "The requirement baseline is already approved")
    if not project.requirements:
        raise HTTPException(409, "No requirements are available for review")
    for requirement in project.requirements:
        requirement.review_status = ReviewStatus.approved
    db.commit()
    db.expire_all()
    logger.info("[project %s] Human reviewer approved all %s requirements", project_id, len(project.requirements))
    return serialize(load_project(db, project_id))


@app.post("/api/projects/{project_id}/approve", response_model=ProjectOut)
def approve_project(project_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    accepted = [r for r in project.requirements if r.review_status == ReviewStatus.approved]
    pending = [r for r in project.requirements if r.review_status == ReviewStatus.pending]
    if pending or not accepted:
        raise HTTPException(409, "Review every requirement and approve at least one before baselining")
    project.status = ProjectStatus.approved
    existing = {a.kind for a in project.artifacts}
    for kind, meta in AGENT_CAPABILITIES.items():
        if kind not in existing:
            db.add(Artifact(project_id=project.id, kind=kind, payload={"label": meta["label"], "agent": meta["agent"], "message": "Ready for the next implementation slice."}))
    db.commit()
    db.expire_all()
    return serialize(queue_fsd_generation(project_id, db, background_tasks))


@app.post("/api/projects/{project_id}/artifacts/fsd/start", response_model=ProjectOut, status_code=202)
def start_fsd_generation(project_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    if project.status != ProjectStatus.approved:
        raise HTTPException(409, "Approve the requirement baseline first")
    # This route is an explicit user action (Generate / Regenerate). Bypass the
    # cache so Regenerate always starts a fresh background job. Automatic FSD
    # generation after baseline approval still uses the cache-aware default.
    return serialize(queue_fsd_generation(project_id, db, background_tasks, force=True))


@app.get("/api/projects/{project_id}/artifacts/fsd/processing-status")
def fsd_processing_status(project_id: str, db: Session = Depends(get_db)):
    key = f"{project_id}:fsd"
    with job_lock:
        job = artifact_jobs.get(key)
        if job:
            return {**job, "logs": list(job["logs"])}
    project = load_project(db, project_id)
    artifact = next((a for a in project.artifacts if a.kind == "fsd"), None)
    if not artifact:
        raise HTTPException(404, "FSD artifact contract was not found")
    if artifact.status == "generated":
        return {"project_id": project_id, "kind": "fsd", "status": "completed",
                "stage": "Functional design ready", "progress": 100, "error": None, "logs": [],
                "timings": artifact.payload.get("timings", [])}
    if artifact.status == "failed":
        return {"project_id": project_id, "kind": "fsd", "status": "failed",
                "stage": "FSD generation failed", "progress": 100,
                "error": artifact.payload.get("error", "FSD generation failed"), "logs": [],
                "timings": artifact.payload.get("timings", [])}
    return {"project_id": project_id, "kind": "fsd", "status": "unknown", "stage": "No active worker",
            "progress": 0, "error": "The server restarted during FSD generation. Click Retry to start it again.", "logs": [], "timings": []}


@app.get("/api/projects/{project_id}/artifacts/fsd/download/{file_format}")
def download_fsd(project_id: str, file_format: str, db: Session = Depends(get_db)):
    if file_format not in {"docx", "pdf"}:
        raise HTTPException(404, "Download format must be docx or pdf")
    project = load_project(db, project_id)
    artifact = next((a for a in project.artifacts if a.kind == "fsd"), None)
    if not artifact or artifact.status != "generated":
        raise HTTPException(409, "Generate the FSD before downloading it")
    candidates = sorted((Path(settings.artifact_dir) / project_id).glob(f"*-functional-specification.{file_format}"))
    if not candidates and isinstance(artifact.payload.get("document"), dict):
        try:
            export_fsd_files(artifact.payload["document"], business_project_name(project), project.id, settings.artifact_dir)
            candidates = sorted((Path(settings.artifact_dir) / project_id).glob(f"*-functional-specification.{file_format}"))
        except Exception as exc:
            logger.exception("On-demand FSD export failed for project %s", project_id)
            raise HTTPException(500, f"The FSD is visible, but the download file could not be created: {exc}") from exc
    if not candidates:
        raise HTTPException(404, f"The generated {file_format.upper()} file was not found. Regenerate the FSD.")
    media_type = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  if file_format == "docx" else "application/pdf")
    return FileResponse(candidates[0], media_type=media_type, filename=candidates[0].name)


@app.get("/api/projects/{project_id}/artifacts/backlog/download/xlsx")
def download_sprint_plan(project_id: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    artifact = next((a for a in project.artifacts if a.kind == "backlog"), None)
    if not artifact or artifact.status != "generated" or not isinstance(artifact.payload.get("document"), dict):
        raise HTTPException(409, "Generate the sprint plan before downloading Excel")
    candidates = sorted((Path(settings.artifact_dir) / project_id).glob("*-sprint-plan.xlsx"))
    if not candidates:
        try:
            export_sprint_plan(artifact.payload["document"], business_project_name(project), project.id, settings.artifact_dir)
            candidates = sorted((Path(settings.artifact_dir) / project_id).glob("*-sprint-plan.xlsx"))
        except Exception as exc:
            logger.exception("On-demand sprint-plan export failed for project %s", project_id)
            raise HTTPException(500, f"The sprint plan is visible, but the Excel file could not be created: {exc}") from exc
    if not candidates:
        raise HTTPException(404, "The sprint-plan Excel file was not found. Regenerate Project Planning.")
    return FileResponse(candidates[0], media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        filename=candidates[0].name)


@app.get("/api/projects/{project_id}/artifacts/technical_design/download/{file_format}")
def download_technical_design(project_id: str, file_format: str, db: Session = Depends(get_db)):
    if file_format not in {"docx", "pdf"}:
        raise HTTPException(404, "Download format must be docx or pdf")
    project = load_project(db, project_id)
    artifact = next((a for a in project.artifacts if a.kind == "technical_design"), None)
    if not artifact or artifact.status != "generated" or not isinstance(artifact.payload.get("document"), dict):
        raise HTTPException(409, "Generate the Technical Design before downloading it")
    candidates = sorted((Path(settings.artifact_dir) / project_id).glob(f"*-technical-design.{file_format}"))
    if not candidates:
        try:
            export_technical_design(artifact.payload["document"], business_project_name(project), project.id, settings.artifact_dir)
            candidates = sorted((Path(settings.artifact_dir) / project_id).glob(f"*-technical-design.{file_format}"))
        except Exception as exc:
            logger.exception("On-demand TDD export failed for project %s", project_id)
            raise HTTPException(500, f"The TDD is visible, but the {file_format.upper()} file could not be created: {exc}") from exc
    if not candidates:
        raise HTTPException(404, f"The Technical Design {file_format.upper()} was not found. Regenerate Technical Design.")
    media_type = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  if file_format == "docx" else "application/pdf")
    return FileResponse(candidates[0], media_type=media_type, filename=candidates[0].name)


@app.get("/api/projects/{project_id}/artifacts/test_cases/download/xlsx")
def download_quality_tests(project_id: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    artifact = next((a for a in project.artifacts if a.kind == "test_cases"), None)
    if not artifact or artifact.status != "generated" or not isinstance(artifact.payload.get("document"), dict):
        raise HTTPException(409, "Generate Quality & Testing before downloading Excel")
    candidates = sorted((Path(settings.artifact_dir) / project_id).glob("*-quality-test-pack.xlsx"))
    if not candidates:
        try:
            export_quality_tests(artifact.payload["document"], business_project_name(project), project.id, settings.artifact_dir)
            candidates = sorted((Path(settings.artifact_dir) / project_id).glob("*-quality-test-pack.xlsx"))
        except Exception as exc:
            logger.exception("On-demand quality-test export failed for project %s", project_id)
            raise HTTPException(500, f"The test pack is visible, but the Excel file could not be created: {exc}") from exc
    if not candidates:
        raise HTTPException(404, "The Quality Test Excel file was not found. Regenerate Quality & Testing.")
    return FileResponse(candidates[0], media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=candidates[0].name)


@app.post("/api/projects/{project_id}/artifacts/technical_design/starter-code", response_model=ProjectOut)
def generate_starter_code(project_id: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    if project.status != ProjectStatus.approved:
        raise HTTPException(409, "Approve the requirement baseline before generating starter code")
    artifact = next((a for a in project.artifacts if a.kind == "technical_design"), None)
    if not artifact:
        raise HTTPException(404, "Technical Design artifact contract was not found")
    try:
        metadata = build_starter_code_zip(project, settings.artifact_dir)
        artifact.payload = {**artifact.payload, "starter_code": metadata}
        db.commit(); db.expire_all()
        logger.info("[project %s] Generated Fiori/ABAP starter-code ZIP with %s files",
                    project_id, metadata["file_count"])
        return serialize(load_project(db, project_id))
    except Exception as exc:
        db.rollback()
        logger.exception("Starter-code generation failed for project %s", project_id)
        raise HTTPException(500, f"Starter-code generation failed: {exc}") from exc


@app.post("/api/projects/{project_id}/artifacts/backlog/resource-distribution", response_model=ProjectOut)
def generate_resource_distribution(project_id: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    if project.status != ProjectStatus.approved:
        raise HTTPException(409, "Approve the requirement baseline before suggesting resource distribution")
    artifact = next((a for a in project.artifacts if a.kind == "backlog"), None)
    if not artifact:
        raise HTTPException(404, "Project Planning artifact contract was not found")
    try:
        payload = dict(artifact.payload or {})
        suggestion = suggest_resource_distribution(project)
        try:
            export_resource_distribution(suggestion, project.id, settings.artifact_dir)
        except Exception:
            logger.exception("Resource-distribution Excel export failed for project %s; keeping on-screen suggestion",
                             project_id)
        downloads = payload.get("downloads") if isinstance(payload.get("downloads"), dict) else {}
        artifact.payload = {**payload, "resource_distribution": suggestion,
                            "downloads": {**downloads,
                                          "xlsx": f"/api/projects/{project_id}/artifacts/backlog/download/xlsx",
                                          "resources_xlsx": f"/api/projects/{project_id}/artifacts/backlog/resource-distribution/xlsx"}}
        flag_modified(artifact, "payload")
        db.commit(); db.expire_all()
        logger.info("[project %s] Suggested %s resources for Project Planning",
                    project_id, suggestion["total_resources"])
        return serialize(load_project(db, project_id))
    except Exception as exc:
        db.rollback()
        logger.exception("Resource-distribution suggestion failed for project %s", project_id)
        raise HTTPException(500, f"Resource distribution suggestion failed: {exc}") from exc


@app.get("/api/projects/{project_id}/artifacts/backlog/resource-distribution/xlsx")
def download_resource_distribution(project_id: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    artifact = next((a for a in project.artifacts if a.kind == "backlog"), None)
    payload = dict(artifact.payload or {}) if artifact and isinstance(artifact.payload, dict) else {}
    suggestion = payload.get("resource_distribution")
    if not isinstance(suggestion, dict) or not suggestion.get("people"):
        if project.status != ProjectStatus.approved:
            raise HTTPException(409, "Approve the requirement baseline before downloading resource distribution")
        if not artifact:
            raise HTTPException(404, "Project Planning artifact contract was not found")
        suggestion = suggest_resource_distribution(project)
        artifact.payload = {**payload, "resource_distribution": suggestion}
        flag_modified(artifact, "payload")
        db.commit()
    candidates = sorted((Path(settings.artifact_dir) / project_id).glob("*-resource-distribution.xlsx"))
    if not candidates:
        try:
            export_resource_distribution(suggestion, project.id, settings.artifact_dir)
            candidates = sorted((Path(settings.artifact_dir) / project_id).glob("*-resource-distribution.xlsx"))
        except Exception as exc:
            logger.exception("On-demand resource-distribution export failed for project %s", project_id)
            raise HTTPException(500, f"The resource list is visible, but the Excel file could not be created: {exc}") from exc
    if not candidates:
        raise HTTPException(404, "The resource-distribution Excel file was not found. Suggest resources again.")
    return FileResponse(candidates[0], media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        filename=candidates[0].name)


@app.get("/api/projects/{project_id}/artifacts/backlog/download/jira-csv")
def download_jira_csv(project_id: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    if project.status != ProjectStatus.approved:
        raise HTTPException(409, "Approve the requirement baseline before downloading Jira CSV")
    csv_content = export_jira_csv(project)
    slug = _slug(project.name)
    filename = f"{slug}-jira-import.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/projects/{project_id}/artifacts/backlog/jira/config", response_model=JiraConfigStatusOut)
def get_jira_config(project_id: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    cfg = get_settings()
    has_token = bool(cfg.jira_api_token and cfg.jira_api_token.strip())
    is_configured = bool(cfg.jira_url and cfg.jira_email and has_token)

    suggested_key = cfg.jira_project_key
    if not suggested_key or suggested_key in {"AUTO", "NEW"}:
        suggested_key = _generate_jira_project_key(business_project_name(project))

    return JiraConfigStatusOut(
        configured_in_env=is_configured,
        jira_url=cfg.jira_url or "",
        jira_email=cfg.jira_email or "",
        has_api_token=has_token,
        suggested_project_key=suggested_key,
    )


@app.post("/api/projects/{project_id}/artifacts/backlog/jira/test-connection", response_model=JiraTestConnectionOut)

def test_jira_connection(project_id: str, config: JiraConfigIn | None = None, db: Session = Depends(get_db)):
    load_project(db, project_id)
    cfg = config or JiraConfigIn()
    try:
        client = JiraClient(
            url=cfg.jira_url,
            email=cfg.jira_email,
            api_token=cfg.jira_api_token,
            project_key=cfg.jira_project_key,
        )
        res = client.test_connection()
        return JiraTestConnectionOut(**res)
    except Exception as e:
        return JiraTestConnectionOut(
            success=False,
            message=f"Connection failed: {e}",
            project_key=cfg.jira_project_key,
        )


@app.post("/api/projects/{project_id}/artifacts/backlog/jira/sync", response_model=JiraSyncResultOut)
def sync_jira_backlog(project_id: str, req: JiraSyncIn | None = None, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    if project.status != ProjectStatus.approved:
        raise HTTPException(409, "Approve the requirement baseline before syncing with Jira")
    r = req or JiraSyncIn()
    try:
        client = JiraClient(
            url=r.jira_url,
            email=r.jira_email,
            api_token=r.jira_api_token,
            project_key=r.jira_project_key,
        )
        result = client.sync_project_backlog(
            project,
            create_epic=r.create_epic,
            create_sprints=r.create_sprints,
        )
        artifact = next((a for a in project.artifacts if a.kind == "backlog"), None)
        if artifact:
            flag_modified(artifact, "payload")
            db.commit()
        return JiraSyncResultOut(**result)
    except Exception as e:
        logger.exception("Jira sync failed for project %s", project_id)
        raise HTTPException(400, f"Jira synchronization failed: {e}")


@app.get("/api/projects/{project_id}/artifacts/test_cases/download/jira-csv")
def download_test_cases_jira_csv(project_id: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    if project.status != ProjectStatus.approved:
        raise HTTPException(409, "Approve the requirement baseline before downloading Jira Test CSV")
    csv_content = export_jira_test_cases_csv(project)
    slug = _slug(project.name)
    filename = f"{slug}-jira-quality-tests.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/projects/{project_id}/artifacts/test_cases/jira/sync", response_model=JiraSyncResultOut)
def sync_jira_test_cases(project_id: str, req: JiraSyncIn | None = None, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    if project.status != ProjectStatus.approved:
        raise HTTPException(409, "Approve the requirement baseline before syncing with Jira")
    r = req or JiraSyncIn()
    try:
        client = JiraClient(
            url=r.jira_url,
            email=r.jira_email,
            api_token=r.jira_api_token,
            project_key=r.jira_project_key,
        )
        result = client.sync_project_test_cases(
            project,
            create_epic=r.create_epic,
        )
        artifact = next((a for a in project.artifacts if a.kind == "test_cases"), None)
        if artifact:
            flag_modified(artifact, "payload")
            db.commit()
        return JiraSyncResultOut(
            success=result.get("success", True),
            message=result.get("message", "Test cases synchronized to Jira"),
            jira_url=result.get("jira_url", client.url),
            project_key=result.get("project_key", client.project_key),
            epic_key=result.get("epic_key"),
            epic_url=result.get("epic_url"),
            stories_created=result.get("tests_created", 0),
            board_url=result.get("board_url"),
            synced_stories=result.get("synced_tests", []),
        )
    except Exception as e:
        logger.exception("Jira test cases sync failed for project %s", project_id)
        raise HTTPException(400, f"Jira test cases synchronization failed: {e}")


@app.get("/api/projects/{project_id}/artifacts/technical_design/starter-code/download")

def download_starter_code(project_id: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    artifact = next((a for a in project.artifacts if a.kind == "technical_design"), None)
    metadata = artifact.payload.get("starter_code") if artifact else None
    if not isinstance(metadata, dict) or metadata.get("status") != "generated":
        raise HTTPException(409, "Generate starter code before downloading the ZIP")
    candidates = sorted((Path(settings.artifact_dir) / project_id).glob("*-sap-starter-code.zip"))
    if not candidates:
        try:
            build_starter_code_zip(project, settings.artifact_dir)
            candidates = sorted((Path(settings.artifact_dir) / project_id).glob("*-sap-starter-code.zip"))
        except Exception as exc:
            logger.exception("On-demand starter-code ZIP generation failed for project %s", project_id)
            raise HTTPException(500, f"The starter-code ZIP could not be created: {exc}") from exc
    if not candidates:
        raise HTTPException(404, "The starter-code ZIP was not found. Generate it again.")
    return FileResponse(candidates[0], media_type="application/zip", filename=candidates[0].name)


@app.get("/api/projects/{project_id}/companion", response_model=CompanionContextOut)
def get_companion(project_id: str, db: Session = Depends(get_db)):
    return companion_context(load_project(db, project_id))


@app.post("/api/projects/{project_id}/companion/ask", response_model=CompanionAnswerOut)
def ask_companion(project_id: str, body: CompanionAsk, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    try:
        turn = answer_companion_question(project, body.question)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    store_companion_turn(project, turn)
    db.commit()
    return turn


@app.post("/api/projects/{project_id}/artifacts/{kind}", response_model=ProjectOut)
def generate_placeholder(project_id: str, kind: str, db: Session = Depends(get_db)):
    project = load_project(db, project_id)
    if project.status != ProjectStatus.approved: raise HTTPException(409, "Approve the requirement baseline first")
    if kind not in AGENT_CAPABILITIES: raise HTTPException(404, "Unknown capability")
    artifact = next((a for a in project.artifacts if a.kind == kind), None)
    if artifact:
        try:
            if kind == "fsd":
                started = time.perf_counter()
                cached = fsd_cached_document(project, artifact)
                document, usage = (cached, None) if cached else build_functional_specification(project)
                document, validation = validate_fsd_document(document, project)
                export_fsd_files(document, business_project_name(project), project.id, settings.artifact_dir)
                save_usage(db, project.id, "fsd_generation", usage)
                previous_generation = artifact.payload.get("generation", {}) if cached else {}
                generation = fsd_generation_metadata(
                    project, usage, cache_hit=bool(cached),
                    model_override=previous_generation.get("model") if cached else None,
                    duration_seconds=time.perf_counter() - started,
                )
            else:
                document, usage = BUILDERS[kind](project), None
                if kind == "backlog":
                    export_sprint_plan(document, business_project_name(project), project.id, settings.artifact_dir)
                elif kind == "technical_design":
                    export_technical_design(document, business_project_name(project), project.id, settings.artifact_dir)
                elif kind == "test_cases":
                    export_quality_tests(document, business_project_name(project), project.id, settings.artifact_dir)
            artifact.status = "generated"
            payload = dict(artifact.payload or {})
            artifact.payload = {**payload, "message": "Generated from the approved requirement baseline.", "document": document,
                                "usage": usage.as_dict() if usage else None,
                                **({"generation": generation, "validation": validation, "render_pending": False} if kind == "fsd" else {}),
                                **({"downloads": {
                                    "docx": f"/api/projects/{project_id}/artifacts/fsd/download/docx",
                                    "pdf": f"/api/projects/{project_id}/artifacts/fsd/download/pdf",
                                }} if kind == "fsd" else {"downloads": {
                                    "xlsx": f"/api/projects/{project_id}/artifacts/backlog/download/xlsx",
                                    "resources_xlsx": f"/api/projects/{project_id}/artifacts/backlog/resource-distribution/xlsx",
                                }} if kind == "backlog" else {"downloads": {
                                    "docx": f"/api/projects/{project_id}/artifacts/technical_design/download/docx",
                                    "pdf": f"/api/projects/{project_id}/artifacts/technical_design/download/pdf",
                                }} if kind == "technical_design" else {"downloads": {
                                    "xlsx": f"/api/projects/{project_id}/artifacts/test_cases/download/xlsx",
                                }} if kind == "test_cases" else {})}
        except AIServiceError as exc:
            logger.error("Artifact generation failed for project %s (%s): %s", project.id, kind, exc)
            db.rollback()
            raise HTTPException(502, str(exc)) from exc
        except Exception as exc:
            logger.exception("Artifact generation failed for project %s (%s)", project.id, kind)
            db.rollback()
            raise HTTPException(500, f"{AGENT_CAPABILITIES[kind]['label']} generation failed: {exc}") from exc
    db.commit()
    db.expire_all()
    return serialize(load_project(db, project_id))
