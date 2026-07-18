from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hanalpha.simulation.events import SimulationBar


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
