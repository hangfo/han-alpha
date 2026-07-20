from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hanalpha.execution.control_store import DurableExecutionStore
from hanalpha.execution.ibkr_observer import IBKRFactStore


class OpsService:
    """Read-only, source-backed operational projection for API and dashboard."""

    def __init__(
        self, store: DurableExecutionStore, *, observer_path: Path | None = None
    ) -> None:
        self.store = store
        self.observer_path = observer_path

    def overview(self, *, now: datetime | None = None) -> dict[str, Any]:
        observed_at = now or datetime.now(UTC)
        frozen, freeze_reason = self.store.is_frozen()
        status_counts = {
            str(row["status"]): int(row["count"])
            for row in self.store.connection.execute(
                "SELECT status, COUNT(*) AS count FROM execution_intents GROUP BY status"
            )
        }
        unknown = sum(
            status_counts.get(key, 0)
            for key in ("SUBMISSION_UNKNOWN", "CANCEL_UNKNOWN", "RECONCILIATION_REQUIRED")
        )
        naked = self.store.connection.execute(
            "SELECT COUNT(*) AS count, MAX(duration_ms) AS max_ms FROM naked_exposure_intervals WHERE resolved_at IS NULL"
        ).fetchone()
        last_reconcile = self.store.connection.execute(
            "SELECT * FROM reconciliation_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        authority = self.store.latest_broker_snapshot_authority()
        heartbeats = [
            {
                "component": row["component"],
                "status": row["status"],
                "observed_at": row["observed_at"],
                "details": json.loads(row["details_json"]),
            }
            for row in self.store.connection.execute(
                "SELECT * FROM ops_heartbeats ORDER BY component"
            )
        ]
        observer = self._observer_summary()
        return {
            "as_of": observed_at.isoformat(),
            "environment": "paper-first",
            "safety": {
                "frozen": frozen,
                "freeze_reason": freeze_reason,
                "unknown_intents": unknown,
                "naked_exposures": int(naked["count"]),
                "max_naked_duration_ms": int(naked["max_ms"] or 0),
            },
            "execution": {
                "status_counts": status_counts,
                "pending_approvals": self.store.pending_approval_count(),
                "pending_cancels": self._count("cancel_commands", "status='PENDING'"),
                "reserved_notional": str(self.store.active_reserved_notional("runtime-paper")),
            },
            "reconciliation": {
                "status": last_reconcile["status"] if last_reconcile else "NEVER_RUN",
                "started_at": last_reconcile["started_at"] if last_reconcile else None,
                "unresolved_discrepancies": self._count(
                    "reconciliation_discrepancies", "resolved_at IS NULL"
                ),
                "authority_snapshot_as_of": authority["snapshot_as_of"] if authority else None,
                "visibility_scope_hash": authority["visibility_scope_hash"] if authority else None,
            },
            "observer": observer,
            "heartbeats": heartbeats,
            "reality_gap": {
                "samples": self._count("reality_gap_ledger"),
                "no_trade_outcomes": self._count("no_trade_ledger"),
            },
            "source_notes": {
                "control": "durable execution SQLite projection",
                "broker": "IBKR fact tape when locally configured; otherwise unavailable",
                "pnl": "not shown until broker-authoritative P&L is available",
            },
        }

    def readiness(self, runtime_status: dict[str, Any]) -> dict[str, Any]:
        frozen, reason = self.store.is_frozen()
        checks = {
            "broker_connected": bool(runtime_status.get("broker_connected")),
            "market_data_healthy": bool(runtime_status.get("market_data_healthy")),
            "control_reconciled": not frozen,
        }
        return {
            "ready": all(checks.values()),
            "checks": checks,
            "freeze_reason": reason,
            "as_of": datetime.now(UTC).isoformat(),
        }

    def prometheus(self) -> str:
        overview = self.overview()
        safety = overview["safety"]
        execution = overview["execution"]
        reconciliation = overview["reconciliation"]
        return "\n".join(
            (
                "# HELP hanalpha_control_frozen Whether new risk is frozen.",
                "# TYPE hanalpha_control_frozen gauge",
                f"hanalpha_control_frozen {int(bool(safety['frozen']))}",
                "# HELP hanalpha_execution_unknown Uncertain submit or cancel outcomes.",
                "# TYPE hanalpha_execution_unknown gauge",
                f"hanalpha_execution_unknown {int(safety['unknown_intents'])}",
                "# HELP hanalpha_pending_approvals Approval-pending intents.",
                "# TYPE hanalpha_pending_approvals gauge",
                f"hanalpha_pending_approvals {int(execution['pending_approvals'])}",
                "# HELP hanalpha_reconciliation_discrepancies Unresolved discrepancies.",
                "# TYPE hanalpha_reconciliation_discrepancies gauge",
                f"hanalpha_reconciliation_discrepancies {int(reconciliation['unresolved_discrepancies'])}",
                "",
            )
        )

    def _observer_summary(self) -> dict[str, Any]:
        if self.observer_path is None or not self.observer_path.exists():
            return {"available": False, "status": "NO_LOCAL_FACT_TAPE"}
        observer = IBKRFactStore(self.observer_path)
        try:
            certificate = observer.latest_certificate()
            if certificate is None:
                return {"available": True, "status": "NO_CERTIFICATE"}
            return {
                "available": True,
                "status": "COMPLETE" if certificate.complete else "INCOMPLETE",
                "certificate_id": certificate.certificate_id,
                "as_of": certificate.as_of.isoformat(),
                "queue_drained": certificate.queue_drained,
                "visibility_complete": certificate.visibility.scope_complete,
                "critical_errors": list(certificate.critical_errors),
            }
        finally:
            observer.close()

    def _count(self, table: str, where: str | None = None) -> int:
        allowed = {
            "cancel_commands",
            "reconciliation_discrepancies",
            "reality_gap_ledger",
            "no_trade_ledger",
        }
        if table not in allowed:
            raise ValueError("unsupported ops table")
        clause = f" WHERE {where}" if where else ""
        row = self.store.connection.execute(
            f"SELECT COUNT(*) AS count FROM {table}{clause}"
        ).fetchone()
        return int(row["count"])
