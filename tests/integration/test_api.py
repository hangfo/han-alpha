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
