from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from hanalpha.execution.burn_in import verify_burn_in_manifest
from hanalpha.execution.ibkr_observer import (
    IBKRFact,
    IBKRFactReducer,
    IBKRFactStore,
    IBKRFactType,
    IBKRReadModel,
    SnapshotCompletenessCertificate,
)
from hanalpha.ops.artifacts import sha256_file
from hanalpha.simulation.events import canonical_hash

REQUIRED_GOLDEN_SCENARIOS = frozenset(
    {
        "empty_account",
        "static_position",
        "api_limit_cancel",
        "manual_limit_cancel",
        "partial_fill",
        "late_commission",
        "api_completed_order",
        "manual_completed_order",
        "bracket_early_perm_id_zero",
        "order_id_rebind_client_switch",
        "disconnect_reconnect",
        "nightly_reset",
        "execution_correction",
        "fill_cancel_race",
    }
)

REQUIRED_TRANSFORMS = frozenset(
    {
        "callback_reorder",
        "duplicate_callbacks",
        "delayed_commission",
        "delayed_correction",
        "remove_redundant_order_status",
        "open_completed_overlap",
    }
)


def evaluate_golden_tape_corpus(
    session_dirs: Iterable[Path],
    *,
    required_scenarios: frozenset[str] = REQUIRED_GOLDEN_SCENARIOS,
) -> dict[str, Any]:
    tape_reports: list[dict[str, Any]] = []
    reasons: list[str] = []
    scenarios: set[str] = set()
    transform_coverage = {name: 0 for name in REQUIRED_TRANSFORMS}
    for session_dir in sorted(session_dirs):
        verification = verify_burn_in_manifest(session_dir)
        if not verification.verified:
            reasons.append(f"INVALID_SESSION:{session_dir.name}")
            continue
        report = _evaluate_tape(session_dir, verification.manifest)
        tape_reports.append(report)
        scenarios.add(str(report["scenario"]))
        if report["decision"] != "PASS":
            reasons.append(f"TAPE_FAILED:{session_dir.name}")
        for transform in report["transforms"]:
            if transform["applicable"]:
                transform_coverage[str(transform["name"])] += 1
    for scenario in sorted(required_scenarios - scenarios):
        reasons.append(f"GOLDEN_SCENARIO_MISSING:{scenario}")
    for transform, count in sorted(transform_coverage.items()):
        if count == 0:
            reasons.append(f"TRANSFORM_COVERAGE_MISSING:{transform}")
    body: dict[str, Any] = {
        "schema_version": "ibkr-golden-tape-corpus-v1",
        "decision": "PASS" if not reasons else "BLOCKED",
        "required_scenarios": sorted(required_scenarios),
        "observed_scenarios": sorted(scenarios),
        "transform_coverage": transform_coverage,
        "tapes": tape_reports,
        "callback_truth_map": _aggregate_truth_maps(tape_reports),
        "reasons": sorted(set(reasons)),
    }
    return {"artifact_id": canonical_hash(body), **body}


def _evaluate_tape(session_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    store = IBKRFactStore(session_dir / "tape.sqlite3")
    try:
        certificate = store.latest_certificate()
        if certificate is None:
            raise ValueError("golden tape certificate is missing")
        facts = store.facts(certificate.session_id)
    finally:
        store.close()
    baseline = IBKRFactReducer.reduce(facts)
    baseline_hash = _model_hash(baseline)
    transforms = (
        _transform_result("callback_reorder", tuple(reversed(facts)), baseline_hash),
        _transform_result("duplicate_callbacks", facts + facts, baseline_hash),
        _conditional_transform(
            "delayed_commission",
            facts,
            lambda fact: fact.fact_type is IBKRFactType.COMMISSION,
            baseline_hash,
        ),
        _conditional_transform(
            "delayed_correction",
            facts,
            lambda fact: (
                fact.fact_type is IBKRFactType.EXECUTION
                and _execution_revision(str(fact.payload.get("exec_id", ""))) > 1
            ),
            baseline_hash,
        ),
        _redundant_status_transform(facts, baseline_hash),
        _overlap_transform(facts, baseline_hash),
    )
    reasons: list[str] = []
    if baseline.reducer_conflicts:
        reasons.append("REDUCER_CONFLICT")
    reasons.extend(f"TRANSFORM_FAILED:{item['name']}" for item in transforms if not item["passed"])
    return {
        "session_manifest_id": manifest["manifest_id"],
        "session_manifest_sha256": sha256_file(session_dir / "manifest.json"),
        "scenario": manifest.get("capture_scenario"),
        "scope_hash": manifest.get("scope_hash"),
        "account_hash": manifest.get("account_hash"),
        "baseline_model_hash": baseline_hash,
        "fact_count": len(facts),
        "decision": "PASS" if not reasons else "BLOCKED",
        "reasons": sorted(set(reasons)),
        "transforms": transforms,
        "callback_truth_map": _callback_truth_map(certificate, baseline),
    }


def _transform_result(
    name: str,
    facts: tuple[IBKRFact, ...],
    baseline_hash: str,
    *,
    applicable: bool = True,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model_hash = _model_hash(IBKRFactReducer.reduce(facts))
    return {
        "name": name,
        "applicable": applicable,
        "passed": model_hash == baseline_hash,
        "model_hash": model_hash,
        "details": details or {},
    }


def _conditional_transform(
    name: str,
    facts: tuple[IBKRFact, ...],
    predicate: Callable[[IBKRFact], bool],
    baseline_hash: str,
) -> dict[str, Any]:
    selected = tuple(fact for fact in facts if predicate(fact))
    if not selected:
        return {
            "name": name,
            "applicable": False,
            "passed": True,
            "model_hash": baseline_hash,
            "details": {"reason": "NO_RELEVANT_CALLBACK"},
        }
    remainder = tuple(fact for fact in facts if not predicate(fact))
    return _transform_result(
        name,
        remainder + tuple(reversed(selected)),
        baseline_hash,
        details={"delayed_callbacks": len(selected)},
    )


def _redundant_status_transform(facts: tuple[IBKRFact, ...], baseline_hash: str) -> dict[str, Any]:
    removable: list[str] = []
    retained = list(facts)
    for fact in tuple(facts):
        if fact.fact_type is not IBKRFactType.ORDER_STATUS:
            continue
        candidate = tuple(item for item in retained if item.fact_id != fact.fact_id)
        if candidate and _model_hash(IBKRFactReducer.reduce(candidate)) == baseline_hash:
            retained = list(candidate)
            removable.append(fact.fact_id)
    if not removable:
        return {
            "name": "remove_redundant_order_status",
            "applicable": False,
            "passed": True,
            "model_hash": baseline_hash,
            "details": {"reason": "NO_PROVABLY_REDUNDANT_STATUS"},
        }
    return _transform_result(
        "remove_redundant_order_status",
        tuple(retained),
        baseline_hash,
        details={"removed_count": len(removable)},
    )


def _overlap_transform(facts: tuple[IBKRFact, ...], baseline_hash: str) -> dict[str, Any]:
    has_open = any(fact.fact_type is IBKRFactType.OPEN_ORDER for fact in facts)
    has_completed = any(fact.fact_type is IBKRFactType.COMPLETED_ORDER for fact in facts)
    if not (has_open and has_completed):
        return {
            "name": "open_completed_overlap",
            "applicable": False,
            "passed": True,
            "model_hash": baseline_hash,
            "details": {"reason": "OPEN_COMPLETED_OVERLAP_NOT_PRESENT"},
        }
    reordered = tuple(
        sorted(
            facts,
            key=lambda fact: (
                0 if fact.fact_type is IBKRFactType.COMPLETED_ORDER else 1,
                fact.fact_id,
            ),
        )
    )
    return _transform_result("open_completed_overlap", reordered, baseline_hash)


def _callback_truth_map(
    certificate: SnapshotCompletenessCertificate, model: IBKRReadModel
) -> dict[str, str]:
    conflict = bool(model.reducer_conflicts)
    return {
        "cash": "CONFLICTED"
        if conflict
        else ("AUTHORITATIVE" if certificate.cash_snapshot_complete else "PENDING"),
        "buying_power": "CONFLICTED"
        if conflict
        else ("AUTHORITATIVE" if certificate.cash_snapshot_complete else "PENDING"),
        "positions": "CONFLICTED"
        if conflict
        else ("AUTHORITATIVE" if certificate.position_snapshot_complete else "PENDING"),
        "orders": "CONFLICTED"
        if conflict
        else ("AUTHORITATIVE" if certificate.order_snapshot_complete else "PENDING"),
        "executions": "CONFLICTED"
        if conflict
        else ("AUTHORITATIVE" if certificate.execution_snapshot_complete else "PENDING"),
        "commissions": (
            "CONFLICTED"
            if conflict
            else ("PENDING" if certificate.executions_missing_commission_count else "AUTHORITATIVE")
        ),
        "protections": "CONFLICTED" if conflict else "DERIVED",
        "market_quotes": "UNAVAILABLE",
        "exchange_calendar": "UNAVAILABLE",
    }


def _aggregate_truth_maps(tape_reports: list[dict[str, Any]]) -> dict[str, Any]:
    fields = sorted(
        {field for report in tape_reports for field in report.get("callback_truth_map", {})}
    )
    return {
        field: {
            "observed_classifications": sorted(
                {
                    str(report["callback_truth_map"][field])
                    for report in tape_reports
                    if field in report.get("callback_truth_map", {})
                }
            )
        }
        for field in fields
    }


def _model_hash(model: IBKRReadModel) -> str:
    return canonical_hash(model.model_dump(mode="json"))


def _execution_revision(exec_id: str) -> int:
    try:
        return int(exec_id.rsplit(".", 1)[1])
    except (IndexError, ValueError):
        return 1
