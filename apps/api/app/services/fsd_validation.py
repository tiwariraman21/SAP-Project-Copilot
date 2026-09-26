from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable

from pydantic import ValidationError

from ..fsd_schemas import FSDDocument
from ..fsd_template import get_fsd_template
from ..models import Project, ReviewStatus
from .openai_support import AIServiceError
from .timing import timed


class FSDValidationError(AIServiceError):
    def __init__(self, report: dict[str, Any]):
        self.report = report
        super().__init__("FSD release validation failed: " + "; ".join(report["errors"]))


def _ids(records: Iterable[dict[str, Any]], field: str = "requirement_ids") -> list[str]:
    values: list[str] = []
    for record in records:
        candidate = record.get(field, [])
        values.extend(candidate if isinstance(candidate, list) else [str(candidate)])
    return values


def _count_tbd(value: Any) -> int:
    if isinstance(value, dict):
        return sum(_count_tbd(item) for item in value.values())
    if isinstance(value, list):
        return sum(_count_tbd(item) for item in value)
    return len(re.findall(r"\bTBD\b", str(value), flags=re.IGNORECASE))


@timed("Validate evidence, coverage and limits")
def validate_fsd_document(document: dict[str, Any], project: Project) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate and normalize model content before deterministic rendering."""
    template = get_fsd_template()
    errors: list[str] = []
    warnings: list[str] = []
    try:
        normalized = FSDDocument.model_validate(document).model_dump()
    except ValidationError as exc:
        report = {
            **template.provenance(), "passed": False,
            "errors": [f"Structured FSD schema mismatch: {exc.error_count()} validation error(s)"],
            "warnings": [], "metrics": {"schema_errors": exc.error_count()},
        }
        raise FSDValidationError(report) from exc

    approved = [item for item in project.requirements if item.review_status == ReviewStatus.approved]
    approved_ids = {item.requirement_key for item in approved}
    requirement_rows = normalized["requirements"]
    generated_ids = [item["requirement_id"] for item in requirement_rows]
    generated_set = set(generated_ids)
    duplicate_ids = sorted(key for key, count in Counter(generated_ids).items() if count > 1)
    missing_requirements = sorted(approved_ids - generated_set)
    unknown_requirements = sorted(generated_set - approved_ids)
    if duplicate_ids:
        errors.append("Duplicate functional requirement rows: " + ", ".join(duplicate_ids))
    if missing_requirements:
        errors.append("Approved requirements missing from the FSD: " + ", ".join(missing_requirements))
    if unknown_requirements:
        errors.append("The FSD contains unapproved requirements: " + ", ".join(unknown_requirements))

    approved_by_id = {item.requirement_key: item for item in approved}
    for row in requirement_rows:
        source = row["source"]
        approved_item = approved_by_id.get(row["requirement_id"])
        if not approved_item:
            continue
        if source["requirement_id"] != row["requirement_id"]:
            errors.append(f"{row['requirement_id']} has a mismatched source requirement ID")
        if not source["source_locator"].strip() or not source["source_quote"].strip():
            errors.append(f"{row['requirement_id']} is missing source evidence")
        if source["source_quote"].strip() != approved_item.source_quote.strip():
            errors.append(f"{row['requirement_id']} changed its approved source quote")

    reference_groups = {
        "actors": _ids(normalized["actors_and_systems"]),
        "as-is steps": _ids(normalized["as_is_process_steps"]),
        "improvements": _ids(normalized["improvement_mapping"]),
        "process steps": _ids(normalized["process_steps"]),
        "flow variants": _ids(normalized["process_flow_variants"]),
        "business rules": _ids(normalized["business_rules"]),
        "data mappings": _ids(normalized["data_mappings"]),
        "status definitions": _ids(normalized["status_definitions"]),
        "message catalog": _ids(normalized["message_catalog"]),
        "non-functional requirements": _ids(normalized["non_functional_requirements"]),
        "screens": _ids(normalized["screens"]),
        "configuration": _ids(normalized["configuration_items"]),
        "technical objects": _ids(normalized["technical_objects"]),
        "interfaces": _ids(normalized["interfaces"]),
        "roles": _ids(normalized["roles_and_authorizations"]),
        "tests": _ids(normalized["test_conditions"]),
        "risks": _ids(normalized["risks"]),
        "screen fields": _ids([field for screen in normalized["screens"] for field in screen["fields"]]),
        "screen actions": _ids([action for screen in normalized["screens"] for action in screen["actions"]]),
        "screen messages": _ids([message for screen in normalized["screens"] for message in screen["messages"]]),
    }
    unknown_references = sorted({item for values in reference_groups.values() for item in values if item not in approved_ids})
    if unknown_references:
        errors.append("Unknown requirement references: " + ", ".join(unknown_references))
    test_coverage_ids = set(reference_groups["tests"])
    missing_test_coverage = sorted(approved_ids - test_coverage_ids)
    if missing_test_coverage:
        errors.append("Approved requirements missing from functional tests: " + ", ".join(missing_test_coverage))

    grounded_collections = {
        "actors and systems": normalized["actors_and_systems"], "as-is steps": normalized["as_is_process_steps"],
        "improvement mappings": normalized["improvement_mapping"], "process steps": normalized["process_steps"],
        "flow variants": normalized["process_flow_variants"], "business rules": normalized["business_rules"],
        "data mappings": normalized["data_mappings"], "status definitions": normalized["status_definitions"],
        "message catalog": normalized["message_catalog"], "non-functional requirements": normalized["non_functional_requirements"],
        "screens": normalized["screens"], "configuration items": normalized["configuration_items"],
        "technical objects": normalized["technical_objects"], "interfaces": normalized["interfaces"],
        "roles": normalized["roles_and_authorizations"], "risks": normalized["risks"],
    }
    ungrounded_records = [f"{label}[{index}]" for label, records in grounded_collections.items()
                          for index, record in enumerate(records, 1) if not record.get("requirement_ids")]
    if ungrounded_records:
        errors.append("Design records without an approved requirement reference: " + ", ".join(ungrounded_records))

    limits = template.content_limits
    bounded_collections = {
        "process_steps": (normalized["process_steps"], limits["process_steps"]),
        "business_rules": (normalized["business_rules"], limits["business_rules"]),
        "screens": (normalized["screens"], limits["screens"]),
        "test_conditions": (normalized["test_conditions"], limits["test_conditions"]),
        "process_flow_variants": (normalized["process_flow_variants"], limits["flow_variants"]),
        "improvement_mapping": (normalized["improvement_mapping"], limits["improvement_mappings"]),
        "data_mappings": (normalized["data_mappings"], limits["data_mappings"]),
        "status_definitions": (normalized["status_definitions"], limits["status_definitions"]),
        "message_catalog": (normalized["message_catalog"], limits["message_catalog"]),
        "non_functional_requirements": (normalized["non_functional_requirements"], limits["non_functional_requirements"]),
    }
    for label, (records, maximum) in bounded_collections.items():
        if len(records) > maximum:
            errors.append(f"{label} exceeds the fixed template limit of {maximum}")

    trace_ids = {row["requirement_id"] for row in normalized["traceability"]}
    missing_traceability = sorted(approved_ids - trace_ids)
    unknown_traceability = sorted(trace_ids - approved_ids)
    if missing_traceability:
        errors.append("Requirements missing from traceability: " + ", ".join(missing_traceability))
    if unknown_traceability:
        errors.append("Traceability contains unapproved IDs: " + ", ".join(unknown_traceability))

    if len(normalized["screens"]) < template.minimum_screens:
        errors.append(f"At least {template.minimum_screens} Fiori screen specifications are required")
    for collection in template.required_collections:
        if not normalized.get(collection):
            errors.append(f"Mandatory FSD collection is empty: {collection}")

    steps = normalized.get("process_steps") or []
    if len(steps) > 12:
        errors.append(f"Process steps count ({len(steps)}) exceeds maximum limit of 12")

    brd_knowledge = getattr(project, "brd_knowledge", None)
    brd_payload = getattr(brd_knowledge, "payload", {}) if brd_knowledge else {}
    if not isinstance(brd_payload, dict):
        brd_payload = {}

    blob = " ".join(str(v) for v in [
        brd_payload.get("business_context"),
        [s.get("activity") for s in brd_payload.get("process_steps") or [] if isinstance(s, dict)],
        [r.statement for r in approved],
    ]).lower()
    has_approval_context = bool(re.search(r"\b(approve|approval|approver|validat|decision)\b", blob))
    if has_approval_context and steps and not any(s.get("step_type") == "decision" for s in steps):
        errors.append("Process graph missing decision step for approval/validation workflow")

    brd_fields_count = len(brd_payload.get("data_fields") or []) + len([
        f for sc in brd_payload.get("screens") or [] if isinstance(sc, dict)
        for f in (sc.get("fields") or [])
    ])
    if brd_fields_count > 0:
        approved_titles = {str(item.title or "").strip().lower() for item in approved}
        for sc in normalized.get("screens") or []:
            sc_fields = [str(f.get("label") or "").strip().lower() for f in sc.get("fields") or [] if f.get("label")]
            if sc_fields and all(f in approved_titles for f in sc_fields):
                errors.append(f"Screen {sc.get('screen_id')} uses requirement titles instead of BRD business fields")
                break

    brd_knowledge = getattr(project, "brd_knowledge", None)
    brd_coverage = float(brd_knowledge.coverage_percent) if brd_knowledge else 0.0
    if brd_knowledge and brd_coverage < 100.0:
        warnings.append(f"Persisted BRD knowledge coverage is {brd_coverage:.1f}%; review extraction completeness")
    elif not brd_knowledge:
        warnings.append("No persisted full-BRD knowledge was available; the FSD used the approved requirement baseline only")

    tbd_count = _count_tbd(normalized)
    if tbd_count:
        warnings.append(f"{tbd_count} unresolved TBD marker(s) require human review")
    empty_optional = [key for key in ("interfaces", "risks", "localization_requirements", "ricefw_inventory") if not normalized.get(key)]
    if empty_optional:
        warnings.append("Optional sections with no grounded entries: " + ", ".join(empty_optional))

    report = {
        **template.provenance(),
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "approved_requirements": len(approved_ids),
            "functional_requirement_rows": len(generated_ids),
            "requirement_coverage_percent": round(100 * len(approved_ids & generated_set) / max(1, len(approved_ids)), 1),
            "traceability_coverage_percent": round(100 * len(approved_ids & trace_ids) / max(1, len(approved_ids)), 1),
            "test_coverage_percent": round(100 * len(approved_ids & test_coverage_ids) / max(1, len(approved_ids)), 1),
            "unknown_requirement_references": len(unknown_references),
            "ungrounded_design_records": len(ungrounded_records),
            "screen_count": len(normalized["screens"]),
            "test_count": len(normalized["test_conditions"]),
            "brd_knowledge_available": bool(brd_knowledge),
            "brd_knowledge_coverage_percent": brd_coverage,
            "tbd_count": tbd_count,
        },
    }
    if errors:
        raise FSDValidationError(report)
    return normalized, report
