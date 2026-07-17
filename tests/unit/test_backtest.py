from datetime import UTC, datetime, timedelta

import pytest

from hanalpha.backtest import BacktestEngine
from hanalpha.data.synthetic import SyntheticMarketDataProvider
from hanalpha.domain.enums import SignalAction
from hanalpha.domain.models import Bar, Signal
from hanalpha.strategies import BreakoutStrategy


@pytest.mark.asyncio
async def test_backtest_runs_without_lookahead_crash(risk_config) -> None:
    provider = SyntheticMarketDataProvider(risk_config.bar_interval_minutes)
    bars = await provider.get_bars("NVDA", 1000)
    benchmark = await provider.get_bars("SPY", 1000)
    engine = BacktestEngine()
    metrics, trades = engine.run(
        symbol="NVDA",
        bars=bars,
        benchmark_bars=benchmark,
        strategy=BreakoutStrategy(risk_config.strategies["breakout"]),
    )
    assert metrics.ending_equity > 0
    assert metrics.trades == len(trades)
    assert metrics.max_drawdown >= 0


def test_backtest_rejects_misaligned_inputs(risk_config) -> None:
    engine = BacktestEngine()
    with pytest.raises(ValueError, match="aligned"):
        engine.run(
            symbol="NVDA",
            bars=[],
            benchmark_bars=[object()],  # type: ignore[list-item]
            strategy=BreakoutStrategy(risk_config.strategies["breakout"]),
        )


class _OneShotStrategy:
    name = "one-shot"

    def __init__(self, stop: float = 95, target: float = 150) -> None:
        self.fired = False
        self.stop = stop
        self.target = target

    def generate(self, *, symbol, bars, benchmark_bars, catalysts, now):
        if self.fired:
            return None
        self.fired = True
        return Signal(
            signal_id="one-shot-signal",
            symbol=symbol,
            strategy=self.name,
            action=SignalAction.BUY,
            generated_at=now,
            confidence=1,
            reference_price=100,
            stop_price=self.stop,
            target_price=self.target,
        )


def _bars(values: list[tuple[float, float, float, float]]) -> list[Bar]:
    start = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    return [
        Bar(
            symbol="TEST",
            timestamp=start + timedelta(minutes=index),
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=1000,
        )
        for index, (open_, high, low, close) in enumerate(values)
    ]


def test_next_bar_entry_is_not_marked_in_prior_bar_equity() -> None:
    bars = _bars([(100, 101, 99, 100), (100, 101, 99, 100), (100, 121, 99, 120)])
    engine = BacktestEngine(starting_cash=10_000, slippage_bps=0)
    engine.run(
        symbol="TEST",
        bars=bars,
        benchmark_bars=bars,
        strategy=_OneShotStrategy(stop=90, target=200),
        warmup=1,
    )
    assert engine.last_equity_curve[1] == (bars[1].timestamp, 10_000)
    assert engine.last_equity_curve[2][1] > 10_000


def test_gap_through_stop_fills_from_adverse_open() -> None:
    bars = _bars(
        [
            (100, 101, 99, 100),
            (100, 101, 99, 100),
            (100, 104, 98, 102),
            (80, 85, 75, 82),
        ]
    )
    engine = BacktestEngine(starting_cash=10_000, slippage_bps=5)
    _, trades = engine.run(
        symbol="TEST",
        bars=bars,
        benchmark_bars=bars,
        strategy=_OneShotStrategy(stop=95, target=150),
        warmup=1,
    )
    assert trades[0].reason == "stop_gap"
    assert trades[0].exit_price < 80
