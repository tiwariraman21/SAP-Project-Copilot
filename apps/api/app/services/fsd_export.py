from __future__ import annotations

import html
import re
import textwrap
from contextvars import ContextVar
from io import BytesIO
from pathlib import Path
from typing import Any

from docx import Document as WordDocument
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image as PdfImage, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.pdfgen.canvas import Canvas

from ..fsd_template import get_fsd_template
from .process_design import floorplan_of, navigation_edges, used_legend_shapes
from .project_identity import looks_like_person_name, priority_label, process_identifier_from_name
from .timing import timed


GREEN, DARK, LIGHT, PALE, GRAY = "0D6B50", "17211E", "E8F3ED", "F5F8F6", "5B6762"
SECTIONS = list(get_fsd_template().sections)
_pdf_table_number: ContextVar[int] = ContextVar("pdf_table_number", default=0)
TABLE_TITLES = {
    ("Document Attribute", "Value"): "Cover document attributes",
    ("Attribute", "Value"): "Document control",
    ("Version", "Date", "Author", "Description"): "Document history",
    ("Role", "Name"): "Role summary",
    ("Role", "Name", "Status / Signature"): "Authorisers for sign off",
    ("Document Name", "Reference / Revision"): "Relevant documents",
    ("Current Constraint", "To-Be Response", "Expected Improvement", "Requirement IDs"): "Constraint to-be mapping",
    ("Current Constraint", "To-Be Response", "Expected Improvement", "Req IDs"): "Constraint to-be mapping",
    ("Actor / System", "Type", "Responsibility", "Requirement IDs"): "Actors and systems",
    ("Actor / System", "Type", "Responsibility", "Req IDs"): "Roles and responsibilities",
    ("Step", "Actor", "Activity and System Behaviour", "Outcome", "Req IDs"): "To-be activity list",
    ("Step", "Actor", "Activity / Behaviour", "Outcome", "Req IDs"): "To-be activity list",
    ("Flow Type", "Trigger", "Flow / Handling", "Expected Outcome", "Requirement IDs"): "Alternate and exception flows",
    ("Flow Type", "Trigger", "Flow / Handling", "Expected Outcome", "Req IDs"): "Alternate and exception flows",
    ("ID", "Requirement and Functional Behaviour", "Priority", "BRD Source"): "Requirement catalogue",
    ("Rule", "Condition / Description", "Expected Result", "Req IDs"): "Business rules",
    ("Rule", "Condition / Description", "Result", "Req IDs"): "Business rules",
    ("Field", "Detail"): "Record details",
    ("Field", "Label / Type", "Required / Validation", "Req IDs"): "Screen fields",
    ("Action", "Enabled When", "Success / Failure", "Req IDs"): "Screen actions",
    ("Action", "Enabled When", "Outcome", "Req IDs"): "Screen actions",
    ("ID", "Type", "Message", "Req IDs"): "Screen messages",
    ("Role", "Business Role", "Activities / Scope", "App / Auth Object", "Req IDs"): "Roles and authorizations",
    ("Test", "Req IDs", "Scenario / Steps", "Expected Result"): "Test conditions",
    ("RICEFW Item",): "Related RICEFW items",
    ("Req", "BRD Source", "Process", "Screen", "Rule", "Test", "Coverage"): "Requirement traceability",
    ("Information", "Detail"): "General data",
    ("Document", "Location / Reference"): "Related documents",
    ("Capability", "Technical Response", "Key Requirement IDs"): "Requirements summary",
    ("Object / Application", "Impact"): "Objects or transactions affected",
    ("Control", "Technical Design"): "Security, integrity and controls",
    ("ID", "Scenario", "User Message / Behavior", "Technical Handling"): "Error handling messages",
    ("Flow", "UI / Service Behavior", "Method / Mechanism"): "Fiori technical flow",
    ("Screen / View", "Proposed Technology", "Key Fields / Controls", "Actions"): "Selection screen details",
    ("Role", "Data Scope", "Technical Authorization Behavior", "SoD / Control"): "Security and authorization",
    ("Item", "Design"): "Fiori HTML5 / CSS design",
    ("Item", "Detail"): "Repository and transport details",
    ("Business Data", "Source / Contract", "Technical Rule"): "Database and data mapping",
    ("Program / Interface", "Purpose", "Direction"): "External programs",
    ("Object Type", "Object Name", "Purpose"): "SAP objects",
    ("Business Data", "Source / Contract", "UI Target", "Technical Rule"): "OData and data mapping",
    ("Rule / Condition", "Technical Behavior", "Open Decision"): "Workflow technical design",
    ("ID", "Condition / Test", "Expected Result", "Req Ref."): "Unit and assembly test conditions",
    ("Issue No.", "Description", "Assigned To", "Status", "Impact", "Resolution / Decision Needed"): "Outstanding issues",
    ("Status", "Source", "UI Semantic State", "Definition"): "Status model",
    ("Term", "Definition"): "Glossary of terms",
    ("Design Area", "FSD Requirements Covered", "Technical Design Sections"): "Requirement traceability",
    ("Version No.", "Date", "Author", "Revision Description"): "Revision history",
    ("Role", "Name", "Date Signed Off"): "Authorisers for sign off",
    ("Name / Team", "Role"): "Document distribution",
}


def _table_caption_text(number: int, headers: list[str], title: str | None = None) -> str:
    label = (title or "").strip() or TABLE_TITLES.get(tuple(headers)) or (headers[0] if len(headers) == 1 else f"{headers[0]} summary")
    return f"Table {number}: {label}"


def _safe(value: Any) -> str:
    if value is None or value == "":
        return "TBD"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return "; ".join(_safe(item) for item in value) or "None"
    if isinstance(value, dict):
        return "; ".join(f"{key.replace('_', ' ').title()}: {_safe(item)}" for key, item in value.items())
    return str(value).replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower() or "fsd"


def _export_display_name(document: dict, fallback: str) -> str:
    title = re.sub(r"\s*-\s*Functional (?:Solution )?Design\s*$", "", str(document.get("title") or ""), flags=re.I).strip()
    if title and not looks_like_person_name(title):
        return title
    if fallback and not looks_like_person_name(fallback):
        return fallback
    return title or fallback or "SAP Business Process"


def _apply_export_identity(document: dict, fallback: str) -> str:
    display_name = _export_display_name(document, fallback)
    document["title"] = display_name
    info = document.setdefault("document_information", {})
    identifier = str(info.get("process_identifier") or "")
    if not identifier or looks_like_person_name(identifier):
        info["process_identifier"] = process_identifier_from_name(display_name)
    return display_name


def _short_text(value: Any, limit: int) -> str:
    text = _safe(value)
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 3)].rsplit(" ", 1)[0].rstrip(" ,.;:") + "..."


def _short_ids(values: Any, limit: int = 4) -> str:
    items = values if isinstance(values, list) else ([values] if values else [])
    return ", ".join(_safe(value) for value in items[:limit]) + (f" (+{len(items) - limit})" if len(items) > limit else "")


def _font(size: int = 20, mono: bool = False, bold: bool = False):
    if mono:
        choices = [
            r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\cour.ttf",
            "/System/Library/Fonts/Supplemental/Courier New.ttf",
        ]
    elif bold:
        choices = [
            r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\calibrib.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]
    else:
        choices = [
            r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\calibri.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
        ]
    for choice in choices:
        if Path(choice).exists():
            return ImageFont.truetype(choice, size)
    return ImageFont.load_default()


def _brand_font(size: int = 64):
    """Use the condensed face that matches the InfraBeat web wordmark."""
    for choice in (r"C:\Windows\Fonts\arialnb.ttf", r"C:\Windows\Fonts\arialn.ttf", r"C:\Windows\Fonts\arialbd.ttf",
                   "/System/Library/Fonts/Supplemental/Arial Narrow Bold.ttf",
                   "/System/Library/Fonts/Supplemental/Arial Narrow.ttf",
                   "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        if Path(choice).exists():
            return ImageFont.truetype(choice, size)
    return _font(size)


@timed("Render process flow diagram")
def _draw_process_flow(steps: list[dict], output: Path, title: str = "To-Be Process Flow") -> None:
    steps = steps[:12]
    actors = list(dict.fromkeys(_safe(step.get("actor")) for step in steps)) or ["Process Owner"]
    label_width = 240
    top = 130
    lane_height = 190
    width = 1900
    height = top + len(actors) * lane_height + 55
    image = Image.new("RGB", (width, height), "#F8FAFC")
    draw = ImageDraw.Draw(image)

    # Title & Subtitle bar
    draw.text((40, 24), title, fill="#111827", font=_font(32, bold=True))
    draw.text((40, 68), "Swimlane sequence diagram grounded in approved BRD process design", fill="#64748B", font=_font(15))
    draw.line((40, 95, width - 40, 95), fill="#CBD5E1", width=2)

    # Swimlane backgrounds and headers
    for lane_index, actor in enumerate(actors):
        y0 = top + lane_index * lane_height
        y1 = y0 + lane_height
        lane_fill = "#FFFFFF" if lane_index % 2 == 0 else "#F1F5F9"
        draw.rectangle((label_width, y0, width - 40, y1), fill=lane_fill)
        draw.line((40, y0, width - 40, y0), fill="#E2E8F0", width=1)
        # Actor pill header
        draw.rounded_rectangle((40, y0 + 16, label_width - 15, y1 - 16), radius=8,
                               fill="#1E293B", outline="#0F172A", width=2)
        label = "\n".join(textwrap.wrap(_short_text(actor, 30), width=18))
        draw.multiline_text((label_width / 2 + 12, y0 + lane_height / 2), label, fill="#FFFFFF",
                            font=_font(14, bold=True), anchor="mm", spacing=3, align="center")

    draw.line((40, top + len(actors) * lane_height, width - 40, top + len(actors) * lane_height), fill="#CBD5E1", width=2)

    # Position each step strictly horizontally by its time index (slot 0..N-1)
    N = len(steps)
    start_x = label_width + 45
    col_width = (width - start_x - 60) / max(1, N)

    nodes: dict[str, dict] = {}
    for index, step in enumerate(steps):
        actor = _safe(step.get("actor"))
        lane_index = actors.index(actor) if actor in actors else 0
        cx = int(start_x + (index + 0.5) * col_width)
        cy = int(top + lane_index * lane_height + lane_height / 2)
        sid = str(step.get("step_id") or f"STEP-{index+1:02}")
        stype = str(step.get("step_type") or "").strip().lower()
        if not stype or stype not in {"start", "task", "decision", "end"}:
            if "?" in _safe(step.get("decision_or_rule")) or "?" in _safe(step.get("activity")):
                stype = "decision"
            elif index == 0:
                stype = "start"
            elif index == N - 1:
                stype = "end"
            else:
                stype = "task"

        hw = min(72, int(col_width * 0.40)) if stype == "decision" else min(76, int(col_width * 0.44))
        hh = 36 if stype == "decision" else (28 if stype in {"start", "end"} else 32)
        nodes[sid] = {
            "cx": cx, "cy": cy, "hw": hw, "hh": hh,
            "type": stype, "lane": lane_index, "index": index, "step": step, "sid": sid,
        }

    # Step connectors and branch arrows
    for index, step in enumerate(steps):
        sid = str(step.get("step_id") or f"STEP-{index+1:02}")
        node = nodes[sid]
        cx, cy, hw, hh, stype = node["cx"], node["cy"], node["hw"], node["hh"], node["type"]

        if stype == "decision":
            # 1. Primary (Yes/Approve) branch
            yes_target = str(step.get("branch_yes_target") or "")
            if not yes_target and index + 1 < N:
                yes_target = str(steps[index + 1].get("step_id") or f"STEP-{index+2:02}")
            if yes_target in nodes:
                tnode = nodes[yes_target]
                tcx, tcy, thw = tnode["cx"], tnode["cy"], tnode["hw"]
                sx, sy = cx + hw, cy
                ex, ey = tcx - thw, tcy
                if sy == ey:
                    draw.line((sx, sy, ex, ey), fill="#1E3A8A", width=3)
                    draw.polygon([(ex, ey), (ex - 10, ey - 6), (ex - 10, ey + 6)], fill="#1E3A8A")
                else:
                    mid_x = (sx + ex) // 2
                    draw.line((sx, sy, mid_x, sy, mid_x, ey, ex, ey), fill="#1E3A8A", width=3)
                    draw.polygon([(ex, ey), (ex - 10, ey - 6), (ex - 10, ey + 6)], fill="#1E3A8A")
                yes_label = _short_text(step.get("branch_yes_label") or "Yes", 16)
                draw.text((sx + 6, sy - 18), yes_label, fill="#0D6B50", font=_font(12, bold=True))

            # 2. Secondary (No/Return/Reject) branch
            no_target = str(step.get("branch_no_target") or "")
            no_label = _short_text(step.get("branch_no_label") or "No", 22)
            if no_target and no_target in nodes:
                tnode = nodes[no_target]
                tcx, tcy, thw, thh = tnode["cx"], tnode["cy"], tnode["hw"], tnode["hh"]
                if tnode["index"] < index:
                    # Return loop back to prior step: drop below, traverse horizontally, up into target bottom
                    loop_y = cy + hh + 24
                    draw.line((cx, cy + hh, cx, loop_y, tcx, loop_y, tcx, tcy + thh), fill="#D97706", width=2)
                    draw.polygon([(tcx, tcy + thh), (tcx - 6, tcy + thh + 9), (tcx + 6, tcy + thh + 9)], fill="#D97706")
                    draw.text(((cx + tcx) // 2, loop_y - 14), no_label, fill="#D97706", font=_font(11, bold=True), anchor="mm")
                else:
                    # Forward alternate path
                    draw.line((cx, cy + hh, cx, tcy, tcx - thw, tcy), fill="#BB0000", width=2)
                    draw.polygon([(tcx - thw, tcy), (tcx - thw - 9, tcy - 5), (tcx - thw - 9, tcy + 5)], fill="#BB0000")
                    draw.text((cx + 6, cy + hh + 4), no_label, fill="#BB0000", font=_font(11, bold=True))
            elif any(tok in no_label.lower() for tok in ("reject", "deny", "stop", "no", "invalid")):
                # Explicit terminal exception stop
                term_y = cy + hh + 32
                draw.line((cx, cy + hh, cx, term_y), fill="#BB0000", width=2)
                draw.ellipse((cx - 8, term_y - 8, cx + 8, term_y + 8), fill="#FFEBEE", outline="#BB0000", width=2)
                draw.text((cx + 14, term_y - 7), no_label, fill="#BB0000", font=_font(11, bold=True))
        elif stype != "end":
            # Normal forward task arrow
            nxt_id = str(step.get("branch_yes_target") or "")
            if not nxt_id and index + 1 < N:
                nxt_id = str(steps[index + 1].get("step_id") or f"STEP-{index+2:02}")
            if nxt_id and nxt_id in nodes:
                tnode = nodes[nxt_id]
                tcx, tcy, thw = tnode["cx"], tnode["cy"], tnode["hw"]
                sx, sy = cx + hw, cy
                ex, ey = tcx - thw, tcy
                if sy == ey:
                    draw.line((sx, sy, ex, ey), fill="#1E3A8A", width=3)
                    draw.polygon([(ex, ey), (ex - 10, ey - 6), (ex - 10, ey + 6)], fill="#1E3A8A")
                else:
                    mid_x = (sx + ex) // 2
                    draw.line((sx, sy, mid_x, sy, mid_x, ey, ex, ey), fill="#1E3A8A", width=3)
                    draw.polygon([(ex, ey), (ex - 10, ey - 6), (ex - 10, ey + 6)], fill="#1E3A8A")

    # Draw shapes and text on top of connectors
    for sid, node in nodes.items():
        cx, cy, hw, hh, stype, step = node["cx"], node["cy"], node["hw"], node["hh"], node["type"], node["step"]
        activity = _safe(step.get("activity"))

        if stype == "decision":
            # Diamond shape ONLY for decisions
            pts = [(cx, cy - hh), (cx + hw, cy), (cx, cy + hh), (cx - hw, cy)]
            draw.polygon(pts, fill="#FFFBEB", outline="#D97706", width=2)
            rule_text = _short_text(step.get("decision_or_rule") or activity, 36)
            label = "\n".join(textwrap.wrap(rule_text, width=13)[:3])
            draw.multiline_text((cx, cy), label, fill="#111827", font=_font(11, bold=True),
                                anchor="mm", align="center", spacing=1)
            draw.text((cx, cy + hh + 12), sid, fill="#D97706", font=_font(10), anchor="mm")
        elif stype in {"start", "end"}:
            # Pill shape
            is_end = stype == "end"
            is_deny = is_end and any(tok in activity.lower() for tok in ("deny", "reject", "stop", "cancel"))
            fill_col = "#FFEBEE" if is_deny else "#E8F5E9"
            out_col = "#C62828" if is_deny else "#2E7D32"
            draw.rounded_rectangle((cx - hw, cy - hh, cx + hw, cy + hh), radius=hh,
                                   fill=fill_col, outline=out_col, width=2)
            label = "\n".join(textwrap.wrap(_short_text(activity, 32), width=15)[:2])
            draw.multiline_text((cx, cy), label, fill="#111827", font=_font(11, bold=True),
                                anchor="mm", align="center", spacing=1)
            draw.text((cx, cy + hh + 12), sid, fill=out_col, font=_font(10), anchor="mm")
        else:
            # Rounded rectangle for task
            draw.rounded_rectangle((cx - hw, cy - hh, cx + hw, cy + hh), radius=6,
                                   fill="#EFF6FF", outline="#2563EB", width=2)
            label = "\n".join(textwrap.wrap(_short_text(activity, 46), width=16)[:3])
            draw.multiline_text((cx, cy - 6), label, fill="#111827", font=_font(11, bold=True),
                                anchor="mm", align="center", spacing=1)
            draw.text((cx, cy + hh - 10), sid, fill="#2563EB", font=_font(10), anchor="mm")

    image.save(output, "PNG")


@timed("Render process legend")
def _draw_process_legend(output: Path, steps: list[dict] | None = None, used_shapes: set[str] | None = None) -> None:
    if used_shapes is None:
        used_shapes = used_legend_shapes(steps or [])

    legend_defs = [
        ("swimlane", "Swimlane", "Actor, organization, or system responsible for the lane.", "swimlane"),
        ("start", "Start / End", "Beginning or completion of the business process.", "start"),
        ("task", "Task", "Business activity or system function in responsible lane.", "task"),
        ("decision", "Decision", "Approval, validation, or conditional branching point.", "decision"),
        ("connector", "Sequence Flow", "Direction of execution and process handover.", "connector"),
        ("exception", "Exception / Return", "Controlled alternate path, return loop, or denial.", "exception"),
    ]
    items = [item for item in legend_defs if item[0] in used_shapes]
    if not items:
        items = legend_defs[:4]

    rows = (len(items) + 1) // 2
    height = max(240, 110 + rows * 105)
    image = Image.new("RGB", (1500, height), "#F4F4F4")
    draw = ImageDraw.Draw(image)
    draw.text((55, 26), "PROCESS DIAGRAM LEGEND", fill="#111111", font=_font(30))
    draw.line((55, 74, 1445, 74), fill="#111111", width=3)

    for index, (_key, name, detail, shape_type) in enumerate(items):
        col, row = index % 2, index // 2
        x, y = 55 + col * 720, 95 + row * 105
        cx, cy = x + 85, y + 36
        if shape_type == "start":
            draw.rounded_rectangle((cx - 45, cy - 22, cx + 45, cy + 22), radius=22,
                                   fill="#E8F5E9", outline="#2E7D32", width=2)
            draw.text((cx, cy), "Start / End", fill="#2E7D32", font=_font(11, bold=True), anchor="mm")
        elif shape_type == "decision":
            draw.polygon([(cx, cy - 28), (cx + 50, cy), (cx, cy + 28), (cx - 50, cy)],
                         fill="#FFFBEB", outline="#D97706", width=2)
            draw.text((cx, cy), "Valid?", fill="#D97706", font=_font(11, bold=True), anchor="mm")
        elif shape_type == "connector":
            draw.line((x + 25, cy, x + 140, cy), fill="#1E3A8A", width=3)
            draw.polygon([(x + 140, cy), (x + 128, cy - 7), (x + 128, cy + 7)], fill="#1E3A8A")
            draw.text((x + 75, cy - 14), "Yes / Pass", fill="#0D6B50", font=_font(11, bold=True), anchor="mm")
        elif shape_type == "swimlane":
            draw.rounded_rectangle((x + 18, y + 8, x + 152, y + 64), radius=8,
                                   fill="#1E293B", outline="#0F172A", width=2)
            draw.text((x + 85, y + 36), "Role / System", fill="white", font=_font(11, bold=True), anchor="mm")
        elif shape_type == "exception":
            draw.line((x + 25, cy, x + 125, cy), fill="#D97706", width=2)
            draw.polygon([(x + 125, cy), (x + 115, cy - 6), (x + 115, cy + 6)], fill="#D97706")
            draw.ellipse((x + 130, cy - 9, x + 148, cy + 9), fill="#FFEBEE", outline="#C62828", width=2)
            draw.text((x + 75, cy - 14), "Return / Deny", fill="#D97706", font=_font(11, bold=True), anchor="mm")
        else:  # task
            draw.rounded_rectangle((x + 18, y + 8, x + 152, y + 64), radius=6,
                                   fill="#EFF6FF", outline="#2563EB", width=2)
            draw.text((x + 85, y + 36), "Activity", fill="#111827", font=_font(11, bold=True), anchor="mm")

        draw.text((x + 175, y + 10), name, fill="#17211E", font=_font(17, bold=True))
        draw.multiline_text((x + 175, y + 38), "\n".join(textwrap.wrap(detail, 54)), fill="#475569", font=_font(14), spacing=2)

    image.save(output, "PNG")


@timed("Render document branding")
def _draw_logos(left_path: Path, right_path: Path) -> None:
    left = Image.new("RGBA", (900, 220), (255, 255, 255, 0)); draw = ImageDraw.Draw(left)
    brand_font = _brand_font(110)
    infra = "Infra"
    draw.text((8, 28), infra, fill="#05A9D6", font=brand_font)
    infra_width = draw.textbbox((8, 28), infra, font=brand_font)[2] - 8
    draw.text((8 + infra_width - 6, 28), "Beat", fill="#ED1C24", font=brand_font)
    bbox = left.getbbox()
    if bbox:
        pad = 10
        left = left.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(left.width, bbox[2] + pad), min(left.height, bbox[3] + pad)))
    left.save(left_path, "PNG")
    right = Image.new("RGBA", (700, 190), (255, 255, 255, 0)); draw = ImageDraw.Draw(right)
    draw.ellipse((500, 18, 665, 168), fill="#E8F3ED", outline="#0D6B50", width=7); draw.text((537, 58), "CL", fill="#0D6B50", font=_font(43))
    draw.text((245, 50), "CLIENT", fill="#17211E", font=_font(42)); draw.text((300, 108), "DUMMY LOGO", fill="#65726C", font=_font(18))
    bbox = right.getbbox()
    if bbox:
        pad = 10
        right = right.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(right.width, bbox[2] + pad), min(right.height, bbox[3] + pad)))
    right.save(right_path, "PNG")


@timed("Render screen navigation")
def _draw_navigation(screens: list[dict], output: Path) -> None:
    screens = screens[:10]
    edges = navigation_edges(screens)
    by_id = {str(s.get("screen_id")): s for s in screens if s.get("screen_id")}

    width, height = 1600, 850
    image = Image.new("RGB", (width, height), "#F8FAFC")
    draw = ImageDraw.Draw(image)

    # Title header
    draw.text((50, 25), "SAP Application Screen Navigation", fill="#111827", font=_font(30, bold=True))
    draw.text((50, 68), "User journey tracks across Supplier portal, My Inbox approvals, and Gate Security verification.", fill="#64748B", font=_font(15))
    draw.line((50, 96, width - 50, 96), fill="#CBD5E1", width=2)

    # Check if screens match the Gate Pass 3-track structure
    has_po = any("po" in _safe(s.get("name")).lower() or "list" in _safe(s.get("name")).lower() for s in screens)
    has_inbox = any("inbox" in _safe(s.get("name")).lower() for s in screens)
    has_gate = any("verification" in _safe(s.get("name")).lower() or "scan" in _safe(s.get("name")).lower() for s in screens)

    positions: dict[str, tuple[int, int, int, int]] = {}

    if has_po and has_inbox and len(screens) >= 5:
        # Layout 3 clear business tracks:
        # Track 1: Supplier Requester Track (Y: 130..300)
        # Track 2: Approver Track / My Inbox (Y: 340..510)
        # Track 3: Gate Security Track (Y: 550..720)

        # Track 1 background
        draw.rounded_rectangle((50, 120, width - 50, 310), radius=10, fill="#FFFFFF", outline="#E2E8F0", width=1)
        draw.rounded_rectangle((50, 120, 260, 155), radius=6, fill="#0284C7")
        draw.text((65, 130), "SUPPLIER TRACK", fill="white", font=_font(12, bold=True))

        # Track 2 background
        draw.rounded_rectangle((50, 330, width - 50, 520), radius=10, fill="#FFFFFF", outline="#E2E8F0", width=1)
        draw.rounded_rectangle((50, 330, 260, 365), radius=6, fill="#7C3AED")
        draw.text((65, 340), "APPROVER TRACK", fill="white", font=_font(12, bold=True))

        # Track 3 background
        draw.rounded_rectangle((50, 540, width - 50, 730), radius=10, fill="#FFFFFF", outline="#E2E8F0", width=1)
        draw.rounded_rectangle((50, 540, 260, 575), radius=6, fill="#059669")
        draw.text((65, 550), "GATE SECURITY TRACK", fill="white", font=_font(12, bold=True))

        # Assign positions based on screen roles
        card_w, card_h = 240, 110
        t1_x = [70, 370, 670, 1070]
        t2_x = [370, 720, 1070]
        t3_x = [370, 770]

        t1_idx = 0
        t2_idx = 0
        for s in screens:
            sid = str(s.get("screen_id"))
            name = _safe(s.get("name")).lower()
            if "inbox" in name:
                x = t2_x[min(t2_idx, len(t2_x) - 1)]
                y = 380
                t2_idx += 1
            elif "scan" in name or "verification" in name or "gate" in name and "pass" not in name:
                x = t3_x[0]
                y = 590
            elif "download" in name or "approved" in name:
                x = 1070
                y = 230  # Shared hub between Track 1 & Track 2
            else:
                x = t1_x[min(t1_idx, len(t1_x) - 1)]
                y = 175
                t1_idx += 1
            positions[sid] = (x, y, card_w, card_h)
    else:
        # Generic grid layout
        per_row = 4
        card_w, card_h = 280, 120
        spacing_x = (width - 140) / per_row
        for index, screen in enumerate(screens):
            sid = str(screen.get("screen_id"))
            row, col = divmod(index, per_row)
            x = int(70 + col * spacing_x)
            y = 140 + row * 220
            positions[sid] = (x, y, card_w, card_h)

    # Draw screen cards
    for sid, (x, y, cw, ch) in positions.items():
        screen = by_id.get(sid, {})
        plan = floorplan_of(screen)
        badge_bg = "#E0F2FE" if plan == "list_report" else ("#EDE9FE" if plan == "my_inbox" else ("#D1FAE5" if plan == "scan" else "#FEF3C7"))
        badge_fg = "#0369A1" if plan == "list_report" else ("#6D28D9" if plan == "my_inbox" else ("#047857" if plan == "scan" else "#B45309"))

        draw.rounded_rectangle((x, y, x + cw, y + ch), radius=10, fill="#FFFFFF", outline="#CBD5E1", width=2)
        # Floorplan badge
        draw.rounded_rectangle((x + 12, y + 10, x + cw - 12, y + 32), radius=4, fill=badge_bg)
        draw.text((x + 18, y + 13), f"{sid} • {plan.upper().replace('_', ' ')}", fill=badge_fg, font=_font(11, bold=True))
        # Screen name
        name_lines = textwrap.wrap(_short_text(screen.get("name"), 40), width=22)[:2]
        draw.multiline_text((x + 14, y + 42), "\n".join(name_lines), fill="#111827", font=_font(14, bold=True), spacing=2)
        # Roles / Purpose
        roles = ", ".join(screen.get("roles") or ["Business User"])[:28]
        draw.text((x + 14, y + ch - 22), roles, fill="#64748B", font=_font(11))

    # Draw navigation edges with branch labels
    drawn_edges: set[tuple[str, str]] = set()
    for source, target, label in edges:
        if (source, target) in drawn_edges or source not in positions or target not in positions or source == target:
            continue
        drawn_edges.add((source, target))

        sx, sy, sw, sh = positions[source]
        tx, ty, tw, th = positions[target]

        is_return = "return" in label.lower() or (tx <= sx and ty < sy)

        if is_return:
            # Curved return arrow loop up/left
            start_pt = (sx + 40, sy)
            end_pt = (tx + tw - 30, ty + th)
            mid_y = (sy + ty + th) // 2
            draw.line((start_pt[0], start_pt[1], start_pt[0], mid_y, end_pt[0], mid_y, end_pt[0], end_pt[1]), fill="#D97706", width=2)
            draw.polygon([(end_pt[0], end_pt[1]), (end_pt[0] - 6, end_pt[1] + 9), (end_pt[0] + 6, end_pt[1] + 9)], fill="#D97706")
            draw.text((start_pt[0] - 10, mid_y - 14), label or "Return", fill="#D97706", font=_font(11, bold=True))
        elif tx > sx and abs(ty - sy) < 40:
            # Direct horizontal right arrow
            start_pt = (sx + sw, sy + sh // 2)
            end_pt = (tx, ty + th // 2)
            draw.line((*start_pt, *end_pt), fill="#1E3A8A", width=3)
            draw.polygon([(end_pt[0], end_pt[1]), (end_pt[0] - 9, end_pt[1] - 5), (end_pt[0] - 9, end_pt[1] + 5)], fill="#1E3A8A")
            if label and label != "Open":
                draw.text(((start_pt[0] + end_pt[0]) // 2, start_pt[1] - 16), label, fill="#1E3A8A", font=_font(11, bold=True), anchor="mm")
        else:
            # Stepped orthogonal connector
            start_pt = (sx + sw, sy + sh // 2)
            end_pt = (tx, ty + th // 2)
            mid_x = (start_pt[0] + end_pt[0]) // 2
            draw.line((start_pt[0], start_pt[1], mid_x, start_pt[1], mid_x, end_pt[1], end_pt[0], end_pt[1]), fill="#1E3A8A", width=3)
            draw.polygon([(end_pt[0], end_pt[1]), (end_pt[0] - 9, end_pt[1] - 5), (end_pt[0] - 9, end_pt[1] + 5)], fill="#1E3A8A")
            if label and label != "Open":
                draw.text((mid_x + 8, (start_pt[1] + end_pt[1]) // 2), label, fill="#1E3A8A", font=_font(11, bold=True))

    image.save(output, "PNG")


@timed("Render Fiori screen wireframe")
def _draw_wireframe(screen: dict, output: Path, detail: bool = False) -> None:
    _draw_fiori_screen(screen, output)


@timed("Render standards-based Fiori screen")
def _draw_fiori_screen(screen: dict, output: Path) -> None:
    """Render a dedicated SAP Fiori floorplan using BRD-grounded fields and actions."""
    image = Image.new("RGB", (1600, 1000), "#F7F8FA")
    draw = ImageDraw.Draw(image)

    fields = screen.get("fields", [])[:12]
    actions = screen.get("actions", [])[:4]
    plan = floorplan_of(screen)
    sid = _safe(screen.get("screen_id"))
    sname = _safe(screen.get("name"))
    purpose = _safe(screen.get("purpose"))

    # Fiori Launchpad Shell Bar (Shared across all floorplans)
    draw.rectangle((0, 0, 1600, 60), fill="#1E293B")
    draw.text((30, 16), "SAP", fill="white", font=_font(22, bold=True))
    draw.text((95, 17), "Fiori Launchpad", fill="#94A3B8", font=_font(17))
    draw.text((1240, 20), "Search    Notifications    Help", fill="#94A3B8", font=_font(13))
    draw.ellipse((1530, 12, 1566, 48), fill="#38BDF8")
    draw.text((1541, 21), "BU", fill="#0F172A", font=_font(12, bold=True))

    # Page Header Banner
    draw.rectangle((0, 60, 1600, 145), fill="#FFFFFF")
    draw.line((0, 145, 1600, 145), fill="#E2E8F0", width=1)
    breadcrumb = f"Home / {plan.replace('_', ' ').title()}"
    draw.text((40, 72), breadcrumb, fill="#0284C7", font=_font(12))
    draw.text((40, 94), f"{sid}  {sname}", fill="#0F172A", font=_font(24, bold=True))
    draw.text((40, 123), _short_text(purpose, 110), fill="#64748B", font=_font(13))

    content_top = 165

    if plan == "list_report":
        # =========================================================================
        # FLOORPLAN 1: LIST REPORT (PO WORKLIST)
        # =========================================================================
        # Filter Bar Container
        draw.rounded_rectangle((40, content_top, 1560, content_top + 160), radius=8, fill="#FFFFFF", outline="#E2E8F0", width=1)
        draw.text((60, content_top + 14), "Standard ▾", fill="#0284C7", font=_font(15, bold=True))
        draw.text((160, content_top + 16), "Filter Bar", fill="#334155", font=_font(14))

        # 4 filter inputs with business labels
        filter_labels = [f.get("label") for f in fields if f.get("label")][:4] or ["Purchase Order", "Plant", "Delivery Date", "Approval Status"]
        for idx, flabel in enumerate(filter_labels[:4]):
            fx = 60 + idx * 310
            draw.text((fx, content_top + 48), _short_text(flabel, 22), fill="#475569", font=_font(12, bold=True))
            draw.rounded_rectangle((fx, content_top + 70, fx + 280, content_top + 105), radius=4, fill="#F8FAFC", outline="#CBD5E1", width=1)
            draw.text((fx + 10, content_top + 80), "Select or enter...", fill="#94A3B8", font=_font(12))

        # Filter actions: Go button and Adapt Filters
        draw.rounded_rectangle((1340, content_top + 70, 1430, content_top + 105), radius=4, fill="#0284C7")
        draw.text((1372, content_top + 80), "Go", fill="white", font=_font(13, bold=True))
        draw.text((1450, content_top + 80), "Adapt Filters", fill="#0284C7", font=_font(12))

        # Responsive Table Container
        table_top = content_top + 180
        draw.rounded_rectangle((40, table_top, 1560, 950), radius=8, fill="#FFFFFF", outline="#E2E8F0", width=1)
        draw.text((60, table_top + 16), "Eligible Purchase Orders (4)", fill="#0F172A", font=_font(18, bold=True))
        draw.text((1380, table_top + 18), "Search    Settings", fill="#0284C7", font=_font(13))

        # Table Header
        columns = ["PO Number", "Vendor / Supplier", "Delivery Date", "Plant", "Open Value", "Status"]
        col_x = [60, 240, 520, 780, 1020, 1260]
        draw.rectangle((41, table_top + 50, 1559, table_top + 88), fill="#F1F5F9")
        for idx, col in enumerate(columns):
            draw.text((col_x[idx], table_top + 60), col, fill="#334155", font=_font(13, bold=True))

        # Realistic PO data rows with semantic status badges
        rows_data = [
            ("4500019280", "Acme Logistics Ltd", "Today", "Plant 1010", "12,450 EUR", "Eligible - Released", "#107E3E", "#E8F5E9"),
            ("4500019284", "Global Freight Corp", "Tomorrow", "Plant 1010", "8,200 EUR", "Eligible - Released", "#107E3E", "#E8F5E9"),
            ("4500019291", "Fastline Transport", "+2 Days", "Plant 1020", "24,100 EUR", "Pass Requested", "#D97706", "#FFFBEB"),
            ("4500019305", "Direct Haulage Co", "+3 Days", "Plant 1010", "4,750 EUR", "Draft Saved", "#475569", "#F1F5F9"),
        ]
        for r_idx, (po, vendor, ddate, plant, val, st, fg, bg) in enumerate(rows_data):
            ry = table_top + 90 + r_idx * 58
            draw.line((40, ry + 56, 1560, ry + 56), fill="#F1F5F9", width=1)
            draw.text((col_x[0], ry + 16), po, fill="#0284C7", font=_font(13, bold=True))
            draw.text((col_x[1], ry + 16), vendor, fill="#1E293B", font=_font(13))
            draw.text((col_x[2], ry + 16), ddate, fill="#1E293B", font=_font(13))
            draw.text((col_x[3], ry + 16), plant, fill="#1E293B", font=_font(13))
            draw.text((col_x[4], ry + 16), val, fill="#1E293B", font=_font(13))
            # Status badge
            draw.rounded_rectangle((col_x[5], ry + 12, col_x[5] + 160, ry + 38), radius=4, fill=bg, outline=fg, width=1)
            draw.text((col_x[5] + 10, ry + 17), st, fill=fg, font=_font(11, bold=True))

    elif plan == "my_inbox":
        # =========================================================================
        # FLOORPLAN 2: MY INBOX (MASTER-DETAIL WORKFLOW APPROVAL)
        # =========================================================================
        # Master Pane (Task List, Left 420px)
        draw.rounded_rectangle((40, content_top, 450, 950), radius=8, fill="#FFFFFF", outline="#E2E8F0", width=1)
        # Search task
        draw.rounded_rectangle((55, content_top + 16, 435, content_top + 52), radius=4, fill="#F8FAFC", outline="#CBD5E1", width=1)
        draw.text((70, content_top + 26), "🔍  Search tasks...", fill="#94A3B8", font=_font(12))

        # Task 1 (Active task)
        draw.rectangle((41, content_top + 65, 449, content_top + 170), fill="#EFF6FF")
        draw.rectangle((41, content_top + 65, 46, content_top + 170), fill="#0284C7")  # Active bar
        draw.text((60, content_top + 78), sname[:26], fill="#0F172A", font=_font(14, bold=True))
        draw.text((60, content_top + 102), "REQ-2026-0042 • Acme Logistics", fill="#475569", font=_font(12))
        draw.rounded_rectangle((60, content_top + 130, 150, content_top + 150), radius=3, fill="#FEE2E2")
        draw.text((68, content_top + 134), "HIGH PRIORITY", fill="#DC2626", font=_font(10, bold=True))
        draw.text((170, content_top + 134), "Slot: 14:00 Today", fill="#64748B", font=_font(11))

        # Task 2
        draw.rectangle((41, content_top + 175, 449, content_top + 270), fill="#FFFFFF")
        draw.line((41, content_top + 270, 449, content_top + 270), fill="#E2E8F0", width=1)
        draw.text((60, content_top + 188), sname[:26], fill="#0F172A", font=_font(14, bold=True))
        draw.text((60, content_top + 212), "REQ-2026-0040 • Global Freight", fill="#475569", font=_font(12))
        draw.rounded_rectangle((60, content_top + 240, 140, content_top + 260), radius=3, fill="#FEF3C7")
        draw.text((68, content_top + 244), "MEDIUM", fill="#D97706", font=_font(10, bold=True))

        # Detail Pane (Right 1080px)
        detail_x = 470
        draw.rounded_rectangle((detail_x, content_top, 1560, 950), radius=8, fill="#FFFFFF", outline="#E2E8F0", width=1)

        # Detail Header
        draw.text((detail_x + 30, content_top + 20), f"Task Details: {sname}", fill="#0F172A", font=_font(20, bold=True))
        draw.text((detail_x + 30, content_top + 48), "Initiated by Supplier Acme Logistics Ltd • PO 4500019280 • Slot: Today 14:00-16:00", fill="#64748B", font=_font(13))
        draw.line((detail_x, content_top + 78, 1560, content_top + 78), fill="#E2E8F0", width=1)

        # Overview Form Grid (6 fields)
        grid_labels = [f.get("label") for f in fields if f.get("label")][:6] or ["Supplier Name", "PO Number", "Requested Entry Date", "Vehicle Reg Number", "Driver Full Name", "Delivery Note Ref"]
        grid_vals = ["Acme Logistics Ltd", "4500019280", "Today, 14:00 - 16:00", "MH-12-AB-8821", "John Doe (Verified)", "DN-90182-B"]
        for idx, (flabel, fval) in enumerate(zip(grid_labels, grid_vals)):
            col, row = idx % 3, idx // 3
            gx = detail_x + 30 + col * 350
            gy = content_top + 95 + row * 65
            draw.text((gx, gy), _short_text(flabel, 26), fill="#64748B", font=_font(12))
            draw.text((gx, gy + 20), fval, fill="#0F172A", font=_font(14, bold=True))

        # Decision Checks Section
        check_y = content_top + 240
        draw.line((detail_x, check_y, 1560, check_y), fill="#E2E8F0", width=1)
        draw.text((detail_x + 30, check_y + 16), "Workflow Authorization Checklist", fill="#0F172A", font=_font(16, bold=True))

        checks = [
            "☑  PO is in 'Released' status with no active payment or credit blocks in S/4HANA",
            "☑  Dock unloading capacity verified for Plant 1010 during requested slot window",
            "☑  Driver security credential matches approved supplier roster; safety induction active",
        ]
        for c_idx, check in enumerate(checks):
            draw.text((detail_x + 30, check_y + 50 + c_idx * 32), check, fill="#15803D", font=_font(13))

        # Decision Reason input box
        box_y = check_y + 160
        draw.text((detail_x + 30, box_y), "Decision Notes / Rejection Reason (Required if Returning/Rejecting):", fill="#475569", font=_font(13, bold=True))
        draw.rounded_rectangle((detail_x + 30, box_y + 24, 1530, box_y + 90), radius=4, fill="#F8FAFC", outline="#CBD5E1", width=1)
        draw.text((detail_x + 45, box_y + 40), "Enter operational verification comments or specify missing documents...", fill="#94A3B8", font=_font(12))

        # Sticky Decision Action Bar (Approve / Return / Reject)
        bar_y = 890
        draw.rectangle((detail_x, bar_y, 1560, 950), fill="#F8FAFC")
        draw.line((detail_x, bar_y, 1560, bar_y), fill="#E2E8F0", width=1)

        # APPROVE (Solid Green)
        draw.rounded_rectangle((detail_x + 30, bar_y + 10, detail_x + 180, bar_y + 48), radius=5, fill="#107E3E")
        draw.text((detail_x + 75, bar_y + 20), "Approve", fill="white", font=_font(14, bold=True))

        # RETURN TO SUPPLIER (Solid Amber)
        draw.rounded_rectangle((detail_x + 200, bar_y + 10, detail_x + 400, bar_y + 48), radius=5, fill="#D97706")
        draw.text((detail_x + 235, bar_y + 20), "Return to Supplier", fill="white", font=_font(14, bold=True))

        # REJECT (Solid Red)
        draw.rounded_rectangle((detail_x + 420, bar_y + 10, detail_x + 550, bar_y + 48), radius=5, fill="#DC2626")
        draw.text((detail_x + 455, bar_y + 20), "Reject", fill="white", font=_font(14, bold=True))

    elif plan == "scan":
        # =========================================================================
        # FLOORPLAN 3: GATE SECURITY SCANNER (HANDHELD TOUCH VERIFICATION)
        # =========================================================================
        card_x = 100
        draw.rounded_rectangle((card_x, content_top, 1500, 950), radius=10, fill="#FFFFFF", outline="#E2E8F0", width=1)

        # Station Title
        draw.text((card_x + 40, content_top + 20), "Gate Security Verification • Main Entrance Station 01", fill="#0F172A", font=_font(22, bold=True))
        draw.text((card_x + 40, content_top + 50), "Live QR token validation with minimum disclosure security policy", fill="#64748B", font=_font(14))

        # Left Column: QR Viewfinder Graphic & Token Input
        vf_x, vf_y = card_x + 40, content_top + 90
        draw.rounded_rectangle((vf_x, vf_y, vf_x + 380, vf_y + 280), radius=8, fill="#0F172A")
        # Corner brackets
        draw.line((vf_x + 20, vf_y + 40, vf_x + 20, vf_y + 20, vf_x + 40, vf_y + 20), fill="#38BDF8", width=4)
        draw.line((vf_x + 360, vf_y + 40, vf_x + 360, vf_y + 20, vf_x + 340, vf_y + 20), fill="#38BDF8", width=4)
        draw.line((vf_x + 20, vf_y + 240, vf_x + 20, vf_y + 260, vf_x + 40, vf_y + 260), fill="#38BDF8", width=4)
        draw.line((vf_x + 360, vf_y + 240, vf_x + 360, vf_y + 260, vf_x + 340, vf_y + 260), fill="#38BDF8", width=4)
        # QR Grid pattern
        for qx in range(vf_x + 100, vf_x + 280, 24):
            for qy in range(vf_y + 60, vf_y + 220, 24):
                if (qx + qy) % 48 != 0:
                    draw.rectangle((qx, qy, qx + 18, qy + 18), fill="#FFFFFF")
        # Laser scanning line
        draw.line((vf_x + 40, vf_y + 140, vf_x + 340, vf_y + 140), fill="#EF4444", width=3)
        draw.text((vf_x + 110, vf_y + 245), "CAMERA SCANNER ACTIVE", fill="#38BDF8", font=_font(11, bold=True))

        # Manual token entry below viewfinder
        draw.text((vf_x, vf_y + 300), "Scanned QR Token:", fill="#475569", font=_font(12, bold=True))
        draw.rounded_rectangle((vf_x, vf_y + 322, vf_x + 260, vf_y + 362), radius=4, fill="#F8FAFC", outline="#CBD5E1", width=1)
        draw.text((vf_x + 10, vf_y + 334), "GP-2026-0042-SEC-99", fill="#0F172A", font=_font(13, mono=True))
        draw.rounded_rectangle((vf_x + 275, vf_y + 322, vf_x + 380, vf_y + 362), radius=4, fill="#0284C7")
        draw.text((vf_x + 305, vf_y + 334), "Verify", fill="white", font=_font(13, bold=True))

        # Right Column: High-Contrast Status Banner & Verification Result
        res_x = vf_x + 430

        # HIGH-CONTRAST VALID STATUS BANNER
        draw.rounded_rectangle((res_x, vf_y, res_x + 880, vf_y + 90), radius=8, fill="#107E3E")
        draw.text((res_x + 30, vf_y + 18), "✓  GATE PASS VERIFIED - ENTRY AUTHORIZED", fill="white", font=_font(22, bold=True))
        draw.text((res_x + 30, vf_y + 54), "Pass Status: VALID  •  Entry Window: Today 08:00 - 18:00  •  Dock Bay: 04", fill="#DCFCE7", font=_font(14))

        # Minimum Disclosure Card
        disc_y = vf_y + 110
        draw.rounded_rectangle((res_x, disc_y, res_x + 880, disc_y + 260), radius=8, fill="#F8FAFC", outline="#E2E8F0", width=1)
        draw.text((res_x + 30, disc_y + 16), "Minimum Disclosure Identity Verification (BRD Security Policy)", fill="#0F172A", font=_font(15, bold=True))
        draw.line((res_x, disc_y + 44, res_x + 880, disc_y + 44), fill="#E2E8F0", width=1)

        info_items = [
            ("Gate Pass Number", "GP-2026-0042"),
            ("Authorized Site / Plant", "Plant 1010 (Main Logistics Gate)"),
            ("Supplier Name", "Acme Logistics Ltd"),
            ("Masked Vehicle Registration", "MH-12-AB-****  (Matches physical truck)"),
            ("Masked Driver Identity", "J*** D**  (Matches Gov ID)"),
            ("Linked PO Reference", "4500019280 (1 Line Item)"),
        ]
        for i_idx, (lbl, val) in enumerate(info_items):
            col, row = i_idx % 2, i_idx // 2
            ix = res_x + 30 + col * 440
            iy = disc_y + 60 + row * 60
            draw.text((ix, iy), lbl, fill="#64748B", font=_font(12))
            draw.text((ix, iy + 20), val, fill="#0F172A", font=_font(15, bold=True))

        # Giant Touch Admission Buttons
        btn_y = disc_y + 290
        # ADMIT VEHICLE (Green)
        draw.rounded_rectangle((res_x, btn_y, res_x + 420, btn_y + 75), radius=8, fill="#107E3E")
        draw.text((res_x + 95, btn_y + 24), "✓  ADMIT VEHICLE", fill="white", font=_font(22, bold=True))

        # DENY ENTRY (Red)
        draw.rounded_rectangle((res_x + 460, btn_y, res_x + 880, btn_y + 75), radius=8, fill="#DC2626")
        draw.text((res_x + 555, btn_y + 24), "✕  DENY ENTRY", fill="white", font=_font(22, bold=True))

    else:
        # =========================================================================
        # FLOORPLAN 4: OBJECT PAGE (PASS DOWNLOAD OR REQUEST ENTRY)
        # =========================================================================
        is_download = "download" in sname.lower() or "approved" in sname.lower() or "SCR-06" in sid

        if is_download:
            # Pass Download Layout
            draw.rounded_rectangle((60, content_top, 1540, 950), radius=8, fill="#FFFFFF", outline="#E2E8F0", width=1)
            # Pass Header
            draw.text((90, content_top + 24), "Approved Gate Pass Document: GP-2026-0042", fill="#0F172A", font=_font(22, bold=True))
            draw.rounded_rectangle((90, content_top + 60, 260, content_top + 88), radius=4, fill="#DCFCE7", outline="#107E3E", width=1)
            draw.text((105, content_top + 66), "APPROVED & ISSUED", fill="#107E3E", font=_font(12, bold=True))
            draw.text((280, content_top + 67), "Issued by S/4HANA Automated Release Engine • Valid for Entry", fill="#64748B", font=_font(13))

            # Left side: QR Code preview
            qr_x, qr_y = 90, content_top + 115
            draw.rounded_rectangle((qr_x, qr_y, qr_x + 280, qr_y + 280), radius=8, fill="#F8FAFC", outline="#CBD5E1", width=2)
            # QR Pattern
            for qx in range(qr_x + 40, qr_x + 240, 20):
                for qy in range(qr_y + 40, qr_y + 240, 20):
                    if (qx * 3 + qy * 7) % 25 < 14:
                        draw.rectangle((qx, qy, qx + 16, qy + 16), fill="#0F172A")
            draw.text((qr_x + 45, qr_y + 250), "Cryptographic QR Token Active", fill="#64748B", font=_font(11))

            # Right side: Audit Trail & Pass Details
            dt_x = qr_x + 320
            draw.text((dt_x, qr_y), "Gate Pass Summary & Authorization Audit Trail", fill="#0F172A", font=_font(16, bold=True))

            details = [
                ("Pass Reference Number", "GP-2026-0042"),
                ("Valid Entry Date Window", "Today, 08:00 - 18:00 IST"),
                ("Plant / Receiving Bay", "Plant 1010 • Bay 04"),
                ("Supplier Organization", "Acme Logistics Ltd"),
                ("Vehicle Registration", "MH-12-AB-8821"),
                ("Authorized Driver", "John Doe (Verified License)"),
                ("Level 1 Approval (Operations)", "APPROVED by Operations Lead • 10:15 IST"),
                ("Level 2 Approval (Security)", "APPROVED by Plant Security Officer • 11:30 IST"),
            ]
            for d_idx, (dlbl, dval) in enumerate(details):
                col, row = d_idx % 2, d_idx // 2
                dx = dt_x + col * 480
                dy = qr_y + 40 + row * 60
                draw.text((dx, dy), dlbl, fill="#64748B", font=_font(12))
                color = "#107E3E" if "APPROVED" in dval else "#0F172A"
                draw.text((dx, dy + 20), dval, fill=color, font=_font(14, bold=True))

            # Primary Download Action Button
            dl_btn_y = content_top + 430
            draw.rounded_rectangle((dt_x, dl_btn_y, dt_x + 360, dl_btn_y + 60), radius=6, fill="#0284C7")
            draw.text((dt_x + 40, dl_btn_y + 18), "⬇  Download Gate Pass (PDF)", fill="white", font=_font(16, bold=True))
        else:
            # Standard Request Entry / Details Object Page
            draw.rounded_rectangle((60, content_top, 1540, 950), radius=8, fill="#FFFFFF", outline="#E2E8F0", width=1)
            # Section 1: Read-only PO Context
            draw.text((90, content_top + 20), "Selected Purchase Order Context (Read-Only)", fill="#0F172A", font=_font(16, bold=True))
            draw.line((90, content_top + 48, 1510, content_top + 48), fill="#E2E8F0", width=1)

            po_fields = [("PO Number", "4500019280"), ("Supplier", "Acme Logistics Ltd"), ("Plant", "Plant 1010"), ("Open Value", "12,450 EUR")]
            for p_idx, (plbl, pval) in enumerate(po_fields):
                px = 90 + p_idx * 350
                draw.text((px, content_top + 60), plbl, fill="#64748B", font=_font(12))
                draw.text((px, content_top + 80), pval, fill="#0F172A", font=_font(14, bold=True))

            # Section 2: Request Entry Form
            draw.text((90, content_top + 130), "Gate Pass Request Entry", fill="#0F172A", font=_font(16, bold=True))
            draw.line((90, content_top + 158, 1510, content_top + 158), fill="#E2E8F0", width=1)

            entry_fields = [f.get("label") for f in fields if f.get("label")][:6] or ["Requested Entry Date", "Arrival Time Slot", "Vehicle Reg Number", "Driver Full Name", "Driver Phone", "Delivery Note Number"]
            for e_idx, elbl in enumerate(entry_fields):
                col, row = e_idx % 2, e_idx // 2
                ex = 90 + col * 700
                ey = content_top + 175 + row * 75
                draw.text((ex, ey), _short_text(elbl, 35) + " *", fill="#475569", font=_font(13, bold=True))
                draw.rounded_rectangle((ex, ey + 24, ex + 640, ey + 62), radius=4, fill="#F8FAFC", outline="#CBD5E1", width=1)
                draw.text((ex + 12, ey + 36), f"Enter {_safe(elbl).lower()}...", fill="#94A3B8", font=_font(12))

            # Bottom Sticky Actions
            f_bar_y = 890
            draw.rectangle((60, f_bar_y, 1540, 950), fill="#F8FAFC")
            draw.line((60, f_bar_y, 1540, f_bar_y), fill="#E2E8F0", width=1)
            # Submit Request
            draw.rounded_rectangle((1360, f_bar_y + 10, 1510, f_bar_y + 48), radius=5, fill="#0284C7")
            draw.text((1388, f_bar_y + 20), "Submit Request", fill="white", font=_font(13, bold=True))
            # Save Draft
            draw.rounded_rectangle((1220, f_bar_y + 10, 1340, f_bar_y + 48), radius=5, fill="#FFFFFF", outline="#CBD5E1", width=1)
            draw.text((1242, f_bar_y + 20), "Save Draft", fill="#334155", font=_font(13))

    image.save(output, "PNG")


def _shade(cell, fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    node = properties.find(qn("w:shd"))
    if node is None:
        node = OxmlElement("w:shd"); properties.append(node)
    node.set(qn("w:fill"), fill)


def _cell_margins(cell) -> None:
    properties = cell._tc.get_or_add_tcPr()
    margins = properties.first_child_found_in("w:tcMar")
    if margins is None:
        margins = OxmlElement("w:tcMar"); properties.append(margins)
    for name, value in (("top", 90), ("start", 120), ("bottom", 90), ("end", 120)):
        node = margins.find(qn(f"w:{name}"))
        if node is None:
            node = OxmlElement(f"w:{name}"); margins.append(node)
        node.set(qn("w:w"), str(value)); node.set(qn("w:type"), "dxa")


def _style_word(doc: WordDocument, project_name: str, logos: dict[str, Path], document_label: str = "SAP Functional Specification") -> None:
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin, section.bottom_margin, section.left_margin, section.right_margin = Inches(1.35), Inches(.78), Inches(.82), Inches(.82)
    section.header_distance, section.footer_distance = Inches(.18), Inches(.28)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size, normal.font.color.rgb = "Calibri", Pt(10.5), RGBColor.from_string(DARK)
    normal.paragraph_format.space_after, normal.paragraph_format.line_spacing = Pt(6), 1.1
    for name, size, color, before, after in (("Heading 1", 16, GREEN, 16, 8), ("Heading 2", 13, GREEN, 12, 6), ("Heading 3", 11.5, DARK, 9, 4)):
        style = doc.styles[name]; style.font.name = "Calibri"; style.font.size = Pt(size); style.font.bold = True; style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.space_before, style.paragraph_format.space_after, style.paragraph_format.keep_with_next = Pt(before), Pt(after), True
    try:
        record_style = doc.styles.add_style("Record Heading", WD_STYLE_TYPE.PARAGRAPH)
    except ValueError:
        record_style = doc.styles["Record Heading"]
    record_style.font.name, record_style.font.size, record_style.font.bold = "Calibri", Pt(10.5), True
    record_style.font.color.rgb = RGBColor.from_string(GREEN)
    record_style.paragraph_format.space_before, record_style.paragraph_format.space_after = Pt(8), Pt(4)
    record_style.paragraph_format.keep_with_next = True
    header = section.header; header.paragraphs[0].text = ""
    logo_table = header.add_table(rows=1, cols=2, width=Inches(6.86)); logo_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    left = logo_table.cell(0, 0).paragraphs[0]; left.alignment = WD_ALIGN_PARAGRAPH.LEFT; left.add_run().add_picture(str(logos["left"]), width=Inches(1.65))
    right = logo_table.cell(0, 1).paragraphs[0]; right.alignment = WD_ALIGN_PARAGRAPH.RIGHT; right.add_run().add_picture(str(logos["right"]), width=Inches(1.65))
    header = header.add_paragraph(f"Classification: INTERNAL  |  {document_label}"); header.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in header.runs:
        run.font.name, run.font.size, run.font.color.rgb = "Calibri", Pt(8), RGBColor.from_string(GRAY)
    footer = section.footer; footer.paragraphs[0].text = ""
    footer_table = footer.add_table(rows=1, cols=2, width=Inches(6.86)); footer_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    left = footer_table.cell(0, 0).paragraphs[0]; left.alignment = WD_ALIGN_PARAGRAPH.LEFT; run = left.add_run(project_name)
    run.font.name, run.font.size, run.font.color.rgb = "Calibri", Pt(8), RGBColor.from_string(GRAY)
    right = footer_table.cell(0, 1).paragraphs[0]; right.alignment = WD_ALIGN_PARAGRAPH.RIGHT; run = right.add_run("Page ")
    run.font.name, run.font.size, run.font.color.rgb = "Calibri", Pt(8), RGBColor.from_string(GRAY)
    field = OxmlElement("w:fldSimple"); field.set(qn("w:instr"), "PAGE"); right._p.append(field)


def _word_table(doc: WordDocument, headers: list[str], rows: list[list[Any]], widths: list[float], title: str | None = None) -> None:
    rows = rows or [["TBD"] + [""] * (len(headers) - 1)]
    number = getattr(doc, "_fsd_table_number", 0) + 1
    doc._fsd_table_number = number
    table = doc.add_table(rows=1, cols=len(headers)); table.style, table.autofit = "Table Grid", False
    repeat = OxmlElement("w:tblHeader"); repeat.set(qn("w:val"), "true"); table.rows[0]._tr.get_or_add_trPr().append(repeat)
    for index, label in enumerate(headers):
        cell = table.rows[0].cells[index]; cell.text = label; _shade(cell, LIGHT); _cell_margins(cell)
        for run in cell.paragraphs[0].runs:
            run.bold = True; run.font.size = Pt(8.5); run.font.color.rgb = RGBColor.from_string(DARK)
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].text = _safe(value); cells[index].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER; _cell_margins(cells[index])
            for paragraph in cells[index].paragraphs:
                paragraph.paragraph_format.space_after = Pt(2)
                for run in paragraph.runs:
                    run.font.name, run.font.size = "Calibri", Pt(8.5)
    for row in table.rows:
        for index, width in enumerate(widths):
            row.cells[index].width = Inches(width)
    caption = doc.add_paragraph(_table_caption_text(number, headers, title))
    caption.alignment = WD_ALIGN_PARAGRAPH.LEFT
    caption.paragraph_format.space_before = Pt(2)
    caption.paragraph_format.space_after = Pt(8)
    for run in caption.runs:
        run.italic = True; run.font.size = Pt(8); run.font.color.rgb = RGBColor.from_string(GRAY)


def _word_list(doc: WordDocument, values: list[Any], numbered: bool = False) -> None:
    for value in values or ["None"]:
        doc.add_paragraph(_safe(value), style="List Number" if numbered else "List Bullet")


def _word_picture(doc: WordDocument, path: Path, max_width: float = 6.65, max_height: float = 7.0) -> None:
    with Image.open(path) as source:
        width, height = source.size
    scale = min(max_width / width, max_height / height)
    doc.add_picture(str(path), width=Inches(width * scale), height=Inches(height * scale)); doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER


def _word_caption(doc: WordDocument, text: str) -> None:
    paragraph = doc.add_paragraph(text); paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in paragraph.runs:
        run.italic = True; run.font.size = Pt(8.5); run.font.color.rgb = RGBColor.from_string(GRAY)


def _word_toc(doc: WordDocument) -> None:
    """Insert a native heading-based TOC with dotted leaders and page numbers."""
    settings = doc.settings._element
    update_fields = settings.find(qn("w:updateFields"))
    if update_fields is None:
        update_fields = OxmlElement("w:updateFields")
        settings.append(update_fields)
    update_fields.set(qn("w:val"), "true")
    paragraph = doc.add_paragraph()
    begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin"); begin.set(qn("w:dirty"), "true")
    instruction = OxmlElement("w:instrText"); instruction.set(qn("xml:space"), "preserve"); instruction.text = ' TOC \\o "1-3" \\h \\z \\u '
    separate = OxmlElement("w:fldChar"); separate.set(qn("w:fldCharType"), "separate")
    result = OxmlElement("w:t"); result.text = "Table of Contents updates automatically when the document opens."
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
    paragraph.add_run()._r.extend([begin, instruction, separate, result, end])


def _word_records(doc: WordDocument, records: list[dict], id_field: str, title_field: str, exclude: set[str] | None = None) -> None:
    exclude = exclude or set()
    if not records:
        doc.add_paragraph("TBD")
    for index, record in enumerate(records, 1):
        identifier = _safe(record.get(id_field, index)); title = _safe(record.get(title_field, ""))
        doc.add_paragraph(f"{identifier}{' - ' + title if title != 'TBD' else ''}", style="Record Heading")
        rows = [[key.replace("_", " ").title(), value] for key, value in record.items() if key not in exclude | {id_field, title_field}]
        _word_table(doc, ["Field", "Detail"], rows, [1.65, 4.95], title=f"{identifier} details")


def _word_cover(doc: WordDocument, data: dict) -> None:
    info = data.get("document_information", {})
    p = doc.add_paragraph("CLASSIFICATION: " + _safe(info.get("classification", "INTERNAL")).upper()); p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for run in p.runs:
        run.font.size, run.font.bold, run.font.color.rgb = Pt(9), True, RGBColor.from_string(GREEN)
    doc.add_paragraph().paragraph_format.space_after = Pt(70)
    for text, size, color in (("SAP FUNCTIONAL SPECIFICATION DOCUMENT", 22, DARK), (_safe(data.get("title")), 16, GREEN)):
        p = doc.add_paragraph(text); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in p.runs:
            run.font.size, run.font.bold, run.font.color.rgb = Pt(size), size > 11, RGBColor.from_string(color)
    doc.add_paragraph().paragraph_format.space_after = Pt(55)
    _word_table(doc, ["Document Attribute", "Value"], [["Process Identifier", info.get("process_identifier")], ["Application", info.get("application")],
        ["Functional Area", info.get("functional_area")], ["Version", data.get("version")], ["Status", data.get("status")],
        ["Prepared By", info.get("prepared_by")]], [1.8, 4.8])
    doc.add_page_break(); toc_title = doc.add_paragraph("Table of Contents")
    for run in toc_title.runs:
        run.font.name, run.font.size, run.font.bold, run.font.color.rgb = "Calibri", Pt(16), True, RGBColor.from_string(GREEN)
    toc_title.paragraph_format.space_after = Pt(10)
    _word_toc(doc); doc.add_page_break()


@timed("Compose DOCX content")
def _add_word_contents(doc: WordDocument, data: dict, images: dict[str, Any]) -> None:
    _word_cover(doc, data); info = data.get("document_information", {})
    doc.add_paragraph("Document Control", style="Record Heading")
    _word_table(doc, ["Attribute", "Value"], [["Short Description", f"Functional specification for the {_safe(data.get('title'))} process"], ["Application", info.get("application")], ["Functional Designer", info.get("prepared_by")],
        ["Classification", info.get("classification")], ["Process Identifier", info.get("process_identifier")]], [1.65, 4.95])
    doc.add_paragraph("Document History", style="Record Heading"); _word_table(doc, ["Version", "Date", "Author", "Description"],
        [[x.get("version"), x.get("date"), x.get("author"), x.get("description")] for x in data.get("revision_history", [])], [.75, 1.0, 1.45, 3.4])
    for heading, statement in (("IT Sign Off", "Reviewed for process security, logic, validations, configuration, permissions, and technical feasibility."),
                               ("Business Sign Off", "Reviewed for business requirement fulfillment, controls, authorizations, scenarios, and expected outcomes.")):
        doc.add_paragraph(heading, style="Record Heading"); doc.add_paragraph(statement)
        _word_table(doc, ["Role", "Name", "Status / Signature"], [[x.get("role"), x.get("name"), x.get("status")] for x in data.get("sign_offs", [])], [2.1, 2.2, 2.3])
    doc.add_heading("1. Relevant Documents", 1); _word_table(doc, ["Document Name", "Reference / Revision"], [[x, "TBD"] for x in data.get("relevant_documents", [])], [4.7, 1.9])
    scope = data.get("scope", {}); doc.add_heading("2. Process Scope", 1)
    doc.add_heading("2.1 Business Context", 2); doc.add_paragraph(_safe(scope.get("business_context")))
    doc.add_heading("2.1.1 As-Is Process", 3); _word_list(doc, scope.get("as_is_process", []))
    doc.add_heading("2.1.2 Current Constraints", 3); _word_list(doc, scope.get("current_constraints", []))
    for number, title, key in (("2.2", "Objectives", "objectives"), ("2.3", "In Scope", "in_scope"), ("2.4", "Out of Scope", "out_of_scope"), ("2.5", "Glossary", "glossary")):
        doc.add_heading(f"{number} {title}", 2); _word_list(doc, scope.get(key, []))
    doc.add_heading("3. Process Information and Future-State Design", 1); doc.add_heading("3.1 Process Description", 2)
    doc.add_paragraph("As-Is Context", style="Record Heading"); doc.add_paragraph(_safe(data.get("as_is_narrative")))
    doc.add_paragraph("To-Be Response", style="Record Heading"); doc.add_paragraph(_safe(data.get("future_state_narrative")))
    _word_table(doc, ["Current Constraint", "To-Be Response", "Expected Improvement", "Requirement IDs"], [[x.get("constraint"), x.get("to_be_response"), x.get("expected_improvement"), x.get("requirement_ids")] for x in data.get("improvement_mapping", [])], [1.6, 2.05, 2.0, .95])
    doc.add_heading("3.2 Actors and Systems", 2); _word_table(doc, ["Actor / System", "Type", "Responsibility", "Requirement IDs"],
        [[x.get("name"), x.get("actor_type"), x.get("responsibility"), x.get("requirement_ids")] for x in data.get("actors_and_systems", [])], [1.35, .9, 2.8, 1.55])
    doc.add_heading("3.3 Process Flow", 2)
    if images.get("as_is_process"):
        doc.add_heading("3.3.1 As-Is Process Flow", 3); _word_picture(doc, images["as_is_process"]); _word_caption(doc, "Figure 1: As-Is process flow and current constraints")
    if images.get("process"):
        doc.add_heading("3.3.2 To-Be Process Flow", 3); _word_picture(doc, images["process"]); _word_caption(doc, "Figure 2: To-Be process flow")
    if images.get("legend"):
        doc.add_heading("3.3.3 Process Diagram Legend", 3); _word_picture(doc, images["legend"], max_height=4.2); _word_caption(doc, "Figure 3: Process diagram legend")
    doc.add_heading("3.4 Activity List", 2); _word_table(doc, ["Step", "Actor", "Activity and System Behaviour", "Outcome", "Req IDs"],
        [[x.get("step_id"), x.get("actor"), f"{_short_text(x.get('activity'), 160)}\n{_short_text(x.get('system_behavior'), 220)}", _short_text(x.get("outcome"), 150), _short_ids(x.get("requirement_ids"))] for x in data.get("process_steps", [])], [.55, 1.05, 2.75, 1.5, .75])
    doc.add_heading("3.5 Process Triggers, Alternate and Exception Flows", 2)
    _word_table(doc, ["Flow Type", "Trigger", "Flow / Handling", "Expected Outcome", "Requirement IDs"], [[x.get("flow_type"), x.get("trigger"), x.get("flow"), x.get("expected_outcome"), x.get("requirement_ids")] for x in data.get("process_flow_variants", [])], [1.0, 1.35, 2.05, 1.45, .75])
    doc.add_heading("4. Functional Specification", 1)
    doc.add_heading("4.1 Requirement Catalogue", 2)
    _word_table(doc, ["ID", "Requirement and Functional Behaviour", "Priority", "BRD Source"],
        [[x.get("requirement_id"), f"{_short_text(x.get('title'), 90)}\n{_short_text(x.get('functional_behavior'), 230)}", priority_label(x.get("priority")), _short_text(x.get('source', {}).get('source_locator'), 80)] for x in data.get("requirements", [])], [.65, 3.9, .85, 1.2])
    doc.add_heading("4.2 Processing Logic", 2); _word_list(doc, data.get("processing_logic", []), True)
    doc.add_heading("4.3 Business Rules", 2); _word_table(doc, ["Rule", "Condition / Description", "Expected Result", "Req IDs"],
        [[x.get("rule_id"), f"{_short_text(x.get('condition'), 120)}\n{_short_text(x.get('description'), 210)}", _short_text(x.get("result"), 180), _short_ids(x.get("requirement_ids"))] for x in data.get("business_rules", [])], [.65, 3.0, 2.0, .95])

    doc.add_heading("4.4 Screen Design and Navigation", 2)
    if images.get("navigation"):
        _word_picture(doc, images["navigation"]); _word_caption(doc, "Figure 4: Screen navigation flow")
    for index, screen in enumerate(data.get("screens", []), 1):
        sid = _safe(screen.get("screen_id")); doc.add_heading(f"4.4.{index} {sid} - {_safe(screen.get('name'))}", 3)
        _word_table(doc, ["Field", "Detail"], [[key.replace("_", " ").title(), value] for key, value in screen.items() if key not in {"screen_id", "name", "ascii_wireframe", "fields", "actions", "messages"}], [1.65, 4.95])
        if images.get("screens", {}).get(sid):
            _word_picture(doc, images["screens"][sid], max_height=5.4); _word_caption(doc, f"Figure {index + 4}: {sid} SAP Fiori screen design sample")
        doc.add_paragraph("Fields", style="Record Heading"); _word_table(doc, ["Field", "Label / Type", "Required / Validation", "Req IDs"], [[x.get("field_id"), f"{x.get('label')} / {x.get('data_type')}", f"Required: {_safe(x.get('required'))}; {_short_text(x.get('validation'), 130)}", _short_ids(x.get("requirement_ids"))] for x in screen.get("fields", [])], [.75, 2.1, 2.8, .95])
        doc.add_paragraph("Actions", style="Record Heading"); _word_table(doc, ["Action", "Enabled When", "Success / Failure", "Req IDs"], [[x.get("action"), _short_text(x.get("enabled_when"), 130), f"{_short_text(x.get('success_result'), 95)} / {_short_text(x.get('failure_result'), 95)}", _short_ids(x.get("requirement_ids"))] for x in screen.get("actions", [])], [1.1, 2.15, 2.4, .95])
        doc.add_paragraph("Messages", style="Record Heading"); _word_table(doc, ["ID", "Type", "Message", "Req IDs"], [[x.get("message_id"), x.get("message_type"), _short_text(x.get("message_text"), 210), _short_ids(x.get("requirement_ids"))] for x in screen.get("messages", [])], [.75, .8, 4.1, .95])

    doc.add_heading("4.5 Data Mapping", 2); _word_records(doc, data.get("data_mappings", []), "mapping_id", "business_field")
    doc.add_heading("4.6 Status Definitions", 2); _word_records(doc, data.get("status_definitions", []), "status_id", "domain")
    doc.add_heading("4.7 Business Message Catalogue", 2); _word_records(doc, data.get("message_catalog", []), "message_id", "scenario")

    doc.add_heading("5. Configuration", 1); _word_records(doc, data.get("configuration_items", []), "config_id", "item")

    doc.add_heading("6. Technical Elements of Enhancement", 1); _word_records(doc, data.get("technical_objects", []), "object_id", "name")
    for sub, list_key in (("6.1 Cross-Process Impacts", "cross_process_impacts"), ("6.2 Batch Job Details", "batch_jobs"), ("6.3 Dependencies", "dependencies"), ("6.4 Assumptions", "assumptions")):
        doc.add_heading(sub, 2); _word_list(doc, data.get(list_key, []))

    doc.add_heading("7. Roles & Responsibilities", 1)
    _word_table(doc, ["Actor / System", "Type", "Responsibility", "Req IDs"], [[x.get("name"), x.get("actor_type"), _short_text(x.get("responsibility"), 240), _short_ids(x.get("requirement_ids"))] for x in data.get("actors_and_systems", [])], [1.45, 1.0, 3.25, .9])

    doc.add_heading("8. Roles, Transaction Codes & Authorization Objects", 1)
    _word_table(doc, ["Role", "Business Role", "Activities / Scope", "App / Auth Object", "Req IDs"], [[x.get("role_id"), x.get("business_role"), f"{_short_text(x.get('activities'), 150)}\nScope: {_short_text(x.get('data_scope'), 110)}", f"{_short_text(x.get('transaction_or_app'), 95)}\n{_short_text(x.get('authorization_object'), 95)}", _short_ids(x.get("requirement_ids"))] for x in data.get("roles_and_authorizations", [])], [.6, 1.2, 2.3, 1.65, .85])

    doc.add_heading("9. Test Conditions", 1); _word_table(doc, ["Test", "Req IDs", "Scenario / Steps", "Expected Result"], [[x.get("test_id"), _short_ids(x.get("requirement_ids")), f"{_short_text(x.get('scenario'), 100)}\n{_short_text(x.get('steps'), 210)}", _short_text(x.get("expected_result"), 210)] for x in data.get("test_conditions", [])], [.65, .8, 2.8, 2.35])
    doc.add_heading("10. Related RICEFW Items", 1); _word_table(doc, ["RICEFW Item"], [[x] for x in data.get("ricefw_inventory", [])], [6.6])
    doc.add_heading("11. Integration Points", 1); _word_records(doc, data.get("interfaces", []), "interface_id", "purpose")
    doc.add_heading("12. Open Points / Outstanding Issues & Omissions", 1); _word_records(doc, data.get("outstanding_issues", []), "issue_id", "description")
    doc.add_heading("13. Group / Company Localization Requirements", 1); _word_list(doc, data.get("localization_requirements", []))
    doc.add_heading("14. Risk / Vulnerability Assessment", 1); _word_records(doc, data.get("risks", []), "risk_id", "risk")
    doc.add_heading("15. Optional Non-Functional Requirements", 1); _word_records(doc, data.get("non_functional_requirements", []), "nfr_id", "category")
    doc.add_heading("16. Appendices", 1)
    doc.add_heading("16.1 Reports and Notifications", 2); _word_list(doc, data.get("reports_and_notifications", []))
    doc.add_heading("16.2 Controls", 2); _word_list(doc, data.get("controls", []))
    doc.add_heading("16.3 Open Questions", 2); _word_list(doc, data.get("open_questions", []))
    doc.add_heading("16.4 Review Checklist", 2); _word_records(doc, data.get("review_checklist", []), "check", "result")



def _pdf_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "CoverKicker": ParagraphStyle("CoverKicker", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=9, textColor=colors.HexColor("#0d6b50"), alignment=TA_CENTER, spaceAfter=12),
        "CoverTitle": ParagraphStyle("CoverTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=22, leading=27, textColor=colors.HexColor("#17211e"), alignment=TA_CENTER, spaceAfter=12),
        "CoverSub": ParagraphStyle("CoverSub", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=colors.HexColor("#0d6b50"), alignment=TA_CENTER, spaceAfter=10),
        "FSDH1": ParagraphStyle("FSDH1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=colors.HexColor("#0d6b50"), spaceBefore=12, spaceAfter=8, keepWithNext=True),
        "FSDH2": ParagraphStyle("FSDH2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, leading=14, textColor=colors.HexColor("#17211e"), spaceBefore=9, spaceAfter=5, keepWithNext=True),
        "FSDH3": ParagraphStyle("FSDH3", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.HexColor("#0d6b50"), spaceBefore=7, spaceAfter=4, keepWithNext=True),
        "Body": ParagraphStyle("Body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.3, leading=12.4, textColor=colors.HexColor("#17211e"), spaceAfter=6),
        "Bullet": ParagraphStyle("Bullet", parent=base["BodyText"], fontName="Helvetica", fontSize=9.1, leading=12, leftIndent=12, firstLineIndent=-8, spaceAfter=4),
        "Caption": ParagraphStyle("Caption", parent=base["BodyText"], fontName="Helvetica-Oblique", fontSize=8, leading=10, alignment=TA_CENTER, textColor=colors.HexColor("#5b6762"), spaceAfter=8),
        "TableHead": ParagraphStyle("TableHead", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=8, leading=10),
        "TableBody": ParagraphStyle("TableBody", parent=base["BodyText"], fontName="Helvetica", fontSize=7.7, leading=9.6),
        "TOC0": ParagraphStyle("TOC0", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=8.5, leading=10.5, spaceBefore=1, spaceAfter=1, textColor=colors.HexColor("#17211e")),
        "TOC1": ParagraphStyle("TOC1", parent=base["BodyText"], fontName="Helvetica", fontSize=7.8, leading=9.3, spaceBefore=0, spaceAfter=0, leftIndent=14, textColor=colors.HexColor("#4f5d57")),
    }


def _pdf_text(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(html.escape(_safe(value)).replace("\n", "<br/>"), style)


def _pdf_table_cell(value: Any, column_width: float) -> str:
    """Keep a generated cell shorter than one PDF frame.

    ReportLab can split a table between rows, but it cannot split one row whose
    tallest cell is higher than the page.  Model-generated details remain
    complete in the DOCX; the PDF receives a readable preview when a cell is
    exceptionally long.
    """
    text = re.sub(r"\s+", " ", _safe(value)).strip()
    limit = max(120, int(column_width * 180))
    if len(text) <= limit:
        return text
    preview = text[: max(1, limit - 43)].rsplit(" ", 1)[0].rstrip(" ;,.")
    return f"{preview}... [Full detail is in the DOCX]"


def _pdf_table(headers: list[str], rows: list[list[Any]], widths: list[float], styles: dict[str, ParagraphStyle], title: str | None = None) -> Table:
    rows = rows or [["TBD"] + [""] * (len(headers) - 1)]
    normalized_rows = [
        list(row[:len(headers)]) + [""] * max(0, len(headers) - len(row))
        for row in rows
    ]
    number = _pdf_table_number.get() + 1
    _pdf_table_number.set(number)
    caption = _pdf_text(_table_caption_text(number, headers, title), styles["Caption"])
    content = [[_pdf_text(item, styles["TableHead"]) for item in headers]] + [
        [_pdf_text(_pdf_table_cell(item, widths[index]), styles["TableBody"]) for index, item in enumerate(row)]
        for row in normalized_rows
    ] + [[caption] + [""] * (len(headers) - 1)]
    last = len(content) - 1
    table = Table(content, colWidths=[width * inch for width in widths], repeatRows=1, hAlign="LEFT", splitByRow=1)
    table.setStyle(TableStyle([
        ("SPAN", (0, last), (-1, last)),
        ("GRID", (0, 0), (-1, last - 1), .4, colors.HexColor("#b7c8bf")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dceee5")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, last), (-1, last), 4),
    ]))
    return table


def _pdf_bullets(values: list[Any], styles: dict[str, ParagraphStyle]) -> list[Any]:
    return [_pdf_text(f"- {_safe(value)}", styles["Bullet"]) for value in (values or ["None"])]


def _pdf_picture(path: Path, max_width: float = 6.5 * inch, max_height: float = 6.8 * inch) -> PdfImage:
    with Image.open(path) as source:
        width, height = source.size
    scale = min(max_width / width, max_height / height)
    return PdfImage(str(path), width=width * scale, height=height * scale)


def _pdf_records(story: list[Any], records: list[dict], id_field: str, title_field: str, styles: dict[str, ParagraphStyle], exclude: set[str] | None = None) -> None:
    exclude = exclude or set()
    if not records:
        story.append(_pdf_text("TBD", styles["Body"]))
        return
    if id_field == "requirement_id" and title_field == "title":
        story.append(_pdf_table(["ID", "Requirement and Functional Behaviour", "Priority", "BRD Source"],
            [[x.get("requirement_id"), f"{_short_text(x.get('title'), 90)}\n{_short_text(x.get('functional_behavior'), 230)}", priority_label(x.get("priority")), _short_text(x.get('source', {}).get('source_locator'), 80)] for x in records], [.62, 3.72, .82, 1.34], styles)); return
    if id_field == "test_id":
        story.append(_pdf_table(["Test", "Req IDs", "Scenario / Steps", "Expected Result"], [[x.get("test_id"), _short_ids(x.get("requirement_ids")), f"{_short_text(x.get('scenario'), 100)}\n{_short_text(x.get('steps'), 210)}", _short_text(x.get("expected_result"), 210)] for x in records], [.62, .78, 2.75, 2.35], styles)); return
    if id_field == "requirement_id" and title_field == "coverage_status":
        story.append(_pdf_table(["Req", "BRD Source", "Process", "Screen", "Rule", "Test", "Coverage"], [[x.get("requirement_id"), _short_text(x.get("brd_source"), 55), _short_ids(x.get("process_step_ids"), 2), _short_ids(x.get("screen_ids"), 2), _short_ids(x.get("rule_ids"), 2), _short_ids(x.get("test_ids"), 2), x.get("coverage_status")] for x in records], [.52, 1.18, .88, .75, .75, .75, .7], styles)); return
    if id_field == "step_id":
        story.append(_pdf_table(["Step", "Actor", "Activity / Behaviour", "Outcome", "Req IDs"], [[x.get("step_id"), x.get("actor"), f"{_short_text(x.get('activity'), 150)}\n{_short_text(x.get('system_behavior'), 210)}", _short_text(x.get("outcome"), 150), _short_ids(x.get("requirement_ids"))] for x in records], [.52, 1.0, 2.75, 1.5, .7], styles)); return
    if id_field == "rule_id":
        story.append(_pdf_table(["Rule", "Condition / Description", "Result", "Req IDs"], [[x.get("rule_id"), f"{_short_text(x.get('condition'), 120)}\n{_short_text(x.get('description'), 210)}", _short_text(x.get("result"), 170), _short_ids(x.get("requirement_ids"))] for x in records], [.62, 3.0, 1.95, .9], styles)); return
    if id_field == "field_id":
        story.append(_pdf_table(["Field", "Label / Type", "Required / Validation", "Req IDs"], [[x.get("field_id"), f"{x.get('label')} / {x.get('data_type')}", f"Required: {_safe(x.get('required'))}; {_short_text(x.get('validation'), 130)}", _short_ids(x.get("requirement_ids"))] for x in records], [.72, 2.0, 2.75, .95], styles)); return
    if id_field == "action":
        story.append(_pdf_table(["Action", "Enabled When", "Outcome", "Req IDs"], [[x.get("action"), _short_text(x.get("enabled_when"), 130), _short_text(x.get("outcome"), 160), _short_ids(x.get("requirement_ids"))] for x in records], [1.0, 2.15, 2.4, .85], styles)); return
    if id_field == "message_id":
        story.append(_pdf_table(["ID", "Type", "Message", "Req IDs"], [[x.get("message_id"), x.get("message_type"), _short_text(x.get("message_text"), 210), _short_ids(x.get("requirement_ids"))] for x in records], [.7, .8, 4.05, .85], styles)); return
    for index, record in enumerate(records, 1):
        identifier, title = _safe(record.get(id_field, index)), _safe(record.get(title_field, ""))
        story.append(_pdf_text(f"{identifier}{' - ' + title if title != 'TBD' else ''}", styles["FSDH3"]))
        rows = [[key.replace("_", " ").title(), value] for key, value in record.items() if key not in exclude | {id_field, title_field}]
        story.append(_pdf_table(["Field", "Detail"], rows, [1.55, 4.95], styles))
        if index < len(records):
            story.append(Spacer(1, 6))


class _FSDTemplate(SimpleDocTemplate):
    def __init__(self, filename: str, **kwargs):
        self.project_name = kwargs.pop("project_name", "Project")
        self.document_label = kwargs.pop("document_label", "SAP Functional Specification")
        self.logo_left = kwargs.pop("logo_left", None); self.logo_right = kwargs.pop("logo_right", None); self._heading_count = 0
        super().__init__(filename, **kwargs)

    def beforeDocument(self):
        self._heading_count = 0
        super().beforeDocument()

    def onFirstPage(self, canvas, doc):
        self._decorate(canvas, doc)

    def onLaterPages(self, canvas, doc):
        self._decorate(canvas, doc)

    def _decorate(self, canvas, doc):
        canvas.saveState(); page = canvas.getPageNumber()
        if self.logo_left: canvas.drawImage(str(self.logo_left), self.leftMargin, letter[1] - .57 * inch, width=1.55 * inch, height=.42 * inch, preserveAspectRatio=True, mask="auto")
        if self.logo_right: canvas.drawImage(str(self.logo_right), letter[0] - self.rightMargin - 1.55 * inch, letter[1] - .57 * inch, width=1.55 * inch, height=.42 * inch, preserveAspectRatio=True, mask="auto")
        canvas.setFont("Helvetica", 7.5); canvas.setFillColor(colors.HexColor("#5b6762"))
        canvas.drawString(self.leftMargin, letter[1] - .75 * inch, "Classification: INTERNAL")
        canvas.drawRightString(letter[0] - self.rightMargin, letter[1] - .75 * inch, self.document_label)
        canvas.setStrokeColor(colors.HexColor("#b7c8bf")); canvas.line(self.leftMargin, letter[1] - .81 * inch, letter[0] - self.rightMargin, letter[1] - .81 * inch)
        canvas.setFont("Helvetica", 7.5); canvas.setFillColor(colors.HexColor("#65726c")); canvas.drawString(self.leftMargin, .38 * inch, self.project_name)
        canvas.drawRightString(letter[0] - self.rightMargin, .38 * inch, f"Page {page}"); canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name in {"FSDH1", "FSDH2", "FSDH3"} and re.match(r"^\d+(?:\.\d+)*(?:\.)?\s", flowable.getPlainText()):
            level = {"FSDH1": 0, "FSDH2": 1, "FSDH3": 2}[flowable.style.name]
            self._heading_count += 1
            key = f"fsd-heading-{self._heading_count}"
            self.canv.bookmarkPage(key)
            self.notify("TOCEntry", (level, flowable.getPlainText(), self.page, key))


@timed("Apply PDF headers and footers")
def _overlay_pdf_chrome(output: Path, project_name: str, logo_left: Path, logo_right: Path, document_label: str = "SAP Functional Specification") -> None:
    reader, writer = PdfReader(str(output)), PdfWriter()
    for page_number, page in enumerate(reader.pages, 1):
        number_stream = BytesIO(); number_canvas = Canvas(number_stream, pagesize=letter)
        if logo_left:
            number_canvas.drawImage(str(logo_left), inch, letter[1] - .58 * inch, width=1.55 * inch, height=.42 * inch, preserveAspectRatio=True, mask="auto")
        number_canvas.setFont("Helvetica-Bold", 8); number_canvas.drawRightString(letter[0] - inch - .34 * inch, letter[1] - .43 * inch, "CLIENT")
        number_canvas.setFillColor(colors.HexColor("#E8F3ED")); number_canvas.circle(letter[0] - inch - .13 * inch, letter[1] - .41 * inch, .13 * inch, fill=1, stroke=0)
        number_canvas.setFillColor(colors.HexColor("#0D6B50")); number_canvas.setFont("Helvetica-Bold", 7); number_canvas.drawCentredString(letter[0] - inch - .13 * inch, letter[1] - .435 * inch, "CL")
        number_canvas.setFont("Helvetica", 7.5); number_canvas.setFillColor(colors.HexColor("#5b6762"))
        number_canvas.drawString(inch, letter[1] - .75 * inch, "Classification: INTERNAL")
        number_canvas.drawRightString(letter[0] - inch, letter[1] - .75 * inch, document_label)
        number_canvas.setStrokeColor(colors.HexColor("#b7c8bf")); number_canvas.line(inch, letter[1] - .81 * inch, letter[0] - inch, letter[1] - .81 * inch)
        number_canvas.setFont("Helvetica", 7.5); number_canvas.setFillColor(colors.HexColor("#65726c")); number_canvas.drawString(inch, .38 * inch, project_name)
        number_canvas.setFont("Helvetica", 7.5); number_canvas.setFillColor(colors.HexColor("#65726c"))
        number_canvas.drawRightString(letter[0] - inch, .38 * inch, f"Page {page_number}"); number_canvas.save(); number_stream.seek(0)
        # Merge onto a fresh page so an unbalanced clipping state from a long
        # table cannot affect the independent header/footer stream.
        final_page = writer.add_blank_page(width=float(page.mediabox.width), height=float(page.mediabox.height))
        final_page.merge_page(page)
        final_page.merge_page(PdfReader(number_stream).pages[0])
    temporary = output.with_suffix(".working.pdf")
    with temporary.open("wb") as handle: writer.write(handle)
    temporary.replace(output)


@timed("Compose PDF content")
def _build_pdf(data: dict, images: dict[str, Any], output: Path) -> None:
    _pdf_table_number.set(0)
    styles = _pdf_styles(); story: list[Any] = []; info = data.get("document_information", {})
    toc = TableOfContents()
    toc.levelStyles = [styles["TOC0"], styles["TOC1"], ParagraphStyle("TOC2", parent=styles["TOC1"], leftIndent=28, fontSize=7.4)]
    toc.dotsMinLevel = 0
    story += [Spacer(1, .45 * inch), _pdf_text("CLASSIFICATION: " + _safe(info.get("classification", "INTERNAL")).upper(), styles["CoverKicker"]), Spacer(1, 1.0 * inch),
        _pdf_text("SAP FUNCTIONAL SPECIFICATION DOCUMENT", styles["CoverTitle"]), _pdf_text(data.get("title"), styles["CoverSub"]), Spacer(1, .65 * inch),
        _pdf_table(["Document Attribute", "Value"], [["Process Identifier", info.get("process_identifier")], ["Application", info.get("application")],
            ["Functional Area", info.get("functional_area")], ["Version", data.get("version")], ["Status", data.get("status")],
            ["Prepared By", info.get("prepared_by")]], [1.8, 4.7], styles), PageBreak(),
        _pdf_text("Table of Contents", styles["CoverSub"]), Spacer(1, 8), toc, PageBreak()]
    story += [_pdf_text("Document Control", styles["FSDH1"]), _pdf_table(["Attribute", "Value"], [["Short Description", f"Functional specification for the {_safe(data.get('title'))} process"], ["Application", info.get("application")],
        ["Functional Designer", info.get("prepared_by")], ["Classification", info.get("classification")], ["Process Identifier", info.get("process_identifier")]], [1.65, 4.85], styles),
        _pdf_text("Document History", styles["FSDH2"]), _pdf_table(["Version", "Date", "Author", "Description"],
        [[x.get("version"), x.get("date"), x.get("author"), x.get("description")] for x in data.get("revision_history", [])], [.75, .95, 1.45, 3.35], styles)]
    for heading, statement in (("IT Sign Off", "Reviewed for process security, logic, validations, configuration, permissions, and technical feasibility."),
                               ("Business Sign Off", "Reviewed for business requirement fulfillment, controls, authorizations, scenarios, and expected outcomes.")):
        story += [_pdf_text(heading, styles["FSDH2"]), _pdf_text(statement, styles["Body"]), _pdf_table(["Role", "Name", "Status / Signature"],
            [[x.get("role"), x.get("name"), x.get("status")] for x in data.get("sign_offs", [])], [2.05, 2.15, 2.3], styles)]
    story += [_pdf_text("1. Relevant Documents", styles["FSDH1"]), _pdf_table(["Document Name", "Reference / Revision"], [[x, "TBD"] for x in data.get("relevant_documents", [])], [4.7, 1.8], styles)]
    scope = data.get("scope", {}); story += [_pdf_text("2. Process Scope", styles["FSDH1"]), _pdf_text("2.1 Business Context", styles["FSDH2"]), _pdf_text(scope.get("business_context"), styles["Body"]),
        _pdf_text("2.1.1 As-Is Process", styles["FSDH3"])]
    story.extend(_pdf_bullets(scope.get("as_is_process", []), styles)); story.append(_pdf_text("2.1.2 Current Constraints", styles["FSDH3"])); story.extend(_pdf_bullets(scope.get("current_constraints", []), styles))
    for number, title, key in (("2.2", "Objectives", "objectives"), ("2.3", "In Scope", "in_scope"), ("2.4", "Out of Scope", "out_of_scope"), ("2.5", "Glossary", "glossary")):
        story.append(_pdf_text(f"{number} {title}", styles["FSDH2"])); story.extend(_pdf_bullets(scope.get(key, []), styles))
    story += [_pdf_text("3. Process Information and Future-State Design", styles["FSDH1"]), _pdf_text("3.1 Process Description", styles["FSDH2"]),
        _pdf_text("As-Is Context", styles["FSDH3"]), _pdf_text(data.get("as_is_narrative"), styles["Body"]), _pdf_text("To-Be Response", styles["FSDH3"]), _pdf_text(data.get("future_state_narrative"), styles["Body"]),
        _pdf_table(["Current Constraint", "To-Be Response", "Expected Improvement", "Req IDs"], [[x.get("constraint"), x.get("to_be_response"), x.get("expected_improvement"), x.get("requirement_ids")] for x in data.get("improvement_mapping", [])], [1.55, 1.95, 2.15, .85], styles),
        _pdf_text("3.2 Actors and Systems", styles["FSDH2"]), _pdf_table(["Actor / System", "Type", "Responsibility", "Requirement IDs"],
        [[x.get("name"), x.get("actor_type"), x.get("responsibility"), x.get("requirement_ids")] for x in data.get("actors_and_systems", [])], [1.3, .85, 2.85, 1.5], styles), _pdf_text("3.3 Process Flow", styles["FSDH2"])]
    if images.get("as_is_process"):
        story += [_pdf_text("3.3.1 As-Is Process Flow", styles["FSDH3"]), _pdf_picture(images["as_is_process"]), _pdf_text("Figure 1: As-Is process flow and current constraints", styles["Caption"])]
    if images.get("process"):
        story += [_pdf_text("3.3.2 To-Be Process Flow", styles["FSDH3"]), _pdf_picture(images["process"]), _pdf_text("Figure 2: To-Be process flow", styles["Caption"])]
    if images.get("legend"):
        story += [_pdf_text("3.3.3 Process Diagram Legend", styles["FSDH3"]), _pdf_picture(images["legend"], max_height=4.0 * inch), _pdf_text("Figure 3: Process diagram legend", styles["Caption"])]
    story.append(_pdf_text("3.4 Activity List", styles["FSDH2"])); _pdf_records(story, data.get("process_steps", []), "step_id", "activity", styles)
    story.append(_pdf_text("3.5 Process Triggers, Alternate and Exception Flows", styles["FSDH2"])); story.append(_pdf_table(["Flow Type", "Trigger", "Flow / Handling", "Expected Outcome", "Req IDs"], [[x.get("flow_type"), x.get("trigger"), x.get("flow"), x.get("expected_outcome"), x.get("requirement_ids")] for x in data.get("process_flow_variants", [])], [1.0, 1.25, 2.0, 1.5, .75], styles))
    story += [_pdf_text("4. Functional Specification", styles["FSDH1"]), _pdf_text("4.1 Requirement Details", styles["FSDH2"])]
    _pdf_records(story, data.get("requirements", []), "requirement_id", "title", styles, {"requirement_key"})
    story.append(_pdf_text("4.2 Processing Logic", styles["FSDH2"])); story.extend(_pdf_bullets(data.get("processing_logic", []), styles))
    story.append(_pdf_text("4.3 Business Rules", styles["FSDH2"])); _pdf_records(story, data.get("business_rules", []), "rule_id", "description", styles)

    story.append(_pdf_text("4.4 Screen Design and Navigation", styles["FSDH2"]))
    if images.get("navigation"):
        story += [_pdf_picture(images["navigation"]), _pdf_text("Figure 4: Screen navigation flow", styles["Caption"])]
    for index, screen in enumerate(data.get("screens", []), 1):
        sid = _safe(screen.get("screen_id")); story += [_pdf_text(f"4.4.{index} {sid} - {_safe(screen.get('name'))}", styles["FSDH3"]),
            _pdf_table(["Field", "Detail"], [[key.replace("_", " ").title(), value] for key, value in screen.items() if key not in {"screen_id", "name", "ascii_wireframe", "fields", "actions", "messages"}], [1.55, 4.95], styles)]
        if images.get("screens", {}).get(sid):
            story += [_pdf_picture(images["screens"][sid], max_height=5.2 * inch), _pdf_text(f"Figure {index + 4}: {sid} SAP Fiori screen design sample", styles["Caption"])]
        story.append(_pdf_text("Fields", styles["FSDH3"])); _pdf_records(story, screen.get("fields", []), "field_id", "label", styles)
        story.append(_pdf_text("Actions", styles["FSDH3"])); _pdf_records(story, screen.get("actions", []), "action", "enabled_when", styles)
        story.append(_pdf_text("Messages", styles["FSDH3"])); _pdf_records(story, screen.get("messages", []), "message_id", "message_text", styles)

    story.append(_pdf_text("4.5 Data Mapping", styles["FSDH2"])); _pdf_records(story, data.get("data_mappings", []), "mapping_id", "business_field", styles)
    story.append(_pdf_text("4.6 Status Definitions", styles["FSDH2"])); _pdf_records(story, data.get("status_definitions", []), "status_id", "domain", styles)
    story.append(_pdf_text("4.7 Business Message Catalogue", styles["FSDH2"])); _pdf_records(story, data.get("message_catalog", []), "message_id", "scenario", styles)

    story.append(_pdf_text("5. Configuration", styles["FSDH1"])); _pdf_records(story, data.get("configuration_items", []), "config_id", "item", styles)
    story.append(_pdf_text("6. Technical Elements of Enhancement", styles["FSDH1"])); _pdf_records(story, data.get("technical_objects", []), "object_id", "name", styles)
    for subheading, list_key in (("6.1 Cross-Process Impacts", "cross_process_impacts"), ("6.2 Batch Job Details", "batch_jobs"), ("6.3 Dependencies", "dependencies"), ("6.4 Assumptions", "assumptions")):
        story.append(_pdf_text(subheading, styles["FSDH2"])); story.extend(_pdf_bullets(data.get(list_key, []), styles))

    story.append(_pdf_text("7. Roles & Responsibilities", styles["FSDH1"])); _pdf_records(story, data.get("actors_and_systems", []), "name", "responsibility", styles)
    story.append(_pdf_text("8. Roles, Transaction Codes & Authorization Objects", styles["FSDH1"])); _pdf_records(story, data.get("roles_and_authorizations", []), "role_id", "business_role", styles)
    story.append(_pdf_text("9. Test Conditions", styles["FSDH1"])); _pdf_records(story, data.get("test_conditions", []), "test_id", "scenario", styles)
    story += [_pdf_text("10. Related RICEFW Items", styles["FSDH1"]), _pdf_table(["RICEFW Item"], [[x] for x in data.get("ricefw_inventory", [])], [6.5], styles)]
    story.append(_pdf_text("11. Integration Points", styles["FSDH1"])); _pdf_records(story, data.get("interfaces", []), "interface_id", "purpose", styles)
    story.append(_pdf_text("12. Open Points / Outstanding Issues & Omissions", styles["FSDH1"])); _pdf_records(story, data.get("outstanding_issues", []), "issue_id", "description", styles)
    story.append(_pdf_text("13. Group / Company Localization Requirements", styles["FSDH1"])); story.extend(_pdf_bullets(data.get("localization_requirements", []), styles))
    story.append(_pdf_text("14. Risk / Vulnerability Assessment", styles["FSDH1"])); _pdf_records(story, data.get("risks", []), "risk_id", "risk", styles)
    story.append(_pdf_text("15. Optional Non-Functional Requirements", styles["FSDH1"])); _pdf_records(story, data.get("non_functional_requirements", []), "nfr_id", "category", styles)
    story.append(_pdf_text("16. Appendices", styles["FSDH1"]))
    for subheading, key in (("16.1 Reports and Notifications", "reports_and_notifications"), ("16.2 Controls", "controls"), ("16.3 Open Questions", "open_questions")):
        story.append(_pdf_text(subheading, styles["FSDH2"])); story.extend(_pdf_bullets(data.get(key, []), styles))
    story.append(_pdf_text("16.4 Review Checklist", styles["FSDH2"])); _pdf_records(story, data.get("review_checklist", []), "check", "result", styles)
    footer_name = _safe(data.get("title"))
    pdf = _FSDTemplate(str(output), pagesize=letter, rightMargin=inch, leftMargin=inch, topMargin=1.0 * inch, bottomMargin=.7 * inch, title=_safe(data.get("title")), author="SAP Project Copilot",
                       project_name=footer_name, logo_left=images.get("logo_left"), logo_right=images.get("logo_right"))
    # Render content first, then merge the same independent chrome stream over
    # every page. This avoids long tables inheriting or clipping canvas state.
    pdf.multiBuild(story, onFirstPage=lambda canvas, doc: None, onLaterPages=lambda canvas, doc: None)
    _overlay_pdf_chrome(output, pdf.project_name, images.get("logo_left"), images.get("logo_right"))


@timed("Export DOCX, PDF and diagrams")
def export_fsd_files(document: dict, project_name: str, project_id: str, artifact_root: str) -> dict[str, str]:
    output_dir = Path(artifact_root) / project_id; image_dir = output_dir / "images"; image_dir.mkdir(parents=True, exist_ok=True)
    process_image = image_dir / "future-state-process.png" if document.get("process_steps") else None
    as_is_process_image = image_dir / "as-is-process.png" if document.get("as_is_process_steps") else None
    legend_image = image_dir / "process-diagram-legend.png"
    navigation_image = image_dir / "screen-navigation.png" if document.get("screens") else None
    left_logo, right_logo = image_dir / "infrabeat-logo.png", image_dir / "dummy-client-logo.png"
    _draw_logos(left_logo, right_logo)
    _draw_process_legend(legend_image, steps=document.get("process_steps") or [])
    if process_image: _draw_process_flow(document.get("process_steps", []), process_image, "To-Be Process Flow")
    if as_is_process_image: _draw_process_flow(document.get("as_is_process_steps", []), as_is_process_image, "As-Is Process Flow")
    if navigation_image: _draw_navigation(document.get("screens", []), navigation_image)
    screen_images: dict[str, Path] = {}
    for index, screen in enumerate(document.get("screens", []), 1):
        sid = _safe(screen.get("screen_id") or f"SCREEN-{index}"); path = image_dir / f"{_slug(sid)}.png"; _draw_fiori_screen(screen, path); screen_images[sid] = path
    images = {"process": process_image, "as_is_process": as_is_process_image, "legend": legend_image, "navigation": navigation_image,
              "screens": screen_images, "logo_left": left_logo, "logo_right": right_logo}
    display_name = _apply_export_identity(document, project_name)
    stem = f"{_slug(display_name)}-functional-specification"; docx_path, pdf_path = output_dir / f"{stem}.docx", output_dir / f"{stem}.pdf"
    word = WordDocument(); _style_word(word, display_name, {"left": left_logo, "right": right_logo}); _add_word_contents(word, document, images); word.save(docx_path); _build_pdf(document, images, pdf_path)
    return {"docx": str(docx_path.resolve()), "pdf": str(pdf_path.resolve()), "process_image": str(process_image.resolve()) if process_image else "",
            "as_is_process_image": str(as_is_process_image.resolve()) if as_is_process_image else "", "navigation_image": str(navigation_image.resolve()) if navigation_image else ""}
