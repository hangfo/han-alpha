from __future__ import annotations

from typing import Protocol

from hanalpha.research.context import EarningsEvent, ResearchContext, ResearchContextBuilder
from hanalpha.simulation.engine import OrderProposal
from hanalpha.simulation.events import ReplayFrame
from hanalpha.simulation.portfolio import PortfolioSnapshot


class ResearchStrategy(Protocol):
    name: str
    version: str

    def evaluate(self, context: ResearchContext) -> list[OrderProposal]: ...


class ResearchPolicyAdapter:
    """Stateful bridge from replay frames to immutable strategy contexts."""

    def __init__(
        self,
        strategy: ResearchStrategy,
        *,
        earnings_events: tuple[EarningsEvent, ...] = (),
    ) -> None:
        self.strategy = strategy
        self.name = strategy.name
        self.version = strategy.version
        self.earnings_events = earnings_events
        self._builder = ResearchContextBuilder()

    def propose(self, frame: ReplayFrame, portfolio: PortfolioSnapshot) -> list[OrderProposal]:
        context = self._builder.build(
            frame,
            portfolio,
            earnings_events=self.earnings_events,
        )
        return self.strategy.evaluate(context)
