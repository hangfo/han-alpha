from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from hanalpha.ops.artifacts import sha256_file
from hanalpha.simulation.events import canonical_hash


class ArtifactType(StrEnum):
    IBKR_PREFLIGHT = "IBKR_PREFLIGHT"
    BURN_IN_SESSION = "BURN_IN_SESSION"
    BURN_IN_CORPUS = "BURN_IN_CORPUS"
    GOLDEN_TAPE = "GOLDEN_TAPE"
    RESET_CASE = "RESET_CASE"
    CANCEL_CASE = "CANCEL_CASE"
    BRACKET_CASE = "BRACKET_CASE"
    ACCOUNT_PROOF = "ACCOUNT_PROOF"
    MARKET_CALENDAR_POLICY = "MARKET_CALENDAR_POLICY"
    LICENSE_RECEIPT = "LICENSE_RECEIPT"
    ENTITLEMENT_PROBE = "ENTITLEMENT_PROBE"
    RAW_SAMPLE_MANIFEST = "RAW_SAMPLE_MANIFEST"
    TIMESTAMP_AUDIT = "TIMESTAMP_AUDIT"
    REVISION_AUDIT = "REVISION_AUDIT"
    SYMBOLOGY_AUDIT = "SYMBOLOGY_AUDIT"
    SURVIVORSHIP_AUDIT = "SURVIVORSHIP_AUDIT"
    REVIEW_APPROVAL = "REVIEW_APPROVAL"


class ArtifactResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: str
    expected_type: ArtifactType
    required_claim: str | None = None
    hash_present: bool
    artifact_found: bool
    artifact_hash_valid: bool
    artifact_schema_valid: bool
    artifact_policy_passed: bool
    reasons: tuple[str, ...]
    path: str | None = None

    @property
    def verified(self) -> bool:
        return (
            self.hash_present
            and self.artifact_found
            and self.artifact_hash_valid
            and self.artifact_schema_valid
            and self.artifact_policy_passed
        )


class ArtifactRegistry:
    """Local evidence index that always re-verifies the referenced immutable file."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence_artifacts (
              artifact_id TEXT PRIMARY KEY,
              artifact_type TEXT NOT NULL,
              schema_version TEXT NOT NULL,
              path TEXT NOT NULL,
              sha256 TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL,
              git_commit TEXT,
              config_hash TEXT,
              scope_hash TEXT,
              account_hash TEXT,
              status TEXT NOT NULL,
              supersedes TEXT
            )
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def register(
        self,
        path: Path,
        *,
        artifact_type: ArtifactType,
        status: str,
        git_commit: str | None = None,
        config_hash: str | None = None,
        scope_hash: str | None = None,
        account_hash: str | None = None,
        supersedes: str | None = None,
        at: datetime | None = None,
    ) -> str:
        if status not in {"CAPTURED", "VERIFIED", "REJECTED", "SUPERSEDED"}:
            raise ValueError("unsupported artifact status")
        document = _read_json(path)
        schema_version = document.get("schema_version")
        if not isinstance(schema_version, (str, int)):
            raise ValueError("artifact schema_version is required")
        digest = sha256_file(path)
        artifact_id = digest
        existing = self.connection.execute(
            "SELECT * FROM evidence_artifacts WHERE artifact_id=?", (artifact_id,)
        ).fetchone()
        created_at = (
            str(existing["created_at"])
            if existing is not None
            else (at or datetime.now(UTC)).astimezone(UTC).isoformat()
        )
        values = (
            artifact_id,
            artifact_type.value,
            str(schema_version),
            str(path.resolve()),
            digest,
            created_at,
            git_commit,
            config_hash,
            scope_hash,
            account_hash,
            status,
            supersedes,
        )
        if existing is not None:
            comparable = (
                existing["artifact_id"],
                existing["artifact_type"],
                existing["schema_version"],
                existing["path"],
                existing["sha256"],
                existing["created_at"],
                existing["git_commit"],
                existing["config_hash"],
                existing["scope_hash"],
                existing["account_hash"],
                existing["status"],
                existing["supersedes"],
            )
            if comparable != values:
                raise RuntimeError("artifact registration is immutable")
            return artifact_id
        with self.connection:
            self.connection.execute(
                "INSERT INTO evidence_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
        return artifact_id

    def resolve(
        self,
        reference: str,
        *,
        expected_type: ArtifactType,
        required_claim: str | None = None,
    ) -> ArtifactResolution:
        reasons: list[str] = []
        hash_present = _is_hash(reference)
        row = (
            self.connection.execute(
                "SELECT * FROM evidence_artifacts WHERE artifact_id=? OR sha256=?",
                (reference, reference),
            ).fetchone()
            if hash_present
            else None
        )
        if not hash_present:
            reasons.append("REFERENCE_NOT_SHA256")
        if row is None:
            reasons.append("ARTIFACT_NOT_REGISTERED")
            return ArtifactResolution(
                reference=reference,
                expected_type=expected_type,
                required_claim=required_claim,
                hash_present=hash_present,
                artifact_found=False,
                artifact_hash_valid=False,
                artifact_schema_valid=False,
                artifact_policy_passed=False,
                reasons=tuple(reasons),
            )
        path = Path(str(row["path"]))
        artifact_found = path.is_file()
        if not artifact_found:
            reasons.append("ARTIFACT_FILE_MISSING")
        hash_valid = artifact_found and sha256_file(path) == reference == row["sha256"]
        if artifact_found and not hash_valid:
            reasons.append("ARTIFACT_HASH_MISMATCH")
        type_valid = row["artifact_type"] == expected_type.value
        if not type_valid:
            reasons.append("ARTIFACT_TYPE_MISMATCH")
        schema_valid = False
        policy_passed = False
        if hash_valid and type_valid:
            try:
                document = _read_json(path)
                schema_valid = _schema_valid(document, expected_type)
                policy_passed = row["status"] == "VERIFIED" and _policy_passed(
                    document, expected_type
                )
                if required_claim and required_claim not in document.get("qualifies_checks", []):
                    policy_passed = False
                    reasons.append("ARTIFACT_CLAIM_MISMATCH")
            except (OSError, ValueError, json.JSONDecodeError):
                reasons.append("ARTIFACT_DOCUMENT_INVALID")
        if not schema_valid:
            reasons.append("ARTIFACT_SCHEMA_INVALID")
        if not policy_passed:
            reasons.append("ARTIFACT_POLICY_NOT_PASSED")
        return ArtifactResolution(
            reference=reference,
            expected_type=expected_type,
            required_claim=required_claim,
            hash_present=hash_present,
            artifact_found=artifact_found,
            artifact_hash_valid=hash_valid,
            artifact_schema_valid=schema_valid,
            artifact_policy_passed=policy_passed,
            reasons=tuple(sorted(set(reasons))),
            path=str(path),
        )

    def latest_verified_document(self, artifact_type: ArtifactType) -> dict[str, Any] | None:
        rows = self.connection.execute(
            """SELECT artifact_id FROM evidence_artifacts
               WHERE artifact_type=? AND status='VERIFIED'
               ORDER BY created_at DESC""",
            (artifact_type.value,),
        ).fetchall()
        for row in rows:
            resolution = self.resolve(str(row["artifact_id"]), expected_type=artifact_type)
            if resolution.verified and resolution.path:
                return _read_json(Path(resolution.path))
        return None

    def ops_summary(self, *, limit: int = 20) -> dict[str, Any]:
        rows = self.connection.execute(
            """SELECT artifact_id, artifact_type, schema_version, created_at, status
               FROM evidence_artifacts ORDER BY created_at DESC"""
        ).fetchall()
        type_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        recent: list[dict[str, Any]] = []
        verified_count = 0
        for row in rows:
            artifact_type = ArtifactType(str(row["artifact_type"]))
            resolution = self.resolve(str(row["artifact_id"]), expected_type=artifact_type)
            type_counts[artifact_type.value] = type_counts.get(artifact_type.value, 0) + 1
            status = str(row["status"])
            status_counts[status] = status_counts.get(status, 0) + 1
            verified_count += int(resolution.verified)
            if len(recent) < limit:
                recent.append(
                    {
                        "artifact_id": row["artifact_id"],
                        "artifact_type": artifact_type,
                        "schema_version": row["schema_version"],
                        "created_at": row["created_at"],
                        "status": status,
                        "verified": resolution.verified,
                        "reasons": list(resolution.reasons),
                    }
                )
        return {
            "total": len(rows),
            "verified": verified_count,
            "type_counts": type_counts,
            "status_counts": status_counts,
            "recent": recent,
        }


def _read_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("artifact must be a JSON object")
    return document


def _schema_valid(document: dict[str, Any], artifact_type: ArtifactType) -> bool:
    schema = str(document.get("schema_version", ""))
    expected_prefixes = {
        ArtifactType.BURN_IN_SESSION: "ibkr-burn-in-session-",
        ArtifactType.BURN_IN_CORPUS: "ibkr-burn-in-corpus-",
        ArtifactType.IBKR_PREFLIGHT: "ibkr-zero-write-preflight-",
        ArtifactType.GOLDEN_TAPE: "ibkr-golden-tape-",
    }
    prefix = expected_prefixes.get(artifact_type)
    if prefix and not schema.startswith(prefix):
        return False
    identifier = (
        document.get("manifest_id") or document.get("corpus_id") or document.get("artifact_id")
    )
    if identifier:
        id_field = next(
            field for field in ("manifest_id", "corpus_id", "artifact_id") if field in document
        )
        body = {key: value for key, value in document.items() if key != id_field}
        if identifier != canonical_hash(body):
            return False
    return bool(schema)


def _policy_passed(document: dict[str, Any], artifact_type: ArtifactType) -> bool:
    if artifact_type is ArtifactType.BURN_IN_SESSION:
        return bool(document.get("safety_case_eligible"))
    if artifact_type is ArtifactType.BURN_IN_CORPUS:
        return document.get("decision") == "PASS"
    if artifact_type is ArtifactType.IBKR_PREFLIGHT:
        return document.get("ready") is True and document.get("write_capability") is False
    if artifact_type is ArtifactType.RAW_SAMPLE_MANIFEST:
        return (
            document.get("schema_version") == "pit-raw-sample-manifest-v1"
            and document.get("decision") == "PASS"
            and document.get("bounded") is True
            and document.get("all_http_success") is True
            and document.get("secrets_redacted") is True
            and isinstance(document.get("responses"), list)
            and bool(document["responses"])
        )
    return document.get("decision") in {"PASS", "APPROVE", "APPROVED", "VERIFIED"}


def _is_hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
