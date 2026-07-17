from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hanalpha.domain.enums import Side
from hanalpha.simulation.events import SimulationBar
from hanalpha.simulation.orders import OrderIntent, OrderKind, TrackedOrder


@pytest.fixture
def simulation_time() -> datetime:
    return datetime(2024, 1, 2, 14, 30, tzinfo=UTC)


@pytest.fixture
def simulation_bar(simulation_time: datetime) -> SimulationBar:
    return SimulationBar(
        snapshot_id="1" * 64,
        instrument_id="inst-alpha",
        source_record_id="bar-1",
        source_revision=1,
        event_time=simulation_time + timedelta(minutes=1),
        available_at=simulation_time + timedelta(minutes=2),
        open=100,
        high=105,
        low=95,
        close=102,
        volume=1000,
    )


@pytest.fixture
def buy_order(simulation_time: datetime) -> TrackedOrder:
    intent = OrderIntent(
        order_id="order-buy-1",
        decision_id="decision-1",
        instrument_id="inst-alpha",
        strategy_id="test-strategy",
        side=Side.BUY,
        kind=OrderKind.LIMIT,
        quantity=100,
        submitted_at=simulation_time,
        earliest_fill_at=simulation_time + timedelta(seconds=1),
        planned_price=100,
        limit_price=101,
        protective_stop=95,
    )
    return TrackedOrder.proposed(intent).accept(simulation_time)
