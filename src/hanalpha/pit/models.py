from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hanalpha.pit.symbology import normalize_ticker

HASH_PATTERN = r"^[0-9a-f]{64}$"


def require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


class CanonicalRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record_type: str
    instrument_id: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    event_time: datetime
    available_at: datetime
    ingested_at: datetime
    valid_from: datetime
    valid_to: datetime | None
    source: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    source_revision: int = Field(ge=1)
    schema_version: str = Field(min_length=1)
    payload_hash: str = Field(pattern=HASH_PATTERN)
    snapshot_id: str = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_temporal_contract(self) -> CanonicalRecord:
        for field in ("event_time", "available_at", "ingested_at", "valid_from"):
            require_aware(getattr(self, field), field)
        if self.valid_to is not None:
            require_aware(self.valid_to, "valid_to")
            if self.valid_to <= self.valid_from:
                raise ValueError("valid_to must be later than valid_from")
        if self.ingested_at < self.available_at:
            raise ValueError("ingested_at must not precede available_at")
        return self


class InstrumentRecord(CanonicalRecord):
    record_type: Literal["instrument"] = "instrument"
    name: str = Field(min_length=1)
    exchange: str = Field(min_length=1)
    asset_type: str = Field(min_length=1)


class SymbolAliasRecord(CanonicalRecord):
    record_type: Literal["symbol_alias"] = "symbol_alias"
    ticker: str = Field(min_length=1)

    @model_validator(mode="after")
    def normalize_alias(self) -> SymbolAliasRecord:
        normalized = normalize_ticker(self.ticker)
        if normalized != self.ticker:
            raise ValueError("ticker must be normalized uppercase without surrounding whitespace")
        return self


class PriceBarRecord(CanonicalRecord):
    record_type: Literal["price_bar"] = "price_bar"
    interval: str = Field(min_length=1)
    open: float
    high: float
    low: float
    close: float
    volume: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_ohlc(self) -> PriceBarRecord:
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be the greatest OHLC value")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be the least OHLC value")
        return self


class CorporateActionType(StrEnum):
    SPLIT = "split"
    DIVIDEND = "dividend"
    DELIST = "delist"
    TICKER_CHANGE = "ticker_change"


class CorporateActionRecord(CanonicalRecord):
    record_type: Literal["corporate_action"] = "corporate_action"
    action_type: CorporateActionType
    ratio: float | None = Field(default=None, gt=0)
    cash_amount: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_action_payload(self) -> CorporateActionRecord:
        if self.action_type == CorporateActionType.SPLIT and self.ratio is None:
            raise ValueError("split action requires ratio")
        if self.action_type == CorporateActionType.DIVIDEND and self.cash_amount is None:
            raise ValueError("dividend action requires cash_amount")
        return self


type Record = Annotated[
    InstrumentRecord | SymbolAliasRecord | PriceBarRecord | CorporateActionRecord,
    Field(discriminator="record_type"),
]


RECORD_MODELS: dict[str, type[CanonicalRecord]] = {
    "instrument": InstrumentRecord,
    "symbol_alias": SymbolAliasRecord,
    "price_bar": PriceBarRecord,
    "corporate_action": CorporateActionRecord,
}


def parse_record(payload: dict[str, object]) -> CanonicalRecord:
    record_type = str(payload.get("record_type", ""))
    model = RECORD_MODELS.get(record_type)
    if model is None:
        raise ValueError(f"unsupported record_type: {record_type}")
    return model.model_validate(payload)
