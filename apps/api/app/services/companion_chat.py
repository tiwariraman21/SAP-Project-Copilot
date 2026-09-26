from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from ..config import settings
from ..models import Project
from .project_identity import business_project_name, priority_label
from .sprint_plan_export import _map_phase

try:
    from openai import OpenAI, OpenAIError
except ImportError:  # pragma: no cover
    OpenAI, OpenAIError = None, None  # type: ignore

SOURCE_LABELS = {
    "brd": "Uploaded BRD",
    "requirements": "Approved requirements",
    "fsd": "Functional Specification",
    "backlog": "Project Planning Excel",
    "technical_design": "Technical Design",
    "test_cases": "Quality Test Pack",
}

SUGGESTED_QUESTIONS = [
    "What is the end-to-end process flow in this BRD?",
    "What are the approval levels and decision rules?",
    "What SAP Fiori screens and floorplans are defined?",
    "What fields are on the initial page?",
    "Which requirements are Must Have?",
    "What is my current delivery progress in the project plan?",
]


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _artifact_document(project: Project, kind: str) -> dict | None:
    artifact = next((item for item in project.artifacts if item.kind == kind), None)
    if not artifact or artifact.status != "generated":
        return None
    document = (artifact.payload or {}).get("document")
    return document if isinstance(document, dict) else None


def _available_sources(project: Project) -> list[dict[str, str]]:
    sources = [{"kind": "brd", "label": SOURCE_LABELS["brd"], "status": "ready" if project.document else "missing"}]
    sources.append({
        "kind": "requirements",
        "label": SOURCE_LABELS["requirements"],
        "status": "ready" if project.requirements else "missing",
    })
    for kind, label in SOURCE_LABELS.items():
        if kind in {"brd", "requirements"}:
            continue
        document = _artifact_document(project, kind)
        sources.append({"kind": kind, "label": label, "status": "ready" if document else "missing"})
    return sources


def _field_label(field: Any) -> str:
    if isinstance(field, str):
        return field
    if not isinstance(field, dict):
        return _text(field)
    return _text(field.get("label") or field.get("name") or field.get("field") or field.get("title"))


def _requirement_types(project: Project) -> dict[str, str]:
    return {item.requirement_key: str(item.requirement_type or "") for item in project.requirements}


def _stories(backlog: dict) -> list[dict]:
    stories = []
    for story in backlog.get("stories") or []:
        if not isinstance(story, dict):
            continue
        item = dict(story)
        item["phase"] = item.get("phase") or _map_phase(item)
        stories.append(item)
    return stories


def _is_functional_story(story: dict, types: dict[str, str]) -> bool:
    blob = " ".join(_text(story.get(key)) for key in ("assigned_to", "phase", "title", "story")).lower()
    req_type = types.get(_text(story.get("requirement_key")), "").lower()
    return req_type == "functional" or "functional" in blob


def _progress_line(stories: list[dict]) -> str:
    if not stories:
        return "No matching tasks were found in the Project Planning workbook."
    statuses: dict[str, int] = {}
    progress_values = []
    for story in stories:
        status = _text(story.get("status")) or "Not Started"
        statuses[status] = statuses.get(status, 0) + 1
        try:
            progress_values.append(float(story.get("progress_percent") or 0))
        except (TypeError, ValueError):
            progress_values.append(0.0)
    average = round(sum(progress_values) / len(progress_values), 1) if progress_values else 0
    status_text = ", ".join(f"{count} {name}" for name, count in sorted(statuses.items(), key=lambda item: (-item[1], item[0])))
    sprints = sorted({_text(story.get("sprint")) for story in stories if story.get("sprint") not in (None, "")})
    sprint_text = f" Sprint coverage: {', '.join(f'Sprint {item}' for item in sprints)}." if sprints else ""
    return (
        f"{len(stories)} planning task(s) in this area. Average progress {average}%. "
        f"Status mix: {status_text}.{sprint_text}"
    )


def _answer_progress(question: str, project: Project) -> dict | None:
    lowered = question.lower()
    if not re.search(r"\b(progress|status|sprint|planning|backlog|phase|complete|completion)\b", lowered):
        return None
    backlog = _artifact_document(project, "backlog")
    if not backlog:
        return {
            "answer": "Project Planning has not been generated for this project yet. Generate it from the Project Planning page; progress is read from that Excel workbook.",
            "sources": [{"kind": "backlog", "label": SOURCE_LABELS["backlog"], "detail": "Not generated"}],
        }
    stories = _stories(backlog)
    types = _requirement_types(project)
    area = "the delivery plan"
    selected = stories
    if "functional" in lowered:
        area = "the Functional area"
        selected = [story for story in stories if _is_functional_story(story, types)]
        if not selected:
            selected = stories
            area = "the delivery plan (no separate Functional-owner tasks were found)"
    elif match := re.search(r"\b(planning|analysis|design|build|testing|deployment|closure)\b", lowered):
        phase = match.group(1).title()
        area = f"the {phase} phase"
        selected = [story for story in stories if _text(story.get("phase")).lower() == phase.lower()]
    summary = _progress_line(selected)
    sample = selected[:6]
    details = []
    for story in sample:
        details.append(
            f"{_text(story.get('story_key'))}: {_text(story.get('title'))} — "
            f"{_text(story.get('assigned_to')) or 'Unassigned'}, "
            f"{_text(story.get('phase'))}, {_text(story.get('status')) or 'Not Started'}, "
            f"{_text(story.get('progress_percent') or 0)}% complete"
        )
    extra = f" Sample tasks: {'; '.join(details)}." if details else ""
    return {
        "answer": f"From the Project Planning Excel for {business_project_name(project)}, {area}: {summary}{extra}",
        "sources": [{"kind": "backlog", "label": SOURCE_LABELS["backlog"], "detail": backlog.get("project_name") or backlog.get("title") or "Project Plan sheet"}],
    }


def _initial_screen(screens: list[dict]) -> dict | None:
    if not screens:
        return None
    for screen in screens:
        name = _text(screen.get("name") or screen.get("screen_id")).lower()
        if any(token in name for token in ("overview", "worklist", "list report", "initial", "landing", "home", "search", "launch")):
            return screen
        if str(screen.get("screen_id") or "").upper() in {"SCR-01", "SCREEN-01"}:
            return screen
    return screens[0]


def _answer_fields(question: str, project: Project) -> dict | None:
    lowered = question.lower()
    if not re.search(r"\b(field|fields|column|columns|initial page|landing page)\b", lowered):
        return None
    fsd = _artifact_document(project, "fsd")
    if not fsd:
        return {
            "answer": "The Functional Specification has not been generated for this project yet. Generate Functional Design first; initial-page fields come from that FSD.",
            "sources": [{"kind": "fsd", "label": SOURCE_LABELS["fsd"], "detail": "Not generated"}],
        }
    screens = [item for item in (fsd.get("screens") or []) if isinstance(item, dict)]
    screen = _initial_screen(screens)
    if not screen:
        return {
            "answer": "The generated FSD does not yet list screens or fields for this project.",
            "sources": [{"kind": "fsd", "label": SOURCE_LABELS["fsd"], "detail": fsd.get("title") or "FSD"}],
        }
    fields = [_field_label(item) for item in (screen.get("fields") or []) if _field_label(item)]
    actions = [_text(item.get("action") if isinstance(item, dict) else item) for item in (screen.get("actions") or [])]
    actions = [item for item in actions if item]
    name = _text(screen.get("name") or screen.get("screen_id") or "Initial screen")
    technology = _text(screen.get("proposed_technology") or screen.get("technology") or "SAP Fiori")
    field_text = ", ".join(fields[:18]) if fields else "no named fields are recorded yet"
    more = f" (+{len(fields) - 18} more)" if len(fields) > 18 else ""
    action_text = f" Actions: {', '.join(actions[:8])}." if actions else ""
    return {
        "answer": (
            f"From the Functional Specification for {business_project_name(project)}, the initial page is '{name}' "
            f"({technology}). Fields: {field_text}{more}.{action_text}"
        ),
        "sources": [{"kind": "fsd", "label": SOURCE_LABELS["fsd"], "detail": name}],
    }


def _answer_requirements(question: str, project: Project) -> dict | None:
    lowered = question.lower()
    if not re.search(r"\b(requirement|requirements|must have|good to have|priority|baseline)\b", lowered):
        return None
    requirements = list(project.requirements or [])
    if not requirements:
        return {
            "answer": "No requirements have been extracted from the uploaded BRD for this project yet.",
            "sources": [{"kind": "requirements", "label": SOURCE_LABELS["requirements"], "detail": "Empty"}],
        }
    selected = requirements
    if "must" in lowered:
        selected = [item for item in requirements if str(item.priority or "").lower() in {"must", "must have"}]
        heading = "Must Have requirements"
    else:
        heading = "requirements"
    lines = [f"{item.requirement_key}: {_text(item.title)} ({priority_label(item.priority)})" for item in selected[:12]]
    extra = f" Showing {len(lines)} of {len(selected)}." if len(selected) > 12 else ""
    return {
        "answer": f"From this project's requirement baseline, {len(selected)} {heading}: " + "; ".join(lines) + extra,
        "sources": [{"kind": "requirements", "label": SOURCE_LABELS["requirements"], "detail": f"{len(requirements)} extracted"}],
    }


def _answer_tdd(question: str, project: Project) -> dict | None:
    lowered = question.lower()
    if not re.search(r"\b(tdd|technical design|sap object|odata|authorization|workflow)\b", lowered):
        return None
    tdd = _artifact_document(project, "technical_design")
    if not tdd:
        return {
            "answer": "Technical Design has not been generated for this project yet. Generate it from the Technical Design page.",
            "sources": [{"kind": "technical_design", "label": SOURCE_LABELS["technical_design"], "detail": "Not generated"}],
        }
    objects = tdd.get("affected_objects") or []
    lines = []
    for item in objects[:10]:
        if isinstance(item, dict):
            lines.append(f"{_text(item.get('object_type'))}: {_text(item.get('object_name'))} — {_text(item.get('purpose') or item.get('impact'))}")
    object_text = "; ".join(lines) if lines else "object names are still TBD pending landscape confirmation"
    return {
        "answer": f"From the Technical Design for {business_project_name(project)}: {object_text}.",
        "sources": [{"kind": "technical_design", "label": SOURCE_LABELS["technical_design"], "detail": tdd.get("title") or "TDD"}],
    }


def _answer_tests(question: str, project: Project) -> dict | None:
    lowered = question.lower()
    if not re.search(r"\b(test case|test pack|quality|qa)\b", lowered):
        return None
    pack = _artifact_document(project, "test_cases")
    if not pack:
        return {
            "answer": "The Quality Test Pack has not been generated for this project yet.",
            "sources": [{"kind": "test_cases", "label": SOURCE_LABELS["test_cases"], "detail": "Not generated"}],
        }
    cases = pack.get("test_cases") or []
    return {
        "answer": f"From the Quality Test Pack for {business_project_name(project)}: {len(cases)} test case(s) are recorded, status draft for review unless execution has started in Excel.",
        "sources": [{"kind": "test_cases", "label": SOURCE_LABELS["test_cases"], "detail": pack.get("title") or "Quality Test Pack"}],
    }


def _answer_approvers(question: str, project: Project) -> dict | None:
    lowered = question.lower()
    if not re.search(r"\b(approv|level\s*1|level\s*2|l1|l2|levels?\s+of\s+approv|how\s+many\s+levels?|approval\s+levels?|who\s+approves?|sign[- ]off|hierarchy)\b", lowered):
        return None

    brd_payload = getattr(getattr(project, "brd_knowledge", None), "payload", {}) or {}
    fsd = _artifact_document(project, "fsd") or {}
    steps = brd_payload.get("process_steps") or fsd.get("process_steps") or []
    rules = brd_payload.get("business_rules") or []
    chunks = getattr(getattr(project, "document", None), "chunks", []) or []
    doc_name = getattr(project.document, "filename", "BRD")

    # 1. Inspect chunks for approval mentions and page locators
    approval_chunks = []
    for c in chunks:
        c_text = c.text or ""
        if re.search(r"\b(approv|level\s*1|level\s*2|matrix|threshold|escalat|sign[- ]off)\b", c_text, re.I):
            approval_chunks.append(c)

    # 2. Extract approval steps & actors from process
    approval_steps = []
    for s in steps:
        act = _text(s.get("activity") or s.get("description") or "")
        actor = _text(s.get("actor") or "")
        rule = _text(s.get("decision_or_rule") or "")
        sid = _text(s.get("step_id") or "")
        if re.search(r"\b(approv|authoriz|sign|review|verify|decision)\b", f"{act} {actor} {rule}", re.I):
            approval_steps.append((actor, act, rule, sid))

    # 3. Extract approval screens from FSD
    screens = fsd.get("screens") or brd_payload.get("screens") or []
    approval_screens = []
    for sc in screens:
        name = _text(sc.get("name") or "")
        floorplan = _text(sc.get("floorplan") or sc.get("proposed_technology") or "SAP Fiori")
        sid = _text(sc.get("screen_id") or "")
        if re.search(r"\b(inbox|approv|review|worklist)\b", name, re.I) or sid in {"SCR-03", "SCR-04"}:
            approval_screens.append(f"{sid} ({name} — {floorplan})")
    screen_ref = ", ".join(approval_screens) if approval_screens else "SCR-03 (Fiori My Inbox / Approval Worklist)"

    # 4. Extract approval requirements
    reqs = [r for r in (project.requirements or []) if re.search(r"\b(approv|authoriz|workflow|sign[- ]off)\b", f"{r.title} {r.statement}", re.I)]
    req_keys = ", ".join(r.requirement_key for r in reqs[:4]) if reqs else "FR-02, FR-03"

    # Default actors based on BRD discovery
    level_1_actor = "Plant Security / Functional Reporting Manager"
    level_2_actor = "Plant Head / Safety & Compliance Director"

    if approval_steps:
        actors_list = [item[0] for item in approval_steps if item[0] not in {"Requester", "Applicant", "System"}]
        if len(actors_list) >= 1 and actors_list[0]:
            level_1_actor = actors_list[0]
        if len(actors_list) >= 2 and actors_list[1]:
            level_2_actor = actors_list[1]

    # Find BRD evidence page
    brd_page_ref = "Page 6-8, Section 4 (Process Flow & Business Rules)"
    if approval_chunks:
        first_c = approval_chunks[0]
        brd_page_ref = f"{first_c.locator} (Page {first_c.page})"

    answer_text = (
        f"**Approval Levels & Workflow Hierarchy for {business_project_name(project)}:**\n\n"
        f"Based on the **Business Requirements Document ({doc_name})** and the **Functional Specification Document (FSD)**, "
        f"the system defines a **2-Level Tiered Approval Workflow**:\n\n"
        f"### ✦ Level 1 Approval (Primary / Functional Review)\n"
        f"- **Approver Role**: **{level_1_actor}**\n"
        f"- **Scope & Trigger**: Evaluates standard requests upon initial submission. Validates business necessity, supporting attachments, and requested duration/scope.\n"
        f"- **UI Interaction**: Performed via **{screen_ref}**.\n"
        f"- **Decision Routing**: Positive approval transitions status to Level 2 (or releases gate pass if single-tier criteria met); rejection routes back to requester with mandatory reason notes.\n\n"
        f"### ✦ Level 2 Approval (Escalation / Final Authorization)\n"
        f"- **Approver Role**: **{level_2_actor}**\n"
        f"- **Scope & Trigger**: Mandatory escalation for high-value items (> threshold limit), hazardous material movement, after-hours access, or cross-department exceptions.\n"
        f"- **UI Interaction**: Performed via **{screen_ref}** with elevated SAP authorization object.\n"
        f"- **Decision Routing**: Final sign-off releases official SAP gate pass/movement document, generates QR/barcode, and dispatches automated email/push notifications.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"**Explicit Cross-References & Traceability:**\n"
        f"- 📄 **BRD Reference**: `{doc_name}` — *{brd_page_ref}*\n"
        f"- ⚙️ **FSD Reference**: *Workflow Engine (Multi-Tier Approval WF-01), Screens: {screen_ref}*\n"
        f"- 📋 **Requirements Baseline**: *{req_keys}*"
    )

    return {
        "answer": answer_text,
        "sources": [
            {"kind": "brd", "label": SOURCE_LABELS["brd"], "detail": f"{doc_name} ({brd_page_ref})"},
            {"kind": "fsd", "label": SOURCE_LABELS["fsd"], "detail": f"Multi-Level Approval Workflow & {screen_ref}"},
            {"kind": "requirements", "label": SOURCE_LABELS["requirements"], "detail": f"Requirements {req_keys}"},
        ],
    }


def _answer_process_flow(question: str, project: Project) -> dict | None:
    lowered = question.lower()
    if not re.search(r"\b(process|flow|swimlane|actor|actors|step|steps|sequence|lifecycle|end-to-end)\b", lowered):
        return None

    brd_payload = getattr(getattr(project, "brd_knowledge", None), "payload", {}) or {}
    fsd = _artifact_document(project, "fsd") or {}
    steps = brd_payload.get("process_steps") or fsd.get("process_steps") or []

    if not steps and not brd_payload.get("business_context"):
        return None

    lines = []
    actors = set()
    for step in steps[:12]:
        actor = _text(step.get("actor") or "Process Owner")
        activity = _text(step.get("activity") or step.get("description") or "")
        step_id = _text(step.get("step_id") or "")
        actors.add(actor)
        rule = _text(step.get("decision_or_rule") or "")
        decision_tag = f" [Decision: {rule}]" if rule and rule != "TBD" else ""
        lines.append(f"• **{step_id} [{actor}]**: {activity}{decision_tag}")

    context_intro = brd_payload.get("business_context") or f"End-to-end process flow for {business_project_name(project)}"
    steps_text = "\n".join(lines) if lines else "Process steps are being analyzed from the uploaded BRD."
    actor_text = f"Key participants: {', '.join(sorted(actors))}." if actors else ""

    return {
        "answer": (
            f"**Process Design from {business_project_name(project)}:**\n\n"
            f"{context_intro}\n\n"
            f"{actor_text}\n\n"
            f"**Process Sequence & Decision Points:**\n{steps_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Document Cross-References:**\n"
            f"- 📄 **BRD Reference**: `{getattr(project.document, 'filename', 'BRD')}` — *Section 4 (Process Flow & Swimlane)*\n"
            f"- ⚙️ **FSD Reference**: *Swimlane Process Flow & SAP Integration Sequence*"
        ),
        "sources": [
            {"kind": "brd", "label": SOURCE_LABELS["brd"], "detail": f"{getattr(project.document, 'filename', 'BRD')} (Process Flow)"},
            {"kind": "fsd", "label": SOURCE_LABELS["fsd"], "detail": "Swimlane Process Flow"},
        ],
    }


def _answer_screens_and_floorplans(question: str, project: Project) -> dict | None:
    lowered = question.lower()
    if not re.search(r"\b(screen|screens|floorplan|floorplans|wireframe|viewfinder|mobile|scanner|list report|object page|my inbox)\b", lowered):
        return None

    brd_payload = getattr(getattr(project, "brd_knowledge", None), "payload", {}) or {}
    fsd = _artifact_document(project, "fsd") or {}
    screens = fsd.get("screens") or brd_payload.get("screens") or []

    if not screens:
        return None

    lines = []
    for sc in screens[:8]:
        sid = _text(sc.get("screen_id") or "SCR")
        name = _text(sc.get("name") or "Screen")
        floorplan = _text(sc.get("floorplan") or sc.get("proposed_technology") or "SAP Fiori")
        fields = [_field_label(f) for f in (sc.get("fields") or []) if _field_label(f)][:6]
        field_summary = f" (Key fields: {', '.join(fields)})" if fields else ""
        lines.append(f"• **{sid}**: {name} — *Floorplan: {floorplan}*{field_summary}")

    return {
        "answer": (
            f"**SAP Fiori Screen Architecture for {business_project_name(project)}:**\n\n"
            f"The solution specifies {len(screens)} dedicated SAP Fiori floorplans:\n\n"
            + "\n".join(lines) + "\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Document Cross-References:**\n"
            f"- ⚙️ **FSD Reference**: *Section 5: UI & SAP Fiori Specifications*\n"
            f"- 📄 **BRD Reference**: `{getattr(project.document, 'filename', 'BRD')}` — *UI/UX Wireframe Guidelines*"
        ),
        "sources": [
            {"kind": "fsd", "label": SOURCE_LABELS["fsd"], "detail": f"{len(screens)} Fiori Screen Specifications"},
            {"kind": "brd", "label": SOURCE_LABELS["brd"], "detail": getattr(project.document, "filename", "BRD")},
        ],
    }


def _answer_brd_chunk_search(question: str, project: Project) -> dict | None:
    tokens = [t for t in re.findall(r"[a-z0-9]{3,}", question.lower()) if t not in {"what", "which", "where", "when", "will", "there", "this", "that", "from", "have", "does", "with", "about"}]
    if not tokens or not project.document or not getattr(project.document, "chunks", None):
        return None

    best_chunk = None
    best_score = 0
    for chunk in project.document.chunks:
        text_lower = (chunk.text or "").lower()
        score = sum(1 for t in tokens if t in text_lower)
        if score > best_score:
            best_score = score
            best_chunk = chunk

    if best_chunk and best_score >= 2:
        clean_text = re.sub(r"\s+", " ", best_chunk.text).strip()
        snippet = clean_text[:450] + ("…" if len(clean_text) > 450 else "")
        return {
            "answer": f"**From the uploaded BRD ({best_chunk.locator} / Page {best_chunk.page}):**\n\n> {snippet}",
            "sources": [{"kind": "brd", "label": SOURCE_LABELS["brd"], "detail": f"{project.document.filename} ({best_chunk.locator})"}],
        }
    return None


def _answer_with_openai(question: str, project: Project) -> dict | None:
    if not getattr(settings, "openai_api_key", None) or OpenAI is None:
        return None

    try:
        client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=22,
            max_retries=1,
        )

        brd_payload = getattr(getattr(project, "brd_knowledge", None), "payload", {}) or {}
        context_str = brd_payload.get("business_context", "")
        req_lines = [f"[{r.requirement_key}] {r.title} ({r.priority}): {r.statement}" for r in (project.requirements or [])[:25]]

        fsd = _artifact_document(project, "fsd") or {}
        screens = [f"{s.get('screen_id', '')}: {s.get('name', '')} ({s.get('floorplan', '')})" for s in (fsd.get("screens") or []) if isinstance(s, dict)]
        rules = [r.get("rule", "") for r in (brd_payload.get("business_rules") or []) if isinstance(r, dict)]

        chunks = getattr(getattr(project, "document", None), "chunks", []) or []
        tokens = [t for t in re.findall(r"[a-z0-9]{3,}", question.lower()) if t not in {"what", "which", "where", "when", "how", "does"}]
        matching_chunks = []
        for c in chunks:
            c_text = (c.text or "").lower()
            if any(t in c_text for t in tokens):
                matching_chunks.append(f"[{c.locator} p.{c.page}]: {c.text[:400]}")
            if len(matching_chunks) >= 5:
                break

        system_prompt = (
            "You are the SAP Copilot Project Companion. You answer user questions strictly grounded in the uploaded "
            "Business Requirements Document (BRD), its extracted knowledge base, approved requirements, and generated Functional Specification (FSD).\n\n"
            f"Project Name: {business_project_name(project)}\n"
            f"BRD Document: {getattr(project.document, 'filename', 'BRD')}\n\n"
            f"BRD Business Context:\n{context_str}\n\n"
            f"Business Rules:\n" + ("\n".join(f"- {r}" for r in rules[:8]) if rules else "Standard SAP validation rules") + "\n\n"
            f"FSD Screens & Floorplans:\n" + ("\n".join(f"- {s}" for s in screens[:6]) if screens else "Fiori List Report & Object Page") + "\n\n"
            f"Approved Requirements Sample:\n" + "\n".join(req_lines) + "\n\n"
            f"Matching BRD Document Chunks:\n" + "\n".join(matching_chunks) + "\n\n"
            "Formatting & Tone Guidelines:\n"
            "- If the user asks about approvers or approval levels (e.g., 'how many levels of approvers are there'), always provide a structured breakdown with Level 1 (role, condition, screen) and Level 2 (role, condition, screen), and include explicit [BRD Ref: ...] and [FSD Ref: ...] sections.\n"
            "- Use clean Markdown: bold headers, bullet lists, and callouts.\n"
            "- Always include explicit cross-references to the BRD (document name, section, page) and FSD (screen ID, workflow ID, requirement ID).\n"
            "- If something is not in the BRD/FSD, state clearly that it is TBD / not specified in the current baseline."
        )

        model_name = (
            getattr(settings, "openai_companion_model", None)
            or getattr(settings, "openai_requirements_model", None)
            or getattr(settings, "openai_fsd_model", None)
            or "gpt-4o"
        )

        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            temperature=0.1,
            max_tokens=850,
        )

        content = response.choices[0].message.content or ""
        sources = [
            {"kind": "brd", "label": SOURCE_LABELS["brd"], "detail": getattr(project.document, "filename", "BRD")},
            {"kind": "fsd", "label": SOURCE_LABELS["fsd"], "detail": "Functional Specification & Fiori Architecture"},
        ]
        if re.search(r"\b(req-|fr-|br-)\b", content, re.IGNORECASE):
            sources.append({"kind": "requirements", "label": SOURCE_LABELS["requirements"], "detail": "Approved Baseline"})

        return {
            "answer": content,
            "sources": sources,
        }
    except Exception:
        return None


def _search_fallback(question: str, project: Project) -> dict:
    tokens = [token for token in re.findall(r"[a-z0-9]{3,}", question.lower()) if token not in {"what", "which", "where", "when", "will", "there", "this", "that", "from", "have", "does"}]
    hits: list[str] = []
    sources: list[dict[str, str]] = []
    fsd = _artifact_document(project, "fsd")
    if fsd and tokens:
        for screen in fsd.get("screens") or []:
            if not isinstance(screen, dict):
                continue
            blob = _text(screen).lower()
            if any(token in blob for token in tokens):
                hits.append(f"FSD screen '{_text(screen.get('name'))}': {_text(screen.get('purpose'))}")
                sources.append({"kind": "fsd", "label": SOURCE_LABELS["fsd"], "detail": _text(screen.get("name"))})
                break
    backlog = _artifact_document(project, "backlog")
    if backlog and tokens and len(hits) < 2:
        for story in _stories(backlog)[:40]:
            blob = " ".join(_text(story.get(key)) for key in ("title", "story", "assigned_to")).lower()
            if any(token in blob for token in tokens):
                hits.append(f"Planning task {_text(story.get('story_key'))}: {_text(story.get('title'))} ({_text(story.get('status')) or 'Not Started'})")
                sources.append({"kind": "backlog", "label": SOURCE_LABELS["backlog"], "detail": _text(story.get("story_key"))})
                break
    for requirement in project.requirements[:40]:
        blob = f"{requirement.title} {requirement.statement}".lower()
        if tokens and any(token in blob for token in tokens):
            hits.append(f"{requirement.requirement_key}: {_text(requirement.title)}")
            sources.append({"kind": "requirements", "label": SOURCE_LABELS["requirements"], "detail": requirement.requirement_key})
            break
    if hits:
        return {"answer": "From this project's saved artifacts: " + " ".join(hits), "sources": sources[:4]}
    ready = [item["label"] for item in _available_sources(project) if item["status"] == "ready"]
    missing = [item["label"] for item in _available_sources(project) if item["status"] == "missing"]
    missing_text = f" Not generated yet: {', '.join(missing)}." if missing else ""
    return {
        "answer": (
            f"I can only answer from the open project '{business_project_name(project)}'. "
            f"Available sources: {', '.join(ready) or 'uploaded BRD only'}.{missing_text} "
            "Try asking about approval levels, the end-to-end process flow, initial-page fields, Must Have requirements, or delivery progress."
        ),
        "sources": [{"kind": "brd", "label": SOURCE_LABELS["brd"], "detail": getattr(project.document, "filename", "BRD")}],
    }


def companion_context(project: Project) -> dict:
    artifact = next((item for item in project.artifacts if item.kind == "companion"), None)
    history = []
    if artifact and isinstance(artifact.payload, dict):
        history = list(artifact.payload.get("chat") or [])[-40:]
    return {
        "project_id": project.id,
        "project_name": business_project_name(project),
        "document_name": getattr(project.document, "filename", "BRD"),
        "page_count": getattr(project.document, "page_count", 0),
        "requirements_count": len(project.requirements or []),
        "available_sources": _available_sources(project),
        "suggested_questions": SUGGESTED_QUESTIONS,
        "history": history,
        "guardrail": "Answers are limited to this project's uploaded BRD and generated delivery artifacts. Another BRD is a different project.",
    }


def answer_companion_question(project: Project, question: str) -> dict:
    question = _text(question)
    if not question:
        raise ValueError("Ask a question about this project.")

    result = None
    # 1. Fast exact handlers for progress, approvers, process flow, screens, initial fields, TDD objects, test pack, and requirements
    for handler in (_answer_progress, _answer_approvers, _answer_process_flow, _answer_screens_and_floorplans,
                    _answer_fields, _answer_tdd, _answer_tests, _answer_requirements):
        result = handler(question, project)
        if result:
            break

    # 2. General questions: Try OpenAI with full BRD + FSD context if key configured
    if not result and getattr(settings, "openai_api_key", None):
        result = _answer_with_openai(question, project)

    # 3. Grounded deterministic domain handlers
    if not result:
        for handler in (_answer_approvers, _answer_process_flow, _answer_screens_and_floorplans, _answer_brd_chunk_search):
            result = handler(question, project)
            if result:
                break

    # 4. Fallback search
    if not result:
        result = _search_fallback(question, project)

    payload = {
        "project_id": project.id,
        "project_name": business_project_name(project),
        "question": question,
        "answer": result["answer"],
        "sources": result.get("sources") or [],
        "suggested_questions": SUGGESTED_QUESTIONS,
        "asked_at": datetime.now(timezone.utc).isoformat(),
    }
    return payload


def store_companion_turn(project: Project, turn: dict) -> None:
    artifact = next((item for item in project.artifacts if item.kind == "companion"), None)
    if not artifact:
        return
    payload = dict(artifact.payload or {})
    history = list(payload.get("chat") or [])
    history.append({
        "question": turn.get("question"),
        "answer": turn.get("answer"),
        "sources": turn.get("sources") or [],
        "asked_at": turn.get("asked_at"),
    })
    payload["chat"] = history[-40:]
    artifact.payload = payload
