from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hanalpha.cli import app
from hanalpha.data.fixtures import run_fixture_pipeline
from hanalpha.pit.canonical_store import CanonicalStore
from hanalpha.pit.catalog import PITCatalog
from hanalpha.pit.context import AsOfContext
from hanalpha.pit.models import parse_record
from hanalpha.pit.quality import DataQualityGate
from hanalpha.pit.repository import AsOfRepository

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "v1"


def test_fixture_pipeline_is_replay_deterministic(tmp_path) -> None:
    first = run_fixture_pipeline(FIXTURE_ROOT, tmp_path / "first")
    second = run_fixture_pipeline(FIXTURE_ROOT, tmp_path / "second")
    assert first.snapshot_id == second.snapshot_id
    assert first.feature_hash == second.feature_hash
    assert first.quality_passed
    assert first.record_count > 0


def test_fixture_pipeline_is_idempotent_in_the_same_state(tmp_path) -> None:
    state = tmp_path / "shared"
    first = run_fixture_pipeline(FIXTURE_ROOT, state)
    second = run_fixture_pipeline(FIXTURE_ROOT, state)
    assert second == first


def test_pit_cli_ingest_quality_and_snapshot(tmp_path) -> None:
    runner = CliRunner()
    state = tmp_path / "pit-state"
    ingest = runner.invoke(
        app,
        ["pit", "ingest-fixture", "--fixture", str(FIXTURE_ROOT), "--state", str(state)],
    )
    assert ingest.exit_code == 0, ingest.output
    snapshot_id = ingest.stdout.strip().split("snapshot_id=")[1].split()[0]
    quality = runner.invoke(
        app, ["pit", "quality", "--state", str(state), "--snapshot", snapshot_id]
    )
    assert quality.exit_code == 0, quality.output
    assert "passed=True" in quality.stdout
    snapshot = runner.invoke(
        app, ["pit", "snapshot", "--state", str(state), "--snapshot", snapshot_id]
    )
    assert snapshot.exit_code == 0, snapshot.output
    assert snapshot_id in snapshot.stdout


def test_frozen_fixture_proves_rename_delist_reuse_and_revision(tmp_path) -> None:
    state = tmp_path / "state"
    result = run_fixture_pipeline(FIXTURE_ROOT, state)
    catalog = PITCatalog(state / "catalog.sqlite3")
    try:
        repository = AsOfRepository(catalog, CanonicalStore(state / "canonical"))
        january = AsOfContext(
            snapshot_id=result.snapshot_id,
            as_of=datetime(2024, 1, 15, tzinfo=UTC),
        )
        february = AsOfContext(
            snapshot_id=result.snapshot_id,
            as_of=datetime(2024, 2, 15, 15, tzinfo=UTC),
        )
        march = AsOfContext(
            snapshot_id=result.snapshot_id,
            as_of=datetime(2024, 3, 15, tzinfo=UTC),
        )
        april = AsOfContext(
            snapshot_id=result.snapshot_id,
            as_of=datetime(2024, 4, 3, tzinfo=UTC),
        )
        assert repository.resolve_ticker("ALFA", january).instrument_id == "inst-alpha"
        assert repository.resolve_ticker("BETA", january) is None
        assert repository.resolve_ticker("BETA", february).instrument_id == "inst-alpha"
        assert repository.resolve_ticker("ALFA", february) is None
        assert "inst-delisted" in {
            item.instrument_id for item in repository.active_instruments(february)
        }
        assert "inst-delisted" not in {
            item.instrument_id for item in repository.active_instruments(march)
        }
        assert repository.resolve_ticker("ALFA", april).instrument_id == "inst-reused"

        early = AsOfContext(
            snapshot_id=result.snapshot_id,
            as_of=datetime(2024, 1, 2, 14, 32, tzinfo=UTC),
        )
        revised = AsOfContext(
            snapshot_id=result.snapshot_id,
            as_of=datetime(2024, 1, 4, tzinfo=UTC),
        )
        assert [bar.close for bar in repository.price_bars("inst-alpha", early)] == [
            101,
            102,
        ]
        assert [bar.close for bar in repository.price_bars("inst-alpha", revised)] == [
            101,
            103,
        ]
    finally:
        catalog.close()


def test_manifested_invalid_fixtures_fail_at_the_declared_boundary() -> None:
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text())
    classifications = {item["path"]: item["classification"] for item in manifest["files"]}
    assert classifications["invalid/naive_timestamp.jsonl"] == "reject_ingest"
    assert classifications["invalid/orphan_action.jsonl"] == "reject_quality"
    assert classifications["invalid/overlapping_alias.jsonl"] == "reject_quality"

    naive = (FIXTURE_ROOT / "invalid/naive_timestamp.jsonl").read_bytes().strip()
    naive_payload = json.loads(naive)
    naive_payload.update(payload_hash=hashlib.sha256(naive).hexdigest(), snapshot_id="1" * 64)
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_record(naive_payload)

    payloads = []
    for relative in (
        "raw/aliases.jsonl",
        "invalid/orphan_action.jsonl",
        "invalid/overlapping_alias.jsonl",
    ):
        lines = (FIXTURE_ROOT / relative).read_bytes().splitlines()
        selected = lines[:1]
        for line in selected:
            payload = json.loads(line)
            payload.update(payload_hash=hashlib.sha256(line).hexdigest(), snapshot_id="1" * 64)
            payloads.append(parse_record(payload))
    report = DataQualityGate().evaluate(payloads)
    assert not report.passed
    assert {issue.code for issue in report.issues} >= {
        "orphan_instrument_reference",
        "overlapping_ticker_interval",
    }
