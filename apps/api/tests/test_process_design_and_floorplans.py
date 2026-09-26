from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from PIL import Image

import pytest

from app.models import ReviewStatus
from app.services.fsd_export import (
    _draw_fiori_screen,
    _draw_navigation,
    _draw_process_flow,
    _draw_process_legend,
)
from app.services.fsd_validation import FSDValidationError, validate_fsd_document
from app.services.functional_design import _build_demo_fsd
from app.services.process_design import (
    build_actors,
    build_process_steps,
    build_screens,
    floorplan_of,
    navigation_edges,
    used_legend_shapes,
)


def _gate_pass_project():
    chunk = SimpleNamespace(id="chunk-gp-1", locator="Page 7")
    reqs = [
        SimpleNamespace(
            requirement_key="FR-01", title="PO Search and Selection",
            statement="The system shall allow suppliers to search and view authorized eligible purchase orders.",
            requirement_type="functional", priority="must", rationale="PO discovery",
            acceptance_criteria=["Only authorized eligible POs are displayed"], assumptions=[],
            source_chunk_ids=[chunk.id], source_quote="Suppliers shall search eligible POs.",
            review_status=ReviewStatus.approved,
        ),
        SimpleNamespace(
            requirement_key="FR-02", title="Gate Pass Request Entry",
            statement="The system shall capture visit date, vehicle number, driver name, license, and delivery note.",
            requirement_type="functional", priority="must", rationale="Pass capture",
            acceptance_criteria=["Request snapshot is locked upon submission"], assumptions=[],
            source_chunk_ids=[chunk.id], source_quote="Capture vehicle and driver details.",
            review_status=ReviewStatus.approved,
        ),
        SimpleNamespace(
            requirement_key="FR-03", title="Eligibility Validation",
            statement="The application shall validate PO status and duplicate requests before workflow routing.",
            requirement_type="functional", priority="must", rationale="System check",
            acceptance_criteria=["Validation prevents duplicate requests"], assumptions=[],
            source_chunk_ids=[chunk.id], source_quote="System validates eligibility.",
            review_status=ReviewStatus.approved,
        ),
        SimpleNamespace(
            requirement_key="FR-04", title="Level 1 Operational Approval",
            statement="Level 1 Approver shall review dock capacity and approve, return or reject the gate pass request.",
            requirement_type="functional", priority="must", rationale="L1 review",
            acceptance_criteria=["L1 approver can approve, return or reject"], assumptions=[],
            source_chunk_ids=[chunk.id], source_quote="L1 approver reviews in My Inbox.",
            review_status=ReviewStatus.approved,
        ),
        SimpleNamespace(
            requirement_key="FR-05", title="Level 2 Security Approval",
            statement="Level 2 Approver shall authorize plant entry and approve or reject.",
            requirement_type="functional", priority="must", rationale="L2 review",
            acceptance_criteria=["L2 provides final security authorization"], assumptions=[],
            source_chunk_ids=[chunk.id], source_quote="L2 security authorization.",
            review_status=ReviewStatus.approved,
        ),
        SimpleNamespace(
            requirement_key="FR-06", title="Gate Pass PDF and QR Generation",
            statement="The application shall generate an immutable PDF pass with a cryptographic QR code.",
            requirement_type="functional", priority="must", rationale="Pass issuance",
            acceptance_criteria=["Pass generated only after Level 2 approval"], assumptions=[],
            source_chunk_ids=[chunk.id], source_quote="PDF and QR generation upon approval.",
            review_status=ReviewStatus.approved,
        ),
        SimpleNamespace(
            requirement_key="FR-07", title="QR Token Verification at Gate",
            statement="Gate Security shall scan the QR code to verify pass validity and admit or deny entry.",
            requirement_type="functional", priority="must", rationale="Security admission",
            acceptance_criteria=["Entry admitted on valid token, denied on expired or invalid token"], assumptions=[],
            source_chunk_ids=[chunk.id], source_quote="Gate security scans QR code to admit or deny.",
            review_status=ReviewStatus.approved,
        ),
    ]
    document = SimpleNamespace(filename="Gate_Pass_Application_BRD.pdf", chunks=[chunk])
    brd_knowledge = SimpleNamespace(
        extraction_version="brd-knowledge-v1", model="test-brd-model", coverage_percent=100.0,
        payload={
            "business_context": "Gate Pass Application BRD for Supplier Vehicle Entry and Multi-Level Workflow",
            "process_steps": [
                {"step_id": "ST-01", "actor": "Supplier", "activity": "Open eligible PO", "business_result": "PO open"},
                {"step_id": "ST-02", "actor": "Supplier", "activity": "Enter request", "business_result": "Request submitted"},
                {"step_id": "ST-03", "actor": "App / S4", "activity": "Validate request", "business_result": "Valid?"},
                {"step_id": "ST-04", "actor": "Level 1", "activity": "My Inbox review", "business_result": "L1 Approved?"},
                {"step_id": "ST-05", "actor": "Level 2", "activity": "Final authorization", "business_result": "L2 Approved?"},
                {"step_id": "ST-06", "actor": "Gate Security", "activity": "Scan QR and verify", "business_result": "Admit or deny"},
            ],
            "screens": [
                {"screen_id": "SCR-01", "name": "Purchase Orders List", "floorplan": "list_report", "fields": ["PO Number", "Plant", "Delivery Date", "Status"]},
                {"screen_id": "SCR-02", "name": "PO & Request Details", "floorplan": "object_page", "fields": ["PO Number", "Vehicle Reg", "Driver Name", "Arrival Slot"]},
                {"screen_id": "SCR-03", "name": "Request Status Tracking", "floorplan": "object_page", "fields": ["Pass ID", "Status", "L1 Status", "L2 Status"]},
                {"screen_id": "SCR-04", "name": "My Inbox Level 1 Review", "floorplan": "my_inbox", "fields": ["Task ID", "Supplier", "PO Number", "Vehicle", "Bay"]},
                {"screen_id": "SCR-05", "name": "My Inbox Level 2 Authorization", "floorplan": "my_inbox", "fields": ["Task ID", "Supplier", "PO Number", "Security Notes"]},
                {"screen_id": "SCR-06", "name": "Approved Gate Pass Download", "floorplan": "object_page", "fields": ["Pass Number", "Validity Window", "QR Code", "Download PDF"]},
                {"screen_id": "SCR-07", "name": "Gate Security QR Verification", "floorplan": "scan", "fields": ["QR Token", "Pass Status", "Masked Vehicle", "Masked Driver"]},
            ],
            "data_fields": [
                {"field_name": "PO Number"}, {"field_name": "Vehicle Number"}, {"field_name": "Driver Name"},
                {"field_name": "Pass Status"}, {"field_name": "Delivery Date"}, {"field_name": "Plant"},
            ],
        },
    )
    return SimpleNamespace(
        id="proj-gate-pass-test",
        name="Gate Pass Application",
        created_at=datetime(2026, 9, 3),
        requirements=reqs,
        document=document,
        brd_knowledge=brd_knowledge,
    )


def test_gate_pass_process_steps_structure_and_coverage():
    project = _gate_pass_project()
    approved = project.requirements
    steps = build_process_steps(project, approved, None, 12)

    # 1. Step count must be bounded between 8 and 12 steps
    assert 8 <= len(steps) <= 12

    # 2. Swimlane actors must reflect real business roles, not generic Business User
    actors = {s["actor"] for s in steps}
    assert any("Supplier" in a for a in actors)
    assert any("Level 1" in a for a in actors)
    assert any("Level 2" in a for a in actors)
    assert any("Gate" in a or "Security" in a for a in actors)

    # 3. Decisions must be first-class typed shapes
    decision_steps = [s for s in steps if s["step_type"] == "decision"]
    assert len(decision_steps) >= 3

    # 4. Outgoing branch labels and targets must exist on decisions
    l1_step = next(s for s in decision_steps if "Level 1" in s["activity"] or "Level 1" in s["actor"])
    assert l1_step["branch_yes_label"] == "Approve"
    assert "Return" in l1_step["branch_no_label"]
    assert l1_step["branch_no_target"] == "STEP-02"  # Loops back to request entry!

    # 5. Requirement citation coverage must be 100% across steps
    all_cited = {rid for s in steps for rid in s.get("requirement_ids", [])}
    for req in approved:
        assert req.requirement_key in all_cited


def test_used_legend_shapes_filters_unused():
    # Only task and connector used
    simple_steps = [
        {"step_id": "S1", "actor": "User", "activity": "Start", "step_type": "task"},
        {"step_id": "S2", "actor": "User", "activity": "Finish", "step_type": "task"},
    ]
    legend = used_legend_shapes(simple_steps)
    assert "task" in legend
    assert "connector" in legend
    assert "swimlane" in legend
    assert "decision" not in legend
    assert "exception" not in legend

    # With decision and return exception
    decision_steps = [
        {"step_id": "S1", "actor": "User", "activity": "Review", "step_type": "decision",
         "branch_yes_label": "Approve", "branch_no_label": "Return to Requester"},
    ]
    decision_legend = used_legend_shapes(decision_steps)
    assert "decision" in decision_legend
    assert "exception" in decision_legend


def test_screen_floorplans_and_business_fields():
    project = _gate_pass_project()
    approved = project.requirements
    screens = build_screens(project, approved, None, "Gate Pass Application", {"screens": 10, "screen_fields": 25, "screen_actions": 10})

    assert len(screens) == 7

    floorplans = [floorplan_of(s) for s in screens]
    assert "list_report" in floorplans
    assert "object_page" in floorplans
    assert "my_inbox" in floorplans
    assert "scan" in floorplans

    # Verify that fields are real business fields, NOT requirement titles
    approved_titles = {r.title.lower() for r in approved}
    for screen in screens:
        field_labels = [f["label"].lower() for f in screen.get("fields", [])]
        assert not all(lbl in approved_titles for lbl in field_labels)


def test_navigation_tracks_generation():
    project = _gate_pass_project()
    approved = project.requirements
    screens = build_screens(project, approved, None, "Gate Pass Application", {"screens": 10, "screen_fields": 25, "screen_actions": 10})

    edges = navigation_edges(screens)
    assert len(edges) >= 3

    # Verify Supplier track: List Report -> Object Page
    list_screens = [s["screen_id"] for s in screens if floorplan_of(s) == "list_report"]
    obj_screens = [s["screen_id"] for s in screens if floorplan_of(s) == "object_page"]
    inbox_screens = [s["screen_id"] for s in screens if floorplan_of(s) == "my_inbox"]

    assert any(src in list_screens and tgt in obj_screens for src, tgt, _ in edges)
    # Verify Approver escalation or return
    assert any(src in inbox_screens for src, _, _ in edges)


def test_drawing_renderers_output_images(tmp_path: Path):
    project = _gate_pass_project()
    approved = project.requirements
    steps = build_process_steps(project, approved, None, 12)
    screens = build_screens(project, approved, None, "Gate Pass Application", {"screens": 10, "screen_fields": 25, "screen_actions": 10})

    flow_path = tmp_path / "flow.png"
    legend_path = tmp_path / "legend.png"
    nav_path = tmp_path / "navigation.png"

    _draw_process_flow(steps, flow_path)
    _draw_process_legend(legend_path, steps=steps)
    _draw_navigation(screens, nav_path)

    with Image.open(flow_path) as img:
        assert img.width == 1900
        assert img.height >= 545

    with Image.open(legend_path) as img:
        assert img.width == 1500
        assert img.height >= 240

    with Image.open(nav_path) as img:
        assert img.width == 1600
        assert img.height >= 700

    # Test each of the 4 Fiori floorplan renders
    for s in screens:
        scr_path = tmp_path / f"{s['screen_id']}.png"
        _draw_fiori_screen(s, scr_path)
        with Image.open(scr_path) as s_img:
            assert s_img.width == 1600
            assert s_img.height == 1000


def test_fsd_validation_quality_gate_checks():
    project = _gate_pass_project()
    doc = _build_demo_fsd(project)

    # Clean FSD passes validation
    normalized, report = validate_fsd_document(doc, project)
    assert report["passed"] is True

    # Quality Gate 1: Fail if process steps > 12
    bad_doc = deepcopy(doc)
    bad_doc["process_steps"] = doc["process_steps"] + [
        {"step_id": f"STEP-{i:02}", "actor": "Extra", "activity": f"Extra step {i}",
         "system_behavior": "Behavior", "decision_or_rule": "TBD", "outcome": "Done",
         "requirement_ids": ["FR-01"]} for i in range(13, 20)
    ]
    with pytest.raises(FSDValidationError) as exc:
        validate_fsd_document(bad_doc, project)
    assert "exceeds" in str(exc.value)

    # Quality Gate 2: Fail if approval context exists but no decision step exists
    no_decision_doc = deepcopy(doc)
    for step in no_decision_doc["process_steps"]:
        step["step_type"] = "task"
        step["decision_or_rule"] = "Perform task"
        step["activity"] = "Perform task"
    with pytest.raises(FSDValidationError) as exc:
        validate_fsd_document(no_decision_doc, project)
    assert "decision step" in str(exc.value).lower()
