from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import hanalpha.execution.ibkr as ibkr_module
from hanalpha.domain.enums import OrderStatus, Side
from hanalpha.domain.models import OrderEvent, OrderRequest, Position, Quote
from hanalpha.execution.ibkr import (
    IBAPI_AVAILABLE,
    IBKRBroker,
    _IBApp,
    _ObserverOnlyIBApp,
    canonical_account_count,
)
from hanalpha.execution.ibkr_observer import (
    IBKRCallbackCollector,
    IBKRFactStore,
    IBKRFactType,
    ObserverRequestBarrier,
)

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def test_observer_only_app_structurally_rejects_broker_writes() -> None:
    app = _ObserverOnlyIBApp()
    for call in (
        lambda: app.placeOrder(1, object(), object()),
        lambda: app.cancelOrder(1),
        app.reqGlobalCancel,
        lambda: app.exerciseOptions(1, object(), 1, 1, "DU", 0),
    ):
        with pytest.raises(PermissionError, match="observer-only"):
            call()


def test_ibapp_callbacks_normalize_redact_and_preserve_order_state(tmp_path) -> None:
    store = IBKRFactStore(tmp_path / "facts.sqlite3")
    session = store.start_session(host="127.0.0.1", port=7497, client_id=7, at=NOW)
    barrier = ObserverRequestBarrier(
        account_request_id=11,
        execution_request_id=12,
        position_epoch="positions-epoch",
        open_orders_epoch="orders-epoch",
        execution_history_start=NOW,
        execution_history_end=NOW,
    )
    app = _IBApp()
    app.observer = IBKRCallbackCollector(
        store,
        session,
        barrier=barrier,
        configured_account="DU123",
        client_id=7,
    )
    contract = SimpleNamespace(symbol="NVDA", conId=42, currency="USD", secType="STK")
    order = SimpleNamespace(
        orderId=5,
        permId=1001,
        parentId=0,
        clientId=7,
        orderRef="HA:" + "a" * 64,
        account="DU123",
        action="BUY",
        totalQuantity=10,
        orderType="LMT",
        lmtPrice=100,
        auxPrice=0,
        tif="DAY",
        transmit=False,
        ocaGroup="",
        outsideRth=False,
        goodTillDate="",
    )
    execution = SimpleNamespace(
        execId="exec.1",
        orderId=5,
        permId=1001,
        clientId=7,
        acctNumber="DU123",
        orderRef=order.orderRef,
        exchange="NASDAQ",
        shares=3,
        price=100.25,
        cumQty=3,
        avgPrice=100.25,
        liquidation=0,
        pendingPriceRevision=False,
        side="BOT",
        time="20240101 10:00:00",
    )
    app.nextValidId(5)
    app.connectAck()
    app.currentTime(1_704_067_200)
    app.managedAccounts("DU123,")
    app.accountSummary(11, "DU123", "TotalCashValue", "100000", "USD")
    app.accountSummary(11, "DU123", "bad", "not-numeric", "USD")
    app.openOrder(5, contract, order, SimpleNamespace(status="Submitted"))
    app.completedOrder(contract, order, SimpleNamespace(status="Filled"))
    app.completedOrdersEnd()
    app.orderStatus(5, "Submitted", 3, 7, 100.25, 1001, 0, 100.25, 7, "", 0)
    app.execDetails(12, contract, execution)
    app.commissionReport(
        SimpleNamespace(execId="exec.1", commission=1.0, currency="USD", realizedPNL=0)
    )
    app.position("DU123", contract, 10, 99.0)
    app.position("DU123", contract, 0, 99.0)
    app.accountSummaryEnd(11)
    app.openOrderEnd()
    app.positionEnd()
    app.execDetailsEnd(12)
    app.error(5, 201, "rejected")
    app.error(-1, 2104, "farm ok")
    app.connectionClosed()

    facts = store.facts(session)
    assert {fact.fact_type for fact in facts} >= {
        IBKRFactType.OPEN_ORDER,
        IBKRFactType.COMPLETED_ORDER,
        IBKRFactType.COMPLETED_ORDER_END,
        IBKRFactType.EXECUTION,
        IBKRFactType.COMMISSION,
        IBKRFactType.DISCONNECT,
    }
    assert "DU123" not in "".join(fact.model_dump_json() for fact in facts)
    assert app.order_events[-1].status == OrderStatus.ERROR
    assert app.order_events[0].status == OrderStatus.PARTIALLY_FILLED
    assert app.positions_cache == {}
    assert canonical_account_count(["a", "b"]) == "accounts:2"
    store.close()


class _FakeIBApp:
    def __init__(self) -> None:
        self.connected = True
        self.next_order_id = 20
        self.lock = threading.RLock()
        self.broker_to_internal: dict[int, str] = {}
        self.order_events: list[OrderEvent] = []
        self.positions_cache: dict[str, Position] = {}
        self.account_values = {
            "NetLiquidation": 100_000.0,
            "TotalCashValue": 80_000.0,
            "BuyingPower": 160_000.0,
        }
        self.placed: list[tuple[int, object, object]] = []
        self.global_cancels = 0

    def isConnected(self) -> bool:
        return self.connected

    def placeOrder(self, order_id: int, contract: object, order: object) -> None:
        self.placed.append((order_id, contract, order))

    def reqGlobalCancel(self) -> None:
        self.global_cancels += 1


def _broker(app: _FakeIBApp) -> IBKRBroker:
    broker = object.__new__(IBKRBroker)
    broker.host = "127.0.0.1"
    broker.port = 7497
    broker.client_id = 7
    broker.account = "DU123"
    broker.app = app
    broker.thread = None
    broker._idempotency = {}
    return broker


@pytest.mark.asyncio
async def test_ibkr_write_adapter_bracket_idempotency_and_risk_reduction(
    broker_write_capability,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ibkr_module, "Contract", SimpleNamespace)
    monkeypatch.setattr(ibkr_module, "Order", SimpleNamespace)
    app = _FakeIBApp()
    broker = _broker(app)
    request = OrderRequest(
        order_id="order-1",
        plan_id="plan-1",
        symbol="NVDA",
        side=Side.BUY,
        quantity=10,
        limit_price=100,
        stop_price=95,
        target_price=110,
        idempotency_key="economic-key-12345678",
        created_at=NOW,
    )
    quote = Quote(symbol="NVDA", timestamp=NOW, bid=99.9, ask=100.1, last=100)
    submitted = await broker.submit(request, quote, broker_write_capability)
    assert submitted[0].status == OrderStatus.SUBMITTED
    assert [item[0] for item in app.placed] == [20, 21, 22]
    assert [item[2].transmit for item in app.placed] == [False, False, True]
    refs = [item[2].orderRef for item in app.placed]
    assert len(set(refs)) == 3
    assert [reference.rsplit(":", 1)[-1] for reference in refs] == ["P", "T", "S"]
    duplicate = await broker.submit(request, quote, broker_write_capability)
    assert duplicate[0].message == "duplicate_idempotency_key"

    app.order_events.append(submitted[0])
    assert await broker.process_quote(quote) == submitted
    assert await broker.process_quote(quote) == []
    cancelled = await broker.cancel_all(broker_write_capability)
    assert cancelled[0].status == OrderStatus.CANCEL_PENDING
    assert app.global_cancels == 1

    app.positions_cache = {
        "NVDA": Position(symbol="NVDA", quantity=5, average_cost=99, mark_price=100),
        "TSLA": Position(symbol="TSLA", quantity=-2, average_cost=200, mark_price=195),
        "MISSING": Position(symbol="MISSING", quantity=1, average_cost=10, mark_price=10),
    }
    tsla_quote = Quote(symbol="TSLA", timestamp=NOW, bid=194, ask=196, last=195)
    flattened = await broker.flatten_all(
        {"NVDA": quote, "TSLA": tsla_quote}, broker_write_capability
    )
    assert [event.status for event in flattened] == [
        OrderStatus.SUBMITTED,
        OrderStatus.SUBMITTED,
        OrderStatus.ERROR,
    ]
    assert app.placed[-2][2].action == "SELL"
    assert app.placed[-1][2].action == "BUY"

    snapshot = await broker.get_account_snapshot()
    assert snapshot.cash == 80_000
    assert snapshot.connected
    app.account_values = {}
    app.positions_cache = {}
    assert (await broker.get_account_snapshot()).net_liquidation == 0.01
    app.next_order_id = None
    with pytest.raises(RuntimeError, match="order ID"):
        broker._next_ids(1)

    app.connected = False
    disconnected_request = request.model_copy(
        update={"order_id": "order-2", "idempotency_key": "economic-key-87654321"}
    )
    assert (await broker.submit(disconnected_request, quote, broker_write_capability))[
        0
    ].status == OrderStatus.ERROR
    simple = await broker._submit_simple_limit(
        symbol="NVDA",
        side=Side.SELL,
        quantity=1,
        limit_price=99,
        internal_id="flat-disconnected",
        capability=broker_write_capability,
    )
    assert simple.status == OrderStatus.ERROR


@pytest.mark.asyncio
async def test_connect_transport_timeout_disconnects() -> None:
    class App(_FakeIBApp):
        def __init__(self) -> None:
            super().__init__()
            self.connected_event = threading.Event()
            self.disconnected = False

        def connect(self, host: str, port: int, client_id: int) -> None:
            return None

        def run(self) -> None:
            return None

        def disconnect(self) -> None:
            self.disconnected = True

    app = App()
    broker = _broker(app)
    with pytest.raises(TimeoutError, match="nextValidId"):
        await broker.connect_transport_only(timeout=0.01)
    assert app.disconnected
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_connect_alias_reaches_transport_readiness() -> None:
    class App(_FakeIBApp):
        def __init__(self) -> None:
            super().__init__()
            self.connected_event = threading.Event()

        def connect(self, host: str, port: int, client_id: int) -> None:
            self.connected_event.set()

        def run(self) -> None:
            return None

    broker = _broker(App())
    await broker.connect(timeout=0.1)
    assert broker.thread is not None


def test_constructor_fails_closed_without_official_ibapi() -> None:
    if IBAPI_AVAILABLE:
        pytest.skip("official ibapi is installed")
    with pytest.raises(RuntimeError, match="Official IBKR TWS API"):
        IBKRBroker(host="127.0.0.1", port=7497, client_id=7)
