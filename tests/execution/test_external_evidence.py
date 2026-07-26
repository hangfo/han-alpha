from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from hanalpha.config import SecretSettings, load_config
from hanalpha.execution.burn_in import persist_burn_in_session
from hanalpha.execution.control_models import BrokerSnapshot
from hanalpha.execution.ibkr_observer import (
    IBKRCallbackCollector,
    IBKRFactStore,
    IBKRFactType,
    ObserverRequestBarrier,
    account_hash,
)
from hanalpha.execution.ibkr_preflight import build_ibkr_preflight
from hanalpha.execution.safety_case import (
    REQUIRED_EXTERNAL_EVIDENCE,
    safety_case_signature,
    verify_safety_case,
)
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
    assert not artifact["checks"]["official_ibapi_importable"]
    assert not artifact["checks"]["paper_socket_listening"]


def test_burn_in_session_exports_only_bound_tape_and_hashes(tmp_path) -> None:
    source = IBKRFactStore(tmp_path / "shared.sqlite3")
    session_id = source.start_session(
        host="127.0.0.1", port=7497, client_id=19, at=NOW
    )
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
    assert len(manifest["files"]["tape.sqlite3"]) == 64
    certificate_path = session_dir / "certificate.json"
    certificate_path.write_bytes(certificate_path.read_bytes() + b"tampered")
    with pytest.raises(RuntimeError, match="hash validation"):
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
        )


def test_safety_case_rejects_unsigned_boolean_payload_and_verifies_bound_manifest() -> None:
    key = b"k" * 32
    unsigned = {
        "schema_version": "paper-canary-safety-case-v1",
        "status": "ACTIVE",
        "issued_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "git_commit": "a" * 40,
        "config_hash": "b" * 64,
        "account_hash": "c" * 64,
        "environment": "paper",
        "scope_policy_hash": "d" * 64,
        "normalization_policy_hash": "e" * 64,
        "reviewers": ["risk-reviewer", "execution-reviewer"],
        "revocation_status": "NOT_REVOKED",
        **{name: canonical_hash({"evidence": name}) for name in REQUIRED_EXTERNAL_EVIDENCE},
    }
    document = {
        "safety_case_id": canonical_hash(unsigned),
        **unsigned,
    }
    rejected = verify_safety_case(
        {**document, "checks": {"burn_in_passed": True}},
        database_status="ACTIVE",
        at=NOW,
        verification_key=None,
        expected_scope_hash="d" * 64,
    )
    assert not rejected.verified
    assert "VERIFICATION_KEY_UNAVAILABLE" in rejected.reasons
    signed = {**document, "signature": safety_case_signature(document, key)}
    verified = verify_safety_case(
        signed,
        database_status="ACTIVE",
        at=NOW,
        verification_key=key,
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
