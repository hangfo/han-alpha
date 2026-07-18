from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hanalpha.domain.enums import Side
from hanalpha.pit.models import (
    HASH_PATTERN,
    CorporateActionRecord,
    CorporateActionType,
    PriceBarRecord,
    require_aware,
)


def canonical_hash(payload: Any) -> str:
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json", exclude_none=True)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


class SimulationBar(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str = Field(pattern=HASH_PATTERN)
    instrument_id: str
    source_record_id: str
    source_revision: int = Field(ge=1)
    event_time: datetime
    available_at: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    halted: bool = False

    @model_validator(mode="after")
    def validate_bar(self) -> SimulationBar:
        require_aware(self.event_time, "event_time")
        require_aware(self.available_at, "available_at")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be the maximum OHLC value")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be the minimum OHLC value")
        return self

    @classmethod
    def from_record(cls, record: PriceBarRecord) -> SimulationBar:
        return cls(
            snapshot_id=record.snapshot_id,
            instrument_id=record.instrument_id,
            source_record_id=record.source_record_id,
            source_revision=record.source_revision,
            event_time=record.event_time,
            available_at=record.available_at,
            open=record.open,
            high=record.high,
            low=record.low,
            close=record.close,
            volume=record.volume,
        )


class CorporateActionPhase(StrEnum):
    ANNOUNCED = "announced"
    EX_DATE = "ex_date"
    RECORD_DATE = "record_date"
    PAYABLE = "payable"
    EFFECTIVE = "effective"


class SimulationCorporateAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str = Field(pattern=HASH_PATTERN)
    action_id: str
    instrument_id: str
    source_record_id: str
    source_revision: int = Field(ge=1)
    action_type: CorporateActionType
    phase: CorporateActionPhase = CorporateActionPhase.EFFECTIVE
    event_time: datetime
    available_at: datetime
    ratio: Decimal | None = None
    cash_amount: Decimal | None = None

    @model_validator(mode="after")
    def validate_action(self) -> SimulationCorporateAction:
        require_aware(self.event_time, "event_time")
        require_aware(self.available_at, "available_at")
        return self

    @classmethod
    def from_record(cls, record: CorporateActionRecord) -> SimulationCorporateAction:
        return cls(
            snapshot_id=record.snapshot_id,
            action_id=record.record_id,
            instrument_id=record.instrument_id,
            source_record_id=record.source_record_id,
            source_revision=record.source_revision,
            action_type=record.action_type,
            event_time=record.event_time,
            available_at=record.available_at,
            ratio=Decimal(str(record.ratio)) if record.ratio is not None else None,
            cash_amount=(
                Decimal(str(record.cash_amount)) if record.cash_amount is not None else None
            ),
        )


class ReplayFrame(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str = Field(pattern=HASH_PATTERN)
    as_of: datetime
    bars: list[SimulationBar]
    bar_revisions: list[SimulationBar] = Field(default_factory=list)
    actions: list[SimulationCorporateAction] = Field(default_factory=list)
    action_revisions: list[SimulationCorporateAction] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_frame(self) -> ReplayFrame:
        require_aware(self.as_of, "as_of")
        for bar in [*self.bars, *self.bar_revisions]:
            if bar.snapshot_id != self.snapshot_id:
                raise ValueError("frame contains a different snapshot")
            if bar.available_at > self.as_of:
                raise ValueError("frame contains information unavailable at as_of")
        for action in [*self.actions, *self.action_revisions]:
            if action.snapshot_id != self.snapshot_id:
                raise ValueError("frame contains a different snapshot")
            if action.available_at > self.as_of:
                raise ValueError("frame contains information unavailable at as_of")
        return self


class FillEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fill_id: str
    order_id: str
    instrument_id: str
    side: Side
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    commission: float = Field(ge=0)
    occurred_at: datetime
    reason: str
    source_record_id: str = "manual"
    source_revision: int = 1

    @model_validator(mode="after")
    def validate_time(self) -> FillEvent:
        require_aware(self.occurred_at, "occurred_at")
        return self


class DecisionIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str = Field(pattern=HASH_PATTERN)
    snapshot_id: str = Field(pattern=HASH_PATTERN)
    as_of: datetime
    strategy_version: str
    config_hash: str = Field(pattern=HASH_PATTERN)
    input_hash: str = Field(pattern=HASH_PATTERN)
    signal_hash: str = Field(pattern=HASH_PATTERN)
    risk_hash: str = Field(pattern=HASH_PATTERN)

    @classmethod
    def build(
        cls,
        *,
        snapshot_id: str,
        as_of: datetime,
        strategy_version: str,
        config_hash: str,
        input_hash: str,
        signal_hash: str,
        risk_hash: str,
    ) -> DecisionIdentity:
        require_aware(as_of, "as_of")
        identity = {
            "snapshot_id": snapshot_id,
            "as_of": as_of.isoformat(),
            "strategy_version": strategy_version,
            "config_hash": config_hash,
            "input_hash": input_hash,
            "signal_hash": signal_hash,
            "risk_hash": risk_hash,
        }
        return cls(
            decision_id=canonical_hash(identity),
            snapshot_id=snapshot_id,
            as_of=as_of,
            strategy_version=strategy_version,
            config_hash=config_hash,
            input_hash=input_hash,
            signal_hash=signal_hash,
            risk_hash=risk_hash,
        )


class DecisionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: DecisionIdentity
    strategy_id: str
    instrument_id: str
    order_id: str | None
    approved: bool
    reason: str


class EquityPoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: datetime
    net_liquidation: Decimal
    cash: Decimal
    gross_exposure: Decimal

    @model_validator(mode="after")
    def validate_time(self) -> EquityPoint:
        require_aware(self.as_of, "as_of")
        return self
