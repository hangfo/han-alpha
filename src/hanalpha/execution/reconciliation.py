from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from hanalpha.domain.enums import Side
from hanalpha.execution.control_models import BrokerSnapshot, ExecutionIntent, ExecutionStatus
from hanalpha.execution.control_store import DurableExecutionStore
from hanalpha.simulation.events import canonical_hash


class DiscrepancySeverity(StrEnum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ReconciliationDiscrepancy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    discrepancy_id: str
    severity: DiscrepancySeverity
    kind: str
    entity_key: str
    details: dict[str, object]


class ReconciliationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    status: str
    discrepancies: tuple[ReconciliationDiscrepancy, ...]
    frozen: bool


class Reconciler:
    def __init__(self, store: DurableExecutionStore) -> None:
        self.store = store

    def reconcile_authoritative(
        self,
        snapshot: BrokerSnapshot,
        *,
        at: datetime,
        minimum_consensus_interval: timedelta = timedelta(seconds=1),
    ) -> ReconciliationReport:
        if not snapshot.complete:
            return self.reconcile(snapshot, at=at)
        consensus, count = self.store.register_snapshot_consensus(
            snapshot, at=at, minimum_interval=minimum_consensus_interval
        )
        if not consensus:
            self.store.open_freeze_ticket(
                "BROKER_SNAPSHOT_CONSENSUS_PENDING", source="reconciler", at=at
            )
            run_id = canonical_hash(
                {
                    "semantic_hash": snapshot.semantic_hash,
                    "visibility_scope_hash": snapshot.visibility_scope_hash,
                    "consensus_count": count,
                    "at": at,
                }
            )
            discrepancy = self._discrepancy(
                DiscrepancySeverity.WARNING,
                "BROKER_SNAPSHOT_CONSENSUS_PENDING",
                snapshot.visibility_scope_hash or "missing-scope",
                {"consecutive_count": count, "required": 2},
            )
            with self.store.connection:
                self.store.connection.execute(
                    "INSERT OR IGNORE INTO reconciliation_runs VALUES (?, ?, ?, ?, ?)",
                    (
                        run_id,
                        at.isoformat(),
                        at.isoformat(),
                        "AWAITING_CONSENSUS",
                        json.dumps({"consecutive_count": count, "required": 2}),
                    ),
                )
                self.store.connection.execute(
                    "INSERT OR IGNORE INTO reconciliation_discrepancies VALUES (?, ?, ?, ?, ?, ?, NULL)",
                    (
                        discrepancy.discrepancy_id,
                        run_id,
                        discrepancy.severity.value,
                        discrepancy.kind,
                        discrepancy.entity_key,
                        json.dumps(discrepancy.details, sort_keys=True),
                    ),
                )
            return ReconciliationReport(
                run_id=run_id,
                status="AWAITING_CONSENSUS",
                discrepancies=(discrepancy,),
                frozen=True,
            )
        report = self.reconcile(snapshot, at=at)
        self.store.record_broker_snapshot_authority(
            snapshot,
            reconciliation_run_id=report.run_id,
            reconciliation_status=report.status,
            at=at,
        )
        return report

    def reconcile(self, snapshot: BrokerSnapshot, *, at: datetime) -> ReconciliationReport:
        run_id = canonical_hash({"as_of": snapshot.as_of, "started_at": at})
        if not snapshot.complete:
            discrepancy = self._discrepancy(
                DiscrepancySeverity.CRITICAL,
                "INCOMPLETE_BROKER_SNAPSHOT",
                snapshot.completeness_certificate_id or "missing-certificate",
                {"snapshot_as_of": snapshot.as_of.isoformat()},
            )
            with self.store.connection:
                self.store.connection.execute(
                    "INSERT OR IGNORE INTO reconciliation_runs VALUES (?, ?, ?, ?, ?)",
                    (
                        run_id,
                        at.isoformat(),
                        at.isoformat(),
                        "INCOMPLETE_SNAPSHOT",
                        json.dumps({"status": "INCOMPLETE_SNAPSHOT", "discrepancy_count": 1}),
                    ),
                )
                self.store.connection.execute(
                    "INSERT OR IGNORE INTO reconciliation_discrepancies VALUES (?, ?, ?, ?, ?, ?, NULL)",
                    (
                        discrepancy.discrepancy_id,
                        run_id,
                        discrepancy.severity.value,
                        discrepancy.kind,
                        discrepancy.entity_key,
                        json.dumps(discrepancy.details, sort_keys=True, separators=(",", ":")),
                    ),
                )
            self.store.open_freeze_ticket(
                "INCOMPLETE_BROKER_SNAPSHOT", source="reconciler", at=at
            )
            return ReconciliationReport(
                run_id=run_id,
                status="INCOMPLETE_SNAPSHOT",
                discrepancies=(discrepancy,),
                frozen=True,
            )
        self.store.open_freeze_ticket(
            "RECONCILIATION_IN_PROGRESS", source="reconciler", at=at
        )
        with self.store.connection:
            self.store.connection.execute(
                "INSERT INTO reconciliation_runs VALUES (?, ?, NULL, 'RUNNING', NULL)",
                (run_id, at.isoformat()),
            )
        broker_by_key = {order.client_order_key: order for order in snapshot.orders}
        self.store.recover_claimed_as_unknown(at=at)
        local_by_key = {row["client_order_key"]: row for row in self.store.intents()}
        for event in snapshot.events:
            if event.client_order_key in local_by_key:
                self.store.ingest_broker_event(event)

        discrepancies: list[ReconciliationDiscrepancy] = []
        for key, broker_order in broker_by_key.items():
            local = local_by_key.get(key)
            if local is None:
                discrepancies.append(
                    self._discrepancy(
                        DiscrepancySeverity.CRITICAL,
                        "BROKER_ONLY_ORDER",
                        key,
                        {"broker_order_id": broker_order.broker_order_id},
                    )
                )
                continue
            self.store.resolve_unknown_at_broker(
                key, broker_order_id=broker_order.broker_order_id, at=at
            )
            refreshed = self.store.intent(local["intent_id"])
            if int(refreshed["filled_quantity"]) != broker_order.filled_quantity:
                discrepancies.append(
                    self._discrepancy(
                        DiscrepancySeverity.CRITICAL,
                        "FILL_QUANTITY_MISMATCH",
                        key,
                        {
                            "local": int(refreshed["filled_quantity"]),
                            "broker": broker_order.filled_quantity,
                        },
                    )
                )

        active_local = {
            ExecutionStatus.SUBMITTING.value,
            ExecutionStatus.SUBMISSION_UNKNOWN.value,
            ExecutionStatus.ACKNOWLEDGED.value,
            ExecutionStatus.PARTIALLY_FILLED.value,
        }
        for key, local in local_by_key.items():
            if (
                local["status"] == ExecutionStatus.SUBMISSION_UNKNOWN.value
                and key not in broker_by_key
            ):
                self.store.requeue_unknown_absent_at_broker(
                    key, snapshot_as_of=snapshot.as_of, at=at
                )
            elif local["status"] in active_local and key not in broker_by_key:
                discrepancies.append(
                    self._discrepancy(
                        DiscrepancySeverity.CRITICAL,
                        "LOCAL_ORDER_MISSING_AT_BROKER",
                        key,
                        {"local_status": local["status"]},
                    )
                )

        local_positions: dict[str, int] = {}
        for row in self.store.intents():
            intent = ExecutionIntent.model_validate_json(row["intent_json"])
            signed = (
                int(row["filled_quantity"])
                if intent.side == Side.BUY
                else -int(row["filled_quantity"])
            )
            local_positions[intent.instrument_id] = (
                local_positions.get(intent.instrument_id, 0) + signed
            )
        for instrument in sorted(set(local_positions) | set(snapshot.positions)):
            if local_positions.get(instrument, 0) != snapshot.positions.get(instrument, 0):
                discrepancies.append(
                    self._discrepancy(
                        DiscrepancySeverity.CRITICAL,
                        "POSITION_MISMATCH",
                        instrument,
                        {
                            "local": local_positions.get(instrument, 0),
                            "broker": snapshot.positions.get(instrument, 0),
                        },
                    )
                )

        for key, broker_order in broker_by_key.items():
            local = local_by_key.get(key)
            if local is None:
                continue
            filled = int(self.store.intent(local["intent_id"])["filled_quantity"])
            children = [
                child
                for child in snapshot.protection_orders
                if child.parent_client_order_key == key and child.active
            ]
            stop_quantity = sum(
                child.quantity for child in children if child.protection_type == "STOP"
            )
            target_quantity = sum(
                child.quantity for child in children if child.protection_type == "TARGET"
            )
            protected_quantity = min(stop_quantity, target_quantity)
            if not children:
                protected_quantity = broker_order.protection_quantity
            if broker_order.side == Side.BUY and filled > protected_quantity:
                unprotected = filled - protected_quantity
                self.store.record_naked_exposure(
                    broker_order.instrument_id,
                    unprotected_quantity=unprotected,
                    duration_ms=0,
                    at=at,
                )
                discrepancies.append(
                    self._discrepancy(
                        DiscrepancySeverity.CRITICAL,
                        "ORDER_PROTECTION_SHORTFALL",
                        key,
                        {
                            "filled": filled,
                            "protected": protected_quantity,
                            "stop_quantity": stop_quantity,
                            "target_quantity": target_quantity,
                            "broker_order_id": broker_order.broker_order_id,
                        },
                    )
                )

        expected_cash = self.store.expected_account_cash()
        if expected_cash is None:
            self.store.set_account_baseline(snapshot)
        elif abs(expected_cash - snapshot.cash) > Decimal("0.01"):
            discrepancies.append(
                self._discrepancy(
                    DiscrepancySeverity.CRITICAL,
                    "CASH_MISMATCH",
                    snapshot.base_currency,
                    {"local": str(expected_cash), "broker": str(snapshot.cash)},
                )
            )

        expected_fields = self.store.expected_account_fields()
        if expected_fields is not None:
            for field_name in ("settled_cash", "buying_power", "accrued_cash"):
                expected = expected_fields[field_name]
                actual = getattr(snapshot, field_name)
                if expected is not None and actual is not None and abs(expected - actual) > Decimal("0.01"):
                    discrepancies.append(
                        self._discrepancy(
                            DiscrepancySeverity.WARNING,
                            f"{field_name.upper()}_MISMATCH",
                            snapshot.base_currency,
                            {"local": str(expected), "broker": str(actual)},
                        )
                    )
            base_balance = snapshot.currency_balances.get(snapshot.base_currency)
            if base_balance is not None and abs(base_balance - snapshot.cash) > Decimal("0.01"):
                discrepancies.append(
                    self._discrepancy(
                        DiscrepancySeverity.WARNING,
                        "BASE_CURRENCY_BALANCE_MISMATCH",
                        snapshot.base_currency,
                        {"cash": str(snapshot.cash), "currency_balance": str(base_balance)},
                    )
                )
        for instrument in sorted(snapshot.positions):
            if snapshot.positions.get(instrument, 0) > snapshot.protections.get(instrument, 0):
                unprotected = snapshot.positions.get(instrument, 0) - snapshot.protections.get(
                    instrument, 0
                )
                fill_times = [
                    event.occurred_at
                    for event in snapshot.events
                    if event.event_type.value in {"PARTIAL_FILL", "FILL"}
                    and event.client_order_key in broker_by_key
                    and broker_by_key[event.client_order_key].instrument_id == instrument
                ]
                duration_ms = (
                    max(0, int((snapshot.as_of - min(fill_times)).total_seconds() * 1000))
                    if fill_times
                    else 0
                )
                self.store.record_naked_exposure(
                    instrument,
                    unprotected_quantity=unprotected,
                    duration_ms=duration_ms,
                    at=at,
                )
                discrepancies.append(
                    self._discrepancy(
                        DiscrepancySeverity.CRITICAL,
                        "NAKED_LONG_EXPOSURE",
                        instrument,
                        {
                            "position": snapshot.positions.get(instrument, 0),
                            "protected": snapshot.protections.get(instrument, 0),
                            "unprotected_duration_ms": duration_ms,
                        },
                    )
                )

        critical = any(item.severity == DiscrepancySeverity.CRITICAL for item in discrepancies)
        status = "BLOCKED" if critical else ("DEGRADED" if discrepancies else "CONVERGED")
        with self.store.connection:
            for item in discrepancies:
                self.store.connection.execute(
                    "INSERT OR IGNORE INTO reconciliation_discrepancies VALUES (?, ?, ?, ?, ?, ?, NULL)",
                    (
                        item.discrepancy_id,
                        run_id,
                        item.severity.value,
                        item.kind,
                        item.entity_key,
                        json.dumps(item.details, sort_keys=True, separators=(",", ":")),
                    ),
                )
            self.store.connection.execute(
                """UPDATE reconciliation_runs SET completed_at=?, status=?, summary_json=?
                   WHERE run_id=?""",
                (
                    at.isoformat(),
                    status,
                    json.dumps(
                        {"status": status, "discrepancy_count": len(discrepancies)},
                        sort_keys=True,
                    ),
                    run_id,
                ),
            )
        if critical:
            self.store.open_freeze_ticket(
                "CRITICAL_RECONCILIATION_DISCREPANCY", source="reconciler", at=at
            )
        else:
            self.store.unfreeze_after_reconciliation(at=at)
        return ReconciliationReport(
            run_id=run_id,
            status=status,
            discrepancies=tuple(discrepancies),
            frozen=critical,
        )

    @staticmethod
    def _discrepancy(
        severity: DiscrepancySeverity,
        kind: str,
        entity_key: str,
        details: dict[str, object],
    ) -> ReconciliationDiscrepancy:
        identity = {
            "severity": severity,
            "kind": kind,
            "entity_key": entity_key,
            "details": details,
        }
        return ReconciliationDiscrepancy(
            discrepancy_id=canonical_hash(identity),
            severity=severity,
            kind=kind,
            entity_key=entity_key,
            details=details,
        )
