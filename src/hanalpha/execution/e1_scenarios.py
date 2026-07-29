from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python

from hanalpha.execution.burn_in import verify_burn_in_manifest
from hanalpha.execution.ibkr_observer import IBKRFactStore, IBKRFactType
from hanalpha.simulation.events import canonical_hash


class E1ScopeName(StrEnum):
    API = "api"
    ALL = "all"


class E1ScenarioType(StrEnum):
    STATIC_POSITION = "static_position"
    API_ORDER = "api_order"
    MANUAL_ORDER = "manual_order"
    PROCESS_RESTART = "process_restart"
    TWS_RESTART = "tws_restart"
    NETWORK_RECOVERY = "network_recovery"
    NIGHTLY_RESET = "nightly_reset"
    CLIENT_ID_SWITCH = "client_id_switch"


class E1EventType(StrEnum):
    PROCESS_BOOT = "PROCESS_BOOT"
    TWS_PROCESS = "TWS_PROCESS"
    CONNECTIVITY = "CONNECTIVITY"
    NIGHTLY_MAINTENANCE = "NIGHTLY_MAINTENANCE"
    FIXTURE_ACTION = "FIXTURE_ACTION"
    MANUAL_ACTION = "MANUAL_ACTION"


class E1EventReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "e1-event-receipt-v1"
    artifact_type: str = "E1_EVENT_RECEIPT"
    artifact_id: str
    event_type: E1EventType
    phase: str
    observed_at: datetime
    account_identity_hash: str = Field(min_length=64, max_length=64)
    git_commit: str = Field(min_length=7)
    config_hash: str = Field(min_length=64, max_length=64)
    details: dict[str, Any]
    secrets_redacted: bool = True

    @model_validator(mode="after")
    def validate_receipt(self) -> E1EventReceipt:
        if not self.observed_at.tzinfo:
            raise ValueError("receipt observed_at must be timezone-aware")
        if not self.phase.strip():
            raise ValueError("receipt phase is required")
        if not self.secrets_redacted:
            raise ValueError("event receipts must be redacted")
        body = self.model_dump(mode="json", exclude={"artifact_id"})
        if self.artifact_id != canonical_hash(body):
            raise ValueError("event receipt artifact_id mismatch")
        _validate_event_details(self.event_type, self.details)
        return self


class E1ScenarioCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "e1-scenario-case-v2"
    artifact_type: str = "E1_SCENARIO_CASE"
    artifact_id: str
    scenario_type: E1ScenarioType
    scope: E1ScopeName
    account_identity_hash: str = Field(min_length=64, max_length=64)
    git_commit: str = Field(min_length=7)
    config_hash: str = Field(min_length=64, max_length=64)
    normalization_policy_hash: str = Field(min_length=64, max_length=64)
    child_session_manifest_ids: tuple[str, ...]
    event_receipt_ids: tuple[str, ...]
    evidence_set_hash: str = Field(min_length=64, max_length=64)
    expected_transition: str
    observed_transition: str
    decision: str
    reasons: tuple[str, ...]
    effective_from: datetime
    expires_at: datetime
    tws_server_versions: tuple[str, ...]
    ibapi_versions: tuple[str, ...]
    scope_hashes: tuple[str, ...]
    client_ids: tuple[int, ...]
    secrets_redacted: bool = True

    @model_validator(mode="after")
    def validate_case(self) -> E1ScenarioCase:
        if not self.effective_from.tzinfo or not self.expires_at.tzinfo:
            raise ValueError("scenario case period must be timezone-aware")
        if self.expires_at <= self.effective_from:
            raise ValueError("scenario case expiry must follow effective time")
        if self.decision not in {"PASS", "BLOCKED"}:
            raise ValueError("unsupported scenario case decision")
        if self.decision == "PASS" and self.reasons:
            raise ValueError("passing scenario case cannot contain reasons")
        if not self.child_session_manifest_ids:
            raise ValueError("scenario case requires child sessions")
        if len(set(self.child_session_manifest_ids)) != len(self.child_session_manifest_ids):
            raise ValueError("scenario case child sessions must be unique")
        expected_evidence_set_hash = canonical_hash(
            {
                "scenario_type": self.scenario_type,
                "child_session_manifest_ids": sorted(self.child_session_manifest_ids),
                "event_receipt_ids": sorted(self.event_receipt_ids),
            }
        )
        if self.evidence_set_hash != expected_evidence_set_hash:
            raise ValueError("scenario case evidence-set hash mismatch")
        if not self.secrets_redacted:
            raise ValueError("scenario cases must be redacted")
        body = self.model_dump(mode="json", exclude={"artifact_id"})
        if self.artifact_id != canonical_hash(body):
            raise ValueError("scenario case artifact_id mismatch")
        return self


class E1AcceptancePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "e1-acceptance-policy-v3"
    scope: E1ScopeName
    minimum_unique_sessions: int = Field(ge=1)
    minimum_scope_sessions: int = Field(ge=1)
    minimum_cross_scope_sessions: int = Field(ge=1)
    session_requirements: dict[str, int]
    scenario_case_requirements: dict[str, int]

    @model_validator(mode="after")
    def validate_topology(self) -> E1AcceptancePolicy:
        cross_scope = self.session_requirements.get("client_id_switch", 0)
        if sum(self.session_requirements.values()) != self.minimum_unique_sessions:
            raise ValueError("session matrix and total threshold disagree")
        if cross_scope != self.minimum_cross_scope_sessions:
            raise ValueError("client-switch matrix and cross-scope threshold disagree")
        if (
            self.minimum_scope_sessions + self.minimum_cross_scope_sessions
            != self.minimum_unique_sessions
        ):
            raise ValueError("scope topology and total threshold disagree")
        return self


E1_ACCEPTANCE_POLICIES: dict[E1ScopeName, E1AcceptancePolicy] = {
    E1ScopeName.API: E1AcceptancePolicy(
        scope=E1ScopeName.API,
        minimum_unique_sessions=34,
        minimum_scope_sessions=30,
        minimum_cross_scope_sessions=4,
        session_requirements={
            "empty_account": 5,
            "static_position": 5,
            "api_order": 4,
            "process_restart": 6,
            "tws_restart": 4,
            "network_recovery": 4,
            "nightly_reset": 2,
            "client_id_switch": 4,
        },
        scenario_case_requirements={
            "static_position": 1,
            "api_order": 1,
            "process_restart": 3,
            "tws_restart": 2,
            "network_recovery": 2,
            "nightly_reset": 1,
            "client_id_switch": 2,
        },
    ),
    E1ScopeName.ALL: E1AcceptancePolicy(
        scope=E1ScopeName.ALL,
        minimum_unique_sessions=16,
        minimum_scope_sessions=14,
        minimum_cross_scope_sessions=2,
        session_requirements={
            "manual_order": 4,
            "process_restart": 4,
            "tws_restart": 4,
            "network_recovery": 2,
            "client_id_switch": 2,
        },
        scenario_case_requirements={
            "manual_order": 1,
            "process_restart": 2,
            "tws_restart": 2,
            "network_recovery": 1,
            "client_id_switch": 1,
        },
    ),
}


def create_event_receipt(
    *,
    event_type: E1EventType,
    phase: str,
    observed_at: datetime,
    account_identity_hash: str,
    git_commit: str,
    config_hash: str,
    details: Mapping[str, Any],
) -> E1EventReceipt:
    body = {
        "schema_version": "e1-event-receipt-v1",
        "artifact_type": "E1_EVENT_RECEIPT",
        "event_type": event_type,
        "phase": phase.strip(),
        "observed_at": observed_at.astimezone(UTC),
        "account_identity_hash": account_identity_hash,
        "git_commit": git_commit,
        "config_hash": config_hash,
        "details": dict(details),
        "secrets_redacted": True,
    }
    normalized = to_jsonable_python(body)
    return E1EventReceipt.model_validate({"artifact_id": canonical_hash(normalized), **normalized})


def build_scenario_case(
    *,
    scenario_type: E1ScenarioType,
    scope: E1ScopeName,
    session_dirs: Iterable[Path],
    event_receipts: Iterable[E1EventReceipt],
    effective_from: datetime,
    expires_at: datetime,
) -> E1ScenarioCase:
    manifests: list[dict[str, Any]] = []
    raw_order_evidence: list[dict[str, Any]] = []
    reasons: list[str] = []
    for session_dir in sorted(session_dirs):
        verification = verify_burn_in_manifest(session_dir)
        if not verification.verified:
            reasons.append(f"INVALID_SESSION:{session_dir.name}")
            continue
        manifests.append(verification.manifest)
        raw_order_evidence.extend(_session_order_evidence(session_dir, verification.manifest))
    receipts = tuple(sorted(event_receipts, key=lambda item: item.artifact_id))
    if not manifests:
        reasons.append("NO_VALID_CHILD_SESSIONS")
        return _scenario_case_document(
            scenario_type=scenario_type,
            scope=scope,
            manifests=manifests,
            receipts=receipts,
            expected_transition=_expected_transition(scenario_type),
            observed_transition="NO_VALID_CHILD_SESSIONS",
            reasons=reasons,
            effective_from=effective_from,
            expires_at=expires_at,
        )
    _check_common_bindings(manifests, receipts, scenario_type, reasons)
    observed = _evaluate_scenario(
        scenario_type,
        scope,
        manifests,
        receipts,
        raw_order_evidence,
        reasons,
    )
    return _scenario_case_document(
        scenario_type=scenario_type,
        scope=scope,
        manifests=manifests,
        receipts=receipts,
        expected_transition=_expected_transition(scenario_type),
        observed_transition=observed,
        reasons=reasons,
        effective_from=effective_from,
        expires_at=expires_at,
    )


def load_scenario_cases(paths: Iterable[Path]) -> tuple[E1ScenarioCase, ...]:
    cases: list[E1ScenarioCase] = []
    for path in sorted(paths):
        cases.append(E1ScenarioCase.model_validate_json(path.read_text(encoding="utf-8")))
    return tuple(cases)


def scenario_case_counts(
    cases: Iterable[E1ScenarioCase],
    *,
    scope: E1ScopeName,
    at: datetime,
    corpus_manifest_ids: Iterable[str] | None = None,
    cross_scope_manifest_ids: Iterable[str] = (),
    available_receipt_ids: Iterable[str] | None = None,
) -> Counter[str]:
    return allocate_scenario_cases(
        cases,
        scope=scope,
        at=at,
        corpus_manifest_ids=corpus_manifest_ids,
        cross_scope_manifest_ids=cross_scope_manifest_ids,
        available_receipt_ids=available_receipt_ids,
    )[0]


def allocate_scenario_cases(
    cases: Iterable[E1ScenarioCase],
    *,
    scope: E1ScopeName,
    at: datetime,
    corpus_manifest_ids: Iterable[str] | None,
    cross_scope_manifest_ids: Iterable[str] = (),
    available_receipt_ids: Iterable[str] | None = None,
) -> tuple[Counter[str], dict[str, tuple[str, ...]]]:
    """Allocate immutable case evidence once for one acceptance evaluation.

    Child sessions and event receipts are exclusive by default. Client-switch is
    the only cross-scope topology and must draw every child from the explicitly
    supplied union of the current and named cross-scope corpora.
    """

    current = set(corpus_manifest_ids or ())
    cross = set(cross_scope_manifest_ids)
    available_receipts = set(available_receipt_ids or ())
    enforce_membership = corpus_manifest_ids is not None
    enforce_receipt_resolution = available_receipt_ids is not None
    consumed_sessions: set[str] = set()
    consumed_receipts: set[str] = set()
    consumed_evidence_sets: set[str] = set()
    counts: Counter[str] = Counter()
    rejected: dict[str, tuple[str, ...]] = {}
    for item in sorted(cases, key=lambda case: case.artifact_id):
        reasons: list[str] = []
        children = set(item.child_session_manifest_ids)
        receipts = set(item.event_receipt_ids)
        if item.scope is not scope:
            reasons.append("CASE_SCOPE_MISMATCH")
        if item.decision != "PASS":
            reasons.append("CASE_NOT_PASSING")
        if not item.effective_from <= at <= item.expires_at:
            reasons.append("CASE_OUTSIDE_VALIDITY")
        if item.evidence_set_hash in consumed_evidence_sets:
            reasons.append("DUPLICATE_EVIDENCE_SET")
        if enforce_membership:
            if item.scenario_type is E1ScenarioType.CLIENT_ID_SWITCH:
                allowed = current | cross
                if (
                    not children <= allowed
                    or not children & cross
                    or len(item.scope_hashes) < 2
                    or len(item.client_ids) < 2
                ):
                    reasons.append("CROSS_SCOPE_TOPOLOGY_INVALID")
            elif not children <= current:
                reasons.append("CHILD_SESSION_OUTSIDE_CURRENT_CORPUS")
        if children & consumed_sessions:
            reasons.append("CHILD_SESSION_ALREADY_ALLOCATED")
        if receipts & consumed_receipts:
            reasons.append("EVENT_RECEIPT_ALREADY_ALLOCATED")
        if enforce_receipt_resolution and not receipts <= available_receipts:
            reasons.append("EVENT_RECEIPT_NOT_RESOLVABLE")
        if reasons:
            rejected[item.artifact_id] = tuple(sorted(set(reasons)))
            continue
        counts[item.scenario_type.value] += 1
        consumed_sessions.update(children)
        consumed_receipts.update(receipts)
        consumed_evidence_sets.add(item.evidence_set_hash)
    return counts, rejected


def _scenario_case_document(
    *,
    scenario_type: E1ScenarioType,
    scope: E1ScopeName,
    manifests: list[dict[str, Any]],
    receipts: tuple[E1EventReceipt, ...],
    expected_transition: str,
    observed_transition: str,
    reasons: list[str],
    effective_from: datetime,
    expires_at: datetime,
) -> E1ScenarioCase:
    first = manifests[0] if manifests else {}
    body = {
        "schema_version": "e1-scenario-case-v2",
        "artifact_type": "E1_SCENARIO_CASE",
        "scenario_type": scenario_type,
        "scope": scope,
        "account_identity_hash": str(first.get("account_identity_hash", "0" * 64)),
        "git_commit": str(first.get("git_commit", "MISSING")),
        "config_hash": str(first.get("config_hash", "0" * 64)),
        "normalization_policy_hash": str(first.get("normalization_policy_hash", "0" * 64)),
        "child_session_manifest_ids": tuple(
            sorted(str(item.get("manifest_id")) for item in manifests)
        ),
        "event_receipt_ids": tuple(item.artifact_id for item in receipts),
        "evidence_set_hash": canonical_hash(
            {
                "scenario_type": scenario_type,
                "child_session_manifest_ids": sorted(
                    str(item.get("manifest_id")) for item in manifests
                ),
                "event_receipt_ids": sorted(item.artifact_id for item in receipts),
            }
        ),
        "expected_transition": expected_transition,
        "observed_transition": observed_transition,
        "decision": "PASS" if not reasons else "BLOCKED",
        "reasons": tuple(sorted(set(reasons))),
        "effective_from": effective_from.astimezone(UTC),
        "expires_at": expires_at.astimezone(UTC),
        "tws_server_versions": tuple(
            sorted({str(item.get("tws_server_version")) for item in manifests})
        ),
        "ibapi_versions": tuple(sorted({str(item.get("ibapi_version")) for item in manifests})),
        "scope_hashes": tuple(sorted({str(item.get("scope_hash")) for item in manifests})),
        "client_ids": tuple(sorted({int(item.get("client_id", -1)) for item in manifests})),
        "secrets_redacted": True,
    }
    normalized = to_jsonable_python(body)
    return E1ScenarioCase.model_validate({"artifact_id": canonical_hash(normalized), **normalized})


def _check_common_bindings(
    manifests: list[dict[str, Any]],
    receipts: tuple[E1EventReceipt, ...],
    scenario_type: E1ScenarioType,
    reasons: list[str],
) -> None:
    fields = (
        "account_identity_hash",
        "git_commit",
        "config_hash",
        "normalization_policy_hash",
    )
    for field in fields:
        values = {str(item.get(field)) for item in manifests}
        if len(values) != 1 or values == {"None"}:
            reasons.append(f"MIXED_OR_MISSING_{field.upper()}")
    if scenario_type is not E1ScenarioType.CLIENT_ID_SWITCH:
        scopes = {str(item.get("scope_hash")) for item in manifests}
        if len(scopes) != 1:
            reasons.append("MIXED_SCOPE_OUTSIDE_CLIENT_SWITCH")
    tws_versions = {str(item.get("tws_server_version")) for item in manifests}
    ibapi_versions = {str(item.get("ibapi_version")) for item in manifests}
    if len(tws_versions) != 1:
        reasons.append("MIXED_TWS_VERSION_WITHOUT_COMPATIBILITY_CASE")
    if len(ibapi_versions) != 1:
        reasons.append("MIXED_IBAPI_VERSION_WITHOUT_COMPATIBILITY_CASE")
    if any(item.get("safety_case_eligible") is not True for item in manifests):
        reasons.append("CHILD_SESSION_NOT_ELIGIBLE")
    expected_account = str(manifests[0].get("account_identity_hash"))
    expected_commit = str(manifests[0].get("git_commit"))
    expected_config = str(manifests[0].get("config_hash"))
    for receipt in receipts:
        if receipt.account_identity_hash != expected_account:
            reasons.append("EVENT_RECEIPT_ACCOUNT_MISMATCH")
        if receipt.git_commit != expected_commit:
            reasons.append("EVENT_RECEIPT_COMMIT_MISMATCH")
        if receipt.config_hash != expected_config:
            reasons.append("EVENT_RECEIPT_CONFIG_MISMATCH")


def _evaluate_scenario(
    scenario: E1ScenarioType,
    scope: E1ScopeName,
    manifests: list[dict[str, Any]],
    receipts: tuple[E1EventReceipt, ...],
    raw_order_evidence: list[dict[str, Any]],
    reasons: list[str],
) -> str:
    labels = Counter(str(item.get("capture_scenario")) for item in manifests)
    receipt_types = Counter(item.event_type for item in receipts)
    if scenario is E1ScenarioType.STATIC_POSITION:
        if len(manifests) < 5:
            reasons.append("STATIC_POSITION_REQUIRES_FIVE_SESSIONS")
        if labels[scenario.value] != len(manifests):
            reasons.append("STATIC_POSITION_CHILD_LABEL_MISMATCH")
        if any(
            int(item.get("scenario_observation", {}).get("position_count", 0)) < 1
            for item in manifests
        ):
            reasons.append("STATIC_POSITION_MISSING_POSITION")
        _require_equal_hash(manifests, "positions_hash", reasons, "POSITION_NOT_STABLE")
        _require_equal_hash(manifests, "orders_hash", reasons, "UNEXPECTED_ORDER_MUTATION")
        _require_equal_hash(manifests, "executions_hash", reasons, "UNEXPECTED_EXECUTION_MUTATION")
        return "STABLE_POSITION_STATE"
    if scenario in {E1ScenarioType.API_ORDER, E1ScenarioType.MANUAL_ORDER}:
        if len(manifests) < 4:
            reasons.append("ORDER_SCENARIO_REQUIRES_FOUR_SESSIONS")
        if labels[scenario.value] != len(manifests):
            reasons.append("ORDER_CHILD_LABEL_MISMATCH")
        if any(
            int(item.get("scenario_observation", {}).get("order_count", 0)) < 1
            for item in manifests
        ):
            reasons.append("ORDER_STATE_MISSING")
        required_receipt = (
            E1EventType.FIXTURE_ACTION
            if scenario is E1ScenarioType.API_ORDER
            else E1EventType.MANUAL_ACTION
        )
        if receipt_types[required_receipt] < 1:
            reasons.append(f"{required_receipt.value}_RECEIPT_MISSING")
        if scenario is E1ScenarioType.API_ORDER:
            fixture_client_ids = {
                int(item.details["fixture_client_id"])
                for item in receipts
                if item.event_type is E1EventType.FIXTURE_ACTION
            }
            if not any(
                item["origin_evidence"] == "HAN_ALPHA_ORDER_REF"
                and item["order_ref"].startswith("E1FIX:")
                and item["client_id"] in fixture_client_ids
                for item in raw_order_evidence
            ):
                reasons.append("FIXTURE_ORDER_ORIGIN_NOT_PROVEN")
        else:
            if not any(
                item["client_id"] == 0 and not item["order_ref"].startswith(("HA:", "E1FIX:"))
                for item in raw_order_evidence
            ):
                reasons.append("MANUAL_CALLBACK_ORIGIN_NOT_PROVEN")
            if not any(
                item["current_snapshot"]
                or item["future_manual_updates"]
                or item["completed_all_scope"]
                for item in raw_order_evidence
            ):
                reasons.append("MANUAL_VISIBILITY_PATH_NOT_PROVEN")
        if scenario is E1ScenarioType.API_ORDER and scope is not E1ScopeName.API:
            reasons.append("API_ORDER_WRONG_SCOPE")
        if scenario is E1ScenarioType.MANUAL_ORDER and scope is not E1ScopeName.ALL:
            reasons.append("MANUAL_ORDER_WRONG_SCOPE")
        return "ORDER_LIFECYCLE_OBSERVED"
    if scenario is E1ScenarioType.PROCESS_RESTART:
        _require_two_sessions(manifests, reasons)
        session_boots = {
            str(item.get("process_boot_id")) for item in manifests if item.get("process_boot_id")
        }
        boots = {
            str(item.details.get("boot_id"))
            for item in receipts
            if item.event_type is E1EventType.PROCESS_BOOT
        }
        if len(boots) < 2:
            reasons.append("DISTINCT_PROCESS_BOOT_RECEIPTS_MISSING")
        if len(session_boots) != 2 or boots != session_boots:
            reasons.append("PROCESS_BOOT_RECEIPTS_NOT_BOUND_TO_SESSIONS")
        _require_equal_hash(manifests, "semantic_hash", reasons, "POST_RESTART_STATE_DIVERGED")
        return "PROCESS_BOOT_CHANGED_STATE_STABLE"
    if scenario is E1ScenarioType.TWS_RESTART:
        _require_two_sessions(manifests, reasons)
        instances = {
            str(item.details.get("instance_id"))
            for item in receipts
            if item.event_type is E1EventType.TWS_PROCESS
        }
        socket_states = {
            str(item.details.get("socket_state"))
            for item in receipts
            if item.event_type is E1EventType.TWS_PROCESS
        }
        if len(instances) < 2:
            reasons.append("DISTINCT_TWS_INSTANCE_RECEIPTS_MISSING")
        if not {"DOWN", "UP"} <= socket_states:
            reasons.append("TWS_SOCKET_DOWN_UP_EVIDENCE_MISSING")
        _require_equal_hash(manifests, "semantic_hash", reasons, "POST_TWS_STATE_DIVERGED")
        return "TWS_INSTANCE_CHANGED_SOCKET_RECOVERED"
    if scenario is E1ScenarioType.NETWORK_RECOVERY:
        _require_two_sessions(manifests, reasons)
        connectivity = [item for item in receipts if item.event_type is E1EventType.CONNECTIVITY]
        codes = {
            int(code) for item in connectivity for code in item.details.get("callback_codes", [])
        }
        if 1100 not in codes or not ({1101, 1102} & codes):
            reasons.append("DOCUMENTED_CONNECTIVITY_SEQUENCE_MISSING")
        if not any(item.details.get("requests_reissued") is True for item in connectivity):
            reasons.append("REQUEST_REISSUE_EVIDENCE_MISSING")
        return "CONNECTIVITY_LOST_AND_RECOVERED"
    if scenario is E1ScenarioType.NIGHTLY_RESET:
        _require_two_sessions(manifests, reasons)
        nightly = [item for item in receipts if item.event_type is E1EventType.NIGHTLY_MAINTENANCE]
        if not any(item.details.get("maintenance_window") is True for item in nightly):
            reasons.append("REAL_MAINTENANCE_WINDOW_EVIDENCE_MISSING")
        codes = {int(code) for item in nightly for code in item.details.get("callback_codes", [])}
        if 1100 not in codes or not ({1101, 1102} & codes):
            reasons.append("NIGHTLY_RESET_CALLBACK_SEQUENCE_MISSING")
        _require_equal_hash(manifests, "semantic_hash", reasons, "POST_NIGHTLY_STATE_DIVERGED")
        return "REAL_NIGHTLY_RESET_RECOVERED"
    if scenario is E1ScenarioType.CLIENT_ID_SWITCH:
        _require_two_sessions(manifests, reasons)
        clients = {int(item.get("client_id", -1)) for item in manifests}
        scopes = {str(item.get("scope_hash")) for item in manifests}
        if len(clients) != 2:
            reasons.append("DISTINCT_CLIENT_IDS_REQUIRED")
        if len(scopes) != 2:
            reasons.append("DISTINCT_SCOPE_HASHES_REQUIRED")
        _require_equal_hash(
            manifests, "semantic_hash", reasons, "CROSS_SCOPE_BROKER_STATE_DIVERGED"
        )
        return "CLIENT_AND_SCOPE_CHANGED_STATE_COMPATIBLE"
    reasons.append("UNSUPPORTED_SCENARIO")
    return "UNSUPPORTED"


def _require_two_sessions(manifests: list[dict[str, Any]], reasons: list[str]) -> None:
    if len(manifests) != 2:
        reasons.append("SCENARIO_REQUIRES_EXACTLY_TWO_SESSIONS")


def _require_equal_hash(
    manifests: list[dict[str, Any]],
    field: str,
    reasons: list[str],
    reason: str,
) -> None:
    values = {str(item.get(field)) for item in manifests}
    if len(values) != 1 or values == {"None"}:
        reasons.append(reason)


def _expected_transition(scenario: E1ScenarioType) -> str:
    return {
        E1ScenarioType.STATIC_POSITION: "POSITION_STABLE",
        E1ScenarioType.API_ORDER: "FIXTURE_ORDER_LIFECYCLE",
        E1ScenarioType.MANUAL_ORDER: "MANUAL_ORDER_LIFECYCLE",
        E1ScenarioType.PROCESS_RESTART: "PROCESS_BOOT_CHANGES_BROKER_STATE_STABLE",
        E1ScenarioType.TWS_RESTART: "TWS_INSTANCE_CHANGES_SOCKET_RECOVERS",
        E1ScenarioType.NETWORK_RECOVERY: "CONNECTIVITY_1100_TO_1101_OR_1102",
        E1ScenarioType.NIGHTLY_RESET: "REAL_MAINTENANCE_RESET_RECOVERS",
        E1ScenarioType.CLIENT_ID_SWITCH: "CROSS_SCOPE_STATE_COMPATIBLE",
    }[scenario]


def _validate_event_details(event_type: E1EventType, details: Mapping[str, Any]) -> None:
    forbidden_fragments = {
        "account",
        "cookie",
        "credential",
        "password",
        "secret",
        "token",
    }
    for key in details:
        normalized = str(key).lower().replace("-", "_")
        if any(fragment in normalized for fragment in forbidden_fragments):
            raise ValueError(f"event receipt detail key is forbidden: {key}")
    required: dict[E1EventType, set[str]] = {
        E1EventType.PROCESS_BOOT: {"boot_id"},
        E1EventType.TWS_PROCESS: {"instance_id", "socket_state"},
        E1EventType.CONNECTIVITY: {
            "callback_codes",
            "requests_reissued",
            "loss_domain",
        },
        E1EventType.NIGHTLY_MAINTENANCE: {
            "callback_codes",
            "maintenance_window",
        },
        E1EventType.FIXTURE_ACTION: {
            "fixture_namespace",
            "fixture_client_id",
            "action",
        },
        E1EventType.MANUAL_ACTION: {"action", "operator_attested"},
    }
    missing = required[event_type] - details.keys()
    if missing:
        raise ValueError(f"event receipt details missing: {','.join(sorted(missing))}")
    if event_type is E1EventType.TWS_PROCESS and details["socket_state"] not in {
        "UP",
        "DOWN",
    }:
        raise ValueError("unsupported TWS socket state")
    if event_type is E1EventType.MANUAL_ACTION and details["operator_attested"] is not True:
        raise ValueError("manual action receipt requires operator attestation")


def _session_order_evidence(
    session_dir: Path,
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    tape_path = session_dir / "tape.sqlite3"
    if not tape_path.is_file():
        return []
    store = IBKRFactStore(tape_path)
    try:
        facts = store.facts(str(manifest.get("observation_id", "")))
    finally:
        store.close()
    scope_policy = manifest.get("scope_policy", {})
    if not isinstance(scope_policy, dict):
        scope_policy = {}
    result: list[dict[str, Any]] = []
    for fact in facts:
        if fact.fact_type not in {
            IBKRFactType.OPEN_ORDER,
            IBKRFactType.COMPLETED_ORDER,
        }:
            continue
        order_ref = str(fact.payload.get("order_ref", ""))
        client_id = int(fact.payload.get("client_id", -1))
        result.append(
            {
                "fact_type": fact.fact_type.value,
                "client_id": client_id,
                "order_ref": order_ref,
                "origin_evidence": str(
                    fact.payload.get(
                        "origin_evidence",
                        (
                            "HAN_ALPHA_ORDER_REF"
                            if order_ref.startswith(("HA:", "E1FIX:"))
                            else "CLIENT_ZERO_CALLBACK"
                            if client_id == 0
                            else "UNCLASSIFIED_CALLBACK"
                        ),
                    )
                ),
                "current_snapshot": scope_policy.get("current_all_open_orders_snapshot_requested")
                is True,
                "future_manual_updates": scope_policy.get("future_manual_order_updates_bound")
                is True,
                "completed_all_scope": manifest.get("completed_orders_scope") == "all",
            }
        )
    return result


def read_event_receipts(paths: Iterable[Path]) -> tuple[E1EventReceipt, ...]:
    return tuple(
        E1EventReceipt.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(paths)
    )
