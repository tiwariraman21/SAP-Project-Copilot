from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


FSD_TEMPLATE_VERSION = "fsd-master-v3"
_TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates" / "fsd" / "v3"


@dataclass(frozen=True)
class FSDTemplateContract:
    template_version: str
    schema_version: str
    prompt_version: str
    renderer_version: str
    name: str
    minimum_screens: int
    sections: tuple[tuple[str, str], ...]
    required_collections: tuple[str, ...]
    content_limits: dict[str, int]
    branding: dict[str, str]
    section_sources: dict[str, tuple[str, ...]]
    validation_rules: dict[str, bool]
    prompt: str

    def provenance(self) -> dict[str, Any]:
        return {
            "template_version": self.template_version,
            "schema_version": self.schema_version,
            "prompt_version": self.prompt_version,
            "renderer_version": self.renderer_version,
        }


@lru_cache(maxsize=1)
def get_fsd_template() -> FSDTemplateContract:
    contract = json.loads((_TEMPLATE_ROOT / "template-contract.json").read_text(encoding="utf-8"))
    rules = json.loads((_TEMPLATE_ROOT / "validation-rules.json").read_text(encoding="utf-8"))
    prompt = (_TEMPLATE_ROOT / "generation-prompt.txt").read_text(encoding="utf-8").strip()
    section_sources = {key: tuple(value) for key, value in contract.get("section_sources", {}).items()}
    if section_sources:
        prompt += "\n\nFSD SECTION-TO-BRD CONTEXT MAP (template-owned):\n" + "\n".join(
            f"- {section}: {', '.join(sources)}" for section, sources in section_sources.items()
        )
    if contract["template_version"] != FSD_TEMPLATE_VERSION:
        raise RuntimeError("The active FSD template version does not match its directory contract")
    return FSDTemplateContract(
        template_version=contract["template_version"],
        schema_version=contract["schema_version"],
        prompt_version=contract["prompt_version"],
        renderer_version=contract["renderer_version"],
        name=contract["name"],
        minimum_screens=int(contract["minimum_screens"]),
        sections=tuple((str(number), str(title)) for number, title in contract["sections"]),
        required_collections=tuple(contract["required_collections"]),
        content_limits={key: int(value) for key, value in contract["content_limits"].items()},
        branding=dict(contract["branding"]),
        section_sources=section_sources,
        validation_rules={key: bool(value) for key, value in rules.items()},
        prompt=prompt,
    )
