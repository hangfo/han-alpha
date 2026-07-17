from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from hanalpha.config import ExecutionConfig
from hanalpha.domain.enums import OrderStatus, Side
from hanalpha.domain.models import (
    AccountSnapshot,
    Fill,
    OrderEvent,
    OrderRequest,
    Position,
    Quote,
)


@dataclass
class _OpenOrder:
    request: OrderRequest
    submitted_at: datetime


@dataclass
class _Protection:
    symbol: str
    quantity: int
    stop_price: float
    target_price: float
    entry_order_id: str


class SimulatedBroker:
    """Conservative paper broker with adverse slippage and append-only events."""

    def __init__(self, starting_cash: float, config: ExecutionConfig) -> None:
        self.config = config
        self.cash = starting_cash
        self.peak_nlv = starting_cash
        self.start_of_day_nlv = starting_cash
        self.positions: dict[str, Position] = {}
        self.open_orders: dict[str, _OpenOrder] = {}
        self.protections: dict[str, _Protection] = {}
        self.fills: list[Fill] = []
        self._idempotency: dict[str, str] = {}
        self._connected = True
        self._lock = asyncio.Lock()

    async def is_connected(self) -> bool:
        return self._connected

    def set_connected(self, connected: bool) -> None:
        self._connected = connected

    def _commission(self, quantity: int) -> float:
        return max(self.config.minimum_commission, quantity * self.config.commission_per_share)

    def _slipped_price(self, quote: Quote, side: Side) -> float:
        multiplier = self.config.slippage_bps / 10_000
        if side == Side.BUY:
            return quote.ask * (1 + multiplier)
        return quote.bid * (1 - multiplier)

    def _mark_to_market(self) -> float:
        return self.cash + sum(position.market_value for position in self.positions.values())

    async def get_account_snapshot(self) -> AccountSnapshot:
        nlv = self._mark_to_market()
        self.peak_nlv = max(self.peak_nlv, nlv)
        return AccountSnapshot(
            timestamp=datetime.now(UTC),
            net_liquidation=max(0.01, nlv),
            cash=self.cash,
            buying_power=max(0.0, self.cash),
            daily_pnl=nlv - self.start_of_day_nlv,
            peak_net_liquidation=max(0.01, self.peak_nlv),
            positions=list(self.positions.values()),
            connected=self._connected,
        )

    async def submit(self, order: OrderRequest, quote: Quote) -> list[OrderEvent]:
        async with self._lock:
            if not self._connected:
                return [
                    OrderEvent(
                        order_id=order.order_id,
                        status=OrderStatus.ERROR,
                        remaining_quantity=order.quantity,
                        message="broker_disconnected",
                    )
                ]
            prior = self._idempotency.get(order.idempotency_key)
            if prior is not None:
                return [
                    OrderEvent(
                        order_id=order.order_id,
                        status=OrderStatus.REJECTED,
                        remaining_quantity=order.quantity,
                        message=f"duplicate_idempotency_key:{prior}",
                    )
                ]
            self._idempotency[order.idempotency_key] = order.order_id
            self.open_orders[order.order_id] = _OpenOrder(order, datetime.now(UTC))
            submitted = OrderEvent(
                order_id=order.order_id,
                status=OrderStatus.SUBMITTED,
                remaining_quantity=order.quantity,
                message="accepted_by_simulated_broker",
            )
            events = [submitted]
            events.extend(self._try_fill(order, quote))
            return events

    def _try_fill(self, order: OrderRequest, quote: Quote) -> list[OrderEvent]:
        marketable = (order.side == Side.BUY and order.limit_price >= quote.ask) or (
            order.side == Side.SELL and order.limit_price <= quote.bid
        )
        if not marketable:
            return []
        fill_price = self._slipped_price(quote, order.side)
        commission = self._commission(order.quantity)
        notional = fill_price * order.quantity
        if order.side == Side.BUY and notional + commission > self.cash:
            self.open_orders.pop(order.order_id, None)
            return [
                OrderEvent(
                    order_id=order.order_id,
                    status=OrderStatus.REJECTED,
                    remaining_quantity=order.quantity,
                    message="insufficient_cash_after_slippage",
                )
            ]
        if order.side == Side.BUY:
            existing = self.positions.get(order.symbol)
            old_quantity = existing.quantity if existing else 0
            old_cost = existing.average_cost if existing else 0.0
            new_quantity = old_quantity + order.quantity
            average_cost = ((old_quantity * old_cost) + notional) / new_quantity
            self.positions[order.symbol] = Position(
                symbol=order.symbol,
                quantity=new_quantity,
                average_cost=average_cost,
                mark_price=quote.last,
                sector=existing.sector if existing else "UNKNOWN",
            )
            self.cash -= notional + commission
            self.protections[order.symbol] = _Protection(
                symbol=order.symbol,
                quantity=order.quantity,
                stop_price=order.stop_price,
                target_price=order.target_price,
                entry_order_id=order.order_id,
            )
        else:
            existing = self.positions.get(order.symbol)
            if existing is None or existing.quantity < order.quantity:
                self.open_orders.pop(order.order_id, None)
                return [
                    OrderEvent(
                        order_id=order.order_id,
                        status=OrderStatus.REJECTED,
                        remaining_quantity=order.quantity,
                        message="shorting_not_supported_or_insufficient_position",
                    )
                ]
            remaining = existing.quantity - order.quantity
            self.cash += notional - commission
            if remaining == 0:
                self.positions.pop(order.symbol, None)
                self.protections.pop(order.symbol, None)
            else:
                self.positions[order.symbol] = existing.model_copy(
                    update={"quantity": remaining, "mark_price": quote.last}
                )
        fill = Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            commission=commission,
        )
        self.fills.append(fill)
        self.open_orders.pop(order.order_id, None)
        return [
            OrderEvent(
                order_id=order.order_id,
                status=OrderStatus.FILLED,
                filled_quantity=order.quantity,
                remaining_quantity=0,
                average_fill_price=fill_price,
                message=f"commission={commission:.2f}",
            )
        ]

    async def process_quote(self, quote: Quote) -> list[OrderEvent]:
        async with self._lock:
            events: list[OrderEvent] = []
            position = self.positions.get(quote.symbol)
            if position is not None:
                self.positions[quote.symbol] = position.model_copy(update={"mark_price": quote.last})
            for item in list(self.open_orders.values()):
                if item.request.symbol == quote.symbol:
                    events.extend(self._try_fill(item.request, quote))
            protection = self.protections.get(quote.symbol)
            position = self.positions.get(quote.symbol)
            if protection and position:
                exit_reason: str | None = None
                if quote.bid <= protection.stop_price:
                    exit_reason = "protective_stop"
                elif quote.bid >= protection.target_price:
                    exit_reason = "profit_target"
                if exit_reason:
                    quantity = min(protection.quantity, position.quantity)
                    exit_order = OrderRequest(
                        order_id=f"exit:{protection.entry_order_id}:{exit_reason}",
                        plan_id=f"exit:{protection.entry_order_id}",
                        symbol=quote.symbol,
                        side=Side.SELL,
                        quantity=quantity,
                        limit_price=quote.bid,
                        stop_price=quote.ask * 1.1,
                        target_price=max(0.01, quote.bid * 0.9),
                        idempotency_key=f"exit:{protection.entry_order_id}:{exit_reason}",
                        status=OrderStatus.SUBMITTED,
                    )
                    self._idempotency[exit_order.idempotency_key] = exit_order.order_id
                    self.open_orders[exit_order.order_id] = _OpenOrder(
                        exit_order, datetime.now(UTC)
                    )
                    events.append(
                        OrderEvent(
                            order_id=exit_order.order_id,
                            status=OrderStatus.SUBMITTED,
                            remaining_quantity=quantity,
                            message=exit_reason,
                        )
                    )
                    events.extend(self._try_fill(exit_order, quote))
            return events

    async def cancel_all(self) -> list[OrderEvent]:
        async with self._lock:
            events = [
                OrderEvent(
                    order_id=item.request.order_id,
                    status=OrderStatus.CANCELLED,
                    remaining_quantity=item.request.quantity,
                    message="cancel_all",
                )
                for item in self.open_orders.values()
            ]
            self.open_orders.clear()
            return events

    async def flatten_all(self, quotes: dict[str, Quote]) -> list[OrderEvent]:
        events: list[OrderEvent] = []
        for symbol, position in list(self.positions.items()):
            quote = quotes.get(symbol)
            if quote is None:
                events.append(
                    OrderEvent(
                        order_id=f"flatten:{symbol}",
                        status=OrderStatus.ERROR,
                        remaining_quantity=position.quantity,
                        message="missing_fresh_quote",
                    )
                )
                continue
            order = OrderRequest(
                order_id=f"flatten:{symbol}:{int(datetime.now(UTC).timestamp())}",
                plan_id=f"flatten:{symbol}",
                symbol=symbol,
                side=Side.SELL,
                quantity=position.quantity,
                limit_price=quote.bid,
                stop_price=quote.ask * 1.1,
                target_price=max(0.01, quote.bid * 0.9),
                idempotency_key=f"flatten:{symbol}:{position.quantity}",
            )
            events.extend(await self.submit(order, quote))
        return events
