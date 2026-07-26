from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from hanalpha.execution.control_store import DurableExecutionStore
from hanalpha.execution.ibkr_observer import IBKRFactStore
from hanalpha.ops.backup import backup_databases, current_generation, restore_databases
from hanalpha.ops.service import OpsService

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def test_ops_overview_readiness_metrics_and_heartbeat(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    try:
        store.record_heartbeat("worker", status="OK", at=NOW, details={"fence": 1})
        service = OpsService(store, observer_path=tmp_path / "missing-observer.sqlite3")
        overview = service.overview(now=NOW)
        assert overview["safety"]["frozen"]
        assert overview["observer"]["status"] == "NO_LOCAL_FACT_TAPE"
        assert overview["heartbeats"][0]["details"] == {"fence": 1}
        assert not service.readiness({"broker_connected": True, "market_data_healthy": True})[
            "ready"
        ]
        runtime_overview = service.overview(
            now=NOW,
            runtime_status={"broker_connected": True, "market_data_healthy": True},
        )
        assert runtime_overview["readiness"]["observer"]["checks"]["broker_connected"]
        assert not runtime_overview["readiness"]["paper_canary"]["ready"]
        assert runtime_overview["paper_canary_safety_case"]["status"] == "NOT_ISSUED"
        metrics = service.prometheus()
        assert "hanalpha_control_frozen 1" in metrics
        with pytest.raises(ValueError, match="unsupported"):
            service._count("execution_intents")
        observer_path = tmp_path / "empty-observer.sqlite3"
        observer = IBKRFactStore(observer_path)
        observer.close()
        assert OpsService(store, observer_path=observer_path).overview(now=NOW)["observer"] == {
            "available": True,
            "status": "NO_CERTIFICATE",
        }
    finally:
        store.close()


def test_backup_restore_verifies_hash_and_sqlite_integrity(tmp_path) -> None:
    source = tmp_path / "source.sqlite3"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE evidence(value TEXT NOT NULL)")
    connection.execute("INSERT INTO evidence VALUES ('durable')")
    connection.commit()
    connection.close()

    manifest = backup_databases((source,), tmp_path / "backup")
    restored = tmp_path / "restored"
    generation = restore_databases(manifest, restored)
    assert current_generation(restored) == generation
    check = sqlite3.connect(generation / source.name)
    assert check.execute("SELECT value FROM evidence").fetchone()[0] == "durable"
    check.close()
    with pytest.raises(FileExistsError):
        restore_databases(manifest, restored)
    assert restore_databases(manifest, restored, overwrite=True) == generation
    assert current_generation(restored) == generation

    artifact = manifest.parent / source.name
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        restore_databases(manifest, tmp_path / "bad")


def test_generation_restore_never_exposes_a_mixed_epoch(tmp_path) -> None:
    sources = []
    for name in ("control.sqlite3", "observer.sqlite3"):
        source = tmp_path / name
        connection = sqlite3.connect(source)
        connection.execute("CREATE TABLE generation(value TEXT NOT NULL)")
        connection.execute("INSERT INTO generation VALUES ('same-epoch')")
        connection.commit()
        connection.close()
        sources.append(source)
    manifest = backup_databases(tuple(sources), tmp_path / "backup-generation")
    state = tmp_path / "state"
    with pytest.raises(RuntimeError, match="injected restore interruption"):
        restore_databases(manifest, state, fail_after_files=1)
    assert current_generation(state) is None
    generation = restore_databases(manifest, state)
    assert current_generation(state) == generation
    assert {path.name for path in generation.glob("*.sqlite3")} == {
        "control.sqlite3",
        "observer.sqlite3",
    }


def test_overwrite_restore_never_deletes_current_generation(tmp_path) -> None:
    source = tmp_path / "source.sqlite3"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE evidence(value TEXT NOT NULL)")
    connection.execute("INSERT INTO evidence VALUES ('current')")
    connection.commit()
    connection.close()
    manifest = backup_databases((source,), tmp_path / "backup-current")
    state = tmp_path / "state-current"
    generation = restore_databases(manifest, state)
    assert (generation / source.name).exists()
    restored = restore_databases(manifest, state, overwrite=True)
    assert restored == generation
    assert (generation / source.name).exists()
    assert current_generation(state) == generation


def test_backup_rejects_ambiguous_same_name_sources(tmp_path) -> None:
    first = tmp_path / "first" / "state.sqlite3"
    second = tmp_path / "second" / "state.sqlite3"
    for path in (first, second):
        path.parent.mkdir()
        sqlite3.connect(path).close()
    with pytest.raises(ValueError, match="unique database names"):
        backup_databases((first, second), tmp_path / "ambiguous")
