from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from hanalpha.domain.enums import Side
from hanalpha.execution.control_store import DurableExecutionStore
from hanalpha.simulation.events import canonical_hash


class RealityGap(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gap_id: str
    decision_id: str
    client_order_key: str
    side: Side
    quantity: int = Field(gt=0)
    decision_price: Decimal = Field(gt=0)
    shadow_fill_price: Decimal | None = Field(default=None, gt=0)
    broker_fill_price: Decimal | None = Field(default=None, gt=0)
    broker_commission: Decimal = Field(default=Decimal("0"), ge=0)
    decision_to_shadow: Decimal | None
    shadow_to_broker: Decimal | None
    total_implementation_shortfall: Decimal | None
    missed_fill: bool
    observed_latency_ms: int = Field(ge=0)
    broker_filled_quantity: int = Field(default=0, ge=0)
    broker_unfilled_quantity: int = Field(default=0, ge=0)
    opportunity_cost: Decimal | None = None
    protection_delay_ms: int | None = Field(default=None, ge=0)
    broker_fill_slices: int = Field(default=0, ge=0)
    observed_at: datetime


class ExecutionSlice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quantity: int = Field(gt=0)
    price: Decimal = Field(gt=0)
    commission: Decimal = Field(default=Decimal("0"), ge=0)
    occurred_at: datetime


class ShadowExecutionEvaluator:
    """Decomposes execution reality gap; it never decides or submits an order."""

    def __init__(self, store: DurableExecutionStore) -> None:
        self.store = store

    def evaluate(
        self,
        *,
        decision_id: str,
        client_order_key: str,
        side: Side,
        quantity: int,
        decision_price: Decimal,
        shadow_fill_price: Decimal | None,
        broker_fill_price: Decimal | None,
        broker_commission: Decimal,
        observed_latency_ms: int,
        at: datetime,
        broker_filled_quantity: int | None = None,
        opportunity_cost: Decimal | None = None,
        protection_delay_ms: int | None = None,
        broker_fill_slices: int = 0,
    ) -> RealityGap:
        sign = Decimal("1") if side == Side.BUY else Decimal("-1")
        decision_to_shadow = (
            sign * (shadow_fill_price - decision_price) * quantity
            if shadow_fill_price is not None
            else None
        )
        shadow_to_broker = (
            sign * (broker_fill_price - shadow_fill_price) * quantity
            if shadow_fill_price is not None and broker_fill_price is not None
            else None
        )
        total = (
            sign * (broker_fill_price - decision_price) * quantity + broker_commission
            if broker_fill_price is not None
            else None
        )
        body = {
            "decision_id": decision_id,
            "client_order_key": client_order_key,
            "side": side,
            "quantity": quantity,
            "decision_price": decision_price,
            "shadow_fill_price": shadow_fill_price,
            "broker_fill_price": broker_fill_price,
            "broker_commission": broker_commission,
            "decision_to_shadow": decision_to_shadow,
            "shadow_to_broker": shadow_to_broker,
            "total_implementation_shortfall": total,
            "missed_fill": broker_fill_price is None,
            "observed_latency_ms": observed_latency_ms,
            "broker_filled_quantity": broker_filled_quantity or 0,
            "broker_unfilled_quantity": quantity - (broker_filled_quantity or 0),
            "opportunity_cost": opportunity_cost,
            "protection_delay_ms": protection_delay_ms,
            "broker_fill_slices": broker_fill_slices,
            "observed_at": at,
        }
        gap = RealityGap.model_validate({"gap_id": canonical_hash(body), **body})
        self.store.record_reality_gap(
            decision_id,
            gap_type="EXECUTION_SHORTFALL" if total is not None else "MISSED_FILL",
            at=at,
            payload=gap.model_dump(mode="json"),
        )
        return gap

    def evaluate_schedule(
        self,
        *,
        decision_id: str,
        client_order_key: str,
        side: Side,
        quantity: int,
        decision_price: Decimal,
        shadow_slices: tuple[ExecutionSlice, ...],
        broker_slices: tuple[ExecutionSlice, ...],
        terminal_mark: Decimal,
        submitted_at: datetime,
        protection_ack_at: datetime | None,
        at: datetime,
    ) -> RealityGap:
        """Compare partial-fill schedules, not a fictional single average fill."""
        shadow_quantity = sum(item.quantity for item in shadow_slices)
        broker_quantity = sum(item.quantity for item in broker_slices)
        if shadow_quantity > quantity or broker_quantity > quantity:
            raise ValueError("fill schedule exceeds intended quantity")
        shadow_vwap = (
            sum((item.price * item.quantity for item in shadow_slices), Decimal("0"))
            / shadow_quantity
            if shadow_quantity
            else None
        )
        broker_vwap = (
            sum((item.price * item.quantity for item in broker_slices), Decimal("0"))
            / broker_quantity
            if broker_quantity
            else None
        )
        sign = Decimal("1") if side == Side.BUY else Decimal("-1")
        opportunity_cost = sign * (terminal_mark - decision_price) * (quantity - broker_quantity)
        latency_ms = (
            max(0, int((broker_slices[0].occurred_at - submitted_at).total_seconds() * 1000))
            if broker_slices
            else max(0, int((at - submitted_at).total_seconds() * 1000))
        )
        protection_delay_ms = (
            max(0, int((protection_ack_at - submitted_at).total_seconds() * 1000))
            if protection_ack_at is not None
            else None
        )
        return self.evaluate(
            decision_id=decision_id,
            client_order_key=client_order_key,
            side=side,
            quantity=quantity,
            decision_price=decision_price,
            shadow_fill_price=shadow_vwap,
            broker_fill_price=broker_vwap,
            broker_commission=sum((item.commission for item in broker_slices), Decimal("0")),
            observed_latency_ms=latency_ms,
            at=at,
            broker_filled_quantity=broker_quantity,
            opportunity_cost=opportunity_cost,
            protection_delay_ms=protection_delay_ms,
            broker_fill_slices=len(broker_slices),
        )
