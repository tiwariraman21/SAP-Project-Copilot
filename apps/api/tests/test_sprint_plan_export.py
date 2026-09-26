import re
import zipfile
from pathlib import Path

from app.services.sprint_plan_export import TEMPLATE_PATH, export_sprint_plan


def _cell_text(xml: str, ref: str) -> str | None:
    match = re.search(rf'<x:c r="{ref}"[\s\S]*?(?:/>|</x:c>)', xml)
    if not match:
        return None
    block = match.group(0)
    formula = re.search(r"<x:f>(.*?)</x:f>", block)
    if formula:
        return formula.group(1)
    value = re.search(r"<x:v>(.*?)</x:v>", block)
    if value:
        return value.group(1)
    return None


def test_sprint_plan_fills_curved_template_without_replacing_formulas(tmp_path: Path):
    backlog = {
        "title": "Delivery Backlog - Order to Cash",
        "project_name": "Order to Cash",
        "project_manager": "Delivery Lead",
        "objective": "Deliver approved credit-check and audit requirements.",
        "stories": [
            {
                "story_key": "US-001",
                "requirement_key": "REQ-001",
                "title": "Validate customer credit",
                "story": "As an SAP business user, I want credit checked before release.",
                "priority": "must",
                "story_points": 5,
                "acceptance_criteria": ["Credit is checked before release"],
                "sprint": 1,
                "assigned_to": "SAP Functional Consultant",
                "start_date": "2026-09-07",
                "target_end_date": "2026-09-20",
                "status": "Not Started",
                "remarks": "Confirm owner during refinement.",
                "dependency": "Master data ready",
                "progress_percent": 0,
                "source_locator": "BRD p.2",
                "source_evidence": "The system must validate customer credit",
            },
            {
                "story_key": "US-002",
                "requirement_key": "REQ-002",
                "title": "Record approval decision",
                "story": "As an SAP business user, I want the approval recorded for audit.",
                "priority": "should",
                "story_points": 3,
                "sprint": 2,
                "assigned_to": "Technical Architect",
                "start_date": "2026-09-21",
                "target_end_date": "2026-10-04",
                "status": "Ready",
                "dependency": "US-001",
                "progress_percent": 0,
            },
        ],
        "sprints": [{"number": 1}, {"number": 2}],
    }

    output = Path(export_sprint_plan(backlog, "Order to Cash", "proj-1", str(tmp_path)))
    assert output.exists()

    with zipfile.ZipFile(TEMPLATE_PATH) as template, zipfile.ZipFile(output) as generated:
        assert set(template.namelist()) == set(generated.namelist())
        for name in template.namelist():
            if name == "xl/worksheets/sheet1.xml":
                continue
            assert template.read(name) == generated.read(name), name
        sheet = generated.read("xl/worksheets/sheet1.xml").decode("utf-8")
        dashboard = generated.read("xl/worksheets/sheet2.xml").decode("utf-8")
        setup = generated.read("xl/worksheets/sheet3.xml").decode("utf-8")
        curve = generated.read("xl/worksheets/sheet4.xml").decode("utf-8")

    assert "Project Planning" in (_cell_text(sheet, "A1") or "")
    assert _cell_text(sheet, "B2") == "Order to Cash"
    assert _cell_text(sheet, "E2") == "Delivery Lead"
    assert "approved credit-check" in (_cell_text(sheet, "B3") or "")
    assert (_cell_text(sheet, "H2") or "").startswith("IF(COUNTIF(A7:A206")
    assert (_cell_text(sheet, "N2") or "") == "TODAY()"

    assert _cell_text(sheet, "A7") == "US-001"
    assert _cell_text(sheet, "B7") == "Planning"
    assert _cell_text(sheet, "C7") == "Validate customer credit"
    assert _cell_text(sheet, "D7") == "SAP Functional Consultant"
    assert _cell_text(sheet, "E7") == "Critical"
    assert _cell_text(sheet, "I7") == "Not Started"
    assert _cell_text(sheet, "Q7") == "Master data ready"
    assert (_cell_text(sheet, "H7") or "").startswith('IF(A7="",""')
    assert "IF(L7" in (_cell_text(sheet, "M7") or "")
    assert "Complete" in (_cell_text(sheet, "R7") or "")

    assert _cell_text(sheet, "A8") == "US-002"
    assert _cell_text(sheet, "B8") == "Analysis"
    assert _cell_text(sheet, "E8") == "High"
    assert _cell_text(sheet, "I8") == "Not Started"
    assert _cell_text(sheet, "A9") is None

    assert "Project Progress Dashboard" in dashboard
    assert "COUNTIF('Project Plan'!$A$7:$A$206" in dashboard
    assert "Not Started" in setup
    assert "Planning" in setup
    assert "Planned vs Actual Progress Curve" in curve
    assert "Project Plan" in curve
