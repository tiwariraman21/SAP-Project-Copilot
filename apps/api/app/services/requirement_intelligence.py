import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

from openai import OpenAI
from openai import OpenAIError

from ..config import settings
from ..schemas import ExtractedRequirement, RequirementBatch
from .openai_support import AIServiceError, Usage, response_usage


SYSTEM_PROMPT = """You are the Requirement Intelligence capability for an SAP delivery copilot.
Extract atomic, implementation-relevant requirements only from the supplied source chunks.
Every requirement must cite one or more exact chunk IDs and include a short verbatim source quote.
Do not invent SAP modules, transactions, integrations, fields, or policy details.
Write testable acceptance criteria. Use confidence below 0.7 when the source is ambiguous.
The source_quote must be a verbatim substring of one cited chunk. Return only atomic requirements that are supported by the chunks."""

ProgressCallback = Callable[[str, int], None]


def _progress(callback: ProgressCallback | None, message: str, percent: int) -> None:
    if callback:
        callback(message, percent)


def extract_requirements(chunks: list[dict[str, str | int]], progress: ProgressCallback | None = None) -> tuple[list[ExtractedRequirement], Usage | None]:
    _progress(progress, f"Preparing {len(chunks)} source chunks", 15)
    if settings.openai_api_key:
        try:
            client = OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds, max_retries=2)
            selected = _limit_source(_compact_source(chunks))
            batches = _make_batches(selected)
            workers = max(1, min(settings.openai_requirements_parallel_batches, len(batches)))
            _progress(progress, f"Prepared {len(batches)} OpenAI extraction batches using {settings.openai_requirements_model}; running up to {workers} concurrently", 20)
            started = time.perf_counter()
            extracted, usages = _extract_batches(client, batches, progress, workers)
            elapsed = time.perf_counter() - started
            _progress(progress, f"OpenAI extraction finished in {elapsed:.1f}s", 82)
            _progress(progress, f"Deduplicating {len(extracted)} requirement candidates", 84)
            deduplicated = _deduplicate(extracted)
            _progress(progress, f"Validating source evidence for {len(deduplicated)} unique candidates", 90)
            grounded = _ground_requirements(deduplicated, selected)
            if not grounded:
                raise AIServiceError("OpenAI produced no requirements with verifiable source evidence")
            usage = Usage(model=settings.openai_requirements_model,
                          input_tokens=sum(x.input_tokens for x in usages), output_tokens=sum(x.output_tokens for x in usages),
                          total_tokens=sum(x.total_tokens for x in usages))
            _progress(progress, f"Validated {len(grounded)} source-linked requirements", 96)
            return grounded, usage
        except (OpenAIError, AIServiceError, ValueError) as exc:
            if not settings.openai_allow_demo_fallback:
                raise AIServiceError(f"Requirement extraction failed: {exc}") from exc
    _progress(progress, "OpenAI key not configured; running local demo extraction", 40)
    results = _demo_extract(chunks)
    _progress(progress, f"Demo extraction produced {len(results)} requirements", 96)
    return results, None


def _extract_batches(client: OpenAI, batches: list[list[dict[str, str | int]]],
                     progress: ProgressCallback | None, workers: int) -> tuple[list[ExtractedRequirement], list[Usage]]:
    """Run independent source batches concurrently while preserving document order."""
    if not batches:
        return [], []
    workers = max(1, min(workers, len(batches)))
    if workers == 1:
        requirements: list[ExtractedRequirement] = []
        usages: list[Usage] = []
        for index, batch in enumerate(batches, 1):
            _progress(progress, f"Sending batch {index}/{len(batches)} to OpenAI ({len(batch)} chunks)", 20 + int(60 * (index - 1) / len(batches)))
            batch_requirements, batch_usages = _extract_batch(client, batch, f"{index}/{len(batches)}", progress)
            requirements.extend(batch_requirements); usages.extend(batch_usages)
            _progress(progress, f"Completed batch {index}/{len(batches)} — {len(batch_requirements)} candidates", 20 + int(60 * index / len(batches)))
        return requirements, usages

    ordered: list[tuple[list[ExtractedRequirement], list[Usage]] | None] = [None] * len(batches)
    completed = 0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="requirement-ai") as executor:
        futures = {
            executor.submit(_extract_batch, client, batch, f"{index + 1}/{len(batches)}", None): index
            for index, batch in enumerate(batches)
        }
        _progress(progress, f"Sent {len(batches)} batches to OpenAI with {workers} parallel workers", 22)
        for future in as_completed(futures):
            index = futures[future]
            ordered[index] = future.result()
            completed += 1
            candidate_count = len(ordered[index][0]) if ordered[index] else 0
            _progress(progress, f"Completed batch {index + 1}/{len(batches)} — {candidate_count} candidates ({completed}/{len(batches)} finished)", 22 + int(58 * completed / len(batches)))

    requirements: list[ExtractedRequirement] = []
    usages: list[Usage] = []
    for result in ordered:
        if result:
            requirements.extend(result[0]); usages.extend(result[1])
    return requirements, usages


def _limit_source(chunks: list[dict[str, str | int]]) -> list[dict[str, str | int]]:
    """Enforce a safety ceiling without silently discarding the end of a BRD."""
    total = sum(len(str(chunk.get("text", ""))) for chunk in chunks)
    if total > settings.openai_max_source_characters:
        raise AIServiceError(
            f"The extracted BRD contains {total:,} source characters, above the configured "
            f"OPENAI_MAX_SOURCE_CHARACTERS={settings.openai_max_source_characters:,}. "
            "Increase the limit or use a retrieval strategy; extraction was stopped to avoid partial coverage."
        )
    return chunks


def _compact_source(chunks: list[dict[str, str | int]]) -> list[dict[str, str | int]]:
    """Remove layout whitespace from extracted documents without dropping text."""
    return [
        {**chunk, "text": re.sub(r"\s+", " ", str(chunk["text"])).strip()}
        for chunk in chunks
        if str(chunk.get("text", "")).strip()
    ]


def _make_batches(chunks: list[dict[str, str | int]]) -> list[list[dict[str, str | int]]]:
    batches: list[list[dict[str, str | int]]] = []
    current: list[dict[str, str | int]] = []
    size = 0
    for chunk in chunks:
        chunk_size = len(str(chunk["text"])) + 100
        if current and size + chunk_size > settings.openai_requirements_batch_characters:
            batches.append(current)
            current, size = [], 0
        current.append(chunk)
        size += chunk_size
    if current:
        batches.append(current)
    if len(batches) > settings.openai_requirements_max_batches:
        raise AIServiceError(
            f"The BRD requires {len(batches)} requirement-extraction batches, but "
            f"OPENAI_REQUIREMENTS_MAX_BATCHES={settings.openai_requirements_max_batches}. "
            "Increase the limit; extraction was stopped to prevent silently ignoring source content."
        )
    return batches


def _extract_batch(client: OpenAI, batch: list[dict[str, str | int]], label: str,
                   progress: ProgressCallback | None = None) -> tuple[list[ExtractedRequirement], list[Usage]]:
    source = "\n".join(f"[{c['id']}] {c['locator']}: {c['text']}" for c in batch)
    try:
        response = client.responses.parse(
            model=settings.openai_requirements_model, instructions=SYSTEM_PROMPT,
            input=f"Extract all review-candidate requirements from source batch {label}:\n{source}",
            text_format=RequirementBatch, max_output_tokens=settings.openai_requirements_max_output_tokens,
            store=False, prompt_cache_key="sap-copilot-requirements-v1",
        )
        if not response.output_parsed:
            raise ValueError("OpenAI returned no parsed requirement output")
        return response.output_parsed.requirements, [response_usage(response, settings.openai_requirements_model)]
    except ValueError:
        if len(batch) <= 1:
            raise
        _progress(progress, f"Batch {label} returned incomplete structured output; splitting and retrying", 0)
        midpoint = len(batch) // 2
        left, left_usage = _extract_batch(client, batch[:midpoint], label + "a", progress)
        right, right_usage = _extract_batch(client, batch[midpoint:], label + "b", progress)
        return left + right, left_usage + right_usage


def _deduplicate(requirements: list[ExtractedRequirement]) -> list[ExtractedRequirement]:
    """Remove exact and strong semantic duplicates while keeping source order."""
    unique: list[ExtractedRequirement] = []
    normalized_unique: list[str] = []
    seen: set[str] = set()
    for item in requirements:
        key = _normalize(item.statement)
        if not key or key in seen:
            continue
        near_duplicate = any(
            SequenceMatcher(None, key, prior).ratio() >= 0.94
            for prior in normalized_unique
        )
        if near_duplicate:
            continue
        seen.add(key)
        normalized_unique.append(key)
        unique.append(item)
    return unique


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"\s+", " ", value).strip().lower())


def _ground_requirements(requirements: list[ExtractedRequirement], chunks: list[dict[str, str | int]]) -> list[ExtractedRequirement]:
    by_id = {str(c["id"]): re.sub(r"\s+", " ", str(c["text"])).strip() for c in chunks}
    grounded: list[ExtractedRequirement] = []
    for item in requirements:
        if any(chunk_id not in by_id for chunk_id in item.source_chunk_ids):
            continue
        quote = _normalize(item.source_quote)
        cited_texts = [by_id[chunk_id] for chunk_id in item.source_chunk_ids]
        exact = next((text for text in cited_texts if quote and quote in _normalize(text)), None)
        if exact:
            grounded.append(item)
            continue
        sentences = [s.strip() for text in cited_texts for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) >= 20]
        if not sentences:
            continue
        best = max(sentences, key=lambda sentence: SequenceMatcher(None, quote, _normalize(sentence)).ratio())
        score = SequenceMatcher(None, quote, _normalize(best)).ratio()
        if score >= 0.55:
            item.source_quote = best[:500]
            item.confidence = min(item.confidence, 0.75)
            grounded.append(item)
    return grounded


def _demo_extract(chunks: list[dict[str, str | int]]) -> list[ExtractedRequirement]:
    signal = re.compile(r"\b(shall|must|should|will|requires?|need(?:s|ed)? to|user can|system can)\b", re.I)
    candidates = [c for c in chunks if signal.search(str(c["text"]))] or chunks
    results: list[ExtractedRequirement] = []
    for c in candidates[:8]:
        text = str(c["text"]).strip()
        sentence = re.split(r"(?<=[.!?])\s+", text)[0][:500]
        title = " ".join(re.sub(r"^(the )?(system|solution|business|user)\s+", "", sentence, flags=re.I).split()[:9]).rstrip(".,")
        results.append(ExtractedRequirement(
            title=title.capitalize() or "Business requirement",
            statement=sentence,
            requirement_type="integration" if re.search(r"integrat|interface|API", sentence, re.I) else "functional",
            priority="must" if re.search(r"\b(must|shall)\b", sentence, re.I) else "should",
            rationale="Extracted from an explicit requirement signal in the BRD.",
            acceptance_criteria=[f"Given the relevant SAP process, when the described scenario occurs, then {sentence[:220].rstrip('.').lower()}."],
            source_chunk_ids=[str(c["id"])], source_quote=sentence[:280], confidence=0.72,
        ))
    return results
