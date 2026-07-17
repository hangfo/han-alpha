from __future__ import annotations

from datetime import timedelta

import pytest

from hanalpha.pit.catalog import PITCatalog, SnapshotManifest
from hanalpha.pit.models import CorporateActionRecord, CorporateActionType
from hanalpha.pit.quality import DataQualityGate


def test_quality_rejects_overlapping_alias_and_orphan_action(
    instrument, alias, pit_time, snapshot_id
) -> None:
    overlap = alias.model_copy(
        update={
            "instrument_id": "inst-other",
            "record_id": "alias-overlap",
            "source_record_id": "alias-overlap",
            "payload_hash": "d" * 64,
            "valid_from": alias.valid_from + timedelta(days=1),
        }
    )
    orphan = CorporateActionRecord(
        instrument_id="inst-missing",
        record_id="action-orphan",
        event_time=pit_time + timedelta(days=2),
        available_at=pit_time + timedelta(days=1),
        ingested_at=pit_time + timedelta(days=1, seconds=1),
        valid_from=pit_time + timedelta(days=2),
        valid_to=None,
        source="fixture",
        source_record_id="action-orphan",
        source_revision=1,
        schema_version="1",
        payload_hash="e" * 64,
        snapshot_id=snapshot_id,
        action_type=CorporateActionType.SPLIT,
        ratio=2,
    )
    report = DataQualityGate().evaluate([instrument, alias, overlap, orphan])
    assert not report.passed
    assert {issue.code for issue in report.issues} >= {
        "overlapping_ticker_interval",
        "orphan_instrument_reference",
    }


def test_quality_passes_clean_records(instrument, alias, price_bar) -> None:
    report = DataQualityGate().evaluate([instrument, alias, price_bar])
    assert report.passed
    assert report.digest


def test_quality_rejects_price_bar_outside_exchange_session(
    instrument, alias, price_bar, pit_time
) -> None:
    weekend = price_bar.model_copy(
        update={
            "event_time": pit_time.replace(day=6),
            "valid_from": pit_time.replace(day=6),
            "record_id": "weekend-bar",
            "source_record_id": "weekend-bar",
            "payload_hash": "8" * 64,
        }
    )
    report = DataQualityGate().evaluate([instrument, alias, weekend])
    assert "event_outside_exchange_session" in {item.code for item in report.issues}


def test_quality_rejects_conflicting_canonical_record_id(
    instrument, alias, price_bar
) -> None:
    conflicting = price_bar.model_copy(
        update={
            "source_record_id": "other-source-row",
            "payload_hash": "7" * 64,
            "close": 100,
        }
    )
    report = DataQualityGate().evaluate([instrument, alias, price_bar, conflicting])
    assert "conflicting_record_id" in {item.code for item in report.issues}


def test_failed_quality_report_cannot_publish(tmp_path, instrument, alias) -> None:
    orphan = alias.model_copy(
        update={
            "instrument_id": "missing",
            "record_id": "orphan-alias",
            "source_record_id": "orphan-alias",
            "payload_hash": "9" * 64,
        }
    )
    report = DataQualityGate().evaluate([instrument, alias, orphan])
    catalog = PITCatalog(tmp_path / "catalog.sqlite3")
    manifest = SnapshotManifest(
        input_hashes=[record.payload_hash for record in [instrument, alias, orphan]],
        schema_version="1",
        normalization_code_hash="a" * 64,
        config_hash="b" * 64,
        fixture_version="test",
    )
    try:
        actual_snapshot = catalog.create_snapshot(manifest)
        catalog.record_quality(actual_snapshot, report)
        with pytest.raises(RuntimeError, match="passing quality report"):
            catalog.publish_snapshot(actual_snapshot)
        assert not catalog.is_published(actual_snapshot)
    finally:
        catalog.close()
