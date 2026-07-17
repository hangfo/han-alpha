from __future__ import annotations

from datetime import timedelta

import pytest

from hanalpha.pit.canonical_store import CanonicalStore
from hanalpha.pit.catalog import PITCatalog, SnapshotManifest
from hanalpha.pit.context import AsOfContext
from hanalpha.pit.quality import DataQualityGate
from hanalpha.pit.repository import AsOfRepository, SnapshotNotPublished


def _publish(tmp_path, records):
    catalog = PITCatalog(tmp_path / "catalog.sqlite3")
    store = CanonicalStore(tmp_path / "canonical")
    manifest = SnapshotManifest(
        input_hashes=sorted(record.payload_hash for record in records),
        schema_version="1",
        normalization_code_hash="c" * 64,
        config_hash="d" * 64,
        fixture_version="test",
    )
    snapshot_id = manifest.snapshot_id
    bound = [record.model_copy(update={"snapshot_id": snapshot_id}) for record in records]
    catalog.create_snapshot(manifest)
    report = DataQualityGate().evaluate(bound)
    catalog.record_quality(snapshot_id, report)
    store.write(snapshot_id, bound)
    return catalog, store, report, snapshot_id


def test_unpublished_snapshot_cannot_be_queried(tmp_path, instrument, alias) -> None:
    catalog, store, _, snapshot_id = _publish(tmp_path, [instrument, alias])
    try:
        repository = AsOfRepository(catalog, store)
        with pytest.raises(SnapshotNotPublished):
            repository.active_instruments(
                AsOfContext(snapshot_id=snapshot_id, as_of=alias.available_at)
            )
    finally:
        catalog.close()


def test_ticker_rename_delisting_and_reuse_are_point_in_time(
    tmp_path, instrument, alias, pit_time
) -> None:
    rename_time = pit_time + timedelta(days=10)
    delist_time = pit_time + timedelta(days=20)
    old_alias = alias.model_copy(update={"valid_to": rename_time})
    new_alias = alias.model_copy(
        update={
            "record_id": "alias-beta",
            "source_record_id": "alias-beta",
            "payload_hash": "d" * 64,
            "ticker": "BETA",
            "event_time": rename_time,
            "available_at": rename_time,
            "ingested_at": rename_time + timedelta(seconds=1),
            "valid_from": rename_time,
            "valid_to": delist_time,
        }
    )
    delisted = instrument.model_copy(update={"valid_to": delist_time})
    reused_instrument = instrument.model_copy(
        update={
            "instrument_id": "inst-reused",
            "record_id": "instrument-reused",
            "source_record_id": "instrument-reused",
            "payload_hash": "e" * 64,
            "event_time": delist_time,
            "available_at": delist_time,
            "ingested_at": delist_time + timedelta(seconds=1),
            "valid_from": delist_time,
        }
    )
    reused_alias = alias.model_copy(
        update={
            "instrument_id": "inst-reused",
            "record_id": "alias-reused",
            "source_record_id": "alias-reused",
            "payload_hash": "f" * 64,
            "event_time": delist_time,
            "available_at": delist_time,
            "ingested_at": delist_time + timedelta(seconds=1),
            "valid_from": delist_time,
        }
    )
    records = [delisted, old_alias, new_alias, reused_instrument, reused_alias]
    catalog, store, report, snapshot_id = _publish(tmp_path, records)
    try:
        assert report.passed
        catalog.publish_snapshot(snapshot_id)
        repository = AsOfRepository(catalog, store)
        before = AsOfContext(snapshot_id=snapshot_id, as_of=pit_time + timedelta(days=1))
        after_rename = AsOfContext(
            snapshot_id=snapshot_id, as_of=rename_time + timedelta(days=1)
        )
        after_reuse = AsOfContext(
            snapshot_id=snapshot_id, as_of=delist_time + timedelta(days=1)
        )
        assert repository.resolve_ticker("ALFA", before).instrument_id == "inst-alpha"
        assert repository.resolve_ticker("BETA", before) is None
        assert repository.resolve_ticker("BETA", after_rename).instrument_id == "inst-alpha"
        assert repository.resolve_ticker("ALFA", after_rename) is None
        assert repository.resolve_ticker("ALFA", after_reuse).instrument_id == "inst-reused"
        assert {item.instrument_id for item in repository.active_instruments(after_reuse)} == {
            "inst-reused"
        }
    finally:
        catalog.close()


def test_available_at_and_revisions_are_enforced(tmp_path, instrument, alias, price_bar) -> None:
    revised = price_bar.model_copy(
        update={
            "record_id": "bar-alpha-v2",
            "source_revision": 2,
            "payload_hash": "e" * 64,
            "available_at": price_bar.available_at + timedelta(hours=1),
            "ingested_at": price_bar.ingested_at + timedelta(hours=1),
            "high": 106,
            "close": 105,
        }
    )
    catalog, store, report, snapshot_id = _publish(
        tmp_path, [instrument, alias, price_bar, revised]
    )
    try:
        assert report.passed
        catalog.publish_snapshot(snapshot_id)
        repository = AsOfRepository(catalog, store)
        early = repository.price_bars(
            "inst-alpha",
            AsOfContext(snapshot_id=snapshot_id, as_of=price_bar.available_at),
        )
        late = repository.price_bars(
            "inst-alpha",
            AsOfContext(snapshot_id=snapshot_id, as_of=revised.available_at),
        )
        assert [item.close for item in early] == [101]
        assert [item.close for item in late] == [105]
    finally:
        catalog.close()


def test_canonical_snapshot_is_immutable(tmp_path, price_bar) -> None:
    store = CanonicalStore(tmp_path / "canonical")
    store.write(price_bar.snapshot_id, [price_bar])
    changed = price_bar.model_copy(
        update={"close": 100, "payload_hash": "9" * 64}
    )
    with pytest.raises(RuntimeError, match="immutable canonical snapshot"):
        store.write(price_bar.snapshot_id, [changed])
