from __future__ import annotations

from datetime import timedelta

import pytest

from hanalpha.pit.catalog import PITCatalog, SnapshotManifest
from hanalpha.pit.raw_store import ContentAddressedRawStore, RawRecordConflict


def test_raw_store_is_content_addressed_and_idempotent(tmp_path, pit_time) -> None:
    store = ContentAddressedRawStore(tmp_path / "raw")
    first = store.put(
        b'{"value":1}',
        source="fixture",
        source_record_id="row-1",
        source_revision=1,
        event_time=pit_time,
        available_at=pit_time,
        ingested_at=pit_time + timedelta(seconds=1),
        schema_version="1",
    )
    second = store.put(
        b'{"value":1}',
        source="fixture",
        source_record_id="row-1",
        source_revision=1,
        event_time=pit_time,
        available_at=pit_time,
        ingested_at=pit_time + timedelta(seconds=1),
        schema_version="1",
    )
    assert first.payload_hash == second.payload_hash
    assert store.read(first.payload_hash) == b'{"value":1}'


def test_raw_catalog_rejects_same_revision_with_different_bytes(tmp_path, pit_time) -> None:
    store = ContentAddressedRawStore(tmp_path / "raw")
    catalog = PITCatalog(tmp_path / "catalog.sqlite3")
    try:
        first = store.put(
            b"first",
            source="fixture",
            source_record_id="row-1",
            source_revision=1,
            event_time=pit_time,
            available_at=pit_time,
            ingested_at=pit_time,
            schema_version="1",
        )
        second = store.put(
            b"second",
            source="fixture",
            source_record_id="row-1",
            source_revision=1,
            event_time=pit_time,
            available_at=pit_time,
            ingested_at=pit_time,
            schema_version="1",
        )
        catalog.register_raw(first)
        with pytest.raises(RawRecordConflict):
            catalog.register_raw(second)
    finally:
        catalog.close()


def test_snapshot_manifest_hash_is_order_independent() -> None:
    first = SnapshotManifest(
        input_hashes=["b" * 64, "a" * 64],
        schema_version="1",
        normalization_code_hash="c" * 64,
        config_hash="d" * 64,
        fixture_version="v1",
    )
    second = first.model_copy(update={"input_hashes": list(reversed(first.input_hashes))})
    assert first.snapshot_id == second.snapshot_id


def test_snapshot_hash_changes_with_each_contract_input() -> None:
    baseline = SnapshotManifest(
        input_hashes=["a" * 64],
        schema_version="1",
        normalization_code_hash="b" * 64,
        config_hash="c" * 64,
        fixture_version="v1",
    )
    variants = [
        baseline.model_copy(update={"input_hashes": ["d" * 64]}),
        baseline.model_copy(update={"schema_version": "2"}),
        baseline.model_copy(update={"normalization_code_hash": "d" * 64}),
        baseline.model_copy(update={"config_hash": "d" * 64}),
    ]
    assert all(item.snapshot_id != baseline.snapshot_id for item in variants)
