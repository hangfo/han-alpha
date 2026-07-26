from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from hanalpha.execution.control_models import BrokerSnapshot
from hanalpha.execution.ibkr_observer import (
    IBKRFactStore,
    SnapshotCompletenessCertificate,
    broker_account_identity,
)
from hanalpha.ops.artifacts import sha256_file, write_immutable_json
from hanalpha.simulation.events import canonical_hash


class BurnInManifestVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    verified: bool
    reasons: tuple[str, ...]
    manifest_id: str | None
    manifest: dict[str, Any]


class BurnInCorpusEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: str
    reasons: tuple[str, ...]
    corpus: dict[str, Any]


def persist_burn_in_session(
    *,
    source_store: IBKRFactStore,
    certificate: SnapshotCompletenessCertificate,
    snapshot: BrokerSnapshot,
    output_root: Path,
    git_commit: str | None,
    config_hash: str,
    client_id: int,
    paper_port: int,
    reconciliation_status: str,
    tws_server_version: int | None = None,
    ibapi_version: str | None = None,
    vote_disposition: str | None = None,
    consensus_count_after_vote: int = 0,
    equivalence_receipt: dict[str, Any] | None = None,
    authority_promoted: bool = False,
    capture_scenario: str = "repeated_connection",
    environment: str = "paper",
    broker_host: str = "127.0.0.1",
    process_boot_id: str | None = None,
) -> Path:
    """Export one Observer session and its self-verifying immutable manifest."""

    sessions_root = output_root / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)
    session_dir = sessions_root / str(snapshot.observation_id)
    if session_dir.exists():
        verification = verify_burn_in_manifest(session_dir)
        if not verification.verified:
            raise RuntimeError(
                "existing burn-in session failed manifest validation: "
                + ",".join(verification.reasons)
            )
        expected = _build_manifest(
            certificate=certificate,
            snapshot=snapshot,
            git_commit=git_commit,
            config_hash=config_hash,
            client_id=client_id,
            paper_port=paper_port,
            reconciliation_status=reconciliation_status,
            tws_server_version=tws_server_version,
            ibapi_version=ibapi_version,
            vote_disposition=vote_disposition,
            consensus_count_after_vote=consensus_count_after_vote,
            equivalence_receipt=equivalence_receipt,
            authority_promoted=authority_promoted,
            capture_scenario=capture_scenario,
            environment=environment,
            broker_host=broker_host,
            process_boot_id=process_boot_id,
            tape_hash=str(verification.manifest["files"]["tape.sqlite3"]),
            certificate_hash=str(verification.manifest["files"]["certificate.json"]),
        )
        if verification.manifest != expected:
            raise RuntimeError("existing burn-in session manifest differs from current capture")
        return session_dir
    staging = sessions_root / f".{snapshot.observation_id}.pending"
    if staging.exists():
        raise RuntimeError("incomplete burn-in staging directory requires inspection")
    tape_path = staging / "tape.sqlite3"
    source_store.export_session(certificate.session_id, tape_path)
    certificate_path = staging / "certificate.json"
    write_immutable_json(certificate_path, certificate.model_dump(mode="json"))
    manifest = _build_manifest(
        certificate=certificate,
        snapshot=snapshot,
        git_commit=git_commit,
        config_hash=config_hash,
        client_id=client_id,
        paper_port=paper_port,
        reconciliation_status=reconciliation_status,
        tws_server_version=tws_server_version,
        ibapi_version=ibapi_version,
        vote_disposition=vote_disposition,
        consensus_count_after_vote=consensus_count_after_vote,
        equivalence_receipt=equivalence_receipt,
        authority_promoted=authority_promoted,
        capture_scenario=capture_scenario,
        environment=environment,
        broker_host=broker_host,
        process_boot_id=process_boot_id,
        tape_hash=sha256_file(tape_path),
        certificate_hash=sha256_file(certificate_path),
    )
    write_immutable_json(staging / "manifest.json", manifest)
    verification = verify_burn_in_manifest(staging)
    if not verification.verified:
        raise RuntimeError("new burn-in session failed self-verification")
    os.replace(staging, session_dir)
    descriptor = os.open(sessions_root, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return session_dir


def verify_burn_in_manifest(session_dir: Path) -> BurnInManifestVerification:
    reasons: list[str] = []
    manifest_path = session_dir / "manifest.json"
    if not manifest_path.is_file():
        return BurnInManifestVerification(
            verified=False,
            reasons=("MANIFEST_MISSING",),
            manifest_id=None,
            manifest={},
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return BurnInManifestVerification(
            verified=False,
            reasons=("MANIFEST_INVALID_JSON",),
            manifest_id=None,
            manifest={},
        )
    claimed_id = manifest.get("manifest_id")
    body = {key: value for key, value in manifest.items() if key != "manifest_id"}
    if claimed_id != canonical_hash(body):
        reasons.append("MANIFEST_ID_MISMATCH")
    if manifest.get("schema_version") != "ibkr-burn-in-session-v2":
        reasons.append("SCHEMA_VERSION_UNSUPPORTED")
    identity_document = manifest.get("account_identity")
    if not isinstance(identity_document, dict):
        reasons.append("ACCOUNT_IDENTITY_MISSING")
    else:
        try:
            expected_identity = broker_account_identity(
                account_hash_value=str(manifest.get("account_hash", "")),
                environment=str(manifest.get("environment", "")),
                host=str(manifest.get("broker_host", "")),
                port=int(manifest.get("paper_port", 0)),
            )
            if identity_document != expected_identity.model_dump():
                reasons.append("ACCOUNT_IDENTITY_MISMATCH")
            if manifest.get("account_identity_hash") != expected_identity.identity_hash:
                reasons.append("ACCOUNT_IDENTITY_HASH_MISMATCH")
        except (TypeError, ValueError):
            reasons.append("ACCOUNT_IDENTITY_INVALID")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != {
        "tape.sqlite3",
        "certificate.json",
    }:
        reasons.append("REQUIRED_FILES_INVALID")
        files = {}
    for name, expected in files.items():
        artifact = session_dir / str(name)
        if not artifact.is_file():
            reasons.append(f"{str(name).upper().replace('.', '_')}_MISSING")
        elif sha256_file(artifact) != expected:
            reasons.append(f"{str(name).upper().replace('.', '_')}_HASH_MISMATCH")
    certificate_path = session_dir / "certificate.json"
    tape_path = session_dir / "tape.sqlite3"
    if not certificate_path.is_file():
        reasons.append("CERTIFICATE_JSON_MISSING")
    if not tape_path.is_file():
        reasons.append("TAPE_SQLITE3_MISSING")
    certificate: SnapshotCompletenessCertificate | None = None
    if certificate_path.is_file():
        try:
            certificate = SnapshotCompletenessCertificate.model_validate_json(
                certificate_path.read_text(encoding="utf-8")
            )
        except ValueError:
            reasons.append("CERTIFICATE_SCHEMA_INVALID")
    if certificate is not None:
        expected_pairs = {
            "certificate_id": certificate.certificate_id,
            "scope_hash": certificate.visibility.scope_hash,
            "account_hash": certificate.account_hash,
            "normalization_policy_hash": certificate.normalization_policy_hash,
            "semantic_hash": certificate.semantic_hash,
            "final_watermark": certificate.final_watermark,
        }
        for name, expected in expected_pairs.items():
            if manifest.get(name) != expected:
                reasons.append(f"{name.upper()}_MISMATCH")
        if tape_path.is_file():
            try:
                tape = IBKRFactStore(tape_path)
                try:
                    tape_certificate = tape.latest_certificate()
                    sessions = tape.connection.execute(
                        "SELECT session_id FROM ibkr_sessions"
                    ).fetchall()
                finally:
                    tape.close()
                if tape_certificate != certificate:
                    reasons.append("TAPE_CERTIFICATE_MISMATCH")
                if len(sessions) != 1 or sessions[0]["session_id"] != certificate.session_id:
                    reasons.append("TAPE_SESSION_SCOPE_MISMATCH")
            except (OSError, ValueError):
                reasons.append("TAPE_INVALID")
    observation_id = manifest.get("observation_id")
    if not isinstance(observation_id, str) or session_dir.name not in {
        observation_id,
        f".{observation_id}.pending",
    }:
        reasons.append("OBSERVATION_DIRECTORY_MISMATCH")
    return BurnInManifestVerification(
        verified=not reasons,
        reasons=tuple(sorted(set(reasons))),
        manifest_id=str(claimed_id) if claimed_id else None,
        manifest=manifest,
    )


def evaluate_burn_in_corpus(
    session_dirs: Iterable[Path],
    *,
    scenario_case_paths: Iterable[Path] = (),
    minimum_sessions: int | None = None,
    required_coverage: dict[str, int] | None = None,
    required_case_coverage: dict[str, int] | None = None,
) -> BurnInCorpusEvaluation:
    from hanalpha.execution.e1_scenarios import (
        E1_ACCEPTANCE_POLICIES,
        E1ScopeName,
        load_scenario_cases,
        scenario_case_counts,
    )

    paths = tuple(sorted(session_dirs))
    manifests: list[dict[str, Any]] = []
    reasons: list[str] = []
    for session_dir in paths:
        verification = verify_burn_in_manifest(session_dir)
        if not verification.verified:
            reasons.append(f"INVALID_SESSION:{session_dir.name}")
            continue
        manifests.append(verification.manifest)
    cross_scope_manifests = [
        item for item in manifests if item.get("capture_scenario") == "client_id_switch"
    ]
    scope_manifests = [
        item for item in manifests if item.get("capture_scenario") != "client_id_switch"
    ]
    api_only_values = {
        item.get("completed_orders_scope") == "api"
        if item.get("completed_orders_scope") in {"api", "all"}
        else item.get("completed_orders_api_only")
        for item in scope_manifests
    }
    api_only = next(iter(api_only_values)) if len(api_only_values) == 1 else None
    if len(api_only_values) > 1:
        reasons.append("MIXED_COMPLETED_ORDERS_SCOPE")
    scope = E1ScopeName.API if api_only is True else E1ScopeName.ALL
    policy = E1_ACCEPTANCE_POLICIES[scope]
    threshold = minimum_sessions if minimum_sessions is not None else policy.minimum_scope_sessions
    coverage_requirements = (
        required_coverage if required_coverage is not None else policy.session_requirements
    )
    case_coverage_requirements = (
        required_case_coverage
        if required_case_coverage is not None
        else {}
        if required_coverage is not None
        else policy.scenario_case_requirements
    )
    if len(scope_manifests) < threshold:
        reasons.append("INSUFFICIENT_ELIGIBLE_SESSIONS")
    if (
        minimum_sessions is None
        and len(cross_scope_manifests) < policy.minimum_cross_scope_sessions
    ):
        reasons.append("INSUFFICIENT_CROSS_SCOPE_SESSIONS")
    binding_fields = (
        "account_hash",
        "git_commit",
        "config_hash",
        "normalization_policy_hash",
        "account_identity_hash",
    )
    bindings: dict[str, list[str]] = {
        field: sorted({str(item.get(field)) for item in scope_manifests})
        for field in binding_fields
    }
    bindings["scope_hash"] = sorted({_scope_compatibility_hash(item) for item in scope_manifests})
    raw_scope_hashes = sorted({str(item.get("scope_hash")) for item in scope_manifests})
    for field, values in bindings.items():
        if len(values) != 1 or values == ["None"]:
            reasons.append(f"MIXED_OR_MISSING_{field.upper()}")
    eligible = [item for item in manifests if item.get("safety_case_eligible") is True]
    if len(eligible) != len(manifests):
        reasons.append("SESSION_NOT_SAFETY_CASE_ELIGIBLE")
    fact_drops = sum(int(item.get("dropped_facts", 0)) for item in manifests)
    writer_errors = sum(1 for item in manifests if item.get("writer_error"))
    reconciliation_failures = sum(
        1 for item in manifests if item.get("reconciliation_result") != "CONVERGED"
    )
    divergent_resets = sum(
        1 for item in manifests if item.get("vote_disposition") == "ACCEPTED_DIVERGENT_RESET"
    )
    maximum_consensus_count = max(
        (int(item.get("consensus_count_after_vote", 0)) for item in manifests),
        default=0,
    )
    if fact_drops:
        reasons.append("FACT_DROPS_PRESENT")
    if writer_errors:
        reasons.append("WRITER_ERRORS_PRESENT")
    if reconciliation_failures:
        reasons.append("RECONCILIATION_FAILURES_PRESENT")
    coverage_counts = {
        scenario: sum(1 for item in manifests if item.get("capture_scenario") == scenario)
        for scenario in coverage_requirements
    }
    for scenario, required_count in coverage_requirements.items():
        if coverage_counts[scenario] < required_count:
            reasons.append(f"COVERAGE_MISSING:{scenario}")
    try:
        scenario_cases = load_scenario_cases(scenario_case_paths)
    except (OSError, ValueError):
        scenario_cases = ()
        reasons.append("SCENARIO_CASE_INVALID")
    expected_bindings = {
        "account_identity_hash": bindings["account_identity_hash"][0]
        if len(bindings["account_identity_hash"]) == 1
        else None,
        "git_commit": bindings["git_commit"][0] if len(bindings["git_commit"]) == 1 else None,
        "config_hash": bindings["config_hash"][0] if len(bindings["config_hash"]) == 1 else None,
        "normalization_policy_hash": bindings["normalization_policy_hash"][0]
        if len(bindings["normalization_policy_hash"]) == 1
        else None,
    }
    valid_cases = []
    for case in scenario_cases:
        mismatched = any(
            expected is not None and str(getattr(case, field)) != expected
            for field, expected in expected_bindings.items()
        )
        if mismatched:
            reasons.append(f"SCENARIO_CASE_BINDING_MISMATCH:{case.artifact_id}")
            continue
        valid_cases.append(case)
    valid_case_counts = scenario_case_counts(
        valid_cases,
        scope=scope,
        at=datetime.now(UTC),
    )
    for scenario, required_count in case_coverage_requirements.items():
        if valid_case_counts[scenario] < required_count:
            reasons.append(f"SCENARIO_CASE_MISSING:{scenario}")
    tws_versions = sorted({str(item.get("tws_server_version")) for item in manifests})
    ibapi_versions = sorted({str(item.get("ibapi_version")) for item in manifests})
    if len(tws_versions) > 1:
        reasons.append("MIXED_TWS_VERSION_WITHOUT_COMPATIBILITY_CASE")
    if len(ibapi_versions) > 1:
        reasons.append("MIXED_IBAPI_VERSION_WITHOUT_COMPATIBILITY_CASE")
    per_state_stability = {
        scenario: {
            "required_sessions": required_count,
            "observed_sessions": coverage_counts[scenario],
            "scenario_case_passed": valid_case_counts[scenario] > 0,
        }
        for scenario, required_count in coverage_requirements.items()
    }
    expected_transitions = {
        item.scenario_type.value: item.expected_transition for item in valid_cases
    }
    observed_transitions = {
        item.scenario_type.value: item.observed_transition for item in valid_cases
    }
    unexplained_divergences = sum(1 for item in scenario_cases if item.decision != "PASS")
    manifest_hashes = [
        sha256_file(path / "manifest.json") for path in paths if (path / "manifest.json").is_file()
    ]
    body: dict[str, Any] = {
        "schema_version": "ibkr-burn-in-corpus-v1",
        "decision": "PASS" if not reasons else "BLOCKED",
        "bindings": bindings,
        "raw_scope_hashes": raw_scope_hashes,
        "sessions_total": len(manifests),
        "scope_child_sessions": len(scope_manifests),
        "cross_scope_child_sessions": len(cross_scope_manifests),
        "sessions_complete": sum(1 for item in manifests if item.get("complete")),
        "sessions_eligible": len(eligible),
        "minimum_sessions": threshold,
        "minimum_total_sessions": policy.minimum_unique_sessions,
        "minimum_cross_scope_sessions": policy.minimum_cross_scope_sessions,
        "maximum_same_state_consensus": maximum_consensus_count,
        "per_state_stability": per_state_stability,
        "divergent_resets": divergent_resets,
        "fact_drops": fact_drops,
        "writer_errors": writer_errors,
        "reconciliation_failures": reconciliation_failures,
        "capture_scenarios": sorted({str(item.get("capture_scenario")) for item in manifests}),
        "coverage_requirements": coverage_requirements,
        "coverage_counts": coverage_counts,
        "scenario_case_requirements": case_coverage_requirements,
        "scenario_case_counts": dict(sorted(valid_case_counts.items())),
        "scenario_case_artifact_ids": sorted(item.artifact_id for item in valid_cases),
        "expected_transitions": expected_transitions,
        "observed_transitions": observed_transitions,
        "unexplained_divergences": unexplained_divergences,
        "tws_versions": tws_versions,
        "ibapi_versions": ibapi_versions,
        "first_observed_at": min((str(item.get("started_at")) for item in manifests), default=None),
        "last_observed_at": max(
            (str(item.get("completed_at")) for item in manifests), default=None
        ),
        "session_manifest_hashes": manifest_hashes,
        "reasons": sorted(set(reasons)),
    }
    return BurnInCorpusEvaluation(
        decision=str(body["decision"]),
        reasons=tuple(body["reasons"]),
        corpus={"corpus_id": canonical_hash(body), **body},
    )


def _scope_compatibility_hash(manifest: dict[str, Any]) -> str:
    """Normalize legacy/new visibility fields without mutating old evidence."""

    policy = manifest.get("scope_policy")
    if not isinstance(policy, dict):
        return str(manifest.get("scope_hash"))
    open_order_query = str(policy.get("open_order_query", "UNDECLARED"))
    body = {
        "configured_account_hash": policy.get("configured_account_hash"),
        "client_id": policy.get("client_id"),
        "master_client": policy.get("master_client"),
        "current_all_open_orders_snapshot_requested": policy.get(
            "current_all_open_orders_snapshot_requested",
            open_order_query in {"ALL_OPEN_ORDERS", "reqAllOpenOrders"},
        ),
        "future_manual_order_updates_bound": policy.get(
            "future_manual_order_updates_bound",
            policy.get("manual_tws_orders_visible", False),
        ),
        "future_other_api_order_updates_visible": policy.get(
            "future_other_api_order_updates_visible",
            policy.get("other_api_clients_visible", False),
        ),
        "execution_query_scope": policy.get("execution_query_scope"),
        "open_order_query": open_order_query,
        "completed_orders_requested": policy.get("completed_orders_requested"),
        "completed_orders_api_only": policy.get("completed_orders_api_only"),
        "completed_order_date_scope": policy.get("completed_order_date_scope"),
        "base_currency": policy.get("base_currency"),
    }
    return canonical_hash(body)


def _build_manifest(
    *,
    certificate: SnapshotCompletenessCertificate,
    snapshot: BrokerSnapshot,
    git_commit: str | None,
    config_hash: str,
    client_id: int,
    paper_port: int,
    reconciliation_status: str,
    tws_server_version: int | None,
    ibapi_version: str | None,
    vote_disposition: str | None,
    consensus_count_after_vote: int,
    equivalence_receipt: dict[str, Any] | None,
    authority_promoted: bool,
    capture_scenario: str,
    environment: str,
    broker_host: str,
    process_boot_id: str | None,
    tape_hash: str,
    certificate_hash: str,
) -> dict[str, Any]:
    ineligibility_reasons: list[str] = []
    required = {
        "GIT_COMMIT_MISSING": git_commit,
        "TWS_SERVER_VERSION_MISSING": tws_server_version,
        "IBAPI_VERSION_MISSING": ibapi_version,
        "VOTE_DISPOSITION_MISSING": vote_disposition,
    }
    ineligibility_reasons.extend(name for name, value in required.items() if value is None)
    if not certificate.complete:
        ineligibility_reasons.append("CERTIFICATE_INCOMPLETE")
    if certificate.dropped_facts:
        ineligibility_reasons.append("FACT_DROP_DETECTED")
    if certificate.writer_error:
        ineligibility_reasons.append("WRITER_ERROR_DETECTED")
    if reconciliation_status != "CONVERGED":
        ineligibility_reasons.append("RECONCILIATION_BLOCKED")
    if capture_scenario == "empty_account" and (snapshot.positions or snapshot.orders):
        ineligibility_reasons.append("SCENARIO_EMPTY_ACCOUNT_HAS_BROKER_STATE")
    if capture_scenario == "static_position" and not snapshot.positions:
        ineligibility_reasons.append("SCENARIO_STATIC_POSITION_MISSING_POSITION")
    if capture_scenario in {"api_order", "manual_order"} and not snapshot.orders:
        ineligibility_reasons.append("SCENARIO_ORDER_MISSING_ORDER")
    equivalence_receipt_hash = (
        canonical_hash(equivalence_receipt) if equivalence_receipt is not None else None
    )
    identity = broker_account_identity(
        account_hash_value=certificate.account_hash,
        environment=environment,
        host=broker_host,
        port=paper_port,
    )
    body: dict[str, Any] = {
        "schema_version": "ibkr-burn-in-session-v2",
        "observation_id": snapshot.observation_id,
        "certificate_id": certificate.certificate_id,
        "git_commit": git_commit,
        "config_hash": config_hash,
        "normalization_policy_hash": certificate.normalization_policy_hash,
        "account_hash": certificate.account_hash,
        "account_identity": identity.model_dump(),
        "account_identity_hash": identity.identity_hash,
        "environment": environment.strip().lower(),
        "broker_host": broker_host.strip().lower(),
        "client_id": client_id,
        "paper_port": paper_port,
        "tws_server_version": tws_server_version,
        "ibapi_version": ibapi_version,
        "scope_hash": certificate.visibility.scope_hash,
        "scope_policy": certificate.visibility.model_dump(
            mode="json", exclude={"observation_window", "scope_hash"}
        ),
        "completed_orders_api_only": certificate.visibility.completed_orders_api_only,
        "completed_orders_scope": (
            "api" if certificate.visibility.completed_orders_api_only else "all"
        ),
        "capture_scenario": capture_scenario,
        "scenario_observation": {
            "order_count": len(snapshot.orders),
            "position_count": len(snapshot.positions),
            "event_count": len(snapshot.events),
        },
        "started_at": (
            certificate.visibility.observation_window.execution_history_end.isoformat()
            if certificate.visibility.observation_window
            else None
        ),
        "completed_at": certificate.as_of.isoformat(),
        "accepted_facts": certificate.accepted_facts,
        "written_facts": certificate.written_facts,
        "dropped_facts": certificate.dropped_facts,
        "writer_error": certificate.writer_error,
        "final_watermark": certificate.final_watermark,
        "semantic_hash": certificate.semantic_hash,
        "orders_hash": certificate.orders_hash,
        "positions_hash": certificate.positions_hash,
        "executions_hash": certificate.executions_hash,
        "commissions_hash": certificate.commissions_hash,
        "protection_hash": certificate.protection_hash,
        "valuation_fields": certificate.valuation_fields,
        "reconciliation_result": reconciliation_status,
        "complete": certificate.complete,
        "vote_disposition": vote_disposition,
        "consensus_count_after_vote": consensus_count_after_vote,
        "equivalence_receipt": equivalence_receipt,
        "equivalence_receipt_hash": equivalence_receipt_hash,
        "authority_candidate_status": (
            "ELIGIBLE"
            if vote_disposition and vote_disposition.startswith("ACCEPTED")
            else "REJECTED"
        ),
        "authority_promoted": authority_promoted,
        "capture_complete": True,
        "safety_case_eligible": not ineligibility_reasons,
        "ineligibility_reasons": sorted(set(ineligibility_reasons)),
        "files": {
            "tape.sqlite3": tape_hash,
            "certificate.json": certificate_hash,
        },
    }
    if process_boot_id is not None:
        body["process_boot_id"] = process_boot_id
    return {"manifest_id": canonical_hash(body), **body}
