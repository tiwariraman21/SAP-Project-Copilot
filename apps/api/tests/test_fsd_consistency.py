from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.fsd_template import get_fsd_template
from app.fsd_schemas import FSDDesignDraft
from app.config import settings
from app.main import fsd_cached_document, fsd_generation_metadata
from app.models import ReviewStatus
from app.services.fsd_validation import FSDValidationError, validate_fsd_document
from app.services.functional_design import _build_demo_fsd, _compose_design_draft, _enhance_fsd
from app.services.openai_support import Usage
import app.services.functional_design as functional_design


def _project():
    chunk = SimpleNamespace(id="chunk-1", locator="Page 1, paragraph 1")
    requirement = SimpleNamespace(
        requirement_key="REQ-001", title="Validate supplier status",
        statement="The system must validate supplier status before approval.",
        requirement_type="functional", priority="must", rationale="Prevent invalid approval.",
        acceptance_criteria=["Approval is blocked when supplier status is invalid."], assumptions=[],
        source_chunk_ids=[chunk.id], source_quote="The system must validate supplier status before approval.",
        review_status=ReviewStatus.approved,
    )
    document = SimpleNamespace(filename="supplier-brd.txt", chunks=[chunk])
    brd_knowledge = SimpleNamespace(
        extraction_version="brd-knowledge-v1", model="test-brd-model", coverage_percent=100.0,
        payload={
            "business_context": "Supplier governance BRD context",
            "screens": [{"screen_id": "BRD-SCR-01", "name": "Supplier Overview"}],
            "data_fields": [{"field_name": "Supplier Status", "source_system": "SAP S/4HANA"}],
        },
    )
    return SimpleNamespace(name="Supplier Governance", created_at=datetime(2026, 8, 24),
                           requirements=[requirement], document=document, brd_knowledge=brd_knowledge)


def test_common_template_and_local_generation_are_stable():
    project = _project()
    first = _build_demo_fsd(project)
    second = _build_demo_fsd(project)
    normalized, report = validate_fsd_document(first, project)

    assert first == second
    assert get_fsd_template() is get_fsd_template()
    assert get_fsd_template().template_version == "fsd-master-v3"
    assert len(get_fsd_template().sections) == 16
    assert normalized["title"] == "Supplier Governance"
    assert normalized["document_information"]["process_identifier"] == "SUPPLIER-GOVERNANCE"
    assert report["passed"] is True
    assert report["metrics"]["requirement_coverage_percent"] == 100.0
    assert report["metrics"]["traceability_coverage_percent"] == 100.0


def test_person_named_project_uses_brd_process_title():
    project = _project()
    project.name = "Anurag Umale"
    document = _build_demo_fsd(project)

    assert document["title"] == "Supplier Governance"
    assert document["document_information"]["process_identifier"] == "SUPPLIER-GOVERNANCE"
    assert "Anurag" not in document["title"]
    assert all("Anurag" not in str(screen.get("name")) for screen in document["screens"])


def test_release_gate_rejects_missing_traceability():
    project = _project()
    document = deepcopy(_build_demo_fsd(project))
    document["traceability"] = []

    with pytest.raises(FSDValidationError) as error:
        validate_fsd_document(document, project)

    assert "Requirements missing from traceability" in str(error.value)


def test_partial_model_output_is_completed_from_approved_baseline():
    project = _project()
    second = deepcopy(project.requirements[0])
    second.requirement_key = "REQ-002"
    second.title = "Record approval decision"
    second.statement = "The system shall record the approval decision for audit reporting."
    second.source_quote = second.statement
    project.requirements.append(second)

    partial = _build_demo_fsd(project)
    partial["requirements"] = partial["requirements"][:1]
    partial["process_steps"] = partial["process_steps"][:1]
    partial["business_rules"] = partial["business_rules"][:1]
    partial["test_conditions"] = partial["test_conditions"][:1]
    partial["traceability"] = partial["traceability"][:1]

    completed = _enhance_fsd(partial, project)
    normalized, report = validate_fsd_document(completed, project)

    assert [row["requirement_id"] for row in normalized["requirements"]] == ["REQ-001", "REQ-002"]
    assert [row["requirement_id"] for row in normalized["traceability"]] == ["REQ-001", "REQ-002"]
    assert report["passed"] is True
    assert report["metrics"]["requirement_coverage_percent"] == 100.0
    assert report["metrics"]["traceability_coverage_percent"] == 100.0


def test_large_baseline_repairs_model_output_truncated_at_44_requirements():
    project = _project()
    original = project.requirements[0]
    project.requirements = []
    for index in range(1, 142):
        requirement = deepcopy(original)
        requirement.requirement_key = f"REQ-{index:03}"
        requirement.title = f"Approved requirement {index}"
        requirement.statement = f"The system shall satisfy approved requirement {index}."
        requirement.source_quote = requirement.statement
        project.requirements.append(requirement)

    partial = _build_demo_fsd(project)
    for collection in ("requirements", "process_steps", "business_rules", "test_conditions", "traceability"):
        partial[collection] = partial[collection][:44]

    normalized, report = validate_fsd_document(_enhance_fsd(partial, project), project)

    assert len(normalized["requirements"]) == 141
    assert len(normalized["traceability"]) == 141
    assert len(normalized["process_steps"]) <= 12
    assert len(normalized["business_rules"]) <= 20
    assert len(normalized["screens"]) <= 10
    assert len(normalized["test_conditions"]) <= 30
    assert report["metrics"]["requirement_coverage_percent"] == 100.0
    assert report["metrics"]["traceability_coverage_percent"] == 100.0


def test_compact_design_is_expanded_into_the_full_contract():
    project = _project()
    full = _build_demo_fsd(project)
    draft = FSDDesignDraft.model_validate({key: full[key] for key in FSDDesignDraft.model_fields}).model_dump()

    completed = _compose_design_draft(draft, project)
    normalized, report = validate_fsd_document(completed, project)

    assert len(normalized["requirements"]) == 1
    assert len(normalized["test_conditions"]) == 1
    assert report["passed"] is True


def test_fsd_cache_is_invalidated_when_the_approved_baseline_changes():
    project = _project()
    document = _build_demo_fsd(project)
    expected_model = settings.openai_fsd_model if settings.openai_api_key else "local-demo"
    usage = Usage(model=expected_model, input_tokens=1, output_tokens=1, total_tokens=2)
    artifact = SimpleNamespace(payload={"document": document, "generation": fsd_generation_metadata(project, usage)})

    assert fsd_cached_document(project, artifact) == document
    project.requirements[0].statement += " Changed."
    assert fsd_cached_document(project, artifact) is None


def test_responses_request_uses_nested_text_verbosity(monkeypatch):
    project = _project()
    full = _build_demo_fsd(project)
    draft = FSDDesignDraft.model_validate({key: full[key] for key in FSDDesignDraft.model_fields})
    captured = {}

    class FakeResponses:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_parsed=draft,
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=20, total_tokens=30))

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr(functional_design, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    document, usage = functional_design.build_functional_specification(project)

    assert document["requirements"][0]["requirement_id"] == "REQ-001"
    assert usage.total_tokens == 30
    assert captured["text"] == {"verbosity": "low"}
    assert "verbosity" not in captured
    assert "FSD PROJECT CONTEXT JSON:" in captured["input"]
    assert '"brd_knowledge"' in captured["input"]
    assert '"approved_requirements"' in captured["input"]
    assert "Supplier governance BRD context" in captured["input"]


def test_ungrounded_design_records_are_removed_and_reported():
    project = _project()
    document = _build_demo_fsd(project)
    document["interfaces"] = [{
        "interface_id": "INT-HALLUCINATED", "name": "Uncited API", "direction": "Outbound",
        "purpose": "Not grounded", "source": "TBD", "target": "TBD", "trigger": "TBD",
        "payload_summary": "TBD", "error_handling": "TBD", "security": "TBD", "requirement_ids": [],
    }]

    grounded = _enhance_fsd(document, project)
    normalized, report = validate_fsd_document(grounded, project)

    assert normalized["interfaces"] == []
    assert any(item["issue_id"] == "ISSUE-GROUNDING-01" for item in normalized["outstanding_issues"])
    assert report["metrics"]["ungrounded_design_records"] == 0
