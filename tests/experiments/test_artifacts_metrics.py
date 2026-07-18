from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from hanalpha.experiments.artifacts import ResultBundleWriter
from hanalpha.experiments.models import ExperimentManifest, ExperimentResult, WindowRole
from hanalpha.metrics.portfolio import EquityPoint, compute_portfolio_metrics
from hanalpha.simulation.events import canonical_hash


def _manifest() -> ExperimentManifest:
    return ExperimentManifest(
        snapshot_id="1" * 64,
        code_hash="2" * 64,
        config_hash="3" * 64,
        cost_policy_hash="4" * 64,
        universe_hash="5" * 64,
        metric_schema_version="1",
        seed=7,
        strategy_id="baseline",
        strategy_version="1",
        hypothesis="fixture mechanics only",
        parameters={},
        protocol_hash="8" * 64,
        trial_allocation_id="9" * 64,
        parameter_point_hash=canonical_hash({}),
        window_role=WindowRole.TEST,
        research_program_id="a" * 64,
    )


def test_metrics_and_result_bundle_are_deterministic(tmp_path) -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    points = [
        EquityPoint(
            as_of=start + timedelta(days=index),
            net_liquidation=Decimal(value),
            cash=Decimal("1000"),
            gross_exposure=Decimal("0.5") if index else Decimal("0"),
        )
        for index, value in enumerate(("10000", "10500", "10200", "11000"))
    ]
    metrics = compute_portfolio_metrics(points, total_traded_notional=Decimal("12000"))
    assert metrics.total_return == Decimal("0.1")
    assert metrics.max_drawdown > 0
    result = ExperimentResult(
        experiment_id=_manifest().experiment_id,
        event_hash="6" * 64,
        equity_hash="7" * 64,
        metrics=metrics,
        equity_points=points,
        fill_count=4,
    )
    first = ResultBundleWriter().write(_manifest(), result, tmp_path / "first")
    second = ResultBundleWriter().write(_manifest(), result, tmp_path / "second")
    assert first == second
    assert (tmp_path / "first" / "report.html").read_text() == (
        tmp_path / "second" / "report.html"
    ).read_text()


def test_result_bundle_refuses_to_overwrite_different_content(tmp_path) -> None:
    directory = tmp_path / "result"
    manifest = _manifest()
    point = EquityPoint(
        as_of=datetime(2024, 1, 1, tzinfo=UTC),
        net_liquidation=Decimal("10000"),
        cash=Decimal("10000"),
        gross_exposure=Decimal("0"),
    )
    result = ExperimentResult(
        experiment_id=manifest.experiment_id,
        event_hash="6" * 64,
        equity_hash="7" * 64,
        metrics=compute_portfolio_metrics([point], total_traded_notional=Decimal("0")),
        equity_points=[point],
        fill_count=0,
    )
    ResultBundleWriter().write(manifest, result, directory)
    with pytest.raises(RuntimeError, match="immutable"):
        ResultBundleWriter().write(
            manifest,
            result.model_copy(update={"event_hash": "8" * 64}),
            directory,
        )


def test_metrics_are_time_weighted_and_require_strict_time() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    points = [
        EquityPoint(
            as_of=start,
            net_liquidation=Decimal("100"),
            cash=Decimal("100"),
            gross_exposure=Decimal("1"),
        ),
        EquityPoint(
            as_of=start + timedelta(hours=1),
            net_liquidation=Decimal("90"),
            cash=Decimal("90"),
            gross_exposure=Decimal("0"),
        ),
        EquityPoint(
            as_of=start + timedelta(hours=4),
            net_liquidation=Decimal("95"),
            cash=Decimal("95"),
            gross_exposure=Decimal("0"),
        ),
    ]
    metrics = compute_portfolio_metrics(points, total_traded_notional=Decimal("0"))
    assert metrics.average_gross_exposure == Decimal("0.3333333333333333333333333333")
    assert metrics.time_weighted_exposure_ratio == Decimal("0.25")
    assert metrics.time_in_market == Decimal("0.25")
    assert metrics.time_under_water == Decimal("0.75")
    assert metrics.expected_shortfall_95 is not None
    with pytest.raises(ValueError, match="strictly"):
        compute_portfolio_metrics([points[0], points[0]], total_traded_notional=Decimal("0"))
