from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hanalpha.experiments.models import ExperimentManifest, WindowRole
from hanalpha.experiments.registry import ExperimentRegistry
from hanalpha.research.protocol import (
    DateWindow,
    PreregisteredProtocol,
    ResearchBudget,
    SuccessCriteria,
)


def protocol(*, max_trials: int = 20) -> PreregisteredProtocol:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    return PreregisteredProtocol(
        name="fixture-program",
        version="1",
        researcher_id="fixture-researcher",
        hypothesis="mechanical fixture hypothesis, not alpha",
        snapshot_id="1" * 64,
        universe_hash="5" * 64,
        feature_schema_hash="6" * 64,
        cost_policy_hash="4" * 64,
        train=DateWindow(start=start, end=start + timedelta(days=100)),
        validation=DateWindow(start=start + timedelta(days=101), end=start + timedelta(days=150)),
        test=DateWindow(start=start + timedelta(days=151), end=start + timedelta(days=220)),
        parameter_ranges={},
        success=SuccessCriteria(
            minimum_oos_return=Decimal("0"),
            maximum_drawdown=Decimal("0.25"),
            minimum_dsr_probability=Decimal("0.95"),
            maximum_pbo=Decimal("0.20"),
            minimum_cost_stress_return=Decimal("0"),
            maximum_contribution_share=Decimal("0.35"),
            minimum_observations=30,
        ),
        budget=ResearchBudget(max_trials=max_trials, used_trials=0),
        benchmarks=("market",),
        purge_bars=1,
        embargo_bars=1,
    )


def authorized_manifest(
    registry: ExperimentRegistry,
    *,
    at: datetime,
    key: str = "fixture-trial",
    window_role: WindowRole = WindowRole.TEST,
    protocol_override: PreregisteredProtocol | None = None,
    **updates: object,
) -> ExperimentManifest:
    research_protocol = protocol_override or protocol()
    registry.register_protocol(research_protocol)
    parameters = updates.pop("parameters", {"slow": 20, "fast": 5})
    assert isinstance(parameters, dict)
    allocation = registry.allocate_trial(
        research_protocol.protocol_hash,
        parameters=parameters,
        window_role=window_role,
        idempotency_key=key,
        at=at,
    )
    payload: dict[str, object] = {
        "snapshot_id": research_protocol.snapshot_id,
        "code_hash": "2" * 64,
        "config_hash": "3" * 64,
        "cost_policy_hash": research_protocol.cost_policy_hash,
        "universe_hash": research_protocol.universe_hash,
        "metric_schema_version": "1",
        "seed": 7,
        "strategy_id": "baseline",
        "strategy_version": "1",
        "hypothesis": research_protocol.hypothesis,
        "parameters": parameters,
        "protocol_hash": allocation.protocol_hash,
        "trial_allocation_id": allocation.allocation_id,
        "parameter_point_hash": allocation.parameter_point_hash,
        "window_role": allocation.window_role,
        "research_program_id": allocation.research_program_id,
    }
    payload.update(updates)
    return ExperimentManifest.model_validate(payload)
