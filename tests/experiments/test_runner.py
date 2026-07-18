from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from hanalpha.experiments.models import TrialStatus
from hanalpha.experiments.registry import ExperimentRegistry
from hanalpha.experiments.runner import ExperimentRunner
from hanalpha.simulation.engine import PortfolioReplayEngine
from hanalpha.simulation.events import ReplayFrame
from hanalpha.simulation.fills import FillPolicy, HistoricalExchange
from hanalpha.simulation.portfolio import PortfolioPolicy
from tests.experiments.helpers import authorized_manifest


class NoCandidates:
    name = "no-candidates"
    version = "1"

    def propose(self, frame, portfolio):
        return []


def _engine() -> PortfolioReplayEngine:
    return PortfolioReplayEngine(
        starting_cash=Decimal("10000"),
        portfolio_policy=PortfolioPolicy(),
        exchange=HistoricalExchange(FillPolicy()),
        config_hash="3" * 64,
    )


def test_runner_closes_registry_result_and_artifact_loop(tmp_path) -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    registry = ExperimentRegistry(tmp_path / "registry.sqlite3")
    try:
        runner = ExperimentRunner(registry, tmp_path / "artifacts")
        manifest = authorized_manifest(
            registry,
            at=now,
            parameters={},
            strategy_id="no-candidates",
            cost_policy_hash=FillPolicy().policy_hash,
        )
        result = runner.run(
            manifest=manifest,
            engine=_engine(),
            frames=[ReplayFrame(snapshot_id="1" * 64, as_of=now, bars=[])],
            policy=NoCandidates(),
            at=now,
        )
        assert result.metrics.ending_equity == Decimal("10000")
        history = registry.history(manifest.experiment_id)
        assert [event.status for event in history] == [
            TrialStatus.REGISTERED,
            TrialStatus.RUNNING,
            TrialStatus.COMPLETED,
        ]
        assert history[-1].result_hash == result.result_hash
        assert {artifact.digest.name for artifact in registry.artifacts(result.experiment_id)} == {
            "cash-ledger.jsonl",
            "journal.jsonl",
            "manifest.json",
            "position-lots.jsonl",
            "report.html",
            "result.json",
        }
        assert result.journal_entries
        assert result.cash_entries
    finally:
        registry.close()


def test_runner_records_failure_in_strategy_cemetery(tmp_path) -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    registry = ExperimentRegistry(tmp_path / "registry.sqlite3")
    try:
        runner = ExperimentRunner(registry, tmp_path / "artifacts")
        manifest = authorized_manifest(
            registry,
            at=now,
            parameters={},
            strategy_id="no-candidates",
            cost_policy_hash=FillPolicy().policy_hash,
        )
        with pytest.raises(ValueError, match="at least one frame"):
            runner.run(
                manifest=manifest,
                engine=_engine(),
                frames=[],
                policy=NoCandidates(),
                at=now,
            )
        cemetery = registry.strategy_cemetery()
        assert cemetery[0].status == TrialStatus.FAILED
        assert "ValueError" in (cemetery[0].failure_reason or "")
    finally:
        registry.close()
