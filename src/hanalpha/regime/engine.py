from __future__ import annotations

from datetime import datetime

from hanalpha.domain.enums import MarketRegime
from hanalpha.domain.models import Bar, RegimeSnapshot
from hanalpha.features.technical import closes, relative_strength, sma


class RegimeEngine:
    def evaluate(
        self,
        *,
        market_bars: list[Bar],
        growth_bars: list[Bar],
        now: datetime,
    ) -> RegimeSnapshot:
        if len(market_bars) < 60 or len(growth_bars) < 60:
            return RegimeSnapshot(
                regime=MarketRegime.UNKNOWN,
                timestamp=now,
                risk_multiplier=0.0,
                max_gross_exposure=0.0,
                allowed_strategies=[],
                metrics={"reason": "insufficient_bars"},
            )
        market_close = closes(market_bars)
        growth_close = closes(growth_bars)
        market_fast = sma(market_close, 20)
        market_slow = sma(market_close, 50)
        growth_fast = sma(growth_close, 20)
        growth_slow = sma(growth_close, 50)
        growth_relative = relative_strength(growth_bars, market_bars, 20)
        risk_on_votes = sum(
            [
                market_close[-1] > market_fast > market_slow,
                growth_close[-1] > growth_fast > growth_slow,
                growth_relative > -0.01,
            ]
        )
        if risk_on_votes == 3:
            regime = MarketRegime.RISK_ON
            multiplier = 1.0
            gross = 0.50
            allowed = ["breakout", "trend_pullback", "event_continuation"]
        elif risk_on_votes >= 1:
            regime = MarketRegime.NEUTRAL
            multiplier = 0.55
            gross = 0.30
            allowed = ["trend_pullback", "event_continuation"]
        else:
            regime = MarketRegime.RISK_OFF
            multiplier = 0.15
            gross = 0.10
            allowed = ["event_continuation"]
        return RegimeSnapshot(
            regime=regime,
            timestamp=now,
            risk_multiplier=multiplier,
            max_gross_exposure=gross,
            allowed_strategies=allowed,
            metrics={
                "market_fast_slow_spread": market_fast / market_slow - 1,
                "growth_fast_slow_spread": growth_fast / growth_slow - 1,
                "growth_relative_strength": growth_relative,
            },
        )
