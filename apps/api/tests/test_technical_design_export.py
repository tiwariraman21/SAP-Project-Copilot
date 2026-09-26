from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from PIL import Image
from pypdf import PdfReader

from app.services.technical_design_export import export_technical_design


W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_text(path) -> str:
    with ZipFile(path) as archive:
        parts = ["word/document.xml"]
        parts.extend(name for name in archive.namelist() if name.startswith("word/header") or name.startswith("word/footer"))
        chunks = []
        for name in parts:
            root = ET.fromstring(archive.read(name))
            chunks.append("".join((node.text or "") for node in root.iter(f"{W_NS}t")))
    return "\n".join(chunks)


def test_technical_design_uses_fsd_chrome_and_reference_outline(tmp_path):
    document = {
        "title": "Order to Cash - Technical Design Specification",
        "generated_on": "29.08.2026",
        "source_fsd": {"title": "Order to Cash - Functional Solution Design", "version": "1.0"},
        "document_information": {
            "extension_id": "OData / Fiori / ABAP",
            "extension_description": "Credit check before sales-order release",
            "application": "SAP S/4HANA / SAP Fiori",
            "process_area": "Order to Cash",
            "project": "Order to Cash",
            "job_name": "N/A - no batch job identified",
            "functional_designer": "SAP Project Copilot (per FSD)",
            "technical_designer": "TBD / project technical lead",
            "developer": "TBD",
            "tools_technology": "SAP Fiori elements, SAPUI5, OData, ABAP",
            "prepared_by": "SAP Project Copilot",
            "program_type": "SAP Fiori / OData / ABAP",
        },
        "related_documents": [{"document": "Order to Cash - Functional Solution Design", "location": "Generated Functional Specification, Version 1.0"}],
        "revision_history": [{"version": "0.1", "date": "29.08.2026", "author": "SAP Project Copilot", "description": "Initial technical design draft generated from Functional Solution Design v1.0."}],
        "sign_offs": [{"role": "SAP Technical Lead", "name": "TBD", "status": "Pending"}],
        "distribution": [{"name": "SAP Development Team", "role": "Implementation"}],
        "requirements_summary": "Translate the approved FSD into a reviewable technical baseline.",
        "capability_map": [{"capability": "Credit check", "technical_response": "Backend validation before release", "requirement_ids": "REQ-001"}],
        "assumptions": ["Target SAP release requires confirmation"],
        "dependencies": ["Approved functional specification"],
        "standards": ["Prefer fit-to-standard SAP Fiori before custom code"],
        "process_steps": [{"step_id": "STEP-01", "actor": "Business User", "activity": "Submit order", "system_behavior": "Validate credit", "outcome": "Order is held or released"}],
        "fiori_flows": [{"flow": "Worklist load", "behavior": "Load authorized records", "mechanism": "OData GET"}],
        "screens": [{"name": "Overview", "technology": "SAP Fiori elements - List Report", "fields": "Order, Status", "actions": "Open"}],
        "affected_objects": [{"object_type": "OData service", "object_name": "TBD", "purpose": "Typed UI-to-ABAP contract", "impact": "Read and update authorized records"}],
        "security_controls": [{"control": "Backend authorization", "design": "Authorize every protected operation"}],
        "error_handling": [{"id": "MSG-01", "scenario": "Invalid input", "user_message": "Correct the highlighted information.", "technical_handling": "Do not persist until valid"}],
        "operational_considerations": {
            "dependencies": ["OData service activation"],
            "reuse": ["Reuse Fiori elements"],
            "fiori_html": [["Application type", "List Report + Object Page"]],
            "bsp": "N/A for the baseline design.",
            "git": [["Git repository", "TBD"]],
            "multi_site": "Do not hard-code system URLs.",
            "other": ["Protect state-changing calls with CSRF"],
        },
        "data_mappings": [{"business_field": "Credit status", "source": "SAP backend", "rule": "Backend remains authoritative"}],
        "interfaces": [],
        "roles_and_authorizations": [{"business_role": "Order Clerk", "data_scope": "Own orders", "authorization_object": "TBD"}],
        "components": [{"requirement_key": "REQ-001", "title": "Validate customer credit", "validation": "Credit is checked before release"}],
        "status_definitions": [{"status": "Blocked", "source": "SAP backend", "semantic_state": "Error", "definition": "Credit check failed"}],
        "nfr": [{"description": "Use server-side paging"}],
        "test_conditions": [{"id": "UT-001", "condition": "Unauthorized user cannot release", "expected_result": "Action is denied", "requirement_key": "REQ-001"}],
        "outstanding_issues": [{"issue_no": "OI-01", "description": "Confirm SAP release", "assigned_to": "Technical Lead", "status": "Open", "impact": "High", "resolution": "Landscape workshop"}],
        "glossary": [{"term": "OData", "definition": "SAP service protocol"}],
        "traceability": [{"capability": "Credit check", "requirement_ids": "REQ-001"}],
        "review_notes": ["Object names marked TBD require technical lead assignment."],
    }

    paths = export_technical_design(document, "Order to Cash", "project-tdd", str(tmp_path))
    path = Path(paths["docx"])
    text = _docx_text(path)

    assert "ADNOC Classification" not in text
    assert "Classification: INTERNAL" in text
    assert "SAP Technical Design Document" in text
    assert "Order to Cash" in text
    assert "ORDER TO CASH" in text
    assert "Order to Cash - Technical Design Specification" not in text
    assert "SAP S/4HANA / SAP Fiori" in text
    assert "TECHNICAL DESIGN SPECIFICATION" in text
    assert "Application" in text
    assert "Source FSD: Order to Cash" in text
    assert "ORDER-CASH" in text
    assert "Table 1: Cover document attributes" in text
    assert "Document Attribute / Value" not in text
    assert "SCREENSHOT REQUIRED" in text
    assert "Insert a screenshot of 'Overview'" in text
    for heading in (
        "1. Document Information",
        "1.1 General Data",
        "2. Development Overview",
        "2.1 Requirements Summary",
        "3. Detailed Technical Specifications",
        "3.1 Technical Flow Diagram",
        "3.5.3 Fiori Application HTML5/JSP/CSS Details (Customized Objects Only)",
        "4. Technical Requirements",
        "4.5 Detailed Design",
        "4.5.4 OData and Data Mapping Design",
        "5. Testing Requirements",
        "6. Outstanding Issues",
        "7. Appendix",
        "7.3 Key Requirement Traceability",
        "7.4 Technical Design Review Notes",
    ):
        assert heading in text
    assert "Page " in text

    logo = next(tmp_path.joinpath("project-tdd").glob("*-logo-left.png"))
    with Image.open(logo) as image:
        assert image.width > 280
        assert image.height > 40

    pdf_path = Path(paths["pdf"])
    assert pdf_path.read_bytes()[:4] == b"%PDF"
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)
    assert "TECHNICAL DESIGN SPECIFICATION" in pdf_text
    assert "SAP S/4HANA / SAP Fiori" in pdf_text
    assert "SAP Technical Design Document" in pdf_text
    assert "Classification: INTERNAL" in pdf_text
    assert "ORDER-CASH" in pdf_text
    assert "Table 1: Cover document attributes" in pdf_text
    assert "SCREENSHOT REQUIRED" in pdf_text
    assert "Document Attribute / Value" not in pdf_text


def test_tdd_replaces_person_name_with_project_identity(tmp_path):
    document = {
        "title": "Anurag Umale - Technical Design Specification",
        "generated_on": "31.08.2026",
        "source_fsd": {"title": "Anurag Umale - Functional Solution Design", "version": "1.0"},
        "document_information": {
            "extension_id": "OData / Fiori / ABAP",
            "application": "SAP S/4HANA / SAP Fiori",
            "process_area": "Procurement",
            "project": "Anurag Umale",
            "process_identifier": "Anurag Umale",
            "prepared_by": "SAP Project Copilot",
        },
        "process_steps": [{"step_id": "STEP-01", "actor": "Buyer", "activity": "Submit requisition", "system_behavior": "Validate", "outcome": "Created"}],
        "screens": [{"name": "PR Worklist", "technology": "SAP Fiori elements - List Report", "fields": "PR, Status", "actions": "Open"}],
        "review_notes": ["Confirm object names before build."],
    }

    paths = export_technical_design(document, "Purchase Requisition Approval", "project-tdd-person", str(tmp_path))
    text = _docx_text(Path(paths["docx"]))
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(paths["pdf"])).pages)

    assert "Anurag" not in text
    assert "Anurag" not in pdf_text
    assert "Purchase Requisition Approval" in text
    assert "PURCHASE REQUISITION APPROVAL" in text
    assert "PURCHASE-REQUISITION-APPROVAL" in text
    assert "PURCHASE-REQUISITION-APPROVAL" in pdf_text
    assert "SCREENSHOT REQUIRED" in text
    assert "Table 1: Cover document attributes" in text
    assert document["title"] == "Purchase Requisition Approval"
    assert document["document_information"]["process_identifier"] == "PURCHASE-REQUISITION-APPROVAL"
