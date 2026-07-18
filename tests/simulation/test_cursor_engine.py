from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from hanalpha.data.fixtures import run_fixture_pipeline
from hanalpha.domain.enums import Side
from hanalpha.pit.canonical_store import CanonicalStore
from hanalpha.pit.catalog import PITCatalog
from hanalpha.pit.models import CorporateActionType
from hanalpha.pit.repository import AsOfRepository
from hanalpha.simulation.engine import (
    OrderProposal,
    PITEventCursor,
    PortfolioReplayEngine,
)
from hanalpha.simulation.events import (
    CorporateActionPhase,
    ReplayFrame,
    SimulationBar,
    SimulationCorporateAction,
)
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
            [],
        ]
        assert [bar.source_revision for bar in frames[-1].bar_revisions] == [2]
        assert frames[-1].bar_revisions[0].close == 103
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


def test_action_revision_is_knowledge_only_and_cannot_duplicate_cash(simulation_time) -> None:
    action = SimulationCorporateAction(
        snapshot_id="1" * 64,
        action_id="dividend-1-revision",
        instrument_id="inst-alpha",
        source_record_id="dividend-1",
        source_revision=2,
        action_type=CorporateActionType.DIVIDEND,
        event_time=simulation_time,
        available_at=simulation_time,
        cash_amount=Decimal("999"),
    )
    result = PortfolioReplayEngine(
        starting_cash=Decimal("10000"),
        portfolio_policy=PortfolioPolicy(),
        exchange=HistoricalExchange(FillPolicy()),
        config_hash="4" * 64,
    ).run(
        [
            ReplayFrame(
                snapshot_id="1" * 64,
                as_of=simulation_time,
                bars=[],
                action_revisions=[action],
            )
        ],
        TwoCandidatePolicy(),
    )
    assert result.equity_points[-1].cash == Decimal("10000")
    assert result.fills == []


def test_announced_action_phase_does_not_cancel_or_apply_before_effective_time(
    simulation_time,
) -> None:
    bars = [
        SimulationBar(
            snapshot_id="1" * 64,
            instrument_id="inst-alpha",
            source_record_id=f"phase-bar-{index}",
            source_revision=1,
            event_time=simulation_time + timedelta(minutes=index),
            available_at=simulation_time + timedelta(minutes=index),
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1000,
        )
        for index in range(2)
    ]
    announcement = SimulationCorporateAction(
        snapshot_id="1" * 64,
        action_id="future-split-announcement",
        instrument_id="inst-alpha",
        source_record_id="future-split",
        source_revision=1,
        action_type=CorporateActionType.SPLIT,
        phase=CorporateActionPhase.ANNOUNCED,
        event_time=bars[1].event_time,
        available_at=bars[1].available_at,
        ratio=Decimal("2"),
    )
    frames = [
        ReplayFrame(snapshot_id="1" * 64, as_of=bars[0].available_at, bars=[bars[0]]),
        ReplayFrame(
            snapshot_id="1" * 64,
            as_of=bars[1].available_at,
            bars=[bars[1]],
            actions=[announcement],
        ),
    ]
    result = PortfolioReplayEngine(
        starting_cash=Decimal("10000"),
        portfolio_policy=PortfolioPolicy(),
        exchange=HistoricalExchange(FillPolicy()),
        config_hash="4" * 64,
    ).run(frames, BuyOncePolicy())
    assert len(result.fills) == 1
    assert result.fills[0].quantity == 10


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


class PermutedCandidates:
    name = "permuted"
    version = "1"

    def __init__(self, reverse: bool) -> None:
        self.reverse = reverse

    def propose(self, frame, portfolio):
        proposals = [
            OrderProposal(
                instrument_id=instrument_id,
                strategy_id=self.name,
                strategy_version=self.version,
                side=Side.BUY,
                kind=OrderKind.MARKET,
                quantity=1,
                planned_price=100,
                protective_stop=90,
                input_hash=hash_digit * 64,
                signal_hash=hash_digit * 64,
            )
            for instrument_id, hash_digit in (("inst-alpha", "a"), ("inst-beta", "b"))
        ]
        return list(reversed(proposals)) if self.reverse else proposals


def test_candidate_permutation_does_not_change_orders_or_event_hash(simulation_time) -> None:
    frame = ReplayFrame(snapshot_id="1" * 64, as_of=simulation_time, bars=[])

    def run(reverse: bool):
        return PortfolioReplayEngine(
            starting_cash=Decimal("10000"),
            portfolio_policy=PortfolioPolicy(
                max_symbol_exposure=Decimal("1"),
                max_risk_per_trade=Decimal("1"),
                max_total_risk=Decimal("1"),
            ),
            exchange=HistoricalExchange(FillPolicy()),
            config_hash="4" * 64,
        ).run([frame], PermutedCandidates(reverse))

    first = run(False)
    second = run(True)
    assert first.event_hash == second.event_hash
    assert [order.intent.order_id for order in first.final_orders] == [
        order.intent.order_id for order in second.final_orders
    ]


class BracketPolicy:
    name = "bracket"
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
                kind=OrderKind.MARKET,
                quantity=100,
                planned_price=100,
                protective_stop=95,
                protective_target=105,
                input_hash="c" * 64,
                signal_hash="d" * 64,
            )
        ]


def test_partial_entry_fills_create_matching_reduce_only_protection(simulation_time) -> None:
    bars = [
        SimulationBar(
            snapshot_id="1" * 64,
            instrument_id="inst-alpha",
            source_record_id=f"bar-{index}",
            source_revision=1,
            event_time=simulation_time + timedelta(minutes=index),
            available_at=simulation_time + timedelta(minutes=index),
            open=100,
            high=101,
            low=99,
            close=100,
            volume=volume,
        )
        for index, volume in enumerate((1000, 40, 60))
    ]
    frames = [ReplayFrame(snapshot_id="1" * 64, as_of=bar.available_at, bars=[bar]) for bar in bars]
    result = PortfolioReplayEngine(
        starting_cash=Decimal("20000"),
        portfolio_policy=PortfolioPolicy(
            max_symbol_exposure=Decimal("1"),
            max_risk_per_trade=Decimal("1"),
            max_total_risk=Decimal("1"),
        ),
        exchange=HistoricalExchange(FillPolicy(participation_rate=1)),
        config_hash="4" * 64,
    ).run(frames, BracketPolicy())
    stops = [
        order
        for order in result.final_orders
        if order.intent.reduce_only and order.intent.kind == OrderKind.STOP_MARKET
    ]
    assert sum(order.intent.quantity for order in stops) == 100
    assert all(order.intent.parent_order_id for order in stops)


def test_entry_bar_protection_uses_adverse_stop_first_policy(simulation_time) -> None:
    proposal_bar = SimulationBar(
        snapshot_id="1" * 64,
        instrument_id="inst-alpha",
        source_record_id="proposal",
        source_revision=1,
        event_time=simulation_time,
        available_at=simulation_time,
        open=100,
        high=101,
        low=99,
        close=100,
        volume=1000,
    )
    entry_bar = proposal_bar.model_copy(
        update={
            "source_record_id": "entry",
            "event_time": simulation_time + timedelta(minutes=1),
            "available_at": simulation_time + timedelta(minutes=1),
            "high": 110,
            "low": 90,
        }
    )
    frames = [
        ReplayFrame(snapshot_id="1" * 64, as_of=bar.available_at, bars=[bar])
        for bar in (proposal_bar, entry_bar)
    ]
    result = PortfolioReplayEngine(
        starting_cash=Decimal("20000"),
        portfolio_policy=PortfolioPolicy(
            max_symbol_exposure=Decimal("1"),
            max_risk_per_trade=Decimal("1"),
            max_total_risk=Decimal("1"),
        ),
        exchange=HistoricalExchange(FillPolicy(participation_rate=1)),
        config_hash="4" * 64,
    ).run(frames, BracketPolicy())
    assert len(result.fills) == 2
    assert result.fills[0].side == Side.BUY
    assert result.fills[1].reason == "stop_intrabar"
    assert result.fills[1].occurred_at == result.fills[0].occurred_at
    assert any(
        order.intent.kind == OrderKind.LIMIT and order.state == SimulationOrderState.CANCELLED
        for order in result.final_orders
    )


def test_oco_stop_first_prevents_double_exit_when_bar_touches_both(simulation_time) -> None:
    bars = [
        SimulationBar(
            snapshot_id="1" * 64,
            instrument_id="inst-alpha",
            source_record_id=f"bar-{index}",
            source_revision=1,
            event_time=simulation_time + timedelta(minutes=index),
            available_at=simulation_time + timedelta(minutes=index),
            open=100,
            high=110 if index == 2 else 101,
            low=90 if index == 2 else 99,
            close=100,
            volume=1000,
        )
        for index in range(3)
    ]
    frames = [ReplayFrame(snapshot_id="1" * 64, as_of=bar.available_at, bars=[bar]) for bar in bars]
    result = PortfolioReplayEngine(
        starting_cash=Decimal("20000"),
        portfolio_policy=PortfolioPolicy(
            max_symbol_exposure=Decimal("1"),
            max_risk_per_trade=Decimal("1"),
            max_total_risk=Decimal("1"),
        ),
        exchange=HistoricalExchange(FillPolicy(participation_rate=1)),
        config_hash="4" * 64,
    ).run(frames, BracketPolicy())
    exits = [fill for fill in result.fills if fill.side == Side.SELL]
    assert len(exits) == 1
    assert exits[0].reason.startswith("stop")
    children = [order for order in result.final_orders if order.intent.reduce_only]
    assert {order.state for order in children} == {
        SimulationOrderState.FILLED,
        SimulationOrderState.CANCELLED,
    }
