from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from hanalpha.domain.enums import Side
from hanalpha.simulation.events import FillEvent
from hanalpha.simulation.orders import OrderIntent, OrderKind
from hanalpha.simulation.portfolio import (
    DuplicateLedgerEvent,
    JournalAccount,
    PortfolioLedger,
    PortfolioPolicy,
    ReservationRejected,
)


def _fill(order_id: str, fill_id: str, side: Side, quantity: int, at, price=100) -> FillEvent:
    return FillEvent(
        fill_id=fill_id,
        order_id=order_id,
        instrument_id="inst-alpha",
        side=side,
        quantity=quantity,
        price=price,
        commission=1,
        occurred_at=at,
        reason="test",
    )


def test_cash_lots_fifo_and_commissions_reconcile(buy_order, simulation_time) -> None:
    ledger = PortfolioLedger(
        Decimal("10002"),
        PortfolioPolicy(
            max_risk_per_trade=Decimal("0.1"),
            max_symbol_exposure=Decimal("1"),
        ),
    )
    ledger.reserve(buy_order.intent)
    first = _fill("order-buy-1", "fill-1", Side.BUY, 50, simulation_time, 100)
    second = _fill(
        "order-buy-1", "fill-2", Side.BUY, 50, simulation_time + timedelta(minutes=1), 100
    )
    ledger.apply_fill(first)
    ledger.apply_fill(second)
    ledger.release("order-buy-1")
    assert ledger.cash == Decimal("0")
    assert ledger.position_quantity("inst-alpha") == 100
    ledger.mark("inst-alpha", Decimal("110"))
    snapshot = ledger.snapshot(simulation_time + timedelta(minutes=1))
    assert snapshot.net_liquidation == Decimal("11000")
    ledger.assert_conservation()

    sell_intent = OrderIntent(
        order_id="order-sell-1",
        decision_id="decision-sell",
        instrument_id="inst-alpha",
        strategy_id="test",
        side=Side.SELL,
        kind=OrderKind.MARKET,
        quantity=50,
        submitted_at=simulation_time + timedelta(minutes=2),
        earliest_fill_at=simulation_time + timedelta(minutes=2, seconds=1),
        planned_price=110,
        protective_stop=None,
    )
    ledger.reserve(sell_intent)
    ledger.apply_fill(
        _fill("order-sell-1", "fill-3", Side.SELL, 50, simulation_time + timedelta(minutes=3), 110)
    )
    ledger.release("order-sell-1")
    assert ledger.realized_pnl == Decimal("498")
    assert ledger.position_quantity("inst-alpha") == 50
    assert all(entry.is_balanced for entry in ledger.journal_entries)
    assert ledger.account_balance(JournalAccount.CASH) == ledger.cash
    ledger.assert_conservation()


def test_atomic_reservations_prevent_shared_cash_oversubscription(
    buy_order, simulation_time
) -> None:
    ledger = PortfolioLedger(
        Decimal("10000"),
        PortfolioPolicy(
            max_gross_exposure=Decimal("1"),
            max_symbol_exposure=Decimal("1"),
            max_risk_per_trade=Decimal("0.1"),
        ),
    )
    first = buy_order.intent.model_copy(update={"quantity": 60, "planned_price": 100})
    second = first.model_copy(update={"order_id": "order-buy-2", "decision_id": "decision-2"})
    ledger.reserve(OrderIntent.model_validate(first.model_dump()))
    with pytest.raises(ReservationRejected, match=r"cash|gross"):
        ledger.reserve(OrderIntent.model_validate(second.model_dump()))
    assert ledger.available_cash == Decimal("3999")


def test_held_and_reserved_trade_risk_share_one_portfolio_budget(
    buy_order, simulation_time
) -> None:
    ledger = PortfolioLedger(
        Decimal("10000"),
        PortfolioPolicy(
            max_gross_exposure=Decimal("2"),
            max_symbol_exposure=Decimal("1"),
            max_risk_per_trade=Decimal("0.1"),
            max_total_risk=Decimal("0.1"),
        ),
    )
    first = buy_order.intent.model_copy(update={"quantity": 50})
    ledger.reserve(OrderIntent.model_validate(first.model_dump()))
    ledger.apply_fill(_fill("order-buy-1", "fill-1", Side.BUY, 50, simulation_time))
    ledger.release("order-buy-1")
    assert ledger.snapshot(simulation_time).open_risk == Decimal("250")
    second = first.model_copy(
        update={
            "order_id": "order-buy-2",
            "decision_id": "decision-2",
            "instrument_id": "inst-beta",
            "quantity": 10,
            "protective_stop": 20,
        }
    )
    with pytest.raises(ReservationRejected, match="total risk"):
        ledger.reserve(OrderIntent.model_validate(second.model_dump()))


def test_duplicate_fill_fails_closed(buy_order, simulation_time) -> None:
    ledger = PortfolioLedger(
        Decimal("20000"),
        PortfolioPolicy(
            max_symbol_exposure=Decimal("1"),
            max_risk_per_trade=Decimal("0.1"),
        ),
    )
    ledger.reserve(buy_order.intent)
    fill = _fill("order-buy-1", "fill-1", Side.BUY, 10, simulation_time)
    ledger.apply_fill(fill)
    with pytest.raises(DuplicateLedgerEvent):
        ledger.apply_fill(fill)


def test_split_and_dividend_are_explicit_conserving_events(buy_order, simulation_time) -> None:
    ledger = PortfolioLedger(
        Decimal("20000"),
        PortfolioPolicy(
            max_symbol_exposure=Decimal("1"),
            max_risk_per_trade=Decimal("0.1"),
        ),
    )
    ledger.reserve(buy_order.intent)
    ledger.apply_fill(_fill("order-buy-1", "fill-1", Side.BUY, 100, simulation_time))
    ledger.release("order-buy-1")
    raw_cash = ledger.cash
    ledger.apply_split(
        action_id="split-1", instrument_id="inst-alpha", ratio=Decimal("2"), at=simulation_time
    )
    assert ledger.position_quantity("inst-alpha") == 200
    ledger.apply_dividend(
        action_id="dividend-1",
        instrument_id="inst-alpha",
        cash_per_share=Decimal("1"),
        at=simulation_time,
    )
    assert ledger.cash == raw_cash + Decimal("200")
    assert ledger.journal_entries[-1].reason == "cash_dividend"
    assert ledger.journal_entries[-1].is_balanced
    ledger.assert_conservation()


def test_delisting_explicitly_closes_lots_at_declared_recovery(buy_order, simulation_time) -> None:
    ledger = PortfolioLedger(
        Decimal("20000"),
        PortfolioPolicy(
            max_symbol_exposure=Decimal("1"),
            max_risk_per_trade=Decimal("0.1"),
        ),
    )
    ledger.reserve(buy_order.intent)
    ledger.apply_fill(_fill("order-buy-1", "fill-1", Side.BUY, 100, simulation_time))
    ledger.release("order-buy-1")
    ledger.apply_delisting(
        action_id="delist-1",
        instrument_id="inst-alpha",
        cash_per_share=Decimal("10"),
        at=simulation_time + timedelta(days=1),
    )
    assert ledger.position_quantity("inst-alpha") == 0
    assert ledger.realized_pnl == Decimal("-9001")
    assert ledger.cash == Decimal("10999")
    assert ledger.cash_entries[-1].reason == "delisting_recovery"
    assert ledger.journal_entries[-1].is_balanced
    ledger.assert_conservation()
