from __future__ import annotations

import html
import re
import shutil
import zipfile
from datetime import date, datetime
from pathlib import Path

from .project_identity import looks_like_person_name

TEMPLATE_NAME = "Project_Planning_Template_Curved.xlsx"
TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "templates" / "sprint-plan" / TEMPLATE_NAME
SHEET1 = "xl/worksheets/sheet1.xml"
FIRST_TASK_ROW = 7
LAST_TASK_ROW = 206
MAX_TASKS = LAST_TASK_ROW - FIRST_TASK_ROW + 1

PHASES = ["Planning", "Analysis", "Design", "Build", "Testing", "Deployment", "Closure", "Other"]
PRIORITY_MAP = {"must": "Critical", "should": "High", "could": "Medium", "won't": "Low", "wont": "Low"}
STATUS_MAP = {
    "not started": "Not Started",
    "ready": "Not Started",
    "in progress": "In Progress",
    "blocked": "Blocked",
    "on hold": "On Hold",
    "complete": "Complete",
    "completed": "Complete",
}
EMPTY_CELL = re.compile(r'<x:c r="([A-Z]+)(\d+)"([^>]*)/>')


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "project"


def _template_path() -> Path:
    if not TEMPLATE_PATH.exists():
        raise RuntimeError(f"Sprint-plan Excel template is missing: {TEMPLATE_PATH}")
    return TEMPLATE_PATH


def _as_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _as_number(value) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _excel_serial(value: date) -> int:
    return (value - date(1899, 12, 30)).days


def _map_priority(value: str) -> str:
    return PRIORITY_MAP.get(_as_text(value).lower(), "Medium")


def _map_status(value: str) -> str:
    return STATUS_MAP.get(_as_text(value).lower(), "Not Started")


def _map_phase(story: dict) -> str:
    explicit = _as_text(story.get("phase"))
    if explicit in PHASES:
        return explicit
    try:
        sprint = int(story.get("sprint") or 1)
    except (TypeError, ValueError):
        sprint = 1
    if 1 <= sprint <= len(PHASES):
        return PHASES[sprint - 1]
    return "Other"


def _task_notes(story: dict) -> str:
    parts = [
        f"Sprint {story.get('sprint')}" if story.get("sprint") not in (None, "") else "",
        _as_text(story.get("requirement_key")),
        _as_text(story.get("source_locator")),
    ]
    return " · ".join(part for part in parts if part)


def _xml_string(text: str) -> str:
    return html.escape(text, quote=False)


def _number_xml(ref: str, attrs: str, value: float | int) -> str:
    cleaned = re.sub(r'\st="[^"]*"', "", attrs)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f'<x:c r="{ref}"{cleaned}><x:v>{value}</x:v></x:c>'


def _string_xml(ref: str, attrs: str, value: str) -> str:
    if ' t="' not in attrs:
        attrs += ' t="str"'
    return f'<x:c r="{ref}"{attrs}><x:v>{_xml_string(value)}</x:v></x:c>'


def _task_values(story: dict, index: int) -> dict[str, object]:
    start = _as_date(story.get("start_date"))
    due = _as_date(story.get("target_end_date") or story.get("due_date"))
    points = _as_number(story.get("story_points"))
    progress = _as_number(story.get("progress_percent"))
    status = _map_status(story.get("status"))
    ratio = None
    if progress is not None:
        ratio = max(0.0, min(1.0, progress / 100.0 if progress > 1 else progress))
    if status == "Complete":
        ratio = 1.0
    values: dict[str, object] = {
        "A": _as_text(story.get("story_key")) or f"US-{index:03}",
        "B": _map_phase(story),
        "C": _as_text(story.get("title")) or _as_text(story.get("story")) or f"US-{index:03}",
        "D": _as_text(story.get("assigned_to")) or "Unassigned",
        "E": _map_priority(story.get("priority")),
        "I": status,
    }
    if start:
        values["F"] = start
    if due:
        values["G"] = due
    if points is not None:
        values["K"] = points
        values["P"] = points
    if ratio:
        values["L"] = ratio
        if points is not None:
            values["J"] = round(points * ratio, 4)
    dependency = _as_text(story.get("dependency"))
    notes = _task_notes(story)
    if dependency:
        values["Q"] = dependency
    if notes:
        values["S"] = notes
    return values


def _display_project_name(backlog: dict, project_name: str) -> str:
    for candidate in (project_name, _as_text(backlog.get("project_name")), _as_text(backlog.get("title"))):
        text = re.sub(r"^delivery backlog\s*[-–:]\s*", "", candidate, flags=re.I).strip()
        text = re.sub(r"\s*[-–:]\s*delivery backlog\s*$", "", text, flags=re.I).strip()
        if text and not looks_like_person_name(text):
            return text
    return "SAP Delivery Project"


def _header_values(backlog: dict, project_name: str) -> dict[str, object]:
    stories = backlog.get("stories") or []
    sprints = backlog.get("sprints") or []
    objective = _as_text(backlog.get("objective")) or _as_text(backlog.get("title"))
    if not objective:
        sprint_count = len(sprints) or len({story.get("sprint") for story in stories if story.get("sprint") is not None})
        objective = (
            f"Deliver {len(stories)} approved, source-linked requirements"
            + (f" across {sprint_count} sprint(s)." if sprint_count else ".")
        )
    return {
        "B2": _display_project_name(backlog, project_name),
        "E2": _as_text(backlog.get("project_manager")) or "SAP Delivery Lead",
        "B3": objective,
    }


def _fill_empty_cell(ref: str, attrs: str, value) -> str:
    if isinstance(value, date):
        return _number_xml(ref, attrs, _excel_serial(value))
    if isinstance(value, (int, float)):
        return _number_xml(ref, attrs, value)
    return _string_xml(ref, attrs, str(value))


def _patch_sheet(xml: str, values_by_ref: dict[str, object]) -> str:
    def replace(match: re.Match[str]) -> str:
        col, row, attrs = match.group(1), match.group(2), match.group(3)
        ref = f"{col}{row}"
        if ref not in values_by_ref:
            return match.group(0)
        return _fill_empty_cell(ref, attrs, values_by_ref[ref])

    return EMPTY_CELL.sub(replace, xml)


def _replace_zip_entry(xlsx_path: Path, inner_name: str, data: bytes) -> None:
    temporary = xlsx_path.with_suffix(xlsx_path.suffix + ".tmp")
    with zipfile.ZipFile(xlsx_path, "r") as source, zipfile.ZipFile(temporary, "w") as target:
        for item in source.infolist():
            payload = data if item.filename == inner_name else source.read(item.filename)
            target.writestr(item, payload)
    temporary.replace(xlsx_path)


def export_sprint_plan(backlog: dict, project_name: str, project_id: str, artifact_root: str) -> str:
    output_dir = (Path(artifact_root) / project_id).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_slug(_display_project_name(backlog or {}, project_name))}-sprint-plan.xlsx"
    shutil.copyfile(_template_path(), output_path)

    backlog = backlog or {}
    values: dict[str, object] = _header_values(backlog, project_name)
    stories = list(backlog.get("stories") or [])[:MAX_TASKS]
    for offset, story in enumerate(stories):
        row = FIRST_TASK_ROW + offset
        for column, value in _task_values(story or {}, offset + 1).items():
            values[f"{column}{row}"] = value

    with zipfile.ZipFile(output_path, "r") as workbook:
        sheet = workbook.read(SHEET1).decode("utf-8")
    _replace_zip_entry(output_path, SHEET1, _patch_sheet(sheet, values).encode("utf-8"))
    return str(output_path.resolve())
