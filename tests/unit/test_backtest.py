import pytest

from hanalpha.backtest import BacktestEngine
from hanalpha.data.synthetic import SyntheticMarketDataProvider
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
