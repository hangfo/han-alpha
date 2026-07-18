from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hanalpha.evidence.models import EvidenceDecision, EvidenceSnapshot
from hanalpha.pit.models import HASH_PATTERN, require_aware
from hanalpha.simulation.events import canonical_hash


class EvidenceReview(BaseModel):
    """Evidence may only allow, veto, or abstain on an existing quant candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str = Field(pattern=HASH_PATTERN)
    decision_id: str = Field(pattern=HASH_PATTERN)
    entity_id: str = Field(min_length=1)
    evidence_snapshot_id: str = Field(pattern=HASH_PATTERN)
    reviewed_at: datetime
    reviewer_config_hash: str = Field(pattern=HASH_PATTERN)
    decision: EvidenceDecision
    rationale: str = Field(min_length=1)
    claim_ids: tuple[str, ...]
    invalidators: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_veto(self) -> EvidenceReview:
        require_aware(self.reviewed_at, "reviewed_at")
        if self.decision == EvidenceDecision.VETO and not self.invalidators:
            raise ValueError("veto requires a concrete invalidator")
        if self.decision != EvidenceDecision.VETO and self.invalidators:
            raise ValueError("only a veto may carry invalidators")
        return self

    @property
    def review_id(self) -> str:
        return canonical_hash(self)


def validate_review(
    review: EvidenceReview,
    snapshot: EvidenceSnapshot,
    *,
    candidate_id: str,
    decision_id: str,
    entity_id: str,
) -> EvidenceReview:
    if (
        review.candidate_id != candidate_id
        or review.decision_id != decision_id
        or review.entity_id != entity_id
        or review.evidence_snapshot_id != snapshot.snapshot_id
    ):
        raise ValueError("review does not bind to candidate, decision, entity and snapshot")
    if review.reviewed_at < snapshot.as_of:
        raise ValueError("review time precedes evidence snapshot")
    allowed = {claim.claim_id for claim in snapshot.claims}
    if not set(review.claim_ids).issubset(allowed):
        raise ValueError("review fabricated or cited unavailable claims")
    if any(
        claim.entity_id != entity_id
        for claim in snapshot.claims
        if claim.claim_id in review.claim_ids
    ):
        raise ValueError("review cited a claim from another entity")
    return review
