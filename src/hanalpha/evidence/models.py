from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hanalpha.pit.models import HASH_PATTERN, require_aware
from hanalpha.simulation.events import canonical_hash


class ClaimType(StrEnum):
    GUIDANCE_RAISE = "guidance_raise"
    GUIDANCE_CUT = "guidance_cut"
    DEMAND_STRENGTH = "demand_strength"
    DEMAND_WEAKNESS = "demand_weakness"
    SUPPLY_CONSTRAINT = "supply_constraint"
    CONTRACT_AWARD = "contract_award"
    ACCOUNTING_RISK = "accounting_risk"
    EARNINGS_SURPRISE = "earnings_surprise"


class EvidenceDecision(StrEnum):
    ALLOW = "allow"
    VETO = "veto"
    ABSTAIN = "abstain"


class EvidenceDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str = Field(pattern=HASH_PATTERN)
    entity_id: str
    source: str
    source_uri: str
    observed_at: datetime
    effective_at: datetime
    available_at: datetime
    ingested_at: datetime
    content: str = Field(min_length=1)
    content_hash: str = Field(pattern=HASH_PATTERN)

    @classmethod
    def create(
        cls,
        *,
        entity_id: str,
        source: str,
        source_uri: str,
        observed_at: datetime,
        effective_at: datetime,
        available_at: datetime,
        ingested_at: datetime,
        content: str,
    ) -> EvidenceDocument:
        content_hash = canonical_hash({"content": content})
        return cls(
            document_id=canonical_hash(
                {"source": source, "source_uri": source_uri, "content_hash": content_hash}
            ),
            entity_id=entity_id,
            source=source,
            source_uri=source_uri,
            observed_at=observed_at,
            effective_at=effective_at,
            available_at=available_at,
            ingested_at=ingested_at,
            content=content,
            content_hash=content_hash,
        )

    @model_validator(mode="after")
    def validate_times_and_hash(self) -> EvidenceDocument:
        for name in ("observed_at", "effective_at", "available_at", "ingested_at"):
            require_aware(getattr(self, name), name)
        if self.available_at < self.observed_at or self.ingested_at < self.available_at:
            raise ValueError("document knowledge times must be monotonic")
        if self.content_hash != canonical_hash({"content": self.content}):
            raise ValueError("document content hash mismatch")
        return self


class SourceSpan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str = Field(pattern=HASH_PATTERN)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text_hash: str = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_range(self) -> SourceSpan:
        if self.end <= self.start:
            raise ValueError("source span end must follow start")
        return self


class ClaimDraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_type: ClaimType
    value: str = Field(min_length=1, max_length=500)
    unit: str | None = Field(default=None, max_length=50)
    effective_at: datetime
    expires_at: datetime
    confidence: float = Field(ge=0, le=1)
    spans: tuple[SourceSpan, ...] = Field(min_length=1)
    invalidation_conditions: tuple[str, ...] = ()


class ExtractionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    abstain: bool
    abstain_reason: str | None = None
    claims: tuple[ClaimDraft, ...] = ()

    @model_validator(mode="after")
    def validate_abstention(self) -> ExtractionResult:
        if self.abstain and (not self.abstain_reason or self.claims):
            raise ValueError("abstention requires a reason and no claims")
        if not self.abstain and not self.claims:
            raise ValueError("non-abstaining extraction requires claims")
        return self


class EvidenceClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str = Field(pattern=HASH_PATTERN)
    entity_id: str
    claim_type: ClaimType
    value: str
    unit: str | None = None
    effective_at: datetime
    available_at: datetime
    expires_at: datetime
    source_document_id: str = Field(pattern=HASH_PATTERN)
    spans: tuple[SourceSpan, ...]
    extractor_id: str
    extractor_version: str
    confidence: float = Field(ge=0, le=1)
    invalidation_conditions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_times(self) -> EvidenceClaim:
        for name in ("effective_at", "available_at", "expires_at"):
            require_aware(getattr(self, name), name)
        if self.expires_at <= self.available_at:
            raise ValueError("claim must expire after availability")
        return self


class ContradictionEdge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    edge_id: str = Field(pattern=HASH_PATTERN)
    left_claim_id: str = Field(pattern=HASH_PATTERN)
    right_claim_id: str = Field(pattern=HASH_PATTERN)
    reason: str


class EvidenceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str = Field(pattern=HASH_PATTERN)
    as_of: datetime
    claims: tuple[EvidenceClaim, ...]
    contradictions: tuple[ContradictionEdge, ...]

    @model_validator(mode="after")
    def validate_snapshot(self) -> EvidenceSnapshot:
        require_aware(self.as_of, "as_of")
        if any(
            claim.available_at > self.as_of or claim.expires_at <= self.as_of
            for claim in self.claims
        ):
            raise ValueError("snapshot contains unavailable or expired claims")
        claim_ids = {claim.claim_id for claim in self.claims}
        if any(
            edge.left_claim_id not in claim_ids or edge.right_claim_id not in claim_ids
            for edge in self.contradictions
        ):
            raise ValueError("contradiction references claim outside snapshot")
        return self
