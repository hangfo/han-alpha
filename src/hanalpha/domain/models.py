from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hanalpha.domain.enums import MarketRegime, OrderStatus, Side, SignalAction


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, validate_assignment=True)


class Bar(StrictModel):
    symbol: str = Field(min_length=1, max_length=20)
    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_ohlc(self) -> Bar:
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be the maximum OHLC value")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be the minimum OHLC value")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return self


class Quote(StrictModel):
    symbol: str
    timestamp: datetime
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)
    last: float = Field(gt=0)
    bid_size: float = Field(ge=0, default=0)
    ask_size: float = Field(ge=0, default=0)

    @model_validator(mode="after")
    def validate_spread(self) -> Quote:
        if self.ask < self.bid:
            raise ValueError("ask cannot be below bid")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return self

    def age_seconds(self, now: datetime | None = None) -> float:
        ref = now or utc_now()
        return max(0.0, (ref - self.timestamp).total_seconds())


class Evidence(StrictModel):
    evidence_id: str = Field(min_length=3, max_length=120)
    source: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    observed_at: datetime
    available_at: datetime
    payload_hash: str = Field(min_length=8, max_length=128)
    summary: str = Field(min_length=1, max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_times(self) -> Evidence:
        if self.observed_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("evidence timestamps must be timezone-aware")
        if self.available_at > self.observed_at:
            raise ValueError("available_at cannot be later than observed_at")
        return self


class Catalyst(StrictModel):
    symbol: str
    category: str
    score: float = Field(ge=0, le=1)
    direction: SignalAction
    published_at: datetime
    available_at: datetime
    headline: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_availability(self) -> Catalyst:
        if self.published_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("catalyst timestamps must be timezone-aware")
        if self.available_at < self.published_at:
            raise ValueError("available_at cannot precede published_at")
        return self


class Signal(StrictModel):
    signal_id: str
    symbol: str
    strategy: str
    action: SignalAction
    generated_at: datetime
    confidence: float = Field(ge=0, le=1)
    reference_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    target_price: float = Field(gt=0)
    score_components: dict[str, float] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_trade_geometry(self) -> Signal:
        if self.action == SignalAction.BUY:
            if not self.stop_price < self.reference_price < self.target_price:
                raise ValueError("BUY signal requires stop < reference < target")
        elif (
            self.action == SignalAction.SELL
            and not self.target_price < self.reference_price < self.stop_price
        ):
            raise ValueError("SELL signal requires target < reference < stop")
        return self


class AgentAssessment(StrictModel):
    agent_name: str
    action: SignalAction
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(default_factory=list)
    invalidators: list[str] = Field(default_factory=list)
    veto: bool = False


class RegimeSnapshot(StrictModel):
    regime: MarketRegime
    timestamp: datetime
    risk_multiplier: float = Field(ge=0, le=1.5)
    max_gross_exposure: float = Field(ge=0, le=1.5)
    allowed_strategies: list[str]
    metrics: dict[str, float | str]


class TradePlan(StrictModel):
    plan_id: str
    signal_id: str
    symbol: str
    strategy: str
    side: Side
    created_at: datetime
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    target_price: float = Field(gt=0)
    quantity: int = Field(gt=0)
    max_holding_bars: int = Field(gt=0, default=390)
    evidence_ids: list[str] = Field(default_factory=list)
    invalidators: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=8, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def notional(self) -> float:
        return self.entry_price * self.quantity

    @property
    def risk_dollars(self) -> float:
        return abs(self.entry_price - self.stop_price) * self.quantity


class RiskDecision(StrictModel):
    approved: bool
    reason_codes: list[str]
    approved_quantity: int = Field(ge=0)
    risk_dollars: float = Field(ge=0)
    gross_exposure_after: float = Field(ge=0)
    reviewed_at: datetime = Field(default_factory=utc_now)


class OrderRequest(StrictModel):
    order_id: str
    plan_id: str
    symbol: str
    side: Side
    quantity: int = Field(gt=0)
    limit_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    target_price: float = Field(gt=0)
    idempotency_key: str
    status: OrderStatus = OrderStatus.PROPOSED
    created_at: datetime = Field(default_factory=utc_now)


class OrderEvent(StrictModel):
    order_id: str
    status: OrderStatus
    timestamp: datetime = Field(default_factory=utc_now)
    filled_quantity: int = Field(ge=0, default=0)
    remaining_quantity: int = Field(ge=0, default=0)
    average_fill_price: float | None = Field(default=None, gt=0)
    message: str = ""
    broker_order_id: str | None = None


class Position(StrictModel):
    symbol: str
    quantity: int
    average_cost: float = Field(gt=0)
    mark_price: float = Field(gt=0)
    sector: str = "UNKNOWN"

    @property
    def market_value(self) -> float:
        return self.quantity * self.mark_price

    @property
    def unrealized_pnl(self) -> float:
        return self.quantity * (self.mark_price - self.average_cost)


class AccountSnapshot(StrictModel):
    timestamp: datetime = Field(default_factory=utc_now)
    net_liquidation: float = Field(gt=0)
    cash: float
    buying_power: float = Field(ge=0)
    daily_pnl: float = 0
    peak_net_liquidation: float = Field(gt=0)
    positions: list[Position] = Field(default_factory=list)
    connected: bool = True

    @property
    def gross_exposure(self) -> float:
        return sum(abs(p.market_value) for p in self.positions) / self.net_liquidation

    @property
    def drawdown_pct(self) -> float:
        if self.peak_net_liquidation <= 0:
            return 0
        return max(0.0, (self.peak_net_liquidation - self.net_liquidation) / self.peak_net_liquidation)


class Fill(StrictModel):
    order_id: str
    symbol: str
    side: Side
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    commission: float = Field(ge=0)
    timestamp: datetime = Field(default_factory=utc_now)


class BacktestMetrics(StrictModel):
    total_return: float
    annualized_return: float
    sharpe: float
    max_drawdown: float
    profit_factor: float
    win_rate: float
    trades: int
    ending_equity: float


class Money(StrictModel):
    amount: Decimal
    currency: str = "USD"

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()
