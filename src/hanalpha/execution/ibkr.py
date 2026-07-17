from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime
from typing import Any

from hanalpha.domain.enums import OrderStatus, Side
from hanalpha.domain.models import AccountSnapshot, OrderEvent, OrderRequest, Position, Quote
from hanalpha.runtime.capabilities import BrokerWriteCapability, require_broker_write

try:
    from ibapi.client import EClient
    from ibapi.contract import Contract
    from ibapi.execution import Execution
    from ibapi.order import Order
    from ibapi.wrapper import EWrapper

    IBAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on local official TWS API install
    class EWrapper:  # type: ignore[no-redef]
        pass

    class EClient:  # type: ignore[no-redef]
        def __init__(self, wrapper: Any) -> None:
            self.wrapper = wrapper

    Contract = Any
    Order = Any
    Execution = Any
    IBAPI_AVAILABLE = False


class _IBApp(EWrapper, EClient):  # type: ignore[misc]
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.next_order_id: int | None = None
        self.order_events: list[OrderEvent] = []
        self.broker_to_internal: dict[int, str] = {}
        self.positions_cache: dict[str, Position] = {}
        self.account_values: dict[str, float] = {}
        self.connected_event = threading.Event()
        self.lock = threading.RLock()

    def nextValidId(self, orderId: int) -> None:
        with self.lock:
            self.next_order_id = orderId
        self.connected_event.set()

    def error(self, reqId: int, errorCode: int, errorString: str, advancedOrderRejectJson: str = "") -> None:
        if reqId >= 0:
            self.order_events.append(
                OrderEvent(
                    order_id=str(reqId),
                    status=OrderStatus.ERROR,
                    message=f"IBKR {errorCode}: {errorString}",
                    broker_order_id=str(reqId),
                )
            )

    def orderStatus(
        self,
        orderId: int,
        status: str,
        filled: float,
        remaining: float,
        avgFillPrice: float,
        permId: int,
        parentId: int,
        lastFillPrice: float,
        clientId: int,
        whyHeld: str,
        mktCapPrice: float,
    ) -> None:
        mapping = {
            "PendingSubmit": OrderStatus.SUBMITTING,
            "PreSubmitted": OrderStatus.SUBMITTED,
            "Submitted": OrderStatus.SUBMITTED,
            "PendingCancel": OrderStatus.CANCEL_PENDING,
            "Cancelled": OrderStatus.CANCELLED,
            "ApiCancelled": OrderStatus.CANCELLED,
            "Filled": OrderStatus.FILLED,
            "Inactive": OrderStatus.REJECTED,
        }
        internal = mapping.get(status, OrderStatus.ERROR)
        if filled > 0 and remaining > 0:
            internal = OrderStatus.PARTIALLY_FILLED
        internal_order_id = self.broker_to_internal.get(orderId, str(orderId))
        self.order_events.append(
            OrderEvent(
                order_id=internal_order_id,
                status=internal,
                filled_quantity=max(0, int(filled)),
                remaining_quantity=max(0, int(remaining)),
                average_fill_price=avgFillPrice if avgFillPrice > 0 else None,
                message=f"ib_status={status};whyHeld={whyHeld}",
                broker_order_id=str(orderId),
            )
        )

    def execDetails(self, reqId: int, contract: Contract, execution: Execution) -> None:
        internal_order_id = self.broker_to_internal.get(execution.orderId, str(execution.orderId))
        self.order_events.append(
            OrderEvent(
                order_id=internal_order_id,
                status=OrderStatus.FILLED,
                filled_quantity=max(0, int(float(execution.shares))),
                remaining_quantity=0,
                average_fill_price=float(execution.price),
                message=f"exec_id={execution.execId}",
                broker_order_id=str(execution.orderId),
            )
        )

    def position(self, account: str, contract: Contract, position: float, avgCost: float) -> None:
        quantity = int(position)
        if quantity == 0:
            self.positions_cache.pop(contract.symbol, None)
            return
        self.positions_cache[contract.symbol] = Position(
            symbol=contract.symbol,
            quantity=quantity,
            average_cost=max(0.01, float(avgCost)),
            mark_price=max(0.01, float(avgCost)),
        )

    def accountSummary(self, reqId: int, account: str, tag: str, value: str, currency: str) -> None:
        try:
            self.account_values[tag] = float(value)
        except ValueError:
            return


class IBKRBroker:
    """Official TWS API adapter for paper/live accounts with bracket orders.

    The official TWS API package must be installed from the TWS API distribution.
    Live use is intentionally gated by higher-level configuration and approval logic.
    """

    def __init__(self, *, host: str, port: int, client_id: int, account: str | None = None) -> None:
        if not IBAPI_AVAILABLE:
            raise RuntimeError(
                "Official IBKR TWS API Python package is unavailable. Install it from the "
                "TWS API distribution, then reinstall this project."
            )
        self.host = host
        self.port = port
        self.client_id = client_id
        self.account = account
        self.app = _IBApp()
        self.thread: threading.Thread | None = None
        self._idempotency: dict[str, int] = {}

    async def connect(self, timeout: float = 10) -> None:
        self.app.connect(self.host, self.port, self.client_id)
        self.thread = threading.Thread(target=self.app.run, daemon=True)
        self.thread.start()
        ok = await asyncio.to_thread(self.app.connected_event.wait, timeout)
        if not ok:
            self.app.disconnect()
            raise TimeoutError("IBKR nextValidId was not received")
        self.app.reqPositions()
        self.app.reqAccountSummary(9001, "All", "NetLiquidation,TotalCashValue,BuyingPower")

    async def is_connected(self) -> bool:
        return bool(self.app.isConnected())

    async def get_account_snapshot(self) -> AccountSnapshot:
        connected = await self.is_connected()
        net = self.app.account_values.get("NetLiquidation", 0.0)
        cash = self.app.account_values.get("TotalCashValue", 0.0)
        buying_power = self.app.account_values.get("BuyingPower", 0.0)
        if net <= 0:
            net = max(0.01, cash + sum(item.market_value for item in self.app.positions_cache.values()))
        return AccountSnapshot(
            timestamp=datetime.now(UTC),
            net_liquidation=net,
            cash=cash,
            buying_power=max(0.0, buying_power),
            daily_pnl=0.0,
            peak_net_liquidation=net,
            positions=list(self.app.positions_cache.values()),
            connected=connected,
        )

    @staticmethod
    def _stock_contract(symbol: str) -> Contract:
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = "USD"
        return contract

    def _next_ids(self, count: int) -> list[int]:
        with self.app.lock:
            if self.app.next_order_id is None:
                raise RuntimeError("IBKR order ID is unavailable")
            start = self.app.next_order_id
            self.app.next_order_id += count
            return list(range(start, start + count))

    async def submit(
        self,
        request: OrderRequest,
        quote: Quote,
        capability: BrokerWriteCapability | None,
    ) -> list[OrderEvent]:
        require_broker_write(capability)
        if request.idempotency_key in self._idempotency:
            return [
                OrderEvent(
                    order_id=request.order_id,
                    status=OrderStatus.REJECTED,
                    remaining_quantity=request.quantity,
                    message="duplicate_idempotency_key",
                )
            ]
        if not await self.is_connected():
            return [
                OrderEvent(
                    order_id=request.order_id,
                    status=OrderStatus.ERROR,
                    remaining_quantity=request.quantity,
                    message="broker_disconnected",
                )
            ]
        parent_id, target_id, stop_id = self._next_ids(3)
        self._idempotency[request.idempotency_key] = parent_id
        self.app.broker_to_internal[parent_id] = request.order_id
        self.app.broker_to_internal[target_id] = f"{request.order_id}:target"
        self.app.broker_to_internal[stop_id] = f"{request.order_id}:stop"
        contract = self._stock_contract(request.symbol)

        parent = Order()
        parent.orderId = parent_id
        parent.action = request.side.value
        parent.orderType = "LMT"
        parent.totalQuantity = request.quantity
        parent.lmtPrice = request.limit_price
        parent.transmit = False
        if self.account:
            parent.account = self.account

        target = Order()
        target.orderId = target_id
        target.action = Side.SELL.value if request.side == Side.BUY else Side.BUY.value
        target.orderType = "LMT"
        target.totalQuantity = request.quantity
        target.lmtPrice = request.target_price
        target.parentId = parent_id
        target.transmit = False
        if self.account:
            target.account = self.account

        stop = Order()
        stop.orderId = stop_id
        stop.action = target.action
        stop.orderType = "STP"
        stop.totalQuantity = request.quantity
        stop.auxPrice = request.stop_price
        stop.parentId = parent_id
        stop.transmit = True
        if self.account:
            stop.account = self.account

        self.app.placeOrder(parent_id, contract, parent)
        self.app.placeOrder(target_id, contract, target)
        self.app.placeOrder(stop_id, contract, stop)
        return [
            OrderEvent(
                order_id=request.order_id,
                status=OrderStatus.SUBMITTED,
                remaining_quantity=request.quantity,
                message=f"ibkr_bracket_parent={parent_id};target={target_id};stop={stop_id}",
                broker_order_id=str(parent_id),
            )
        ]

    async def _submit_simple_limit(
        self,
        *,
        symbol: str,
        side: Side,
        quantity: int,
        limit_price: float,
        internal_id: str,
        capability: BrokerWriteCapability | None,
    ) -> OrderEvent:
        require_broker_write(capability)
        if not await self.is_connected():
            return OrderEvent(
                order_id=internal_id,
                status=OrderStatus.ERROR,
                remaining_quantity=quantity,
                message="broker_disconnected",
            )
        broker_id = self._next_ids(1)[0]
        self.app.broker_to_internal[broker_id] = internal_id
        contract = self._stock_contract(symbol)
        order = Order()
        order.orderId = broker_id
        order.action = side.value
        order.orderType = "LMT"
        order.totalQuantity = quantity
        order.lmtPrice = limit_price
        order.transmit = True
        if self.account:
            order.account = self.account
        self.app.placeOrder(broker_id, contract, order)
        return OrderEvent(
            order_id=internal_id,
            status=OrderStatus.SUBMITTED,
            remaining_quantity=quantity,
            message=f"ibkr_simple_order={broker_id}",
            broker_order_id=str(broker_id),
        )

    async def process_quote(self, quote: Quote) -> list[OrderEvent]:
        with self.app.lock:
            events = list(self.app.order_events)
            self.app.order_events.clear()
        return events

    async def cancel_all(
        self, capability: BrokerWriteCapability | None
    ) -> list[OrderEvent]:
        require_broker_write(capability)
        self.app.reqGlobalCancel()
        await asyncio.sleep(0.2)
        return [
            OrderEvent(
                order_id="GLOBAL_CANCEL",
                status=OrderStatus.CANCEL_PENDING,
                message="IBKR global cancel requested",
            )
        ]

    async def flatten_all(
        self,
        quotes: dict[str, Quote],
        capability: BrokerWriteCapability | None,
    ) -> list[OrderEvent]:
        require_broker_write(capability)
        events: list[OrderEvent] = []
        snapshot = await self.get_account_snapshot()
        for position in snapshot.positions:
            quote = quotes.get(position.symbol)
            internal_id = f"flatten:{position.symbol}:{int(time.time())}"
            if quote is None:
                events.append(
                    OrderEvent(
                        order_id=internal_id,
                        status=OrderStatus.ERROR,
                        remaining_quantity=abs(position.quantity),
                        message="missing_fresh_quote",
                    )
                )
                continue
            side = Side.SELL if position.quantity > 0 else Side.BUY
            events.append(
                await self._submit_simple_limit(
                    symbol=position.symbol,
                    side=side,
                    quantity=abs(position.quantity),
                    limit_price=quote.bid if side == Side.SELL else quote.ask,
                    internal_id=internal_id,
                    capability=capability,
                )
            )
        return events
