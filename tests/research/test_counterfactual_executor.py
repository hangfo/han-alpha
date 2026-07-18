from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hanalpha.domain.enums import Side
from hanalpha.experiments.models import WindowRole
from hanalpha.experiments.registry import ExperimentRegistry
from hanalpha.experiments.runner import ExperimentRunner
from hanalpha.research.counterfactuals import CounterfactualExecutor, CounterfactualSpec
from hanalpha.simulation.engine import OrderProposal, PortfolioReplayEngine
from hanalpha.simulation.events import ReplayFrame, SimulationBar
from hanalpha.simulation.fills import FillPolicy, HistoricalExchange
from hanalpha.simulation.orders import OrderKind
from hanalpha.simulation.portfolio import PortfolioPolicy
from tests.experiments.helpers import authorized_manifest, protocol


class BuyOnce:
    name = "buy-once"
    version = "1"

    def __init__(self) -> None:
        self.called = False

    def propose(self, frame, portfolio):
        if self.called:
            return []
        self.called = True
        return [
            OrderProposal(
                instrument_id="inst-alpha",
                strategy_id=self.name,
                strategy_version=self.version,
                side=Side.BUY,
                kind=OrderKind.MARKET,
                quantity=10,
                planned_price=100,
                protective_stop=80,
                input_hash="1" * 64,
                signal_hash="2" * 64,
            )
        ]


def test_counterfactuals_execute_cost_and_delay_under_registry_budget(tmp_path) -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    fill_policy = FillPolicy(minimum_commission=1)
    research_protocol = protocol(max_trials=3).model_copy(
        update={"cost_policy_hash": fill_policy.policy_hash}
    )
    registry = ExperimentRegistry(tmp_path / "registry.sqlite3")
    portfolio_policy = PortfolioPolicy(
        max_symbol_exposure=Decimal("1"),
        max_risk_per_trade=Decimal("1"),
        max_total_risk=Decimal("1"),
    )
    engine = PortfolioReplayEngine(
        starting_cash=Decimal("10000"),
        portfolio_policy=portfolio_policy,
        exchange=HistoricalExchange(fill_policy),
        config_hash="3" * 64,
    )
    bars = [
        SimulationBar(
            snapshot_id="1" * 64,
            instrument_id="inst-alpha",
            source_record_id=f"bar-{index}",
            source_revision=1,
            event_time=now + timedelta(minutes=index),
            available_at=now + timedelta(minutes=index),
            open=100 + index,
            high=102 + index,
            low=99 + index,
            close=101 + index,
            volume=1000,
        )
        for index in range(4)
    ]
    frames = [ReplayFrame(snapshot_id="1" * 64, as_of=bar.available_at, bars=[bar]) for bar in bars]
    try:
        base = authorized_manifest(
            registry,
            at=now,
            protocol_override=research_protocol,
            parameters={},
            strategy_id=BuyOnce.name,
            cost_policy_hash=fill_policy.policy_hash,
        )
        base_result = ExperimentRunner(registry, tmp_path / "artifacts").run(
            manifest=base, engine=engine, frames=frames, policy=BuyOnce(), at=now
        )
        results = CounterfactualExecutor(registry, tmp_path / "artifacts").run(
            base=base,
            base_engine=engine,
            frames=frames,
            policy_factory=lambda parameters: BuyOnce(),
            specs=(
                CounterfactualSpec(name="double-cost", cost_multiplier=Decimal("2")),
                CounterfactualSpec(name="one-bar-delay", delay_bars=1),
            ),
            at=now,
        )
        assert results[0].metrics.ending_equity < base_result.metrics.ending_equity
        manifests = [registry.manifest(result.experiment_id) for result in results]
        assert all(item.counterfactual_of == base.experiment_id for item in manifests)
        assert all(item.window_role == WindowRole.COUNTERFACTUAL for item in manifests)
        assert manifests[0].cost_policy_hash != base.cost_policy_hash
        assert manifests[1].parameters["__delay_bars"] == 1
    finally:
        registry.close()
