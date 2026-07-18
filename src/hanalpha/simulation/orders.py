from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hanalpha.domain.enums import Side
from hanalpha.pit.models import require_aware


class OrderKind(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"


class SimulationOrderState(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class IllegalOrderTransition(RuntimeError):
    pass


class DuplicateOrderEvent(RuntimeError):
    pass


class OrderIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str
    decision_id: str
    instrument_id: str
    strategy_id: str
    side: Side
    kind: OrderKind
    quantity: int = Field(gt=0)
    submitted_at: datetime
    earliest_fill_at: datetime
    expires_at: datetime | None = None
    planned_price: float = Field(gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    protective_stop: float | None = Field(default=None, gt=0)
    protective_target: float | None = Field(default=None, gt=0)
    parent_order_id: str | None = None
    oco_group_id: str | None = None
    reduce_only: bool = False

    @model_validator(mode="after")
    def validate_intent(self) -> OrderIntent:
        require_aware(self.submitted_at, "submitted_at")
        require_aware(self.earliest_fill_at, "earliest_fill_at")
        if self.earliest_fill_at < self.submitted_at:
            raise ValueError("earliest_fill_at must not precede submitted_at")
        if self.expires_at is not None:
            require_aware(self.expires_at, "expires_at")
            if self.expires_at <= self.submitted_at:
                raise ValueError("expires_at must be later than submitted_at")
        if self.kind in {OrderKind.LIMIT, OrderKind.STOP_LIMIT} and self.limit_price is None:
            raise ValueError("limit order requires limit_price")
        if self.kind in {OrderKind.STOP_MARKET, OrderKind.STOP_LIMIT} and self.stop_price is None:
            raise ValueError("stop order requires stop_price")
        if (
            self.side == Side.BUY
            and self.protective_stop is not None
            and self.protective_stop >= self.planned_price
        ):
            raise ValueError("buy protective_stop must be below planned_price")
        if (
            self.side == Side.BUY
            and self.protective_target is not None
            and self.protective_target <= self.planned_price
        ):
            raise ValueError("buy protective_target must be above planned_price")
        if self.reduce_only and self.side != Side.SELL:
            raise ValueError("long-only reduce_only orders must sell")
        return self


class TrackedOrder(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: OrderIntent
    state: SimulationOrderState
    filled_quantity: int = Field(ge=0)
    average_fill_price: float | None = Field(default=None, gt=0)
    fill_ids: tuple[str, ...] = ()
    last_event_at: datetime

    @property
    def remaining_quantity(self) -> int:
        return self.intent.quantity - self.filled_quantity

    @classmethod
    def proposed(cls, intent: OrderIntent) -> TrackedOrder:
        return cls(
            intent=intent,
            state=SimulationOrderState.PROPOSED,
            filled_quantity=0,
            last_event_at=intent.submitted_at,
        )

    def accept(self, at: datetime) -> TrackedOrder:
        self._require_state({SimulationOrderState.PROPOSED})
        return self._updated(state=SimulationOrderState.ACCEPTED, last_event_at=at)

    def reject(self, at: datetime) -> TrackedOrder:
        self._require_state({SimulationOrderState.PROPOSED})
        return self._updated(state=SimulationOrderState.REJECTED, last_event_at=at)

    def cancel(self, at: datetime) -> TrackedOrder:
        self._require_state({SimulationOrderState.ACCEPTED, SimulationOrderState.PARTIALLY_FILLED})
        return self._updated(state=SimulationOrderState.CANCELLED, last_event_at=at)

    def expire(self, at: datetime) -> TrackedOrder:
        self._require_state({SimulationOrderState.ACCEPTED, SimulationOrderState.PARTIALLY_FILLED})
        return self._updated(state=SimulationOrderState.EXPIRED, last_event_at=at)

    def apply_fill(
        self, *, fill_id: str, quantity: int, price: float, at: datetime
    ) -> TrackedOrder:
        self._require_state({SimulationOrderState.ACCEPTED, SimulationOrderState.PARTIALLY_FILLED})
        if fill_id in self.fill_ids:
            raise DuplicateOrderEvent(fill_id)
        if quantity <= 0 or quantity > self.remaining_quantity:
            raise IllegalOrderTransition("fill quantity exceeds remaining quantity")
        total = self.filled_quantity + quantity
        old_notional = (self.average_fill_price or 0.0) * self.filled_quantity
        average = (old_notional + price * quantity) / total
        state = (
            SimulationOrderState.FILLED
            if total == self.intent.quantity
            else SimulationOrderState.PARTIALLY_FILLED
        )
        return self._updated(
            state=state,
            filled_quantity=total,
            average_fill_price=average,
            fill_ids=(*self.fill_ids, fill_id),
            last_event_at=at,
        )

    def _require_state(self, allowed: set[SimulationOrderState]) -> None:
        if self.state not in allowed:
            raise IllegalOrderTransition(f"state {self.state} not in {sorted(allowed)}")

    def _updated(self, **updates: object) -> TrackedOrder:
        at = updates.get("last_event_at", self.last_event_at)
        if not isinstance(at, datetime):
            raise TypeError("last_event_at must be datetime")
        require_aware(at, "last_event_at")
        if at < self.last_event_at:
            raise IllegalOrderTransition("order events must be monotonic")
        data = self.model_dump(mode="python")
        data.update(updates)
        return TrackedOrder.model_validate(data)
