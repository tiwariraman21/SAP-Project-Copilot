from __future__ import annotations

import re
from pathlib import Path
from typing import Any


PROCESS_KEYWORDS = {
    "sap", "s4hana", "fiori", "hana", "purchase", "requisition", "procurement", "approval",
    "order", "cash", "invoice", "vendor", "supplier", "governance", "warehouse", "inventory",
    "finance", "payroll", "project", "process", "workflow", "sales", "delivery", "material",
    "plant", "quality", "maintenance", "asset", "contract", "sourcing", "payment", "credit",
}

PROCESS_PHRASES = (
    (r"purchase\s+requisition", "Purchase Requisition Approval"),
    (r"procure\s+to\s+pay|source\s+to\s+pay", "Procure to Pay"),
    (r"order\s+to\s+cash", "Order to Cash"),
    (r"supplier\s+governance", "Supplier Governance"),
    (r"vendor\s+management", "Vendor Management"),
    (r"sales\s+order", "Sales Order Management"),
    (r"goods\s+receipt", "Goods Receipt"),
    (r"invoice\s+(?:process|approval|management)", "Invoice Processing"),
    (r"credit\s+(?:check|management)", "Credit Management"),
)

TITLE_PATTERNS = (
    r"(?:project\s+(?:name|title)|document\s+title|process\s+(?:name|title)|business\s+process|solution\s+name)\s*[:\-]\s*(.+)",
    r"(?:title)\s*[:\-]\s*(.+)",
)

PRIORITY_LABELS = {
    "must": "Must Have",
    "should": "Good To Have",
    "could": "Nice To Have",
    "won't": "Won't Have",
    "wont": "Won't Have",
}


def priority_label(value: Any) -> str:
    text = str(value or "").strip()
    return PRIORITY_LABELS.get(text.lower(), text.replace("_", " ").title() or "TBD")


def looks_like_person_name(value: Any) -> bool:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" -_,.")
    if not text:
        return False
    words = re.findall(r"[A-Za-z]+", text)
    if not (2 <= len(words) <= 4):
        return False
    if any(ch.isdigit() for ch in text):
        return False
    if any(word.lower() in PROCESS_KEYWORDS for word in words):
        return False
    return all(word[0].isupper() and (word[1:].islower() or word.isupper()) for word in words)


def _clean_label(value: Any) -> str:
    text = str(value or "").strip()
    text = Path(text).stem
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"\b(brd|fsd|tdd|tsd|docx|pdf|final|draft|v\d+(?:\.\d+)?|version\s*\d+)\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -_,.")
    if text.lower().endswith(" business requirements document"):
        text = text[: -len(" business requirements document")].strip(" -")
    return text


def _usable_name(value: Any) -> str:
    text = _clean_label(value)
    if not text or looks_like_person_name(text) or text.upper() in {"TBD", "N/A", "NONE"}:
        return ""
    words = re.findall(r"[A-Za-z0-9]+", text)
    if len(text) < 4 or len(words) < 2:
        return ""
    return text


def _suggest_from_text(text: str) -> str:
    blob = text.lower()
    for pattern, label in PROCESS_PHRASES:
        if re.search(pattern, blob, re.I):
            return label
    for pattern in TITLE_PATTERNS:
        match = re.search(pattern, text, re.I)
        if match:
            candidate = _usable_name(match.group(1).split("\n")[0][:120])
            if candidate:
                return candidate
    return ""


def _source_text(project: Any) -> str:
    parts: list[str] = []
    knowledge = getattr(project, "brd_knowledge", None)
    payload = knowledge.payload if knowledge and isinstance(getattr(knowledge, "payload", None), dict) else {}
    control = payload.get("document_control") if isinstance(payload.get("document_control"), dict) else {}
    for key in ("document_name", "business_area", "primary_business_system"):
        if control.get(key):
            parts.append(str(control[key]))
    for key in ("executive_summary", "business_context", "desired_future_state"):
        if payload.get(key):
            parts.append(str(payload[key]))
    document = getattr(project, "document", None)
    if document is not None:
        parts.append(str(getattr(document, "filename", "") or ""))
        chunks = list(getattr(document, "chunks", []) or [])[:20]
        parts.extend(str(getattr(chunk, "text", "") or "")[:800] for chunk in chunks)
    for requirement in list(getattr(project, "requirements", []) or [])[:12]:
        parts.append(str(getattr(requirement, "title", "") or ""))
        parts.append(str(getattr(requirement, "statement", "") or "")[:240])
    return "\n".join(part for part in parts if part)


def business_project_name(project: Any) -> str:
    knowledge = getattr(project, "brd_knowledge", None)
    payload = knowledge.payload if knowledge and isinstance(getattr(knowledge, "payload", None), dict) else {}
    control = payload.get("document_control") if isinstance(payload.get("document_control"), dict) else {}
    document = getattr(project, "document", None)
    suggested = _suggest_from_text(_source_text(project))
    candidates = [
        _usable_name(control.get("document_name")),
        suggested,
        _usable_name(getattr(project, "name", "")),
        _usable_name(getattr(document, "filename", "") if document is not None else ""),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    return "SAP Business Process"


def process_identifier_from_name(name: str) -> str:
    stop = {"the", "a", "an", "of", "and", "to", "for", "in", "on", "sap"}
    words = [word.upper() for word in re.findall(r"[A-Za-z0-9]+", name) if word.lower() not in stop]
    if not words:
        return "PROC-TBD"
    compact = []
    for word in words[:5]:
        compact.append(word if len(word) <= 12 else word[:6])
    return "-".join(compact)


def process_identifier(project: Any) -> str:
    return process_identifier_from_name(business_project_name(project))


def clean_document_title(value: Any, fallback: str = "") -> str:
    text = re.sub(
        r"\s*-\s*(?:Technical Design Specification|Functional (?:Solution )?Design)\s*$",
        "",
        str(value or ""),
        flags=re.I,
    ).strip()
    if text and not looks_like_person_name(text):
        return text
    fallback_text = str(fallback or "").strip()
    if fallback_text and not looks_like_person_name(fallback_text):
        return fallback_text
    return "SAP Business Process"


def project_short_description(project: Any) -> str:
    return f"Functional specification for the {business_project_name(project)} process"
