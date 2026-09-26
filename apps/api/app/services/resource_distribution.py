from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from ..models import Project, ReviewStatus
from .project_identity import business_project_name

EXPERIENCE_LADDERS = {
    1: [6],
    2: [6, 2],
    3: [8, 5, 2],
    4: [8, 6, 4, 2],
    5: [10, 8, 5, 3, 2],
}

ROLE_SHORT_NAMES = {
    "SAP Functional Consultant": "Functional Consultant",
    "Fiori Developer": "Fiori Developer",
    "ABAP Developer": "ABAP Developer",
    "Technical Architect": "Technical Architect",
    "Integration Developer": "Integration Developer",
    "Security Consultant": "Security Consultant",
    "SAP Data & Analytics Consultant": "Data Consultant",
    "QA / Test Analyst": "QA Analyst",
}


def _level(years: int) -> str:
    if years >= 8:
        return "Lead"
    if years >= 6:
        return "Senior"
    if years >= 4:
        return "Mid"
    return "Junior"


def _ladder(count: int) -> list[int]:
    if count <= 0:
        return []
    if count in EXPERIENCE_LADDERS:
        return EXPERIENCE_LADDERS[count]
    extra = max(2, 10 - count)
    years = [10]
    for index in range(1, count):
        years.append(max(2, extra - index + 1) if index < count - 1 else 2)
    return years[:count]


def _count_type(requirements: list, *types: str) -> int:
    wanted = {item.lower() for item in types}
    return sum(1 for item in requirements if str(getattr(item, "requirement_type", "") or "").lower() in wanted)


def _fsd_document(project: Project) -> dict:
    artifact = next((item for item in project.artifacts if item.kind == "fsd"), None)
    payload = artifact.payload if artifact else None
    document = payload.get("document") if isinstance(payload, dict) else None
    return document if isinstance(document, dict) else {}


def _role_counts(requirements: list, screens: int, technical_objects: int) -> list[tuple[str, int, str]]:
    total = len(requirements)
    must = sum(1 for item in requirements if str(getattr(item, "priority", "") or "").lower() == "must")
    integration = _count_type(requirements, "integration")
    security = _count_type(requirements, "security")
    data = _count_type(requirements, "data", "reporting")
    non_functional = _count_type(requirements, "non_functional")

    functional = 1 if total < 12 else 2 if total < 35 else 3
    fiori = 1 if total < 8 and screens <= 2 else 2 if total < 30 and screens <= 5 else 3
    if screens >= 3:
        fiori = max(fiori, 2)
    if screens >= 6 or technical_objects >= 8:
        fiori = max(fiori, 3)
    abap = 1 if total < 10 else 2 if total < 22 else 3 if total < 45 else 4
    if technical_objects >= 6:
        abap = max(abap, 3)
    if must >= 12:
        abap = max(abap, 3)
        fiori = max(fiori, 2)

    roles: list[tuple[str, int, str]] = [
        ("SAP Functional Consultant", functional, "Owns process design, fit-gap, and business configuration for the approved BRD scope."),
        ("Fiori Developer", fiori, "Builds Fiori / UI5 screens, validations, and user-facing actions from the functional design."),
        ("ABAP Developer", abap, "Implements backend behaviour, OData/service logic, and SAP object changes."),
    ]
    if total >= 12 or non_functional:
        roles.append(("Technical Architect", 1, "Sets extension approach, landscape decisions, and review gates for the technical design."))
    if integration or total >= 20:
        roles.append(("Integration Developer", 1 if integration < 8 else 2, "Covers interfaces, APIs, and cross-system data movement in the approved baseline."))
    if security or total >= 25:
        roles.append(("Security Consultant", 1, "Defines roles, authorization objects, and SoD controls for the process."))
    if data:
        roles.append(("SAP Data & Analytics Consultant", 1, "Covers reporting, persistence, and data-quality requirements."))
    roles.append(("QA / Test Analyst", 1 if total < 18 else 2, "Designs and executes SIT/UAT coverage against the approved requirements and FSD tests."))
    return roles


def suggest_resource_distribution(project: Project) -> dict:
    requirements = [item for item in project.requirements if item.review_status == ReviewStatus.approved]
    fsd = _fsd_document(project)
    screens = len(fsd.get("screens") or [])
    technical_objects = len(fsd.get("technical_objects") or [])
    display_name = business_project_name(project)
    roles = _role_counts(requirements, screens, technical_objects)
    people = []
    for role, count, _reason in roles:
        short = ROLE_SHORT_NAMES.get(role, role)
        for index, years in enumerate(_ladder(count), 1):
            label = f"{short} {index}" if count > 1 else short
            people.append({
                "role": role,
                "label": label,
                "experience_years": years,
                "experience": f"{years} Yrs exp",
                "level": _level(years),
            })
    return {
        "status": "generated",
        "project_name": display_name,
        "requirement_count": len(requirements),
        "screen_count": screens,
        "total_resources": len(people),
        "basis": (
            f"Suggested from {len(requirements)} approved requirement(s)"
            + (f", {screens} Fiori screen(s)" if screens else "")
            + ", mixed seniority so each workstream has a lead and a supporting resource where more than one person is needed."
        ),
        "summary": [
            {"role": role, "count": count, "reason": reason}
            for role, count, reason in roles
        ],
        "people": people,
    }


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-") or "project"


def _sheet_xml(rows: list[list[str]]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
    lines.append('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>')
    for row_index, row in enumerate(rows, 1):
        cells = []
        for col_index, value in enumerate(row):
            ref = f"{chr(65 + col_index)}{row_index}"
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value or ""))}</t></is></c>')
        lines.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    lines.append("</sheetData></worksheet>")
    return "".join(lines)


def export_resource_distribution(suggestion: dict, project_id: str, artifact_root: str) -> str:
    display_name = str((suggestion or {}).get("project_name") or "SAP Business Process")
    output_dir = (Path(artifact_root) / project_id).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{_slug(display_name)}-resource-distribution.xlsx"
    summary_rows = [["Role", "Count", "Reason"]] + [
        [item.get("role"), item.get("count"), item.get("reason")]
        for item in (suggestion or {}).get("summary") or []
    ]
    people_rows = [["Person", "Role", "Level", "Experience"]] + [
        [item.get("label"), item.get("role"), item.get("level"), item.get("experience")]
        for item in (suggestion or {}).get("people") or []
    ]
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Role Summary" sheetId="1" r:id="rId1"/><sheet name="People" sheetId="2" r:id="rId2"/></sheets>
</workbook>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
</Relationships>"""
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", _sheet_xml(summary_rows))
        archive.writestr("xl/worksheets/sheet2.xml", _sheet_xml(people_rows))
    return str(output)
