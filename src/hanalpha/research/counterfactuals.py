from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from hanalpha.experiments.models import (
    ExperimentManifest,
    ExperimentResult,
    WindowRole,
)
from hanalpha.experiments.registry import ExperimentRegistry
from hanalpha.experiments.runner import ExperimentRunner
from hanalpha.simulation.engine import (
    CandidatePolicy,
    OrderProposal,
    PortfolioReplayEngine,
)
from hanalpha.simulation.events import ReplayFrame, canonical_hash
from hanalpha.simulation.fills import FillPolicy, HistoricalExchange
from hanalpha.simulation.portfolio import PortfolioSnapshot


class CounterfactualSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    parameter_overrides: dict[str, int | float | str] = Field(default_factory=dict)
    cost_multiplier: Decimal = Field(default=Decimal("1"), gt=0)
    delay_bars: int = Field(default=0, ge=0)


def standard_counterfactual_suite(
    *, parameter: str, base_value: int
) -> tuple[CounterfactualSpec, ...]:
    if base_value < 2:
        raise ValueError("counterfactual parameter base must be at least two")
    delta = max(1, round(base_value * 0.1))
    return (
        CounterfactualSpec(name="double-cost", cost_multiplier=Decimal("2")),
        CounterfactualSpec(name="one-bar-delay", delay_bars=1),
        CounterfactualSpec(
            name=f"{parameter}-lower",
            parameter_overrides={parameter: base_value - delta},
        ),
        CounterfactualSpec(
            name=f"{parameter}-higher",
            parameter_overrides={parameter: base_value + delta},
        ),
    )


class _DelayedPolicy:
    def __init__(self, policy: CandidatePolicy, delay_bars: int) -> None:
        self.policy = policy
        self.delay_bars = delay_bars
        self.name = policy.name
        self.version = policy.version
        self._queue: list[list[OrderProposal]] = [[] for _ in range(delay_bars)]

    def propose(self, frame: ReplayFrame, portfolio: PortfolioSnapshot) -> list[OrderProposal]:
        current = self.policy.propose(frame, portfolio)
        if self.delay_bars == 0:
            return current
        self._queue.append(current)
        return self._queue.pop(0)


def _scaled_fill_policy(policy: FillPolicy, multiplier: Decimal) -> FillPolicy:
    factor = float(multiplier)
    return policy.model_copy(
        update={
            "spread_bps": policy.spread_bps * factor,
            "slippage_bps": policy.slippage_bps * factor,
            "impact_bps": policy.impact_bps * factor,
            "commission_per_share": policy.commission_per_share * factor,
            "minimum_commission": policy.minimum_commission * factor,
        }
    )


class CounterfactualExecutor:
    """Execute, budget, and persist counterfactuals instead of describing them."""

    def __init__(self, registry: ExperimentRegistry, artifact_root: Path) -> None:
        self.registry = registry
        self.runner = ExperimentRunner(registry, artifact_root)

    def run(
        self,
        *,
        base: ExperimentManifest,
        base_engine: PortfolioReplayEngine,
        frames: list[ReplayFrame],
        policy_factory: Callable[[dict[str, object]], CandidatePolicy],
        specs: tuple[CounterfactualSpec, ...],
        at: datetime,
    ) -> tuple[ExperimentResult, ...]:
        if not self.registry.history(base.experiment_id):
            raise KeyError("counterfactual base experiment is not registered")
        results: list[ExperimentResult] = []
        for spec in specs:
            parameters: dict[str, object] = {
                **base.parameters,
                **spec.parameter_overrides,
                "__cost_multiplier": str(spec.cost_multiplier),
                "__delay_bars": spec.delay_bars,
            }
            fill_policy = _scaled_fill_policy(base_engine.exchange.policy, spec.cost_multiplier)
            config_hash = canonical_hash(
                {
                    "base_config_hash": base.config_hash,
                    "counterfactual": spec,
                    "fill_policy": fill_policy,
                }
            )
            engine = PortfolioReplayEngine(
                starting_cash=base_engine.starting_cash,
                portfolio_policy=base_engine.portfolio_policy,
                exchange=HistoricalExchange(fill_policy),
                config_hash=config_hash,
            )
            policy = _DelayedPolicy(policy_factory(parameters), spec.delay_bars)
            allocation = self.registry.allocate_trial(
                base.protocol_hash,
                parameters=parameters,
                window_role=WindowRole.COUNTERFACTUAL,
                idempotency_key=f"counterfactual:{base.experiment_id}:{spec.name}",
                at=at,
            )
            manifest = base.model_copy(
                update={
                    "config_hash": config_hash,
                    "cost_policy_hash": fill_policy.policy_hash,
                    "hypothesis": f"{base.hypothesis}; counterfactual={spec.name}",
                    "parameters": parameters,
                    "counterfactual_of": base.experiment_id,
                    "trial_allocation_id": allocation.allocation_id,
                    "parameter_point_hash": allocation.parameter_point_hash,
                    "window_role": allocation.window_role,
                }
            )
            results.append(
                self.runner.run(
                    manifest=manifest,
                    engine=engine,
                    frames=frames,
                    policy=policy,
                    at=at,
                )
            )
        return tuple(results)
