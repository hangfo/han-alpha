from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from hanalpha.domain.enums import Side
from hanalpha.execution.control_models import (
    BrokerEvent,
    BrokerEventType,
    BrokerOrderTruth,
    BrokerProtectionTruth,
    BrokerSnapshot,
    ExecutionIntent,
)
from hanalpha.simulation.events import canonical_hash


class FakeScenario(StrEnum):
    ACCEPT = "accept"
    ACCEPT_DROP_RESPONSE = "accept_drop_response"
    DUPLICATE_ACK = "duplicate_ack"
    REJECT = "reject"
    PARTIAL_FILL = "partial_fill"
    MISSING_PROTECTION = "missing_protection"
    CANCEL_DROP_RESPONSE = "cancel_drop_response"


class BrokerSubmissionUnknown(RuntimeError):
    pass


class StaleFencingToken(RuntimeError):
    pass


class DurableFakeBroker:
    """Persistent broker truth and fault tape; idempotent by economic order key."""

    def __init__(self, path: Path, *, starting_cash: Decimal = Decimal("100000")) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS broker_meta (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), cash TEXT NOT NULL,
              highest_fencing_token INTEGER NOT NULL, next_order_id INTEGER NOT NULL,
              next_sequence INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS broker_orders (
              client_order_key TEXT PRIMARY KEY, broker_order_id TEXT UNIQUE NOT NULL,
              intent_json TEXT NOT NULL, status TEXT NOT NULL, filled_quantity INTEGER NOT NULL,
              response_dropped INTEGER NOT NULL, protection_quantity INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS broker_events (
              broker_event_id TEXT PRIMARY KEY, client_order_key TEXT NOT NULL,
              sequence INTEGER UNIQUE NOT NULL, event_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS broker_positions (
              instrument_id TEXT PRIMARY KEY, quantity INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scenario_queue (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, scenario TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS broker_tape (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, direction TEXT NOT NULL,
              item_type TEXT NOT NULL, item_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
              recorded_at TEXT NOT NULL
            );
            """
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO broker_meta VALUES (1, ?, 0, 1, 1)",
            (str(starting_cash),),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def enqueue(self, *scenarios: FakeScenario) -> None:
        with self.connection:
            self.connection.executemany(
                "INSERT INTO scenario_queue(scenario) VALUES (?)",
                ((scenario.value,) for scenario in scenarios),
            )

    def advance_fence(self, fencing_token: int) -> None:
        """Publish a newly acquired lease before it can submit any order."""
        with self.connection:
            self._accept_fencing_token(fencing_token)

    def submit(
        self, intent: ExecutionIntent, *, fencing_token: int, at: datetime
    ) -> tuple[BrokerEvent, ...]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            meta = self.connection.execute("SELECT * FROM broker_meta WHERE singleton=1").fetchone()
            if fencing_token < int(meta["highest_fencing_token"]):
                raise StaleFencingToken("broker rejected stale fencing token")
            self.connection.execute(
                "UPDATE broker_meta SET highest_fencing_token=? WHERE singleton=1",
                (fencing_token,),
            )
            existing = self.connection.execute(
                "SELECT * FROM broker_orders WHERE client_order_key=?",
                (intent.client_order_key,),
            ).fetchone()
            if existing is not None:
                prior_events = self._events_for(intent.client_order_key)
                self._tape("IN", "IDEMPOTENT_SUBMIT", intent.model_dump_json(), at)
                self.connection.commit()
                return prior_events
            scenario = self._next_scenario()
            broker_order_id = f"fake-{int(meta['next_order_id'])}"
            self.connection.execute(
                "UPDATE broker_meta SET next_order_id=next_order_id+1 WHERE singleton=1"
            )
            protection = 0 if scenario == FakeScenario.MISSING_PROTECTION else intent.quantity
            self.connection.execute(
                "INSERT INTO broker_orders VALUES (?, ?, ?, 'ACCEPTED', 0, 0, ?)",
                (intent.client_order_key, broker_order_id, intent.model_dump_json(), protection),
            )
            self._tape("IN", "SUBMIT", intent.model_dump_json(), at)
            if scenario == FakeScenario.REJECT:
                event = self._emit(intent, broker_order_id, BrokerEventType.REJECTED, at=at)
                self.connection.execute(
                    "UPDATE broker_orders SET status='REJECTED' WHERE client_order_key=?",
                    (intent.client_order_key,),
                )
                self.connection.commit()
                return (event,)
            ack = self._emit(intent, broker_order_id, BrokerEventType.ACKNOWLEDGED, at=at)
            if scenario == FakeScenario.ACCEPT_DROP_RESPONSE:
                self.connection.execute(
                    "UPDATE broker_orders SET response_dropped=1 WHERE client_order_key=?",
                    (intent.client_order_key,),
                )
                self.connection.commit()
                raise BrokerSubmissionUnknown("accepted by broker but response was dropped")
            events: tuple[BrokerEvent, ...] = (ack,)
            if scenario == FakeScenario.DUPLICATE_ACK:
                events = (ack, ack)
            elif scenario == FakeScenario.PARTIAL_FILL:
                quantity = max(1, intent.quantity // 2)
                fill = self._fill(intent, broker_order_id, quantity, intent.limit_price, at)
                events = (ack, fill)
            self.connection.commit()
            return events
        except BrokerSubmissionUnknown:
            raise
        except BaseException:
            self.connection.rollback()
            raise

    def fill(
        self,
        client_order_key: str,
        *,
        quantity: int,
        price: Decimal,
        at: datetime,
    ) -> BrokerEvent:
        with self.connection:
            row = self.connection.execute(
                "SELECT * FROM broker_orders WHERE client_order_key=?", (client_order_key,)
            ).fetchone()
            if row is None:
                raise KeyError(client_order_key)
            intent = ExecutionIntent.model_validate_json(row["intent_json"])
            return self._fill(intent, row["broker_order_id"], quantity, price, at)

    def cancel(
        self,
        client_order_key: str,
        *,
        fencing_token: int,
        at: datetime,
        fill_before_cancel_quantity: int = 0,
    ) -> tuple[BrokerEvent, ...]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self._accept_fencing_token(fencing_token)
            row = self.connection.execute(
                "SELECT * FROM broker_orders WHERE client_order_key=?", (client_order_key,)
            ).fetchone()
            if row is None:
                raise KeyError(client_order_key)
            intent = ExecutionIntent.model_validate_json(row["intent_json"])
            scenario = self._next_scenario()
            events: list[BrokerEvent] = []
            if fill_before_cancel_quantity > 0 and int(row["filled_quantity"]) < intent.quantity:
                events.append(
                    self._fill(
                        intent,
                        row["broker_order_id"],
                        fill_before_cancel_quantity,
                        intent.limit_price,
                        at,
                    )
                )
            refreshed = self.connection.execute(
                "SELECT filled_quantity FROM broker_orders WHERE client_order_key=?",
                (client_order_key,),
            ).fetchone()
            if int(refreshed["filled_quantity"]) < intent.quantity:
                cancelled = self._emit(
                    intent, row["broker_order_id"], BrokerEventType.CANCELLED, at=at
                )
                events.append(cancelled)
                self.connection.execute(
                    "UPDATE broker_orders SET status='CANCELLED' WHERE client_order_key=?",
                    (client_order_key,),
                )
            if scenario == FakeScenario.CANCEL_DROP_RESPONSE:
                self.connection.commit()
                raise BrokerSubmissionUnknown("cancel accepted but response was dropped")
            self.connection.commit()
            return tuple(events)
        except BaseException:
            self.connection.rollback()
            raise

    def commission(
        self,
        client_order_key: str,
        *,
        amount: Decimal,
        at: datetime,
    ) -> BrokerEvent:
        if amount < 0:
            raise ValueError("commission cannot be negative")
        with self.connection:
            row = self.connection.execute(
                "SELECT * FROM broker_orders WHERE client_order_key=?", (client_order_key,)
            ).fetchone()
            if row is None:
                raise KeyError(client_order_key)
            intent = ExecutionIntent.model_validate_json(row["intent_json"])
            event = self._emit(
                intent,
                row["broker_order_id"],
                BrokerEventType.COMMISSION,
                at=at,
                commission=amount,
            )
            meta = self.connection.execute(
                "SELECT cash FROM broker_meta WHERE singleton=1"
            ).fetchone()
            self.connection.execute(
                "UPDATE broker_meta SET cash=? WHERE singleton=1",
                (str(Decimal(meta["cash"]) - amount),),
            )
            return event

    def snapshot(self, *, at: datetime) -> BrokerSnapshot:
        meta = self.connection.execute("SELECT cash FROM broker_meta WHERE singleton=1").fetchone()
        orders = tuple(
            BrokerOrderTruth(
                broker_order_id=row["broker_order_id"],
                client_order_key=row["client_order_key"],
                instrument_id=ExecutionIntent.model_validate_json(row["intent_json"]).instrument_id,
                side=ExecutionIntent.model_validate_json(row["intent_json"]).side,
                quantity=ExecutionIntent.model_validate_json(row["intent_json"]).quantity,
                filled_quantity=int(row["filled_quantity"]),
                status=row["status"],
                protection_quantity=min(
                    int(row["protection_quantity"]), int(row["filled_quantity"])
                ),
            )
            for row in self.connection.execute(
                "SELECT * FROM broker_orders ORDER BY broker_order_id"
            )
        )
        positions = {
            row["instrument_id"]: int(row["quantity"])
            for row in self.connection.execute("SELECT * FROM broker_positions")
        }
        protections: dict[str, int] = {}
        for row in self.connection.execute(
            "SELECT intent_json, protection_quantity, filled_quantity FROM broker_orders"
        ):
            intent = ExecutionIntent.model_validate_json(row["intent_json"])
            if intent.side == Side.BUY and int(row["filled_quantity"]) > 0:
                protections[intent.instrument_id] = protections.get(intent.instrument_id, 0) + min(
                    int(row["protection_quantity"]), int(row["filled_quantity"])
                )
        events = tuple(
            BrokerEvent.model_validate_json(row["event_json"])
            for row in self.connection.execute(
                "SELECT event_json FROM broker_events ORDER BY sequence"
            )
        )
        protection_orders = tuple(
            BrokerProtectionTruth(
                protection_order_id=f"{row['broker_order_id']}:{kind.lower()}",
                parent_client_order_key=row["client_order_key"],
                protection_type=kind,
                quantity=min(int(row["protection_quantity"]), int(row["filled_quantity"])),
            )
            for row in self.connection.execute(
                """SELECT broker_order_id, client_order_key, protection_quantity, filled_quantity
                   FROM broker_orders WHERE filled_quantity>0 AND protection_quantity>0"""
            )
            for kind in ("STOP", "TARGET")
        )
        return BrokerSnapshot(
            as_of=at,
            cash=Decimal(meta["cash"]),
            settled_cash=Decimal(meta["cash"]),
            buying_power=Decimal(meta["cash"]),
            accrued_cash=Decimal("0"),
            base_currency="USD",
            currency_balances={"USD": Decimal(meta["cash"])},
            orders=orders,
            positions=positions,
            protections=protections,
            events=events,
            protection_orders=protection_orders,
        )

    def inject_broker_only_order(self, intent: ExecutionIntent, *, at: datetime) -> None:
        with self.connection:
            meta = self.connection.execute(
                "SELECT next_order_id FROM broker_meta WHERE singleton=1"
            ).fetchone()
            broker_id = f"external-{int(meta['next_order_id'])}"
            self.connection.execute(
                "UPDATE broker_meta SET next_order_id=next_order_id+1 WHERE singleton=1"
            )
            self.connection.execute(
                "INSERT INTO broker_orders VALUES (?, ?, ?, 'ACCEPTED', 0, 0, 0)",
                (intent.client_order_key, broker_id, intent.model_dump_json()),
            )
            self._tape("BROKER", "EXTERNAL_ORDER", intent.model_dump_json(), at)

    def tape_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM broker_tape").fetchone()[0])

    def _fill(
        self,
        intent: ExecutionIntent,
        broker_order_id: str,
        quantity: int,
        price: Decimal,
        at: datetime,
    ) -> BrokerEvent:
        row = self.connection.execute(
            "SELECT filled_quantity FROM broker_orders WHERE client_order_key=?",
            (intent.client_order_key,),
        ).fetchone()
        remaining = intent.quantity - int(row["filled_quantity"])
        actual = min(quantity, remaining)
        if actual <= 0:
            raise ValueError("broker order is already fully filled")
        total = int(row["filled_quantity"]) + actual
        event_type = (
            BrokerEventType.FILL if total == intent.quantity else BrokerEventType.PARTIAL_FILL
        )
        event = self._emit(
            intent,
            broker_order_id,
            event_type,
            at=at,
            filled_quantity=actual,
            fill_price=price,
        )
        status = "FILLED" if total == intent.quantity else "PARTIALLY_FILLED"
        self.connection.execute(
            "UPDATE broker_orders SET filled_quantity=?, status=? WHERE client_order_key=?",
            (total, status, intent.client_order_key),
        )
        signed = actual if intent.side == Side.BUY else -actual
        self.connection.execute(
            """INSERT INTO broker_positions VALUES (?, ?)
               ON CONFLICT(instrument_id) DO UPDATE SET quantity=quantity+excluded.quantity""",
            (intent.instrument_id, signed),
        )
        cash_delta = -(price * actual) if intent.side == Side.BUY else price * actual
        meta = self.connection.execute(
            "SELECT cash FROM broker_meta WHERE singleton=1"
        ).fetchone()
        self.connection.execute(
            "UPDATE broker_meta SET cash=? WHERE singleton=1",
            (str(Decimal(meta["cash"]) + cash_delta),),
        )
        return event

    def _emit(
        self,
        intent: ExecutionIntent,
        broker_order_id: str,
        event_type: BrokerEventType,
        *,
        at: datetime,
        filled_quantity: int = 0,
        fill_price: Decimal | None = None,
        commission: Decimal = Decimal("0"),
    ) -> BrokerEvent:
        meta = self.connection.execute(
            "SELECT next_sequence FROM broker_meta WHERE singleton=1"
        ).fetchone()
        sequence = int(meta["next_sequence"])
        self.connection.execute(
            "UPDATE broker_meta SET next_sequence=next_sequence+1 WHERE singleton=1"
        )
        raw = {
            "broker_order_id": broker_order_id,
            "client_order_key": intent.client_order_key,
            "event_type": event_type.value,
            "sequence": sequence,
            "filled_quantity": filled_quantity,
            "fill_price": str(fill_price) if fill_price is not None else None,
            "commission": str(commission),
        }
        event = BrokerEvent(
            broker_event_id=canonical_hash(raw),
            broker_order_id=broker_order_id,
            client_order_key=intent.client_order_key,
            event_type=event_type,
            sequence=sequence,
            filled_quantity=filled_quantity,
            fill_price=fill_price,
            commission=commission,
            occurred_at=at,
            received_at=at,
            raw_payload_hash=canonical_hash(raw),
        )
        self.connection.execute(
            "INSERT INTO broker_events VALUES (?, ?, ?, ?)",
            (event.broker_event_id, intent.client_order_key, sequence, event.model_dump_json()),
        )
        self._tape("OUT", event_type.value, event.model_dump_json(), at)
        return event

    def _events_for(self, client_order_key: str) -> tuple[BrokerEvent, ...]:
        return tuple(
            BrokerEvent.model_validate_json(row["event_json"])
            for row in self.connection.execute(
                "SELECT event_json FROM broker_events WHERE client_order_key=? ORDER BY sequence",
                (client_order_key,),
            )
        )

    def _next_scenario(self) -> FakeScenario:
        row = self.connection.execute(
            "SELECT sequence, scenario FROM scenario_queue ORDER BY sequence LIMIT 1"
        ).fetchone()
        if row is None:
            return FakeScenario.ACCEPT
        self.connection.execute("DELETE FROM scenario_queue WHERE sequence=?", (row["sequence"],))
        return FakeScenario(row["scenario"])

    def _accept_fencing_token(self, fencing_token: int) -> None:
        meta = self.connection.execute(
            "SELECT highest_fencing_token FROM broker_meta WHERE singleton=1"
        ).fetchone()
        if fencing_token < int(meta["highest_fencing_token"]):
            raise StaleFencingToken("broker rejected stale fencing token")
        self.connection.execute(
            "UPDATE broker_meta SET highest_fencing_token=? WHERE singleton=1",
            (fencing_token,),
        )

    def _tape(self, direction: str, item_type: str, payload: str, at: datetime) -> None:
        self.connection.execute(
            """INSERT INTO broker_tape(direction, item_type, item_hash, payload_json, recorded_at)
               VALUES (?, ?, ?, ?, ?)""",
            (direction, item_type, canonical_hash({"payload": payload}), payload, at.isoformat()),
        )
