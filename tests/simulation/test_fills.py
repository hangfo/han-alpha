from __future__ import annotations

from datetime import timedelta

from hanalpha.domain.enums import Side
from hanalpha.simulation.events import SimulationBar
from hanalpha.simulation.fills import CostScenario, FillPolicy, HistoricalExchange
from hanalpha.simulation.orders import OrderIntent, OrderKind, TrackedOrder


def _order(buy_order, **updates) -> TrackedOrder:
    intent = buy_order.intent.model_copy(update=updates)
    return TrackedOrder.proposed(OrderIntent.model_validate(intent.model_dump())).accept(
        intent.submitted_at
    )


def test_limit_fill_respects_price_and_volume_participation(buy_order, simulation_bar) -> None:
    exchange = HistoricalExchange(
        FillPolicy(
            scenario=CostScenario.BASE,
            spread_bps=10,
            slippage_bps=5,
            impact_bps=0,
            participation_rate=0.05,
            minimum_commission=1,
            commission_per_share=0.01,
        )
    )
    fill = exchange.match(buy_order, simulation_bar, as_of=simulation_bar.available_at)
    assert fill is not None
    assert fill.quantity == 50
    assert fill.price <= buy_order.intent.limit_price
    assert fill.commission == 1


def test_sell_limit_never_fills_below_limit(buy_order, simulation_bar) -> None:
    order = _order(
        buy_order,
        side=Side.SELL,
        kind=OrderKind.LIMIT,
        limit_price=103,
        protective_stop=None,
    )
    fill = HistoricalExchange(FillPolicy()).match(
        order, simulation_bar, as_of=simulation_bar.available_at
    )
    assert fill is not None
    assert fill.price >= 103


def test_stop_market_gap_uses_adverse_open_not_stale_stop(buy_order, simulation_bar) -> None:
    order = _order(
        buy_order,
        side=Side.SELL,
        kind=OrderKind.STOP_MARKET,
        limit_price=None,
        stop_price=95,
        protective_stop=None,
    )
    gap = simulation_bar.model_copy(update={"open": 80, "high": 85, "low": 75, "close": 82})
    fill = HistoricalExchange(FillPolicy(slippage_bps=5)).match(order, gap, as_of=gap.available_at)
    assert fill is not None
    assert fill.reason == "stop_gap"
    assert fill.price < 80


def test_stop_limit_can_remain_unfilled_after_gap(buy_order, simulation_bar) -> None:
    order = _order(
        buy_order,
        side=Side.SELL,
        kind=OrderKind.STOP_LIMIT,
        limit_price=94,
        stop_price=95,
        protective_stop=None,
    )
    gap = simulation_bar.model_copy(update={"open": 80, "high": 90, "low": 75, "close": 82})
    assert HistoricalExchange(FillPolicy()).match(order, gap, as_of=gap.available_at) is None


def test_same_decision_bar_halt_and_zero_volume_do_not_fill(buy_order, simulation_bar) -> None:
    exchange = HistoricalExchange(FillPolicy())
    same_bar = simulation_bar.model_copy(update={"available_at": buy_order.intent.submitted_at})
    assert exchange.match(buy_order, same_bar, as_of=same_bar.available_at) is None
    assert (
        exchange.match(
            buy_order,
            simulation_bar.model_copy(update={"halted": True}),
            as_of=simulation_bar.available_at,
        )
        is None
    )
    zero = SimulationBar.model_validate(
        simulation_bar.model_copy(update={"volume": 0}).model_dump()
    )
    assert exchange.match(buy_order, zero, as_of=zero.available_at) is None


def test_future_unavailable_bar_is_rejected(buy_order, simulation_bar) -> None:
    as_of = simulation_bar.available_at - timedelta(seconds=1)
    assert HistoricalExchange(FillPolicy()).match(buy_order, simulation_bar, as_of=as_of) is None
