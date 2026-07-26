from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from hanalpha.config import SecretSettings
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


class QualificationEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: EvidenceStatus
    evidence: str = Field(min_length=1)
    source_url: str | None = None
    verified_at: datetime | None = None


class DataSourceProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "pit-source-profile-v1"
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


class DataSourceQualificationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str
    source_id: str
    intended_use: QualificationUse
    decision: str
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


def evaluate_source_profile(
    profile: DataSourceProfile, *, at: datetime
) -> DataSourceQualificationReport:
    required = (*COMMON_REQUIRED, *USE_REQUIRED[profile.intended_use])
    findings: list[QualificationFinding] = []
    for code in required:
        evidence = profile.checks.get(code)
        if evidence is None:
            findings.append(
                QualificationFinding(
                    code=code,
                    severity="CRITICAL",
                    status=EvidenceStatus.BLOCKED,
                    evidence="required qualification evidence is missing",
                )
            )
            continue
        status = evidence.status
        findings.append(
            QualificationFinding(
                code=code,
                severity="INFO" if status == EvidenceStatus.VERIFIED else "CRITICAL",
                status=status,
                evidence=evidence.evidence,
            )
        )
    decision = (
        "QUALIFIED"
        if all(item.status == EvidenceStatus.VERIFIED for item in findings)
        else "BLOCKED"
    )
    body: dict[str, Any] = {
        "source_id": profile.source_id,
        "intended_use": profile.intended_use,
        "decision": decision,
        "required_checks": required,
        "findings": tuple(findings),
        "profile_hash": canonical_hash(profile),
        "evaluated_at": at.astimezone(UTC),
    }
    return DataSourceQualificationReport(
        report_id=canonical_hash(body),
        **body,
    )


def vendor_access_preflight(secrets: SecretSettings, *, at: datetime) -> dict[str, Any]:
    checks = {
        "massive": {
            "credential_configured": bool(
                secrets.massive_api_key or secrets.polygon_api_key
            ),
            "required_environment": "MASSIVE_API_KEY",
        },
        "sec_edgar": {
            "credential_configured": bool(
                secrets.sec_user_agent and len(secrets.sec_user_agent.strip()) >= 8
            ),
            "required_environment": "SEC_USER_AGENT",
        },
        "fred_alfred": {
            "credential_configured": bool(secrets.fred_api_key),
            "required_environment": "FRED_API_KEY",
        },
    }
    body = {
        "schema_version": "pit-vendor-access-preflight-v1",
        "evaluated_at": at.astimezone(UTC).isoformat(),
        "checks": checks,
        "ready_sources": sorted(
            name for name, value in checks.items() if value["credential_configured"]
        ),
        "secrets_redacted": True,
    }
    return {"artifact_id": canonical_hash(body), **body}


def persist_qualification(path: Path, document: BaseModel | dict[str, Any]) -> None:
    payload = (
        document.model_dump(mode="json")
        if isinstance(document, BaseModel)
        else document
    )
    write_immutable_json(path, payload)
