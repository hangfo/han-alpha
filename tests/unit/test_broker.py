import pytest

from hanalpha.domain.enums import OrderStatus, Side
from hanalpha.domain.models import OrderRequest
from hanalpha.execution import SimulatedBroker


@pytest.mark.asyncio
async def test_simulated_broker_fills_and_rejects_duplicate(
    quote, risk_config, broker_write_capability
) -> None:
    broker = SimulatedBroker(100_000, risk_config.execution)
    order = OrderRequest(
        order_id="order-1",
        plan_id="plan-1",
        symbol="NVDA",
        side=Side.BUY,
        quantity=10,
        limit_price=quote.ask,
        stop_price=95,
        target_price=110,
        idempotency_key="idem-1",
    )
    events = await broker.submit(order, quote, broker_write_capability)
    assert events[-1].status == OrderStatus.FILLED
    assert events[-1].average_fill_price <= order.limit_price
    duplicate = await broker.submit(
        order.model_copy(update={"order_id": "order-2"}), quote, broker_write_capability
    )
    assert duplicate[-1].status == OrderStatus.REJECTED
    snapshot = await broker.get_account_snapshot()
    assert snapshot.positions[0].quantity == 10


@pytest.mark.asyncio
async def test_broker_disconnect_fails_closed(quote, risk_config, broker_write_capability) -> None:
    broker = SimulatedBroker(100_000, risk_config.execution)
    broker.set_connected(False)
    order = OrderRequest(
        order_id="order-1",
        plan_id="plan-1",
        symbol="NVDA",
        side=Side.BUY,
        quantity=10,
        limit_price=quote.ask,
        stop_price=95,
        target_price=110,
        idempotency_key="idem-1",
    )
    events = await broker.submit(order, quote, broker_write_capability)
    assert events[-1].status == OrderStatus.ERROR


@pytest.mark.asyncio
async def test_simulated_sell_fill_never_crosses_limit(
    quote, risk_config, broker_write_capability
) -> None:
    broker = SimulatedBroker(100_000, risk_config.execution)
    buy = OrderRequest(
        order_id="buy-1",
        plan_id="plan-1",
        symbol="NVDA",
        side=Side.BUY,
        quantity=10,
        limit_price=quote.ask,
        stop_price=95,
        target_price=110,
        idempotency_key="buy-idem",
    )
    await broker.submit(buy, quote, broker_write_capability)
    sell = OrderRequest(
        order_id="sell-1",
        plan_id="plan-2",
        symbol="NVDA",
        side=Side.SELL,
        quantity=10,
        limit_price=quote.bid,
        stop_price=110,
        target_price=95,
        idempotency_key="sell-idem",
    )
    events = await broker.submit(sell, quote, broker_write_capability)
    assert events[-1].status == OrderStatus.FILLED
    assert events[-1].average_fill_price >= sell.limit_price
