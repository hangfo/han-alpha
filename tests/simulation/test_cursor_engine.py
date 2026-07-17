from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from hanalpha.data.fixtures import run_fixture_pipeline
from hanalpha.domain.enums import Side
from hanalpha.pit.canonical_store import CanonicalStore
from hanalpha.pit.catalog import PITCatalog
from hanalpha.pit.repository import AsOfRepository
from hanalpha.simulation.engine import (
    OrderProposal,
    PITEventCursor,
    PortfolioReplayEngine,
)
from hanalpha.simulation.events import ReplayFrame, SimulationBar
from hanalpha.simulation.fills import FillPolicy, HistoricalExchange
from hanalpha.simulation.orders import OrderKind, SimulationOrderState
from hanalpha.simulation.parity import ParityHarness
from hanalpha.simulation.portfolio import PortfolioPolicy

FIXTURE_ROOT = Path(__file__).parents[1] / "pit" / "fixtures" / "v1"


class BuyOncePolicy:
    name = "buy-once"
    version = "1"

    def __init__(self) -> None:
        self.called = 0

    def propose(self, frame, portfolio):
        self.called += 1
        if self.called != 1:
            return []
        bar = frame.bars[0]
        return [
            OrderProposal(
                instrument_id=bar.instrument_id,
                strategy_id=self.name,
                strategy_version=self.version,
                side=Side.BUY,
                kind=OrderKind.MARKET,
                quantity=10,
                planned_price=bar.close,
                protective_stop=bar.close * 0.9,
                input_hash="2" * 64,
                signal_hash="3" * 64,
            )
        ]


class TwoCandidatePolicy:
    name = "two-candidate"
    version = "1"

    def propose(self, frame, portfolio):
        if portfolio.positions:
            return []
        return [
            OrderProposal(
                instrument_id=instrument_id,
                strategy_id=self.name,
                strategy_version=self.version,
                side=Side.BUY,
                kind=OrderKind.MARKET,
                quantity=6,
                planned_price=100,
                protective_stop=90,
                input_hash=str(index + 5) * 64,
                signal_hash=str(index + 7) * 64,
            )
            for index, instrument_id in enumerate(("inst-alpha", "inst-beta"))
        ]


class ExpiringLimitPolicy:
    name = "expiring-limit"
    version = "1"

    def __init__(self) -> None:
        self.called = False

    def propose(self, frame, portfolio):
        if self.called:
            return []
        self.called = True
        return [
            OrderProposal(
                instrument_id="inst-alpha",
                strategy_id=self.name,
                strategy_version=self.version,
                side=Side.BUY,
                kind=OrderKind.LIMIT,
                quantity=5,
                planned_price=50,
                limit_price=50,
                protective_stop=45,
                expires_at=frame.as_of + timedelta(seconds=30),
                input_hash="8" * 64,
                signal_hash="9" * 64,
            )
        ]


def test_pit_cursor_exposes_revisions_only_when_available(tmp_path) -> None:
    state = tmp_path / "state"
    result = run_fixture_pipeline(FIXTURE_ROOT, state)
    catalog = PITCatalog(state / "catalog.sqlite3")
    try:
        cursor = PITEventCursor(
            AsOfRepository(catalog, CanonicalStore(state / "canonical")), result.snapshot_id
        )
        frames = cursor.frames(
            ["inst-alpha"],
            [
                datetime(2024, 1, 2, 14, 31, tzinfo=UTC),
                datetime(2024, 1, 2, 14, 32, tzinfo=UTC),
                datetime(2024, 1, 4, tzinfo=UTC),
            ],
        )
        assert [[bar.source_revision for bar in frame.bars] for frame in frames] == [
            [1],
            [1],
            [2],
        ]
        assert frames[-1].bars[0].close == 103
    finally:
        catalog.close()


def test_replay_fills_on_next_available_bar_and_is_deterministic(simulation_time) -> None:
    bars = [
        SimulationBar(
            snapshot_id="1" * 64,
            instrument_id="inst-alpha",
            source_record_id=f"bar-{index}",
            source_revision=1,
            event_time=simulation_time + timedelta(minutes=index),
            available_at=simulation_time + timedelta(minutes=index + 1),
            open=100 + index,
            high=102 + index,
            low=99 + index,
            close=101 + index,
            volume=1000,
        )
        for index in range(3)
    ]
    frames = [ReplayFrame(snapshot_id="1" * 64, as_of=bar.available_at, bars=[bar]) for bar in bars]

    def run_once():
        engine = PortfolioReplayEngine(
            starting_cash=Decimal("10000"),
            portfolio_policy=PortfolioPolicy(),
            exchange=HistoricalExchange(FillPolicy()),
            config_hash="4" * 64,
        )
        return engine.run(frames, BuyOncePolicy())

    first = run_once()
    second = run_once()
    assert len(first.fills) == 1
    assert first.fills[0].occurred_at == bars[1].available_at
    assert first.event_hash == second.event_hash
    assert first.equity_hash == second.equity_hash
    ParityHarness().assert_decision_parity(first.decisions, second.decisions)


def test_replay_rejects_non_monotonic_frames(simulation_time, simulation_bar) -> None:
    engine = PortfolioReplayEngine(
        starting_cash=Decimal("10000"),
        portfolio_policy=PortfolioPolicy(),
        exchange=HistoricalExchange(FillPolicy()),
        config_hash="4" * 64,
    )
    frames = [
        ReplayFrame(snapshot_id="1" * 64, as_of=simulation_time + timedelta(minutes=2), bars=[]),
        ReplayFrame(snapshot_id="1" * 64, as_of=simulation_time + timedelta(minutes=1), bars=[]),
    ]
    try:
        engine.run(frames, BuyOncePolicy())
    except ValueError as exc:
        assert "monotonic" in str(exc)
    else:
        raise AssertionError("non-monotonic replay must fail")


def test_replay_atomic_reservation_rejects_second_shared_cash_candidate(
    simulation_time,
) -> None:
    frame = ReplayFrame(
        snapshot_id="1" * 64,
        as_of=simulation_time,
        bars=[
            SimulationBar(
                snapshot_id="1" * 64,
                instrument_id="inst-alpha",
                source_record_id="alpha",
                source_revision=1,
                event_time=simulation_time - timedelta(minutes=1),
                available_at=simulation_time,
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1000,
            )
        ],
    )
    result = PortfolioReplayEngine(
        starting_cash=Decimal("1000"),
        portfolio_policy=PortfolioPolicy(
            max_gross_exposure=Decimal("2"),
            max_symbol_exposure=Decimal("1"),
            max_risk_per_trade=Decimal("1"),
            max_total_risk=Decimal("2"),
        ),
        exchange=HistoricalExchange(FillPolicy()),
        config_hash="4" * 64,
    ).run([frame], TwoCandidatePolicy())
    assert [decision.approved for decision in result.decisions] == [True, False]
    assert "insufficient cash" in result.decisions[1].reason


def test_replay_expires_order_and_releases_reservation(simulation_time) -> None:
    frames = [
        ReplayFrame(
            snapshot_id="1" * 64,
            as_of=simulation_time + timedelta(minutes=index),
            bars=[],
        )
        for index in range(2)
    ]
    result = PortfolioReplayEngine(
        starting_cash=Decimal("1000"),
        portfolio_policy=PortfolioPolicy(
            max_symbol_exposure=Decimal("1"),
            max_risk_per_trade=Decimal("1"),
        ),
        exchange=HistoricalExchange(FillPolicy()),
        config_hash="4" * 64,
    ).run(frames, ExpiringLimitPolicy())
    assert result.final_orders[0].state == SimulationOrderState.EXPIRED
    assert result.equity_points[-1].cash == Decimal("1000")
    assert result.equity_points[-1].gross_exposure == 0
