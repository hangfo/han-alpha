from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hanalpha.evidence.models import EvidenceDecision, EvidenceSnapshot


class EvidenceReview(BaseModel):
    """Evidence may only allow, veto, or abstain on an existing quant candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: EvidenceDecision
    rationale: str = Field(min_length=1)
    claim_ids: tuple[str, ...]
    invalidators: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_veto(self) -> EvidenceReview:
        if self.decision == EvidenceDecision.VETO and not self.invalidators:
            raise ValueError("veto requires a concrete invalidator")
        return self


def validate_review(review: EvidenceReview, snapshot: EvidenceSnapshot) -> EvidenceReview:
    allowed = {claim.claim_id for claim in snapshot.claims}
    if not set(review.claim_ids).issubset(allowed):
        raise ValueError("review fabricated or cited unavailable claims")
    return review
