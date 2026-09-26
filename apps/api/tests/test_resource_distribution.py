from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from app.models import ReviewStatus
from app.services.downstream import build_backlog
from app.services.resource_distribution import export_resource_distribution, suggest_resource_distribution
from app.services.sprint_plan_export import _display_project_name, export_sprint_plan


def _project(name="Anurag Umale", filename="purchase-requisition-approval-brd.txt"):
    chunk = SimpleNamespace(id="chunk-1", locator="Page 1")
    requirement = SimpleNamespace(
        requirement_key="REQ-001", title="Create purchase requisition",
        statement="The requester must create a purchase requisition.",
        requirement_type="functional", priority="must",
        acceptance_criteria=["Requisition is created"], source_chunk_ids=[chunk.id],
        source_quote="The requester must create a purchase requisition.",
        review_status=ReviewStatus.approved,
    )
    document = SimpleNamespace(filename=filename, chunks=[chunk])
    return SimpleNamespace(
        name=name, created_at=datetime(2026, 8, 31),
        document=document, requirements=[requirement], artifacts=[],
        brd_knowledge=SimpleNamespace(payload={"business_context": "Purchase requisition approval process"}),
    )


def test_backlog_uses_brd_process_name_instead_of_person_name():
    document = build_backlog(_project())
    assert document["project_name"] == "Purchase Requisition Approval"
    assert document["title"] == "Delivery Backlog - Purchase Requisition Approval"
    assert "Anurag" not in document["project_name"]
    assert "Anurag" not in document["title"]


def test_sprint_plan_excel_rejects_person_name_in_project_cell(tmp_path):
    assert _display_project_name({"project_name": "Anurag Umale", "title": "Delivery Backlog - Anurag Umale"}, "Anurag Umale") == "SAP Delivery Project"
    output = export_sprint_plan(
        {"title": "Delivery Backlog - Anurag Umale", "project_name": "Anurag Umale", "stories": []},
        "Anurag Umale", "proj-person", str(tmp_path),
    )
    assert "anurag" not in output.lower()


def test_resource_distribution_mixes_counts_and_experience(tmp_path):
    project = _project()
    extra = []
    for index in range(2, 16):
        extra.append(SimpleNamespace(
            requirement_key=f"REQ-{index:03}", title=f"Requirement {index}",
            statement="The system shall complete the approved process step.",
            requirement_type="integration" if index % 5 == 0 else "functional",
            priority="must" if index < 10 else "should",
            acceptance_criteria=["Done"], source_chunk_ids=["chunk-1"],
            source_quote="The system shall complete the approved process step.",
            review_status=ReviewStatus.approved,
        ))
    project.requirements.extend(extra)
    suggestion = suggest_resource_distribution(project)

    assert suggestion["project_name"] == "Purchase Requisition Approval"
    assert suggestion["total_resources"] >= 6
    roles = {item["role"]: item["count"] for item in suggestion["summary"]}
    assert roles["Fiori Developer"] >= 2
    assert roles["ABAP Developer"] >= 2
    assert roles["SAP Functional Consultant"] >= 1
    fiori = [item for item in suggestion["people"] if item["role"] == "Fiori Developer"]
    assert fiori[0]["experience_years"] == 6
    assert fiori[-1]["experience_years"] == 2
    assert "Anurag" not in suggestion["project_name"]
    path = export_resource_distribution(suggestion, "proj-resources", str(tmp_path))
    assert Path(path).exists()
    assert Path(path).read_bytes()[:2] == b"PK"
