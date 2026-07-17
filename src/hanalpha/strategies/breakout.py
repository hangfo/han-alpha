from __future__ import annotations

from datetime import datetime

from hanalpha.config import StrategyConfig
from hanalpha.domain.enums import SignalAction
from hanalpha.domain.models import Bar, Catalyst, Signal
from hanalpha.features.technical import (
    atr,
    closes,
    relative_strength,
    rolling_high,
    sma,
    volumes,
    zscore_last,
)
from hanalpha.strategies.common import signal_id


class BreakoutStrategy:
    name = "breakout"

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
        fast = self.config.fast_window or 20
        slow = self.config.slow_window or 55
        if len(bars) < max(slow + 2, self.config.atr_window + 2):
            return None
        prices = closes(bars)
        current = float(prices[-1])
        prior_high = rolling_high(prices, fast, exclude_last=True)
        current_atr = atr(bars, self.config.atr_window)
        buffer_atr = self.config.breakout_buffer_atr or 0.0
        trend_ok = sma(prices, fast) > sma(prices, slow)
        breakout_ok = current > prior_high + current_atr * buffer_atr
        rel_strength = relative_strength(bars, benchmark_bars, min(fast, 20))
        volume_z = zscore_last(volumes(bars).tolist(), min(20, len(bars)))
        if not (trend_ok and breakout_ok and rel_strength > 0 and volume_z > -0.5):
            return None
        stop = current - current_atr * self.config.stop_atr
        risk = current - stop
        target = current + risk * self.config.target_r_multiple
        confidence = min(0.95, 0.55 + min(rel_strength * 4, 0.2) + max(0.0, volume_z) * 0.03)
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
                "volume_z": volume_z,
                "trend_spread": sma(prices, fast) / sma(prices, slow) - 1,
            },
            evidence_ids=[],
            metadata={"prior_high": prior_high, "atr": current_atr},
        )
