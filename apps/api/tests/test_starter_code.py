import io
import json
import zipfile
from datetime import datetime
from types import SimpleNamespace

from app.models import ReviewStatus
from app.services.downstream import build_technical_design
from app.services.functional_design import _build_demo_fsd
from app.services.starter_code import build_starter_code_zip


def _requirement(**overrides):
    base = dict(
        requirement_key="REQ-001",
        title="Supplier Purchase Order Selection",
        statement="The supplier shall select an eligible purchase order for gate pass creation.",
        requirement_type="functional",
        priority="must",
        acceptance_criteria=["PO is selected and verified"],
        source_chunk_ids=["chunk-1"],
        source_quote="The supplier shall select an eligible purchase order.",
        review_status=ReviewStatus.approved,
        rationale="",
        assumptions=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _project():
    chunk = SimpleNamespace(id="chunk-1", locator="Page 7")
    document = SimpleNamespace(filename="Gate_Pass_Application_BRD.pdf", chunks=[chunk])
    project = SimpleNamespace(
        id="proj-starter-test",
        name="Gate Pass Application",
        created_at=datetime(2026, 8, 31),
        document=document,
        requirements=[
            _requirement(requirement_key="REQ-001", title="PO Search and Selection"),
            _requirement(requirement_key="REQ-002", title="Transporter Details Entry"),
            _requirement(requirement_key="REQ-003", title="Approver Inbox L1 Review"),
            _requirement(requirement_key="REQ-004", title="Gate Security QR Verification"),
        ],
        artifacts=[],
        brd_knowledge=SimpleNamespace(payload={
            "business_context": "Gate Pass request and QR mobile verification",
            "screens": [
                {"screen_id": "SCR-01", "name": "Supplier Purchase Orders", "floorplan": "SAP Fiori elements - List Report"},
                {"screen_id": "SCR-02", "name": "Gate Pass Request Entry", "floorplan": "SAP Fiori elements - Object Page"},
                {"screen_id": "SCR-04", "name": "My Inbox: Level 1 Review", "floorplan": "SAPUI5 - Freestyle"},
                {"screen_id": "SCR-07", "name": "Gate Verification", "floorplan": "SAPUI5 - Freestyle"},
            ],
            "process_steps": [
                {"step_id": "PS-01", "actor": "Supplier Requester", "activity": "Select PO"},
                {"step_id": "PS-02", "actor": "Supplier Requester", "activity": "Submit Request"},
                {"step_id": "PS-03", "actor": "Level 1 Approver", "activity": "Approve/Reject"},
                {"step_id": "PS-06", "actor": "Gate Security", "activity": "Scan QR Token"},
            ],
        }),
    )
    fsd = _build_demo_fsd(project)
    tdd = build_technical_design(project)
    project.artifacts = [
        SimpleNamespace(kind="fsd", status="generated", payload={"document": fsd}),
        SimpleNamespace(kind="technical_design", status="generated", payload={"document": tdd}),
    ]
    return project


def test_starter_code_generates_fsd_grounded_views_and_abap(tmp_path):
    project = _project()
    result = build_starter_code_zip(project, str(tmp_path))

    assert result["status"] == "generated"
    assert result["requirement_count"] == 4
    assert result["file_count"] >= 25

    # Inspect the generated zip archive
    zip_path = result["zip_path"]
    with zipfile.ZipFile(zip_path, "r") as archive:
        namelist = archive.namelist()

        # 1. UI5 Views & Controllers mirroring FSD screens
        assert any("fiori/webapp/view/App.view.xml" in name for name in namelist)
        assert any("fiori/webapp/view/ListReport.view.xml" in name for name in namelist)
        assert any("fiori/webapp/view/RequestEntry.view.xml" in name for name in namelist)
        assert any("fiori/webapp/view/ApprovalInbox.view.xml" in name for name in namelist)
        assert any("fiori/webapp/view/GateVerification.view.xml" in name for name in namelist)
        assert any("fiori/webapp/view/PassDownload.view.xml" in name for name in namelist)
        assert any("fiori/webapp/manifest.json" in name for name in namelist)
        assert any("fiori/webapp/model/mockData.json" in name for name in namelist)

        # 2. ABAP CDS, RAP, and Service definitions
        assert any("abap/src/cds/" in name and name.endswith(".ddls.asddls") for name in namelist)
        assert any("abap/src/rap/" in name and name.endswith(".bdef.asbdef") for name in namelist)
        assert any("abap/src/rap/" in name and name.endswith(".clas.abap") for name in namelist)
        assert any("abap/src/srv/" in name and name.endswith(".srvd.asapsrvd") for name in namelist)
        assert any("abap/src/sec/" in name and name.endswith(".clas.abap") for name in namelist)

        # 3. Documentation & Alignment
        assert any("docs/FSD_ALIGNMENT.md" in name for name in namelist)
        assert any("docs/DATA_MODEL.md" in name for name in namelist)
        assert any("docs/API_CONTRACT.md" in name for name in namelist)
        assert any("docs/SECURITY.md" in name for name in namelist)
        assert any("docs/requirements.json" in name for name in namelist)

        # Verify content of FSD Alignment doc
        fsd_align_file = next(name for name in namelist if name.endswith("docs/FSD_ALIGNMENT.md"))
        fsd_align_content = archive.read(fsd_align_file).decode("utf-8")
        assert "SCR-01" in fsd_align_content
        assert "Gate Verification" in fsd_align_content or "SCR-07" in fsd_align_content

        # Verify manifest.json contains routing targets
        manifest_file = next(name for name in namelist if name.endswith("fiori/webapp/manifest.json"))
        manifest_content = json.loads(archive.read(manifest_file).decode("utf-8"))
        assert "routes" in manifest_content["sap.ui5"]["routing"]
        assert len(manifest_content["sap.ui5"]["routing"]["routes"]) >= 5
