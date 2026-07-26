from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field

from hanalpha.config import SecretSettings
from hanalpha.ops.artifact_registry import ArtifactRegistry, ArtifactType
from hanalpha.ops.artifacts import write_immutable_json
from hanalpha.simulation.events import canonical_hash


class QualificationUse(StrEnum):
    PRICE_BACKTEST = "price_backtest"
    EVENT_BACKTEST = "event_backtest"
    MACRO_BACKTEST = "macro_backtest"


class EvidenceStatus(StrEnum):
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class QualificationLevel(StrEnum):
    BLOCKED = "BLOCKED"
    RESEARCH_QUALIFIED = "RESEARCH_QUALIFIED"
    PROMOTION_QUALIFIED = "PROMOTION_QUALIFIED"


class QualificationEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: EvidenceStatus
    evidence: str = Field(min_length=1)
    artifact_ids: tuple[str, ...] = ()
    reviewer_receipt_ids: tuple[str, ...] = ()
    source_url: str | None = None
    verified_at: datetime | None = None
    expires_at: datetime | None = None


class DataSourceProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "pit-source-profile-v2"
    source_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    product: str = Field(min_length=1)
    intended_use: QualificationUse
    checks: dict[str, QualificationEvidence]
    notes: tuple[str, ...] = ()


class QualificationFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    severity: str
    status: EvidenceStatus
    evidence: str
    artifact_ids: tuple[str, ...] = ()
    reviewer_receipt_ids: tuple[str, ...] = ()
    artifact_reasons: tuple[str, ...] = ()


class DataSourceQualificationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str
    source_id: str
    intended_use: QualificationUse
    decision: QualificationLevel
    required_checks: tuple[str, ...]
    findings: tuple[QualificationFinding, ...]
    profile_hash: str
    evaluated_at: datetime


COMMON_REQUIRED = (
    "systematic_backtest_license",
    "local_cache_permitted",
    "revision_retention",
    "stable_instrument_identifier",
    "timezone_defined",
    "source_timestamp_semantics",
)
USE_REQUIRED: dict[QualificationUse, tuple[str, ...]] = {
    QualificationUse.PRICE_BACKTEST: (
        "delisted_history",
        "point_in_time_universe",
        "ticker_history",
        "corporate_action_available_at",
        "raw_unadjusted_prices",
        "halts_and_no_trade_states",
    ),
    QualificationUse.EVENT_BACKTEST: (
        "public_acceptance_timestamp",
        "original_filing_access",
        "amendment_and_revision_lineage",
        "cik_point_in_time_mapping",
        "pre_market_after_hours_classification",
    ),
    QualificationUse.MACRO_BACKTEST: (
        "vintage_observations",
        "release_timestamp_or_conservative_lag",
        "revision_dates",
        "series_metadata_history",
    ),
}
RESEARCH_EXEMPT: dict[QualificationUse, frozenset[str]] = {
    QualificationUse.PRICE_BACKTEST: frozenset({"delisted_history", "point_in_time_universe"}),
    QualificationUse.EVENT_BACKTEST: frozenset({"cik_point_in_time_mapping"}),
    QualificationUse.MACRO_BACKTEST: frozenset({"series_metadata_history"}),
}
CHECK_ARTIFACT_TYPES: dict[str, ArtifactType] = {
    "systematic_backtest_license": ArtifactType.LICENSE_RECEIPT,
    "local_cache_permitted": ArtifactType.LICENSE_RECEIPT,
    "revision_retention": ArtifactType.LICENSE_RECEIPT,
    "stable_instrument_identifier": ArtifactType.SYMBOLOGY_AUDIT,
    "timezone_defined": ArtifactType.TIMESTAMP_AUDIT,
    "source_timestamp_semantics": ArtifactType.TIMESTAMP_AUDIT,
    "delisted_history": ArtifactType.SURVIVORSHIP_AUDIT,
    "point_in_time_universe": ArtifactType.SURVIVORSHIP_AUDIT,
    "ticker_history": ArtifactType.SYMBOLOGY_AUDIT,
    "corporate_action_available_at": ArtifactType.TIMESTAMP_AUDIT,
    "raw_unadjusted_prices": ArtifactType.RAW_SAMPLE_MANIFEST,
    "halts_and_no_trade_states": ArtifactType.RAW_SAMPLE_MANIFEST,
    "public_acceptance_timestamp": ArtifactType.TIMESTAMP_AUDIT,
    "original_filing_access": ArtifactType.RAW_SAMPLE_MANIFEST,
    "amendment_and_revision_lineage": ArtifactType.REVISION_AUDIT,
    "cik_point_in_time_mapping": ArtifactType.SYMBOLOGY_AUDIT,
    "pre_market_after_hours_classification": ArtifactType.TIMESTAMP_AUDIT,
    "vintage_observations": ArtifactType.REVISION_AUDIT,
    "release_timestamp_or_conservative_lag": ArtifactType.TIMESTAMP_AUDIT,
    "revision_dates": ArtifactType.REVISION_AUDIT,
    "series_metadata_history": ArtifactType.REVISION_AUDIT,
}


def evaluate_source_profile(
    profile: DataSourceProfile,
    *,
    at: datetime,
    registry: ArtifactRegistry | None = None,
    reviewer_keys: dict[str, bytes] | None = None,
) -> DataSourceQualificationReport:
    required = (*COMMON_REQUIRED, *USE_REQUIRED[profile.intended_use])
    findings: list[QualificationFinding] = []
    for code in required:
        evidence = profile.checks.get(code)
        if evidence is None:
            findings.append(_blocked_finding(code, "required qualification evidence is missing"))
            continue
        artifact_reasons: list[str] = []
        verified_artifacts = bool(evidence.artifact_ids)
        if registry is None:
            verified_artifacts = False
            artifact_reasons.append("ARTIFACT_REGISTRY_UNAVAILABLE")
        else:
            for artifact_id in evidence.artifact_ids:
                resolution = registry.resolve(
                    artifact_id,
                    expected_type=CHECK_ARTIFACT_TYPES[code],
                    required_claim=code,
                )
                if not resolution.verified:
                    verified_artifacts = False
                    artifact_reasons.extend(resolution.reasons)
            review_valid = False
            for receipt_id in evidence.reviewer_receipt_ids:
                resolution = registry.resolve(
                    receipt_id, expected_type=ArtifactType.REVIEW_APPROVAL
                )
                if not resolution.verified or resolution.path is None:
                    artifact_reasons.extend(resolution.reasons)
                    continue
                try:
                    receipt = json.loads(Path(resolution.path).read_text(encoding="utf-8"))
                    if _verify_review_receipt(
                        receipt,
                        evidence_artifact_ids=evidence.artifact_ids,
                        reviewer_keys=reviewer_keys or {},
                        at=at,
                    ):
                        review_valid = True
                    else:
                        artifact_reasons.append("REVIEW_RECEIPT_INVALID")
                except (OSError, json.JSONDecodeError):
                    artifact_reasons.append("REVIEW_RECEIPT_INVALID")
            if not review_valid:
                verified_artifacts = False
                artifact_reasons.append("INDEPENDENT_REVIEW_MISSING")
        if evidence.expires_at is None:
            verified_artifacts = False
            artifact_reasons.append("EVIDENCE_EXPIRY_MISSING")
        elif evidence.expires_at <= at:
            verified_artifacts = False
            artifact_reasons.append("EVIDENCE_EXPIRED")
        status = (
            EvidenceStatus.VERIFIED
            if evidence.status is EvidenceStatus.VERIFIED and verified_artifacts
            else EvidenceStatus.BLOCKED
        )
        findings.append(
            QualificationFinding(
                code=code,
                severity="INFO" if status is EvidenceStatus.VERIFIED else "CRITICAL",
                status=status,
                evidence=evidence.evidence,
                artifact_ids=evidence.artifact_ids,
                reviewer_receipt_ids=evidence.reviewer_receipt_ids,
                artifact_reasons=tuple(sorted(set(artifact_reasons))),
            )
        )
    passed = {item.code for item in findings if item.status is EvidenceStatus.VERIFIED}
    promotion_required = set(required)
    research_required = promotion_required - set(RESEARCH_EXEMPT[profile.intended_use])
    if promotion_required <= passed:
        decision = QualificationLevel.PROMOTION_QUALIFIED
    elif research_required <= passed:
        decision = QualificationLevel.RESEARCH_QUALIFIED
    else:
        decision = QualificationLevel.BLOCKED
    body: dict[str, Any] = {
        "source_id": profile.source_id,
        "intended_use": profile.intended_use,
        "decision": decision,
        "required_checks": required,
        "findings": tuple(findings),
        "profile_hash": canonical_hash(profile),
        "evaluated_at": at.astimezone(UTC),
    }
    return DataSourceQualificationReport(report_id=canonical_hash(body), **body)


def vendor_access_preflight(secrets: SecretSettings, *, at: datetime) -> dict[str, Any]:
    user_agent = secrets.sec_user_agent.strip() if secrets.sec_user_agent else ""
    user_agent_valid = _valid_sec_user_agent(user_agent)
    checks: dict[str, dict[str, object]] = {
        "massive": {
            "credential_present": bool(secrets.massive_api_key or secrets.polygon_api_key),
            "required_environment": "MASSIVE_API_KEY",
        },
        "sec_edgar": {
            "credential_present": bool(user_agent),
            "format_valid": user_agent_valid,
            "user_agent_hash": (
                hashlib.sha256(user_agent.encode()).hexdigest() if user_agent_valid else None
            ),
            "throttle_policy_hash": canonical_hash(
                {"policy": "sec-fair-access", "max_requests_per_second": 8}
            ),
            "required_environment": "SEC_USER_AGENT",
        },
        "fred_alfred": {
            "credential_present": bool(secrets.fred_api_key),
            "required_environment": "FRED_API_KEY",
        },
    }
    body = {
        "schema_version": "pit-vendor-access-preflight-v2",
        "evaluated_at": at.astimezone(UTC).isoformat(),
        "checks": checks,
        "credentials_present_for": sorted(
            name for name, value in checks.items() if value.get("credential_present") is True
        ),
        "access_ready_for": [],
        "secrets_redacted": True,
        "limitations": [
            "Credential presence does not prove validity, entitlement, license, coverage or retention.",
            "ACCESS_READY requires a registered entitlement probe and approved license receipt.",
        ],
    }
    return {"artifact_id": canonical_hash(body), **body}


def persist_qualification(path: Path, document: BaseModel | dict[str, Any]) -> None:
    payload = document.model_dump(mode="json") if isinstance(document, BaseModel) else document
    write_immutable_json(path, payload)


def _blocked_finding(code: str, evidence: str) -> QualificationFinding:
    return QualificationFinding(
        code=code,
        severity="CRITICAL",
        status=EvidenceStatus.BLOCKED,
        evidence=evidence,
        artifact_reasons=("EVIDENCE_MISSING",),
    )


def _valid_sec_user_agent(value: str) -> bool:
    if not value or "example.com" in value.lower():
        return False
    email_match = re.search(r"(?<![\w.-])([\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![\w.-])", value)
    if email_match is None:
        return False
    project = value[: email_match.start()].strip(" ()[]<>-")
    return len(project) >= 3 and not any(
        marker in value.lower() for marker in ("api_key", "token=", "bearer ")
    )


def _verify_review_receipt(
    receipt: dict[str, Any],
    *,
    evidence_artifact_ids: tuple[str, ...],
    reviewer_keys: dict[str, bytes],
    at: datetime,
) -> bool:
    if receipt.get("decision") != "APPROVE":
        return False
    if sorted(receipt.get("evidence_artifact_ids", [])) != sorted(evidence_artifact_ids):
        return False
    try:
        reviewed_at = datetime.fromisoformat(str(receipt["reviewed_at"]))
        expires_at = datetime.fromisoformat(str(receipt["expires_at"]))
        if (
            reviewed_at.tzinfo is None
            or expires_at.tzinfo is None
            or reviewed_at > at
            or expires_at <= at
        ):
            return False
        public_key = reviewer_keys[str(receipt["public_key_id"])]
        signature = base64.b64decode(str(receipt["signature"]), validate=True)
        unsigned = {name: value for name, value in receipt.items() if name != "signature"}
        payload = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
    except (KeyError, ValueError, InvalidSignature):
        return False
    return True
