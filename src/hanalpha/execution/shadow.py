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
    observed_at: datetime


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
