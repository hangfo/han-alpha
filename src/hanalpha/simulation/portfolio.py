from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hanalpha.domain.enums import Side
from hanalpha.pit.models import require_aware
from hanalpha.simulation.events import FillEvent
from hanalpha.simulation.orders import OrderIntent


def _decimal(value: Decimal | float | int | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


class ReservationRejected(RuntimeError):
    pass


class DuplicateLedgerEvent(RuntimeError):
    pass


class JournalAccount(StrEnum):
    CASH = "cash"
    OPENING_EQUITY = "opening_equity"
    POSITIONS_AT_COST = "positions_at_cost"
    COMMISSION_EXPENSE = "commission_expense"
    REALIZED_PNL = "realized_pnl"
    DIVIDEND_INCOME = "dividend_income"


class JournalLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    account: JournalAccount
    debit: Decimal = Field(default=Decimal("0"), ge=0)
    credit: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def validate_sides(self) -> JournalLine:
        if self.debit > 0 and self.credit > 0:
            raise ValueError("journal line cannot debit and credit simultaneously")
        return self


class JournalEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    at: datetime
    reason: str
    lines: tuple[JournalLine, ...]

    @property
    def total_debits(self) -> Decimal:
        return sum((line.debit for line in self.lines), Decimal("0"))

    @property
    def total_credits(self) -> Decimal:
        return sum((line.credit for line in self.lines), Decimal("0"))

    @property
    def is_balanced(self) -> bool:
        return self.total_debits == self.total_credits

    @model_validator(mode="after")
    def validate_entry(self) -> JournalEntry:
        require_aware(self.at, "at")
        if not self.is_balanced:
            raise ValueError("journal entry debits and credits must balance")
        return self


class PortfolioPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_gross_exposure: Decimal = Decimal("1")
    max_symbol_exposure: Decimal = Decimal("0.35")
    max_positions: int = Field(default=20, gt=0)
    max_risk_per_trade: Decimal = Decimal("0.02")
    max_total_risk: Decimal = Decimal("0.10")
    minimum_commission: Decimal = Decimal("1")


class CashEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    at: datetime
    amount: Decimal
    reason: str
    reference_id: str


class PositionLot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lot_id: str
    instrument_id: str
    opened_at: datetime
    original_quantity: Decimal
    remaining_quantity: Decimal
    unit_cost: Decimal
    risk_per_share: Decimal


class PortfolioPosition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument_id: str
    quantity: Decimal
    average_cost: Decimal
    mark_price: Decimal

    @property
    def market_value(self) -> Decimal:
        return self.quantity * self.mark_price


class PortfolioSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: datetime
    cash: Decimal
    available_cash: Decimal
    reserved_cash: Decimal
    net_liquidation: Decimal
    gross_exposure: Decimal
    realized_pnl: Decimal
    commissions: Decimal
    open_risk: Decimal
    positions: list[PortfolioPosition]


@dataclass
class _Reservation:
    order_id: str
    instrument_id: str
    side: Side
    remaining_cash: Decimal
    remaining_notional: Decimal
    remaining_quantity: Decimal
    risk_amount: Decimal
    risk_per_share: Decimal
    oco_group_id: str | None


class PortfolioLedger:
    def __init__(self, starting_cash: Decimal, policy: PortfolioPolicy) -> None:
        if starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        self.starting_cash = starting_cash
        self.policy = policy
        self.cash = starting_cash
        self.realized_pnl = Decimal("0")
        self.commissions = Decimal("0")
        self.cash_entries: list[CashEntry] = []
        self.journal_entries: list[JournalEntry] = []
        self.lots: list[PositionLot] = []
        self.marks: dict[str, Decimal] = {}
        self._reservations: dict[str, _Reservation] = {}
        self._event_ids: set[str] = set()
        self._append_cash(
            event_id="initial-capital",
            at=datetime.min.replace(tzinfo=UTC),
            amount=starting_cash,
            reason="initial_capital",
            reference_id="initial",
            mutate_cash=False,
        )
        self._append_journal(
            event_id="initial-capital",
            at=datetime.min.replace(tzinfo=UTC),
            reason="initial_capital",
            lines=(
                JournalLine(account=JournalAccount.CASH, debit=starting_cash),
                JournalLine(account=JournalAccount.OPENING_EQUITY, credit=starting_cash),
            ),
        )

    @property
    def reserved_cash(self) -> Decimal:
        return sum((item.remaining_cash for item in self._reservations.values()), Decimal("0"))

    @property
    def available_cash(self) -> Decimal:
        return self.cash - self.reserved_cash

    def reserve(self, intent: OrderIntent) -> None:
        if intent.order_id in self._reservations:
            raise ReservationRejected("duplicate reservation")
        planned = _decimal(intent.planned_price)
        quantity = Decimal(intent.quantity)
        notional = planned * quantity
        if intent.side == Side.BUY and intent.protective_stop is None:
            raise ReservationRejected("buy order requires protective stop")
        stop = _decimal(intent.protective_stop or intent.planned_price)
        risk_per_share = abs(planned - stop) if intent.side == Side.BUY else Decimal("0")
        risk = risk_per_share * quantity
        snapshot = self.snapshot(intent.submitted_at)
        if risk > snapshot.net_liquidation * self.policy.max_risk_per_trade:
            raise ReservationRejected("risk limit exceeded")
        reserved_risk = sum(
            (item.risk_amount for item in self._reservations.values()), Decimal("0")
        )
        if snapshot.open_risk + reserved_risk + risk > (
            snapshot.net_liquidation * self.policy.max_total_risk
        ):
            raise ReservationRejected("total risk limit exceeded")
        current_gross = sum((abs(item.market_value) for item in snapshot.positions), Decimal("0"))
        reserved_notional = sum(
            (item.remaining_notional for item in self._reservations.values()), Decimal("0")
        )
        exposure_delta = notional if intent.side == Side.BUY else Decimal("0")
        if current_gross + reserved_notional + exposure_delta > (
            snapshot.net_liquidation * self.policy.max_gross_exposure
        ):
            raise ReservationRejected("gross exposure exceeded")
        symbol_value = sum(
            (
                abs(item.market_value)
                for item in snapshot.positions
                if item.instrument_id == intent.instrument_id
            ),
            Decimal("0"),
        ) + sum(
            (
                item.remaining_notional
                for item in self._reservations.values()
                if item.instrument_id == intent.instrument_id
            ),
            Decimal("0"),
        )
        if intent.side == Side.BUY and symbol_value + notional > (
            snapshot.net_liquidation * self.policy.max_symbol_exposure
        ):
            raise ReservationRejected("symbol exposure exceeded")
        if intent.side == Side.BUY:
            current_symbols = {item.instrument_id for item in snapshot.positions}
            reserved_symbols = {
                item.instrument_id for item in self._reservations.values() if item.side == Side.BUY
            }
            if (
                intent.instrument_id not in current_symbols | reserved_symbols
                and len(current_symbols | reserved_symbols) >= self.policy.max_positions
            ):
                raise ReservationRejected("position count exceeded")
            required_cash = notional + self.policy.minimum_commission
            if required_cash > self.available_cash:
                raise ReservationRejected("insufficient cash")
            reserved_quantity = Decimal("0")
        else:
            reserved_quantity = quantity
            already_reserved = self._reserved_sell_quantity(intent.instrument_id)
            same_group = Decimal("0")
            if intent.oco_group_id is not None:
                same_group = max(
                    (
                        item.remaining_quantity
                        for item in self._reservations.values()
                        if item.instrument_id == intent.instrument_id
                        and item.side == Side.SELL
                        and item.oco_group_id == intent.oco_group_id
                    ),
                    default=Decimal("0"),
                )
            incremental = (
                quantity
                if intent.oco_group_id is None
                else max(Decimal("0"), quantity - same_group)
            )
            if already_reserved + incremental > self.position_quantity(intent.instrument_id):
                raise ReservationRejected("insufficient position")
            required_cash = Decimal("0")
        self._reservations[intent.order_id] = _Reservation(
            order_id=intent.order_id,
            instrument_id=intent.instrument_id,
            side=intent.side,
            remaining_cash=required_cash,
            remaining_notional=notional if intent.side == Side.BUY else Decimal("0"),
            remaining_quantity=reserved_quantity,
            risk_amount=risk,
            risk_per_share=risk_per_share,
            oco_group_id=intent.oco_group_id,
        )

    def release(self, order_id: str) -> None:
        self._reservations.pop(order_id, None)

    def apply_fill(self, fill: FillEvent) -> None:
        if fill.fill_id in self._event_ids:
            raise DuplicateLedgerEvent(fill.fill_id)
        reservation = self._reservations.get(fill.order_id)
        if reservation is None:
            raise ReservationRejected("fill has no active reservation")
        if reservation.instrument_id != fill.instrument_id or reservation.side != fill.side:
            raise ReservationRejected("fill does not match reservation")
        notional = _decimal(fill.price) * Decimal(fill.quantity)
        commission = _decimal(fill.commission)
        if fill.side == Side.BUY:
            cost = notional + commission
            if cost > reservation.remaining_cash + self.available_cash:
                raise ReservationRejected("fill exceeds reserved and available cash")
            self._append_cash(
                event_id=fill.fill_id,
                at=fill.occurred_at,
                amount=-cost,
                reason="buy_fill",
                reference_id=fill.order_id,
            )
            self._append_journal(
                event_id=fill.fill_id,
                at=fill.occurred_at,
                reason="buy_fill",
                lines=(
                    JournalLine(account=JournalAccount.POSITIONS_AT_COST, debit=cost),
                    JournalLine(account=JournalAccount.CASH, credit=cost),
                ),
            )
            unit_cost = cost / Decimal(fill.quantity)
            self.lots.append(
                PositionLot(
                    lot_id=fill.fill_id,
                    instrument_id=fill.instrument_id,
                    opened_at=fill.occurred_at,
                    original_quantity=Decimal(fill.quantity),
                    remaining_quantity=Decimal(fill.quantity),
                    unit_cost=unit_cost,
                    risk_per_share=reservation.risk_per_share,
                )
            )
            reservation.remaining_cash = max(Decimal("0"), reservation.remaining_cash - cost)
            reservation.risk_amount = max(
                Decimal("0"),
                reservation.risk_amount - reservation.risk_per_share * Decimal(fill.quantity),
            )
        else:
            cost_basis = self._consume_fifo(fill.instrument_id, Decimal(fill.quantity))
            proceeds = notional - commission
            self._append_cash(
                event_id=fill.fill_id,
                at=fill.occurred_at,
                amount=proceeds,
                reason="sell_fill",
                reference_id=fill.order_id,
            )
            gross_pnl = notional - cost_basis
            journal_lines = [
                JournalLine(account=JournalAccount.CASH, debit=proceeds),
                JournalLine(account=JournalAccount.COMMISSION_EXPENSE, debit=commission),
                JournalLine(account=JournalAccount.POSITIONS_AT_COST, credit=cost_basis),
            ]
            if gross_pnl >= 0:
                journal_lines.append(
                    JournalLine(account=JournalAccount.REALIZED_PNL, credit=gross_pnl)
                )
            else:
                journal_lines.append(
                    JournalLine(account=JournalAccount.REALIZED_PNL, debit=-gross_pnl)
                )
            self._append_journal(
                event_id=fill.fill_id,
                at=fill.occurred_at,
                reason="sell_fill",
                lines=tuple(journal_lines),
            )
            self.realized_pnl += proceeds - cost_basis
            reservation.remaining_quantity -= Decimal(fill.quantity)
        reservation.remaining_notional = max(
            Decimal("0"),
            reservation.remaining_notional - _decimal(fill.price) * Decimal(fill.quantity),
        )
        self.commissions += commission
        self._event_ids.add(fill.fill_id)

    def mark(self, instrument_id: str, price: Decimal) -> None:
        if price <= 0:
            raise ValueError("mark must be positive")
        self.marks[instrument_id] = price

    def position_quantity(self, instrument_id: str) -> Decimal:
        return sum(
            (lot.remaining_quantity for lot in self.lots if lot.instrument_id == instrument_id),
            Decimal("0"),
        )

    def apply_split(
        self, *, action_id: str, instrument_id: str, ratio: Decimal, at: datetime
    ) -> None:
        self._require_new_event(action_id)
        self._require_no_reservations(instrument_id)
        require_aware(at, "at")
        if ratio <= 0:
            raise ValueError("split ratio must be positive")
        updated: list[PositionLot] = []
        for lot in self.lots:
            if lot.instrument_id != instrument_id:
                updated.append(lot)
                continue
            updated.append(
                lot.model_copy(
                    update={
                        "original_quantity": lot.original_quantity * ratio,
                        "remaining_quantity": lot.remaining_quantity * ratio,
                        "unit_cost": lot.unit_cost / ratio,
                        "risk_per_share": lot.risk_per_share / ratio,
                    }
                )
            )
        self.lots = updated
        if instrument_id in self.marks:
            self.marks[instrument_id] /= ratio
        self._append_journal(
            event_id=action_id,
            at=at,
            reason="split_quantity_restatement",
            lines=(),
        )
        self._event_ids.add(action_id)

    def apply_dividend(
        self,
        *,
        action_id: str,
        instrument_id: str,
        cash_per_share: Decimal,
        at: datetime,
    ) -> None:
        self._require_new_event(action_id)
        if cash_per_share < 0:
            raise ValueError("cash_per_share must not be negative")
        quantity = self.position_quantity(instrument_id)
        amount = quantity * cash_per_share
        self._append_cash(
            event_id=action_id,
            at=at,
            amount=amount,
            reason="cash_dividend",
            reference_id=instrument_id,
        )
        self._append_journal(
            event_id=action_id,
            at=at,
            reason="cash_dividend",
            lines=(
                JournalLine(account=JournalAccount.CASH, debit=amount),
                JournalLine(account=JournalAccount.DIVIDEND_INCOME, credit=amount),
            ),
        )
        self._event_ids.add(action_id)

    def apply_delisting(
        self,
        *,
        action_id: str,
        instrument_id: str,
        cash_per_share: Decimal,
        at: datetime,
    ) -> None:
        self._require_new_event(action_id)
        self._require_no_reservations(instrument_id)
        require_aware(at, "at")
        if cash_per_share < 0:
            raise ValueError("cash_per_share must not be negative")
        quantity = self.position_quantity(instrument_id)
        cost_basis = sum(
            (
                lot.remaining_quantity * lot.unit_cost
                for lot in self.lots
                if lot.instrument_id == instrument_id
            ),
            Decimal("0"),
        )
        recovery = quantity * cash_per_share
        self.lots = [
            lot.model_copy(update={"remaining_quantity": Decimal("0")})
            if lot.instrument_id == instrument_id
            else lot
            for lot in self.lots
        ]
        self._append_cash(
            event_id=action_id,
            at=at,
            amount=recovery,
            reason="delisting_recovery",
            reference_id=instrument_id,
        )
        gross_pnl = recovery - cost_basis
        journal_lines = [
            JournalLine(account=JournalAccount.CASH, debit=recovery),
            JournalLine(account=JournalAccount.POSITIONS_AT_COST, credit=cost_basis),
        ]
        if gross_pnl >= 0:
            journal_lines.append(JournalLine(account=JournalAccount.REALIZED_PNL, credit=gross_pnl))
        else:
            journal_lines.append(JournalLine(account=JournalAccount.REALIZED_PNL, debit=-gross_pnl))
        self._append_journal(
            event_id=action_id,
            at=at,
            reason="delisting_recovery",
            lines=tuple(journal_lines),
        )
        self.realized_pnl += recovery - cost_basis
        self.marks.pop(instrument_id, None)
        self._event_ids.add(action_id)

    def snapshot(self, as_of: datetime) -> PortfolioSnapshot:
        require_aware(as_of, "as_of")
        positions: list[PortfolioPosition] = []
        instruments = sorted({lot.instrument_id for lot in self.lots if lot.remaining_quantity > 0})
        for instrument_id in instruments:
            lots = [
                lot
                for lot in self.lots
                if lot.instrument_id == instrument_id and lot.remaining_quantity > 0
            ]
            quantity = sum((lot.remaining_quantity for lot in lots), Decimal("0"))
            total_cost = sum((lot.remaining_quantity * lot.unit_cost for lot in lots), Decimal("0"))
            mark = self.marks.get(instrument_id, total_cost / quantity)
            positions.append(
                PortfolioPosition(
                    instrument_id=instrument_id,
                    quantity=quantity,
                    average_cost=total_cost / quantity,
                    mark_price=mark,
                )
            )
        gross_value = sum((abs(item.market_value) for item in positions), Decimal("0"))
        net_liquidation = self.cash + sum((item.market_value for item in positions), Decimal("0"))
        gross = gross_value / net_liquidation if net_liquidation > 0 else Decimal("0")
        open_risk = sum(
            (lot.remaining_quantity * lot.risk_per_share for lot in self.lots),
            Decimal("0"),
        )
        return PortfolioSnapshot(
            as_of=as_of,
            cash=self.cash,
            available_cash=self.available_cash,
            reserved_cash=self.reserved_cash,
            net_liquidation=net_liquidation,
            gross_exposure=gross,
            realized_pnl=self.realized_pnl,
            commissions=self.commissions,
            open_risk=open_risk,
            positions=positions,
        )

    def assert_conservation(self) -> None:
        expected = sum((entry.amount for entry in self.cash_entries), Decimal("0"))
        if self.cash != expected:
            raise AssertionError(f"cash ledger mismatch: cash={self.cash} entries={expected}")
        if any(lot.remaining_quantity < 0 for lot in self.lots):
            raise AssertionError("negative lot quantity")
        if any(not entry.is_balanced for entry in self.journal_entries):
            raise AssertionError("unbalanced journal entry")
        if self.account_balance(JournalAccount.CASH) != self.cash:
            raise AssertionError("journal cash account does not match portfolio cash")

    def account_balance(self, account: JournalAccount) -> Decimal:
        return sum(
            (
                line.debit - line.credit
                for entry in self.journal_entries
                for line in entry.lines
                if line.account == account
            ),
            Decimal("0"),
        )

    def _append_cash(
        self,
        *,
        event_id: str,
        at: datetime,
        amount: Decimal,
        reason: str,
        reference_id: str,
        mutate_cash: bool = True,
    ) -> None:
        require_aware(at, "at")
        self.cash_entries.append(
            CashEntry(
                event_id=event_id,
                at=at,
                amount=amount,
                reason=reason,
                reference_id=reference_id,
            )
        )
        if mutate_cash:
            self.cash += amount

    def _append_journal(
        self,
        *,
        event_id: str,
        at: datetime,
        reason: str,
        lines: tuple[JournalLine, ...],
    ) -> None:
        if any(entry.event_id == event_id for entry in self.journal_entries):
            raise DuplicateLedgerEvent(event_id)
        self.journal_entries.append(
            JournalEntry(event_id=event_id, at=at, reason=reason, lines=lines)
        )

    def _consume_fifo(self, instrument_id: str, quantity: Decimal) -> Decimal:
        remaining = quantity
        cost_basis = Decimal("0")
        updated: list[PositionLot] = []
        for lot in self.lots:
            if lot.instrument_id != instrument_id or remaining <= 0:
                updated.append(lot)
                continue
            consumed = min(lot.remaining_quantity, remaining)
            cost_basis += consumed * lot.unit_cost
            remaining -= consumed
            updated.append(
                lot.model_copy(update={"remaining_quantity": lot.remaining_quantity - consumed})
            )
        if remaining > 0:
            raise ReservationRejected("sell fill exceeds held quantity")
        self.lots = updated
        return cost_basis

    def _require_new_event(self, event_id: str) -> None:
        if event_id in self._event_ids:
            raise DuplicateLedgerEvent(event_id)

    def _require_no_reservations(self, instrument_id: str) -> None:
        if any(item.instrument_id == instrument_id for item in self._reservations.values()):
            raise ReservationRejected("corporate action requires released orders")

    def _reserved_sell_quantity(self, instrument_id: str) -> Decimal:
        groups: dict[str, Decimal] = {}
        for item in self._reservations.values():
            if item.instrument_id != instrument_id or item.side != Side.SELL:
                continue
            key = item.oco_group_id or item.order_id
            groups[key] = max(groups.get(key, Decimal("0")), item.remaining_quantity)
        return sum(groups.values(), Decimal("0"))
