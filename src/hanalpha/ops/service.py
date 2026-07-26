from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from hanalpha.execution.admission import evaluate_quote_admission
from hanalpha.execution.control_models import BrokerSnapshot, QuoteSnapshot
from hanalpha.execution.control_store import DurableExecutionStore
from hanalpha.execution.ibkr_observer import IBKRFactStore
from hanalpha.execution.safety_case import SafetyCaseVerification, verify_safety_case


class OpsService:
    """Read-only, source-backed operational projection for API and dashboard."""

    AUTHORITY_MAX_AGE = timedelta(seconds=30)
    OBSERVER_MAX_AGE = timedelta(seconds=30)
    HEARTBEAT_MAX_AGE = timedelta(seconds=30)

    def __init__(
        self,
        store: DurableExecutionStore,
        *,
        observer_path: Path | None = None,
        safety_case_verification_key: bytes | None = None,
    ) -> None:
        self.store = store
        self.observer_path = observer_path
        self.safety_case_verification_key = safety_case_verification_key

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
        selected_scope = (
            str(authority["visibility_scope_hash"])
            if authority
            else observer.get("visibility_scope_hash")
        )
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
        all_scope_vote_counts = {
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
        quote_admission = (
            evaluate_quote_admission(
                QuoteSnapshot.model_validate(quote_document),
                at=observed_at,
                expected_currency=(
                    str(runtime_status["base_currency"])
                    if runtime_status and runtime_status.get("base_currency")
                    else None
                ),
            )
            if quote
            else None
        )
        safety_case_document = json.loads(safety_case["case_json"]) if safety_case else {}
        authority_snapshot = (
            BrokerSnapshot.model_validate_json(authority["snapshot_json"])
            if authority
            else None
        )
        safety_verification = (
            verify_safety_case(
                safety_case_document,
                database_status=str(safety_case["status"]),
                at=observed_at,
                verification_key=self.safety_case_verification_key,
                expected_scope_hash=selected_scope,
                expected_bindings={
                    "git_commit": (
                        str(runtime_status["git_commit"])
                        if runtime_status and runtime_status.get("git_commit")
                        else None
                    ),
                    "config_hash": (
                        str(runtime_status["config_hash"])
                        if runtime_status and runtime_status.get("config_hash")
                        else None
                    ),
                    "account_hash": (
                        authority_snapshot.account_hash if authority_snapshot else None
                    ),
                    "environment": (
                        str(runtime_status["environment"])
                        if runtime_status and runtime_status.get("environment")
                        else None
                    ),
                    "normalization_policy_hash": (
                        authority_snapshot.normalization_policy_hash
                        if authority_snapshot
                        else None
                    ),
                },
            )
            if safety_case
            else SafetyCaseVerification(
                verified=False,
                reasons=("NOT_ISSUED",),
                safety_case_id=None,
                evidence_checks={},
            )
        )
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
            quote_evidence_eligible=bool(
                quote_admission is not None and quote_admission.eligible
            ),
            safety_case_verification=safety_verification,
        )
        if selected_scope:
            vote_counts = {
                str(row["disposition"]): int(row["count"])
                for row in self.store.connection.execute(
                    """SELECT disposition, COUNT(*) AS count FROM broker_snapshot_votes
                       WHERE visibility_scope_hash=? GROUP BY disposition""",
                    (selected_scope,),
                )
            }
            stable_row = self.store.connection.execute(
                """SELECT consecutive_count FROM broker_snapshot_consensus
                   WHERE visibility_scope_hash=?""",
                (selected_scope,),
            ).fetchone()
            stable_consensus = int(stable_row["consecutive_count"]) if stable_row else 0
            reset = self.store.connection.execute(
                """SELECT equivalence_json FROM broker_snapshot_votes
                   WHERE visibility_scope_hash=? AND disposition='ACCEPTED_DIVERGENT_RESET'
                   ORDER BY recorded_at DESC LIMIT 1""",
                (selected_scope,),
            ).fetchone()
        else:
            vote_counts = {}
            stable_consensus = 0
            reset = None
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
                "scope_hash": selected_scope,
                "scope_policy": observer.get("scope_policy"),
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
                "all_scope_vote_dispositions": all_scope_vote_counts,
                "last_reset_reason": (
                    json.loads(reset["equivalence_json"]).get("explanation")
                    if reset and reset["equivalence_json"]
                    else None
                ),
            },
            "paper_canary_safety_case": {
                "available": safety_case is not None,
                "status": (
                    "VERIFIED"
                    if safety_verification.verified
                    else (str(safety_case["status"]) if safety_case else "NOT_ISSUED")
                ),
                "created_at": safety_case["created_at"] if safety_case else None,
                "safety_case_id": safety_verification.safety_case_id,
                "verified": safety_verification.verified,
                "reasons": list(safety_verification.reasons),
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
        quote_evidence_eligible: bool,
        safety_case_verification: SafetyCaseVerification,
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
        required_heartbeats = {
            "observer": ("broker-observer",),
            "shadow": ("broker-observer", "market-data", "reconciler"),
            "runtime_control": (
                "broker-observer",
                "execution-worker",
                "market-data",
                "reconciler",
            ),
            "paper_canary": (
                "broker-observer",
                "execution-worker",
                "market-data",
                "reconciler",
                "durable-writer",
                "permit-verifier",
            ),
        }

        def required_heartbeat_checks(layer: str) -> dict[str, bool]:
            return {
                f"heartbeat_{component.replace('-', '_')}": heartbeat_checks.get(
                    component, False
                )
                for component in required_heartbeats[layer]
            }

        observer_checks = {
            **observer_checks,
            **required_heartbeat_checks("observer"),
        }
        runtime_control_checks = {
            **observer_checks,
            **authority_checks,
            "market_data_healthy": bool(runtime_status.get("market_data_healthy", False)),
            **required_heartbeat_checks("runtime_control"),
        }
        external_checks = {
            "burn_in_passed": "burn_in_manifest_hash",
            "golden_tapes_passed": "golden_tape_corpus_hash",
            "nightly_reset_passed": "nightly_reset_case_hash",
            "market_calendar_verified": "market_calendar_policy_hash",
            "real_cancel_passed": "cancel_case_hash",
            "real_bracket_passed": "bracket_case_hash",
            "paper_account_verified": "paper_account_proof_hash",
        }
        paper_checks = {
            "runtime_control_ready": all(runtime_control_checks.values()),
            "quote_evidence_eligible": quote_evidence_eligible,
            "quote_intent_binding_verified": False,
            "safety_case_verified": safety_case_verification.verified,
            **required_heartbeat_checks("paper_canary"),
            **{
                name: bool(
                    safety_case_verification.verified
                    and safety_case_verification.evidence_checks.get(evidence_name, False)
                )
                for name, evidence_name in external_checks.items()
            },
            "durable_writer_available": heartbeat_checks.get("durable-writer", False),
            "canary_permit_valid": False,
        }
        return {
            "service": {"ready": all(service_checks.values()), "checks": service_checks},
            "observer": {"ready": all(observer_checks.values()), "checks": observer_checks},
            "authority": {"ready": all(authority_checks.values()), "checks": authority_checks},
            "shadow": {
                "ready": all(authority_checks.values())
                and bool(runtime_status.get("market_data_healthy", False))
                and all(required_heartbeat_checks("shadow").values()),
                "checks": {
                    **authority_checks,
                    "market_data_healthy": bool(runtime_status.get("market_data_healthy", False)),
                    **required_heartbeat_checks("shadow"),
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
                "visibility_scope_hash": certificate.visibility.scope_hash,
                "scope_policy": certificate.visibility.model_dump(
                    mode="json", exclude={"observation_window", "scope_hash"}
                ),
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
