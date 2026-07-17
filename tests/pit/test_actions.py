from __future__ import annotations

from datetime import timedelta

from hanalpha.pit.actions import AdjustmentPolicy, adjust_price
from hanalpha.pit.models import CorporateActionRecord, CorporateActionType


def test_split_adjustment_is_traceable_and_does_not_mutate_raw(
    pit_time, snapshot_id
) -> None:
    action = CorporateActionRecord(
        instrument_id="inst-alpha",
        record_id="split-1",
        event_time=pit_time + timedelta(days=2),
        available_at=pit_time + timedelta(days=1),
        ingested_at=pit_time + timedelta(days=1, seconds=1),
        valid_from=pit_time + timedelta(days=2),
        valid_to=None,
        source="fixture",
        source_record_id="split-1",
        source_revision=1,
        schema_version="1",
        payload_hash="f" * 64,
        snapshot_id=snapshot_id,
        action_type=CorporateActionType.SPLIT,
        ratio=2,
    )
    raw = 100.0
    adjusted = adjust_price(
        raw,
        price_time=pit_time,
        as_of=pit_time + timedelta(days=3),
        actions=[action],
        policy=AdjustmentPolicy.SPLIT,
    )
    assert raw == 100
    assert adjusted.value == 50
    assert adjusted.policy == AdjustmentPolicy.SPLIT
    assert adjusted.action_ids == ["split-1"]
    assert adjusted.snapshot_id == snapshot_id
    assert adjusted.policy_version == "1"


def test_cash_adjustment_is_explicit_and_raw_policy_remains_unchanged(
    pit_time, snapshot_id
) -> None:
    action = CorporateActionRecord(
        instrument_id="inst-alpha",
        record_id="dividend-1",
        event_time=pit_time + timedelta(days=2),
        available_at=pit_time + timedelta(days=1),
        ingested_at=pit_time + timedelta(days=1, seconds=1),
        valid_from=pit_time + timedelta(days=2),
        valid_to=None,
        source="fixture",
        source_record_id="dividend-1",
        source_revision=1,
        schema_version="1",
        payload_hash="e" * 64,
        snapshot_id=snapshot_id,
        action_type=CorporateActionType.DIVIDEND,
        cash_amount=1.5,
    )
    raw_view = adjust_price(
        100,
        price_time=pit_time,
        as_of=pit_time + timedelta(days=3),
        actions=[action],
        policy=AdjustmentPolicy.RAW,
    )
    adjusted = adjust_price(
        100,
        price_time=pit_time,
        as_of=pit_time + timedelta(days=3),
        actions=[action],
        policy=AdjustmentPolicy.SPLIT_AND_CASH,
    )
    assert raw_view.value == 100
    assert raw_view.action_ids == []
    assert adjusted.value == 98.5
    assert adjusted.action_ids == ["dividend-1"]
