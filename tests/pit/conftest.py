from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hanalpha.pit.models import InstrumentRecord, PriceBarRecord, SymbolAliasRecord


@pytest.fixture
def pit_time() -> datetime:
    return datetime(2024, 1, 2, 14, 30, tzinfo=UTC)


@pytest.fixture
def snapshot_id() -> str:
    return "1" * 64


@pytest.fixture
def instrument(pit_time: datetime, snapshot_id: str) -> InstrumentRecord:
    return InstrumentRecord(
        instrument_id="inst-alpha",
        record_id="instrument-alpha-v1",
        event_time=pit_time,
        available_at=pit_time,
        ingested_at=pit_time + timedelta(seconds=1),
        valid_from=pit_time,
        valid_to=None,
        source="fixture",
        source_record_id="instrument-alpha",
        source_revision=1,
        schema_version="1",
        payload_hash="a" * 64,
        snapshot_id=snapshot_id,
        name="Alpha Synthetic",
        exchange="XNYS",
        asset_type="stock",
    )


@pytest.fixture
def alias(pit_time: datetime, snapshot_id: str) -> SymbolAliasRecord:
    return SymbolAliasRecord(
        instrument_id="inst-alpha",
        record_id="alias-alpha-v1",
        event_time=pit_time,
        available_at=pit_time,
        ingested_at=pit_time + timedelta(seconds=1),
        valid_from=pit_time,
        valid_to=None,
        source="fixture",
        source_record_id="alias-alpha",
        source_revision=1,
        schema_version="1",
        payload_hash="b" * 64,
        snapshot_id=snapshot_id,
        ticker="ALFA",
    )


@pytest.fixture
def price_bar(pit_time: datetime, snapshot_id: str) -> PriceBarRecord:
    return PriceBarRecord(
        instrument_id="inst-alpha",
        record_id="bar-alpha-v1",
        event_time=pit_time,
        available_at=pit_time + timedelta(minutes=1),
        ingested_at=pit_time + timedelta(minutes=2),
        valid_from=pit_time,
        valid_to=None,
        source="fixture",
        source_record_id="bar-alpha",
        source_revision=1,
        schema_version="1",
        payload_hash="c" * 64,
        snapshot_id=snapshot_id,
        interval="1m",
        open=100,
        high=102,
        low=99,
        close=101,
        volume=1000,
    )
