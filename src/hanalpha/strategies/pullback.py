from __future__ import annotations

from datetime import datetime

from hanalpha.config import StrategyConfig
from hanalpha.domain.enums import SignalAction
from hanalpha.domain.models import Bar, Catalyst, Signal
from hanalpha.features.technical import atr, closes, relative_strength, rsi, sma
from hanalpha.strategies.common import signal_id


class TrendPullbackStrategy:
    name = "trend_pullback"

    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

    def generate(
        self,
        *,
        symbol: str,
        bars: list[Bar],
        benchmark_bars: list[Bar],
        catalysts: list[Catalyst],
        now: datetime,
    ) -> Signal | None:
        if not self.config.enabled:
            return None
        trend_window = self.config.trend_window or 50
        pullback_window = self.config.pullback_window or 10
        required = max(trend_window + 2, self.config.atr_window + 2, pullback_window + 2)
        if len(bars) < required:
            return None
        prices = closes(bars)
        current = float(prices[-1])
        trend_ma = sma(prices, trend_window)
        short_ma = sma(prices, pullback_window)
        previous_close = float(prices[-2])
        current_rsi = rsi(bars, min(14, len(bars) - 1))
        rel_strength = relative_strength(bars, benchmark_bars, min(20, len(bars) - 1))
        trend_ok = current > trend_ma and rel_strength > -0.01
        recovery = previous_close <= short_ma and current > short_ma
        not_overbought = current_rsi < 72
        if not (trend_ok and recovery and not_overbought):
            return None
        current_atr = atr(bars, self.config.atr_window)
        stop = current - current_atr * self.config.stop_atr
        risk = current - stop
        target = current + risk * self.config.target_r_multiple
        confidence = min(0.9, 0.58 + max(0.0, rel_strength) * 2 + max(0.0, 65 - current_rsi) / 250)
        return Signal(
            signal_id=signal_id(self.name, symbol, now),
            symbol=symbol,
            strategy=self.name,
            action=SignalAction.BUY,
            generated_at=now,
            confidence=confidence,
            reference_price=current,
            stop_price=stop,
            target_price=target,
            score_components={
                "relative_strength": rel_strength,
                "rsi": current_rsi,
                "distance_to_trend_ma": current / trend_ma - 1,
            },
            evidence_ids=[],
            metadata={"trend_ma": trend_ma, "short_ma": short_ma, "atr": current_atr},
        )
