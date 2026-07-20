from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from hanalpha.execution.control_store import DurableExecutionStore
from hanalpha.execution.ibkr_observer import IBKRFactStore
from hanalpha.ops.backup import backup_databases, restore_databases
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
        assert not service.readiness(
            {"broker_connected": True, "market_data_healthy": True}
        )["ready"]
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
    restore_databases(manifest, restored)
    check = sqlite3.connect(restored / source.name)
    assert check.execute("SELECT value FROM evidence").fetchone()[0] == "durable"
    check.close()
    with pytest.raises(FileExistsError):
        restore_databases(manifest, restored)

    artifact = manifest.parent / source.name
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        restore_databases(manifest, tmp_path / "bad")
