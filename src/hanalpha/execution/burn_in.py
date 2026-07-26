from __future__ import annotations

import json
import os
from collections.abc import Iterable
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


API_SCOPE_COVERAGE = {
    "empty_account": 5,
    "static_position": 5,
    "api_order": 4,
    "process_restart": 3,
    "tws_restart": 2,
    "network_recovery": 2,
    "nightly_reset": 1,
    "client_id_switch": 2,
}
ALL_SCOPE_COVERAGE = {
    "manual_order": 4,
    "process_restart": 2,
    "tws_restart": 2,
    "network_recovery": 1,
    "client_id_switch": 1,
}


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
    minimum_sessions: int | None = None,
    required_coverage: dict[str, int] | None = None,
) -> BurnInCorpusEvaluation:
    paths = tuple(sorted(session_dirs))
    manifests: list[dict[str, Any]] = []
    reasons: list[str] = []
    for session_dir in paths:
        verification = verify_burn_in_manifest(session_dir)
        if not verification.verified:
            reasons.append(f"INVALID_SESSION:{session_dir.name}")
            continue
        manifests.append(verification.manifest)
    api_only_values = {item.get("completed_orders_api_only") for item in manifests}
    api_only = next(iter(api_only_values)) if len(api_only_values) == 1 else None
    if len(api_only_values) > 1:
        reasons.append("MIXED_COMPLETED_ORDERS_SCOPE")
    threshold = minimum_sessions if minimum_sessions is not None else (30 if api_only else 10)
    coverage_requirements = required_coverage or (
        API_SCOPE_COVERAGE if api_only is True else ALL_SCOPE_COVERAGE
    )
    if len(manifests) < threshold:
        reasons.append("INSUFFICIENT_ELIGIBLE_SESSIONS")
    binding_fields = (
        "scope_hash",
        "account_hash",
        "git_commit",
        "config_hash",
        "normalization_policy_hash",
        "account_identity_hash",
    )
    bindings = {
        field: sorted({str(item.get(field)) for item in manifests}) for field in binding_fields
    }
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
    consecutive_stable = max(
        (int(item.get("consensus_count_after_vote", 0)) for item in manifests),
        default=0,
    )
    if fact_drops:
        reasons.append("FACT_DROPS_PRESENT")
    if writer_errors:
        reasons.append("WRITER_ERRORS_PRESENT")
    if reconciliation_failures:
        reasons.append("RECONCILIATION_FAILURES_PRESENT")
    if consecutive_stable < threshold:
        reasons.append("CONSECUTIVE_STABILITY_BELOW_THRESHOLD")
    coverage_counts = {
        scenario: sum(1 for item in manifests if item.get("capture_scenario") == scenario)
        for scenario in coverage_requirements
    }
    for scenario, required_count in coverage_requirements.items():
        if coverage_counts[scenario] < required_count:
            reasons.append(f"COVERAGE_MISSING:{scenario}")
    manifest_hashes = [
        sha256_file(path / "manifest.json") for path in paths if (path / "manifest.json").is_file()
    ]
    body: dict[str, Any] = {
        "schema_version": "ibkr-burn-in-corpus-v1",
        "decision": "PASS" if not reasons else "BLOCKED",
        "bindings": bindings,
        "sessions_total": len(manifests),
        "sessions_complete": sum(1 for item in manifests if item.get("complete")),
        "sessions_eligible": len(eligible),
        "minimum_sessions": threshold,
        "consecutive_stable": consecutive_stable,
        "divergent_resets": divergent_resets,
        "fact_drops": fact_drops,
        "writer_errors": writer_errors,
        "reconciliation_failures": reconciliation_failures,
        "capture_scenarios": sorted({str(item.get("capture_scenario")) for item in manifests}),
        "coverage_requirements": coverage_requirements,
        "coverage_counts": coverage_counts,
        "tws_versions": sorted({str(item.get("tws_server_version")) for item in manifests}),
        "ibapi_versions": sorted({str(item.get("ibapi_version")) for item in manifests}),
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
        "capture_scenario": capture_scenario,
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
    return {"manifest_id": canonical_hash(body), **body}
