import threading
import time

from app.schemas import ExtractedRequirement
from app.services import requirement_intelligence as service
from app.services.openai_support import Usage


def test_requirement_batches_run_concurrently_and_keep_source_order(monkeypatch):
    active = 0
    peak_active = 0
    lock = threading.Lock()

    def fake_extract(_client, batch, label, _progress):
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        time.sleep(0.06)
        chunk_id = str(batch[0]["id"])
        with lock:
            active -= 1
        requirement = ExtractedRequirement(
            title=f"Requirement {chunk_id}", statement=f"The system must process item {chunk_id}.",
            requirement_type="functional", priority="must", rationale="Test fixture",
            acceptance_criteria=[f"Given item {chunk_id}, when processed, then it succeeds."],
            source_chunk_ids=[chunk_id], source_quote=f"The system must process item {chunk_id}.", confidence=0.9,
        )
        return [requirement], [Usage(model="test", input_tokens=1, output_tokens=1, total_tokens=2)]

    monkeypatch.setattr(service, "_extract_batch", fake_extract)
    batches = [[{"id": str(index), "locator": f"Page {index}", "text": f"The system must process item {index}."}]
               for index in range(1, 5)]

    requirements, usages = service._extract_batches(object(), batches, None, workers=3)

    assert peak_active >= 2
    assert [item.source_chunk_ids[0] for item in requirements] == ["1", "2", "3", "4"]
    assert sum(item.total_tokens for item in usages) == 8


def test_source_limit_fails_instead_of_silently_truncating(monkeypatch):
    monkeypatch.setattr(service.settings, "openai_max_source_characters", 20)
    chunks = [
        {"id": "1", "locator": "Page 1", "text": "A" * 15},
        {"id": "2", "locator": "Page 2", "text": "B" * 15},
    ]

    try:
        service._limit_source(chunks)
    except service.AIServiceError as exc:
        assert "partial coverage" in str(exc)
    else:
        raise AssertionError("Expected source coverage guard to fail")


def test_batch_limit_fails_instead_of_dropping_later_batches(monkeypatch):
    monkeypatch.setattr(service.settings, "openai_requirements_batch_characters", 110)
    monkeypatch.setattr(service.settings, "openai_requirements_max_batches", 2)
    chunks = [
        {"id": str(index), "locator": f"Page {index}", "text": "X" * 20}
        for index in range(1, 5)
    ]

    try:
        service._make_batches(chunks)
    except service.AIServiceError as exc:
        assert "silently ignoring source content" in str(exc)
    else:
        raise AssertionError("Expected batch coverage guard to fail")
