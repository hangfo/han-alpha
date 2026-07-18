from __future__ import annotations

from datetime import datetime

from hanalpha.evidence.extractors import EvidenceExtractor
from hanalpha.evidence.models import (
    ClaimType,
    ContradictionEdge,
    EvidenceClaim,
    EvidenceDocument,
    EvidenceSnapshot,
    ExtractionResult,
)
from hanalpha.evidence.store import EvidenceBudgetPolicy, EvidenceStore
from hanalpha.simulation.events import canonical_hash

_OPPOSITES = {
    frozenset({ClaimType.GUIDANCE_RAISE, ClaimType.GUIDANCE_CUT}),
    frozenset({ClaimType.DEMAND_STRENGTH, ClaimType.DEMAND_WEAKNESS}),
}


class EvidenceIntegrityError(RuntimeError):
    pass


class EvidenceService:
    def __init__(
        self,
        store: EvidenceStore,
        extractor: EvidenceExtractor,
        policy: EvidenceBudgetPolicy | None = None,
    ) -> None:
        self.store = store
        self.extractor = extractor
        self.policy = policy or EvidenceBudgetPolicy()

    async def ingest(self, document: EvidenceDocument, *, as_of: datetime) -> ExtractionResult:
        if document.available_at > as_of:
            raise EvidenceIntegrityError("future document is unavailable")
        self.store.put_document(document, self.policy)
        cache_key = canonical_hash(
            {
                "document_hash": document.content_hash,
                "extractor_schema_hash": self.extractor.schema_hash,
                "model_id": self.extractor.model_id,
                "extractor_version": self.extractor.version,
                "system_prompt_hash": self.extractor.prompt_hash,
                "temperature": 0,
            }
        )
        cached = self.store.cached(cache_key)
        if cached is not None:
            return cached
        event_key = canonical_hash(
            {"document_id": document.document_id, "extractor": self.extractor.extractor_id}
        )
        attempt_id = self.store.reserve_call(
            event_key,
            self.policy,
            cache_key=cache_key,
            extractor_id=self.extractor.extractor_id,
            at=as_of,
        )
        try:
            result = await self.extractor.extract(document)
            if len(result.claims) > self.policy.max_claims_per_document:
                raise EvidenceIntegrityError("claim budget exceeded")
            claims = self._materialize(document, result)
            existing = self.store.claims_as_of(as_of)
            edges = self._contradictions((*existing, *claims))
            self.store.put_claims(claims, edges)
            self.store.put_cache(cache_key, result, as_of)
            self.store.complete_call(attempt_id, at=as_of)
            return result
        except Exception as exc:
            self.store.complete_call(attempt_id, at=as_of, error_type=type(exc).__name__)
            raise

    def snapshot(self, *, as_of: datetime) -> EvidenceSnapshot:
        claims = self.store.claims_as_of(as_of)
        ids = {claim.claim_id for claim in claims}
        edges = self.store.edges_for(ids)
        return EvidenceSnapshot(
            snapshot_id=canonical_hash(
                {
                    "as_of": as_of,
                    "claims": [claim.claim_id for claim in claims],
                    "edges": [edge.edge_id for edge in edges],
                }
            ),
            as_of=as_of,
            claims=claims,
            contradictions=edges,
        )

    def _materialize(
        self, document: EvidenceDocument, result: ExtractionResult
    ) -> tuple[EvidenceClaim, ...]:
        claims: list[EvidenceClaim] = []
        for draft in result.claims:
            if draft.effective_at > draft.expires_at:
                raise EvidenceIntegrityError("claim effective time follows expiry")
            for span in draft.spans:
                if span.document_id != document.document_id or span.end > len(document.content):
                    raise EvidenceIntegrityError("claim cites an invalid document span")
                actual = document.content[span.start : span.end]
                if span.text_hash != canonical_hash({"text": actual}):
                    raise EvidenceIntegrityError("claim span hash mismatch")
            identity = {
                "entity_id": document.entity_id,
                "claim_type": draft.claim_type,
                "value": draft.value,
                "effective_at": draft.effective_at,
                "available_at": document.available_at,
                "document_id": document.document_id,
                "spans": [span.model_dump(mode="json") for span in draft.spans],
                "extractor": self.extractor.extractor_id,
                "version": self.extractor.version,
            }
            claims.append(
                EvidenceClaim(
                    claim_id=canonical_hash(identity),
                    entity_id=document.entity_id,
                    claim_type=draft.claim_type,
                    value=draft.value,
                    unit=draft.unit,
                    effective_at=draft.effective_at,
                    available_at=document.available_at,
                    expires_at=draft.expires_at,
                    source_document_id=document.document_id,
                    spans=draft.spans,
                    extractor_id=self.extractor.extractor_id,
                    extractor_version=self.extractor.version,
                    confidence=draft.confidence,
                    invalidation_conditions=draft.invalidation_conditions,
                )
            )
        return tuple(claims)

    @staticmethod
    def _contradictions(
        claims: tuple[EvidenceClaim, ...],
    ) -> tuple[ContradictionEdge, ...]:
        edges: dict[str, ContradictionEdge] = {}
        for index, left in enumerate(claims):
            for right in claims[index + 1 :]:
                if left.entity_id != right.entity_id:
                    continue
                if frozenset({left.claim_type, right.claim_type}) not in _OPPOSITES:
                    continue
                edge_id = canonical_hash(
                    {
                        "left": min(left.claim_id, right.claim_id),
                        "right": max(left.claim_id, right.claim_id),
                    }
                )
                edges[edge_id] = ContradictionEdge(
                    edge_id=edge_id,
                    left_claim_id=left.claim_id,
                    right_claim_id=right.claim_id,
                    reason="opposing point-in-time claims require review",
                )
        return tuple(edges[key] for key in sorted(edges))
