from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hanalpha.config import StrategyConfig
from hanalpha.domain.enums import SignalAction
from hanalpha.domain.models import Bar, Catalyst
from hanalpha.features.technical import (
    atr,
    average_dollar_volume,
    closes,
    highs,
    lows,
    relative_strength,
    rolling_high,
    rolling_low,
    rsi,
    sma,
    volumes,
    zscore_last,
)
from hanalpha.strategies.event import EventContinuationStrategy
from hanalpha.strategies.pullback import TrendPullbackStrategy


def _bars(closes_: list[float], *, symbol: str = "TEST") -> list[Bar]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Bar(
            symbol=symbol,
            timestamp=start + timedelta(days=index),
            open=value,
            high=value + 1,
            low=value - 1,
            close=value,
            volume=1000 + index,
        )
        for index, value in enumerate(closes_)
    ]


def test_technical_features_cover_valid_and_failure_boundaries() -> None:
    bars = _bars([100 + index for index in range(25)])
    assert closes(bars)[-1] == 124
    assert highs(bars)[-1] == 125
    assert lows(bars)[-1] == 123
    assert volumes(bars)[-1] == 1024
    assert sma([1, 2, 3], 2) == 2.5
    assert rolling_high([1, 5, 3], 2) == 5
    assert rolling_high([1, 5, 3], 2, exclude_last=True) == 5
    assert rolling_low([1, 5, 3], 2) == 3
    assert rolling_low([1, 5, 3], 2, exclude_last=True) == 1
    assert atr(bars, 14) > 0
    assert rsi(bars, 14) == 100
    assert relative_strength(bars, _bars([100] * 25), 20) > 0
    assert average_dollar_volume(bars, 20) > 100_000
    assert zscore_last([1, 1, 1], 3) == 0
    assert zscore_last([1, 2, 3], 3) > 0
    for operation in (
        lambda: sma([1], 2),
        lambda: rolling_high([1], 2),
        lambda: rolling_low([1], 2),
        lambda: atr(bars[:5], 14),
        lambda: rsi(bars[:5], 14),
        lambda: relative_strength(bars[:5], bars[:5], 20),
        lambda: average_dollar_volume(bars[:5], 20),
        lambda: zscore_last([1], 2),
    ):
        with pytest.raises(ValueError, match="insufficient"):
            operation()


def test_event_strategy_abstains_on_bad_evidence_and_emits_typed_signal() -> None:
    now = datetime(2024, 2, 1, tzinfo=UTC)
    bars = _bars([100 + index for index in range(25)])
    config = StrategyConfig(atr_window=14, min_catalyst_score=0.7)
    strategy = EventContinuationStrategy(config)
    assert (
        strategy.generate(symbol="TEST", bars=bars, benchmark_bars=bars, catalysts=[], now=now)
        is None
    )
    catalyst = Catalyst(
        symbol="TEST",
        category="earnings",
        score=0.8,
        direction=SignalAction.BUY,
        published_at=now - timedelta(hours=2),
        available_at=now - timedelta(hours=1),
        headline="raised guidance",
        evidence_ids=["evidence-1"],
    )
    signal = strategy.generate(
        symbol="TEST", bars=bars, benchmark_bars=bars, catalysts=[catalyst], now=now
    )
    assert signal is not None
    assert signal.evidence_ids == ["evidence-1"]
    assert (
        EventContinuationStrategy(config.model_copy(update={"enabled": False})).generate(
            symbol="TEST", bars=bars, benchmark_bars=bars, catalysts=[catalyst], now=now
        )
        is None
    )


def test_pullback_strategy_abstention_boundaries() -> None:
    now = datetime(2024, 2, 1, tzinfo=UTC)
    bars = _bars([100 + index for index in range(25)])
    disabled = TrendPullbackStrategy(StrategyConfig(enabled=False))
    assert (
        disabled.generate(symbol="TEST", bars=bars, benchmark_bars=bars, catalysts=[], now=now)
        is None
    )
    short = TrendPullbackStrategy(StrategyConfig(trend_window=20, pullback_window=5, atr_window=14))
    assert (
        short.generate(
            symbol="TEST", bars=bars[:10], benchmark_bars=bars[:10], catalysts=[], now=now
        )
        is None
    )
