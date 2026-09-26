from datetime import datetime
from types import SimpleNamespace
from zipfile import ZipFile

from app.models import ReviewStatus
from app.services.downstream import build_test_cases
from app.services.quality_test_export import _quality_display_name, export_quality_tests


def _xlsx_text(path) -> str:
    with ZipFile(path) as archive:
        return "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in archive.namelist()
            if name.endswith(".xml")
        )


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


def test_test_pack_uses_brd_name_and_readable_priority():
    document = build_test_cases(_project())
    assert document["title"] == "Purchase Requisition Approval"
    assert document["project_name"] == "Purchase Requisition Approval"
    assert "Anurag" not in document["title"]
    assert document["test_cases"][0]["priority"] == "Must Have"


def test_quality_export_strips_person_name_and_maps_priority(tmp_path):
    assert _quality_display_name(
        {"title": "Quality Test Pack - Anurag Umale"},
        "Purchase Requisition Approval",
    ) == "Purchase Requisition Approval"
    assert _quality_display_name(
        {"title": "Quality Test Pack - Anurag Umale"},
        "Anurag Umale",
    ) == "SAP Business Process"

    output = export_quality_tests(
        {
            "title": "Quality Test Pack - Anurag Umale",
            "test_cases": [{
                "test_key": "TC-001", "requirement_key": "REQ-001",
                "title": "Validate create purchase requisition", "priority": "must",
                "preconditions": ["Role assigned"], "steps": ["Open Fiori app"],
                "expected_result": "Requisition is created", "source_evidence": "BRD",
            }],
        },
        "Purchase Requisition Approval",
        "proj-qtest",
        str(tmp_path),
    )
    assert "anurag" not in output.lower()
    text = _xlsx_text(output)
    assert "Purchase Requisition Approval" in text
    assert "Must Have" in text
    assert "Anurag" not in text
    assert "Quality Test Pack - Anurag Umale" not in text
