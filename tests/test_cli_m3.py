from __future__ import annotations

import json

from typer.testing import CliRunner

from hanalpha.cli import app


def test_default_backtest_registers_deterministic_m3_artifacts(tmp_path) -> None:
    runner = CliRunner()
    state = tmp_path / "research"
    args = ["backtest", "--symbol", "NVDA", "--bars", "200", "--state", str(state)]
    first = runner.invoke(app, args)
    second = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    experiment_id = first.output.split("experiment_id=")[1].split()[0]
    assert experiment_id == second.output.split("experiment_id=")[1].split()[0]
    directory = state / "artifacts" / experiment_id
    assert {path.name for path in directory.iterdir()} == {
        "manifest.json",
        "report.html",
        "result.json",
    }
    result = json.loads((directory / "result.json").read_text())
    assert result["metrics"]["observations"] == 200
    assert "synthetic trend baseline" in (directory / "manifest.json").read_text()


def test_legacy_backtest_remains_explicitly_available() -> None:
    result = CliRunner().invoke(app, ["legacy-backtest", "--bars", "200"])
    assert result.exit_code == 0, result.output
    assert "trades=" in result.output
