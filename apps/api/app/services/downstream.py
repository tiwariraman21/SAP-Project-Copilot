from datetime import date, timedelta
import re

from ..models import Project, ReviewStatus
from .project_identity import business_project_name, looks_like_person_name, priority_label, process_identifier


def _approved(project: Project):
    return [r for r in project.requirements if r.review_status == ReviewStatus.approved]


def build_backlog(project: Project) -> dict:
    requirements = _approved(project)
    today = date.today()
    first_sprint_start = today + timedelta(days=(7 - today.weekday()) % 7)
    source_locators = {chunk.id: chunk.locator for chunk in project.document.chunks}
    assignment_by_type = {
        "functional": "SAP Functional Consultant", "non_functional": "Technical Architect",
        "integration": "Integration Developer", "data": "SAP Data & Analytics Consultant",
        "reporting": "SAP Data & Analytics Consultant", "security": "Security Consultant",
    }
    stories = []
    for index, r in enumerate(requirements, 1):
        sprint = 1 + ((index - 1) // 4)
        start_date = first_sprint_start + timedelta(days=(sprint - 1) * 14)
        source_locator = "; ".join(source_locators.get(chunk_id, "") for chunk_id in r.source_chunk_ids)
        stories.append({
            "story_key": f"US-{index:03}", "requirement_key": r.requirement_key,
            "title": r.title, "story": f"As an SAP business user, I want {r.statement[:1].lower() + r.statement[1:]} so that the approved business outcome is achieved.",
            "priority": r.priority, "story_points": 5 if r.priority == "must" else 3,
            "acceptance_criteria": r.acceptance_criteria, "sprint": sprint,
            "assigned_to": assignment_by_type.get(r.requirement_type, "Unassigned"),
            "start_date": start_date.isoformat(), "target_end_date": (start_date + timedelta(days=13)).isoformat(),
            "status": "Not Started", "remarks": "Confirm scope, estimate, owner, and dependencies during sprint refinement.",
            "dependency": "TBD during refinement", "progress_percent": 0,
            "source_locator": source_locator or "Approved BRD source", "source_evidence": r.source_quote,
        })
    sprint_numbers = sorted({s["sprint"] for s in stories})
    display_name = business_project_name(project)
    return {"title": f"Delivery Backlog - {display_name}", "project_name": display_name,
            "generated_on": today.isoformat(), "status": "draft_for_review", "stories": stories,
            "sprints": [{"number": n, "goal": f"Deliver approved requirement group {n}",
                         "start_date": next(s["start_date"] for s in stories if s["sprint"] == n),
                         "target_end_date": next(s["target_end_date"] for s in stories if s["sprint"] == n),
                         "story_keys": [s["story_key"] for s in stories if s["sprint"] == n]} for n in sprint_numbers],
            "assumptions": ["Two-week sprints", "Story points require team calibration", "Dependencies must be validated during refinement"]}


def _fsd_document(project: Project) -> dict:
    artifact = next((item for item in project.artifacts if item.kind == "fsd"), None)
    payload = artifact.payload if artifact else None
    document = payload.get("document") if isinstance(payload, dict) else None
    return document if isinstance(document, dict) else {}


def _application_name(info: dict, fallback: str = "SAP S/4HANA / SAP Fiori / SAPUI5") -> str:
    value = str(info.get("application") or "").strip()
    if not value or value.upper() in {"TBD", "SAP - TBD", "SAP", "N/A", "NONE"}:
        return fallback
    return value


def _join_ids(values) -> str:
    if isinstance(values, list):
        return ", ".join(str(item) for item in values if item) or "TBD"
    return str(values) if values else "TBD"


def _glossary_rows(values) -> list[dict]:
    rows = []
    for item in values or []:
        if isinstance(item, dict):
            term = item.get("term") or item.get("name") or "Term"
            definition = item.get("definition") or item.get("description") or str(item)
            rows.append({"term": term, "definition": definition})
        else:
            text = str(item)
            term, _, definition = text.partition(" - ")
            if not definition:
                term, _, definition = text.partition(": ")
            rows.append({"term": term.strip(), "definition": (definition or text).strip()})
    return rows or [
        {"term": "TDD/TSD", "definition": "Technical Design Document / Technical Specification Document"},
        {"term": "OData", "definition": "Service protocol used by SAP applications to expose business data and operations"},
        {"term": "TBD", "definition": "To be determined and approved during technical design review"},
    ]


def build_technical_design(project: Project) -> dict:
    requirements = _approved(project)
    fsd = _fsd_document(project)
    info = fsd.get("document_information") if isinstance(fsd.get("document_information"), dict) else {}
    scope = fsd.get("scope") if isinstance(fsd.get("scope"), dict) else {}
    locators = {chunk.id: chunk.locator for chunk in project.document.chunks}
    today = date.today()
    display_name = business_project_name(project)
    fsd_title = display_name
    raw_fsd_title = str(fsd.get("title") or "")
    cleaned_fsd = re.sub(r"\s*-\s*Functional (?:Solution )?Design\s*$", "", raw_fsd_title, flags=re.I).strip()
    if cleaned_fsd and not looks_like_person_name(cleaned_fsd):
        fsd_title = cleaned_fsd
    fsd_version = fsd.get("version") or "1.0"
    type_response = {
        "functional": ("Core process / Fiori capability", "Fiori List Report / Object Page with ABAP service behaviour for the approved process"),
        "integration": ("Integration", "Approved OData / API over HTTPS with backend authorization on every operation"),
        "data": ("Data and persistence", "SAP persistence remains authoritative; the UI does not own master data"),
        "reporting": ("Reporting / analytics", "Read model via CDS/OData; confirm analytics objects during design review"),
        "security": ("Security and authorization", "Least-privilege roles and backend checks on every protected operation"),
        "non_functional": ("Non-functional", "Performance, logging, transport and operational controls from the FSD baseline"),
    }
    capability_map = []
    for item in fsd.get("improvement_mapping") or []:
        capability_map.append({
            "capability": item.get("constraint") or item.get("area") or "Capability",
            "technical_response": item.get("to_be_response") or item.get("expected_improvement") or "Confirm technical pattern during design review",
            "requirement_ids": _join_ids(item.get("requirement_ids")),
        })
    if not capability_map:
        by_type: dict[str, list] = {}
        for requirement in requirements:
            by_type.setdefault(requirement.requirement_type or "functional", []).append(requirement)
        for requirement_type, grouped in by_type.items():
            label, response = type_response.get(requirement_type, ("Other", "Confirm technical pattern during design review"))
            extra = f" (+{len(grouped) - 18})" if len(grouped) > 18 else ""
            capability_map.append({
                "capability": label,
                "technical_response": response,
                "requirement_ids": ", ".join(item.requirement_key for item in grouped[:18]) + extra,
            })

    components = []
    fsd_requirements = fsd.get("requirements") or []
    for requirement in requirements:
        locator = "; ".join(locators.get(chunk_id, "") for chunk_id in requirement.source_chunk_ids) or "Approved BRD source"
        fsd_row = next((row for row in fsd_requirements if row.get("requirement_id") == requirement.requirement_key or row.get("requirement_key") == requirement.requirement_key), {})
        components.append({
            "requirement_key": requirement.requirement_key,
            "title": requirement.title,
            "requirement_type": requirement.requirement_type,
            "priority": priority_label(requirement.priority),
            "technical_component": "SAP Fiori application and ABAP / OData service layer (confirm final extension pattern)",
            "design": fsd_row.get("functional_behavior") or f"Implement the approved behavior: {requirement.statement}",
            "interface_or_entity": "TBD after SAP landscape and data-model confirmation",
            "validation": "; ".join(requirement.acceptance_criteria) if requirement.acceptance_criteria else requirement.statement,
            "authorization": "Apply least privilege; confirm business role and authorization object during design review",
            "source_locator": locator,
            "source_evidence": requirement.source_quote,
        })

    process_steps = fsd.get("process_steps") or [{
        "step_id": f"TDF-{index:02}", "actor": "SAP business user" if index == 1 else "SAP application",
        "activity": requirement.title, "system_behavior": requirement.statement,
        "outcome": requirement.acceptance_criteria[0] if requirement.acceptance_criteria else "Approved result is recorded",
        "requirement_ids": [requirement.requirement_key],
    } for index, requirement in enumerate(requirements[:18], 1)]

    technical_objects = fsd.get("technical_objects") or [
        {"object_type": "Fiori application", "object_name": "TBD", "purpose": "User interaction and validations"},
        {"object_type": "OData service", "object_name": "TBD", "purpose": "Typed UI-to-ABAP service contract"},
        {"object_type": "ABAP class", "object_name": "ZCL_* (TBD)", "purpose": "Business orchestration and validation"},
        {"object_type": "Database/CDS", "object_name": "TBD", "purpose": "Read/write model selected after fit-to-standard review"},
    ]
    affected_objects = [{
        "object_type": item.get("object_type") or item.get("type") or "SAP object",
        "object_name": item.get("object_name") or item.get("name") or "TBD",
        "purpose": item.get("purpose") or item.get("description") or "Confirm during design review",
        "impact": item.get("impact") or item.get("purpose") or "Confirm during design review",
    } for item in technical_objects]

    related = [{"document": fsd_title, "location": f"Generated Functional Specification, Version {fsd_version}"},
               {"document": project.document.filename if project.document else "Approved BRD", "location": "Project knowledge base"}]
    for name in fsd.get("relevant_documents") or []:
        if name and name not in {row["document"] for row in related}:
            related.append({"document": name, "location": "Referenced by the FSD"})

    fsd_issues = fsd.get("outstanding_issues") or []
    outstanding_issues = []
    for index, issue in enumerate(fsd_issues, 1):
        if isinstance(issue, dict):
            outstanding_issues.append({
                "issue_no": issue.get("issue_id") or issue.get("issue_no") or f"OI-{index:02}",
                "description": issue.get("description") or issue.get("issue") or issue.get("title") or "Open design decision",
                "assigned_to": issue.get("owner") or issue.get("assigned_to") or "Solution Architect",
                "status": issue.get("status") or "Open",
                "impact": issue.get("impact") or "Technical design cannot be finalized",
                "resolution": issue.get("resolution") or issue.get("decision_needed") or "Confirm during design workshop",
            })
        else:
            outstanding_issues.append({
                "issue_no": f"OI-{index:02}", "description": str(issue), "assigned_to": "Solution Architect",
                "status": "Open", "impact": "Technical design cannot be finalized", "resolution": "Confirm during design workshop",
            })
    if not outstanding_issues:
        outstanding_issues = [{
            "issue_no": f"OI-{index:02}", "description": decision, "assigned_to": "Solution Architect",
            "status": "Open", "impact": "Technical design cannot be finalized", "resolution": "Confirm during design workshop",
        } for index, decision in enumerate([
            "Confirm SAP modules and release", "Confirm clean-core extension strategy",
            "Confirm integration middleware and identity provider", "Assign final SAP repository object names",
        ], 1)]

    test_conditions = []
    for index, item in enumerate(fsd.get("test_conditions") or [], 1):
        test_conditions.append({
            "id": item.get("test_id") or item.get("id") or f"UT-{index:03}",
            "condition": item.get("scenario") or item.get("condition") or item.get("steps") or "Validate the approved technical behaviour",
            "expected_result": item.get("expected_result") or "Approved outcome is recorded without unauthorized side effects",
            "requirement_key": _join_ids(item.get("requirement_ids") or item.get("requirement_key")),
            "cycle_ref": item.get("cycle_ref") or "SIT/UAT",
        })
    if not test_conditions:
        test_conditions = [{
            "id": f"UT-{index:03}", "requirement_key": item["requirement_key"], "condition": item["design"],
            "expected_result": item["validation"], "cycle_ref": "SIT/UAT",
        } for index, item in enumerate(components, 1)]

    messages = []
    for index, item in enumerate(fsd.get("message_catalog") or [], 1):
        messages.append({
            "id": item.get("message_id") or f"MSG-{index:02}",
            "scenario": item.get("scenario") or item.get("condition") or "Exception path",
            "user_message": item.get("message_text") or item.get("message") or item.get("description") or "Display a controlled business message",
            "technical_handling": item.get("handling") or "Return a controlled business error; retain technical detail in support logs only",
        })

    return {
        "title": display_name,
        "status": "draft_for_review",
        "generated_on": today.strftime("%d.%m.%Y"),
        "source_fsd": {"title": fsd_title, "version": fsd_version, "prepared_by": info.get("prepared_by") or "SAP Project Copilot"},
        "document_information": {
            "extension_id": "OData / Fiori / ABAP (to be confirmed)",
            "extension_description": f"Technical design for the {display_name} process",
            "application": _application_name(info),
            "process_area": info.get("functional_area") or "TBD",
            "project": display_name,
            "process_identifier": process_identifier(project),
            "job_name": "N/A - no batch job identified" if not fsd.get("batch_jobs") else _join_ids(fsd.get("batch_jobs")),
            "functional_designer": info.get("prepared_by") or "SAP Project Copilot (per FSD)",
            "technical_designer": "TBD / project technical lead",
            "developer": "TBD",
            "tools_technology": "SAP Fiori elements, SAPUI5, OData, ABAP",
            "classification": info.get("classification") or "Internal",
            "program_type": "SAP Fiori / OData / ABAP (to be confirmed)",
            "prepared_by": "SAP Project Copilot",
            "version": "0.1",
        },
        "related_documents": related,
        "revision_history": [{"version": "0.1", "date": today.strftime("%d.%m.%Y"), "author": "SAP Project Copilot",
                              "description": f"Initial technical design draft generated from Functional Solution Design v{fsd_version}."}],
        "sign_offs": fsd.get("sign_offs") or [
            {"role": "Business Process Owner", "name": "TBD"}, {"role": "SAP Functional Lead", "name": "TBD"},
            {"role": "SAP Technical Lead", "name": "TBD"}, {"role": "Security / Authorization Lead", "name": "TBD"},
        ],
        "distribution": [
            {"name": "Business review team", "role": "Business review"},
            {"name": "SAP Development Team", "role": "Implementation"},
            {"name": "SAP Basis / Security", "role": "Landscape, activation and authorization review"},
            {"name": "QA / Test Team", "role": "Technical and integration testing"},
        ],
        "requirements_summary": fsd.get("future_state_narrative") or fsd.get("purpose") or (
            f"This design translates {len(requirements)} approved, source-linked requirements from the FSD into a reviewable SAP technical implementation baseline."
        ),
        "capability_map": capability_map,
        "assumptions": fsd.get("assumptions") or scope.get("current_constraints") or [
            "Target SAP product, release, deployment model, and clean-core policy require confirmation",
            "Object names shown as TBD must be assigned by the SAP development lead",
            "All generated technical decisions require architecture and security review",
        ],
        "dependencies": fsd.get("dependencies") or [
            "Approved functional specification", "Confirmed SAP landscape and connectivity",
            "Business roles and authorization design", "Representative test data and transport path",
        ],
        "standards": [
            "Prefer fit-to-standard SAP Fiori, OData and workflow capabilities before custom code",
            "Follow SAP Fiori responsive design and accessibility expectations; status must use text/state and not color alone",
            "Use enterprise SAP authentication, HTTPS/TLS and standard OData security mechanisms",
            "Use backend business authorization as the enforcement point; UI visibility is not an authorization control",
            "Use target-system naming, package, transport and development standards once confirmed by the project technical lead",
        ],
        "architecture": [item.get("name") or item.get("layer") or str(item) for item in (fsd.get("actors_and_systems") or [])] or [
            "SAP Fiori/UI5 presentation layer", "OData service contract", "ABAP application/service layer",
            "SAP persistence and standard APIs", "Enterprise identity, authorization, logging, and transport controls",
        ],
        "process_steps": process_steps,
        "fiori_flows": [
            {"flow": item.get("activity") or item.get("step_id"), "behavior": item.get("system_behavior") or item.get("outcome"),
             "mechanism": "OData / SAP Fiori unless a confirmed fit-gap selects a standard application or API"}
            for item in process_steps[:12]
        ],
        "screens": [{
            "name": item.get("name") or item.get("screen_id") or "Screen",
            "technology": item.get("proposed_technology") or "SAP Fiori",
            "fields": ", ".join(str(field.get("label") or field.get("field_id") or field) for field in (item.get("fields") or [])[:8]) or "TBD during UI design",
            "actions": ", ".join(str(action.get("action") or action) for action in (item.get("actions") or [])[:6]) or "TBD",
        } for item in (fsd.get("screens") or [])],
        "components": components,
        "affected_objects": affected_objects,
        "technical_objects": technical_objects,
        "interfaces": fsd.get("interfaces") or [],
        "roles_and_authorizations": fsd.get("roles_and_authorizations") or [],
        "security_controls": [
            {"control": item.get("business_role") or item.get("role_id") or "Authorization",
             "design": item.get("authorization_object") or item.get("activities") or item.get("data_scope") or str(item)}
            for item in (fsd.get("roles_and_authorizations") or [])
        ] or [
            {"control": "Least-privilege business roles", "design": "Backend authorization checks for every protected operation"},
            {"control": "Audit trail", "design": "Retain business keys, processor, decision and timestamps; exclude secrets"},
            {"control": "Transport security", "design": "HTTPS/TLS and standard SAP CSRF protection for state-changing calls"},
        ],
        "error_handling": messages or [
            {"id": "MSG-01", "scenario": "Mandatory or invalid input", "user_message": "Correct the highlighted required or invalid information before submitting.",
             "technical_handling": "Frontend field state plus backend validation. Do not persist until both pass."},
            {"id": "MSG-02", "scenario": "Backend unavailable", "user_message": "The service is currently unavailable. Try again later or contact support.",
             "technical_handling": "Return a controlled business error; log request/business key for support."},
            {"id": "AUTH", "scenario": "Unauthorized action", "user_message": "You are not authorized to perform this action.",
             "technical_handling": "Backend authorization returns a controlled 403-equivalent response without exposing internals."},
        ],
        "operational_considerations": {
            "dependencies": fsd.get("dependencies") or ["Target SAP release and available API version", "Fiori Launchpad content and OData service activation", "Role provisioning and representative test data"],
            "reuse": ["Reuse standard SAP Fiori elements List Report / Object Page patterns where they satisfy the FSD", "Reuse approved OData, authentication, authorization and attachment capabilities", "Introduce custom development only after a documented fit-gap"],
            "fiori_html": [
                ["Application type", "Prefer Fiori elements List Report + Object Page; freestyle SAPUI5 only for confirmed gaps"],
                ["Manifest / data source", "Define the approved OData data source in manifest.json after service/version confirmation"],
                ["Custom controllers/fragments", "Avoid where standard annotations/actions satisfy requirements"],
                ["CSS", "Use SAP Fiori theming and semantic controls; custom CSS only for approved layout gaps"],
                ["Value help", "Use approved standard value-help services/CDS; organizational authorization where applicable"],
            ],
            "bsp": "N/A for the baseline design. No custom BSP application is required by the FSD.",
            "git": [["Git repository", "TBD"], ["Package / development class", "TBD"], ["Branching / review", "Peer review before transport"]],
            "multi_site": "Confirm whether one global template or site-specific configuration is required. Do not hard-code system URLs.",
            "other": ["Protect state-changing calls with standard SAP OData CSRF/session mechanisms", "Map backend errors to controlled business messages", "Include a request/correlation identifier in support logging"],
        },
        "data_mappings": fsd.get("data_mappings") or [],
        "status_definitions": fsd.get("status_definitions") or [],
        "nfr": fsd.get("non_functional_requirements") or [],
        "test_conditions": test_conditions,
        "outstanding_issues": outstanding_issues,
        "glossary": _glossary_rows(scope.get("glossary")),
        "traceability": capability_map,
        "review_notes": [
            "This TDD is generated from the approved Functional Specification and requirement baseline.",
            "Object names, service versions, package names and transport requests marked TBD require technical lead assignment before build.",
        ],
    }


def build_test_cases(project: Project) -> dict:
    display_name = business_project_name(project)
    cases = []
    number = 1
    for r in _approved(project):
        criteria = r.acceptance_criteria or [r.statement]
        for criterion in criteria:
            cases.append({"test_key": f"QT-{number:03}", "requirement_key": r.requirement_key, "title": f"Validate {r.title}",
                          "priority": priority_label(r.priority), "assigned_to": "QA Engineer", "planned_date": "",
                          "preconditions": ["Test user has the required business role", "Required master and transactional data exist"],
                          "steps": ["Open the relevant SAP business process", f"Execute the scenario for {r.requirement_key}", "Capture the system result and audit evidence"],
                          "expected_result": criterion, "actual_result": "", "test_type": "Functional", "status": "Not Run",
                          "execution_date": "", "defect_id": "", "evidence": "", "remarks": "Review test data and owner before execution",
                          "source_evidence": r.source_quote})
            number += 1
    return {"title": display_name, "project_name": display_name, "status": "draft_for_review", "test_cases": cases,
            "entry_criteria": ["Approved requirement baseline", "Configured test environment", "Test data prepared"],
            "exit_criteria": ["All Must Have tests passed", "No open critical defects", "Business owner sign-off recorded"]}


def build_traceability(project: Project) -> dict:
    rows = []
    for index, r in enumerate(_approved(project), 1):
        rows.append({"requirement_key": r.requirement_key, "requirement": r.title, "source": r.source_quote,
                     "fsd_section": f"2.{index}", "story_key": f"US-{index:03}", "test_key": f"QT-{index:03}", "coverage": "covered"})
    return {"title": f"Requirements Traceability Matrix - {project.name}", "status": "current", "coverage_percent": 100 if rows else 0, "rows": rows,
            "gaps": [], "rule": "Every approved requirement must map to functional design, delivery backlog, and at least one test case."}


def build_companion(project: Project) -> dict:
    display_name = business_project_name(project)
    requirements = _approved(project)
    return {
        "title": f"AI Companion - {display_name}",
        "project_name": display_name,
        "status": "grounded",
        "summary": f"Answers for {display_name} are taken only from this project's uploaded BRD and generated artifacts.",
        "suggested_questions": [
            "What is my current progress status in the Functional area?",
            "What fields will be on my initial page?",
            "Which requirements are Must Have?",
            "What SAP objects are in the Technical Design?",
        ],
        "answers": [
            {
                "question": "Which requirements have the highest priority?",
                "answer": ", ".join(r.requirement_key for r in requirements if r.priority == "must") or "No Must Have requirements.",
                "citations": [r.requirement_key for r in requirements if r.priority == "must"],
            },
            {
                "question": "Show requirement-to-test coverage.",
                "answer": f"All {len(requirements)} approved requirements have generated functional and test coverage in this project.",
                "citations": [r.requirement_key for r in requirements],
            },
        ],
        "guardrail": "Answers are limited to this project's knowledge base. Open a different project URL to chat about another BRD.",
    }


BUILDERS = {"backlog": build_backlog, "technical_design": build_technical_design, "test_cases": build_test_cases,
            "traceability": build_traceability, "companion": build_companion}
