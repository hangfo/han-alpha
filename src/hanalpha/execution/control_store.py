from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from hanalpha.execution.admission import evaluate_quote_admission
from hanalpha.execution.control_models import (
    BrokerEvent,
    BrokerEventType,
    BrokerSnapshot,
    DecisionCapsule,
    ExecutionIntent,
    ExecutionLease,
    ExecutionStatus,
    OutboxCommand,
    OutboxStatus,
    QuoteSnapshot,
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
            CREATE TABLE IF NOT EXISTS approval_arms (
              arm_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL,
              version INTEGER NOT NULL, status TEXT NOT NULL,
              authority_id TEXT NOT NULL, quote_snapshot_id TEXT NOT NULL,
              broker_snapshot_hash TEXT NOT NULL, quote_hash TEXT NOT NULL,
              approved_limit_price TEXT NOT NULL, max_drift_bps TEXT NOT NULL,
              armed_at TEXT NOT NULL, expires_at TEXT NOT NULL,
              armed_by TEXT NOT NULL, arm_source TEXT NOT NULL,
              operator_session_id TEXT, consumed_at TEXT, arm_json TEXT NOT NULL,
              UNIQUE(intent_id, version)
            );
            CREATE TABLE IF NOT EXISTS outbox_commands (
              command_id TEXT PRIMARY KEY, intent_id TEXT UNIQUE NOT NULL,
              client_order_key TEXT UNIQUE NOT NULL, command_json TEXT NOT NULL,
              status TEXT NOT NULL, fencing_token INTEGER, claimed_at TEXT, delivered_at TEXT
            );
            CREATE TABLE IF NOT EXISTS cancel_commands (
              command_id TEXT PRIMARY KEY, intent_id TEXT UNIQUE NOT NULL,
              client_order_key TEXT UNIQUE NOT NULL, status TEXT NOT NULL,
              fencing_token INTEGER, requested_by TEXT NOT NULL,
              requested_at TEXT NOT NULL, claimed_at TEXT, delivered_at TEXT,
              last_error TEXT
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
            CREATE TABLE IF NOT EXISTS freeze_tickets (
              ticket_id TEXT PRIMARY KEY, reason_code TEXT NOT NULL, severity TEXT NOT NULL,
              source TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT,
              resolution_evidence TEXT
            );
            CREATE TABLE IF NOT EXISTS broker_account_baseline (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), cash TEXT NOT NULL,
              buying_power TEXT, settled_cash TEXT, accrued_cash TEXT,
              currency_balances_json TEXT NOT NULL, snapshot_as_of TEXT NOT NULL,
              projection_cash_delta TEXT NOT NULL DEFAULT '0',
              projection_commissions TEXT NOT NULL DEFAULT '0', bridge_id TEXT
            );
            CREATE TABLE IF NOT EXISTS broker_snapshot_authority (
              certificate_id TEXT PRIMARY KEY, semantic_hash TEXT NOT NULL,
              visibility_scope_hash TEXT NOT NULL, snapshot_as_of TEXT NOT NULL,
              snapshot_json TEXT NOT NULL, reconciliation_run_id TEXT,
              reconciliation_status TEXT, recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS broker_snapshot_consensus (
              visibility_scope_hash TEXT PRIMARY KEY, semantic_hash TEXT NOT NULL,
              consecutive_count INTEGER NOT NULL, first_seen_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL, last_certificate_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS broker_snapshot_votes (
              observation_id TEXT PRIMARY KEY, certificate_id TEXT NOT NULL,
              session_id TEXT NOT NULL, visibility_scope_hash TEXT NOT NULL,
              semantic_hash TEXT NOT NULL, snapshot_as_of TEXT NOT NULL,
              final_watermark INTEGER NOT NULL, recorded_at TEXT NOT NULL,
              disposition TEXT NOT NULL, snapshot_json TEXT,
              equivalence_json TEXT
            );
            CREATE TABLE IF NOT EXISTS broker_authority_candidates (
              certificate_id TEXT PRIMARY KEY, snapshot_json TEXT NOT NULL,
              reconciliation_run_id TEXT NOT NULL, reconciliation_status TEXT NOT NULL,
              promotion_status TEXT NOT NULL, policy_reason TEXT NOT NULL,
              recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS quote_snapshots (
              quote_snapshot_id TEXT PRIMARY KEY, symbol TEXT NOT NULL,
              quote_json TEXT NOT NULL, observed_at TEXT NOT NULL,
              provider_timestamp TEXT NOT NULL, recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cash_bridge_events (
              bridge_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, amount TEXT NOT NULL,
              currency TEXT NOT NULL, occurred_at TEXT NOT NULL, evidence_json TEXT NOT NULL,
              baseline_epoch_started INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reconciliation_runs (
              run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT,
              status TEXT NOT NULL, summary_json TEXT
            );
            CREATE TABLE IF NOT EXISTS reconciliation_discrepancies (
              discrepancy_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, severity TEXT NOT NULL,
              kind TEXT NOT NULL, entity_key TEXT NOT NULL, details_json TEXT NOT NULL,
              resolved_at TEXT, first_seen_at TEXT, last_seen_at TEXT,
              lifecycle_status TEXT NOT NULL DEFAULT 'OPEN', resolution_evidence TEXT
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
            CREATE TABLE IF NOT EXISTS ops_heartbeats (
              component TEXT PRIMARY KEY, status TEXT NOT NULL,
              observed_at TEXT NOT NULL, details_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_canary_safety_cases (
              safety_case_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
              case_json TEXT NOT NULL, status TEXT NOT NULL
            );
            INSERT OR IGNORE INTO control_state VALUES (1, 1, 'startup_reconciliation_required',
              '1970-01-01T00:00:00+00:00');
            INSERT OR IGNORE INTO freeze_tickets VALUES (
              'startup-reconciliation', 'STARTUP_RECONCILIATION', 'BLOCKING', 'system',
              '1970-01-01T00:00:00+00:00', NULL, NULL
            );
            INSERT OR IGNORE INTO cash_projection VALUES (1, '0', '0');
            """
        )
        freeze_schema = self.connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='freeze_tickets'"
        ).fetchone()["sql"]
        if "UNIQUE(reason_code, source, resolved_at)" in freeze_schema:
            self.connection.executescript(
                """
                ALTER TABLE freeze_tickets RENAME TO freeze_tickets_legacy;
                CREATE TABLE freeze_tickets (
                  ticket_id TEXT PRIMARY KEY, reason_code TEXT NOT NULL, severity TEXT NOT NULL,
                  source TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT,
                  resolution_evidence TEXT
                );
                INSERT INTO freeze_tickets SELECT * FROM freeze_tickets_legacy;
                DROP TABLE freeze_tickets_legacy;
                """
            )
        arm_columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(approval_arms)")
        }
        if "version" not in arm_columns:
            self.connection.executescript(
                """
                DROP INDEX IF EXISTS idx_approval_arms_active_intent;
                ALTER TABLE approval_arms RENAME TO approval_arms_legacy;
                CREATE TABLE approval_arms (
                  arm_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL,
                  version INTEGER NOT NULL, status TEXT NOT NULL,
                  authority_id TEXT NOT NULL, quote_snapshot_id TEXT NOT NULL,
                  broker_snapshot_hash TEXT NOT NULL, quote_hash TEXT NOT NULL,
                  approved_limit_price TEXT NOT NULL, max_drift_bps TEXT NOT NULL,
                  armed_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                  armed_by TEXT NOT NULL, arm_source TEXT NOT NULL,
                  operator_session_id TEXT, consumed_at TEXT, arm_json TEXT NOT NULL,
                  UNIQUE(intent_id, version)
                );
                INSERT INTO approval_arms
                  (arm_id, intent_id, version, status, authority_id, quote_snapshot_id,
                   broker_snapshot_hash, quote_hash, approved_limit_price, max_drift_bps,
                   armed_at, expires_at, armed_by, arm_source, operator_session_id,
                   consumed_at, arm_json)
                SELECT arm_id, intent_id, 1, 'ACTIVE', '', '', broker_snapshot_hash,
                       quote_hash, approved_limit_price, max_drift_bps, armed_at,
                       expires_at, 'LEGACY_UNKNOWN', 'LEGACY_MIGRATION', NULL, NULL,
                       arm_json
                FROM approval_arms_legacy;
                DROP TABLE approval_arms_legacy;
                CREATE UNIQUE INDEX idx_approval_arms_active_intent
                  ON approval_arms(intent_id) WHERE status='ACTIVE';
                """
            )
        self.connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_approval_arms_active_intent
               ON approval_arms(intent_id) WHERE status='ACTIVE'"""
        )
        vote_columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(broker_snapshot_votes)")
        }
        for name in ("snapshot_json", "equivalence_json"):
            if name not in vote_columns:
                self.connection.execute(f"ALTER TABLE broker_snapshot_votes ADD COLUMN {name} TEXT")
        baseline_columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(broker_account_baseline)")
        }
        for name, declaration in (
            ("projection_cash_delta", "TEXT NOT NULL DEFAULT '0'"),
            ("projection_commissions", "TEXT NOT NULL DEFAULT '0'"),
            ("bridge_id", "TEXT"),
        ):
            if name not in baseline_columns:
                self.connection.execute(
                    f"ALTER TABLE broker_account_baseline ADD COLUMN {name} {declaration}"
                )
        discrepancy_columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(reconciliation_discrepancies)")
        }
        for name, declaration in (
            ("first_seen_at", "TEXT"),
            ("last_seen_at", "TEXT"),
            ("lifecycle_status", "TEXT NOT NULL DEFAULT 'OPEN'"),
            ("resolution_evidence", "TEXT"),
        ):
            if name not in discrepancy_columns:
                self.connection.execute(
                    f"ALTER TABLE reconciliation_discrepancies ADD COLUMN {name} {declaration}"
                )
        self.connection.commit()
        if not self.connection.execute(
            """SELECT 1 FROM freeze_tickets WHERE reason_code='STARTUP_RECONCILIATION'
               AND source='system' AND resolved_at IS NULL"""
        ).fetchone():
            self.open_freeze_ticket("STARTUP_RECONCILIATION", source="system", at=datetime.now(UTC))

    def close(self) -> None:
        self.connection.close()

    def record_heartbeat(
        self,
        component: str,
        *,
        status: str,
        at: datetime,
        details: dict[str, object] | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO ops_heartbeats VALUES (?, ?, ?, ?)
                   ON CONFLICT(component) DO UPDATE SET status=excluded.status,
                   observed_at=excluded.observed_at, details_json=excluded.details_json""",
                (
                    component,
                    status,
                    at.isoformat(),
                    json.dumps(details or {}, sort_keys=True, separators=(",", ":")),
                ),
            )

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
            tickets = self.connection.execute(
                "SELECT reason_code FROM freeze_tickets WHERE resolved_at IS NULL AND severity='BLOCKING'"
            ).fetchall()
            if tickets:
                raise ExecutionInvariantError(
                    "new risk is frozen: " + ",".join(row["reason_code"] for row in tickets)
                )
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
            blocking = self.active_freeze_reasons()
            if blocking:
                raise ExecutionInvariantError("approval is frozen: " + ",".join(blocking))
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
                "approval_expires_at": reservation_model.expires_at.isoformat(),
                "intent_spec_hash": canonical_hash(
                    ExecutionIntent.model_validate_json(row["intent_json"])
                ),
                "reservation_hash": canonical_hash(reservation_model),
                "projection_version": int(row["version"]),
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
            self.connection.execute(
                "UPDATE execution_intents SET status=?, version=version+1 WHERE intent_id=?",
                (ExecutionStatus.APPROVED.value, intent_id),
            )
            self.connection.commit()
            return approval_id
        except BaseException:
            self.connection.rollback()
            raise

    def arm_approved_intent(
        self,
        intent_id: str,
        *,
        authority_id: str,
        quote_snapshot_id: str,
        max_drift_bps: Decimal,
        armed_by: str,
        at: datetime,
        expires_at: datetime,
        arm_source: str = "OPERATOR",
        operator_session_id: str | None = None,
        authority_max_age: timedelta = timedelta(seconds=30),
        quote_max_age: timedelta = timedelta(seconds=5),
        provider_clock_skew: timedelta = timedelta(seconds=1),
        max_spread_bps: Decimal = Decimal("50"),
    ) -> str:
        """Bind approval to fresh broker/quote truth before creating the submit outbox."""
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            blocking = self.active_freeze_reasons()
            if blocking:
                raise ExecutionInvariantError("arming is frozen: " + ",".join(blocking))
            row = self._intent_row(intent_id)
            if row["status"] not in {
                ExecutionStatus.APPROVED.value,
                ExecutionStatus.OUTBOXED.value,
            }:
                raise ExecutionInvariantError("intent is not approved")
            if expires_at <= at:
                raise ExecutionInvariantError("approval arm is already expired")
            if max_drift_bps > Decimal("10"):
                raise ExecutionInvariantError("approval arm drift exceeds system policy")
            authority = self.connection.execute(
                "SELECT * FROM broker_snapshot_authority WHERE certificate_id=? AND reconciliation_status='CONVERGED'",
                (authority_id,),
            ).fetchone()
            if authority is None:
                raise ExecutionInvariantError("broker snapshot authority is stale or unknown")
            authority_age = at - datetime.fromisoformat(authority["snapshot_as_of"])
            if authority_age < timedelta(0) or authority_age > authority_max_age:
                self.open_freeze_ticket(
                    "BROKER_AUTHORITY_STALE",
                    source="approval_arm",
                    at=at,
                    in_transaction=True,
                )
                self.connection.commit()
                raise ExecutionInvariantError("broker snapshot authority exceeded maximum age")
            snapshot = BrokerSnapshot.model_validate_json(authority["snapshot_json"])
            if not (
                snapshot.complete
                and snapshot.order_snapshot_complete
                and snapshot.position_snapshot_complete
                and snapshot.execution_snapshot_complete
                and snapshot.cash_snapshot_complete
                and snapshot.commission_pending_count == 0
            ):
                raise ExecutionInvariantError("broker authority components are incomplete")
            quote_row = self.connection.execute(
                "SELECT quote_json FROM quote_snapshots WHERE quote_snapshot_id=?",
                (quote_snapshot_id,),
            ).fetchone()
            if quote_row is None:
                raise ExecutionInvariantError("quote snapshot is unknown")
            quote = QuoteSnapshot.model_validate_json(quote_row["quote_json"])
            intent = ExecutionIntent.model_validate_json(row["intent_json"])
            quote_admission = evaluate_quote_admission(
                quote,
                at=at,
                quote_max_age=quote_max_age,
                provider_clock_skew=provider_clock_skew,
                max_spread_bps=max_spread_bps,
                expected_symbol=intent.instrument_id,
                expected_currency=snapshot.base_currency,
                reference_limit_price=intent.limit_price,
                side=intent.side.value,
                max_drift_bps=max_drift_bps,
            )
            if "OBSERVED_QUOTE_STALE" in quote_admission.reasons:
                self.open_freeze_ticket(
                    "MARKET_QUOTE_STALE",
                    source="approval_arm",
                    at=at,
                    in_transaction=True,
                )
                self.connection.commit()
                raise ExecutionInvariantError("quote snapshot exceeded maximum age")
            if not quote_admission.eligible:
                raise ExecutionInvariantError(
                    "quote admission rejected: " + ",".join(quote_admission.reasons)
                )
            current_limit_price = quote.ask if intent.side.value == "BUY" else quote.bid
            approval = self.connection.execute(
                "SELECT approval_json FROM operator_approvals WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
            if approval is None:
                raise ExecutionInvariantError("approval evidence is missing")
            approval_document = json.loads(approval["approval_json"])
            reservation = self.connection.execute(
                "SELECT reservation_json FROM risk_reservations WHERE reservation_id=?",
                (row["reservation_id"],),
            ).fetchone()
            if reservation is None:
                raise ExecutionInvariantError("intent reservation is missing")
            reservation_model = RiskReservation.model_validate_json(reservation["reservation_json"])
            effective_expires_at = min(
                expires_at,
                quote_admission.valid_until,
                datetime.fromisoformat(authority["snapshot_as_of"]) + authority_max_age,
                reservation_model.expires_at,
                datetime.fromisoformat(approval_document["approval_expires_at"]),
            )
            if effective_expires_at <= at:
                raise ExecutionInvariantError("upstream evidence expires before Arm can be issued")
            active = self.connection.execute(
                """SELECT * FROM approval_arms
                   WHERE intent_id=? AND status='ACTIVE'
                   ORDER BY version DESC LIMIT 1""",
                (intent_id,),
            ).fetchone()
            binding = {
                "intent_id": intent_id,
                "authority_id": authority_id,
                "broker_snapshot_hash": authority["semantic_hash"],
                "quote_snapshot_id": quote_snapshot_id,
                "quote_hash": quote.raw_hash,
                "approved_limit_price": str(current_limit_price),
                "max_drift_bps": str(max_drift_bps),
                "armed_at": at.isoformat(),
                "requested_expires_at": expires_at.isoformat(),
                "expires_at": effective_expires_at.isoformat(),
                "intent_spec_hash": canonical_hash(intent),
                "armed_by": armed_by,
                "arm_source": arm_source,
                "operator_session_id": operator_session_id,
                "provider_age_seconds": quote_admission.provider_age_seconds,
                "observed_age_seconds": quote_admission.observed_age_seconds,
                "spread_bps": str(quote_admission.spread_bps),
                "quote_max_age_seconds": quote_max_age.total_seconds(),
                "authority_max_age_seconds": authority_max_age.total_seconds(),
                "provider_clock_skew_seconds": provider_clock_skew.total_seconds(),
                "max_spread_bps": str(max_spread_bps),
            }
            if active is not None:
                existing_document = json.loads(active["arm_json"])
                if all(existing_document.get(key) == value for key, value in binding.items()):
                    self.connection.commit()
                    return str(active["arm_id"])
                replacement_status = (
                    "EXPIRED"
                    if datetime.fromisoformat(active["expires_at"]) <= at
                    else "SUPERSEDED"
                )
                self.connection.execute(
                    "UPDATE approval_arms SET status=? WHERE arm_id=?",
                    (replacement_status, active["arm_id"]),
                )
            previous_version = self.connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM approval_arms WHERE intent_id=?",
                (intent_id,),
            ).fetchone()[0]
            version = int(previous_version) + 1
            document = {**binding, "version": version, "status": "ACTIVE"}
            arm_id = canonical_hash(document)
            serialized = json.dumps(document, sort_keys=True, separators=(",", ":"))
            self.connection.execute(
                """INSERT INTO approval_arms
                   (arm_id, intent_id, version, status, authority_id, quote_snapshot_id,
                    broker_snapshot_hash, quote_hash, approved_limit_price, max_drift_bps,
                    armed_at, expires_at, armed_by, arm_source, operator_session_id,
                    consumed_at, arm_json)
                   VALUES (?, ?, ?, 'ACTIVE', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                (
                    arm_id,
                    intent_id,
                    version,
                    authority_id,
                    quote_snapshot_id,
                    authority["semantic_hash"],
                    quote.raw_hash,
                    str(current_limit_price),
                    str(max_drift_bps),
                    at.isoformat(),
                    effective_expires_at.isoformat(),
                    armed_by,
                    arm_source,
                    operator_session_id,
                    serialized,
                ),
            )
            self._enqueue(intent)
            self.connection.commit()
            return arm_id
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

    def validate_lease(self, lease: ExecutionLease, *, at: datetime) -> None:
        current = self.connection.execute(
            "SELECT * FROM execution_leases WHERE lease_name=?", (lease.lease_name,)
        ).fetchone()
        if (
            current is None
            or current["owner_id"] != lease.owner_id
            or int(current["fencing_token"]) != lease.fencing_token
            or datetime.fromisoformat(current["expires_at"]) <= at
        ):
            raise ExecutionInvariantError("stale execution fencing token")

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
            approval = self.connection.execute(
                "SELECT 1 FROM operator_approvals WHERE intent_id=?", (row["intent_id"],)
            ).fetchone()
            if approval is not None:
                arm = self.connection.execute(
                    """SELECT * FROM approval_arms
                       WHERE intent_id=? AND status='ACTIVE'
                       ORDER BY version DESC LIMIT 1""",
                    (row["intent_id"],),
                ).fetchone()
                if arm is None:
                    raise ExecutionInvariantError("approval arm missing or expired")
                if datetime.fromisoformat(arm["expires_at"]) <= at:
                    self.connection.execute(
                        "UPDATE approval_arms SET status='EXPIRED' WHERE arm_id=?",
                        (arm["arm_id"],),
                    )
                    self.connection.commit()
                    raise ExecutionInvariantError("approval arm missing or expired")
                arm_document = json.loads(arm["arm_json"])
                authority = self.connection.execute(
                    """SELECT * FROM broker_snapshot_authority
                       WHERE certificate_id=? AND reconciliation_status='CONVERGED'""",
                    (arm["authority_id"],),
                ).fetchone()
                latest_authority = self.latest_broker_snapshot_authority()
                quote_row = self.connection.execute(
                    "SELECT quote_json FROM quote_snapshots WHERE quote_snapshot_id=?",
                    (arm["quote_snapshot_id"],),
                ).fetchone()
                intent_for_gate = ExecutionIntent.model_validate_json(
                    self._intent_row(row["intent_id"])["intent_json"]
                )
                if (
                    authority is None
                    or latest_authority is None
                    or latest_authority["certificate_id"] != arm["authority_id"]
                    or quote_row is None
                ):
                    self.connection.execute(
                        "UPDATE approval_arms SET status='EXPIRED' WHERE arm_id=?",
                        (arm["arm_id"],),
                    )
                    self.connection.commit()
                    raise ExecutionInvariantError("approval arm upstream authority changed")
                authority_snapshot = BrokerSnapshot.model_validate_json(authority["snapshot_json"])
                claim_quote = QuoteSnapshot.model_validate_json(quote_row["quote_json"])
                claim_admission = evaluate_quote_admission(
                    claim_quote,
                    at=at,
                    quote_max_age=timedelta(
                        seconds=float(arm_document["quote_max_age_seconds"])
                    ),
                    provider_clock_skew=timedelta(
                        seconds=float(arm_document["provider_clock_skew_seconds"])
                    ),
                    max_spread_bps=Decimal(arm_document["max_spread_bps"]),
                    expected_symbol=intent_for_gate.instrument_id,
                    expected_currency=authority_snapshot.base_currency,
                    reference_limit_price=intent_for_gate.limit_price,
                    side=intent_for_gate.side.value,
                    max_drift_bps=Decimal(arm["max_drift_bps"]),
                )
                if not claim_admission.eligible:
                    self.connection.execute(
                        "UPDATE approval_arms SET status='EXPIRED' WHERE arm_id=?",
                        (arm["arm_id"],),
                    )
                    self.connection.commit()
                    raise ExecutionInvariantError(
                        "approval arm evidence expired: "
                        + ",".join(claim_admission.reasons)
                    )
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
            if approval is not None:
                self.connection.execute(
                    """UPDATE approval_arms SET status='CONSUMED', consumed_at=?
                       WHERE arm_id=? AND status='ACTIVE'""",
                    (at.isoformat(), arm["arm_id"]),
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

    def request_cancel(self, intent_id: str, *, actor_id: str, at: datetime) -> str:
        """Persist a risk-reducing cancel command; repeated requests are idempotent."""
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self._intent_row(intent_id)
            existing = self.connection.execute(
                "SELECT command_id FROM cancel_commands WHERE intent_id=?", (intent_id,)
            ).fetchone()
            if existing is not None:
                self.connection.commit()
                return str(existing["command_id"])
            terminal = {
                ExecutionStatus.FILLED.value,
                ExecutionStatus.CANCELLED.value,
                ExecutionStatus.REJECTED.value,
                ExecutionStatus.EXPIRED.value,
            }
            if row["status"] in terminal:
                raise ExecutionInvariantError("terminal intent cannot be cancelled")
            command_id = canonical_hash(
                {"command_type": "CANCEL", "client_order_key": row["client_order_key"]}
            )
            local_only = row["status"] in {
                ExecutionStatus.APPROVAL_PENDING.value,
                ExecutionStatus.APPROVED.value,
                ExecutionStatus.OUTBOXED.value,
            }
            self.connection.execute(
                """INSERT INTO cancel_commands
                   VALUES (?, ?, ?, ?, NULL, ?, ?, NULL, ?, NULL)""",
                (
                    command_id,
                    intent_id,
                    row["client_order_key"],
                    "DELIVERED" if local_only else "PENDING",
                    actor_id,
                    at.isoformat(),
                    at.isoformat() if local_only else None,
                ),
            )
            if local_only:
                self.connection.execute(
                    """UPDATE outbox_commands SET status='DELIVERED', delivered_at=?
                       WHERE intent_id=? AND status='PENDING'""",
                    (at.isoformat(), intent_id),
                )
            self.connection.execute(
                "UPDATE execution_intents SET status=?, version=version+1 WHERE intent_id=?",
                (
                    ExecutionStatus.CANCELLED.value
                    if local_only
                    else ExecutionStatus.CANCEL_REQUESTED.value,
                    intent_id,
                ),
            )
            if local_only:
                self._update_reservation(
                    row["reservation_id"],
                    int(row["filled_quantity"]),
                    ExecutionIntent.model_validate_json(row["intent_json"]).quantity,
                    ExecutionStatus.CANCELLED,
                    at,
                )
            self._append_order_event(
                intent_id,
                "CANCELLED_BEFORE_BROKER" if local_only else "CANCEL_REQUESTED",
                at,
                {"actor_id": actor_id, "command_id": command_id},
            )
            self.connection.commit()
            return command_id
        except BaseException:
            self.connection.rollback()
            raise

    def claim_next_cancel(
        self, lease: ExecutionLease, *, at: datetime
    ) -> tuple[str, ExecutionIntent] | None:
        """Claim cancel under the single-writer fence even while new risk is frozen."""
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            current = self.connection.execute(
                "SELECT * FROM execution_leases WHERE lease_name=?", (lease.lease_name,)
            ).fetchone()
            if (
                current is None
                or current["owner_id"] != lease.owner_id
                or int(current["fencing_token"]) != lease.fencing_token
                or datetime.fromisoformat(current["expires_at"]) <= at
            ):
                raise ExecutionInvariantError("stale execution fencing token")
            row = self.connection.execute(
                """SELECT c.*, i.intent_json FROM cancel_commands c
                   JOIN execution_intents i ON i.intent_id=c.intent_id
                   WHERE c.status='PENDING' ORDER BY c.rowid LIMIT 1"""
            ).fetchone()
            if row is None:
                self.connection.commit()
                return None
            updated = self.connection.execute(
                """UPDATE cancel_commands SET status='CLAIMED', fencing_token=?, claimed_at=?
                   WHERE command_id=? AND status='PENDING'""",
                (lease.fencing_token, at.isoformat(), row["command_id"]),
            )
            if updated.rowcount != 1:
                self.connection.rollback()
                return None
            self.connection.commit()
            return row["command_id"], ExecutionIntent.model_validate_json(row["intent_json"])
        except BaseException:
            self.connection.rollback()
            raise

    def mark_cancel_unknown(self, command_id: str, *, at: datetime, reason: str) -> None:
        with self.connection:
            row = self.connection.execute(
                "SELECT intent_id FROM cancel_commands WHERE command_id=?", (command_id,)
            ).fetchone()
            if row is None:
                raise KeyError(command_id)
            self.connection.execute(
                """UPDATE cancel_commands SET status='UNKNOWN', delivered_at=?, last_error=?
                   WHERE command_id=?""",
                (at.isoformat(), reason, command_id),
            )
            self.connection.execute(
                "UPDATE execution_intents SET status=?, version=version+1 WHERE intent_id=?",
                (ExecutionStatus.CANCEL_UNKNOWN.value, row["intent_id"]),
            )
            self._append_order_event(row["intent_id"], "CANCEL_UNKNOWN", at, {"reason": reason})

    def mark_cancel_delivered(self, command_id: str, *, at: datetime) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE cancel_commands SET status='DELIVERED', delivered_at=? WHERE command_id=?",
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

    def resolve_unknown_at_broker(
        self,
        client_order_key: str,
        *,
        broker_order_id: str,
        at: datetime,
    ) -> None:
        with self.connection:
            row = self.connection.execute(
                """SELECT o.command_id, o.intent_id FROM outbox_commands o
                   WHERE o.client_order_key=? AND o.status='UNKNOWN'""",
                (client_order_key,),
            ).fetchone()
            if row is not None:
                self.connection.execute(
                    "UPDATE outbox_commands SET status='DELIVERED', delivered_at=? WHERE command_id=?",
                    (at.isoformat(), row["command_id"]),
                )
                self.connection.execute(
                    """UPDATE execution_intents SET status=?, broker_order_id=?, version=version+1
                       WHERE intent_id=? AND status=?""",
                    (
                        ExecutionStatus.ACKNOWLEDGED.value,
                        broker_order_id,
                        row["intent_id"],
                        ExecutionStatus.SUBMISSION_UNKNOWN.value,
                    ),
                )
                self._append_order_event(
                    row["intent_id"],
                    "BROKER_ORDER_DISCOVERED",
                    at,
                    {"broker_order_id": broker_order_id},
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
            if snapshot_as_of <= claimed_at:
                raise ExecutionInvariantError(
                    "broker snapshot does not post-date uncertain submission"
                )
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
            filled = int(row["filled_quantity"])
            intent = ExecutionIntent.model_validate_json(row["intent_json"])
            current_status = ExecutionStatus(row["status"])
            status = self._status_for(
                event,
                filled + event.filled_quantity,
                intent.quantity,
                current=current_status,
            )
            new_filled = min(intent.quantity, filled + event.filled_quantity)
            self.connection.execute(
                """UPDATE execution_intents SET status=?, filled_quantity=?, broker_order_id=?,
                   last_broker_sequence=?, version=version+1 WHERE intent_id=?""",
                (
                    status.value,
                    new_filled,
                    event.broker_order_id,
                    max(int(row["last_broker_sequence"]), event.sequence),
                    intent.intent_id,
                ),
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

    def resolve_client_order_prefix(self, prefix: str) -> str | None:
        rows = self.connection.execute(
            "SELECT client_order_key FROM execution_intents WHERE client_order_key LIKE ? LIMIT 2",
            (f"{prefix}%",),
        ).fetchall()
        return str(rows[0]["client_order_key"]) if len(rows) == 1 else None

    def pending_approval_count(self) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM execution_intents WHERE status=?",
                (ExecutionStatus.APPROVAL_PENDING.value,),
            ).fetchone()[0]
        )

    def pending_approvals(self) -> tuple[sqlite3.Row, ...]:
        return tuple(
            self.connection.execute(
                """SELECT intent_id, decision_id, client_order_key, intent_json, status, version
                   FROM execution_intents WHERE status=? ORDER BY rowid""",
                (ExecutionStatus.APPROVAL_PENDING.value,),
            )
        )

    def active_reserved_notional(self, account_id: str) -> Decimal:
        total = Decimal("0")
        for row in self.connection.execute(
            """SELECT reservation_json FROM risk_reservations
               WHERE status IN (?, ?, ?)""",
            (
                ReservationStatus.ACTIVE.value,
                ReservationStatus.PARTIALLY_CONSUMED.value,
                ReservationStatus.RECONCILIATION_HOLD.value,
            ),
        ):
            reservation = RiskReservation.model_validate_json(row["reservation_json"])
            if reservation.account_id == account_id:
                total += reservation.notional_reserved
        return total

    def is_frozen(self) -> tuple[bool, str]:
        reasons = self.active_freeze_reasons()
        return bool(reasons), ",".join(reasons)

    def active_freeze_reasons(self) -> tuple[str, ...]:
        return tuple(
            row["reason_code"]
            for row in self.connection.execute(
                """SELECT reason_code FROM freeze_tickets
                   WHERE resolved_at IS NULL AND severity='BLOCKING'
                   ORDER BY created_at, ticket_id"""
            )
        )

    def open_freeze_ticket(
        self,
        reason_code: str,
        *,
        source: str,
        at: datetime,
        severity: str = "BLOCKING",
        in_transaction: bool = False,
    ) -> str:
        existing = self.connection.execute(
            """SELECT ticket_id FROM freeze_tickets
               WHERE reason_code=? AND source=? AND resolved_at IS NULL""",
            (reason_code, source),
        ).fetchone()
        if existing is not None:
            return str(existing["ticket_id"])
        ticket_id = canonical_hash({"reason_code": reason_code, "source": source, "created_at": at})
        self.connection.execute(
            "INSERT INTO freeze_tickets VALUES (?, ?, ?, ?, ?, NULL, NULL)",
            (ticket_id, reason_code, severity, source, at.isoformat()),
        )
        self.connection.execute(
            "UPDATE control_state SET frozen=1, reason=?, updated_at=? WHERE singleton=1",
            (reason_code, at.isoformat()),
        )
        if not in_transaction:
            remaining = self.active_freeze_reasons()
            self.connection.execute(
                "UPDATE control_state SET frozen=?, reason=?, updated_at=? WHERE singleton=1",
                (bool(remaining), ",".join(remaining), at.isoformat()),
            )
            self.connection.commit()
        return ticket_id

    def resolve_freeze_ticket(
        self,
        reason_code: str,
        *,
        source: str,
        at: datetime,
        evidence: str,
        in_transaction: bool = False,
    ) -> int:
        updated = self.connection.execute(
            """UPDATE freeze_tickets SET resolved_at=?, resolution_evidence=?
               WHERE reason_code=? AND source=? AND resolved_at IS NULL""",
            (at.isoformat(), evidence, reason_code, source),
        )
        if not in_transaction:
            self.connection.commit()
        return updated.rowcount

    def freeze(self, reason: str, *, at: datetime, in_transaction: bool = False) -> None:
        self.open_freeze_ticket(
            reason.upper(), source="legacy", at=at, in_transaction=in_transaction
        )

    def unfreeze_after_reconciliation(self, *, at: datetime) -> None:
        with self.connection:
            for reason, source in (
                ("STARTUP_RECONCILIATION", "system"),
                ("RECONCILIATION_IN_PROGRESS", "reconciler"),
                ("CRITICAL_RECONCILIATION_DISCREPANCY", "reconciler"),
                ("INCOMPLETE_BROKER_SNAPSHOT", "reconciler"),
                ("BROKER_SNAPSHOT_CONSENSUS_PENDING", "reconciler"),
            ):
                self.resolve_freeze_ticket(
                    reason,
                    source=source,
                    at=at,
                    evidence="complete broker snapshot converged",
                    in_transaction=True,
                )
            remaining = self.active_freeze_reasons()
            self.connection.execute(
                "UPDATE control_state SET frozen=?, reason=?, updated_at=? WHERE singleton=1",
                (bool(remaining), ",".join(remaining), at.isoformat()),
            )

    def set_account_baseline(self, snapshot: BrokerSnapshot) -> None:
        with self.connection:
            projection = self.connection.execute(
                "SELECT cash_delta, commissions FROM cash_projection WHERE singleton=1"
            ).fetchone()
            self.connection.execute(
                """INSERT INTO broker_account_baseline
                   (singleton, cash, buying_power, settled_cash, accrued_cash,
                    currency_balances_json, snapshot_as_of, projection_cash_delta,
                    projection_commissions, bridge_id)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                   ON CONFLICT(singleton) DO NOTHING""",
                (
                    str(snapshot.cash),
                    str(snapshot.buying_power) if snapshot.buying_power is not None else None,
                    str(snapshot.settled_cash) if snapshot.settled_cash is not None else None,
                    str(snapshot.accrued_cash) if snapshot.accrued_cash is not None else None,
                    json.dumps(
                        {key: str(value) for key, value in snapshot.currency_balances.items()},
                        sort_keys=True,
                    ),
                    snapshot.as_of.isoformat(),
                    projection["cash_delta"],
                    projection["commissions"],
                ),
            )

    def advance_account_baseline_epoch(
        self, snapshot: BrokerSnapshot, *, bridge_id: str, at: datetime
    ) -> None:
        """Accept a new cash epoch only after an explained bridge is durable."""
        bridge = self.connection.execute(
            "SELECT baseline_epoch_started FROM cash_bridge_events WHERE bridge_id=?",
            (bridge_id,),
        ).fetchone()
        if bridge is None or not bool(bridge["baseline_epoch_started"]):
            raise ExecutionInvariantError("cash baseline requires an explained bridge")
        projection = self.connection.execute(
            "SELECT cash_delta, commissions FROM cash_projection WHERE singleton=1"
        ).fetchone()
        with self.connection:
            self.connection.execute(
                """INSERT INTO broker_account_baseline
                   (singleton, cash, buying_power, settled_cash, accrued_cash,
                    currency_balances_json, snapshot_as_of, projection_cash_delta,
                    projection_commissions, bridge_id)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(singleton) DO UPDATE SET
                     cash=excluded.cash, buying_power=excluded.buying_power,
                     settled_cash=excluded.settled_cash, accrued_cash=excluded.accrued_cash,
                     currency_balances_json=excluded.currency_balances_json,
                     snapshot_as_of=excluded.snapshot_as_of,
                     projection_cash_delta=excluded.projection_cash_delta,
                     projection_commissions=excluded.projection_commissions,
                     bridge_id=excluded.bridge_id""",
                (
                    str(snapshot.cash),
                    str(snapshot.buying_power) if snapshot.buying_power is not None else None,
                    str(snapshot.settled_cash) if snapshot.settled_cash is not None else None,
                    str(snapshot.accrued_cash) if snapshot.accrued_cash is not None else None,
                    json.dumps(
                        {key: str(value) for key, value in snapshot.currency_balances.items()},
                        sort_keys=True,
                    ),
                    snapshot.as_of.isoformat(),
                    projection["cash_delta"],
                    projection["commissions"],
                    bridge_id,
                ),
            )
            self._append_order_event(
                bridge_id,
                "CASH_BASELINE_EPOCH_ADVANCED",
                at,
                {"snapshot_as_of": snapshot.as_of.isoformat(), "bridge_id": bridge_id},
            )

    def register_snapshot_consensus(
        self,
        snapshot: BrokerSnapshot,
        *,
        at: datetime,
        minimum_interval: timedelta = timedelta(seconds=1),
    ) -> tuple[bool, int]:
        if not (
            snapshot.complete
            and snapshot.semantic_hash
            and snapshot.visibility_scope_hash
            and snapshot.completeness_certificate_id
            and snapshot.observation_id
            and snapshot.session_id
            and snapshot.final_watermark > 0
        ):
            return False, 0
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            duplicate = self.connection.execute(
                "SELECT disposition FROM broker_snapshot_votes WHERE observation_id=?",
                (snapshot.observation_id,),
            ).fetchone()
            row = self.connection.execute(
                "SELECT * FROM broker_snapshot_consensus WHERE visibility_scope_hash=?",
                (snapshot.visibility_scope_hash,),
            ).fetchone()
            if duplicate is not None:
                self.connection.rollback()
                duplicate_count = int(row["consecutive_count"]) if row is not None else 0
                return duplicate_count >= 2, duplicate_count
            count = 1
            first_seen = at
            disposition = "ACCEPTED_FIRST"
            previous = self.connection.execute(
                """SELECT * FROM broker_snapshot_votes
                   WHERE visibility_scope_hash=? AND disposition LIKE 'ACCEPTED%'
                   ORDER BY snapshot_as_of DESC, recorded_at DESC LIMIT 1""",
                (snapshot.visibility_scope_hash,),
            ).fetchone()
            equivalence = self._authority_equivalence(previous, snapshot)
            if (
                previous is not None
                and previous["semantic_hash"] == snapshot.semantic_hash
                and bool(equivalence["state_equivalent"])
            ):
                previous_as_of = datetime.fromisoformat(previous["snapshot_as_of"])
                independent = (
                    previous["certificate_id"] != snapshot.completeness_certificate_id
                    and previous["session_id"] != snapshot.session_id
                    and snapshot.as_of > previous_as_of
                    and snapshot.final_watermark > int(previous["final_watermark"])
                    and snapshot.as_of - previous_as_of >= minimum_interval
                )
                if independent:
                    count = int(row["consecutive_count"]) + 1
                    first_seen = datetime.fromisoformat(row["first_seen_at"])
                    disposition = "ACCEPTED_INDEPENDENT"
                else:
                    count = int(row["consecutive_count"]) if row is not None else 1
                    first_seen = (
                        datetime.fromisoformat(row["first_seen_at"]) if row is not None else at
                    )
                    disposition = "REJECTED_NON_INDEPENDENT"
            elif previous is not None:
                disposition = "ACCEPTED_DIVERGENT_RESET"
            self.connection.execute(
                """INSERT INTO broker_snapshot_votes
                   (observation_id, certificate_id, session_id, visibility_scope_hash,
                    semantic_hash, snapshot_as_of, final_watermark, recorded_at,
                    disposition, snapshot_json, equivalence_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot.observation_id,
                    snapshot.completeness_certificate_id,
                    snapshot.session_id,
                    snapshot.visibility_scope_hash,
                    snapshot.semantic_hash,
                    snapshot.as_of.isoformat(),
                    snapshot.final_watermark,
                    at.isoformat(),
                    disposition,
                    snapshot.model_dump_json(),
                    json.dumps(equivalence, sort_keys=True, separators=(",", ":")),
                ),
            )
            self.connection.execute(
                """INSERT INTO broker_snapshot_consensus VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(visibility_scope_hash) DO UPDATE SET
                     semantic_hash=excluded.semantic_hash,
                     consecutive_count=excluded.consecutive_count,
                     first_seen_at=excluded.first_seen_at,
                     last_seen_at=excluded.last_seen_at,
                     last_certificate_id=excluded.last_certificate_id""",
                (
                    snapshot.visibility_scope_hash,
                    snapshot.semantic_hash,
                    count,
                    first_seen.isoformat(),
                    at.isoformat(),
                    snapshot.completeness_certificate_id,
                ),
            )
            self.connection.commit()
            return count >= 2, count
        except BaseException:
            self.connection.rollback()
            raise

    @staticmethod
    def _authority_equivalence(
        previous: sqlite3.Row | None,
        snapshot: BrokerSnapshot,
        *,
        valuation_tolerance_bps: Decimal = Decimal("25"),
        valuation_absolute_floor: Decimal = Decimal("1"),
    ) -> dict[str, object]:
        exact_equal = bool(
            previous is not None and previous["semantic_hash"] == snapshot.semantic_hash
        )
        differences: dict[str, dict[str, str | bool]] = {}
        previous_snapshot: BrokerSnapshot | None = None
        if previous is not None and previous["snapshot_json"]:
            previous_snapshot = BrokerSnapshot.model_validate_json(previous["snapshot_json"])
        same_policy = bool(
            previous_snapshot is not None
            and previous_snapshot.normalization_policy_hash == snapshot.normalization_policy_hash
        )
        same_fields = bool(
            previous_snapshot is not None
            and set(previous_snapshot.valuation_fields) == set(snapshot.valuation_fields)
        )
        within_budget = same_fields
        if previous_snapshot is not None and same_fields:
            for key in sorted(snapshot.valuation_fields):
                before = previous_snapshot.valuation_fields[key]
                after = snapshot.valuation_fields[key]
                difference = abs(after - before)
                allowed = max(
                    valuation_absolute_floor,
                    abs(before) * valuation_tolerance_bps / Decimal("10000"),
                )
                allowed_field = difference <= allowed
                within_budget = within_budget and allowed_field
                differences[key] = {
                    "previous": str(before),
                    "current": str(after),
                    "absolute_difference": str(difference),
                    "allowed_difference": str(allowed),
                    "within_budget": allowed_field,
                }
        state_equivalent = exact_equal and same_policy and within_budget
        return {
            "state_equivalent": state_equivalent,
            "exact_fields_equal": exact_equal,
            "tolerant_fields_within_budget": within_budget,
            "normalization_policy_equal": same_policy,
            "valuation_tolerance_bps": str(valuation_tolerance_bps),
            "valuation_absolute_floor": str(valuation_absolute_floor),
            "differences": differences,
            "excluded_from_exact_hash": ["NetLiquidation", "BuyingPower"],
            "explanation": (
                "exact economic state matched and valuation observations stayed within "
                "a fail-closed drift budget; market causality is not inferred"
                if state_equivalent
                else "authority state was not equivalent under the normalization policy"
            ),
        }

    def record_broker_snapshot_authority(
        self,
        snapshot: BrokerSnapshot,
        *,
        reconciliation_run_id: str,
        reconciliation_status: str,
        at: datetime,
    ) -> bool:
        if not (
            snapshot.completeness_certificate_id
            and snapshot.semantic_hash
            and snapshot.visibility_scope_hash
        ):
            raise ExecutionInvariantError("broker snapshot authority metadata is incomplete")
        components_complete = (
            snapshot.complete
            and snapshot.order_snapshot_complete
            and snapshot.position_snapshot_complete
            and snapshot.execution_snapshot_complete
            and snapshot.cash_snapshot_complete
            and snapshot.commission_pending_count == 0
        )
        promoted = reconciliation_status == "CONVERGED" and components_complete
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO broker_authority_candidates VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot.completeness_certificate_id,
                    snapshot.model_dump_json(),
                    reconciliation_run_id,
                    reconciliation_status,
                    "PROMOTED" if promoted else "REJECTED",
                    (
                        "policy_converged"
                        if promoted
                        else (
                            "authority_components_incomplete"
                            if reconciliation_status == "CONVERGED"
                            else "reconciliation_not_converged"
                        )
                    ),
                    at.isoformat(),
                ),
            )
            if not promoted:
                return False
            self.connection.execute(
                "INSERT OR REPLACE INTO broker_snapshot_authority VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot.completeness_certificate_id,
                    snapshot.semantic_hash,
                    snapshot.visibility_scope_hash,
                    snapshot.as_of.isoformat(),
                    snapshot.model_dump_json(),
                    reconciliation_run_id,
                    reconciliation_status,
                    at.isoformat(),
                ),
            )
        return True

    def latest_broker_snapshot_authority(
        self, *, at: datetime | None = None, max_age: timedelta | None = None
    ) -> sqlite3.Row | None:
        row = self.connection.execute(
            """SELECT * FROM broker_snapshot_authority
               WHERE reconciliation_status='CONVERGED'
               ORDER BY snapshot_as_of DESC LIMIT 1"""
        ).fetchone()
        if row is not None and at is not None and max_age is not None:
            age = at - datetime.fromisoformat(row["snapshot_as_of"])
            if age < timedelta(0) or age > max_age:
                return None
        assert row is None or isinstance(row, sqlite3.Row)
        return row

    def record_quote_snapshot(
        self,
        *,
        symbol: str,
        bid: Decimal,
        ask: Decimal,
        last: Decimal | None,
        observed_at: datetime,
        provider_timestamp: datetime,
        provider: str,
        feed_mode: str,
        market_phase: str,
        venue: str = "UNKNOWN",
        currency: str = "USD",
        recorded_at: datetime | None = None,
    ) -> QuoteSnapshot:
        raw_hash = canonical_hash(
            {
                "symbol": symbol,
                "bid": str(bid),
                "ask": str(ask),
                "last": str(last) if last is not None else None,
                "provider_timestamp": provider_timestamp,
                "provider": provider,
                "feed_mode": feed_mode,
                "venue": venue,
                "currency": currency,
            }
        )
        freshness_policy_hash = canonical_hash(
            {
                "quote_max_age_seconds": 5,
                "provider_max_age_seconds": 5,
                "eligible_market_phases": ["OPEN", "REGULAR"],
                "required_feed_mode": "REALTIME",
                "maximum_spread_bps": 50,
                "venue_and_currency_required": True,
            }
        )
        body = {
            "symbol": symbol,
            "bid": str(bid),
            "ask": str(ask),
            "last": str(last) if last is not None else None,
            "observed_at": observed_at,
            "provider_timestamp": provider_timestamp,
            "provider": provider,
            "feed_mode": feed_mode,
            "market_phase": market_phase,
            "venue": venue,
            "currency": currency,
            "raw_hash": raw_hash,
            "freshness_policy_hash": freshness_policy_hash,
        }
        quote = QuoteSnapshot.model_validate({"quote_snapshot_id": canonical_hash(body), **body})
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO quote_snapshots VALUES (?, ?, ?, ?, ?, ?)",
                (
                    quote.quote_snapshot_id,
                    symbol,
                    quote.model_dump_json(),
                    observed_at.isoformat(),
                    provider_timestamp.isoformat(),
                    (recorded_at or datetime.now(UTC)).isoformat(),
                ),
            )
        return quote

    def record_cash_bridge(
        self,
        *,
        event_type: str,
        amount: Decimal,
        currency: str,
        at: datetime,
        evidence: dict[str, object],
        explained: bool,
    ) -> str:
        allowed = {
            "BROKER_INTEREST",
            "DIVIDEND",
            "DEPOSIT",
            "WITHDRAWAL",
            "MANUAL_TRADE",
            "FX_TRANSLATION",
            "BROKER_ADJUSTMENT",
        }
        normalized_type = event_type if event_type in allowed else "UNKNOWN_EXTERNAL_CASH_EVENT"
        document = {
            "event_type": normalized_type,
            "amount": str(amount),
            "currency": currency,
            "occurred_at": at.isoformat(),
            "evidence": evidence,
        }
        bridge_id = canonical_hash(document)
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO cash_bridge_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    bridge_id,
                    normalized_type,
                    str(amount),
                    currency,
                    at.isoformat(),
                    json.dumps(evidence, sort_keys=True, separators=(",", ":")),
                    bool(explained and normalized_type in allowed),
                ),
            )
        if not explained or normalized_type == "UNKNOWN_EXTERNAL_CASH_EVENT":
            self.open_freeze_ticket("UNEXPLAINED_CASH_BRIDGE", source="cash_bridge", at=at)
        return bridge_id

    def expected_account_cash(self) -> Decimal | None:
        baseline = self.connection.execute(
            "SELECT cash, projection_cash_delta FROM broker_account_baseline WHERE singleton=1"
        ).fetchone()
        if baseline is None:
            return None
        projection = self.connection.execute(
            "SELECT cash_delta FROM cash_projection WHERE singleton=1"
        ).fetchone()
        return (
            Decimal(baseline["cash"])
            + Decimal(projection["cash_delta"])
            - Decimal(baseline["projection_cash_delta"])
        )

    def expected_account_fields(self) -> dict[str, Decimal | None] | None:
        baseline = self.connection.execute(
            "SELECT * FROM broker_account_baseline WHERE singleton=1"
        ).fetchone()
        if baseline is None:
            return None
        projection = self.connection.execute(
            "SELECT cash_delta FROM cash_projection WHERE singleton=1"
        ).fetchone()
        cash_delta = Decimal(projection["cash_delta"]) - Decimal(baseline["projection_cash_delta"])
        return {
            "cash": Decimal(baseline["cash"]) + cash_delta,
            "settled_cash": None,
            "buying_power": None,
            "accrued_cash": (
                Decimal(baseline["accrued_cash"]) if baseline["accrued_cash"] is not None else None
            ),
        }

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
                self._status_for(
                    broker_event,
                    filled,
                    quantity,
                    current=ExecutionStatus(rebuilt.get(event["intent_id"], ("SUBMITTING", 0))[0]),
                ).value,
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
    def _status_for(
        event: BrokerEvent,
        filled: int,
        quantity: int,
        *,
        current: ExecutionStatus = ExecutionStatus.SUBMITTING,
    ) -> ExecutionStatus:
        if event.event_type == BrokerEventType.COMMISSION:
            return current
        if event.event_type == BrokerEventType.REJECTED:
            if current in {ExecutionStatus.PARTIALLY_FILLED, ExecutionStatus.FILLED}:
                return current
            return ExecutionStatus.REJECTED
        if event.event_type == BrokerEventType.CANCELLED:
            if current == ExecutionStatus.FILLED:
                return current
            return ExecutionStatus.CANCELLED
        if event.event_type in {BrokerEventType.PARTIAL_FILL, BrokerEventType.FILL}:
            return (
                ExecutionStatus.FILLED if filled >= quantity else ExecutionStatus.PARTIALLY_FILLED
            )
        if current in {
            ExecutionStatus.PARTIALLY_FILLED,
            ExecutionStatus.FILLED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.REJECTED,
        }:
            return current
        return ExecutionStatus.ACKNOWLEDGED
