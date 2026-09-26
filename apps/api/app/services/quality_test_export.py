from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


from .project_identity import looks_like_person_name, priority_label


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "project"


def _quality_display_name(test_pack: dict, fallback: str) -> str:
    pack = test_pack if isinstance(test_pack, dict) else {}
    candidates = [fallback, pack.get("project_name"), pack.get("title")]
    for candidate in candidates:
        text = re.sub(r"^quality test pack\s*[-–:]\s*", "", str(candidate or ""), flags=re.I).strip()
        text = re.sub(r"\s*[-–:]\s*quality test pack\s*$", "", text, flags=re.I).strip()
        if text and not looks_like_person_name(text):
            return text
    return "SAP Business Process"


def _apply_quality_identity(test_pack: dict, fallback: str) -> str:
    display_name = _quality_display_name(test_pack, fallback)
    test_pack["title"] = display_name
    test_pack["project_name"] = display_name
    for case in test_pack.get("test_cases") or []:
        if isinstance(case, dict):
            case["priority"] = priority_label(case.get("priority"))
    return display_name


def _runtime() -> tuple[Path, Path]:
    root = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies"
    bundled_node, bundled_modules = root / "node" / "bin" / "node.exe", root / "node" / "node_modules"
    node = bundled_node if bundled_node.exists() else Path(shutil.which("node") or "")
    modules = Path(os.getenv("ARTIFACT_TOOL_NODE_MODULES", str(bundled_modules)))
    if not node.exists() or not modules.exists():
        raise RuntimeError("Spreadsheet runtime is unavailable. Configure ARTIFACT_TOOL_NODE_MODULES.")
    return node, modules


def export_quality_tests(test_pack: dict, project_name: str, project_id: str, artifact_root: str) -> str:
    pack = dict(test_pack or {})
    display_name = _apply_quality_identity(pack, project_name)
    output_dir = (Path(artifact_root) / project_id).resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{_slug(display_name)}-quality-test-pack.xlsx"
    node, modules = _runtime(); temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False, dir=output_dir) as temporary:
            json.dump(pack, temporary, ensure_ascii=False); temporary_path = Path(temporary.name)
        environment = {**os.environ, "NODE_PATH": str(modules)}
        completed = subprocess.run([str(node), str(Path(__file__).with_name("quality_test_builder.mjs")), str(temporary_path), str(output)], cwd=str(output_dir), env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False)
        if completed.returncode != 0 or not output.exists():
            detail = (completed.stderr or completed.stdout or "Unknown spreadsheet export error").strip()
            raise RuntimeError(f"Quality-testing Excel export failed: {detail[-1600:]}")
        return str(output)
    finally:
        if temporary_path: temporary_path.unlink(missing_ok=True)
