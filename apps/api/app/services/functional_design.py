import json
import math
from collections.abc import Callable

from openai import OpenAI, OpenAIError

from ..config import settings
from ..fsd_schemas import FSDDesignDraft
from ..fsd_template import get_fsd_template
from ..models import Project, ReviewStatus
from .openai_support import AIServiceError, Usage, response_usage
from .process_design import (
    build_actors,
    build_process_steps,
    build_screens,
    process_flow_mermaid,
    screen_navigation_mermaid,
)
from .project_identity import business_project_name, looks_like_person_name, process_identifier
from .timing import timed


ProgressCallback = Callable[[str, int], None]


@timed("AI design and deterministic expansion")
def build_functional_specification(project: Project, progress: ProgressCallback | None = None) -> tuple[dict, Usage | None]:
    approved = [r for r in project.requirements if r.review_status == ReviewStatus.approved]
    if progress:
        progress(f"Preparing {len(approved)} approved requirements for the combined FSD template", 15)
    if settings.openai_api_key:
        try:
            template = get_fsd_template()
            client = OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_fsd_timeout_seconds,
                            max_retries=settings.openai_fsd_max_retries)
            requirement_input = [{
                "id": r.requirement_key,
                "title": r.title,
                "statement": r.statement,
                "type": r.requirement_type,
                "priority": r.priority,
                "rationale": r.rationale or "",
                "acceptance_criteria": r.acceptance_criteria,
                "assumptions": r.assumptions,
                "source_quote": r.source_quote,
                "source_locators": [c.locator for c in project.document.chunks if c.id in r.source_chunk_ids],
            } for r in approved]
            knowledge = getattr(project, "brd_knowledge", None)
            brd_context = knowledge.payload if knowledge and isinstance(knowledge.payload, dict) else {
                "coverage_notes": ["No persisted BRD knowledge is available; use the approved requirement baseline only."]
            }
            model_input = {
                "project": {
                    "name": project.name,
                    "source_document": project.document.filename,
                    "brd_knowledge_version": knowledge.extraction_version if knowledge else None,
                    "brd_knowledge_coverage_percent": knowledge.coverage_percent if knowledge else None,
                },
                "brd_knowledge": brd_context,
                "approved_requirements": requirement_input,
            }
            compact_input = json.dumps(model_input, ensure_ascii=False, separators=(",", ":"))
            if progress:
                progress(
                    f"Sending BRD knowledge + {len(approved)} approved requirements "
                    f"({len(compact_input):,} characters) to {settings.openai_fsd_model}", 30
                )
            response = client.responses.parse(
                model=settings.openai_fsd_model, instructions=template.prompt,
                input="FSD PROJECT CONTEXT JSON:\n" + compact_input,
                text_format=FSDDesignDraft, max_output_tokens=settings.openai_fsd_max_output_tokens,
                reasoning={"effort": "low"}, text={"verbosity": "low"},
                store=False, prompt_cache_key=f"sap-copilot-{template.template_version}-prompt-{template.prompt_version}",
            )
            if not response.output_parsed:
                raise AIServiceError("OpenAI returned no parsed FSD output")
            if progress:
                progress("Compact design received; expanding requirements, tests and traceability locally", 82)
            return _compose_design_draft(response.output_parsed.model_dump(), project), response_usage(response, settings.openai_fsd_model)
        except (OpenAIError, AIServiceError, ValueError) as exc:
            if not settings.openai_allow_demo_fallback:
                raise AIServiceError(f"FSD generation failed: {exc}") from exc
    if progress:
        progress("OpenAI key not configured; generating the local demonstration FSD", 50)
    return _build_demo_fsd(project), None


def _screen(screen_id: str, name: str, purpose: str, requirements: list, detail: bool = False) -> dict:
    requirement_ids = [r.requirement_key for r in requirements]
    fields = [{"field_id": f"{screen_id}-FLD-{index:02}", "label": r.title, "control": "Input" if detail else "Filter / table column",
        "data_type": "Text", "required": "TBD", "editable": "Yes" if detail else "No", "source_or_default": "Approved process data",
        "validation": r.statement, "value_help": "TBD", "requirement_ids": [r.requirement_key]} for index, r in enumerate(requirements[:25], 1)]
    floorplan = "SAP Fiori elements - Object Page" if detail else "SAP Fiori elements - List Report"
    wireframe = ("Shell Bar > Dynamic Page Header > Object Header and Status > Anchor Navigation > Content Sections > Footer Toolbar"
                 if detail else "Shell Bar > Dynamic Page Header > Variant and Filter Bar > Responsive Table > Table Toolbar")
    return {"screen_id": screen_id, "name": name, "purpose": purpose, "roles": ["Business User"],
        "entry_point": "Fiori Launchpad", "exit_conditions": ["User navigates to the next page or completes processing"],
        "proposed_technology": floorplan, "requirement_ids": requirement_ids,
        "ascii_wireframe": wireframe, "fields": fields,
        "actions": [{"action": "Open Details" if not detail else "Validate and Submit", "enabled_when": "User has access and required data is available",
            "processing": purpose, "success_result": "The next page or confirmation is displayed", "failure_result": "An actionable message is displayed",
            "authorization": "TBD", "requirement_ids": requirement_ids}], "messages": []}


def _grouped_process_steps(requirements: list, limit: int) -> list[dict]:
    if not requirements:
        return []
    chunk_size = max(1, math.ceil(len(requirements) / limit))
    groups = [requirements[index:index + chunk_size] for index in range(0, len(requirements), chunk_size)][:limit]
    return [{
        "step_id": f"STEP-{index:02}", "actor": "Business User / SAP",
        "activity": f"Execute approved requirement group {index}",
        "system_behavior": "; ".join(item.statement for item in group[:3]) +
                           (f"; plus {len(group) - 3} additional approved behaviors" if len(group) > 3 else ""),
        "decision_or_rule": "Apply only the cited approved requirements",
        "outcome": "All cited requirements in this process group are satisfied or routed to a controlled exception",
        "requirement_ids": [item.requirement_key for item in group],
    } for index, group in enumerate(groups, 1)]


def _grouped_business_rules(requirements: list, limit: int) -> list[dict]:
    if not requirements:
        return []
    chunk_size = max(1, math.ceil(len(requirements) / limit))
    groups = [requirements[index:index + chunk_size] for index in range(0, len(requirements), chunk_size)][:limit]
    return [{
        "rule_id": f"RULE-{index:02}",
        "description": f"Apply the approved controls for requirement group {index}",
        "condition": "When the cited approved business scenario occurs",
        "result": "; ".join(item.acceptance_criteria[0] if item.acceptance_criteria else item.statement for item in group[:3]) +
                  (f"; plus {len(group) - 3} additional cited outcomes" if len(group) > 3 else ""),
        "requirement_ids": [item.requirement_key for item in group],
    } for index, group in enumerate(groups, 1)]


def _grouped_test_conditions(requirements: list, limit: int) -> list[dict]:
    if not requirements:
        return []
    chunk_size = max(1, math.ceil(len(requirements) / limit))
    groups = [requirements[index:index + chunk_size] for index in range(0, len(requirements), chunk_size)][:limit]
    return [{
        "test_id": f"TEST-{index:02}",
        "requirement_ids": [item.requirement_key for item in group],
        "scenario": f"Validate approved requirement group {index}",
        "preconditions": ["Representative test data and required access are available"],
        "steps": [item.statement for item in group[:3]] + ([f"Execute the remaining {len(group) - 3} cited requirement scenarios in this group."] if len(group) > 3 else []),
        "expected_result": "; ".join(item.acceptance_criteria[0] if item.acceptance_criteria else item.statement for item in group[:3]) +
                           (f"; plus {len(group) - 3} additional cited outcomes" if len(group) > 3 else ""),
        "test_type": "Functional",
    } for index, group in enumerate(groups, 1)]


@timed("Ground and bound FSD content")
def _enhance_fsd(data: dict, project: Project) -> dict:
    approved = [r for r in project.requirements if r.review_status == ReviewStatus.approved]
    template = get_fsd_template()
    display_name = business_project_name(project)
    data["title"] = display_name
    data["version"] = "1.0"
    data["status"] = "draft_for_review"
    data["purpose"] = "Translate the approved, source-linked BRD baseline into a review-ready SAP functional design."
    data["revision_history"] = [{"version": "1.0", "date": project.created_at.date().isoformat(),
        "author": "SAP Project Copilot", "description": "Initial draft generated from approved BRD requirements"}]
    data["sign_offs"] = [
        {"role": "Business Process Owner", "name": "TBD", "status": "Pending"},
        {"role": "SAP Functional Lead", "name": "TBD", "status": "Pending"},
        {"role": "IT / Technical Lead", "name": "TBD", "status": "Pending"},
    ]
    data["relevant_documents"] = [project.document.filename]
    info = data.setdefault("document_information", {})
    info["process_identifier"] = process_identifier(project)
    info["classification"] = info.get("classification") or template.branding["classification_default"]
    info["prepared_by"] = "SAP Project Copilot"

    approved_ids = {requirement.requirement_key for requirement in approved}
    # The model is allowed to summarize design content, but the approved
    # baseline is authoritative. Rebuild this collection in baseline order so
    # large BRDs cannot lose requirements when the model reaches its output
    # token limit.
    requirement_rows = {
        row.get("requirement_id"): row
        for row in data.get("requirements", [])
        if row.get("requirement_id") in approved_ids
    }
    normalized_requirements = []
    for requirement in approved:
        row = requirement_rows.get(requirement.requirement_key)
        if not row:
            row = {
                "requirement_id": requirement.requirement_key,
                "requirement_key": requirement.requirement_key,
                "title": requirement.title,
                "priority": requirement.priority,
                "actors": ["Business User"],
                "trigger": "The relevant business-process event occurs",
                "preconditions": ["Required access, master data, and process context are available"],
                "functional_behavior": requirement.statement,
                "postconditions": ["The approved requirement outcome is recorded and available for review"],
                "acceptance_criteria": requirement.acceptance_criteria,
                "assumptions": requirement.assumptions,
            }
        locator = ", ".join(c.locator for c in project.document.chunks if c.id in requirement.source_chunk_ids) or "TBD"
        row["requirement_id"] = requirement.requirement_key
        row["requirement_key"] = requirement.requirement_key
        row["title"] = row.get("title") or requirement.title
        row["priority"] = row.get("priority") or requirement.priority
        row["functional_behavior"] = row.get("functional_behavior") or requirement.statement
        row["acceptance_criteria"] = row.get("acceptance_criteria") or requirement.acceptance_criteria
        row["assumptions"] = row.get("assumptions") or requirement.assumptions
        row["source"] = {"requirement_id": requirement.requirement_key, "source_locator": locator,
                         "source_quote": requirement.source_quote}
        row["source_quote"] = requirement.source_quote
        normalized_requirements.append(row)
    data["requirements"] = normalized_requirements

    limits = template.content_limits
    removed_ungrounded = 0
    grounded_collections = (
        "actors_and_systems", "as_is_process_steps", "improvement_mapping", "process_steps",
        "process_flow_variants", "business_rules", "data_mappings", "status_definitions",
        "message_catalog", "non_functional_requirements", "configuration_items", "technical_objects",
        "interfaces", "roles_and_authorizations", "risks",
    )
    for collection in grounded_collections:
        grounded_rows = []
        for record in data.get(collection, []):
            record["requirement_ids"] = [item for item in record.get("requirement_ids", []) if item in approved_ids]
            if record["requirement_ids"]:
                grounded_rows.append(record)
            else:
                removed_ungrounded += 1
        data[collection] = grounded_rows
    data["process_steps"] = build_process_steps(project, approved, data.get("process_steps"), limits["process_steps"])
    data["actors_and_systems"] = build_actors(data["process_steps"], approved)
    data["process_flow_mermaid"] = process_flow_mermaid(data["process_steps"])
    if not data.get("business_rules"):
        data["business_rules"] = _grouped_business_rules(approved, limits["business_rules"])
    if removed_ungrounded:
        data.setdefault("outstanding_issues", []).append({
            "issue_id": "ISSUE-GROUNDING-01",
            "description": f"{removed_ungrounded} generated design record(s) without an approved requirement reference were excluded.",
            "decision_required": "Confirm whether additional grounded design records are required.",
            "proposed_owner": "SAP Functional Lead", "priority": "High", "status": "Open",
        })
    if len(data.get("business_rules", [])) > limits["business_rules"]:
        data["business_rules"] = _grouped_business_rules(approved, limits["business_rules"])
    if len(data.get("processing_logic", [])) > limits["processing_logic"]:
        hidden = len(data["processing_logic"]) - limits["processing_logic"] + 1
        data["processing_logic"] = data["processing_logic"][:limits["processing_logic"] - 1] + [
            f"{hidden} additional approved behaviors are detailed in the requirement catalogue and traceability matrix."
        ]

    # Guarantee one grounded test and traceability row for every approved
    # requirement. Process steps and rules stay grouped in the compact design,
    # avoiding hundreds of repetitive model-authored records.
    data["test_conditions"] = _grouped_test_conditions(approved, limits["test_conditions"])

    process_by_requirement = {key: [] for key in approved_ids}
    rule_by_requirement = {key: [] for key in approved_ids}
    test_by_requirement = {key: [] for key in approved_ids}
    for row in data["process_steps"]:
        for key in row.get("requirement_ids", []):
            if key in process_by_requirement:
                process_by_requirement[key].append(row["step_id"])
    for row in data["business_rules"]:
        for key in row.get("requirement_ids", []):
            if key in rule_by_requirement:
                rule_by_requirement[key].append(row["rule_id"])
    for row in data["test_conditions"]:
        for key in row.get("requirement_ids", []):
            if key in test_by_requirement:
                test_by_requirement[key].append(row["test_id"])
    existing_trace = {row.get("requirement_id"): row for row in data.get("traceability", []) if row.get("requirement_id") in approved_ids}
    data["traceability"] = []
    for requirement in approved:
        locator = ", ".join(c.locator for c in project.document.chunks if c.id in requirement.source_chunk_ids) or "TBD"
        prior = existing_trace.get(requirement.requirement_key, {})
        data["traceability"].append({
            "requirement_id": requirement.requirement_key,
            "brd_source": locator,
            "process_step_ids": process_by_requirement[requirement.requirement_key],
            "screen_ids": prior.get("screen_ids", []),
            "rule_ids": rule_by_requirement[requirement.requirement_key],
            "interface_or_object_ids": prior.get("interface_or_object_ids", []),
            "test_ids": test_by_requirement[requirement.requirement_key],
            "coverage_status": "Covered",
        })
    scope = data.setdefault("scope", {})
    constraints = []
    as_is = []
    for requirement in approved[:12]:
        rationale = requirement.rationale.strip() if requirement.rationale else ""
        constraints.append((f"{requirement.title}: {rationale}. The target gap is that the current process does not consistently guarantee: {requirement.statement}"
                            if rationale and rationale.lower() != "not explicitly stated" else
                            f"{requirement.title}: the current process does not consistently guarantee: {requirement.statement}"))
        as_is.append(f"Current-state handling for {requirement.title} relies on the existing process; the approved BRD identifies a gap because it requires: {requirement.statement}")
    scope["as_is_process"] = scope.get("as_is_process") or as_is or ["The current process is not described in enough detail in the approved BRD; validate it during the fit-to-standard workshop."]
    scope["current_constraints"] = scope.get("current_constraints") or constraints or ["Current constraints are TBD pending business-process discovery."]
    for key in ("as_is_process", "current_constraints", "objectives", "in_scope", "out_of_scope", "glossary"):
        values = scope.get(key, [])
        if len(values) > 12:
            scope[key] = values[:11] + [f"{len(values) - 11} additional items are covered by the approved requirement catalogue."]
    data["as_is_narrative"] = data.get("as_is_narrative") or " ".join(scope["as_is_process"][:4])
    data["as_is_process_steps"] = data.get("as_is_process_steps") or [{
        "step_id": f"ASIS-{index:02}", "actor": "Business User / Existing Process", "activity": f"Current handling: {r.title}",
        "system_behavior": f"The existing process does not consistently guarantee the approved outcome: {r.statement}",
        "decision_or_rule": "Manual or inconsistent control", "outcome": "Constraint remains until the To-Be design is implemented",
        "requirement_ids": [r.requirement_key],
    } for index, r in enumerate(approved[:12], 1)]
    data["improvement_mapping"] = data.get("improvement_mapping") or [{
        "constraint": scope["current_constraints"][index - 1] if index - 1 < len(scope["current_constraints"]) else "Current-state constraint",
        "to_be_response": r.statement, "expected_improvement": r.acceptance_criteria[0] if r.acceptance_criteria else "Approved requirement outcome is achieved",
        "requirement_ids": [r.requirement_key],
    } for index, r in enumerate(approved[:12], 1)]
    flow_rows = data.get("process_flow_variants", [])
    for row in flow_rows:
        ids = row.get("requirement_ids", [])
        if isinstance(ids, str):
            row["requirement_ids"] = [item.strip() for item in ids.split(",") if item.strip()]
    if not flow_rows:
        flow_rows = [{"flow_type": "Primary", "trigger": "User starts the relevant process", "flow": "Execute approved process steps and validations", "expected_outcome": "Approved business outcome is recorded", "requirement_ids": [r.requirement_key for r in approved]},
                     {"flow_type": "Exception", "trigger": "Validation fails", "flow": "Stop processing, preserve entered data where safe, and display an actionable message", "expected_outcome": "No invalid or partial transaction is committed", "requirement_ids": [r.requirement_key for r in approved]}]
    elif not any(row["flow_type"].lower() == "primary" for row in flow_rows):
        flow_rows.insert(0, {"flow_type": "Primary", "trigger": "User starts the relevant process", "flow": "Execute the approved process steps and validations in sequence", "expected_outcome": "Approved business outcome is recorded", "requirement_ids": [r.requirement_key for r in approved]})
    data["process_flow_variants"] = flow_rows
    data["screens"] = build_screens(project, approved, data.get("screens"), display_name, limits)
    data["screen_navigation_mermaid"] = screen_navigation_mermaid(data["screens"])
    collection_limits = {
        "as_is_process_steps": limits["process_steps"], "improvement_mapping": limits["improvement_mappings"],
        "process_flow_variants": limits["flow_variants"], "configuration_items": limits["configuration_items"],
        "technical_objects": limits["technical_objects"], "interfaces": limits["interfaces"],
        "data_mappings": limits["data_mappings"], "status_definitions": limits["status_definitions"],
        "message_catalog": limits["message_catalog"], "non_functional_requirements": limits["non_functional_requirements"],
        "risks": limits["risks"], "outstanding_issues": limits["open_issues"],
    }
    for key, limit in collection_limits.items():
        data[key] = data.get(key, [])[:limit]
    defaults = {
        "reports_and_notifications": [], "configuration_items": [], "technical_objects": [],
        "data_mappings": [], "status_definitions": [], "message_catalog": [], "non_functional_requirements": [],
        "cross_process_impacts": [], "batch_jobs": [], "dependencies": [], "interfaces": [],
        "integration_sequence_mermaid": "Not applicable - no approved integration requirement was identified.",
        "assumptions": [], "roles_and_authorizations": [], "ricefw_inventory": [], "risks": [],
        "outstanding_issues": [], "localization_requirements": [],
        "review_checklist": [
            {"check": "Approved requirement coverage", "result": "Pass", "notes": "Validated automatically before rendering."},
            {"check": "Source evidence preserved", "result": "Pass", "notes": "Approved source quotes are copied deterministically."},
            {"check": "Human functional review", "result": "Pending", "notes": "Business and SAP leads must review this draft."},
        ],
    }
    for key, value in defaults.items():
        data.setdefault(key, value)
    if looks_like_person_name(project.name):
        for screen in data.get("screens") or []:
            name = str(screen.get("name") or "")
            if project.name and project.name in name:
                screen["name"] = name.replace(project.name, display_name)
    return data


@timed("Compose FSD v2 document")
def _compose_design_draft(draft: dict, project: Project) -> dict:
    """Merge compact AI decisions over the deterministic full FSD baseline."""
    document = _build_demo_fsd(project)
    for key, value in draft.items():
        document[key] = value
    return _enhance_fsd(document, project)


def _build_demo_fsd(project: Project) -> dict:
    approved = [r for r in project.requirements if r.review_status == ReviewStatus.approved]
    modules = sorted({r.requirement_type.replace("_", " ").title() for r in approved})
    requirement_ids = [r.requirement_key for r in approved]
    display_name = business_project_name(project)
    template = get_fsd_template()
    limits = template.content_limits
    process_steps = build_process_steps(project, approved, None, limits["process_steps"])
    actors = build_actors(process_steps, approved)
    screens = build_screens(project, approved, None, display_name, limits)
    return _enhance_fsd({
        "title": display_name,
        "version": "0.1",
        "status": "draft_for_review",
        "document_information": {"process_identifier": process_identifier(project), "classification": "Internal",
            "application": "SAP - TBD", "functional_area": ", ".join(modules) or "TBD", "prepared_by": "SAP Project Copilot"},
        "revision_history": [{"version": "0.1", "date": "TBD", "author": "SAP Project Copilot", "description": "Initial draft"}],
        "sign_offs": [{"role": "Business Process Owner", "name": "TBD", "status": "Pending"}],
        "relevant_documents": [project.document.filename],
        "purpose": "Translate the approved, source-linked business requirement baseline into a reviewable functional design.",
        "scope": {
            "business_context": "This design is grounded in the approved BRD requirement baseline.",
            "objectives": ["Provide a traceable functional design for every approved requirement."],
            "in_scope": [r.title for r in approved],
            "out_of_scope": ["Items not present in the approved requirement baseline", "Detailed ABAP or integration implementation design"],
            "glossary": ["BRD - Business Requirements Document", "FSD - Functional Specification Document"],
        },
        "functional_areas": modules,
        "actors_and_systems": actors,
        "future_state_narrative": "The current process constraints identified by the approved BRD are addressed through a controlled To-Be flow. Approved requirements are executed in sequence with explicit validations, traceable decisions and user-visible outcomes, reducing manual handling and preventing incomplete or unauthorized processing.",
        "process_steps": process_steps,
        "process_flow_mermaid": process_flow_mermaid(process_steps),
        "alternate_and_exception_flows": ["Exception | Validation failure | Stop processing, retain safe input and display a corrective message | No invalid transaction is committed | " + ", ".join(requirement_ids)],
        "requirements": [
            {
                "requirement_id": r.requirement_key,
                "requirement_key": r.requirement_key,
                "title": r.title,
                "functional_behavior": r.statement,
                "priority": r.priority,
                "actors": ["Business User"], "trigger": "User starts the relevant process",
                "preconditions": ["Required access and master data are available"],
                "postconditions": ["The result is recorded and displayed"],
                "acceptance_criteria": r.acceptance_criteria,
                "assumptions": r.assumptions,
                "source": {"requirement_id": r.requirement_key, "source_locator": "TBD", "source_quote": r.source_quote},
                "source_quote": r.source_quote,
            }
            for r in approved
        ],
        "processing_logic": [r.statement for r in approved],
        "business_rules": [{"rule_id": f"RULE-{index:02}", "description": r.statement,
            "condition": "When the requirement trigger occurs", "result": "Apply the required behavior",
            "requirement_ids": [r.requirement_key]} for index, r in enumerate(approved, 1)],
        "data_mappings": [],
        "status_definitions": [],
        "message_catalog": [],
        "non_functional_requirements": [],
        "screen_navigation_mermaid": screen_navigation_mermaid(screens),
        "screens": screens,
        "interfaces": [], "roles_and_authorizations": [],
        "test_conditions": [{"test_id": f"TEST-{index:02}", "requirement_ids": [r.requirement_key],
            "scenario": r.title, "preconditions": ["Test data is available"], "steps": [r.statement],
            "expected_result": r.acceptance_criteria[0] if r.acceptance_criteria else "Requirement is satisfied",
            "test_type": "Functional"} for index, r in enumerate(approved, 1)],
        "traceability": [{"requirement_id": r.requirement_key, "brd_source": "TBD",
            "process_step_ids": [f"STEP-{index:02}"], "screen_ids": [f"SCR-{index:02}"] if index <= len(screens) else [],
            "rule_ids": [f"RULE-{index:02}"], "interface_or_object_ids": [], "test_ids": [f"TEST-{index:02}"],
            "coverage_status": "Covered"} for index, r in enumerate(approved, 1)],
        "risks": [], "outstanding_issues": [],
        "controls": [
            "All design decisions must remain traceable to an approved requirement.",
            "Unresolved SAP configuration and integration choices require functional consultant review.",
            "Rejected requirements are excluded from this specification.",
        ],
        "open_questions": [
            "Which SAP modules, organizational units, and deployment landscape are in scope?",
            "Which requirements use standard configuration versus extension or custom development?",
            "Who owns final business acceptance for each functional area?",
        ],
    }, project)
