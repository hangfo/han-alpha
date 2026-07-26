from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from typer.testing import CliRunner

from hanalpha.cli import app
from hanalpha.config import SecretSettings, load_config
from hanalpha.execution.burn_in import (
    evaluate_burn_in_corpus,
    persist_burn_in_session,
    verify_burn_in_manifest,
)
from hanalpha.execution.control_models import BrokerSnapshot
from hanalpha.execution.golden_tape import evaluate_golden_tape_corpus
from hanalpha.execution.ibkr_observer import (
    IBKRCallbackCollector,
    IBKRFactStore,
    IBKRFactType,
    ObserverRequestBarrier,
    account_hash,
)
from hanalpha.execution.ibkr_preflight import build_ibkr_preflight
from hanalpha.execution.safety_case import (
    EVIDENCE_TYPES,
    reviewer_receipt_signature,
    verify_safety_case,
)
from hanalpha.ops.artifact_registry import ArtifactRegistry, ArtifactType
from hanalpha.ops.artifacts import sha256_file, write_immutable_json
from hanalpha.simulation.events import canonical_hash

NOW = datetime(2024, 1, 1, tzinfo=UTC)
ACCOUNT = "DU1234567"


def _complete_certificate(store: IBKRFactStore, session_id: str):
    barrier = ObserverRequestBarrier(
        account_request_id=1,
        execution_request_id=2,
        position_epoch="p" * 64,
        open_orders_epoch="o" * 64,
        execution_history_start=NOW - timedelta(days=1),
        execution_history_end=NOW,
    )
    collector = IBKRCallbackCollector(
        store,
        session_id,
        barrier=barrier,
        configured_account=ACCOUNT,
        base_currency="USD",
        client_id=19,
    )
    collector.record(IBKRFactType.CONNECTION, {}, identity_key="connected", at=NOW)
    collector.record(IBKRFactType.NEXT_VALID_ID, {"order_id": 1}, identity_key="1", at=NOW)
    collector.record(
        IBKRFactType.MANAGED_ACCOUNTS,
        {"account_count": 1, "account_hashes": [account_hash(ACCOUNT)]},
        identity_key="accounts",
        at=NOW,
    )
    collector.record(IBKRFactType.SERVER_TIME, {}, identity_key="time", at=NOW)
    for tag in (
        "NetLiquidation",
        "TotalCashValue",
        "SettledCash",
        "BuyingPower",
        "AccruedCash",
    ):
        collector.record(
            IBKRFactType.ACCOUNT_VALUE,
            {
                "request_id": 1,
                "account_hash": account_hash(ACCOUNT),
                "tag": tag,
                "value": "100000" if tag != "AccruedCash" else "0",
                "currency": "USD",
            },
            identity_key=tag,
            at=NOW,
        )
    for fact_type, payload, key in (
        (IBKRFactType.ACCOUNT_END, {"request_id": 1}, "account-end"),
        (IBKRFactType.OPEN_ORDER_END, {"epoch": "o" * 64}, "orders-end"),
        (IBKRFactType.POSITION_END, {"epoch": "p" * 64}, "positions-end"),
        (IBKRFactType.EXECUTION_END, {"request_id": 2}, "execution-end"),
    ):
        collector.record(fact_type, payload, identity_key=key, at=NOW)
    return collector.certificate(
        store,
        at=NOW,
        queue_drained=True,
        accepted_facts=13,
        written_facts=13,
        final_watermark=13,
    )


def test_preflight_is_redacted_and_fail_closed(tmp_path) -> None:
    config, _ = load_config()
    secrets = SecretSettings(
        ibkr_account=ACCOUNT,
        ibkr_port=7497,
        hanalpha_env="paper",
    )
    artifact = build_ibkr_preflight(
        config,
        secrets,
        at=NOW,
        repository_root=tmp_path,
        read_only_attested=False,
        importable=lambda: False,
        listening=lambda _host, _port: False,
    )
    serialized = json.dumps(artifact)
    assert ACCOUNT not in serialized
    assert artifact["account_hash"] == account_hash(ACCOUNT)
    assert not artifact["ready"]
    assert artifact["write_capability"] is False
    assert artifact["checks"]["observer_client_write_methods_blocked"]
    assert artifact["observation_mode"] == "UNATTESTED"
    assert not artifact["checks"]["official_ibapi_importable"]
    assert not artifact["checks"]["paper_socket_listening"]

    order_visibility = build_ibkr_preflight(
        config,
        secrets,
        at=NOW,
        repository_root=tmp_path,
        read_only_attested=False,
        order_visibility_attested=True,
        importable=lambda: True,
        listening=lambda _host, _port: True,
    )
    assert order_visibility["ready"]
    assert order_visibility["observation_mode"] == "ORDER_VISIBILITY_ZERO_WRITE_CLIENT"


def test_burn_in_session_exports_only_bound_tape_and_hashes(tmp_path) -> None:
    source = IBKRFactStore(tmp_path / "shared.sqlite3")
    session_id = source.start_session(host="127.0.0.1", port=7497, client_id=19, at=NOW)
    certificate = _complete_certificate(source, session_id)
    snapshot = BrokerSnapshot(
        as_of=NOW,
        cash=Decimal("100000"),
        completeness_certificate_id=certificate.certificate_id,
        observation_id=certificate.visibility.observation_window.envelope_hash,
        session_id=session_id,
        final_watermark=certificate.final_watermark,
        semantic_hash=certificate.semantic_hash,
        visibility_scope_hash=certificate.visibility.scope_hash,
        normalization_policy_hash=certificate.normalization_policy_hash,
        orders=(),
        positions={},
        protections={},
        events=(),
    )
    try:
        session_dir = persist_burn_in_session(
            source_store=source,
            certificate=certificate,
            snapshot=snapshot,
            output_root=tmp_path / "burn-in",
            git_commit="a" * 40,
            config_hash="b" * 64,
            client_id=19,
            paper_port=7497,
            reconciliation_status="CONVERGED",
            tws_server_version=180,
            ibapi_version="10.40.1",
            vote_disposition="ACCEPTED_FIRST",
            consensus_count_after_vote=1,
            equivalence_receipt={"state_equivalent": True},
        )
        assert (
            persist_burn_in_session(
                source_store=source,
                certificate=certificate,
                snapshot=snapshot,
                output_root=tmp_path / "burn-in",
                git_commit="a" * 40,
                config_hash="b" * 64,
                client_id=19,
                paper_port=7497,
                reconciliation_status="CONVERGED",
                tws_server_version=180,
                ibapi_version="10.40.1",
                vote_disposition="ACCEPTED_FIRST",
                consensus_count_after_vote=1,
                equivalence_receipt={"state_equivalent": True},
            )
            == session_dir
        )
    finally:
        source.close()
    manifest = json.loads((session_dir / "manifest.json").read_text())
    exported = IBKRFactStore(session_dir / "tape.sqlite3")
    try:
        assert len(exported.facts(session_id)) == 13
        assert exported.latest_certificate() == certificate
    finally:
        exported.close()
    assert manifest["accepted_facts"] == manifest["written_facts"] == 13
    assert manifest["dropped_facts"] == 0
    assert manifest["scope_hash"] == certificate.visibility.scope_hash
    assert manifest["safety_case_eligible"] is True
    assert len(manifest["files"]["tape.sqlite3"]) == 64
    assert verify_burn_in_manifest(session_dir).verified
    golden = evaluate_golden_tape_corpus(
        (session_dir,), required_scenarios=frozenset({"repeated_connection"})
    )
    assert golden["decision"] == "BLOCKED"
    assert golden["tapes"][0]["decision"] == "PASS"
    assert golden["tapes"][0]["callback_truth_map"]["cash"] == "AUTHORITATIVE"
    assert "TRANSFORM_COVERAGE_MISSING:delayed_commission" in golden["reasons"]
    matrix = evaluate_burn_in_corpus(
        (session_dir,),
        minimum_sessions=1,
        required_coverage={"manual_order": 1},
    )
    assert matrix.decision == "BLOCKED"
    assert "COVERAGE_MISSING:manual_order" in matrix.reasons
    tampered_manifest = dict(manifest)
    tampered_manifest["client_id"] = 20
    (session_dir / "manifest.json").write_text(json.dumps(tampered_manifest))
    assert "MANIFEST_ID_MISMATCH" in verify_burn_in_manifest(session_dir).reasons
    (session_dir / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    )
    certificate_path = session_dir / "certificate.json"
    certificate_path.write_bytes(certificate_path.read_bytes() + b"tampered")
    with pytest.raises(RuntimeError, match="manifest validation"):
        persist_burn_in_session(
            source_store=source,
            certificate=certificate,
            snapshot=snapshot,
            output_root=tmp_path / "burn-in",
            git_commit="a" * 40,
            config_hash="b" * 64,
            client_id=19,
            paper_port=7497,
            reconciliation_status="CONVERGED",
            tws_server_version=180,
            ibapi_version="10.40.1",
            vote_disposition="ACCEPTED_FIRST",
            consensus_count_after_vote=1,
            equivalence_receipt={"state_equivalent": True},
        )


def test_corpus_evaluation_fails_closed_without_stable_eligible_matrix(tmp_path) -> None:
    evaluation = evaluate_burn_in_corpus((), minimum_sessions=5)
    assert evaluation.decision == "BLOCKED"
    assert "INSUFFICIENT_ELIGIBLE_SESSIONS" in evaluation.reasons
    assert len(evaluation.corpus["corpus_id"]) == 64


def test_burn_in_manifest_verification_rejects_missing_and_invalid_json(tmp_path) -> None:
    missing = verify_burn_in_manifest(tmp_path / "missing")
    assert missing.reasons == ("MANIFEST_MISSING",)
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "manifest.json").write_text("{", encoding="utf-8")
    assert verify_burn_in_manifest(invalid).reasons == ("MANIFEST_INVALID_JSON",)

    structurally_invalid = tmp_path / "wrong-directory"
    structurally_invalid.mkdir()
    body = {
        "schema_version": "unsupported",
        "observation_id": "different-observation",
        "files": {},
    }
    write_immutable_json(
        structurally_invalid / "manifest.json",
        {"manifest_id": canonical_hash(body), **body},
    )
    reasons = verify_burn_in_manifest(structurally_invalid).reasons
    assert "SCHEMA_VERSION_UNSUPPORTED" in reasons
    assert "REQUIRED_FILES_INVALID" in reasons
    assert "CERTIFICATE_JSON_MISSING" in reasons
    assert "TAPE_SQLITE3_MISSING" in reasons
    assert "OBSERVATION_DIRECTORY_MISMATCH" in reasons
    invalid_corpus = evaluate_burn_in_corpus((structurally_invalid,), minimum_sessions=1)
    assert "INVALID_SESSION:wrong-directory" in invalid_corpus.reasons


def test_burn_in_evaluate_cli_persists_blocked_corpus_and_exits_nonzero(
    tmp_path,
) -> None:
    input_root = tmp_path / "capture"
    (input_root / "sessions").mkdir(parents=True)
    output = tmp_path / "corpus.json"
    result = CliRunner().invoke(
        app,
        [
            "ibkr-burn-in-evaluate",
            "--input",
            str(input_root),
            "--output",
            str(output),
            "--minimum-sessions",
            "1",
            "--registry",
            str(tmp_path / "registry.sqlite3"),
        ],
    )
    assert result.exit_code == 2
    assert output.is_file()
    assert json.loads(output.read_text())["decision"] == "BLOCKED"


def test_preflight_cli_registers_rejected_zero_write_artifact(tmp_path) -> None:
    output = tmp_path / "preflight"
    registry_path = tmp_path / "registry.sqlite3"
    result = CliRunner().invoke(
        app,
        [
            "ibkr-preflight",
            "--read-only-not-attested",
            "--output",
            str(output),
            "--registry",
            str(registry_path),
        ],
    )
    assert result.exit_code == 2
    artifacts = tuple(output.glob("*.json"))
    assert len(artifacts) == 1
    registry = ArtifactRegistry(registry_path)
    try:
        artifact_id = sha256_file(artifacts[0])
        resolution = registry.resolve(artifact_id, expected_type=ArtifactType.IBKR_PREFLIGHT)
        assert resolution.artifact_found
        assert not resolution.verified
        assert "ARTIFACT_POLICY_NOT_PASSED" in resolution.reasons
    finally:
        registry.close()


def test_artifact_registry_is_immutable_and_resolves_fail_closed(tmp_path) -> None:
    registry = ArtifactRegistry(tmp_path / "registry.sqlite3")
    artifact = tmp_path / "artifact.json"
    write_immutable_json(
        artifact,
        {
            "schema_version": "pit-license-receipt-v1",
            "artifact_type": "LICENSE_RECEIPT",
            "decision": "VERIFIED",
            "qualifies_checks": ["systematic_backtest_license"],
            "effective_from": NOW.isoformat(),
            "expires_at": (NOW + timedelta(days=30)).isoformat(),
        },
    )
    with pytest.raises(ValueError, match="unsupported artifact status"):
        registry.register(
            artifact,
            artifact_type=ArtifactType.LICENSE_RECEIPT,
            status="UNSAFE",
        )
    missing_schema = tmp_path / "missing-schema.json"
    write_immutable_json(missing_schema, {"decision": "VERIFIED"})
    with pytest.raises(ValueError, match="schema_version"):
        registry.register(
            missing_schema,
            artifact_type=ArtifactType.LICENSE_RECEIPT,
            status="VERIFIED",
        )

    artifact_id = registry.register(
        artifact,
        artifact_type=ArtifactType.LICENSE_RECEIPT,
        status="VERIFIED",
        at=NOW,
    )
    assert (
        registry.register(
            artifact,
            artifact_type=ArtifactType.LICENSE_RECEIPT,
            status="VERIFIED",
            at=NOW + timedelta(days=1),
        )
        == artifact_id
    )
    with pytest.raises(RuntimeError, match="immutable"):
        registry.register(
            artifact,
            artifact_type=ArtifactType.LICENSE_RECEIPT,
            status="REJECTED",
            at=NOW,
        )
    assert registry.resolve(artifact_id, expected_type=ArtifactType.LICENSE_RECEIPT).verified
    assert registry.latest_verified_document(ArtifactType.LICENSE_RECEIPT) == {
        "artifact_type": "LICENSE_RECEIPT",
        "decision": "VERIFIED",
        "effective_from": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=30)).isoformat(),
        "qualifies_checks": ["systematic_backtest_license"],
        "schema_version": "pit-license-receipt-v1",
    }
    summary = registry.ops_summary()
    assert summary["total"] == summary["verified"] == 1
    assert summary["type_counts"] == {"LICENSE_RECEIPT": 1}
    claim_mismatch = registry.resolve(
        artifact_id,
        expected_type=ArtifactType.LICENSE_RECEIPT,
        required_claim="local_cache_permitted",
    )
    assert "ARTIFACT_CLAIM_MISMATCH" in claim_mismatch.reasons

    invalid_reference = registry.resolve("not-a-hash", expected_type=ArtifactType.LICENSE_RECEIPT)
    assert invalid_reference.reasons == (
        "REFERENCE_NOT_SHA256",
        "ARTIFACT_NOT_REGISTERED",
    )
    wrong_type = registry.resolve(artifact_id, expected_type=ArtifactType.RAW_SAMPLE_MANIFEST)
    assert "ARTIFACT_TYPE_MISMATCH" in wrong_type.reasons

    artifact.write_bytes(artifact.read_bytes() + b"tamper")
    tampered = registry.resolve(artifact_id, expected_type=ArtifactType.LICENSE_RECEIPT)
    assert tampered.verified
    assert tampered.identity_type.value == "CONTENT_HASH"
    assert tampered.path is not None
    Path(tampered.path).write_bytes(Path(tampered.path).read_bytes() + b"tamper")
    tampered = registry.resolve(artifact_id, expected_type=ArtifactType.LICENSE_RECEIPT)
    assert "ARTIFACT_HASH_MISMATCH" in tampered.reasons
    Path(tampered.path).unlink()
    missing = registry.resolve(artifact_id, expected_type=ArtifactType.LICENSE_RECEIPT)
    assert "ARTIFACT_FILE_MISSING" in missing.reasons
    registry.close()


def test_artifact_registry_requires_valid_schema_and_policy(tmp_path) -> None:
    registry = ArtifactRegistry(tmp_path / "registry.sqlite3")
    non_object = tmp_path / "non-object.json"
    non_object.write_text('["not","an","object"]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        registry.register(
            non_object,
            artifact_type=ArtifactType.LICENSE_RECEIPT,
            status="VERIFIED",
        )

    bad_schema = tmp_path / "bad-schema.json"
    write_immutable_json(
        bad_schema,
        {
            "schema_version": "wrong-prefix-v1",
            "decision": "PASS",
        },
    )
    bad_schema_id = registry.register(
        bad_schema,
        artifact_type=ArtifactType.IBKR_PREFLIGHT,
        status="VERIFIED",
        at=NOW,
    )
    resolution = registry.resolve(bad_schema_id, expected_type=ArtifactType.IBKR_PREFLIGHT)
    assert "ARTIFACT_SCHEMA_INVALID" in resolution.reasons

    captured = tmp_path / "captured.json"
    write_immutable_json(
        captured,
        {
            "schema_version": "pit-raw-sample-manifest-v1",
            "artifact_type": "RAW_SAMPLE_MANIFEST",
            "decision": "PASS",
            "bounded": True,
            "all_http_success": True,
            "secrets_redacted": True,
            "qualifies_checks": [],
            "responses": [{"name": "fixture"}],
        },
    )
    captured_id = registry.register(
        captured,
        artifact_type=ArtifactType.RAW_SAMPLE_MANIFEST,
        status="CAPTURED",
        at=NOW,
    )
    captured_resolution = registry.resolve(
        captured_id, expected_type=ArtifactType.RAW_SAMPLE_MANIFEST
    )
    assert captured_resolution.artifact_schema_valid
    assert "ARTIFACT_POLICY_NOT_PASSED" in captured_resolution.reasons

    bad_identifier = tmp_path / "bad-identifier.json"
    write_immutable_json(
        bad_identifier,
        {
            "artifact_id": "0" * 64,
            "schema_version": "pit-raw-sample-manifest-v1",
            "artifact_type": "RAW_SAMPLE_MANIFEST",
            "decision": "PASS",
            "bounded": True,
            "all_http_success": True,
            "secrets_redacted": True,
            "qualifies_checks": [],
            "responses": [{"name": "fixture"}],
        },
    )
    identifier_id = registry.register(
        bad_identifier,
        artifact_type=ArtifactType.RAW_SAMPLE_MANIFEST,
        status="VERIFIED",
        at=NOW,
    )
    assert (
        "ARTIFACT_SCHEMA_INVALID"
        in registry.resolve(identifier_id, expected_type=ArtifactType.RAW_SAMPLE_MANIFEST).reasons
    )

    burn_body = {
        "schema_version": "ibkr-burn-in-session-v2",
        "safety_case_eligible": False,
    }
    burn = tmp_path / "ineligible-burn.json"
    write_immutable_json(
        burn,
        {"manifest_id": canonical_hash(burn_body), **burn_body},
    )
    burn_id = registry.register(
        burn,
        artifact_type=ArtifactType.BURN_IN_SESSION,
        status="VERIFIED",
        at=NOW,
    )
    burn_resolution = registry.resolve(burn_id, expected_type=ArtifactType.BURN_IN_SESSION)
    assert burn_resolution.artifact_schema_valid
    assert "ARTIFACT_POLICY_NOT_PASSED" in burn_resolution.reasons
    registry.close()


def _register_safety_artifacts(registry: ArtifactRegistry, root: Path) -> dict[str, str]:
    references: dict[str, str] = {}
    for field, artifact_type in EVIDENCE_TYPES.items():
        if artifact_type is ArtifactType.BURN_IN_CORPUS:
            body = {
                "schema_version": "ibkr-burn-in-corpus-v1",
                "decision": "PASS",
                "sessions_eligible": 30,
            }
            document = {"corpus_id": canonical_hash(body), **body}
        elif artifact_type is ArtifactType.GOLDEN_TAPE:
            body = {
                "schema_version": "ibkr-golden-tape-corpus-v1",
                "decision": "PASS",
            }
            document = {"artifact_id": canonical_hash(body), **body}
        else:
            document = {
                "schema_version": f"{artifact_type.value.lower()}-v1",
                "decision": "VERIFIED",
                "artifact_kind": artifact_type.value,
            }
        path = root / f"{field}.json"
        write_immutable_json(path, document)
        references[field] = registry.register(
            path, artifact_type=artifact_type, status="VERIFIED", at=NOW
        )
    return references


def test_safety_case_requires_artifacts_and_independent_ed25519_reviews(tmp_path) -> None:
    registry = ArtifactRegistry(tmp_path / "registry.sqlite3")
    references = _register_safety_artifacts(registry, tmp_path / "artifacts")
    risk_private = Ed25519PrivateKey.generate()
    execution_private = Ed25519PrivateKey.generate()
    keys = {
        "risk-key": risk_private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ),
        "execution-key": execution_private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ),
    }
    unsigned = {
        "schema_version": "paper-canary-safety-case-v2",
        "status": "ACTIVE",
        "issued_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "git_commit": "a" * 40,
        "config_hash": "b" * 64,
        "account_hash": "c" * 64,
        "environment": "paper",
        "scope_policy_hash": "d" * 64,
        "normalization_policy_hash": "e" * 64,
        "revocation_status": "NOT_REVOKED",
        **references,
    }
    case_hash = canonical_hash(unsigned)
    document = {"safety_case_id": case_hash, **unsigned}
    rejected = verify_safety_case(
        {**document, "checks": {"burn_in_passed": True}},
        database_status="ACTIVE",
        at=NOW,
        verification_keys=None,
        artifact_registry=None,
        expected_scope_hash="d" * 64,
    )
    assert not rejected.verified
    assert "EXTERNAL_EVIDENCE_INCOMPLETE" in rejected.reasons
    approvals = []
    for reviewer_id, role, key_id, private in (
        ("reviewer-risk", "RISK", "risk-key", risk_private),
        ("reviewer-execution", "EXECUTION", "execution-key", execution_private),
    ):
        receipt = {
            "reviewer_id": reviewer_id,
            "role": role,
            "decision": "APPROVE",
            "reviewed_at": NOW.isoformat(),
            "case_hash": case_hash,
            "public_key_id": key_id,
        }
        approvals.append(
            {
                **receipt,
                "signature": reviewer_receipt_signature(
                    receipt,
                    private.private_bytes(
                        serialization.Encoding.Raw,
                        serialization.PrivateFormat.Raw,
                        serialization.NoEncryption(),
                    ),
                ),
            }
        )
    signed = {**document, "reviewer_approvals": approvals}
    verified = verify_safety_case(
        signed,
        database_status="ACTIVE",
        at=NOW,
        verification_keys=keys,
        artifact_registry=registry,
        expected_scope_hash="d" * 64,
        expected_bindings={
            "git_commit": "a" * 40,
            "config_hash": "b" * 64,
            "account_hash": "c" * 64,
            "environment": "paper",
            "normalization_policy_hash": "e" * 64,
        },
    )
    assert verified.verified
    assert all(verified.evidence_checks.values())
    assert verified.reviewer_checks == {"RISK": True, "EXECUTION": True}
    duplicate = {**signed, "reviewer_approvals": [approvals[0], approvals[0]]}
    duplicate_result = verify_safety_case(
        duplicate,
        database_status="ACTIVE",
        at=NOW,
        verification_keys=keys,
        artifact_registry=registry,
        expected_scope_hash="d" * 64,
        expected_bindings={
            "git_commit": "a" * 40,
            "config_hash": "b" * 64,
            "account_hash": "c" * 64,
            "environment": "paper",
            "normalization_policy_hash": "e" * 64,
        },
    )
    assert not duplicate_result.verified
    assert "REVIEWER_NOT_INDEPENDENT" in duplicate_result.reasons
    registry.close()
