from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
from pydantic import ValidationError

from hanalpha.research.protocol import (
    DateWindow,
    ParameterRange,
    PreregisteredProtocol,
    ResearchBudget,
    SuccessCriteria,
)
from hanalpha.research.statistics import (
    bootstrap_mean_interval,
    deflated_sharpe_ratio,
    holm_adjust,
    moving_block_bootstrap_interval,
    probability_of_backtest_overfitting,
)
from hanalpha.research.validation import (
    LabelInterval,
    purge_overlapping_labels,
    rolling_walk_forward,
)


def _protocol(**updates) -> PreregisteredProtocol:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    payload = {
        "name": "momentum-baseline",
        "version": "1",
        "researcher_id": "fixture-researcher",
        "hypothesis": "medium-term relative strength persists after costs",
        "snapshot_id": "1" * 64,
        "universe_hash": "2" * 64,
        "feature_schema_hash": "3" * 64,
        "cost_policy_hash": "4" * 64,
        "train": DateWindow(start=start, end=start + timedelta(days=365)),
        "validation": DateWindow(
            start=start + timedelta(days=366), end=start + timedelta(days=500)
        ),
        "test": DateWindow(start=start + timedelta(days=501), end=start + timedelta(days=700)),
        "parameter_ranges": {"lookback": ParameterRange(low=6, high=12)},
        "success": SuccessCriteria(
            minimum_oos_return=Decimal("0"),
            maximum_drawdown=Decimal("0.25"),
            minimum_dsr_probability=Decimal("0.95"),
            maximum_pbo=Decimal("0.20"),
            minimum_cost_stress_return=Decimal("0"),
            maximum_contribution_share=Decimal("0.35"),
            minimum_observations=60,
        ),
        "budget": ResearchBudget(max_trials=12, used_trials=0),
        "benchmarks": ("market", "equal_weight", "simple_momentum"),
        "purge_bars": 5,
        "embargo_bars": 5,
    }
    payload.update(updates)
    return PreregisteredProtocol.model_validate(payload)


def test_preregistration_hash_and_budget_are_immutable() -> None:
    protocol = _protocol()
    assert len(protocol.protocol_hash) == 64
    consumed = protocol.consume_trial()
    assert protocol.budget.used_trials == 0
    assert consumed.budget.used_trials == 1
    exhausted = protocol.model_copy(update={"budget": ResearchBudget(max_trials=1, used_trials=1)})
    with pytest.raises(RuntimeError, match="budget"):
        exhausted.consume_trial()


def test_preregistration_rejects_overlapping_windows() -> None:
    protocol = _protocol()
    with pytest.raises(ValidationError, match="window"):
        _protocol(
            validation=DateWindow(
                start=protocol.train.end - timedelta(days=1),
                end=protocol.validation.end,
            )
        )


def test_walk_forward_applies_purge_and_embargo() -> None:
    folds = rolling_walk_forward(
        observation_count=40,
        train_size=20,
        test_size=5,
        step=5,
        purge=2,
        embargo=3,
    )
    assert folds
    for fold in folds:
        assert max(fold.train_indices) + 2 < min(fold.test_indices)
        assert set(fold.train_indices).isdisjoint(fold.test_indices)


def test_statistics_fail_closed_on_small_samples_and_detect_overfit() -> None:
    small = deflated_sharpe_ratio([0.01] * 10, trial_sharpes=[0.1, 0.2])
    assert not small.sufficient
    rng = np.random.default_rng(7)
    returns = rng.normal(0.001, 0.01, 300).tolist()
    dsr = deflated_sharpe_ratio(returns, trial_sharpes=[0.1, 0.2, 0.3, 0.4])
    assert dsr.sufficient
    assert dsr.probability is not None
    matrix = np.column_stack(
        [
            np.linspace(-0.05, 0.08, 24),
            np.linspace(0.08, -0.05, 24),
            rng.normal(0, 0.01, 24),
        ]
    )
    pbo = probability_of_backtest_overfitting(matrix, partitions=6)
    assert pbo.sufficient
    assert pbo.probability is not None
    low, high = bootstrap_mean_interval(returns, seed=11, samples=500)
    assert low < high
    adjusted = holm_adjust([0.01, 0.04, 0.20])
    assert adjusted == sorted(adjusted)
    block_low, block_high = moving_block_bootstrap_interval(
        returns, block_length=10, seed=11, samples=500
    )
    assert block_low < block_high


def test_event_interval_purge_removes_only_overlapping_labels() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    train = (
        LabelInterval(
            observation_id="safe",
            information_start=start,
            label_end=start + timedelta(days=2),
        ),
        LabelInterval(
            observation_id="overlap",
            information_start=start + timedelta(days=4),
            label_end=start + timedelta(days=7),
        ),
    )
    test = (
        LabelInterval(
            observation_id="test",
            information_start=start + timedelta(days=6),
            label_end=start + timedelta(days=8),
        ),
    )
    assert [item.observation_id for item in purge_overlapping_labels(train, test)] == ["safe"]
