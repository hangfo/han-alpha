from datetime import UTC, datetime, timedelta

from hanalpha.domain.enums import MarketRegime
from hanalpha.domain.models import Bar
from hanalpha.regime import RegimeEngine


def make_bars(symbol: str, start: float, drift: float) -> list[Bar]:
    now = datetime.now(UTC) - timedelta(minutes=5 * 80)
    bars = []
    price = start
    for index in range(80):
        next_price = price * (1 + drift)
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=now + timedelta(minutes=5 * index),
                open=price,
                high=max(price, next_price) * 1.001,
                low=min(price, next_price) * 0.999,
                close=next_price,
                volume=1_000_000,
            )
        )
        price = next_price
    return bars


def test_regime_risk_on() -> None:
    engine = RegimeEngine()
    result = engine.evaluate(
        market_bars=make_bars("SPY", 100, 0.002),
        growth_bars=make_bars("QQQ", 100, 0.0025),
        now=datetime.now(UTC),
    )
    assert result.regime == MarketRegime.RISK_ON
    assert "breakout" in result.allowed_strategies


def test_regime_unknown_with_short_history() -> None:
    engine = RegimeEngine()
    bars = make_bars("SPY", 100, 0.001)[:20]
    result = engine.evaluate(market_bars=bars, growth_bars=bars, now=datetime.now(UTC))
    assert result.regime == MarketRegime.UNKNOWN
    assert result.risk_multiplier == 0
