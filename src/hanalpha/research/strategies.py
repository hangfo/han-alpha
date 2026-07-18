from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import numpy as np

from hanalpha.domain.enums import Side
from hanalpha.research.context import ResearchContext
from hanalpha.simulation.engine import OrderProposal
from hanalpha.simulation.events import canonical_hash
from hanalpha.simulation.orders import OrderKind


def _proposal(
    *,
    context: ResearchContext,
    instrument_id: str,
    strategy_id: str,
    strategy_version: str,
    quantity: int,
    stop_fraction: float,
    target_r: float,
    evidence: object,
) -> OrderProposal:
    history = context.history(instrument_id)
    price = history[-1].close
    stop = price * (1 - stop_fraction)
    target = price + (price - stop) * target_r
    input_hash = canonical_hash(
        {
            "context": context.feature_hash,
            "instrument_id": instrument_id,
            "evidence": evidence,
        }
    )
    return OrderProposal(
        instrument_id=instrument_id,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        side=Side.BUY,
        kind=OrderKind.MARKET,
        quantity=quantity,
        planned_price=price,
        protective_stop=stop,
        protective_target=target,
        input_hash=input_hash,
        signal_hash=canonical_hash({"input_hash": input_hash, "side": "buy"}),
    )


class CrossSectionalMomentumStrategy:
    name = "cross-sectional-momentum"
    version = "1"

    def __init__(
        self,
        *,
        lookback_bars: int = 12,
        skip_bars: int = 1,
        top_n: int = 3,
        quantity: int = 10,
        minimum_dollar_volume: float = 0,
    ) -> None:
        if lookback_bars < 2 or skip_bars < 0 or top_n < 1 or quantity < 1:
            raise ValueError("invalid momentum parameters")
        self.lookback_bars = lookback_bars
        self.skip_bars = skip_bars
        self.top_n = top_n
        self.quantity = quantity
        self.minimum_dollar_volume = minimum_dollar_volume

    def evaluate(self, context: ResearchContext) -> list[OrderProposal]:
        held = {position.instrument_id for position in context.portfolio.positions}
        scores: list[tuple[float, str]] = []
        required = self.lookback_bars + self.skip_bars
        for item in context.histories:
            if item.instrument_id in held or len(item.bars) < required:
                continue
            start = item.bars[-required].close
            end = item.bars[-(self.skip_bars + 1)].close
            current = item.bars[-1]
            if current.close * current.volume < self.minimum_dollar_volume:
                continue
            scores.append((end / start - 1, item.instrument_id))
        winners = [
            item for item in sorted(scores, key=lambda row: (-row[0], row[1])) if item[0] > 0
        ]
        return [
            _proposal(
                context=context,
                instrument_id=instrument_id,
                strategy_id=self.name,
                strategy_version=self.version,
                quantity=self.quantity,
                stop_fraction=0.10,
                target_r=2,
                evidence={"momentum": score},
            )
            for score, instrument_id in winners[: self.top_n]
        ]


class SlowTrendStrategy:
    name = "slow-trend"
    version = "1"

    def __init__(
        self,
        *,
        fast_window: int = 50,
        slow_window: int = 200,
        quantity: int = 10,
        target_r: float = 2,
    ) -> None:
        if fast_window < 2 or slow_window <= fast_window or quantity < 1:
            raise ValueError("invalid trend parameters")
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.quantity = quantity
        self.target_r = target_r

    def evaluate(self, context: ResearchContext) -> list[OrderProposal]:
        held = {position.instrument_id for position in context.portfolio.positions}
        proposals: list[OrderProposal] = []
        for item in context.histories:
            if item.instrument_id in held or len(item.bars) < self.slow_window:
                continue
            closes = np.asarray([bar.close for bar in item.bars], dtype=float)
            fast = float(closes[-self.fast_window :].mean())
            slow = float(closes[-self.slow_window :].mean())
            if closes[-1] <= fast or fast <= slow:
                continue
            returns = np.diff(closes[-self.slow_window :]) / closes[-self.slow_window : -1]
            volatility = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0
            stop_fraction = min(0.25, max(0.05, volatility * 2))
            proposals.append(
                _proposal(
                    context=context,
                    instrument_id=item.instrument_id,
                    strategy_id=self.name,
                    strategy_version=self.version,
                    quantity=self.quantity,
                    stop_fraction=stop_fraction,
                    target_r=self.target_r,
                    evidence={"fast": fast, "slow": slow, "volatility": volatility},
                )
            )
        return proposals


class PEADStrategy:
    name = "pead-baseline"
    version = "1"

    def __init__(
        self,
        *,
        quantity: int = 10,
        minimum_surprise: Decimal = Decimal("0.05"),
        maximum_age_days: int = 5,
    ) -> None:
        self.quantity = quantity
        self.minimum_surprise = minimum_surprise
        self.maximum_age = timedelta(days=maximum_age_days)

    def evaluate(self, context: ResearchContext) -> list[OrderProposal]:
        held = {position.instrument_id for position in context.portfolio.positions}
        proposals: list[OrderProposal] = []
        for event in context.earnings_events:
            if event.instrument_id in held or not context.history(event.instrument_id):
                continue
            surprise = event.standardized_surprise
            if surprise is None or surprise < self.minimum_surprise:
                continue
            if context.as_of - event.available_at > self.maximum_age:
                continue
            proposals.append(
                _proposal(
                    context=context,
                    instrument_id=event.instrument_id,
                    strategy_id=self.name,
                    strategy_version=self.version,
                    quantity=self.quantity,
                    stop_fraction=0.08,
                    target_r=2,
                    evidence={
                        "event_id": event.event_id,
                        "expectation_snapshot_id": event.expectation_snapshot_id,
                        "surprise": str(surprise),
                    },
                )
            )
        return proposals
