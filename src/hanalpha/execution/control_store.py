from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from hanalpha.execution.control_models import (
    BrokerEvent,
    BrokerEventType,
    DecisionCapsule,
    ExecutionIntent,
    ExecutionLease,
    ExecutionStatus,
    OutboxCommand,
    OutboxStatus,
    ReservationStatus,
    RiskReservation,
)
from hanalpha.simulation.events import canonical_hash


class ExecutionInvariantError(RuntimeError):
    pass


class DurableExecutionStore:
    """SQLite control-plane truth with append-only economic events and projections."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS decision_capsules (
              decision_id TEXT PRIMARY KEY, capsule_hash TEXT UNIQUE NOT NULL,
              capsule_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS risk_reservations (
              reservation_id TEXT PRIMARY KEY, decision_id TEXT UNIQUE NOT NULL,
              reservation_json TEXT NOT NULL, status TEXT NOT NULL,
              quantity_reserved INTEGER NOT NULL, quantity_consumed INTEGER NOT NULL,
              version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS execution_intents (
              intent_id TEXT PRIMARY KEY, decision_id TEXT UNIQUE NOT NULL,
              reservation_id TEXT UNIQUE NOT NULL, client_order_key TEXT UNIQUE NOT NULL,
              intent_json TEXT NOT NULL, status TEXT NOT NULL, filled_quantity INTEGER NOT NULL,
              broker_order_id TEXT, last_broker_sequence INTEGER NOT NULL, version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operator_approvals (
              approval_id TEXT PRIMARY KEY, intent_id TEXT UNIQUE NOT NULL,
              actor_id TEXT NOT NULL, approved_at TEXT NOT NULL, approval_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox_commands (
              command_id TEXT PRIMARY KEY, intent_id TEXT UNIQUE NOT NULL,
              client_order_key TEXT UNIQUE NOT NULL, command_json TEXT NOT NULL,
              status TEXT NOT NULL, fencing_token INTEGER, claimed_at TEXT, delivered_at TEXT
            );
            CREATE TABLE IF NOT EXISTS broker_event_inbox (
              broker_event_id TEXT PRIMARY KEY, client_order_key TEXT NOT NULL,
              sequence INTEGER NOT NULL, event_json TEXT NOT NULL,
              received_at TEXT NOT NULL, processing_status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS order_events (
              event_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL, event_type TEXT NOT NULL,
              occurred_at TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fill_events (
              broker_event_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL,
              instrument_id TEXT NOT NULL, side TEXT NOT NULL, quantity INTEGER NOT NULL,
              price TEXT NOT NULL, commission TEXT NOT NULL, event_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS position_projections (
              instrument_id TEXT PRIMARY KEY, quantity INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cash_projection (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), cash_delta TEXT NOT NULL,
              commissions TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS execution_leases (
              lease_name TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
              fencing_token INTEGER NOT NULL, acquired_at TEXT NOT NULL, expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS control_state (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), frozen INTEGER NOT NULL,
              reason TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reconciliation_runs (
              run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT,
              status TEXT NOT NULL, summary_json TEXT
            );
            CREATE TABLE IF NOT EXISTS reconciliation_discrepancies (
              discrepancy_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, severity TEXT NOT NULL,
              kind TEXT NOT NULL, entity_key TEXT NOT NULL, details_json TEXT NOT NULL,
              resolved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS no_trade_ledger (
              outcome_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, reason_code TEXT NOT NULL,
              source TEXT NOT NULL, recorded_at TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reality_gap_ledger (
              gap_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, gap_type TEXT NOT NULL,
              recorded_at TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS naked_exposure_intervals (
              interval_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL,
              detected_at TEXT NOT NULL, unprotected_quantity INTEGER NOT NULL,
              duration_ms INTEGER NOT NULL, resolved_at TEXT, payload_json TEXT NOT NULL
            );
            INSERT OR IGNORE INTO control_state VALUES (1, 1, 'startup_reconciliation_required',
              '1970-01-01T00:00:00+00:00');
            INSERT OR IGNORE INTO cash_projection VALUES (1, '0', '0');
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def stage(
        self,
        capsule: DecisionCapsule,
        reservation: RiskReservation,
        intent: ExecutionIntent,
        *,
        failpoint: str | None = None,
    ) -> None:
        if reservation.decision_id != capsule.decision_id:
            raise ExecutionInvariantError("reservation does not bind to decision")
        if reservation.status != ReservationStatus.ACTIVE:
            raise ExecutionInvariantError("new reservation must be active")
        if reservation.expires_at <= intent.created_at:
            raise ExecutionInvariantError("reservation expired before intent creation")
        if (
            intent.decision_id != capsule.decision_id
            or intent.reservation_id != reservation.reservation_id
            or intent.quantity > reservation.quantity_reserved
            or intent.status not in {ExecutionStatus.APPROVED, ExecutionStatus.APPROVAL_PENDING}
        ):
            raise ExecutionInvariantError("intent does not bind to active reservation")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            active_statuses = (
                ReservationStatus.ACTIVE.value,
                ReservationStatus.PARTIALLY_CONSUMED.value,
                ReservationStatus.RECONCILIATION_HOLD.value,
            )
            existing_reserved = Decimal("0")
            for row in self.connection.execute(
                """SELECT reservation_id, reservation_json FROM risk_reservations
                   WHERE status IN (?, ?, ?)""",
                active_statuses,
            ):
                current = RiskReservation.model_validate_json(row["reservation_json"])
                if (
                    current.account_id == reservation.account_id
                    and current.reservation_id != reservation.reservation_id
                ):
                    existing_reserved += current.notional_reserved
            if (
                existing_reserved + reservation.notional_reserved
                > reservation.account_notional_capacity
            ):
                raise ExecutionInvariantError("durable account reservation capacity exceeded")
            self._insert_immutable(
                "decision_capsules",
                "decision_id",
                capsule.decision_id,
                "capsule_json",
                capsule.model_dump_json(),
                "INSERT OR IGNORE INTO decision_capsules VALUES (?, ?, ?, ?)",
                (
                    capsule.decision_id,
                    capsule.capsule_hash,
                    capsule.model_dump_json(),
                    capsule.created_at.isoformat(),
                ),
            )
            if failpoint == "after_capsule":
                raise RuntimeError("injected crash after capsule")
            self._insert_immutable(
                "risk_reservations",
                "reservation_id",
                reservation.reservation_id,
                "reservation_json",
                reservation.model_dump_json(),
                "INSERT OR IGNORE INTO risk_reservations VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    reservation.reservation_id,
                    reservation.decision_id,
                    reservation.model_dump_json(),
                    reservation.status.value,
                    reservation.quantity_reserved,
                    reservation.quantity_consumed,
                    reservation.version,
                ),
            )
            if failpoint == "after_reservation":
                raise RuntimeError("injected crash after reservation")
            self._insert_immutable(
                "execution_intents",
                "intent_id",
                intent.intent_id,
                "intent_json",
                intent.model_dump_json(),
                """INSERT OR IGNORE INTO execution_intents
                   VALUES (?, ?, ?, ?, ?, ?, 0, NULL, 0, ?)""",
                (
                    intent.intent_id,
                    intent.decision_id,
                    intent.reservation_id,
                    intent.client_order_key,
                    intent.model_dump_json(),
                    intent.status.value,
                    intent.version,
                ),
            )
            if intent.status == ExecutionStatus.APPROVED:
                self._enqueue(intent)
            if failpoint == "after_outbox":
                raise RuntimeError("injected crash after outbox")
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def approve(self, intent_id: str, *, actor_id: str, at: datetime) -> str:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self._intent_row(intent_id)
            if row["status"] not in {
                ExecutionStatus.APPROVAL_PENDING.value,
                ExecutionStatus.APPROVED.value,
                ExecutionStatus.OUTBOXED.value,
            }:
                raise ExecutionInvariantError("intent is not approval-pending")
            reservation = self.connection.execute(
                "SELECT reservation_json FROM risk_reservations WHERE reservation_id=?",
                (row["reservation_id"],),
            ).fetchone()
            if reservation is None:
                raise ExecutionInvariantError("intent reservation is missing")
            reservation_model = RiskReservation.model_validate_json(reservation["reservation_json"])
            if reservation_model.expires_at <= at:
                raise ExecutionInvariantError("reservation expired before approval")
            approval = {
                "intent_id": intent_id,
                "actor_id": actor_id,
                "approved_at": at.isoformat(),
            }
            approval_id = canonical_hash(approval)
            existing = self.connection.execute(
                "SELECT approval_json FROM operator_approvals WHERE intent_id=?", (intent_id,)
            ).fetchone()
            serialized = json.dumps(approval, sort_keys=True, separators=(",", ":"))
            if existing is not None and existing["approval_json"] != serialized:
                raise ExecutionInvariantError("intent already has a different approval")
            self.connection.execute(
                "INSERT OR IGNORE INTO operator_approvals VALUES (?, ?, ?, ?, ?)",
                (approval_id, intent_id, actor_id, at.isoformat(), serialized),
            )
            intent = ExecutionIntent.model_validate_json(row["intent_json"])
            self.connection.execute(
                "UPDATE execution_intents SET status=?, version=version+1 WHERE intent_id=?",
                (ExecutionStatus.APPROVED.value, intent_id),
            )
            self._enqueue(intent)
            self.connection.commit()
            return approval_id
        except BaseException:
            self.connection.rollback()
            raise

    def acquire_lease(
        self,
        lease_name: str,
        *,
        owner_id: str,
        at: datetime,
        ttl: timedelta,
    ) -> ExecutionLease:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                "SELECT * FROM execution_leases WHERE lease_name=?", (lease_name,)
            ).fetchone()
            if (
                row is not None
                and datetime.fromisoformat(row["expires_at"]) > at
                and row["owner_id"] != owner_id
            ):
                raise ExecutionInvariantError("execution lease is held by another writer")
            token = int(row["fencing_token"]) + 1 if row is not None else 1
            lease = ExecutionLease(
                lease_name=lease_name,
                owner_id=owner_id,
                fencing_token=token,
                acquired_at=at,
                expires_at=at + ttl,
            )
            self.connection.execute(
                """INSERT INTO execution_leases VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(lease_name) DO UPDATE SET owner_id=excluded.owner_id,
                   fencing_token=excluded.fencing_token, acquired_at=excluded.acquired_at,
                   expires_at=excluded.expires_at""",
                (lease_name, owner_id, token, at.isoformat(), lease.expires_at.isoformat()),
            )
            self.connection.commit()
            return lease
        except BaseException:
            self.connection.rollback()
            raise

    def claim_next(
        self, lease: ExecutionLease, *, at: datetime
    ) -> tuple[OutboxCommand, ExecutionIntent] | None:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            current = self.connection.execute(
                "SELECT * FROM execution_leases WHERE lease_name=?", (lease.lease_name,)
            ).fetchone()
            frozen = self.connection.execute(
                "SELECT frozen, reason FROM control_state WHERE singleton=1"
            ).fetchone()
            if bool(frozen["frozen"]):
                raise ExecutionInvariantError(f"execution is frozen: {frozen['reason']}")
            if (
                current is None
                or current["owner_id"] != lease.owner_id
                or int(current["fencing_token"]) != lease.fencing_token
                or datetime.fromisoformat(current["expires_at"]) <= at
            ):
                raise ExecutionInvariantError("stale execution fencing token")
            row = self.connection.execute(
                """SELECT o.*, r.reservation_json FROM outbox_commands o
                   JOIN execution_intents i ON i.intent_id=o.intent_id
                   JOIN risk_reservations r ON r.reservation_id=i.reservation_id
                   WHERE o.status='PENDING' ORDER BY o.rowid LIMIT 1"""
            ).fetchone()
            if row is None:
                self.connection.commit()
                return None
            reservation = RiskReservation.model_validate_json(row["reservation_json"])
            if reservation.expires_at <= at:
                self.connection.execute(
                    "UPDATE outbox_commands SET status='DELIVERED', delivered_at=? WHERE command_id=?",
                    (at.isoformat(), row["command_id"]),
                )
                self.connection.execute(
                    "UPDATE execution_intents SET status=?, version=version+1 WHERE intent_id=?",
                    (ExecutionStatus.EXPIRED.value, row["intent_id"]),
                )
                self.connection.execute(
                    "UPDATE risk_reservations SET status=?, version=version+1 WHERE reservation_id=?",
                    (ReservationStatus.EXPIRED.value, reservation.reservation_id),
                )
                self._append_order_event(
                    row["intent_id"], "RESERVATION_EXPIRED", at, {"at": at.isoformat()}
                )
                self.connection.commit()
                return None
            self.connection.execute(
                """UPDATE outbox_commands SET status='CLAIMED', fencing_token=?, claimed_at=?
                   WHERE command_id=? AND status='PENDING'""",
                (lease.fencing_token, at.isoformat(), row["command_id"]),
            )
            self.connection.execute(
                "UPDATE execution_intents SET status=?, version=version+1 WHERE intent_id=?",
                (ExecutionStatus.SUBMITTING.value, row["intent_id"]),
            )
            intent_row = self._intent_row(row["intent_id"])
            self.connection.commit()
            command = OutboxCommand.model_validate_json(row["command_json"]).model_copy(
                update={"status": OutboxStatus.CLAIMED, "fencing_token": lease.fencing_token}
            )
            return command, ExecutionIntent.model_validate_json(intent_row["intent_json"])
        except BaseException:
            self.connection.rollback()
            raise

    def mark_submission_unknown(self, command_id: str, *, at: datetime, reason: str) -> None:
        with self.connection:
            row = self.connection.execute(
                "SELECT intent_id FROM outbox_commands WHERE command_id=?", (command_id,)
            ).fetchone()
            if row is None:
                raise KeyError(command_id)
            self.connection.execute(
                "UPDATE outbox_commands SET status='UNKNOWN', delivered_at=? WHERE command_id=?",
                (at.isoformat(), command_id),
            )
            self.connection.execute(
                "UPDATE execution_intents SET status=?, version=version+1 WHERE intent_id=?",
                (ExecutionStatus.SUBMISSION_UNKNOWN.value, row["intent_id"]),
            )
            self._append_order_event(row["intent_id"], "SUBMISSION_UNKNOWN", at, {"reason": reason})

    def mark_delivered(self, command_id: str, *, at: datetime) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE outbox_commands SET status='DELIVERED', delivered_at=? WHERE command_id=?",
                (at.isoformat(), command_id),
            )

    def recover_claimed_as_unknown(self, *, at: datetime) -> int:
        """After a process crash, never assume a claimed command was not submitted."""
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            rows = self.connection.execute(
                "SELECT command_id, intent_id FROM outbox_commands WHERE status='CLAIMED'"
            ).fetchall()
            for row in rows:
                self.connection.execute(
                    "UPDATE outbox_commands SET status='UNKNOWN', delivered_at=? WHERE command_id=?",
                    (at.isoformat(), row["command_id"]),
                )
                self.connection.execute(
                    "UPDATE execution_intents SET status=?, version=version+1 WHERE intent_id=?",
                    (ExecutionStatus.SUBMISSION_UNKNOWN.value, row["intent_id"]),
                )
                self._append_order_event(
                    row["intent_id"],
                    "SUBMISSION_UNKNOWN",
                    at,
                    {"reason": "writer_recovery_after_claim"},
                )
            self.connection.commit()
            return len(rows)
        except BaseException:
            self.connection.rollback()
            raise

    def resolve_unknown_at_broker(self, client_order_key: str, *, at: datetime) -> None:
        with self.connection:
            row = self.connection.execute(
                "SELECT command_id FROM outbox_commands WHERE client_order_key=? AND status='UNKNOWN'",
                (client_order_key,),
            ).fetchone()
            if row is not None:
                self.connection.execute(
                    "UPDATE outbox_commands SET status='DELIVERED', delivered_at=? WHERE command_id=?",
                    (at.isoformat(), row["command_id"]),
                )

    def requeue_unknown_absent_at_broker(
        self, client_order_key: str, *, snapshot_as_of: datetime, at: datetime
    ) -> bool:
        """Requeue only when an authoritative snapshot post-dates the original claim."""
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                """SELECT o.command_id, o.intent_id, o.claimed_at
                   FROM outbox_commands o WHERE o.client_order_key=? AND o.status='UNKNOWN'""",
                (client_order_key,),
            ).fetchone()
            if row is None:
                self.connection.commit()
                return False
            claimed_at = (
                datetime.fromisoformat(row["claimed_at"])
                if row["claimed_at"] is not None
                else datetime.min.replace(tzinfo=snapshot_as_of.tzinfo)
            )
            if snapshot_as_of < claimed_at:
                raise ExecutionInvariantError("broker snapshot predates uncertain submission")
            self.connection.execute(
                """UPDATE outbox_commands SET status='PENDING', fencing_token=NULL,
                   claimed_at=NULL, delivered_at=NULL WHERE command_id=?""",
                (row["command_id"],),
            )
            self.connection.execute(
                "UPDATE execution_intents SET status=?, version=version+1 WHERE intent_id=?",
                (ExecutionStatus.OUTBOXED.value, row["intent_id"]),
            )
            self._append_order_event(
                row["intent_id"],
                "REQUEUED_AFTER_BROKER_ABSENCE",
                at,
                {"broker_snapshot_as_of": snapshot_as_of.isoformat()},
            )
            self.connection.commit()
            return True
        except BaseException:
            self.connection.rollback()
            raise

    def ingest_broker_event(self, event: BrokerEvent) -> bool:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            inserted = self.connection.execute(
                "INSERT OR IGNORE INTO broker_event_inbox VALUES (?, ?, ?, ?, ?, 'RECEIVED')",
                (
                    event.broker_event_id,
                    event.client_order_key,
                    event.sequence,
                    event.model_dump_json(),
                    event.received_at.isoformat(),
                ),
            )
            if inserted.rowcount == 0:
                self.connection.commit()
                return False
            row = self.connection.execute(
                "SELECT * FROM execution_intents WHERE client_order_key=?",
                (event.client_order_key,),
            ).fetchone()
            if row is None:
                self.connection.execute(
                    "UPDATE broker_event_inbox SET processing_status='ORPHAN' WHERE broker_event_id=?",
                    (event.broker_event_id,),
                )
                self.freeze("broker_only_order_or_event", at=event.received_at, in_transaction=True)
                self.connection.commit()
                return True
            if event.sequence <= int(row["last_broker_sequence"]):
                self.connection.execute(
                    "UPDATE broker_event_inbox SET processing_status='STALE' WHERE broker_event_id=?",
                    (event.broker_event_id,),
                )
                self.connection.commit()
                return False
            filled = int(row["filled_quantity"])
            intent = ExecutionIntent.model_validate_json(row["intent_json"])
            status = (
                ExecutionStatus(row["status"])
                if event.event_type == BrokerEventType.COMMISSION
                else self._status_for(event, filled + event.filled_quantity, intent.quantity)
            )
            new_filled = min(intent.quantity, filled + event.filled_quantity)
            self.connection.execute(
                """UPDATE execution_intents SET status=?, filled_quantity=?, broker_order_id=?,
                   last_broker_sequence=?, version=version+1 WHERE intent_id=?""",
                (status.value, new_filled, event.broker_order_id, event.sequence, intent.intent_id),
            )
            self._update_reservation(
                intent.reservation_id, new_filled, intent.quantity, status, event.received_at
            )
            self._update_economic_projections(intent, event)
            self._append_order_event(
                intent.intent_id,
                event.event_type.value,
                event.occurred_at,
                event.model_dump(mode="json"),
            )
            self.connection.execute(
                "UPDATE broker_event_inbox SET processing_status='APPLIED' WHERE broker_event_id=?",
                (event.broker_event_id,),
            )
            self.connection.commit()
            return True
        except BaseException:
            self.connection.rollback()
            raise

    def intents(self) -> tuple[sqlite3.Row, ...]:
        return tuple(self.connection.execute("SELECT * FROM execution_intents ORDER BY intent_id"))

    def intent(self, intent_id: str) -> sqlite3.Row:
        return self._intent_row(intent_id)

    def pending_approval_count(self) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM execution_intents WHERE status=?",
                (ExecutionStatus.APPROVAL_PENDING.value,),
            ).fetchone()[0]
        )

    def is_frozen(self) -> tuple[bool, str]:
        row = self.connection.execute(
            "SELECT frozen, reason FROM control_state WHERE singleton=1"
        ).fetchone()
        return bool(row["frozen"]), row["reason"]

    def freeze(self, reason: str, *, at: datetime, in_transaction: bool = False) -> None:
        self.connection.execute(
            "UPDATE control_state SET frozen=1, reason=?, updated_at=? WHERE singleton=1",
            (reason, at.isoformat()),
        )
        if not in_transaction:
            self.connection.commit()

    def unfreeze_after_reconciliation(self, *, at: datetime) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE control_state SET frozen=0, reason='', updated_at=? WHERE singleton=1",
                (at.isoformat(),),
            )

    def record_no_trade(
        self,
        decision_id: str,
        *,
        reason_code: str,
        source: str,
        at: datetime,
        payload: dict[str, object] | None = None,
    ) -> str:
        document = {
            "decision_id": decision_id,
            "reason_code": reason_code,
            "source": source,
            "recorded_at": at.isoformat(),
            "payload": payload or {},
        }
        outcome_id = canonical_hash(document)
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO no_trade_ledger VALUES (?, ?, ?, ?, ?, ?)",
                (
                    outcome_id,
                    decision_id,
                    reason_code,
                    source,
                    at.isoformat(),
                    json.dumps(document, sort_keys=True, separators=(",", ":")),
                ),
            )
        return outcome_id

    def record_reality_gap(
        self,
        decision_id: str,
        *,
        gap_type: str,
        at: datetime,
        payload: dict[str, object],
    ) -> str:
        document = {
            "decision_id": decision_id,
            "gap_type": gap_type,
            "recorded_at": at.isoformat(),
            "payload": payload,
        }
        gap_id = canonical_hash(document)
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO reality_gap_ledger VALUES (?, ?, ?, ?, ?)",
                (
                    gap_id,
                    decision_id,
                    gap_type,
                    at.isoformat(),
                    json.dumps(document, sort_keys=True, separators=(",", ":")),
                ),
            )
        return gap_id

    def record_naked_exposure(
        self,
        instrument_id: str,
        *,
        unprotected_quantity: int,
        duration_ms: int,
        at: datetime,
    ) -> str:
        payload = {
            "instrument_id": instrument_id,
            "unprotected_quantity": unprotected_quantity,
            "detected_at": at.isoformat(),
            "duration_ms": duration_ms,
        }
        interval_id = canonical_hash(payload)
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO naked_exposure_intervals VALUES (?, ?, ?, ?, ?, NULL, ?)",
                (
                    interval_id,
                    instrument_id,
                    at.isoformat(),
                    unprotected_quantity,
                    duration_ms,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            )
        return interval_id

    def rebuild_projection(self) -> dict[str, tuple[str, int]]:
        rows = self.connection.execute(
            "SELECT intent_id, status, filled_quantity FROM execution_intents ORDER BY intent_id"
        ).fetchall()
        events = self.connection.execute(
            "SELECT intent_id, event_type, payload_json FROM order_events ORDER BY rowid"
        ).fetchall()
        rebuilt: dict[str, tuple[str, int]] = {
            row["intent_id"]: (ExecutionStatus.SUBMITTING.value, 0) for row in rows
        }
        for event in events:
            if event["event_type"] == "SUBMISSION_UNKNOWN":
                rebuilt[event["intent_id"]] = (ExecutionStatus.SUBMISSION_UNKNOWN.value, 0)
                continue
            payload = json.loads(event["payload_json"])
            broker_event = BrokerEvent.model_validate(payload)
            old_filled = rebuilt.get(event["intent_id"], ("", 0))[1]
            intent_row = self._intent_row(event["intent_id"])
            quantity = ExecutionIntent.model_validate_json(intent_row["intent_json"]).quantity
            filled = min(quantity, old_filled + broker_event.filled_quantity)
            rebuilt[event["intent_id"]] = (
                self._status_for(broker_event, filled, quantity).value,
                filled,
            )
        return rebuilt

    def rebuild_economic_projection(self) -> dict[str, object]:
        positions: dict[str, int] = {}
        cash_delta = Decimal("0")
        commissions = Decimal("0")
        for row in self.connection.execute("SELECT payload_json FROM order_events ORDER BY rowid"):
            payload = json.loads(row["payload_json"])
            if "broker_event_id" not in payload:
                continue
            event = BrokerEvent.model_validate(payload)
            intent_row = self.connection.execute(
                "SELECT intent_json FROM execution_intents WHERE client_order_key=?",
                (event.client_order_key,),
            ).fetchone()
            if intent_row is None:
                continue
            intent = ExecutionIntent.model_validate_json(intent_row["intent_json"])
            commissions += event.commission
            cash_delta -= event.commission
            if event.event_type not in {BrokerEventType.PARTIAL_FILL, BrokerEventType.FILL}:
                continue
            assert event.fill_price is not None
            signed = event.filled_quantity if intent.side.value == "BUY" else -event.filled_quantity
            positions[intent.instrument_id] = positions.get(intent.instrument_id, 0) + signed
            notional = event.fill_price * event.filled_quantity
            cash_delta += -notional if intent.side.value == "BUY" else notional
        return {
            "positions": positions,
            "cash_delta": cash_delta,
            "commissions": commissions,
        }

    def _enqueue(self, intent: ExecutionIntent) -> None:
        command = OutboxCommand(
            command_id=canonical_hash({"intent_id": intent.intent_id, "command": "SUBMIT"}),
            intent_id=intent.intent_id,
            client_order_key=intent.client_order_key,
            payload_hash=canonical_hash(intent),
            status=OutboxStatus.PENDING,
            created_at=intent.created_at,
        )
        self._insert_immutable(
            "outbox_commands",
            "command_id",
            command.command_id,
            "command_json",
            command.model_dump_json(),
            "INSERT OR IGNORE INTO outbox_commands VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL)",
            (
                command.command_id,
                command.intent_id,
                command.client_order_key,
                command.model_dump_json(),
                command.status.value,
            ),
        )
        self.connection.execute(
            """UPDATE execution_intents SET status=?, version=version+1
               WHERE intent_id=? AND status IN (?, ?)""",
            (
                ExecutionStatus.OUTBOXED.value,
                intent.intent_id,
                ExecutionStatus.APPROVED.value,
                ExecutionStatus.APPROVAL_PENDING.value,
            ),
        )

    def _intent_row(self, intent_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM execution_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        if row is None:
            raise KeyError(intent_id)
        assert isinstance(row, sqlite3.Row)
        return row

    def _insert_immutable(
        self,
        table: str,
        key_column: str,
        key: str,
        json_column: str,
        serialized: str,
        insert_sql: str,
        values: tuple[object, ...],
    ) -> None:
        row = self.connection.execute(
            f"SELECT {json_column} FROM {table} WHERE {key_column}=?", (key,)
        ).fetchone()
        if row is not None and row[json_column] != serialized:
            raise ExecutionInvariantError(f"immutable {table} conflict")
        self.connection.execute(insert_sql, values)

    def _append_order_event(
        self, intent_id: str, event_type: str, at: datetime, payload: dict[str, object]
    ) -> None:
        event_id = canonical_hash({"intent_id": intent_id, "type": event_type, "payload": payload})
        self.connection.execute(
            "INSERT OR IGNORE INTO order_events VALUES (?, ?, ?, ?, ?)",
            (
                event_id,
                intent_id,
                event_type,
                at.isoformat(),
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
            ),
        )

    def _update_reservation(
        self, reservation_id: str, filled: int, quantity: int, status: ExecutionStatus, at: datetime
    ) -> None:
        if status in {ExecutionStatus.REJECTED, ExecutionStatus.CANCELLED, ExecutionStatus.EXPIRED}:
            reservation_status = ReservationStatus.RELEASED
        elif filled == quantity:
            reservation_status = ReservationStatus.CONSUMED
        elif filled > 0:
            reservation_status = ReservationStatus.PARTIALLY_CONSUMED
        else:
            reservation_status = ReservationStatus.ACTIVE
        self.connection.execute(
            """UPDATE risk_reservations SET status=?, quantity_consumed=?, version=version+1
               WHERE reservation_id=?""",
            (reservation_status.value, filled, reservation_id),
        )

    def _update_economic_projections(self, intent: ExecutionIntent, event: BrokerEvent) -> None:
        cash_delta = -event.commission
        if event.event_type in {BrokerEventType.PARTIAL_FILL, BrokerEventType.FILL}:
            if event.fill_price is None:
                raise ExecutionInvariantError("fill event is missing a price")
            signed = event.filled_quantity if intent.side.value == "BUY" else -event.filled_quantity
            self.connection.execute(
                """INSERT INTO position_projections VALUES (?, ?)
                   ON CONFLICT(instrument_id) DO UPDATE SET quantity=quantity+excluded.quantity""",
                (intent.instrument_id, signed),
            )
            notional = event.fill_price * event.filled_quantity
            cash_delta += -notional if intent.side.value == "BUY" else notional
            self.connection.execute(
                "INSERT INTO fill_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.broker_event_id,
                    intent.intent_id,
                    intent.instrument_id,
                    intent.side.value,
                    event.filled_quantity,
                    str(event.fill_price),
                    str(event.commission),
                    event.model_dump_json(),
                ),
            )
        row = self.connection.execute(
            "SELECT cash_delta, commissions FROM cash_projection WHERE singleton=1"
        ).fetchone()
        self.connection.execute(
            "UPDATE cash_projection SET cash_delta=?, commissions=? WHERE singleton=1",
            (
                str(Decimal(row["cash_delta"]) + cash_delta),
                str(Decimal(row["commissions"]) + event.commission),
            ),
        )

    @staticmethod
    def _status_for(event: BrokerEvent, filled: int, quantity: int) -> ExecutionStatus:
        if event.event_type == BrokerEventType.REJECTED:
            return ExecutionStatus.REJECTED
        if event.event_type == BrokerEventType.CANCELLED:
            return ExecutionStatus.CANCELLED
        if event.event_type in {BrokerEventType.PARTIAL_FILL, BrokerEventType.FILL}:
            return (
                ExecutionStatus.FILLED if filled >= quantity else ExecutionStatus.PARTIALLY_FILLED
            )
        return ExecutionStatus.ACKNOWLEDGED
