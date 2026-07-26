from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from hanalpha.execution.control_models import BrokerSnapshot
from hanalpha.execution.ibkr_observer import (
    IBKRFactStore,
    SnapshotCompletenessCertificate,
)
from hanalpha.ops.artifacts import sha256_file, write_immutable_json
from hanalpha.simulation.events import canonical_hash


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
) -> Path:
    """Export one Observer session and its immutable evidence manifest."""

    sessions_root = output_root / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)
    session_dir = sessions_root / str(snapshot.observation_id)
    if session_dir.exists():
        manifest_path = session_dir / "manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError("existing burn-in session is incomplete")
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("certificate_id") != certificate.certificate_id:
            raise RuntimeError("existing burn-in session binds a different certificate")
        for name, expected in existing.get("files", {}).items():
            artifact = session_dir / str(name)
            if not artifact.is_file() or sha256_file(artifact) != expected:
                raise RuntimeError("existing burn-in session failed artifact hash validation")
        return session_dir
    staging = sessions_root / f".{snapshot.observation_id}.pending"
    if staging.exists():
        raise RuntimeError("incomplete burn-in staging directory requires inspection")
    tape_path = staging / "tape.sqlite3"
    source_store.export_session(certificate.session_id, tape_path)
    certificate_document = certificate.model_dump(mode="json")
    certificate_path = staging / "certificate.json"
    write_immutable_json(certificate_path, certificate_document)
    tape_hash = sha256_file(tape_path)
    certificate_hash = sha256_file(certificate_path)
    body: dict[str, Any] = {
        "schema_version": "ibkr-burn-in-session-v1",
        "observation_id": snapshot.observation_id,
        "certificate_id": certificate.certificate_id,
        "git_commit": git_commit,
        "config_hash": config_hash,
        "normalization_policy_hash": certificate.normalization_policy_hash,
        "account_hash": certificate.account_hash,
        "client_id": client_id,
        "paper_port": paper_port,
        "tws_server_version": tws_server_version,
        "ibapi_version": ibapi_version,
        "scope_hash": certificate.visibility.scope_hash,
        "scope_policy": certificate.visibility.model_dump(
            mode="json", exclude={"observation_window", "scope_hash"}
        ),
        "completed_orders_api_only": certificate.visibility.completed_orders_api_only,
        "started_at": (
            certificate.visibility.observation_window.execution_history_end.isoformat()
            if certificate.visibility.observation_window
            else None
        ),
        "completed_at": certificate.as_of.isoformat(),
        "accepted_facts": certificate.accepted_facts,
        "written_facts": certificate.written_facts,
        "dropped_facts": certificate.dropped_facts,
        "final_watermark": certificate.final_watermark,
        "semantic_hash": certificate.semantic_hash,
        "valuation_fields": certificate.valuation_fields,
        "reconciliation_result": reconciliation_status,
        "complete": certificate.complete,
        "files": {
            "tape.sqlite3": tape_hash,
            "certificate.json": certificate_hash,
        },
    }
    manifest = {"manifest_id": canonical_hash(body), **body}
    write_immutable_json(staging / "manifest.json", manifest)
    os.replace(staging, session_dir)
    descriptor = os.open(sessions_root, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return session_dir
