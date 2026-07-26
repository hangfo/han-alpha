from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from hanalpha.config import SecretSettings
from hanalpha.ops.artifact_registry import ArtifactRegistry, ArtifactType
from hanalpha.ops.artifacts import write_immutable_json
from hanalpha.ops.evidence_schemas import SCHEMA_PREFIXES
from hanalpha.pit.qualification import (
    CHECK_ARTIFACT_TYPES,
    DataSourceProfile,
    EvidenceStatus,
    QualificationEvidence,
    QualificationLevel,
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
    assert report.decision is QualificationLevel.BLOCKED
    assert any(
        finding.code == "systematic_backtest_license" and finding.severity == "CRITICAL"
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
        profile = DataSourceProfile.model_validate_json(Path(path).read_text(encoding="utf-8"))
        report = evaluate_source_profile(profile, at=NOW)
        assert report.decision is QualificationLevel.BLOCKED
        assert any(finding.status == EvidenceStatus.BLOCKED for finding in report.findings)


def test_vendor_preflight_never_serializes_secret_values() -> None:
    secrets = SecretSettings(
        massive_api_key="massive-secret",
        fred_api_key="fred-secret",
        sec_user_agent="Han Alpha Research ops@hanalpha.test",
    )
    artifact = vendor_access_preflight(secrets, at=NOW)
    serialized = json.dumps(artifact)
    assert "massive-secret" not in serialized
    assert "fred-secret" not in serialized
    assert artifact["credentials_present_for"] == [
        "fred_alfred",
        "massive",
        "sec_edgar",
    ]
    assert artifact["access_ready_for"] == []
    assert "ops@hanalpha.test" not in serialized
    assert artifact["checks"]["sec_edgar"]["format_valid"] is True


def test_sec_user_agent_rejects_placeholder_or_unidentified_contact() -> None:
    placeholder = vendor_access_preflight(
        SecretSettings(sec_user_agent="Han Alpha contact@example.com"), at=NOW
    )
    unidentified = vendor_access_preflight(
        SecretSettings(sec_user_agent="contact@real.test"), at=NOW
    )
    assert placeholder["checks"]["sec_edgar"]["format_valid"] is False
    assert unidentified["checks"]["sec_edgar"]["format_valid"] is False


def test_profile_cannot_self_report_verified_without_registered_artifacts() -> None:
    checks = {
        code: QualificationEvidence(
            status=EvidenceStatus.VERIFIED,
            evidence="caller assertion",
            artifact_ids=("a" * 64,),
            expires_at=NOW + timedelta(days=1),
        )
        for code in (
            "systematic_backtest_license",
            "local_cache_permitted",
            "revision_retention",
            "stable_instrument_identifier",
            "timezone_defined",
            "source_timestamp_semantics",
            "delisted_history",
            "point_in_time_universe",
            "ticker_history",
            "corporate_action_available_at",
            "raw_unadjusted_prices",
            "halts_and_no_trade_states",
        )
    }
    profile = DataSourceProfile(
        source_id="self-asserted",
        provider="unsafe",
        product="prices",
        intended_use=QualificationUse.PRICE_BACKTEST,
        checks=checks,
    )
    report = evaluate_source_profile(profile, at=NOW)
    assert report.decision is QualificationLevel.BLOCKED
    assert all(
        "ARTIFACT_REGISTRY_UNAVAILABLE" in finding.artifact_reasons for finding in report.findings
    )


def test_registered_unexpired_evidence_can_reach_promotion_qualified(tmp_path) -> None:
    registry = ArtifactRegistry(tmp_path / "registry.sqlite3")
    references = {}
    review_references = {}
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    artifact_types = sorted(set(CHECK_ARTIFACT_TYPES.values()), key=lambda item: item.value)
    for artifact_type in artifact_types:
        document = {
            "schema_version": f"{SCHEMA_PREFIXES[artifact_type]}v1",
            "artifact_type": artifact_type.value,
            "decision": "VERIFIED",
            "artifact_kind": artifact_type.value,
            "effective_from": NOW.isoformat(),
            "expires_at": (NOW + timedelta(days=30)).isoformat(),
            "qualifies_checks": sorted(
                code
                for code, mapped_type in CHECK_ARTIFACT_TYPES.items()
                if mapped_type is artifact_type
            ),
        }
        if artifact_type is ArtifactType.RAW_SAMPLE_MANIFEST:
            document.update(
                {
                    "schema_version": "pit-raw-sample-manifest-v1",
                    "artifact_type": ArtifactType.RAW_SAMPLE_MANIFEST.value,
                    "decision": "PASS",
                    "bounded": True,
                    "all_http_success": True,
                    "secrets_redacted": True,
                    "responses": [{"name": "reviewed-fixture"}],
                }
            )
        path = tmp_path / f"{artifact_type.value}.json"
        write_immutable_json(path, document)
        references[artifact_type] = registry.register(
            path, artifact_type=artifact_type, status="VERIFIED", at=NOW
        )
        receipt = {
            "schema_version": "qualification-review-receipt-v1",
            "artifact_type": ArtifactType.REVIEW_APPROVAL.value,
            "reviewer_id": "independent-data-reviewer",
            "public_key_id": "data-review-key",
            "decision": "APPROVE",
            "reviewed_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(days=30)).isoformat(),
            "evidence_artifact_ids": [references[artifact_type]],
        }
        payload = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
        signed_receipt = {
            **receipt,
            "signature": base64.b64encode(private_key.sign(payload)).decode(),
        }
        receipt_path = tmp_path / f"{artifact_type.value}-review.json"
        write_immutable_json(receipt_path, signed_receipt)
        review_references[artifact_type] = registry.register(
            receipt_path,
            artifact_type=ArtifactType.REVIEW_APPROVAL,
            status="VERIFIED",
            at=NOW,
        )
    required = (
        "systematic_backtest_license",
        "local_cache_permitted",
        "revision_retention",
        "stable_instrument_identifier",
        "timezone_defined",
        "source_timestamp_semantics",
        "delisted_history",
        "point_in_time_universe",
        "ticker_history",
        "corporate_action_available_at",
        "raw_unadjusted_prices",
        "halts_and_no_trade_states",
    )
    profile = DataSourceProfile(
        source_id="qualified",
        provider="reviewed",
        product="prices",
        intended_use=QualificationUse.PRICE_BACKTEST,
        checks={
            code: QualificationEvidence(
                status=EvidenceStatus.VERIFIED,
                evidence="registered audit",
                artifact_ids=(references[CHECK_ARTIFACT_TYPES[code]],),
                reviewer_receipt_ids=(review_references[CHECK_ARTIFACT_TYPES[code]],),
                expires_at=NOW + timedelta(days=30),
            )
            for code in required
        },
    )
    report = evaluate_source_profile(
        profile,
        at=NOW,
        registry=registry,
        reviewer_keys={"data-review-key": public_key},
    )
    assert report.decision is QualificationLevel.PROMOTION_QUALIFIED
    assert all(finding.status is EvidenceStatus.VERIFIED for finding in report.findings)
    registry.close()
