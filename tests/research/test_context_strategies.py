from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from hanalpha.research.context import (
    EarningsEvent,
    InstrumentHistory,
    ResearchContext,
    ResearchContextBuilder,
)
from hanalpha.research.strategies import (
    CrossSectionalMomentumStrategy,
    PEADStrategy,
    SlowTrendStrategy,
)
from hanalpha.simulation.events import ReplayFrame
from hanalpha.simulation.portfolio import PortfolioLedger, PortfolioPolicy


def test_research_context_applies_revision_to_knowledge_not_current_market(
    simulation_time, simulation_bar
) -> None:
    ledger = PortfolioLedger(Decimal("10000"), PortfolioPolicy())
    builder = ResearchContextBuilder()
    first = builder.build(
        ReplayFrame(
            snapshot_id="1" * 64,
            as_of=simulation_bar.available_at,
            bars=[simulation_bar],
        ),
        ledger.snapshot(simulation_bar.available_at),
    )
    revision = simulation_bar.model_copy(
        update={
            "source_revision": 2,
            "close": 103,
            "available_at": simulation_bar.available_at + timedelta(days=1),
        }
    )
    second = builder.build(
        ReplayFrame(
            snapshot_id="1" * 64,
            as_of=revision.available_at,
            bars=[],
            bar_revisions=[revision],
        ),
        ledger.snapshot(revision.available_at),
    )
    assert first.history("inst-alpha")[-1].close == 102
    assert second.history("inst-alpha")[-1].close == 103
    assert second.current_bars == ()
    assert second.knowledge_revisions == (revision,)
    assert first.feature_hash != second.feature_hash


def _context(simulation_time, histories, events=()) -> ResearchContext:
    ledger = PortfolioLedger(Decimal("100000"), PortfolioPolicy())
    as_of = max(
        simulation_time,
        *(bar.available_at for history in histories for bar in history.bars),
        *(event.available_at for event in events),
    )
    return ResearchContext(
        snapshot_id="1" * 64,
        as_of=as_of,
        current_bars=tuple(history.bars[-1] for history in histories),
        histories=tuple(histories),
        knowledge_revisions=(),
        earnings_events=events,
        portfolio=ledger.snapshot(as_of),
    )


def test_momentum_ranks_only_sufficient_liquid_histories(simulation_time, simulation_bar) -> None:
    def history(instrument: str, closes: tuple[float, ...]) -> InstrumentHistory:
        bars = tuple(
            simulation_bar.model_copy(
                update={
                    "instrument_id": instrument,
                    "source_record_id": f"{instrument}-{index}",
                    "event_time": simulation_time - timedelta(days=len(closes) - index),
                    "available_at": simulation_time - timedelta(days=len(closes) - index),
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1_000_000,
                }
            )
            for index, close in enumerate(closes)
        )
        return InstrumentHistory(instrument_id=instrument, bars=bars)

    context = _context(
        simulation_time,
        (
            history("winner", (100, 105, 110, 120)),
            history("flat", (100, 100, 100, 100)),
            history("loser", (100, 95, 90, 80)),
        ),
    )
    proposals = CrossSectionalMomentumStrategy(
        lookback_bars=3, skip_bars=1, top_n=1, quantity=10
    ).evaluate(context)
    assert [proposal.instrument_id for proposal in proposals] == ["winner"]


def test_slow_trend_requires_positive_trend_and_builds_protected_candidate(
    simulation_time, simulation_bar
) -> None:
    bars = tuple(
        simulation_bar.model_copy(
            update={
                "source_record_id": f"trend-{index}",
                "event_time": simulation_time - timedelta(days=6 - index),
                "available_at": simulation_time - timedelta(days=6 - index),
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
            }
        )
        for index, close in enumerate((90, 92, 94, 97, 100, 104))
    )
    context = _context(
        simulation_time,
        (InstrumentHistory(instrument_id="inst-alpha", bars=bars),),
    )
    proposal = SlowTrendStrategy(fast_window=2, slow_window=5, quantity=5).evaluate(context)[0]
    assert proposal.protective_stop < proposal.planned_price
    assert proposal.protective_target > proposal.planned_price


def test_pead_abstains_without_pit_expectations_and_trades_only_fresh_surprise(
    simulation_time, simulation_bar
) -> None:
    history = InstrumentHistory(instrument_id="inst-alpha", bars=(simulation_bar,))
    strategy = PEADStrategy(quantity=5, minimum_surprise=Decimal("0.05"))
    assert strategy.evaluate(_context(simulation_time, (history,))) == []
    event = EarningsEvent(
        event_id="earnings-1",
        instrument_id="inst-alpha",
        announced_at=simulation_time - timedelta(hours=1),
        available_at=simulation_time - timedelta(minutes=59),
        actual_eps=Decimal("1.10"),
        consensus_eps=Decimal("1.00"),
        expectation_snapshot_id="e" * 64,
    )
    proposals = strategy.evaluate(_context(simulation_time, (history,), (event,)))
    assert len(proposals) == 1
    assert proposals[0].instrument_id == "inst-alpha"
