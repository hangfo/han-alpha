from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hanalpha.pit.models import HASH_PATTERN, require_aware
from hanalpha.simulation.events import canonical_hash


class DateWindow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_window(self) -> DateWindow:
        require_aware(self.start, "start")
        require_aware(self.end, "end")
        if self.end <= self.start:
            raise ValueError("window end must follow start")
        return self


class ParameterRange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    low: Decimal
    high: Decimal

    @model_validator(mode="after")
    def validate_range(self) -> ParameterRange:
        if self.high < self.low:
            raise ValueError("parameter range high must not be below low")
        return self


class ResearchBudget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_trials: int = Field(gt=0)
    used_trials: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_budget(self) -> ResearchBudget:
        if self.used_trials > self.max_trials:
            raise ValueError("used trials exceed research budget")
        return self

    @property
    def remaining_trials(self) -> int:
        return self.max_trials - self.used_trials


class SuccessCriteria(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    minimum_oos_return: Decimal
    maximum_drawdown: Decimal = Field(ge=0)
    minimum_dsr_probability: Decimal = Field(ge=0, le=1)
    maximum_pbo: Decimal = Field(ge=0, le=1)
    minimum_cost_stress_return: Decimal
    maximum_contribution_share: Decimal = Field(gt=0, le=1)
    minimum_observations: int = Field(ge=30)


class PreregisteredProtocol(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    researcher_id: str = Field(min_length=1)
    hypothesis: str = Field(min_length=1)
    snapshot_id: str = Field(pattern=HASH_PATTERN)
    universe_hash: str = Field(pattern=HASH_PATTERN)
    feature_schema_hash: str = Field(pattern=HASH_PATTERN)
    cost_policy_hash: str = Field(pattern=HASH_PATTERN)
    train: DateWindow
    validation: DateWindow
    test: DateWindow
    parameter_ranges: dict[str, ParameterRange]
    success: SuccessCriteria
    budget: ResearchBudget
    benchmarks: tuple[str, ...]
    purge_bars: int = Field(ge=0)
    embargo_bars: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_windows(self) -> PreregisteredProtocol:
        if self.train.end >= self.validation.start or self.validation.end >= self.test.start:
            raise ValueError("train, validation and test windows must not overlap")
        if not self.benchmarks:
            raise ValueError("at least one benchmark is required")
        return self

    @property
    def protocol_hash(self) -> str:
        payload = self.model_dump(mode="json")
        budget = dict(payload["budget"])
        budget.pop("used_trials", None)
        payload["budget"] = budget
        return canonical_hash(payload)

    @property
    def research_program_id(self) -> str:
        return canonical_hash(
            {
                "name": self.name,
                "researcher_id": self.researcher_id,
                "hypothesis": self.hypothesis,
                "snapshot_id": self.snapshot_id,
                "universe_hash": self.universe_hash,
                "feature_schema_hash": self.feature_schema_hash,
            }
        )

    def consume_trial(self) -> PreregisteredProtocol:
        if self.budget.remaining_trials <= 0:
            raise RuntimeError("research budget exhausted")
        budget = ResearchBudget(
            max_trials=self.budget.max_trials,
            used_trials=self.budget.used_trials + 1,
        )
        return PreregisteredProtocol.model_validate(
            {**self.model_dump(mode="python"), "budget": budget}
        )
