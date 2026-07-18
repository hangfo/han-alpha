from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hanalpha.evidence.extractors import DeterministicEvidenceExtractor
from hanalpha.evidence.models import (
    CitationDraft,
    ClaimDraft,
    ClaimType,
    EvidenceDocument,
    ExtractionEnvelope,
    ExtractionResult,
    ProviderCallMetadata,
)
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
        expired = service.snapshot(as_of=now + timedelta(days=121))
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
    config_hash = "3" * 64
    task_type = "claim_extraction"

    async def extract(self, document):
        raise TimeoutError("fixture timeout")


class StaticExtractor:
    extractor_id = "static-fixture"
    version = "1"
    model_id = "static"
    prompt_hash = "4" * 64
    schema_hash = "5" * 64
    task_type = "claim_extraction"

    def __init__(self, draft: ClaimDraft, *, config_hash: str = "6" * 64) -> None:
        self.draft = draft
        self.config_hash = config_hash

    async def extract(self, document):
        return ExtractionEnvelope(
            result=ExtractionResult(abstain=False, claims=(self.draft,)),
            call=ProviderCallMetadata(provider="fixture", actual_model="static"),
        )


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
        {"document_id": document.document_id, "task_type": "claim_extraction"}
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


@pytest.mark.asyncio
async def test_backend_resolves_repeated_quote_and_failed_span_is_atomic(tmp_path) -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    content = "raised guidance; later raised guidance"
    draft = ClaimDraft(
        claim_type=ClaimType.GUIDANCE_RAISE,
        value="raised",
        effective_at=now,
        confidence=0.8,
        citations=(CitationDraft(quote="raised guidance", occurrence_hint=2),),
    )
    store = EvidenceStore(tmp_path / "evidence.sqlite3")
    try:
        service = EvidenceService(store, StaticExtractor(draft))
        await service.ingest(_document(now, content), as_of=now)
        claim = service.snapshot(as_of=now).claims[0]
        assert claim.spans[0].start == content.rfind("raised guidance")

        bad_draft = draft.model_copy(
            update={"citations": (CitationDraft(quote="fabricated quote"),)}
        )
        bad_service = EvidenceService(store, StaticExtractor(bad_draft, config_hash="7" * 64))
        with pytest.raises(EvidenceIntegrityError, match="does not resolve"):
            await bad_service.ingest(
                _document(now, "a different filing", uri="bad-span"), as_of=now
            )
        assert len(store.claims_as_of(now)) == 1
        assert store.connection.execute("SELECT COUNT(*) FROM extraction_cache").fetchone()[0] == 1
        failed = store.connection.execute(
            "SELECT status, error_type FROM model_call_attempts WHERE status='failed'"
        ).fetchone()
        assert tuple(failed) == ("failed", "EvidenceIntegrityError")
    finally:
        store.close()


@pytest.mark.asyncio
async def test_scope_prevents_false_contradiction_and_config_changes_cache(tmp_path) -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    store = EvidenceStore(tmp_path / "evidence.sqlite3")
    try:
        raised = ClaimDraft(
            claim_type=ClaimType.GUIDANCE_RAISE,
            value="raised",
            effective_at=now,
            confidence=0.8,
            citations=(CitationDraft(quote="raised guidance"),),
            segment="cloud",
        )
        cut = ClaimDraft(
            claim_type=ClaimType.GUIDANCE_CUT,
            value="cut",
            effective_at=now,
            confidence=0.8,
            citations=(CitationDraft(quote="cut guidance"),),
            segment="retail",
        )
        await EvidenceService(store, StaticExtractor(raised)).ingest(
            _document(now, "raised guidance", uri="cloud"), as_of=now
        )
        service = EvidenceService(store, StaticExtractor(cut, config_hash="7" * 64))
        await service.ingest(_document(now, "cut guidance", uri="retail"), as_of=now)
        assert service.snapshot(as_of=now).contradictions == ()

        shared = _document(now, "raised guidance", uri="cache-config")
        await EvidenceService(store, StaticExtractor(raised, config_hash="8" * 64)).ingest(
            shared, as_of=now
        )
        await EvidenceService(store, StaticExtractor(raised, config_hash="9" * 64)).ingest(
            shared, as_of=now
        )
        assert store.connection.execute("SELECT COUNT(*) FROM extraction_cache").fetchone()[0] == 4
    finally:
        store.close()
