from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hanalpha.metrics.portfolio import EquityPoint, PortfolioMetrics
from hanalpha.pit.models import HASH_PATTERN, require_aware
from hanalpha.simulation.events import canonical_hash
from hanalpha.simulation.portfolio import CashEntry, JournalEntry, PositionLot


class TrialStatus(StrEnum):
    REGISTERED = "registered"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"
    PROMOTED = "promoted"


class WindowRole(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
    COUNTERFACTUAL = "counterfactual"


class TrialAllocation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allocation_id: str = Field(pattern=HASH_PATTERN)
    protocol_hash: str = Field(pattern=HASH_PATTERN)
    research_program_id: str = Field(pattern=HASH_PATTERN)
    trial_number: int = Field(gt=0)
    parameter_point_hash: str = Field(pattern=HASH_PATTERN)
    window_role: WindowRole
    allocated_at: datetime
    experiment_id: str | None = Field(default=None, pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_time(self) -> TrialAllocation:
        require_aware(self.allocated_at, "allocated_at")
        return self


class ExperimentManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str = Field(pattern=HASH_PATTERN)
    code_hash: str = Field(pattern=HASH_PATTERN)
    config_hash: str = Field(pattern=HASH_PATTERN)
    cost_policy_hash: str = Field(pattern=HASH_PATTERN)
    universe_hash: str = Field(pattern=HASH_PATTERN)
    metric_schema_version: str
    seed: int
    strategy_id: str
    strategy_version: str
    hypothesis: str = Field(min_length=1)
    parameters: dict[str, Any]
    counterfactual_of: str | None = Field(default=None, pattern=HASH_PATTERN)
    protocol_hash: str = Field(pattern=HASH_PATTERN)
    trial_allocation_id: str = Field(pattern=HASH_PATTERN)
    parameter_point_hash: str = Field(pattern=HASH_PATTERN)
    window_role: WindowRole
    research_program_id: str = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_parameter_point(self) -> ExperimentManifest:
        if self.parameter_point_hash != canonical_hash(self.parameters):
            raise ValueError("parameter_point_hash does not match parameters")
        return self

    @property
    def experiment_id(self) -> str:
        return canonical_hash(self)


class TrialEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence: int = Field(ge=1)
    experiment_id: str = Field(pattern=HASH_PATTERN)
    status: TrialStatus
    occurred_at: datetime
    result_hash: str | None = Field(default=None, pattern=HASH_PATTERN)
    failure_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_event(self) -> TrialEvent:
        require_aware(self.occurred_at, "occurred_at")
        if self.status == TrialStatus.FAILED and not self.failure_reason:
            raise ValueError("failed trial requires failure_reason")
        if self.status == TrialStatus.COMPLETED and self.result_hash is None:
            raise ValueError("completed trial requires result_hash")
        return self


class TrialView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: str
    manifest: ExperimentManifest
    status: TrialStatus
    failure_reason: str | None
    result_hash: str | None
    event_count: int


class ExperimentResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: str = Field(pattern=HASH_PATTERN)
    event_hash: str = Field(pattern=HASH_PATTERN)
    equity_hash: str = Field(pattern=HASH_PATTERN)
    metrics: PortfolioMetrics
    equity_points: list[EquityPoint]
    fill_count: int = Field(ge=0)
    journal_entries: list[JournalEntry] = Field(default_factory=list)
    cash_entries: list[CashEntry] = Field(default_factory=list)
    position_lots: list[PositionLot] = Field(default_factory=list)

    @property
    def result_hash(self) -> str:
        return canonical_hash(self)


class ArtifactDigest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    sha256: str = Field(pattern=HASH_PATTERN)
    size: int = Field(ge=0)


class ArtifactRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: str = Field(pattern=HASH_PATTERN)
    digest: ArtifactDigest
    relative_path: str = Field(min_length=1)
    created_at: datetime

    @model_validator(mode="after")
    def validate_record(self) -> ArtifactRecord:
        require_aware(self.created_at, "created_at")
        path = self.relative_path.replace("\\", "/")
        if path.startswith("/") or ".." in path.split("/"):
            raise ValueError("relative_path must stay within the artifact root")
        return self
