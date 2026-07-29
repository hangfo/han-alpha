from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from hanalpha.execution import e1_scenarios
from hanalpha.execution.e1_scenarios import (
    E1_ACCEPTANCE_POLICIES,
    E1AcceptancePolicy,
    E1EventType,
    E1ScenarioType,
    E1ScopeName,
    allocate_scenario_cases,
    build_scenario_case,
    create_event_receipt,
)
from hanalpha.execution.ibkr_observer import IBKRFactStore, IBKRFactType
from hanalpha.ops.artifacts import write_immutable_json
from hanalpha.simulation.events import canonical_hash

NOW = datetime(2026, 7, 27, tzinfo=UTC)


def _manifest(
    *,
    manifest_id: str,
    label: str = "empty_account",
    client_id: int = 41,
    scope_hash: str = "7" * 64,
    semantic_hash: str = "8" * 64,
) -> dict[str, object]:
    return {
        "manifest_id": manifest_id,
        "account_identity_hash": "a" * 64,
        "git_commit": "b" * 40,
        "config_hash": "c" * 64,
        "normalization_policy_hash": "d" * 64,
        "scope_hash": scope_hash,
        "semantic_hash": semantic_hash,
        "orders_hash": "e" * 64,
        "positions_hash": "f" * 64,
        "executions_hash": "1" * 64,
        "safety_case_eligible": True,
        "capture_scenario": label,
        "scenario_observation": {"position_count": 0, "order_count": 0},
        "tws_server_version": "188",
        "ibapi_version": "10.48.1",
        "client_id": client_id,
    }


def _patch_manifests(monkeypatch, manifests: dict[str, dict[str, object]]) -> None:
    def verify(path: Path):
        manifest = manifests[path.name]
        return SimpleNamespace(verified=True, manifest=manifest)

    monkeypatch.setattr(e1_scenarios, "verify_burn_in_manifest", verify)


def test_labels_alone_cannot_prove_process_restart(tmp_path, monkeypatch) -> None:
    manifests = {
        "one": _manifest(manifest_id="1" * 64, label="process_restart"),
        "two": _manifest(manifest_id="2" * 64, label="process_restart"),
    }
    _patch_manifests(monkeypatch, manifests)
    for name in manifests:
        (tmp_path / name).mkdir()
    case = build_scenario_case(
        scenario_type=E1ScenarioType.PROCESS_RESTART,
        scope=E1ScopeName.API,
        session_dirs=(tmp_path / "one", tmp_path / "two"),
        event_receipts=(),
        effective_from=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    assert case.decision == "BLOCKED"
    assert "DISTINCT_PROCESS_BOOT_RECEIPTS_MISSING" in case.reasons


def test_client_switch_is_a_cross_scope_case(monkeypatch, tmp_path) -> None:
    manifests = {
        "one": _manifest(
            manifest_id="1" * 64,
            client_id=41,
            scope_hash="4" * 64,
        ),
        "two": _manifest(
            manifest_id="2" * 64,
            client_id=42,
            scope_hash="5" * 64,
        ),
    }
    _patch_manifests(monkeypatch, manifests)
    for name in manifests:
        (tmp_path / name).mkdir()
    case = build_scenario_case(
        scenario_type=E1ScenarioType.CLIENT_ID_SWITCH,
        scope=E1ScopeName.API,
        session_dirs=(tmp_path / "one", tmp_path / "two"),
        event_receipts=(),
        effective_from=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    assert case.decision == "PASS"
    assert len(case.scope_hashes) == 2
    assert case.observed_transition == "CLIENT_AND_SCOPE_CHANGED_STATE_COMPATIBLE"
    counts, rejected = allocate_scenario_cases(
        (case,),
        scope=E1ScopeName.API,
        at=NOW,
        corpus_manifest_ids=(),
        cross_scope_manifest_ids=("1" * 64, "2" * 64),
        available_receipt_ids=(),
    )
    assert counts["client_id_switch"] == 1
    assert rejected == {}


def test_case_evidence_cannot_be_rewrapped_or_reused(monkeypatch, tmp_path) -> None:
    manifests = {
        str(index): {
            **_manifest(
                manifest_id=str(index) * 64,
                label="static_position",
            ),
            "scenario_observation": {"position_count": 1, "order_count": 0},
        }
        for index in range(1, 6)
    }
    _patch_manifests(monkeypatch, manifests)
    paths = tuple(tmp_path / name for name in manifests)
    for path in paths:
        path.mkdir()
    first = build_scenario_case(
        scenario_type=E1ScenarioType.STATIC_POSITION,
        scope=E1ScopeName.API,
        session_dirs=paths,
        event_receipts=(),
        effective_from=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    rewrapped = build_scenario_case(
        scenario_type=E1ScenarioType.STATIC_POSITION,
        scope=E1ScopeName.API,
        session_dirs=paths,
        event_receipts=(),
        effective_from=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(days=2),
    )
    assert first.artifact_id != rewrapped.artifact_id
    assert first.evidence_set_hash == rewrapped.evidence_set_hash
    counts, rejected = allocate_scenario_cases(
        (first, rewrapped),
        scope=E1ScopeName.API,
        at=NOW,
        corpus_manifest_ids=(str(index) * 64 for index in range(1, 6)),
    )
    assert counts["static_position"] == 1
    assert len(rejected) == 1
    assert set(next(iter(rejected.values()))) & {
        "DUPLICATE_EVIDENCE_SET",
        "CHILD_SESSION_ALREADY_ALLOCATED",
    }


def test_case_children_must_belong_to_current_corpus(monkeypatch, tmp_path) -> None:
    manifests = {
        str(index): {
            **_manifest(
                manifest_id=str(index) * 64,
                label="static_position",
            ),
            "scenario_observation": {"position_count": 1, "order_count": 0},
        }
        for index in range(1, 6)
    }
    _patch_manifests(monkeypatch, manifests)
    paths = tuple(tmp_path / name for name in manifests)
    for path in paths:
        path.mkdir()
    case = build_scenario_case(
        scenario_type=E1ScenarioType.STATIC_POSITION,
        scope=E1ScopeName.API,
        session_dirs=paths,
        event_receipts=(),
        effective_from=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    counts, rejected = allocate_scenario_cases(
        (case,),
        scope=E1ScopeName.API,
        at=NOW,
        corpus_manifest_ids=("1" * 64,),
    )
    assert counts == {}
    assert rejected[case.artifact_id] == ("CHILD_SESSION_OUTSIDE_CURRENT_CORPUS",)


def test_case_allocator_rejects_wrong_scope_status_and_validity(monkeypatch, tmp_path) -> None:
    manifests = {
        str(index): {
            **_manifest(
                manifest_id=str(index) * 64,
                label="static_position",
            ),
            "scenario_observation": {"position_count": 1, "order_count": 0},
        }
        for index in range(1, 6)
    }
    _patch_manifests(monkeypatch, manifests)
    paths = tuple(tmp_path / name for name in manifests)
    for path in paths:
        path.mkdir()
    case = build_scenario_case(
        scenario_type=E1ScenarioType.STATIC_POSITION,
        scope=E1ScopeName.API,
        session_dirs=paths,
        event_receipts=(),
        effective_from=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    variants = (
        case.model_copy(update={"scope": E1ScopeName.ALL}),
        case.model_copy(update={"decision": "BLOCKED"}),
        case.model_copy(
            update={
                "effective_from": NOW - timedelta(days=3),
                "expires_at": NOW - timedelta(days=2),
            }
        ),
    )
    expected = (
        "CASE_SCOPE_MISMATCH",
        "CASE_NOT_PASSING",
        "CASE_OUTSIDE_VALIDITY",
    )
    for variant, reason in zip(variants, expected, strict=True):
        counts, rejected = allocate_scenario_cases(
            (variant,),
            scope=E1ScopeName.API,
            at=NOW,
            corpus_manifest_ids=(str(index) * 64 for index in range(1, 6)),
        )
        assert counts == {}
        assert reason in rejected[variant.artifact_id]
    unresolved_receipt = case.model_copy(update={"event_receipt_ids": ("9" * 64,)})
    counts, rejected = allocate_scenario_cases(
        (unresolved_receipt,),
        scope=E1ScopeName.API,
        at=NOW,
        corpus_manifest_ids=(str(index) * 64 for index in range(1, 6)),
        available_receipt_ids=(),
    )
    assert counts == {}
    assert "EVENT_RECEIPT_NOT_RESOLVABLE" in rejected[unresolved_receipt.artifact_id]


def test_client_switch_requires_explicit_cross_scope_membership(monkeypatch, tmp_path) -> None:
    manifests = {
        "one": _manifest(manifest_id="1" * 64, client_id=41, scope_hash="4" * 64),
        "two": _manifest(manifest_id="2" * 64, client_id=42, scope_hash="5" * 64),
    }
    _patch_manifests(monkeypatch, manifests)
    for name in manifests:
        (tmp_path / name).mkdir()
    case = build_scenario_case(
        scenario_type=E1ScenarioType.CLIENT_ID_SWITCH,
        scope=E1ScopeName.API,
        session_dirs=(tmp_path / "one", tmp_path / "two"),
        event_receipts=(),
        effective_from=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    counts, rejected = allocate_scenario_cases(
        (case,),
        scope=E1ScopeName.API,
        at=NOW,
        corpus_manifest_ids=(),
        cross_scope_manifest_ids=("1" * 64,),
    )
    assert counts == {}
    assert rejected[case.artifact_id] == ("CROSS_SCOPE_TOPOLOGY_INVALID",)


def test_event_receipts_reject_secret_shaped_detail_keys() -> None:
    with pytest.raises(ValueError, match="detail key is forbidden"):
        create_event_receipt(
            event_type=E1EventType.PROCESS_BOOT,
            phase="POST",
            observed_at=NOW,
            account_identity_hash="a" * 64,
            git_commit="b" * 40,
            config_hash="c" * 64,
            details={"boot_id": "boot-1", "access_token": "must-not-persist"},
        )


def test_acceptance_policy_rejects_runner_evaluator_arithmetic_drift() -> None:
    with pytest.raises(ValueError, match="matrix and total threshold disagree"):
        E1AcceptancePolicy(
            scope=E1ScopeName.API,
            minimum_unique_sessions=30,
            minimum_scope_sessions=22,
            minimum_cross_scope_sessions=2,
            session_requirements={"empty_account": 5, "client_id_switch": 2},
            scenario_case_requirements={"client_id_switch": 1},
        )


def test_acceptance_policy_reserves_disjoint_sessions_for_every_case() -> None:
    api = E1_ACCEPTANCE_POLICIES[E1ScopeName.API]
    all_scope = E1_ACCEPTANCE_POLICIES[E1ScopeName.ALL]
    assert api.minimum_unique_sessions == 34
    assert api.minimum_scope_sessions == 30
    assert api.minimum_cross_scope_sessions == 4
    assert all_scope.minimum_unique_sessions == 16
    assert all_scope.minimum_scope_sessions == 14
    assert all_scope.minimum_cross_scope_sessions == 2
    for policy in (api, all_scope):
        for scenario, required_cases in policy.scenario_case_requirements.items():
            if scenario in {"static_position", "api_order", "manual_order"}:
                continue
            assert policy.session_requirements[scenario] == required_cases * 2


def _receipt(event_type: E1EventType, details: dict[str, object], phase: str = "POST"):
    return create_event_receipt(
        event_type=event_type,
        phase=phase,
        observed_at=NOW,
        account_identity_hash="a" * 64,
        git_commit="b" * 40,
        config_hash="c" * 64,
        details=details,
    )


@pytest.mark.parametrize(
    ("scenario", "scope", "manifests", "receipts", "raw", "transition"),
    (
        (
            E1ScenarioType.STATIC_POSITION,
            E1ScopeName.API,
            [
                {
                    **_manifest(
                        manifest_id=str(index) * 64,
                        label="static_position",
                    ),
                    "scenario_observation": {
                        "position_count": 1,
                        "order_count": 0,
                    },
                }
                for index in range(1, 6)
            ],
            (),
            [],
            "STABLE_POSITION_STATE",
        ),
        (
            E1ScenarioType.API_ORDER,
            E1ScopeName.API,
            [
                {
                    **_manifest(
                        manifest_id=str(index) * 64,
                        label="api_order",
                    ),
                    "scenario_observation": {
                        "position_count": 0,
                        "order_count": 1,
                    },
                }
                for index in range(1, 5)
            ],
            (
                _receipt(
                    E1EventType.FIXTURE_ACTION,
                    {
                        "fixture_namespace": "E1FIX",
                        "fixture_client_id": 9100,
                        "action": "PLACE",
                    },
                ),
            ),
            [
                {
                    "origin_evidence": "HAN_ALPHA_ORDER_REF",
                    "order_ref": "E1FIX:known",
                    "client_id": 9100,
                    "current_snapshot": True,
                    "future_manual_updates": False,
                    "completed_all_scope": False,
                }
            ],
            "ORDER_LIFECYCLE_OBSERVED",
        ),
        (
            E1ScenarioType.MANUAL_ORDER,
            E1ScopeName.ALL,
            [
                {
                    **_manifest(
                        manifest_id=str(index) * 64,
                        label="manual_order",
                    ),
                    "scenario_observation": {
                        "position_count": 0,
                        "order_count": 1,
                    },
                }
                for index in range(1, 5)
            ],
            (
                _receipt(
                    E1EventType.MANUAL_ACTION,
                    {"action": "PLACE", "operator_attested": True},
                ),
            ),
            [
                {
                    "origin_evidence": "CLIENT_ZERO_CALLBACK",
                    "order_ref": "",
                    "client_id": 0,
                    "current_snapshot": True,
                    "future_manual_updates": False,
                    "completed_all_scope": True,
                }
            ],
            "ORDER_LIFECYCLE_OBSERVED",
        ),
        (
            E1ScenarioType.PROCESS_RESTART,
            E1ScopeName.API,
            [
                {
                    **_manifest(manifest_id="1" * 64),
                    "process_boot_id": "one",
                },
                {
                    **_manifest(manifest_id="2" * 64),
                    "process_boot_id": "two",
                },
            ],
            (
                _receipt(E1EventType.PROCESS_BOOT, {"boot_id": "one"}, "PRE"),
                _receipt(E1EventType.PROCESS_BOOT, {"boot_id": "two"}),
            ),
            [],
            "PROCESS_BOOT_CHANGED_STATE_STABLE",
        ),
        (
            E1ScenarioType.TWS_RESTART,
            E1ScopeName.API,
            [
                _manifest(manifest_id="1" * 64),
                _manifest(manifest_id="2" * 64),
            ],
            (
                _receipt(
                    E1EventType.TWS_PROCESS,
                    {"instance_id": "one", "socket_state": "DOWN"},
                    "PRE",
                ),
                _receipt(
                    E1EventType.TWS_PROCESS,
                    {"instance_id": "two", "socket_state": "UP"},
                ),
            ),
            [],
            "TWS_INSTANCE_CHANGED_SOCKET_RECOVERED",
        ),
        (
            E1ScenarioType.NETWORK_RECOVERY,
            E1ScopeName.API,
            [
                _manifest(manifest_id="1" * 64),
                _manifest(manifest_id="2" * 64),
            ],
            (
                _receipt(
                    E1EventType.CONNECTIVITY,
                    {
                        "callback_codes": [1100, 1102],
                        "requests_reissued": True,
                        "loss_domain": "IB_SERVER",
                    },
                ),
            ),
            [],
            "CONNECTIVITY_LOST_AND_RECOVERED",
        ),
        (
            E1ScenarioType.NIGHTLY_RESET,
            E1ScopeName.API,
            [
                _manifest(manifest_id="1" * 64),
                _manifest(manifest_id="2" * 64),
            ],
            (
                _receipt(
                    E1EventType.NIGHTLY_MAINTENANCE,
                    {
                        "callback_codes": [1100, 1101],
                        "maintenance_window": True,
                    },
                ),
            ),
            [],
            "REAL_NIGHTLY_RESET_RECOVERED",
        ),
    ),
)
def test_each_scenario_requires_typed_evidence(
    scenario,
    scope,
    manifests,
    receipts,
    raw,
    transition,
) -> None:
    reasons: list[str] = []
    observed = e1_scenarios._evaluate_scenario(
        scenario,
        scope,
        manifests,
        receipts,
        raw,
        reasons,
    )
    assert observed == transition
    assert reasons == []


def test_event_detail_contracts_fail_closed() -> None:
    with pytest.raises(ValueError, match="details missing"):
        _receipt(E1EventType.CONNECTIVITY, {"callback_codes": []})
    with pytest.raises(ValueError, match="socket state"):
        _receipt(
            E1EventType.TWS_PROCESS,
            {"instance_id": "one", "socket_state": "MAYBE"},
        )


def test_raw_order_evidence_is_derived_from_tape_not_scenario_label(tmp_path) -> None:
    session_dir = tmp_path / "session"
    store = IBKRFactStore(session_dir / "tape.sqlite3")
    session_id = store.start_session(
        host="127.0.0.1",
        port=7497,
        client_id=41,
        at=NOW,
    )
    try:
        store.append(
            session_id=session_id,
            fact_type=IBKRFactType.REQUEST_START,
            identity_key="skip",
            payload={},
            received_at=NOW,
        )
        store.append(
            session_id=session_id,
            fact_type=IBKRFactType.OPEN_ORDER,
            identity_key="api",
            payload={
                "client_id": 9100,
                "order_ref": "E1FIX:known",
            },
            received_at=NOW,
        )
        store.append(
            session_id=session_id,
            fact_type=IBKRFactType.COMPLETED_ORDER,
            identity_key="manual",
            payload={"client_id": 0, "order_ref": ""},
            received_at=NOW,
        )
        store.append(
            session_id=session_id,
            fact_type=IBKRFactType.OPEN_ORDER,
            identity_key="unknown",
            payload={"client_id": 42, "order_ref": ""},
            received_at=NOW,
        )
    finally:
        store.close()
    evidence = e1_scenarios._session_order_evidence(
        session_dir,
        {
            "observation_id": session_id,
            "scope_policy": {
                "current_all_open_orders_snapshot_requested": True,
                "future_manual_order_updates_bound": False,
            },
            "completed_orders_scope": "all",
        },
    )
    assert {item["origin_evidence"] for item in evidence} == {
        "HAN_ALPHA_ORDER_REF",
        "CLIENT_ZERO_CALLBACK",
        "UNCLASSIFIED_CALLBACK",
    }
    assert all(item["current_snapshot"] for item in evidence)
    assert all(item["completed_all_scope"] for item in evidence)
    assert (
        e1_scenarios._session_order_evidence(
            tmp_path / "missing",
            {"observation_id": "none"},
        )
        == []
    )


def test_scenario_adversarial_paths_report_every_missing_proof() -> None:
    bad = _manifest(manifest_id="1" * 64, label="wrong")
    cases = (
        (
            E1ScenarioType.STATIC_POSITION,
            E1ScopeName.API,
            [bad],
            {
                "STATIC_POSITION_REQUIRES_FIVE_SESSIONS",
                "STATIC_POSITION_CHILD_LABEL_MISMATCH",
                "STATIC_POSITION_MISSING_POSITION",
            },
        ),
        (
            E1ScenarioType.API_ORDER,
            E1ScopeName.ALL,
            [bad],
            {
                "ORDER_SCENARIO_REQUIRES_FOUR_SESSIONS",
                "ORDER_CHILD_LABEL_MISMATCH",
                "ORDER_STATE_MISSING",
                "FIXTURE_ACTION_RECEIPT_MISSING",
                "FIXTURE_ORDER_ORIGIN_NOT_PROVEN",
                "API_ORDER_WRONG_SCOPE",
            },
        ),
        (
            E1ScenarioType.MANUAL_ORDER,
            E1ScopeName.API,
            [bad],
            {
                "MANUAL_ACTION_RECEIPT_MISSING",
                "MANUAL_CALLBACK_ORIGIN_NOT_PROVEN",
                "MANUAL_VISIBILITY_PATH_NOT_PROVEN",
                "MANUAL_ORDER_WRONG_SCOPE",
            },
        ),
        (
            E1ScenarioType.TWS_RESTART,
            E1ScopeName.API,
            [bad],
            {
                "SCENARIO_REQUIRES_EXACTLY_TWO_SESSIONS",
                "DISTINCT_TWS_INSTANCE_RECEIPTS_MISSING",
                "TWS_SOCKET_DOWN_UP_EVIDENCE_MISSING",
            },
        ),
        (
            E1ScenarioType.NETWORK_RECOVERY,
            E1ScopeName.API,
            [bad],
            {
                "DOCUMENTED_CONNECTIVITY_SEQUENCE_MISSING",
                "REQUEST_REISSUE_EVIDENCE_MISSING",
            },
        ),
        (
            E1ScenarioType.NIGHTLY_RESET,
            E1ScopeName.API,
            [bad],
            {
                "REAL_MAINTENANCE_WINDOW_EVIDENCE_MISSING",
                "NIGHTLY_RESET_CALLBACK_SEQUENCE_MISSING",
            },
        ),
        (
            E1ScenarioType.CLIENT_ID_SWITCH,
            E1ScopeName.API,
            [bad],
            {
                "DISTINCT_CLIENT_IDS_REQUIRED",
                "DISTINCT_SCOPE_HASHES_REQUIRED",
            },
        ),
    )
    for scenario, scope, manifests, expected in cases:
        reasons: list[str] = []
        e1_scenarios._evaluate_scenario(
            scenario,
            scope,
            manifests,
            (),
            [],
            reasons,
        )
        assert expected <= set(reasons)


def test_binding_and_receipt_loaders_reject_cross_evidence(tmp_path) -> None:
    first = _manifest(manifest_id="1" * 64)
    second = {
        **_manifest(
            manifest_id="2" * 64,
            scope_hash="9" * 64,
        ),
        "git_commit": "9" * 40,
        "tws_server_version": "189",
        "ibapi_version": "10.49",
        "safety_case_eligible": False,
    }
    mismatched_receipt = create_event_receipt(
        event_type=E1EventType.PROCESS_BOOT,
        phase="POST",
        observed_at=NOW,
        account_identity_hash="9" * 64,
        git_commit="8" * 40,
        config_hash="7" * 64,
        details={"boot_id": "one"},
    )
    reasons: list[str] = []
    e1_scenarios._check_common_bindings(
        [first, second],
        (mismatched_receipt,),
        E1ScenarioType.PROCESS_RESTART,
        reasons,
    )
    assert {
        "MIXED_OR_MISSING_GIT_COMMIT",
        "MIXED_SCOPE_OUTSIDE_CLIENT_SWITCH",
        "MIXED_TWS_VERSION_WITHOUT_COMPATIBILITY_CASE",
        "MIXED_IBAPI_VERSION_WITHOUT_COMPATIBILITY_CASE",
        "CHILD_SESSION_NOT_ELIGIBLE",
        "EVENT_RECEIPT_ACCOUNT_MISMATCH",
        "EVENT_RECEIPT_COMMIT_MISMATCH",
        "EVENT_RECEIPT_CONFIG_MISMATCH",
    } <= set(reasons)
    receipt_path = tmp_path / "receipt.json"
    write_immutable_json(receipt_path, mismatched_receipt.model_dump(mode="json"))
    assert e1_scenarios.read_event_receipts((receipt_path,)) == (mismatched_receipt,)
    with pytest.raises(ValueError, match="operator attestation"):
        _receipt(
            E1EventType.MANUAL_ACTION,
            {"action": "PLACE", "operator_attested": False},
        )


def _rehash(document: dict[str, object]) -> dict[str, object]:
    body = {key: value for key, value in document.items() if key != "artifact_id"}
    return {"artifact_id": canonical_hash(body), **body}


def test_event_receipt_model_rejects_tampered_period_phase_and_redaction() -> None:
    valid = _receipt(E1EventType.PROCESS_BOOT, {"boot_id": "one"}).model_dump(mode="json")
    with pytest.raises(ValueError, match="timezone-aware"):
        e1_scenarios.E1EventReceipt.model_validate(
            _rehash({**valid, "observed_at": "2026-01-01T00:00:00"})
        )
    with pytest.raises(ValueError, match="phase is required"):
        e1_scenarios.E1EventReceipt.model_validate(_rehash({**valid, "phase": " "}))
    with pytest.raises(ValueError, match="must be redacted"):
        e1_scenarios.E1EventReceipt.model_validate(_rehash({**valid, "secrets_redacted": False}))
    with pytest.raises(ValueError, match="artifact_id mismatch"):
        e1_scenarios.E1EventReceipt.model_validate({**valid, "artifact_id": "0" * 64})


def test_scenario_case_model_rejects_invalid_authority_shapes() -> None:
    manifests = [
        _manifest(
            manifest_id="1" * 64,
            client_id=41,
            scope_hash="4" * 64,
        ),
        _manifest(
            manifest_id="2" * 64,
            client_id=42,
            scope_hash="5" * 64,
        ),
    ]
    valid = e1_scenarios._scenario_case_document(
        scenario_type=E1ScenarioType.CLIENT_ID_SWITCH,
        scope=E1ScopeName.API,
        manifests=manifests,
        receipts=(),
        expected_transition="CROSS_SCOPE",
        observed_transition="COMPATIBLE",
        reasons=[],
        effective_from=NOW,
        expires_at=NOW + timedelta(days=1),
    ).model_dump(mode="json")
    invalid_documents = (
        ({**valid, "expires_at": valid["effective_from"]}, "expiry"),
        ({**valid, "decision": "UNKNOWN"}, "unsupported"),
        ({**valid, "reasons": ["unexpected"]}, "cannot contain reasons"),
        ({**valid, "child_session_manifest_ids": []}, "requires child"),
        (
            {**valid, "child_session_manifest_ids": ["1" * 64, "1" * 64]},
            "must be unique",
        ),
        ({**valid, "secrets_redacted": False}, "must be redacted"),
    )
    for document, message in invalid_documents:
        with pytest.raises(ValueError, match=message):
            e1_scenarios.E1ScenarioCase.model_validate(_rehash(document))
    with pytest.raises(ValueError, match="artifact_id mismatch"):
        e1_scenarios.E1ScenarioCase.model_validate({**valid, "artifact_id": "0" * 64})
