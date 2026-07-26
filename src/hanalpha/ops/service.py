from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from hanalpha.execution.control_store import DurableExecutionStore
from hanalpha.execution.ibkr_observer import IBKRFactStore


class OpsService:
    """Read-only, source-backed operational projection for API and dashboard."""

    AUTHORITY_MAX_AGE = timedelta(seconds=30)
    OBSERVER_MAX_AGE = timedelta(seconds=30)
    HEARTBEAT_MAX_AGE = timedelta(seconds=30)

    def __init__(self, store: DurableExecutionStore, *, observer_path: Path | None = None) -> None:
        self.store = store
        self.observer_path = observer_path

    @staticmethod
    def _age_seconds(value: str | None, now: datetime) -> float | None:
        if value is None:
            return None
        return max(0.0, (now - datetime.fromisoformat(value)).total_seconds())

    @staticmethod
    def _signed_age_seconds(value: str | None, now: datetime) -> float | None:
        if value is None:
            return None
        return (now - datetime.fromisoformat(value)).total_seconds()

    def overview(
        self,
        *,
        now: datetime | None = None,
        runtime_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
            """SELECT COUNT(*) AS count, MAX(duration_ms) AS max_ms
               FROM naked_exposure_intervals WHERE resolved_at IS NULL"""
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
                "age_seconds": self._age_seconds(row["observed_at"], observed_at),
                "details": json.loads(row["details_json"]),
            }
            for row in self.store.connection.execute(
                "SELECT * FROM ops_heartbeats ORDER BY component"
            )
        ]
        observer = self._observer_summary(observed_at)
        authority_as_of = authority["snapshot_as_of"] if authority else None
        reconciliation_at = last_reconcile["completed_at"] if last_reconcile else None
        candidates = [
            {
                "certificate_id": row["certificate_id"],
                "recorded_at": row["recorded_at"],
                "reconciliation_status": row["reconciliation_status"],
                "promotion_status": row["promotion_status"],
                "policy_reason": row["policy_reason"],
            }
            for row in self.store.connection.execute(
                """SELECT * FROM broker_authority_candidates
                   ORDER BY recorded_at DESC LIMIT 20"""
            )
        ]
        discrepancies = [
            {
                "kind": row["kind"],
                "entity_key": row["entity_key"],
                "severity": row["severity"],
                "status": row["lifecycle_status"],
                "first_seen_at": row["first_seen_at"],
                "last_seen_at": row["last_seen_at"],
                "resolved_at": row["resolved_at"],
                "resolution_evidence": (
                    json.loads(row["resolution_evidence"]) if row["resolution_evidence"] else None
                ),
            }
            for row in self.store.connection.execute(
                """SELECT * FROM reconciliation_discrepancies
                   ORDER BY COALESCE(last_seen_at, first_seen_at) DESC LIMIT 50"""
            )
        ]
        vote_counts = {
            str(row["disposition"]): int(row["count"])
            for row in self.store.connection.execute(
                """SELECT disposition, COUNT(*) AS count FROM broker_snapshot_votes
                   GROUP BY disposition"""
            )
        }
        quote = self.store.connection.execute(
            """SELECT observed_at, provider_timestamp, quote_json
               FROM quote_snapshots ORDER BY observed_at DESC LIMIT 1"""
        ).fetchone()
        safety_case = self.store.connection.execute(
            """SELECT case_json, status, created_at FROM paper_canary_safety_cases
               ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
        authority_age = self._age_seconds(authority_as_of, observed_at)
        reconcile_age = self._age_seconds(reconciliation_at, observed_at)
        quote_age = self._signed_age_seconds(quote["observed_at"], observed_at) if quote else None
        quote_provider_age = (
            self._signed_age_seconds(quote["provider_timestamp"], observed_at) if quote else None
        )
        quote_document = json.loads(quote["quote_json"]) if quote else {}
        safety_case_document = json.loads(safety_case["case_json"]) if safety_case else {}
        readiness = self.layered_readiness(
            runtime_status=runtime_status or {},
            now=observed_at,
            observer=observer,
            frozen=frozen,
            authority_age=authority_age,
            reconcile_status=(last_reconcile["status"] if last_reconcile else None),
            unknown=unknown,
            naked=int(naked["count"]),
            heartbeats=heartbeats,
            quote_age=quote_age,
            quote_provider_age=quote_provider_age,
            quote_document=quote_document,
            safety_case=safety_case_document,
        )
        stable_consensus = self.store.connection.execute(
            "SELECT COALESCE(MAX(consecutive_count), 0) FROM broker_snapshot_consensus"
        ).fetchone()[0]
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
                "age_seconds": reconcile_age,
                "unresolved_discrepancies": self._count(
                    "reconciliation_discrepancies", "lifecycle_status='OPEN'"
                ),
                "authority_snapshot_as_of": authority_as_of,
                "authority_age_seconds": authority_age,
                "visibility_scope_hash": authority["visibility_scope_hash"] if authority else None,
            },
            "observer": observer,
            "freshness": {
                "api_age_seconds": 0,
                "authority_age_seconds": authority_age,
                "observer_fact_age_seconds": observer.get("age_seconds"),
                "quote_age_seconds": quote_age,
                "quote_provider_age_seconds": quote_provider_age,
                "reconciliation_age_seconds": reconcile_age,
            },
            "readiness": readiness,
            "authority_timeline": candidates,
            "discrepancies": discrepancies,
            "heartbeats": heartbeats,
            "backup": self._backup_summary(heartbeats),
            "burn_in": {
                "completed_observation_sessions": sum(
                    vote_counts.get(key, 0)
                    for key in (
                        "ACCEPTED_FIRST",
                        "ACCEPTED_INDEPENDENT",
                        "ACCEPTED_DIVERGENT_RESET",
                    )
                ),
                "stable_consensus_votes": vote_counts.get("ACCEPTED_INDEPENDENT", 0),
                "consecutive_stable_sessions": int(stable_consensus),
                "divergent_resets": vote_counts.get("ACCEPTED_DIVERGENT_RESET", 0),
                "non_independent_rejections": vote_counts.get("REJECTED_NON_INDEPENDENT", 0),
                "target_sessions": 30,
                "process_restarts": 0,
                "target_process_restarts": 3,
                "tws_restarts": 0,
                "target_tws_restarts": 2,
                "nightly_resets": 0,
                "target_nightly_resets": 1,
                "golden_tapes": 0,
                "target_golden_tapes": 10,
                "vote_dispositions": vote_counts,
            },
            "paper_canary_safety_case": {
                "available": safety_case is not None,
                "status": safety_case["status"] if safety_case else "NOT_ISSUED",
                "created_at": safety_case["created_at"] if safety_case else None,
                "safety_case_id": safety_case_document.get("safety_case_id"),
            },
            "reality_gap": {
                "samples": self._count("reality_gap_ledger"),
                "no_trade_outcomes": self._count("no_trade_ledger"),
            },
            "source_notes": {
                "control": "durable execution SQLite projection",
                "broker": "IBKR fact tape when locally configured; otherwise unavailable",
                "freshness": "status colors derive from the oldest required fact, not API response time",
                "pnl": "not shown until broker-authoritative P&L is available",
            },
        }

    def readiness(self, runtime_status: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC)
        overview = self.overview(now=now, runtime_status=runtime_status)
        layered = overview["readiness"]
        return {
            "ready": layered["paper_canary"]["ready"],
            "checks": layered["paper_canary"]["checks"],
            "layers": layered,
            "as_of": now.isoformat(),
        }

    def layered_readiness(
        self,
        *,
        runtime_status: dict[str, Any],
        now: datetime,
        observer: dict[str, Any],
        frozen: bool,
        authority_age: float | None,
        reconcile_status: str | None,
        unknown: int,
        naked: int,
        heartbeats: list[dict[str, Any]],
        quote_age: float | None,
        quote_provider_age: float | None,
        quote_document: dict[str, Any],
        safety_case: dict[str, Any],
    ) -> dict[str, Any]:
        service_checks = {"control_database": True, "api_process": True}
        observer_checks = {
            "broker_connected": bool(runtime_status.get("broker_connected", False)),
            "certificate_complete": observer.get("status") == "COMPLETE",
            "observer_fresh": observer.get("age_seconds") is not None
            and float(observer["age_seconds"]) <= self.OBSERVER_MAX_AGE.total_seconds(),
            "queue_clean": int(observer.get("queue_depth", 0)) == 0
            and int(observer.get("dropped_facts", 0)) == 0
            and observer.get("writer_error") is None,
        }
        authority_checks = {
            "authority_fresh": authority_age is not None
            and authority_age <= self.AUTHORITY_MAX_AGE.total_seconds(),
            "reconciliation_converged": reconcile_status == "CONVERGED",
            "control_not_frozen": not frozen,
            "no_unknown": unknown == 0,
            "no_naked_exposure": naked == 0,
        }
        heartbeat_checks = {
            item["component"]: item["status"] == "OK"
            and item.get("age_seconds") is not None
            and float(item["age_seconds"]) <= self.HEARTBEAT_MAX_AGE.total_seconds()
            for item in heartbeats
        }
        runtime_control_checks = {
            **observer_checks,
            **authority_checks,
            "market_data_healthy": bool(runtime_status.get("market_data_healthy", False)),
            "component_heartbeats": bool(heartbeat_checks) and all(heartbeat_checks.values()),
        }
        quote_authority_valid = bool(
            quote_age is not None
            and quote_age >= 0
            and quote_age <= 5
            and quote_provider_age is not None
            and quote_provider_age >= 0
            and quote_provider_age <= 5
            and quote_document.get("feed_mode") == "REALTIME"
            and quote_document.get("market_phase") in {"OPEN", "REGULAR"}
        )
        required_safety_checks = (
            "burn_in_passed",
            "golden_tapes_passed",
            "nightly_reset_passed",
            "market_calendar_verified",
            "real_cancel_passed",
            "real_bracket_passed",
            "paper_account_verified",
            "durable_writer_available",
            "canary_permit_valid",
        )
        paper_checks = {
            "runtime_control_ready": all(runtime_control_checks.values()),
            "quote_authority_valid": quote_authority_valid,
            **{
                name: bool(safety_case.get("checks", {}).get(name, False))
                for name in required_safety_checks
            },
        }
        return {
            "service": {"ready": all(service_checks.values()), "checks": service_checks},
            "observer": {"ready": all(observer_checks.values()), "checks": observer_checks},
            "authority": {"ready": all(authority_checks.values()), "checks": authority_checks},
            "shadow": {
                "ready": all(authority_checks.values())
                and bool(runtime_status.get("market_data_healthy", False)),
                "checks": {
                    **authority_checks,
                    "market_data_healthy": bool(runtime_status.get("market_data_healthy", False)),
                },
            },
            "runtime_control": {
                "ready": all(runtime_control_checks.values()),
                "checks": runtime_control_checks,
            },
            "paper_canary": {"ready": all(paper_checks.values()), "checks": paper_checks},
        }

    def prometheus(self) -> str:
        overview = self.overview()
        now = datetime.now(UTC)

        def age_or_missing(value: Any) -> float:
            return -1.0 if value is None else float(value)

        lease = self.store.connection.execute(
            "SELECT acquired_at FROM execution_leases ORDER BY acquired_at DESC LIMIT 1"
        ).fetchone()
        oldest_unknown = self.store.connection.execute(
            """SELECT MIN(started_at) AS occurred_at FROM (
                 SELECT e.intent_id, MAX(e.occurred_at) AS started_at
                 FROM order_events e
                 JOIN execution_intents i ON i.intent_id=e.intent_id
                 WHERE i.status IN ('SUBMISSION_UNKNOWN', 'CANCEL_UNKNOWN',
                                    'RECONCILIATION_REQUIRED')
                   AND e.event_type IN ('SUBMISSION_UNKNOWN', 'CANCEL_UNKNOWN')
                 GROUP BY e.intent_id
               )"""
        ).fetchone()
        discrepancy_kinds = {
            str(row["kind"]): int(row["count"])
            for row in self.store.connection.execute(
                """SELECT kind, COUNT(*) AS count FROM reconciliation_discrepancies
                   WHERE lifecycle_status='OPEN' GROUP BY kind"""
            )
        }
        values = {
            "control_frozen": int(bool(overview["safety"]["frozen"])),
            "execution_unknown": int(overview["safety"]["unknown_intents"]),
            "pending_approvals": int(overview["execution"]["pending_approvals"]),
            "reconciliation_discrepancies": int(
                overview["reconciliation"]["unresolved_discrepancies"]
            ),
            "observer_certificate_complete": int(overview["observer"].get("status") == "COMPLETE"),
            "observer_queue_depth": int(overview["observer"].get("queue_depth", 0)),
            "observer_dropped_facts": int(overview["observer"].get("dropped_facts", 0)),
            "authority_age_seconds": age_or_missing(overview["freshness"]["authority_age_seconds"]),
            "quote_provider_age_seconds": age_or_missing(
                overview["freshness"]["quote_provider_age_seconds"]
            ),
            "reconciliation_age_seconds": age_or_missing(
                overview["freshness"]["reconciliation_age_seconds"]
            ),
            "naked_exposure_duration_ms": int(overview["safety"]["max_naked_duration_ms"]),
            "commission_pending": int(overview["observer"].get("commission_pending", 0)),
            "cash_gap": discrepancy_kinds.get("CASH_MISMATCH", 0),
            "position_gap": discrepancy_kinds.get("POSITION_MISMATCH", 0),
            "unknown_age_seconds": float(
                self._age_seconds(oldest_unknown["occurred_at"], now) or 0
            ),
            "lease_age_seconds": age_or_missing(
                self._age_seconds(lease["acquired_at"], now) if lease else None
            ),
            "heartbeat_max_age_seconds": max(
                (
                    float(item["age_seconds"])
                    for item in overview["heartbeats"]
                    if item["age_seconds"] is not None
                ),
                default=-1,
            ),
            "backup_age_seconds": age_or_missing(overview["backup"].get("age_seconds")),
            "burn_in_completed_observation_sessions": int(
                overview["burn_in"]["completed_observation_sessions"]
            ),
            "burn_in_consecutive_stable_sessions": int(
                overview["burn_in"]["consecutive_stable_sessions"]
            ),
            "burn_in_divergent_resets": int(overview["burn_in"]["divergent_resets"]),
        }
        lines: list[str] = []
        for name, value in values.items():
            metric = f"hanalpha_{name}"
            lines.extend((f"# TYPE {metric} gauge", f"{metric} {value}"))
        return "\n".join((*lines, ""))

    def _observer_summary(self, now: datetime) -> dict[str, Any]:
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
                "age_seconds": self._age_seconds(certificate.as_of.isoformat(), now),
                "queue_drained": certificate.queue_drained,
                "queue_depth": certificate.queue_depth,
                "accepted_facts": certificate.accepted_facts,
                "written_facts": certificate.written_facts,
                "dropped_facts": certificate.dropped_facts,
                "writer_error": certificate.writer_error,
                "commission_pending": certificate.executions_missing_commission_count,
                "cash_complete": certificate.cash_snapshot_complete,
                "visibility_complete": certificate.visibility.scope_complete,
                "critical_errors": list(certificate.critical_errors),
            }
        finally:
            observer.close()

    @staticmethod
    def _backup_summary(heartbeats: list[dict[str, Any]]) -> dict[str, Any]:
        backup = next((item for item in heartbeats if item["component"] == "backup"), None)
        if backup is None:
            return {"status": "NO_RECORDED_BACKUP", "age_seconds": None}
        return {
            "status": backup["status"],
            "age_seconds": backup["age_seconds"],
            **backup["details"],
            "current_generation_id": backup["details"].get("generation_id"),
        }

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
