from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hanalpha.evidence.extractors import DeterministicEvidenceExtractor
from hanalpha.evidence.models import EvidenceDocument
from hanalpha.evidence.service import EvidenceIntegrityError, EvidenceService
from hanalpha.evidence.store import EvidenceBudgetPolicy, EvidenceStore
from hanalpha.simulation.events import canonical_hash


def _document(now: datetime, content: str, *, uri: str = "doc-1") -> EvidenceDocument:
    return EvidenceDocument.create(
        entity_id="inst-alpha",
        source="fixture-filing",
        source_uri=uri,
        observed_at=now - timedelta(minutes=2),
        effective_at=now - timedelta(minutes=2),
        available_at=now - timedelta(minutes=1),
        ingested_at=now,
        content=content,
    )


@pytest.mark.asyncio
async def test_evidence_cache_expiry_and_contradiction_graph(tmp_path) -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    store = EvidenceStore(tmp_path / "evidence.sqlite3")
    service = EvidenceService(store, DeterministicEvidenceExtractor())
    try:
        first = _document(now, "Management raised guidance for the year.")
        assert not (await service.ingest(first, as_of=now)).abstain
        assert await service.ingest(first, as_of=now) == await service.ingest(first, as_of=now)
        second = _document(now, "Management cut guidance after demand weakened.", uri="doc-2")
        await service.ingest(second, as_of=now)
        snapshot = service.snapshot(as_of=now)
        assert len(snapshot.claims) == 2
        assert len(snapshot.contradictions) == 1
        expired = service.snapshot(as_of=now + timedelta(days=91))
        assert expired.claims == ()
    finally:
        store.close()


@pytest.mark.asyncio
async def test_future_document_and_budget_fail_closed(tmp_path) -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    store = EvidenceStore(tmp_path / "evidence.sqlite3")
    service = EvidenceService(
        store,
        DeterministicEvidenceExtractor(),
        EvidenceBudgetPolicy(max_documents_per_entity_day=1, max_document_characters=100),
    )
    try:
        future = _document(now + timedelta(days=1), "raised guidance")
        with pytest.raises(EvidenceIntegrityError, match="future"):
            await service.ingest(future, as_of=now)
        await service.ingest(_document(now, "raised guidance"), as_of=now)
        with pytest.raises(RuntimeError, match="budget"):
            await service.ingest(_document(now, "cut guidance", uri="doc-2"), as_of=now)
    finally:
        store.close()


class FailingExtractor:
    extractor_id = "failing-fixture"
    version = "1"
    model_id = "fake"
    prompt_hash = "1" * 64
    schema_hash = "2" * 64

    async def extract(self, document):
        raise TimeoutError("fixture timeout")


@pytest.mark.asyncio
async def test_failed_model_attempt_is_persisted_and_consumes_budget(tmp_path) -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    store = EvidenceStore(tmp_path / "evidence.sqlite3")
    service = EvidenceService(
        store,
        FailingExtractor(),
        EvidenceBudgetPolicy(max_calls_per_event=1),
    )
    document = _document(now, "raised guidance")
    event_key = canonical_hash(
        {"document_id": document.document_id, "extractor": "failing-fixture"}
    )
    try:
        with pytest.raises(TimeoutError):
            await service.ingest(document, as_of=now)
        attempts = store.call_attempts(event_key)
        assert len(attempts) == 1
        assert attempts[0]["status"] == "failed"
        assert attempts[0]["error_type"] == "TimeoutError"
        with pytest.raises(RuntimeError, match="budget"):
            await service.ingest(document, as_of=now)
    finally:
        store.close()
