from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_api_lifecycle_and_controls(monkeypatch, tmp_path: Path) -> None:
    config = Path(__file__).parents[2] / "configs" / "paper.yaml"
    monkeypatch.setenv("HANALPHA_CONFIG_PATH", str(config))
    monkeypatch.setenv("HANALPHA_LEDGER_PATH", str(tmp_path / "api-ledger.sqlite3"))
    from hanalpha.api.main import app, state

    state.system = None
    state.ledger = None
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["ok"]
        readiness = client.get("/ready")
        assert readiness.status_code == 200
        assert set(readiness.json()["layers"]) == {
            "service",
            "observer",
            "authority",
            "shadow",
            "runtime_control",
            "paper_canary",
        }
        assert client.get("/ready/service").status_code == 200
        assert client.get("/ready/observer").status_code == 200
        assert client.get("/ready/paper-canary").status_code == 200
        overview = client.get("/ops/overview")
        assert overview.status_code == 200
        assert overview.json()["source_notes"]["control"]
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "hanalpha_control_frozen" in metrics.text
        cycle = client.post("/cycles/run")
        assert cycle.status_code == 403
        frozen = client.post("/risk/freeze", json={"reason": "operator test"})
        assert frozen.status_code == 403
        unfrozen = client.post("/risk/unfreeze")
        assert unfrozen.status_code == 403
        assert client.post("/orders/cancel-all").status_code == 403
        assert client.post("/positions/flatten-all").status_code == 403
        events = client.get("/events")
        assert events.status_code == 200
