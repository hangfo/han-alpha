from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hanalpha.pit.models import HASH_PATTERN, require_aware
from hanalpha.simulation.events import ReplayFrame, SimulationBar, canonical_hash
from hanalpha.simulation.portfolio import PortfolioSnapshot


class EarningsEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    instrument_id: str
    announced_at: datetime
    available_at: datetime
    actual_eps: Decimal
    consensus_eps: Decimal
    expectation_snapshot_id: str = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_times(self) -> EarningsEvent:
        require_aware(self.announced_at, "announced_at")
        require_aware(self.available_at, "available_at")
        if self.available_at < self.announced_at:
            raise ValueError("earnings availability cannot precede announcement")
        return self

    @property
    def standardized_surprise(self) -> Decimal | None:
        if self.consensus_eps == 0:
            return None
        return (self.actual_eps - self.consensus_eps) / abs(self.consensus_eps)


class InstrumentHistory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument_id: str
    bars: tuple[SimulationBar, ...]

    @model_validator(mode="after")
    def validate_history(self) -> InstrumentHistory:
        if any(bar.instrument_id != self.instrument_id for bar in self.bars):
            raise ValueError("history contains a different instrument")
        ordering = [(bar.event_time, bar.available_at, bar.source_record_id) for bar in self.bars]
        if ordering != sorted(ordering):
            raise ValueError("history bars must be monotonic")
        return self


class ResearchContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str = Field(pattern=HASH_PATTERN)
    as_of: datetime
    current_bars: tuple[SimulationBar, ...]
    histories: tuple[InstrumentHistory, ...]
    knowledge_revisions: tuple[SimulationBar, ...]
    earnings_events: tuple[EarningsEvent, ...]
    portfolio: PortfolioSnapshot

    @model_validator(mode="after")
    def validate_context(self) -> ResearchContext:
        require_aware(self.as_of, "as_of")
        bars = [
            *self.current_bars,
            *self.knowledge_revisions,
            *(bar for history in self.histories for bar in history.bars),
        ]
        if any(bar.snapshot_id != self.snapshot_id for bar in bars):
            raise ValueError("research context mixes snapshots")
        if any(bar.available_at > self.as_of for bar in bars):
            raise ValueError("research context contains future bar knowledge")
        if any(event.available_at > self.as_of for event in self.earnings_events):
            raise ValueError("research context contains future earnings knowledge")
        return self

    @property
    def feature_hash(self) -> str:
        return canonical_hash(
            {
                "snapshot_id": self.snapshot_id,
                "as_of": self.as_of,
                "histories": [item.model_dump(mode="json") for item in self.histories],
                "earnings_events": [item.model_dump(mode="json") for item in self.earnings_events],
            }
        )

    def history(self, instrument_id: str) -> tuple[SimulationBar, ...]:
        return next(
            (item.bars for item in self.histories if item.instrument_id == instrument_id),
            (),
        )


class ResearchContextBuilder:
    def __init__(self) -> None:
        self._bars: dict[tuple[str, str], SimulationBar] = {}

    def build(
        self,
        frame: ReplayFrame,
        portfolio: PortfolioSnapshot,
        *,
        earnings_events: tuple[EarningsEvent, ...] = (),
    ) -> ResearchContext:
        for bar in [*frame.bars, *frame.bar_revisions]:
            key = (bar.instrument_id, bar.source_record_id)
            current = self._bars.get(key)
            if current is None or bar.source_revision > current.source_revision:
                self._bars[key] = bar
        instruments = sorted({key[0] for key in self._bars})
        histories = tuple(
            InstrumentHistory(
                instrument_id=instrument_id,
                bars=tuple(
                    sorted(
                        (
                            bar
                            for (candidate, _), bar in self._bars.items()
                            if candidate == instrument_id
                        ),
                        key=lambda item: (
                            item.event_time,
                            item.available_at,
                            item.source_record_id,
                        ),
                    )
                ),
            )
            for instrument_id in instruments
        )
        visible_events = tuple(
            sorted(
                (event for event in earnings_events if event.available_at <= frame.as_of),
                key=lambda item: (item.available_at, item.event_id),
            )
        )
        return ResearchContext(
            snapshot_id=frame.snapshot_id,
            as_of=frame.as_of,
            current_bars=tuple(frame.bars),
            histories=histories,
            knowledge_revisions=tuple(frame.bar_revisions),
            earnings_events=visible_events,
            portfolio=portfolio,
        )
