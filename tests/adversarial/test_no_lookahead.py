from datetime import timedelta

from hanalpha.config import StrategyConfig
from hanalpha.domain.enums import SignalAction
from hanalpha.domain.models import Catalyst
from hanalpha.strategies.event import EventContinuationStrategy


def test_future_catalyst_not_visible(now) -> None:
    strategy = EventContinuationStrategy(
        StrategyConfig(
            enabled=True,
            min_catalyst_score=0.7,
            max_catalyst_age_hours=48,
            stop_atr=2,
            target_r_multiple=3,
        )
    )
    catalyst = Catalyst(
        symbol="NVDA",
        category="future",
        score=0.9,
        direction=SignalAction.BUY,
        published_at=now - timedelta(minutes=1),
        available_at=now,
        headline="Available only at now",
        evidence_ids=["future-1"],
    )
    # The decision is one second before availability, so the event cannot be used.
    result = strategy.generate(
        symbol="NVDA",
        bars=[],
        benchmark_bars=[],
        catalysts=[catalyst],
        now=now - timedelta(seconds=1),
    )
    assert result is None
