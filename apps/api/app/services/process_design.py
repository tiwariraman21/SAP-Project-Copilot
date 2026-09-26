from __future__ import annotations

import re
from typing import Any


STEP_TYPES = {"start", "task", "decision", "end"}
FLOORPLANS = {
    "list_report": "SAP Fiori elements - List Report",
    "object_page": "SAP Fiori elements - Object Page",
    "my_inbox": "SAP Fiori - My Inbox",
    "scan": "SAPUI5 - Freestyle",
    "form": "SAP Fiori elements - Object Page",
}

_DECISION_HINT = re.compile(
    r"\b(approv|reject|return|valid|eligib|decid|authorize|authorise|admit|deny|scan|verif)\w*\b"
    r"|[?]",
    re.I,
)
_CATALOGUE_HINT = re.compile(r"^execute approved requirement group\b", re.I)


def brd_payload(project: Any) -> dict:
    knowledge = getattr(project, "brd_knowledge", None)
    payload = getattr(knowledge, "payload", None) if knowledge else None
    return payload if isinstance(payload, dict) else {}


def step_type_of(step: dict) -> str:
    explicit = str(step.get("step_type") or "").strip().lower()
    if explicit in STEP_TYPES:
        return explicit
    text = f"{step.get('decision_or_rule') or ''} {step.get('activity') or ''}"
    if _is_decision_text(text):
        return "decision"
    return "task"


def floorplan_of(screen: dict) -> str:
    explicit = str(screen.get("floorplan") or "").strip().lower().replace(" ", "_")
    aliases = {
        "listreport": "list_report", "list": "list_report", "worklist": "list_report",
        "objectpage": "object_page", "object": "object_page",
        "inbox": "my_inbox", "myinbox": "my_inbox",
        "qr": "scan", "verify": "scan", "verification": "scan",
    }
    if explicit in FLOORPLANS:
        return explicit
    if explicit in aliases:
        return aliases[explicit]
    blob = " ".join(str(screen.get(key) or "") for key in ("proposed_technology", "name", "purpose")).lower()
    if any(token in blob for token in ("inbox", "approval task", "my inbox")):
        return "my_inbox"
    if any(token in blob for token in ("scanner", "gate verif", "admit", "deny")) or ("scan" in blob and "download" not in blob):
        return "scan"
    if "qr" in blob and any(token in blob for token in ("verif", "camera", "mobile", "guard", "security")):
        return "scan"
    if "download" in blob or "object page" in blob or "object header" in blob:
        return "object_page"
    if "list report" in blob or "worklist" in blob or "filter bar" in blob:
        return "list_report"
    return "object_page" if any(token in blob for token in ("detail", "download", "status", "request")) else "list_report"


def used_legend_shapes(steps: list[dict], *, drew_terminals: bool = False) -> set[str]:
    used = set()
    if steps:
        used.add("swimlane")
    if len(steps) > 1:
        used.add("connector")
    types = {step_type_of(step) for step in steps}
    if types & {"start", "end"}:
        used.add("start")
    if "task" in types or not types:
        used.add("task")
    if "decision" in types:
        used.add("decision")
    has_exception_branch = any(
        step_type_of(step) == "decision" and any(
            tok in str(step.get("branch_no_label") or "").lower()
            for tok in ("return", "reject", "deny", "exception", "no", "invalid", "fail")
        )
        for step in steps
    )
    if drew_terminals or has_exception_branch:
        used.add("exception")
    return used


def process_flow_mermaid(steps: list[dict]) -> str:
    lines = ["flowchart TD"]
    actors: list[str] = []
    for step in steps:
        actor = str(step.get("actor") or "Process").strip() or "Process"
        if actor not in actors:
            actors.append(actor)
    for actor in actors:
        safe = re.sub(r"[^A-Za-z0-9]", "", actor) or "Lane"
        lines.append(f"    subgraph {safe}[{_short(actor, 40)}]")
        for step in steps:
            if str(step.get("actor") or "Process").strip() != actor:
                continue
            sid = step.get("step_id") or "STEP"
            label = _short(step.get("activity") or sid, 42)
            if step_type_of(step) == "decision":
                lines.append(f"        {sid}{{{label}}}")
            else:
                lines.append(f"        {sid}[{label}]")
        lines.append("    end")
    by_id = {step.get("step_id"): step for step in steps}
    for index, step in enumerate(steps):
        sid = step.get("step_id")
        if step_type_of(step) == "decision":
            yes = step.get("branch_yes_target") or _next_id(steps, index)
            no = step.get("branch_no_target")
            if yes:
                lines.append(f"    {sid} -->|{step.get('branch_yes_label') or 'Yes'}| {yes}")
            if no and no in by_id:
                lines.append(f"    {sid} -->|{step.get('branch_no_label') or 'No'}| {no}")
        else:
            nxt = step.get("branch_yes_target") or _next_id(steps, index)
            if nxt:
                lines.append(f"    {sid} --> {nxt}")
    return "\n".join(lines)


def screen_navigation_mermaid(screens: list[dict]) -> str:
    if not screens:
        return "flowchart LR\n    Launchpad[Fiori Launchpad]"
    lines = ["flowchart LR", "    Launchpad[Fiori Launchpad]"]
    first = screens[0].get("screen_id") or "SCR-01"
    lines.append(f"    Launchpad --> {first}")
    seen: set[tuple[str, str]] = set()
    for source, target, label in navigation_edges(screens):
        key = (source, target)
        if key in seen:
            continue
        seen.add(key)
        if label and label != "Open":
            lines.append(f"    {source} -->|{label}| {target}")
        else:
            lines.append(f"    {source} --> {target}")
    return "\n".join(lines)


def navigation_edges(screens: list[dict]) -> list[tuple[str, str, str]]:
    ids = {str(screen.get("screen_id") or ""): screen for screen in screens if screen.get("screen_id")}
    name_to_id: dict[str, str] = {}
    for screen in screens:
        sid = str(screen.get("screen_id") or "")
        name = str(screen.get("name") or "").lower().strip()
        if sid and name:
            name_to_id[name] = sid
            if "purchase order" in name and "page" not in name:
                name_to_id.setdefault("po_list", sid)
            if "object page" in name or ("request" in name and "status" not in name and "download" not in name):
                name_to_id.setdefault("po_request", sid)
            if "status" in name or "visibility" in name:
                name_to_id.setdefault("request_status", sid)
            if "level 1" in name or "l1" in name:
                name_to_id.setdefault("inbox_l1", sid)
            if "level 2" in name or "l2" in name:
                name_to_id.setdefault("inbox_l2", sid)
            if "download" in name or "approved" in name:
                name_to_id.setdefault("download", sid)
            if "verification" in name or "scan" in name or "gate" in name:
                name_to_id.setdefault("gate_verify", sid)

    edges: list[tuple[str, str, str]] = []
    for screen in screens:
        source = str(screen.get("screen_id") or "")
        for raw_target in screen.get("navigates_to") or []:
            target_str = str(raw_target).strip()
            target_id = ""
            if target_str in ids:
                target_id = target_str
            else:
                target_lower = target_str.lower()
                if target_lower in name_to_id:
                    target_id = name_to_id[target_lower]
                else:
                    for key, val in name_to_id.items():
                        if key in target_lower or target_lower in key:
                            target_id = val
                            break
            if source and target_id and target_id in ids and target_id != source:
                label = "Return" if ("inbox" in source.lower() and "request" in target_str.lower()) else "Open"
                edges.append((source, target_id, label))
    if edges:
        return edges

    # Grounded fallback matching real SAP application structure:
    # 1. Supplier track: List Report -> Object Page Request -> Status Page -> Pass Download
    # 2. Approver track: My Inbox L1 -> My Inbox L2 -> Pass Download, plus Return loop to Request
    # 3. Security track: Launchpad / Scanner -> Gate Verification
    by_plan: dict[str, list[dict]] = {}
    for screen in screens:
        by_plan.setdefault(floorplan_of(screen), []).append(screen)

    lists = by_plan.get("list_report") or []
    objects = by_plan.get("object_page") or []
    inboxes = by_plan.get("my_inbox") or []
    scans = by_plan.get("scan") or []

    if lists and objects:
        edges.append((lists[0]["screen_id"], objects[0]["screen_id"], "Open PO"))
    if len(objects) >= 2:
        edges.append((objects[0]["screen_id"], objects[1]["screen_id"], "Submit Request"))
    if len(objects) >= 3:
        edges.append((objects[1]["screen_id"], objects[2]["screen_id"], "Download"))
    if inboxes:
        if len(inboxes) >= 2:
            edges.append((inboxes[0]["screen_id"], inboxes[1]["screen_id"], "L1 Approve"))
            if objects:
                edges.append((inboxes[0]["screen_id"], objects[0]["screen_id"], "Return"))
            if len(objects) >= 3:
                edges.append((inboxes[1]["screen_id"], objects[2]["screen_id"], "Final Approve"))
        elif objects and len(objects) >= 3:
            edges.append((inboxes[0]["screen_id"], objects[2]["screen_id"], "Approve"))

    return edges


def build_process_steps(project: Any, approved: list, existing: list[dict] | None, limit: int) -> list[dict]:
    candidates = [dict(item) for item in existing or [] if isinstance(item, dict)]
    if _is_process_graph(candidates, approved):
        steps = _normalize_steps(candidates[:limit], approved)
    else:
        brd_steps = _from_brd_process(project, approved, limit)
        steps = brd_steps if len(brd_steps) >= 3 else _inferred_process(project, approved, limit)
    return _ensure_requirement_coverage(steps[:limit], approved)


def build_screens(project: Any, approved: list, existing: list[dict] | None, display_name: str, limits: dict) -> list[dict]:
    payload = brd_payload(project)
    brd_screens = [item for item in (payload.get("screens") or []) if isinstance(item, dict)]
    if brd_screens:
        screens = [_screen_from_brd(item, approved, payload, index) for index, item in enumerate(brd_screens[:limits.get("screens", 10)], 1)]
    else:
        screens = [_repair_screen(item, approved, payload, index) for index, item in enumerate(existing or [], 1)]
        screens = [item for item in screens if item.get("requirement_ids")]
    if not screens:
        screens = _inferred_screens(project, approved, display_name)
    screens = screens[:limits.get("screens", 10)]
    field_limit = limits.get("screen_fields", 25)
    action_limit = limits.get("screen_actions", 10)
    for screen in screens:
        screen["fields"] = (screen.get("fields") or [])[:field_limit]
        screen["actions"] = (screen.get("actions") or [])[:action_limit]
        screen["messages"] = (screen.get("messages") or [])[:4]
        screen["floorplan"] = floorplan_of(screen)
        screen["proposed_technology"] = screen.get("proposed_technology") or FLOORPLANS[screen["floorplan"]]
    _assign_navigation(screens)
    return screens


def build_actors(steps: list[dict], approved: list) -> list[dict]:
    ids = [item.requirement_key for item in approved]
    actors = []
    seen: set[str] = set()
    for step in steps:
        name = str(step.get("actor") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        actors.append({
            "name": name,
            "actor_type": "System" if re.search(r"\b(sap|s/4|application|system)\b", name, re.I) else "Human",
            "responsibility": f"Perform {step.get('activity') or 'the assigned process step'}",
            "requirement_ids": list(ids),
        })
    return actors or [{
        "name": "Business User", "actor_type": "Human",
        "responsibility": "Execute and review the process", "requirement_ids": ids,
    }]


def _is_decision_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or text.upper() == "TBD":
        return False
    if _CATALOGUE_HINT.search(text):
        return False
    return bool(_DECISION_HINT.search(text))


def _is_process_graph(steps: list[dict], approved: list) -> bool:
    if len(steps) < 2:
        return False
    titles = {str(item.title or "").strip().lower() for item in approved}
    activities = [str(step.get("activity") or "").strip() for step in steps]
    if any(_CATALOGUE_HINT.search(activity) for activity in activities):
        return False
    if activities and all(activity.lower() in titles for activity in activities if activity):
        return False
    actors = {str(step.get("actor") or "").strip() for step in steps}
    generic = actors <= {"", "Business User", "Business User / SAP", "Business User / Existing Process"}
    has_decision = any(step_type_of(step) == "decision" for step in steps)
    if generic and not has_decision and len(steps) > 4:
        return False
    return True


def _from_brd_process(project: Any, approved: list, limit: int) -> list[dict]:
    payload = brd_payload(project)
    raw_steps = [s for s in (payload.get("process_steps") or []) if isinstance(s, dict)]
    blob = _context_blob(approved, payload)
    ids = [item.requirement_key for item in approved]

    is_gate_pass = bool(re.search(r"\b(gate.?pass|vehicle|driver|admit.*deny)\b", blob))
    if is_gate_pass:
        return _build_gate_pass_process(payload, approved, limit)

    steps: list[dict] = []
    for index, raw in enumerate(raw_steps[:limit], 1):
        activity = str(raw.get("activity") or raw.get("business_result") or f"Process step {index}").strip()
        actor = str(raw.get("actor") or raw.get("system") or "Business User").strip() or "Business User"
        biz_result = str(raw.get("business_result") or activity)
        decision = _is_decision_text(activity) or _is_decision_text(biz_result)
        step_id = str(raw.get("step_id") or f"STEP-{index:02}")

        yes_label = "Approve" if "approv" in (activity + biz_result).lower() else ("Valid" if "valid" in (activity + biz_result).lower() else "Yes")
        no_label = "Reject / Return" if "approv" in (activity + biz_result).lower() else ("Invalid" if "valid" in (activity + biz_result).lower() else "No")

        steps.append(_step(
            step_id, actor, activity,
            biz_result,
            f"{activity}?" if not activity.endswith("?") else activity,
            "decision" if decision else "task",
            ids,
            yes=yes_label if decision else "",
            no=no_label if decision else "",
        ))

    if len(steps) >= 3:
        return _link_branches(steps)
    return _inferred_process(project, approved, limit)


def _build_gate_pass_process(payload: dict, approved: list, limit: int) -> list[dict]:
    ids = [item.requirement_key for item in approved]
    supplier = _named_actor(payload, ("supplier", "requester"), "Supplier Requester")
    application = _named_actor(payload, ("application", "s/4", "sap"), "Application / S4")
    level1 = _named_actor(payload, ("level 1", "l1", "operations approver"), "Level 1 Approver")
    level2 = _named_actor(payload, ("level 2", "l2", "final approv", "security approver"), "Level 2 Approver")
    gate = _named_actor(payload, ("gate", "security", "scanner"), "Gate Security")

    po_ids = _matching_ids(approved, "po purchase order eligible eligibility open") or ids
    req_ids = _matching_ids(approved, "request submit draft vehicle driver time slot") or ids
    val_ids = _matching_ids(approved, "validate snapshot lock validation duplicate") or ids
    l1_ids = _matching_ids(approved, "level 1 l1 my inbox operational review approve return") or ids
    l2_ids = _matching_ids(approved, "level 2 l2 final authorization approve reject") or ids
    pass_ids = _matching_ids(approved, "pdf qr generate issue token download") or ids
    scan_ids = _matching_ids(approved, "scan verify qr token fail closed") or ids
    gate_ids = _matching_ids(approved, "admit deny gate entry record outcome audit") or ids

    steps = [
        _step("STEP-01", supplier, "Open eligible PO",
              "Supplier searches and opens authorized, eligible purchase orders", "", "start", po_ids),
        _step("STEP-02", supplier, "Enter and submit request",
              "Capture visit date, vehicle, driver details and delivery note", "", "task", req_ids),
        _step("STEP-03", application, "Validate request?",
              "Perform eligibility re-checks, duplicate detection and lock snapshot", "Request valid?", "decision", val_ids,
              yes="Valid", no="Return to Supplier"),
        _step("STEP-04", level1, "Level 1 approved?",
              "Operational review in My Inbox: verify dock capacity and supplier authorization", "Approved?", "decision", l1_ids,
              yes="Approve", no="Return / Reject"),
        _step("STEP-05", level2, "Level 2 approved?",
              "Final security and plant authorization in My Inbox", "Final approval?", "decision", l2_ids,
              yes="Approve", no="Reject"),
        _step("STEP-06", application, "Generate PDF and QR token",
              "Issue immutable gate pass PDF and generate signed QR verification token", "", "task", pass_ids),
        _step("STEP-07", supplier, "Track status and download pass",
              "Supplier tracks approval status and downloads authorized gate pass document", "", "task", pass_ids),
        _step("STEP-08", gate, "QR valid?",
              "Scan QR code at entry gate, resolve token live against backend", "Valid?", "decision", scan_ids,
              yes="Admit", no="Deny"),
        _step("STEP-09", gate, "Admit vehicle and log entry",
              "Verify vehicle/driver identity against minimum disclosure and record entry timestamp", "", "end", gate_ids),
        _step("STEP-10", gate, "Deny entry and log exception",
              "Fail closed on expired, invalid or revoked pass and record gate security exception", "", "end", gate_ids),
    ]

    steps[0]["branch_yes_target"] = "STEP-02"
    steps[1]["branch_yes_target"] = "STEP-03"
    steps[2]["branch_yes_target"] = "STEP-04"
    steps[2]["branch_no_target"] = "STEP-02"
    steps[3]["branch_yes_target"] = "STEP-05"
    steps[3]["branch_no_target"] = "STEP-02"
    steps[4]["branch_yes_target"] = "STEP-06"
    steps[4]["branch_no_target"] = "STEP-10"
    steps[5]["branch_yes_target"] = "STEP-07"
    steps[6]["branch_yes_target"] = "STEP-08"
    steps[7]["branch_yes_target"] = "STEP-09"
    steps[7]["branch_no_target"] = "STEP-10"

    return steps[:limit]


def _inferred_process(project: Any, approved: list, limit: int) -> list[dict]:
    payload = brd_payload(project)
    blob = _context_blob(approved, payload)
    ids = [item.requirement_key for item in approved]

    is_gate_pass = bool(re.search(r"\b(gate.?pass|vehicle|driver|admit.*deny)\b", blob))
    if is_gate_pass:
        return _build_gate_pass_process(payload, approved, limit)

    supplier = _named_actor(payload, ("supplier", "requester", "buyer"), "Business Requester")
    application = _named_actor(payload, ("application", "s/4", "sap", "system"), "Application / S4")
    level1 = _named_actor(payload, ("level 1", "l1", "approver", "manager"), "Approver")
    level2 = _named_actor(payload, ("level 2", "l2", "final approv"), "Final Approver")
    has_l1 = bool(re.search(r"\b(level\s*1|\bl1\b|my inbox|approv)\b", blob))
    has_l2 = bool(re.search(r"\b(level\s*2|\bl2\b|final approv|two.?step)\b", blob))

    steps: list[dict] = [
        _step("STEP-01", supplier, "Open business record", "Search and select authorized record", "", "start", ids),
        _step("STEP-02", supplier, "Submit request", "Capture required input fields and submit", "", "task", ids),
        _step("STEP-03", application, "Request valid?", "Execute automated validation checks", "Valid?", "decision", ids,
              yes="Valid", no="Return"),
    ]
    if has_l1:
        steps.append(_step("STEP-04", level1, "Approved?", "Review and decide in My Inbox", "Approved?", "decision", ids,
                           yes="Approve", no="Reject / Return"))
    if has_l2:
        steps.append(_step("STEP-05", level2, "Final approval?", "Final review before commit", "Authorized?", "decision", ids,
                           yes="Approve", no="Reject"))
    steps.append(_step(f"STEP-{len(steps)+1:02}", application, "Commit transaction", "Record authorized business outcome", "", "task", ids))
    steps.append(_step(f"STEP-{len(steps)+1:02}", supplier, "View completed outcome", "Display confirmation and audit trail", "", "end", ids))
    return _link_branches(steps[:limit])


def _inferred_screens(project: Any, approved: list, display_name: str) -> list[dict]:
    payload = brd_payload(project)
    blob = _context_blob(approved, payload)
    ids = [item.requirement_key for item in approved]
    fields = _fields_from_brd(payload, approved, "SCR")
    screens = []
    if re.search(r"\b(purchase order|\bpo\b|list|search|filter)\b", blob) or True:
        screens.append(_screen_spec(
            "SCR-01", f"{display_name} worklist", "Search, filter and open eligible business records",
            "list_report", ["Business User"], ids, fields[:6] or [_field("SCR-01-FLD-01", "Business record", "ObjectIdentifier", False, ids)],
            [_action("Open", "A row is selected", "Object page opens", ids)],
        ))
    screens.append(_screen_spec(
        "SCR-02", f"{display_name} details", "Review trusted data and complete the approved action",
        "object_page", ["Business User"], ids, fields[:8] or [_field("SCR-02-FLD-01", "Status", "ObjectStatus", False, ids)],
        [_action("Submit", "Required fields are complete", "The next process step starts", ids)],
    ))
    if re.search(r"\b(my inbox|approv|level\s*1)\b", blob):
        screens.append(_screen_spec(
            "SCR-03", "My Inbox approval", "Decide the assigned workflow task",
            "my_inbox", ["Approver"], ids, fields[:6],
            [_action("Approve", "Task is claimed and authorized", "Workflow advances", ids),
             _action("Reject", "A reason is entered", "Workflow ends", ids)],
        ))
    if re.search(r"\b(qr|scan|gate)\b", blob):
        screens.append(_screen_spec(
            "SCR-04", "QR verification", "Live pass check with minimum disclosure",
            "scan", ["Gate Security"], ids,
            [_field("SCR-04-FLD-01", "Pass status", "ObjectStatus", False, ids),
             _field("SCR-04-FLD-02", "Pass number", "Text", False, ids)],
            [_action("Admit", "Scan result is valid", "Entry is recorded", ids),
             _action("Deny", "Scan failed or policy blocks entry", "Denial is recorded", ids)],
        ))
    return screens


def _screen_from_brd(raw: dict, approved: list, payload: dict, index: int) -> dict:
    ids = _matching_ids(approved, " ".join(str(raw.get(key) or "") for key in ("name", "purpose", "floorplan"))) or [item.requirement_key for item in approved]
    screen_id = str(raw.get("screen_id") or f"SCR-{index:02}")
    plan = floorplan_of({**raw, "proposed_technology": raw.get("floorplan") or raw.get("proposed_technology")})
    labels = [str(item) for item in (raw.get("fields") or raw.get("columns") or raw.get("filters") or []) if str(item).strip()]
    if not labels:
        labels = [item.get("field_name") for item in payload.get("data_fields") or [] if isinstance(item, dict) and item.get("field_name")]
    fields = [_field(f"{screen_id}-FLD-{offset:02}", label, _control_for(label, plan), plan == "object_page" and offset > 1, ids)
              for offset, label in enumerate(labels[:12], 1)]
    actions = [_action(str(name), "The user is authorized for the action", "The next approved step is available", ids)
               for name in (raw.get("actions") or [])[:6]]
    if not actions:
        actions = [_action("Open" if plan == "list_report" else "Submit", "Required context is available", "The next page or confirmation is displayed", ids)]
    screen = _screen_spec(screen_id, str(raw.get("name") or f"Screen {index}"), str(raw.get("purpose") or raw.get("name") or "Process the approved business object"),
                          plan, raw.get("roles") or ["Business User"], ids, fields, actions)
    screen["navigates_to"] = [str(item) for item in (raw.get("navigation") or []) if str(item).strip()]
    return screen


def _repair_screen(raw: dict, approved: list, payload: dict, index: int) -> dict:
    screen = dict(raw)
    screen_id = str(screen.get("screen_id") or f"SCR-{index:02}")
    titles = {str(item.title or "").strip().lower() for item in approved}
    fields = [dict(item) for item in screen.get("fields") or [] if isinstance(item, dict)]
    if not fields or all(str(item.get("label") or "").strip().lower() in titles for item in fields):
        replacements = _fields_from_brd(payload, approved, screen_id)
        if replacements:
            fields = replacements
    screen["fields"] = fields
    screen["screen_id"] = screen_id
    screen["floorplan"] = floorplan_of(screen)
    if not screen.get("requirement_ids"):
        screen["requirement_ids"] = [item.requirement_key for item in approved]
    return screen


def _fields_from_brd(payload: dict, approved: list, prefix: str) -> list[dict]:
    ids = [item.requirement_key for item in approved]
    names: list[str] = []
    for item in payload.get("data_fields") or []:
        if isinstance(item, dict) and item.get("field_name"):
            names.append(str(item["field_name"]))
    for screen in payload.get("screens") or []:
        if not isinstance(screen, dict):
            continue
        for key in ("fields", "columns", "filters"):
            names.extend(str(value) for value in (screen.get(key) or []) if str(value).strip())
    unique = list(dict.fromkeys(name.strip() for name in names if name and name.strip()))
    if not unique:
        unique = [item.title for item in approved if getattr(item, "title", None)]
    return [_field(f"{prefix}-FLD-{index:02}", name, _control_for(name, "object_page"), False, ids) for index, name in enumerate(unique[:12], 1)]


def _assign_navigation(screens: list[dict]) -> None:
    ids = {str(screen.get("screen_id") or "") for screen in screens}
    for screen in screens:
        targets = [str(item) for item in (screen.get("navigates_to") or []) if str(item) in ids and str(item) != screen.get("screen_id")]
        screen["navigates_to"] = targets
    if any(screen.get("navigates_to") for screen in screens):
        return
    by_id = {screen["screen_id"]: screen for screen in screens if screen.get("screen_id")}
    for source, target, _label in navigation_edges([{**screen, "navigates_to": []} for screen in screens]):
        if source in by_id and target in by_id:
            by_id[source].setdefault("navigates_to", []).append(target)


def _normalize_steps(steps: list[dict], approved: list) -> list[dict]:
    ids = [item.requirement_key for item in approved]
    normalized = []
    for index, raw in enumerate(steps, 1):
        step = dict(raw)
        step["step_id"] = str(step.get("step_id") or f"STEP-{index:02}")
        step["actor"] = str(step.get("actor") or "Business User").strip() or "Business User"
        step["activity"] = str(step.get("activity") or step["step_id"]).strip()
        step["system_behavior"] = str(step.get("system_behavior") or step["activity"])
        step["decision_or_rule"] = str(step.get("decision_or_rule") or "")
        step["outcome"] = str(step.get("outcome") or step["activity"])
        step["requirement_ids"] = [item for item in (step.get("requirement_ids") or []) if item in {req.requirement_key for req in approved}] or list(ids)
        step["step_type"] = step_type_of(step)
        if step["step_type"] == "decision" and not step.get("branch_yes_label"):
            step["branch_yes_label"] = "Yes"
            step["branch_no_label"] = step.get("branch_no_label") or "No"
        normalized.append(step)
    return _link_branches(normalized)


def _link_branches(steps: list[dict]) -> list[dict]:
    by_id = {step["step_id"]: step for step in steps}
    for index, step in enumerate(steps):
        nxt = _next_id(steps, index)
        if step_type_of(step) == "decision":
            yes = str(step.get("branch_yes_target") or "")
            no = str(step.get("branch_no_target") or "")
            step["branch_yes_target"] = yes if yes in by_id else (nxt or "")
            step["branch_yes_label"] = str(step.get("branch_yes_label") or "Yes")
            step["branch_no_label"] = str(step.get("branch_no_label") or "No")
            step["branch_no_target"] = no if no in by_id else no
            if not step.get("decision_or_rule") or str(step.get("decision_or_rule")).upper() == "TBD":
                step["decision_or_rule"] = step["activity"] if str(step["activity"]).endswith("?") else f"{step['activity']}?"
        else:
            step["branch_yes_label"] = ""
            step["branch_no_label"] = ""
            step["branch_no_target"] = ""
            step["branch_yes_target"] = str(step.get("branch_yes_target") or nxt or "")
            if step.get("branch_yes_target") not in by_id:
                step["branch_yes_target"] = nxt or ""
    if steps and step_type_of(steps[0]) == "task":
        steps[0]["step_type"] = "start"
    if steps and step_type_of(steps[-1]) in {"task", "start"}:
        steps[-1]["step_type"] = "end"
    return steps


def _ensure_requirement_coverage(steps: list[dict], approved: list) -> list[dict]:
    cited = {item for step in steps for item in step.get("requirement_ids") or []}
    missing = [item.requirement_key for item in approved if item.requirement_key not in cited]
    if missing and steps:
        host = next((step for step in steps if step_type_of(step) != "decision"), steps[0])
        host["requirement_ids"] = list(dict.fromkeys([*(host.get("requirement_ids") or []), *missing]))
    for step in steps:
        if not step.get("requirement_ids"):
            step["requirement_ids"] = [item.requirement_key for item in approved]
    return steps


def _matching_ids(approved: list, text: str) -> list[str]:
    blob = text.lower()
    matched = []
    for item in approved:
        tokens = [part for part in re.findall(r"[a-z0-9]{4,}", f"{item.title} {item.statement}".lower()) if part not in {"shall", "system", "must", "with", "that", "this"}]
        if any(token in blob for token in tokens[:6]):
            matched.append(item.requirement_key)
    return matched


def _context_blob(approved: list, payload: dict) -> str:
    parts = [str(item.title or "") + " " + str(item.statement or "") for item in approved]
    for key in ("business_context", "desired_future_state", "executive_summary"):
        if payload.get(key):
            parts.append(str(payload[key]))
    for item in payload.get("process_steps") or []:
        if isinstance(item, dict):
            parts.append(" ".join(str(item.get(key) or "") for key in ("activity", "actor", "business_result")))
    for item in payload.get("screens") or []:
        if isinstance(item, dict):
            parts.append(" ".join(str(item.get(key) or "") for key in ("name", "purpose", "floorplan")))
    return " ".join(parts).lower()


def _named_actor(payload: dict, tokens: tuple[str, ...], fallback: str) -> str:
    for item in payload.get("stakeholders") or []:
        name = str(item.get("name") or "") if isinstance(item, dict) else ""
        lowered = name.lower()
        if name and any(token in lowered for token in tokens):
            return name
    return fallback


def _next_id(steps: list[dict], index: int) -> str:
    if index + 1 < len(steps):
        return str(steps[index + 1].get("step_id") or "")
    return ""


def _step(step_id: str, actor: str, activity: str, behavior: str, decision: str, step_type: str, ids: list[str],
          yes: str = "", no: str = "") -> dict:
    return {
        "step_id": step_id, "actor": actor, "activity": activity, "system_behavior": behavior,
        "decision_or_rule": decision if step_type == "decision" else "",
        "step_type": step_type, "branch_yes_label": yes, "branch_yes_target": "",
        "branch_no_label": no, "branch_no_target": "", "outcome": activity,
        "requirement_ids": list(ids),
    }


def _screen_spec(screen_id: str, name: str, purpose: str, plan: str, roles: list, ids: list[str],
                 fields: list[dict], actions: list[dict]) -> dict:
    wireframes = {
        "list_report": "Shell Bar > Dynamic Page Header > Variant and Filter Bar > Responsive Table > Table Toolbar",
        "object_page": "Shell Bar > Dynamic Page Header > Object Header and Status > Anchor Navigation > Content Sections > Footer Toolbar",
        "my_inbox": "Shell Bar > My Inbox task list > Task detail > Decision comment > Approve / Reject / Return",
        "scan": "Shell Bar > Scan result header > Minimum disclosure panel > Admit / Deny",
        "form": "Shell Bar > Dynamic Page Header > Form sections > Footer Toolbar",
    }
    return {
        "screen_id": screen_id, "name": name, "purpose": purpose, "roles": roles or ["Business User"],
        "entry_point": "Fiori Launchpad", "exit_conditions": ["User completes the screen action or returns to the previous page"],
        "proposed_technology": FLOORPLANS[plan], "floorplan": plan, "navigates_to": [],
        "requirement_ids": ids, "ascii_wireframe": wireframes[plan], "fields": fields, "actions": actions, "messages": [],
    }


def _field(field_id: str, label: str, control: str, required: bool, ids: list[str]) -> dict:
    return {
        "field_id": field_id, "label": label, "control": control, "data_type": "Text",
        "required": "Yes" if required else "No", "editable": "Yes" if required else "No",
        "source_or_default": "Approved BRD data", "validation": "Required format and authorization checks apply",
        "value_help": "TBD", "requirement_ids": list(ids),
    }


def _action(name: str, when: str, success: str, ids: list[str]) -> dict:
    return {
        "action": name, "enabled_when": when, "processing": name,
        "success_result": success, "failure_result": "An actionable Fiori message is displayed",
        "authorization": "Backend authorization on the action", "requirement_ids": list(ids),
    }


def _control_for(label: str, plan: str) -> str:
    lowered = label.lower()
    if "status" in lowered:
        return "ObjectStatus"
    if "date" in lowered:
        return "DatePicker"
    if any(token in lowered for token in ("search", "po number", "id")):
        return "SearchField" if plan == "list_report" else "ObjectIdentifier"
    if plan == "list_report":
        return "FilterField"
    return "Input"


def _short(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip() or "Step"
    return text if len(text) <= limit else text[: limit - 3].rsplit(" ", 1)[0] + "..."
