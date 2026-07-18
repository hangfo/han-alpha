from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from hanalpha.evidence.extractors import EvidenceExtractor
from hanalpha.evidence.models import (
    ClaimType,
    ContradictionEdge,
    EvidenceClaim,
    EvidenceDocument,
    EvidenceSnapshot,
    ExtractionResult,
    SourceSpan,
)
from hanalpha.evidence.store import EvidenceBudgetPolicy, EvidenceStore
from hanalpha.simulation.events import canonical_hash

_OPPOSITES = {
    frozenset({ClaimType.GUIDANCE_RAISE, ClaimType.GUIDANCE_CUT}),
    frozenset({ClaimType.DEMAND_STRENGTH, ClaimType.DEMAND_WEAKNESS}),
}


class EvidenceIntegrityError(RuntimeError):
    pass


class ClaimExpiryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    guidance_days: int = Field(default=120, gt=0)
    earnings_surprise_days: int = Field(default=30, gt=0)
    contract_award_days: int = Field(default=365, gt=0)
    supply_constraint_days: int = Field(default=90, gt=0)
    demand_days: int = Field(default=60, gt=0)
    accounting_risk_days: int = Field(default=365, gt=0)

    def expires_at(self, claim_type: ClaimType, available_at: datetime) -> datetime:
        days = {
            ClaimType.GUIDANCE_RAISE: self.guidance_days,
            ClaimType.GUIDANCE_CUT: self.guidance_days,
            ClaimType.EARNINGS_SURPRISE: self.earnings_surprise_days,
            ClaimType.CONTRACT_AWARD: self.contract_award_days,
            ClaimType.SUPPLY_CONSTRAINT: self.supply_constraint_days,
            ClaimType.DEMAND_STRENGTH: self.demand_days,
            ClaimType.DEMAND_WEAKNESS: self.demand_days,
            ClaimType.ACCOUNTING_RISK: self.accounting_risk_days,
        }[claim_type]
        return available_at + timedelta(days=days)


class EvidenceService:
    def __init__(
        self,
        store: EvidenceStore,
        extractor: EvidenceExtractor,
        policy: EvidenceBudgetPolicy | None = None,
        expiry_policy: ClaimExpiryPolicy | None = None,
    ) -> None:
        self.store = store
        self.extractor = extractor
        self.policy = policy or EvidenceBudgetPolicy()
        self.expiry_policy = expiry_policy or ClaimExpiryPolicy()

    async def ingest(self, document: EvidenceDocument, *, as_of: datetime) -> ExtractionResult:
        if document.available_at > as_of:
            raise EvidenceIntegrityError("future document is unavailable")
        self.store.put_document(document, self.policy)
        cache_key = canonical_hash(
            {
                "document_hash": document.content_hash,
                "extractor_config_hash": self.extractor.config_hash,
            }
        )
        cached = self.store.cached(cache_key)
        if cached is not None:
            return cached
        event_key = canonical_hash(
            {"document_id": document.document_id, "task_type": self.extractor.task_type}
        )
        attempt_id = self.store.reserve_call(
            event_key,
            self.policy,
            cache_key=cache_key,
            extractor_id=self.extractor.extractor_id,
            extractor_config_hash=self.extractor.config_hash,
            at=as_of,
        )
        try:
            envelope = await self.extractor.extract(document)
            result = envelope.result
            if len(result.claims) > self.policy.max_claims_per_document:
                raise EvidenceIntegrityError("claim budget exceeded")
            claims = self._materialize(document, result)
            existing = self.store.claims_as_of(as_of)
            edges = self._contradictions((*existing, *claims))
            self.store.finalize_extraction(
                attempt_id,
                cache_key=cache_key,
                result=result,
                claims=claims,
                edges=edges,
                call=envelope.call,
                at=as_of,
            )
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
            spans = tuple(
                self._resolve_span(document, citation.quote, citation.occurrence_hint)
                for citation in draft.citations
            )
            expires_at = self.expiry_policy.expires_at(draft.claim_type, document.available_at)
            identity = {
                "entity_id": document.entity_id,
                "claim_type": draft.claim_type,
                "value": draft.value,
                "effective_at": draft.effective_at,
                "available_at": document.available_at,
                "document_id": document.document_id,
                "spans": [span.model_dump(mode="json") for span in spans],
                "extractor": self.extractor.extractor_id,
                "version": self.extractor.version,
                "scope": {
                    "subject": draft.subject,
                    "metric": draft.metric,
                    "segment": draft.segment,
                    "geography": draft.geography,
                    "fiscal_period": draft.fiscal_period,
                    "time_horizon": draft.time_horizon,
                },
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
                    expires_at=expires_at,
                    source_document_id=document.document_id,
                    spans=spans,
                    extractor_id=self.extractor.extractor_id,
                    extractor_version=self.extractor.version,
                    confidence=draft.confidence,
                    invalidation_conditions=draft.invalidation_conditions,
                    subject=draft.subject,
                    metric=draft.metric,
                    segment=draft.segment,
                    geography=draft.geography,
                    fiscal_period=draft.fiscal_period,
                    time_horizon=draft.time_horizon,
                )
            )
        return tuple(claims)

    @staticmethod
    def _resolve_span(document: EvidenceDocument, quote: str, occurrence_hint: int) -> SourceSpan:
        starts: list[int] = []
        cursor = 0
        while True:
            start = document.content.find(quote, cursor)
            if start < 0:
                break
            starts.append(start)
            cursor = start + max(1, len(quote))
        if not starts or occurrence_hint > len(starts):
            raise EvidenceIntegrityError("claim quote does not resolve in frozen document")
        start = starts[occurrence_hint - 1]
        end = start + len(quote)
        return SourceSpan(
            document_id=document.document_id,
            start=start,
            end=end,
            text_hash=canonical_hash({"text": document.content[start:end]}),
        )

    @staticmethod
    def _contradictions(
        claims: tuple[EvidenceClaim, ...],
    ) -> tuple[ContradictionEdge, ...]:
        edges: dict[str, ContradictionEdge] = {}
        for index, left in enumerate(claims):
            for right in claims[index + 1 :]:
                if left.entity_id != right.entity_id:
                    continue
                left_scope = (
                    left.subject,
                    left.metric,
                    left.segment,
                    left.geography,
                    left.fiscal_period,
                    left.time_horizon,
                )
                right_scope = (
                    right.subject,
                    right.metric,
                    right.segment,
                    right.geography,
                    right.fiscal_period,
                    right.time_horizon,
                )
                if left_scope != right_scope:
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
