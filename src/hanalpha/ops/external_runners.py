from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from hanalpha.config import SecretSettings
from hanalpha.execution.burn_in import verify_burn_in_manifest
from hanalpha.execution.e1_scenarios import (
    E1_ACCEPTANCE_POLICIES,
    E1EventReceipt,
    E1ScopeName,
    allocate_scenario_cases,
    load_scenario_cases,
)
from hanalpha.ops.artifact_registry import ArtifactRegistry, ArtifactType
from hanalpha.ops.artifacts import write_immutable_json
from hanalpha.ops.onboarding import OperatorStatus
from hanalpha.pit.source_audit import audit_probe_manifest
from hanalpha.pit.source_probe import ProbeSource, run_bounded_source_probe
from hanalpha.simulation.events import canonical_hash


class E1Scope(StrEnum):
    API = "api"
    ALL = "all"


E1_SCENARIOS: dict[E1Scope, tuple[tuple[str, int], ...]] = {
    scope: tuple(E1_ACCEPTANCE_POLICIES[E1ScopeName(scope.value)].session_requirements.items())
    for scope in E1Scope
}
E1_SCENARIO_CASES: dict[E1Scope, tuple[tuple[str, int], ...]] = {
    scope: tuple(
        E1_ACCEPTANCE_POLICIES[E1ScopeName(scope.value)].scenario_case_requirements.items()
    )
    for scope in E1Scope
}

R1_SAMPLES: dict[ProbeSource, tuple[str, ...]] = {
    ProbeSource.SEC_EDGAR: ("320193", "789019"),
    ProbeSource.FRED_ALFRED: ("CPIAUCSL", "PAYEMS", "GDP", "RSAFS", "INDPRO"),
    ProbeSource.MASSIVE: ("AAPL",),
}


def e1_progress(output_root: Path, scope: E1Scope) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    invalid_sessions = 0
    verified_manifests: list[dict[str, Any]] = []
    sessions_root = output_root / "sessions"
    for session_dir in sorted(sessions_root.iterdir()) if sessions_root.is_dir() else ():
        if not session_dir.is_dir():
            continue
        verification = verify_burn_in_manifest(session_dir)
        if not verification.verified or not verification.manifest.get("safety_case_eligible"):
            invalid_sessions += 1
            continue
        completed_orders_scope = verification.manifest.get("completed_orders_scope")
        if completed_orders_scope is None:
            api_only = verification.manifest.get("completed_orders_api_only")
            completed_orders_scope = (
                "api" if api_only is True else "all" if api_only is False else None
            )
        if completed_orders_scope != scope.value:
            invalid_sessions += 1
            continue
        verified_manifests.append(verification.manifest)
        counts[str(verification.manifest.get("capture_scenario"))] += 1
    session_required = dict(E1_SCENARIOS[scope])
    session_missing = {
        scenario: max(0, target - counts.get(scenario, 0))
        for scenario, target in session_required.items()
    }
    case_paths = tuple((output_root / "cases").glob("*.json"))
    invalid_cases = 0
    try:
        cases = load_scenario_cases(case_paths)
    except (OSError, ValueError):
        cases = ()
        invalid_cases = len(case_paths)
    binding_fields = (
        "account_identity_hash",
        "git_commit",
        "config_hash",
        "normalization_policy_hash",
    )
    accepted_cases = tuple(
        case
        for case in cases
        if all(
            {str(item.get(field)) for item in verified_manifests} == {str(getattr(case, field))}
            for field in binding_fields
        )
    )
    invalid_cases += len(cases) - len(accepted_cases)
    scope_manifest_ids = {
        str(item.get("manifest_id"))
        for item in verified_manifests
        if item.get("capture_scenario") != "client_id_switch"
    }
    cross_scope_manifest_ids = {
        str(item.get("manifest_id"))
        for item in verified_manifests
        if item.get("capture_scenario") == "client_id_switch"
    }
    available_receipt_ids: set[str] = set()
    for receipt_path in (output_root / "receipts").glob("*.json"):
        try:
            receipt = E1EventReceipt.model_validate_json(
                receipt_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            continue
        available_receipt_ids.add(receipt.artifact_id)
    case_counts, allocation_rejections = allocate_scenario_cases(
        accepted_cases,
        scope=E1ScopeName(scope.value),
        at=datetime.now(UTC),
        corpus_manifest_ids=scope_manifest_ids,
        cross_scope_manifest_ids=cross_scope_manifest_ids,
        available_receipt_ids=available_receipt_ids,
    )
    invalid_cases += len(allocation_rejections)
    case_required = dict(E1_SCENARIO_CASES[scope])
    case_missing = {
        scenario: max(0, target - case_counts.get(scenario, 0))
        for scenario, target in case_required.items()
    }
    next_session = next(
        (scenario for scenario, _ in E1_SCENARIOS[scope] if session_missing[scenario] > 0),
        None,
    )
    next_case = next(
        (scenario for scenario, _ in E1_SCENARIO_CASES[scope] if case_missing[scenario] > 0),
        None,
    )
    next_scenario = next_session or next_case
    next_action_kind = (
        "SESSION_CAPTURE"
        if next_session is not None
        else "SCENARIO_CASE"
        if next_case is not None
        else None
    )
    body = {
        "schema_version": "e1-external-runner-progress-v2",
        "scope": scope,
        "status": OperatorStatus.PASS
        if next_scenario is None
        else OperatorStatus.BLOCKED_HUMAN_ACTION,
        "verified_counts": dict(sorted(counts.items())),
        "required_counts": session_required,
        "missing_counts": session_missing,
        "verified_case_counts": dict(sorted(case_counts.items())),
        "required_case_counts": case_required,
        "missing_case_counts": case_missing,
        "invalid_session_count": invalid_sessions,
        "invalid_case_count": invalid_cases,
        "case_allocation_rejections": {
            case_id: list(reasons)
            for case_id, reasons in sorted(allocation_rejections.items())
        },
        "next_scenario": next_scenario,
        "next_action_kind": next_action_kind,
        "next_human_action": _scenario_action(
            next_scenario,
            scope,
            action_kind=next_action_kind,
        ),
        "secrets_redacted": True,
    }
    return {"report_id": canonical_hash(body), **body}


async def run_r1_source(
    source: ProbeSource,
    *,
    output_root: Path,
    registry: ArtifactRegistry,
    secrets: SecretSettings,
    at: datetime,
    execute: bool,
) -> dict[str, Any]:
    missing_secret = {
        ProbeSource.SEC_EDGAR: not bool(secrets.sec_user_agent),
        ProbeSource.FRED_ALFRED: not bool(secrets.fred_api_key),
        ProbeSource.MASSIVE: not bool(secrets.massive_api_key or secrets.polygon_api_key),
    }[source]
    if missing_secret:
        return _r1_report(
            source,
            status=OperatorStatus.BLOCKED_HUMAN_ACTION,
            reason="STORE_REQUIRED_LOCAL_SECRET",
            artifact_ids=(),
            at=at,
        )
    if not execute:
        return _r1_report(
            source,
            status=OperatorStatus.BLOCKED_HUMAN_ACTION,
            reason="REAL_PROBE_REQUIRES_EXPLICIT_EXECUTE",
            artifact_ids=(),
            at=at,
        )
    source_root = output_root / source.value / at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    manifest_path, _ = await run_bounded_source_probe(
        source,
        R1_SAMPLES[source],
        output_root=source_root,
        secrets=secrets,
        at=at,
    )
    artifact_ids: list[str] = [
        registry.register(
            manifest_path,
            artifact_type=ArtifactType.RAW_SAMPLE_MANIFEST,
            status="VERIFIED",
            at=at,
        )
    ]
    for path, artifact_type, document in audit_probe_manifest(
        manifest_path, output_root=source_root / "audits"
    ):
        artifact_ids.append(
            registry.register(
                path,
                artifact_type=artifact_type,
                status="VERIFIED" if document["decision"] == "PASS" else "REJECTED",
                at=at,
            )
        )
    bundle_body = {
        "schema_version": "pit-reviewer-bundle-v1",
        "source_id": source.value,
        "created_at": at.astimezone(UTC).isoformat(),
        "evidence_artifact_ids": sorted(artifact_ids),
        "contains_secrets": False,
        "limitations": [
            "This bundle is unsigned and cannot replace independent review.",
            "License, cache, retention and backtest rights require written evidence.",
        ],
    }
    bundle = {"bundle_id": canonical_hash(bundle_body), **bundle_body}
    write_immutable_json(source_root / f"{bundle['bundle_id']}.reviewer-bundle.json", bundle)
    return _r1_report(
        source,
        status=OperatorStatus.BLOCKED_EXTERNAL_RIGHTS,
        reason="INDEPENDENT_RIGHTS_AND_REVIEW_REQUIRED",
        artifact_ids=tuple(artifact_ids),
        at=at,
        reviewer_bundle_id=str(bundle["bundle_id"]),
    )


def runner_github_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        (
            f"status={report['status']}",
            f"report={str(report['report_id'])[:12]}",
            f"scope_or_source={report.get('scope') or report.get('source_id')}",
            f"next={report.get('next_scenario') or report.get('reason') or 'none'}",
            f"artifacts={len(report.get('artifact_ids', []))}",
            "secrets_redacted=true",
        )
    )


def _r1_report(
    source: ProbeSource,
    *,
    status: OperatorStatus,
    reason: str,
    artifact_ids: tuple[str, ...],
    at: datetime,
    reviewer_bundle_id: str | None = None,
) -> dict[str, Any]:
    body = {
        "schema_version": "r1-external-runner-progress-v1",
        "source_id": source.value,
        "status": status,
        "reason": reason,
        "artifact_ids": sorted(artifact_ids),
        "reviewer_bundle_id": reviewer_bundle_id,
        "created_at": at.astimezone(UTC).isoformat(),
        "qualification": "BLOCKED",
        "secrets_redacted": True,
    }
    return {"report_id": canonical_hash(body), **body}


def _scenario_action(
    scenario: str | None,
    scope: E1Scope,
    *,
    action_kind: str | None = None,
) -> str | None:
    if scenario is None:
        return None
    if action_kind == "SCENARIO_CASE":
        return f"BUILD_VERIFIED_{scenario.upper()}_SCENARIO_CASE"
    if scenario in {"tws_restart", "network_recovery", "nightly_reset"}:
        return f"PERFORM_BOUNDED_{scenario.upper()}_WINDOW"
    if scenario in {"api_order", "manual_order"}:
        return (
            "ATTEST_ORDER_VISIBILITY_MODE_AND_CREATE_BOUNDED_PAPER_EVENT"
            if scope is E1Scope.ALL
            else "CREATE_BOUNDED_EVENT_WITH_SEPARATE_TEST_CLIENT"
        )
    return f"CAPTURE_{scenario.upper()}"
