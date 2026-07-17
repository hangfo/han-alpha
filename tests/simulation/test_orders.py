from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from hanalpha.simulation.orders import (
    DuplicateOrderEvent,
    IllegalOrderTransition,
    OrderIntent,
    SimulationOrderState,
)


def test_order_intent_rejects_naive_time(buy_order) -> None:
    data = buy_order.intent.model_dump()
    data["submitted_at"] = datetime(2024, 1, 1)
    with pytest.raises(ValidationError, match="timezone-aware"):
        OrderIntent.model_validate(data)


def test_order_state_tracks_partial_then_full_fill(buy_order, simulation_time) -> None:
    partial = buy_order.apply_fill(
        fill_id="fill-1", quantity=40, price=100, at=simulation_time + timedelta(minutes=2)
    )
    assert partial.state == SimulationOrderState.PARTIALLY_FILLED
    assert partial.remaining_quantity == 60
    filled = partial.apply_fill(
        fill_id="fill-2", quantity=60, price=101, at=simulation_time + timedelta(minutes=3)
    )
    assert filled.state == SimulationOrderState.FILLED
    assert filled.average_fill_price == pytest.approx(100.6)


def test_order_state_fails_closed_on_duplicate_or_overfill(buy_order, simulation_time) -> None:
    partial = buy_order.apply_fill(
        fill_id="fill-1", quantity=40, price=100, at=simulation_time + timedelta(minutes=2)
    )
    with pytest.raises(DuplicateOrderEvent):
        partial.apply_fill(
            fill_id="fill-1", quantity=10, price=100, at=simulation_time + timedelta(minutes=3)
        )
    with pytest.raises(IllegalOrderTransition, match="remaining"):
        partial.apply_fill(
            fill_id="fill-x", quantity=61, price=100, at=simulation_time + timedelta(minutes=3)
        )
    with pytest.raises(IllegalOrderTransition):
        buy_order.accept(simulation_time)


def test_open_order_can_expire_but_filled_order_cannot(buy_order, simulation_time) -> None:
    expired = buy_order.expire(simulation_time + timedelta(minutes=5))
    assert expired.state == SimulationOrderState.EXPIRED
    filled = buy_order.apply_fill(
        fill_id="fill-1",
        quantity=buy_order.remaining_quantity,
        price=100,
        at=simulation_time + timedelta(minutes=2),
    )
    with pytest.raises(IllegalOrderTransition):
        filled.expire(simulation_time + timedelta(minutes=5))
