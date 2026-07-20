from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hanalpha.domain.enums import Side
from hanalpha.pit.models import HASH_PATTERN, require_aware
from hanalpha.simulation.events import canonical_hash


class ReservationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PARTIALLY_CONSUMED = "PARTIALLY_CONSUMED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    RECONCILIATION_HOLD = "RECONCILIATION_HOLD"


class ExecutionStatus(StrEnum):
    PROPOSED = "PROPOSED"
    RISK_RESERVED = "RISK_RESERVED"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    OUTBOXED = "OUTBOXED"
    SUBMITTING = "SUBMITTING"
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCEL_UNKNOWN = "CANCEL_UNKNOWN"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    DELIVERED = "DELIVERED"
    UNKNOWN = "UNKNOWN"


class BrokerEventType(StrEnum):
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILL = "FILL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    COMMISSION = "COMMISSION"


class DecisionCapsule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str = Field(pattern=HASH_PATTERN)
    decision_snapshot_id: str = Field(pattern=HASH_PATTERN)
    market_snapshot_id: str = Field(pattern=HASH_PATTERN)
    evidence_snapshot_id: str | None = Field(default=None, pattern=HASH_PATTERN)
    evidence_review_id: str | None = Field(default=None, pattern=HASH_PATTERN)
    strategy_id: str
    strategy_version: str
    entity_id: str
    input_hash: str = Field(pattern=HASH_PATTERN)
    signal_hash: str = Field(pattern=HASH_PATTERN)
    risk_policy_hash: str = Field(pattern=HASH_PATTERN)
    risk_decision_hash: str = Field(pattern=HASH_PATTERN)
    config_hash: str = Field(pattern=HASH_PATTERN)
    created_at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> DecisionCapsule:
        require_aware(self.created_at, "created_at")
        if (self.evidence_snapshot_id is None) != (self.evidence_review_id is None):
            raise ValueError("evidence snapshot and review must be bound together")
        return self

    @property
    def capsule_hash(self) -> str:
        return canonical_hash(self)


class RiskReservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reservation_id: str = Field(pattern=HASH_PATTERN)
    decision_id: str = Field(pattern=HASH_PATTERN)
    account_id: str
    instrument_id: str
    cash_reserved: Decimal = Field(ge=0)
    notional_reserved: Decimal = Field(ge=0)
    risk_reserved: Decimal = Field(ge=0)
    account_notional_capacity: Decimal = Field(gt=0)
    quantity_reserved: int = Field(gt=0)
    quantity_consumed: int = Field(default=0, ge=0)
    status: ReservationStatus = ReservationStatus.ACTIVE
    expires_at: datetime
    version: int = Field(default=1, gt=0)
    created_at: datetime
    released_at: datetime | None = None

    @model_validator(mode="after")
    def validate_reservation(self) -> RiskReservation:
        for name in ("expires_at", "created_at"):
            require_aware(getattr(self, name), name)
        if self.released_at is not None:
            require_aware(self.released_at, "released_at")
        if self.expires_at <= self.created_at:
            raise ValueError("reservation expiry must follow creation")
        if self.quantity_consumed > self.quantity_reserved:
            raise ValueError("reservation over-consumed")
        return self


class ExecutionIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_id: str = Field(pattern=HASH_PATTERN)
    decision_id: str = Field(pattern=HASH_PATTERN)
    reservation_id: str = Field(pattern=HASH_PATTERN)
    client_order_key: str = Field(pattern=HASH_PATTERN)
    account_id: str
    instrument_id: str
    side: Side
    order_type: str = "LIMIT"
    quantity: int = Field(gt=0)
    limit_price: Decimal = Field(gt=0)
    stop_price: Decimal = Field(gt=0)
    target_price: Decimal = Field(gt=0)
    time_in_force: str = "DAY"
    session: str = "REGULAR"
    status: ExecutionStatus
    version: int = Field(default=1, gt=0)
    created_at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> ExecutionIntent:
        require_aware(self.created_at, "created_at")
        return self

    @classmethod
    def create(
        cls,
        *,
        capsule: DecisionCapsule,
        reservation: RiskReservation,
        side: Side,
        quantity: int,
        limit_price: Decimal,
        stop_price: Decimal,
        target_price: Decimal,
        approval_required: bool,
    ) -> ExecutionIntent:
        economics = {
            "decision_id": capsule.decision_id,
            "account_id": reservation.account_id,
            "instrument_id": reservation.instrument_id,
            "side": side,
            "quantity": quantity,
            "order_type": "LIMIT",
            "limit_price": str(limit_price),
            "stop_price": str(stop_price),
            "target_price": str(target_price),
            "time_in_force": "DAY",
            "session": "REGULAR",
        }
        client_key = canonical_hash(economics)
        return cls(
            intent_id=canonical_hash(
                {"client_order_key": client_key, "reservation": reservation.reservation_id}
            ),
            decision_id=capsule.decision_id,
            reservation_id=reservation.reservation_id,
            client_order_key=client_key,
            account_id=reservation.account_id,
            instrument_id=reservation.instrument_id,
            side=side,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            target_price=target_price,
            status=(
                ExecutionStatus.APPROVAL_PENDING if approval_required else ExecutionStatus.APPROVED
            ),
            created_at=capsule.created_at,
        )


class OutboxCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: str = Field(pattern=HASH_PATTERN)
    intent_id: str = Field(pattern=HASH_PATTERN)
    client_order_key: str = Field(pattern=HASH_PATTERN)
    command_type: str = "SUBMIT"
    payload_hash: str = Field(pattern=HASH_PATTERN)
    status: OutboxStatus
    fencing_token: int | None = Field(default=None, gt=0)
    created_at: datetime


class BrokerEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    broker_event_id: str = Field(pattern=HASH_PATTERN)
    broker_order_id: str
    client_order_key: str = Field(pattern=HASH_PATTERN)
    event_type: BrokerEventType
    sequence: int = Field(gt=0)
    filled_quantity: int = Field(default=0, ge=0)
    fill_price: Decimal | None = Field(default=None, gt=0)
    commission: Decimal = Field(default=Decimal("0"), ge=0)
    occurred_at: datetime
    received_at: datetime
    raw_payload_hash: str = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_times(self) -> BrokerEvent:
        require_aware(self.occurred_at, "occurred_at")
        require_aware(self.received_at, "received_at")
        return self


class ExecutionLease(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lease_name: str
    owner_id: str
    fencing_token: int = Field(gt=0)
    acquired_at: datetime
    expires_at: datetime


class BrokerOrderTruth(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    broker_order_id: str
    client_order_key: str = Field(pattern=HASH_PATTERN)
    instrument_id: str
    side: Side
    quantity: int
    filled_quantity: int
    status: str
    perm_id: str | None = None
    parent_client_order_key: str | None = None
    protection_quantity: int = Field(default=0, ge=0)


class BrokerProtectionTruth(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    protection_order_id: str
    parent_client_order_key: str = Field(pattern=HASH_PATTERN)
    protection_type: str
    quantity: int = Field(ge=0)
    active: bool = True


class BrokerSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: datetime
    cash: Decimal
    settled_cash: Decimal | None = None
    buying_power: Decimal | None = None
    accrued_cash: Decimal | None = None
    base_currency: str = "USD"
    currency_balances: dict[str, Decimal] = Field(default_factory=dict)
    complete: bool = True
    completeness_certificate_id: str | None = None
    observation_id: str | None = None
    session_id: str | None = None
    final_watermark: int = Field(default=0, ge=0)
    semantic_hash: str | None = None
    visibility_scope_hash: str | None = None
    account_hash: str | None = None
    orders_hash: str | None = None
    positions_hash: str | None = None
    executions_hash: str | None = None
    commissions_hash: str | None = None
    protection_hash: str | None = None
    order_snapshot_complete: bool = True
    position_snapshot_complete: bool = True
    execution_snapshot_complete: bool = True
    cash_snapshot_complete: bool = True
    commission_pending_count: int = Field(default=0, ge=0)
    orders: tuple[BrokerOrderTruth, ...]
    positions: dict[str, int]
    protections: dict[str, int]
    events: tuple[BrokerEvent, ...]
    protection_orders: tuple[BrokerProtectionTruth, ...] = ()


class QuoteSnapshot(BaseModel):
    """Immutable, provider-attributed quote evidence used by the arm admission gate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_snapshot_id: str = Field(pattern=HASH_PATTERN)
    symbol: str = Field(min_length=1)
    bid: Decimal = Field(gt=0)
    ask: Decimal = Field(gt=0)
    last: Decimal | None = Field(default=None, gt=0)
    observed_at: datetime
    provider_timestamp: datetime
    provider: str = Field(min_length=1)
    feed_mode: str
    market_phase: str
    raw_hash: str = Field(pattern=HASH_PATTERN)
    freshness_policy_hash: str = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_quote(self) -> QuoteSnapshot:
        require_aware(self.observed_at, "observed_at")
        require_aware(self.provider_timestamp, "provider_timestamp")
        if self.ask < self.bid:
            raise ValueError("quote ask must be greater than or equal to bid")
        return self
