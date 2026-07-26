from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, ConfigDict

from hanalpha.ops.artifact_registry import (
    ArtifactRegistry,
    ArtifactResolution,
    ArtifactType,
)
from hanalpha.simulation.events import canonical_hash

REQUIRED_EXTERNAL_EVIDENCE = (
    "burn_in_manifest_hash",
    "golden_tape_corpus_hash",
    "nightly_reset_case_hash",
    "market_calendar_policy_hash",
    "cancel_case_hash",
    "bracket_case_hash",
    "paper_account_proof_hash",
)
EVIDENCE_TYPES = {
    "burn_in_manifest_hash": ArtifactType.BURN_IN_CORPUS,
    "golden_tape_corpus_hash": ArtifactType.GOLDEN_TAPE,
    "nightly_reset_case_hash": ArtifactType.RESET_CASE,
    "market_calendar_policy_hash": ArtifactType.MARKET_CALENDAR_POLICY,
    "cancel_case_hash": ArtifactType.CANCEL_CASE,
    "bracket_case_hash": ArtifactType.BRACKET_CASE,
    "paper_account_proof_hash": ArtifactType.ACCOUNT_PROOF,
}
REQUIRED_REVIEWER_ROLES = frozenset({"RISK", "EXECUTION"})


class SafetyCaseVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    verified: bool
    reasons: tuple[str, ...]
    safety_case_id: str | None
    evidence_checks: dict[str, bool]
    evidence_resolutions: dict[str, ArtifactResolution]
    reviewer_checks: dict[str, bool]


def reviewer_receipt_signature(receipt: dict[str, Any], private_key: bytes) -> str:
    payload = _canonical_receipt_payload(receipt)
    signature = Ed25519PrivateKey.from_private_bytes(private_key).sign(payload)
    return base64.b64encode(signature).decode()


def verify_safety_case(
    document: dict[str, Any],
    *,
    database_status: str,
    at: datetime,
    verification_keys: dict[str, bytes] | None,
    artifact_registry: ArtifactRegistry | None,
    expected_scope_hash: str | None,
    expected_bindings: dict[str, str | None] | None = None,
) -> SafetyCaseVerification:
    """Verify external artifacts and independent offline reviewer approvals."""

    reasons: list[str] = []
    unsigned = {
        name: value
        for name, value in document.items()
        if name not in {"safety_case_id", "reviewer_approvals", "signature", "reviewers"}
    }
    claimed_id = document.get("safety_case_id")
    if claimed_id != canonical_hash(unsigned):
        reasons.append("NON_CANONICAL_ID")
    if database_status != "ACTIVE" or document.get("status") != "ACTIVE":
        reasons.append("NOT_ACTIVE")
    if document.get("revocation_status") != "NOT_REVOKED":
        reasons.append("REVOKED_OR_UNKNOWN")
    try:
        issued_at = datetime.fromisoformat(str(document["issued_at"]))
        expires_at = datetime.fromisoformat(str(document["expires_at"]))
        if issued_at.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError
        if not issued_at <= at < expires_at:
            reasons.append("OUTSIDE_VALIDITY_WINDOW")
    except (KeyError, ValueError):
        reasons.append("INVALID_VALIDITY_WINDOW")
    if expected_scope_hash is None or document.get("scope_policy_hash") != expected_scope_hash:
        reasons.append("CURRENT_SCOPE_MISMATCH")
    for name, expected in (expected_bindings or {}).items():
        if expected is None:
            reasons.append(f"CURRENT_{name.upper()}_UNAVAILABLE")
        elif document.get(name) != expected:
            reasons.append(f"CURRENT_{name.upper()}_MISMATCH")
    for required in (
        "schema_version",
        "git_commit",
        "config_hash",
        "account_hash",
        "environment",
        "normalization_policy_hash",
    ):
        if not document.get(required):
            reasons.append(f"MISSING_{required.upper()}")

    evidence_resolutions: dict[str, ArtifactResolution] = {}
    for name in REQUIRED_EXTERNAL_EVIDENCE:
        reference = document.get(name)
        if artifact_registry is None:
            resolution = ArtifactResolution(
                reference=str(reference or ""),
                expected_type=EVIDENCE_TYPES[name],
                hash_present=_is_hash(reference),
                artifact_found=False,
                artifact_hash_valid=False,
                artifact_schema_valid=False,
                artifact_policy_passed=False,
                reasons=("ARTIFACT_REGISTRY_UNAVAILABLE",),
            )
        else:
            resolution = artifact_registry.resolve(
                str(reference or ""), expected_type=EVIDENCE_TYPES[name]
            )
        evidence_resolutions[name] = resolution
    evidence_checks = {
        name: resolution.verified for name, resolution in evidence_resolutions.items()
    }
    if not all(evidence_checks.values()):
        reasons.append("EXTERNAL_EVIDENCE_INCOMPLETE")

    reviewer_checks: dict[str, bool] = {}
    approvals = document.get("reviewer_approvals")
    if not isinstance(approvals, list):
        approvals = []
    seen_reviewers: set[str] = set()
    seen_keys: set[str] = set()
    for approval in approvals:
        valid, receipt_reasons = _verify_reviewer_receipt(
            approval,
            case_hash=str(claimed_id or ""),
            verification_keys=verification_keys or {},
            at=at,
        )
        role = str(approval.get("role", "UNKNOWN")) if isinstance(approval, dict) else "UNKNOWN"
        reviewer_id = str(approval.get("reviewer_id", "")) if isinstance(approval, dict) else ""
        key_id = str(approval.get("public_key_id", "")) if isinstance(approval, dict) else ""
        if reviewer_id in seen_reviewers or key_id in seen_keys:
            valid = False
            receipt_reasons.append("REVIEWER_NOT_INDEPENDENT")
        seen_reviewers.add(reviewer_id)
        seen_keys.add(key_id)
        reviewer_checks[role] = reviewer_checks.get(role, False) or valid
        reasons.extend(receipt_reasons)
    if not all(reviewer_checks.get(role, False) for role in REQUIRED_REVIEWER_ROLES):
        reasons.append("INDEPENDENT_REVIEW_APPROVALS_INCOMPLETE")
    return SafetyCaseVerification(
        verified=not reasons,
        reasons=tuple(sorted(set(reasons))),
        safety_case_id=str(claimed_id) if claimed_id else None,
        evidence_checks=evidence_checks,
        evidence_resolutions=evidence_resolutions,
        reviewer_checks=reviewer_checks,
    )


def _verify_reviewer_receipt(
    receipt: object,
    *,
    case_hash: str,
    verification_keys: dict[str, bytes],
    at: datetime,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not isinstance(receipt, dict):
        return False, ["REVIEW_RECEIPT_INVALID"]
    if receipt.get("case_hash") != case_hash:
        reasons.append("REVIEW_CASE_MISMATCH")
    if receipt.get("decision") != "APPROVE":
        reasons.append("REVIEW_NOT_APPROVED")
    try:
        reviewed_at = datetime.fromisoformat(str(receipt["reviewed_at"]))
        if reviewed_at.tzinfo is None or reviewed_at > at:
            reasons.append("REVIEW_TIME_INVALID")
    except (KeyError, ValueError):
        reasons.append("REVIEW_TIME_INVALID")
    key_id = str(receipt.get("public_key_id", ""))
    public_key = verification_keys.get(key_id)
    if public_key is None:
        reasons.append("REVIEW_PUBLIC_KEY_UNAVAILABLE")
    else:
        try:
            signature = base64.b64decode(str(receipt.get("signature", "")), validate=True)
            Ed25519PublicKey.from_public_bytes(public_key).verify(
                signature, _canonical_receipt_payload(receipt)
            )
        except (ValueError, InvalidSignature):
            reasons.append("REVIEW_SIGNATURE_INVALID")
    return not reasons, reasons


def _canonical_receipt_payload(receipt: dict[str, Any]) -> bytes:
    unsigned = {name: value for name, value in receipt.items() if name != "signature"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()


def _is_hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
