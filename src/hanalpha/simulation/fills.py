from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from hanalpha.domain.enums import Side
from hanalpha.pit.models import require_aware
from hanalpha.simulation.events import FillEvent, SimulationBar, canonical_hash
from hanalpha.simulation.orders import (
    OrderIntent,
    OrderKind,
    SimulationOrderState,
    TrackedOrder,
)


class CostScenario(StrEnum):
    OPTIMISTIC = "optimistic"
    BASE = "base"
    ADVERSE = "adverse"


class FillPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "1"
    scenario: CostScenario = CostScenario.BASE
    spread_bps: float = Field(default=4, ge=0)
    slippage_bps: float = Field(default=5, ge=0)
    impact_bps: float = Field(default=2, ge=0)
    participation_rate: float = Field(default=0.1, gt=0, le=1)
    commission_per_share: float = Field(default=0.005, ge=0)
    minimum_commission: float = Field(default=1, ge=0)

    @property
    def policy_hash(self) -> str:
        return canonical_hash(self)

    @property
    def scenario_multiplier(self) -> float:
        return {
            CostScenario.OPTIMISTIC: 0.5,
            CostScenario.BASE: 1.0,
            CostScenario.ADVERSE: 2.0,
        }[self.scenario]


class HistoricalExchange:
    def __init__(self, policy: FillPolicy) -> None:
        self.policy = policy

    def match(
        self,
        order: TrackedOrder,
        bar: SimulationBar,
        *,
        as_of: datetime,
        same_bar_protection: bool = False,
    ) -> FillEvent | None:
        require_aware(as_of, "as_of")
        if order.state not in {
            SimulationOrderState.ACCEPTED,
            SimulationOrderState.PARTIALLY_FILLED,
        }:
            return None
        intent = order.intent
        if same_bar_protection and not (
            intent.reduce_only and intent.submitted_at == bar.available_at
        ):
            raise ValueError("same-bar matching is restricted to new reduce-only protection")
        if bar.instrument_id != intent.instrument_id:
            return None
        if bar.source_revision != 1 or (
            not same_bar_protection and bar.event_time < intent.submitted_at
        ):
            return None
        if bar.available_at > as_of or (
            not same_bar_protection and bar.available_at <= intent.submitted_at
        ):
            return None
        if bar.available_at < intent.earliest_fill_at:
            return None
        if intent.expires_at is not None and bar.available_at > intent.expires_at:
            return None
        if bar.halted or bar.volume <= 0:
            return None
        maximum = math.floor(bar.volume * self.policy.participation_rate)
        quantity = min(order.remaining_quantity, maximum)
        if quantity <= 0:
            return None
        reference = self._reference_price(intent, bar)
        if reference is None:
            return None
        raw_price, reason = reference
        price = self._cost_adjusted(raw_price, intent.side)
        if intent.kind in {OrderKind.LIMIT, OrderKind.STOP_LIMIT}:
            assert intent.limit_price is not None
            if intent.side == Side.BUY:
                price = min(price, intent.limit_price)
            else:
                price = max(price, intent.limit_price)
        commission = max(
            self.policy.minimum_commission,
            quantity * self.policy.commission_per_share,
        )
        fill_id = canonical_hash(
            {
                "order_id": intent.order_id,
                "source_record_id": bar.source_record_id,
                "source_revision": bar.source_revision,
                "filled_before": order.filled_quantity,
            }
        )
        return FillEvent(
            fill_id=fill_id,
            order_id=intent.order_id,
            instrument_id=intent.instrument_id,
            side=intent.side,
            quantity=quantity,
            price=price,
            commission=commission,
            occurred_at=bar.available_at,
            reason=reason,
            source_record_id=bar.source_record_id,
            source_revision=bar.source_revision,
        )

    def _reference_price(self, intent: OrderIntent, bar: SimulationBar) -> tuple[float, str] | None:
        if intent.kind == OrderKind.MARKET:
            return bar.open, "market_open"
        if intent.kind == OrderKind.LIMIT:
            assert intent.limit_price is not None
            if intent.side == Side.BUY and bar.low <= intent.limit_price:
                return min(bar.open, intent.limit_price), "limit"
            if intent.side == Side.SELL and bar.high >= intent.limit_price:
                return max(bar.open, intent.limit_price), "limit"
            return None
        assert intent.stop_price is not None
        triggered = (intent.side == Side.SELL and bar.low <= intent.stop_price) or (
            intent.side == Side.BUY and bar.high >= intent.stop_price
        )
        if not triggered:
            return None
        gap = (intent.side == Side.SELL and bar.open < intent.stop_price) or (
            intent.side == Side.BUY and bar.open > intent.stop_price
        )
        if intent.kind == OrderKind.STOP_MARKET:
            reference = (
                min(bar.open, intent.stop_price)
                if intent.side == Side.SELL
                else max(bar.open, intent.stop_price)
            )
            return reference, "stop_gap" if gap else "stop_intrabar"
        assert intent.limit_price is not None
        if gap:
            marketable_at_open = (intent.side == Side.SELL and bar.open >= intent.limit_price) or (
                intent.side == Side.BUY and bar.open <= intent.limit_price
            )
            if not marketable_at_open:
                return None
            return bar.open, "stop_limit_gap"
        can_trade = (intent.side == Side.SELL and bar.high >= intent.limit_price) or (
            intent.side == Side.BUY and bar.low <= intent.limit_price
        )
        return (intent.limit_price, "stop_limit") if can_trade else None

    def _cost_adjusted(self, price: float, side: Side) -> float:
        bps = (
            self.policy.spread_bps / 2 + self.policy.slippage_bps + self.policy.impact_bps
        ) * self.policy.scenario_multiplier
        multiplier = 1 + bps / 10_000 if side == Side.BUY else 1 - bps / 10_000
        return max(0.000001, price * multiplier)
