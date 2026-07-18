from __future__ import annotations

import json
from datetime import datetime
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

    def reconcile(self, snapshot: BrokerSnapshot, *, at: datetime) -> ReconciliationReport:
        run_id = canonical_hash({"as_of": snapshot.as_of, "started_at": at})
        self.store.freeze("reconciliation_in_progress", at=at)
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
            self.store.resolve_unknown_at_broker(key, at=at)
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
        status = "BLOCKED" if critical else "CONVERGED"
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
            self.store.freeze("critical_reconciliation_discrepancy", at=at)
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
