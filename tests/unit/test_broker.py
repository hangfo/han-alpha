import pytest

from hanalpha.domain.enums import OrderStatus, Side
from hanalpha.domain.models import OrderRequest
from hanalpha.execution import SimulatedBroker


@pytest.mark.asyncio
async def test_simulated_broker_fills_and_rejects_duplicate(quote, risk_config) -> None:
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
    events = await broker.submit(order, quote)
    assert events[-1].status == OrderStatus.FILLED
    duplicate = await broker.submit(order.model_copy(update={"order_id": "order-2"}), quote)
    assert duplicate[-1].status == OrderStatus.REJECTED
    snapshot = await broker.get_account_snapshot()
    assert snapshot.positions[0].quantity == 10


@pytest.mark.asyncio
async def test_broker_disconnect_fails_closed(quote, risk_config) -> None:
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
    events = await broker.submit(order, quote)
    assert events[-1].status == OrderStatus.ERROR
