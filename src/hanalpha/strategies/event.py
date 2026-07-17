from __future__ import annotations

from datetime import datetime, timedelta

from hanalpha.config import StrategyConfig
from hanalpha.domain.enums import SignalAction
from hanalpha.domain.models import Bar, Catalyst, Signal
from hanalpha.features.technical import atr, relative_strength
from hanalpha.strategies.common import signal_id


class EventContinuationStrategy:
    name = "event_continuation"

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
        if not self.config.enabled or len(bars) < self.config.atr_window + 2:
            return None
        min_score = self.config.min_catalyst_score or 0.7
        max_age = timedelta(hours=self.config.max_catalyst_age_hours or 48)
        eligible = [
            item
            for item in catalysts
            if item.direction == SignalAction.BUY
            and item.score >= min_score
            and item.available_at <= now
            and now - item.available_at <= max_age
        ]
        if not eligible:
            return None
        best = max(eligible, key=lambda item: item.score)
        current = bars[-1].close
        current_atr = atr(bars, self.config.atr_window)
        rel_strength = relative_strength(bars, benchmark_bars, min(20, len(bars) - 1))
        if rel_strength < -0.03:
            return None
        stop = current - current_atr * self.config.stop_atr
        risk = current - stop
        target = current + risk * self.config.target_r_multiple
        confidence = min(0.95, 0.55 + best.score * 0.35 + max(0.0, rel_strength))
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
            score_components={"catalyst_score": best.score, "relative_strength": rel_strength},
            evidence_ids=best.evidence_ids,
            metadata={"headline": best.headline, "category": best.category, "atr": current_atr},
        )
