from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openai import OpenAI, OpenAIError

from ..brd_schemas import BRDKnowledgeBase
from ..config import settings
from .openai_support import AIServiceError, Usage, response_usage


BRD_EXTRACTION_PROMPT = """You are the BRD Understanding capability for an SAP delivery copilot.
Convert the entire supplied Business Requirements Document into the requested structured BRD knowledge model.

Grounding and coverage rules:
- The supplied BRD is the only source of project facts.
- Read all available text, tables, diagrams, architecture figures, captions, SAP Fiori mockups, business rules, messages, acceptance criteria, tests, assumptions, dependencies, risks and reference tables.
- Preserve explicit BRD IDs (for example BR-001, IR-001, BRULE-001, AC-001, BT-001) exactly when present.
- Preserve SAP and business terminology exactly enough that a later FSD agent can trace back to the BRD.
- Do not invent SAP modules, applications, APIs, CDS views, OData entities, tables, fields, roles, authorization objects, destinations, workflows, thresholds, configuration values, owners or dates.
- If a fact is not provided, use "TBD" for scalar text or an empty list for a collection.
- Keep registration, qualification, risk, supplier status and integration status as distinct concepts when the BRD distinguishes them.
- Extract every distinct Fiori screen/mockup described by the BRD. Do not merge screens merely to reduce output size.
- For evidence, use the source page number when it is visible/known, a section heading, and a short verbatim quote. If page number is unknown, use 0.
- Open questions must represent actual gaps or design decisions that remain unresolved; do not turn assumptions into facts.
- Do not generate an FSD. Only extract and normalize BRD knowledge for downstream use.
"""


def _chunk_fallback_input(chunks: list[dict[str, Any]]) -> str:
    """Build a complete text fallback without silently truncating document coverage."""
    rows = [
        {
            "id": str(chunk.get("id", "")),
            "page": int(chunk.get("page", 0) or 0),
            "locator": str(chunk.get("locator", "")),
            "text": str(chunk.get("text", "")),
        }
        for chunk in chunks
        if str(chunk.get("text", "")).strip()
    ]
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))


def _parse_with_file(client: OpenAI, source_path: Path, filename: str):
    uploaded = None
    try:
        with source_path.open("rb") as handle:
            uploaded = client.files.create(file=(filename, handle), purpose="user_data")
        return client.responses.parse(
            model=settings.openai_brd_model,
            instructions=BRD_EXTRACTION_PROMPT,
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_file", "file_id": uploaded.id},
                    {"type": "input_text", "text": (
                        "Analyze the complete uploaded BRD and populate the structured BRD knowledge model. "
                        "Use visual information from PDF pages when available. Return only grounded document knowledge."
                    )},
                ],
            }],
            text_format=BRDKnowledgeBase,
            max_output_tokens=settings.openai_brd_max_output_tokens,
            reasoning={"effort": settings.openai_brd_reasoning_effort},
            text={"verbosity": "low"},
            store=False,
            prompt_cache_key="sap-copilot-brd-knowledge-v1",
        )
    finally:
        if uploaded is not None:
            try:
                client.files.delete(uploaded.id)
            except Exception:
                # The extraction result is more important than cleanup; uploaded
                # user_data can still be removed later from the OpenAI project.
                pass


def _parse_with_chunks(client: OpenAI, filename: str, chunks: list[dict[str, Any]]):
    return client.responses.parse(
        model=settings.openai_brd_model,
        instructions=BRD_EXTRACTION_PROMPT,
        input=(
            f"SOURCE DOCUMENT: {filename}\n"
            "The following JSON contains every locally extracted BRD chunk in source order. "
            "Analyze all chunks; do not stop early.\nBRD CHUNKS JSON:\n"
            + _chunk_fallback_input(chunks)
        ),
        text_format=BRDKnowledgeBase,
        max_output_tokens=settings.openai_brd_max_output_tokens,
        reasoning={"effort": settings.openai_brd_reasoning_effort},
        text={"verbosity": "low"},
        store=False,
        prompt_cache_key="sap-copilot-brd-knowledge-v1",
    )


def extract_brd_knowledge(source_path: str | Path, filename: str,
                          chunks: list[dict[str, Any]] | None = None) -> tuple[BRDKnowledgeBase, Usage, str]:
    """Extract the full BRD once so later FSD calls can reuse durable context.

    Returns ``(knowledge, usage, input_mode)`` where input_mode is either
    ``file`` (preferred because PDFs include page imagery) or ``chunks``.
    """
    if not settings.openai_api_key:
        raise AIServiceError("BRD knowledge extraction requires OPENAI_API_KEY")

    path = Path(source_path)
    if not path.exists():
        raise AIServiceError(f"BRD source file was not found: {path}")

    client = OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_brd_timeout_seconds,
        max_retries=settings.openai_brd_max_retries,
    )

    response = None
    input_mode = "file"
    try:
        if settings.openai_brd_use_file_input:
            try:
                response = _parse_with_file(client, path, filename)
            except (OpenAIError, ValueError) as exc:
                if not chunks:
                    raise
                input_mode = "chunks"
                response = _parse_with_chunks(client, filename, chunks)
        else:
            input_mode = "chunks"
            response = _parse_with_chunks(client, filename, chunks or [])
    except (OpenAIError, ValueError) as exc:
        raise AIServiceError(f"BRD knowledge extraction failed: {exc}") from exc

    if response is None or not response.output_parsed:
        raise AIServiceError("OpenAI returned no parsed BRD knowledge output")

    return (
        response.output_parsed,
        response_usage(response, settings.openai_brd_model),
        input_mode,
    )
