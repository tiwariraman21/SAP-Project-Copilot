from datetime import datetime
from types import SimpleNamespace

from app.models import ReviewStatus
from app.services.companion_chat import answer_companion_question, companion_context
from app.services.downstream import build_backlog, build_companion, build_technical_design
from app.services.functional_design import _build_demo_fsd


def _requirement(**overrides):
    base = dict(
        requirement_key="REQ-001", title="Create purchase requisition",
        statement="The requester must create a purchase requisition.",
        requirement_type="functional", priority="must",
        acceptance_criteria=["Requisition is created"], source_chunk_ids=["chunk-1"],
        source_quote="The requester must create a purchase requisition.",
        review_status=ReviewStatus.approved, rationale="", assumptions=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _project():
    chunk = SimpleNamespace(id="chunk-1", locator="Page 1")
    document = SimpleNamespace(filename="purchase-requisition-approval-brd.txt", chunks=[chunk])
    project = SimpleNamespace(
        id="proj-companion",
        name="Anurag Umale",
        created_at=datetime(2026, 8, 31),
        document=document,
        requirements=[
            _requirement(),
            _requirement(requirement_key="REQ-002", title="Approve requisition", statement="The approver shall release the requisition.",
                         source_quote="The approver shall release the requisition."),
        ],
        artifacts=[],
        brd_knowledge=SimpleNamespace(payload={"business_context": "Purchase requisition approval process"}),
    )
    fsd = _build_demo_fsd(project)
    backlog = build_backlog(project)
    tdd = build_technical_design(project)
    project.artifacts = [
        SimpleNamespace(kind="fsd", status="generated", payload={"document": fsd}),
        SimpleNamespace(kind="backlog", status="generated", payload={"document": backlog}),
        SimpleNamespace(kind="technical_design", status="generated", payload={"document": tdd}),
        SimpleNamespace(kind="companion", status="placeholder", payload={"chat": []}),
    ]
    return project


def test_companion_answers_functional_progress_from_planning():
    result = answer_companion_question(_project(), "what is my current progress status in Functional area?")
    assert result["project_id"] == "proj-companion"
    assert "Anurag" not in result["answer"]
    assert result["project_name"] == "Purchase Requisition Approval"
    assert any(source["kind"] == "backlog" for source in result["sources"])
    assert "Project Planning" in result["answer"]
    assert "Not Started" in result["answer"]
    assert "US-001" in result["answer"]


def test_companion_answers_initial_page_fields_from_fsd():
    result = answer_companion_question(_project(), "What all fields will be there in my initial page?")
    assert any(source["kind"] == "fsd" for source in result["sources"])
    assert "Functional Specification" in result["answer"] or "Overview" in result["answer"]
    assert "Create purchase requisition" in result["answer"]
    assert "Anurag" not in result["answer"]


def test_companion_stays_scoped_to_open_project():
    context = companion_context(_project())
    assert context["project_id"] == "proj-companion"
    assert context["project_name"] == "Purchase Requisition Approval"
    assert "another BRD" in context["guardrail"].lower() or "different project" in context["guardrail"].lower()
    briefing = build_companion(_project())
    assert "Anurag" not in briefing["title"]
    assert "Purchase Requisition Approval" in briefing["title"]


def test_companion_answers_process_flow_from_brd():
    project = _project()
    # Add process steps to brd_knowledge payload
    project.brd_knowledge.payload["process_steps"] = [
        {"step_id": "STEP-01", "actor": "Requester", "activity": "Create requisition", "decision_or_rule": "Valid?"},
        {"step_id": "STEP-02", "actor": "Approver", "activity": "Release requisition", "decision_or_rule": "Approved?"},
    ]
    result = answer_companion_question(project, "Explain the process flow and actors in this BRD")
    assert any(source["kind"] == "brd" for source in result["sources"])
    assert "Requester" in result["answer"]
    assert "Approver" in result["answer"]
    assert "Process Sequence" in result["answer"] or "Process Design" in result["answer"]


def test_companion_answers_screens_and_floorplans():
    project = _project()
    result = answer_companion_question(project, "What SAP Fiori screens and floorplans are specified?")
    assert any(source["kind"] == "fsd" or source["kind"] == "brd" for source in result["sources"])
    assert "Floorplan" in result["answer"] or "Screen" in result["answer"]


def test_companion_answers_from_raw_brd_chunks():
    project = _project()
    project.document.chunks = [
        SimpleNamespace(id="chunk-dock", locator="Page 4, Section 2", page=4,
                        text="Special gate security protocol requires biometric driver verification and sealed cargo inspection at Dock Bay 4.")
    ]
    result = answer_companion_question(project, "What are the rules for biometric cargo inspection at Dock Bay?")
    assert any(source["kind"] == "brd" for source in result["sources"])
    assert "Page 4" in result["answer"] or "Dock Bay 4" in result["answer"]


def test_companion_answers_approver_levels_with_brd_and_fsd_references():
    project = _project()
    project.document.chunks = [
        SimpleNamespace(id="chunk-appr", locator="Page 7, Section 4.2", page=7,
                        text="Approval matrix defines 2 levels: Level 1 Functional Manager review, and Level 2 Safety / Plant Head authorization for hazardous movement.")
    ]
    result = answer_companion_question(project, "how many level of approvers are there")
    assert result["project_id"] == "proj-companion"
    assert "Level 1" in result["answer"]
    assert "Level 2" in result["answer"]
    assert "BRD Reference" in result["answer"]
    assert "FSD Reference" in result["answer"]
    assert any(s["kind"] == "brd" for s in result["sources"])
    assert any(s["kind"] == "fsd" for s in result["sources"])


