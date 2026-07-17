from __future__ import annotations

from datetime import timedelta

import pytest

from hanalpha.domain.enums import OrderStatus, Side
from hanalpha.domain.models import OrderRequest
from hanalpha.execution import SimulatedBroker


@pytest.mark.asyncio
async def test_protective_stop_closes_position(quote, risk_config) -> None:
    broker = SimulatedBroker(100_000, risk_config.execution)
    order = OrderRequest(
        order_id="entry-1",
        plan_id="plan-1",
        symbol="NVDA",
        side=Side.BUY,
        quantity=10,
        limit_price=quote.ask,
        stop_price=98,
        target_price=110,
        idempotency_key="entry-idem",
    )
    await broker.submit(order, quote)
    stop_quote = quote.model_copy(
        update={
            "timestamp": quote.timestamp + timedelta(seconds=1),
            "bid": 97.8,
            "ask": 98.0,
            "last": 97.9,
        }
    )
    events = await broker.process_quote(stop_quote)
    assert any(event.status == OrderStatus.FILLED for event in events)
    assert not (await broker.get_account_snapshot()).positions


@pytest.mark.asyncio
async def test_flatten_without_quote_refuses_to_guess(quote, risk_config) -> None:
    broker = SimulatedBroker(100_000, risk_config.execution)
    order = OrderRequest(
        order_id="entry-1",
        plan_id="plan-1",
        symbol="NVDA",
        side=Side.BUY,
        quantity=10,
        limit_price=quote.ask,
        stop_price=98,
        target_price=110,
        idempotency_key="entry-idem",
    )
    await broker.submit(order, quote)
    events = await broker.flatten_all({})
    assert events[0].status == OrderStatus.ERROR
    assert events[0].message == "missing_fresh_quote"
