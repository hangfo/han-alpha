from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

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


class SafetyCaseVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    verified: bool
    reasons: tuple[str, ...]
    safety_case_id: str | None
    evidence_checks: dict[str, bool]


def safety_case_signature(document: dict[str, Any], key: bytes) -> str:
    unsigned = {
        name: value
        for name, value in document.items()
        if name not in {"safety_case_id", "signature"}
    }
    payload = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def verify_safety_case(
    document: dict[str, Any],
    *,
    database_status: str,
    at: datetime,
    verification_key: bytes | None,
    expected_scope_hash: str | None,
    expected_bindings: dict[str, str | None] | None = None,
) -> SafetyCaseVerification:
    """Verify integrity and current binding; never trust stored Boolean checks."""

    reasons: list[str] = []
    unsigned = {
        name: value
        for name, value in document.items()
        if name not in {"safety_case_id", "signature"}
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
        "reviewers",
    ):
        if not document.get(required):
            reasons.append(f"MISSING_{required.upper()}")
    evidence_checks = {
        name: _is_hash(document.get(name)) for name in REQUIRED_EXTERNAL_EVIDENCE
    }
    if not all(evidence_checks.values()):
        reasons.append("EXTERNAL_EVIDENCE_INCOMPLETE")
    signature = document.get("signature")
    if verification_key is None:
        reasons.append("VERIFICATION_KEY_UNAVAILABLE")
    elif len(verification_key) < 32:
        reasons.append("VERIFICATION_KEY_TOO_SHORT")
    elif not isinstance(signature, str) or not hmac.compare_digest(
        signature, safety_case_signature(document, verification_key)
    ):
        reasons.append("SIGNATURE_INVALID")
    return SafetyCaseVerification(
        verified=not reasons,
        reasons=tuple(sorted(set(reasons))),
        safety_case_id=str(claimed_id) if claimed_id else None,
        evidence_checks=evidence_checks,
    )


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )
