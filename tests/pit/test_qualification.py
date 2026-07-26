from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from hanalpha.config import SecretSettings
from hanalpha.pit.qualification import (
    DataSourceProfile,
    EvidenceStatus,
    QualificationEvidence,
    QualificationUse,
    evaluate_source_profile,
    vendor_access_preflight,
)

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def test_source_qualification_fails_closed_on_missing_pit_and_license_evidence() -> None:
    profile = DataSourceProfile(
        source_id="fixture",
        provider="fixture",
        product="prices",
        intended_use=QualificationUse.PRICE_BACKTEST,
        checks={
            "timezone_defined": QualificationEvidence(
                status=EvidenceStatus.VERIFIED,
                evidence="UTC",
            )
        },
    )
    report = evaluate_source_profile(profile, at=NOW)
    assert report.decision == "BLOCKED"
    assert any(
        finding.code == "systematic_backtest_license"
        and finding.severity == "CRITICAL"
        for finding in report.findings
    )
    assert len(report.report_id) == 64


def test_repository_vendor_profiles_remain_blocked_until_external_evidence() -> None:
    paths = (
        "configs/data-sources/massive-price-profile.json",
        "configs/data-sources/sec-edgar-event-profile.json",
        "configs/data-sources/fred-alfred-macro-profile.json",
    )
    for path in paths:
        profile = DataSourceProfile.model_validate_json(
            Path(path).read_text(encoding="utf-8")
        )
        report = evaluate_source_profile(profile, at=NOW)
        assert report.decision == "BLOCKED"
        assert any(
            finding.status == EvidenceStatus.BLOCKED for finding in report.findings
        )


def test_vendor_preflight_never_serializes_secret_values() -> None:
    secrets = SecretSettings(
        massive_api_key="massive-secret",
        fred_api_key="fred-secret",
        sec_user_agent="Han Alpha research@example.com",
    )
    artifact = vendor_access_preflight(secrets, at=NOW)
    serialized = json.dumps(artifact)
    assert "massive-secret" not in serialized
    assert "fred-secret" not in serialized
    assert artifact["ready_sources"] == ["fred_alfred", "massive", "sec_edgar"]
