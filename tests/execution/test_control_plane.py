from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from hanalpha.domain.enums import Side
from hanalpha.execution.control_models import (
    BrokerSnapshot,
    DecisionCapsule,
    ExecutionIntent,
    ExecutionStatus,
    OutboxStatus,
    RiskReservation,
)
from hanalpha.execution.control_store import DurableExecutionStore, ExecutionInvariantError
from hanalpha.execution.fake_broker import (
    DurableFakeBroker,
    FakeScenario,
    StaleFencingToken,
)
from hanalpha.execution.reconciliation import Reconciler
from hanalpha.execution.worker import ExecutionWorker
from hanalpha.simulation.events import canonical_hash

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def _contracts(*, approval_required: bool = False, discriminator: str = "base"):
    def digest(label: str) -> str:
        return canonical_hash({"label": label, "case": discriminator})

    capsule = DecisionCapsule(
        decision_id=digest("decision"),
        decision_snapshot_id=digest("decision-snapshot"),
        market_snapshot_id=digest("market-snapshot"),
        evidence_snapshot_id=digest("evidence-snapshot"),
        evidence_review_id=digest("evidence-review"),
        strategy_id="fixture-strategy",
        strategy_version="1",
        entity_id="inst-alpha",
        input_hash=digest("input"),
        signal_hash=digest("signal"),
        risk_policy_hash=digest("risk-policy"),
        risk_decision_hash=digest("risk-decision"),
        config_hash=digest("config"),
        created_at=NOW,
    )
    reservation = RiskReservation(
        reservation_id=digest("reservation"),
        decision_id=capsule.decision_id,
        account_id="paper-account",
        instrument_id="inst-alpha",
        cash_reserved=Decimal("1000"),
        notional_reserved=Decimal("1000"),
        risk_reserved=Decimal("100"),
        account_notional_capacity=Decimal("100000"),
        quantity_reserved=10,
        expires_at=NOW + timedelta(minutes=10),
        created_at=NOW,
    )
    intent = ExecutionIntent.create(
        capsule=capsule,
        reservation=reservation,
        side=Side.BUY,
        quantity=10,
        limit_price=Decimal("100"),
        stop_price=Decimal("90"),
        target_price=Decimal("120"),
        approval_required=approval_required,
    )
    return capsule, reservation, intent


def _unfreeze(store: DurableExecutionStore, broker: DurableFakeBroker) -> None:
    report = Reconciler(store).reconcile(broker.snapshot(at=NOW), at=NOW)
    assert report.status == "CONVERGED"
    assert store.is_frozen() == (False, "")


def _allow_fixture_staging(store: DurableExecutionStore) -> None:
    """Tests that do not exercise reconciliation explicitly establish a fixture authority."""
    store.unfreeze_after_reconciliation(at=NOW)


def _record_authority(store: DurableExecutionStore, *, discriminator: str = "authority") -> str:
    semantic_hash = canonical_hash({"semantic": discriminator})
    snapshot = BrokerSnapshot(
        as_of=NOW,
        cash=Decimal("100000"),
        complete=True,
        completeness_certificate_id=canonical_hash({"certificate": discriminator}),
        semantic_hash=semantic_hash,
        visibility_scope_hash=canonical_hash({"scope": discriminator}),
        orders=(),
        positions={},
        protections={},
        events=(),
    )
    assert store.record_broker_snapshot_authority(
        snapshot,
        reconciliation_run_id=canonical_hash({"run": discriminator}),
        reconciliation_status="CONVERGED",
        at=NOW,
    )
    return str(snapshot.completeness_certificate_id)


def _record_quote(
    store: DurableExecutionStore,
    *,
    at: datetime = NOW,
    provider: str = "fixture",
    venue: str = "SMART",
    currency: str = "USD",
) -> str:
    return store.record_quote_snapshot(
        symbol="inst-alpha",
        bid=Decimal("100.01"),
        ask=Decimal("100.02"),
        last=Decimal("100.015"),
        observed_at=at,
        provider_timestamp=at,
        provider=provider,
        feed_mode="REALTIME",
        market_phase="REGULAR",
        venue=venue,
        currency=currency,
        recorded_at=at,
    ).quote_snapshot_id


@pytest.mark.parametrize("failpoint", ["after_capsule", "after_reservation", "after_outbox"])
def test_stage_is_atomic_across_crash_boundaries(tmp_path, failpoint) -> None:
    store = DurableExecutionStore(tmp_path / f"{failpoint}.sqlite3")
    _allow_fixture_staging(store)
    capsule, reservation, intent = _contracts(discriminator=failpoint)
    try:
        with pytest.raises(RuntimeError, match="injected crash"):
            store.stage(capsule, reservation, intent, failpoint=failpoint)
        for table in (
            "decision_capsules",
            "risk_reservations",
            "execution_intents",
            "outbox_commands",
        ):
            assert store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        store.close()


def test_manual_approval_and_outbox_survive_restart_exactly_once(tmp_path) -> None:
    path = tmp_path / "control.sqlite3"
    capsule, reservation, intent = _contracts(approval_required=True)
    store = DurableExecutionStore(path)
    _allow_fixture_staging(store)
    store.stage(capsule, reservation, intent)
    assert store.pending_approval_count() == 1
    store.close()

    reopened = DurableExecutionStore(path)
    try:
        _allow_fixture_staging(reopened)
        approval_id = reopened.approve(intent.intent_id, actor_id="operator-1", at=NOW)
        assert len(approval_id) == 64
        assert reopened.pending_approval_count() == 0
        assert (
            reopened.connection.execute("SELECT COUNT(*) FROM operator_approvals").fetchone()[0]
            == 1
        )
        assert (
            reopened.connection.execute("SELECT COUNT(*) FROM outbox_commands").fetchone()[0] == 0
        )
        authority_id = _record_authority(reopened)
        quote_snapshot_id = _record_quote(reopened)
        arm_id = reopened.arm_approved_intent(
            intent.intent_id,
            authority_id=authority_id,
            quote_snapshot_id=quote_snapshot_id,
            max_drift_bps=Decimal("5"),
            armed_by="operator-1",
            at=NOW,
            expires_at=NOW + timedelta(seconds=5),
        )
        assert len(arm_id) == 64
        assert (
            reopened.connection.execute("SELECT COUNT(*) FROM outbox_commands").fetchone()[0] == 1
        )
        with pytest.raises(ExecutionInvariantError, match="different approval"):
            reopened.approve(intent.intent_id, actor_id="operator-2", at=NOW)
    finally:
        reopened.close()


def test_durable_cancel_survives_freeze_and_unknown_response(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    broker = DurableFakeBroker(tmp_path / "broker.sqlite3")
    capsule, reservation, intent = _contracts(discriminator="durable-cancel")
    try:
        _unfreeze(store, broker)
        store.stage(capsule, reservation, intent)
        lease = store.acquire_lease(
            "broker-writer", owner_id="worker", at=NOW, ttl=timedelta(minutes=1)
        )
        worker = ExecutionWorker(store, broker, lease)
        assert worker.dispatch_once(at=NOW)
        heartbeat = store.connection.execute(
            "SELECT status FROM ops_heartbeats WHERE component='execution-worker'"
        ).fetchone()
        assert heartbeat["status"] == "OK"
        store.open_freeze_ticket("MANUAL_FREEZE", source="test", at=NOW)
        first_id = store.request_cancel(intent.intent_id, actor_id="operator", at=NOW)
        assert store.request_cancel(intent.intent_id, actor_id="operator", at=NOW) == first_id
        broker.enqueue(FakeScenario.CANCEL_DROP_RESPONSE)
        assert worker.dispatch_cancel_once(at=NOW + timedelta(seconds=1))
        assert store.intent(intent.intent_id)["status"] == ExecutionStatus.CANCEL_UNKNOWN
        assert broker.snapshot(at=NOW).orders[0].status == "CANCELLED"
        assert store.request_cancel(intent.intent_id, actor_id="operator", at=NOW) == first_id
    finally:
        broker.close()
        store.close()


def test_cancel_before_submission_is_local_durable_and_releases_risk(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    capsule, reservation, intent = _contracts(discriminator="local-cancel")
    try:
        _allow_fixture_staging(store)
        store.stage(capsule, reservation, intent)
        command_id = store.request_cancel(intent.intent_id, actor_id="operator", at=NOW)
        assert store.request_cancel(intent.intent_id, actor_id="operator", at=NOW) == command_id
        assert store.intent(intent.intent_id)["status"] == ExecutionStatus.CANCELLED
        assert (
            store.connection.execute("SELECT status FROM outbox_commands").fetchone()[0]
            == "DELIVERED"
        )
        assert (
            store.connection.execute("SELECT status FROM cancel_commands").fetchone()[0]
            == "DELIVERED"
        )
        assert store.active_reserved_notional("paper-account") == Decimal("0")
    finally:
        store.close()


def test_authoritative_reconciliation_requires_semantic_consensus(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    broker = DurableFakeBroker(tmp_path / "broker.sqlite3")
    try:
        raw = broker.snapshot(at=NOW)
        incomplete = raw.model_copy(update={"complete": False})
        assert (
            Reconciler(store).reconcile_authoritative(incomplete, at=NOW).status
            == "INCOMPLETE_SNAPSHOT"
        )

        snapshot = raw.model_copy(
            update={
                "completeness_certificate_id": canonical_hash({"certificate": 1}),
                "semantic_hash": canonical_hash({"semantic": 1}),
                "visibility_scope_hash": canonical_hash({"scope": 1}),
                "observation_id": canonical_hash({"observation": 1}),
                "session_id": canonical_hash({"session": 1}),
                "final_watermark": 10,
            }
        )
        first = Reconciler(store).reconcile_authoritative(snapshot, at=NOW)
        assert first.status == "AWAITING_CONSENSUS"
        assert first.frozen
        replay = Reconciler(store).reconcile_authoritative(snapshot, at=NOW + timedelta(seconds=2))
        assert replay.status == "AWAITING_CONSENSUS"
        independent = snapshot.model_copy(
            update={
                "as_of": NOW + timedelta(seconds=2),
                "completeness_certificate_id": canonical_hash({"certificate": 2}),
                "observation_id": canonical_hash({"observation": 2}),
                "session_id": canonical_hash({"session": 2}),
                "final_watermark": 20,
            }
        )
        second = Reconciler(store).reconcile_authoritative(
            independent, at=NOW + timedelta(seconds=2)
        )
        assert second.status == "CONVERGED"
        authority = store.latest_broker_snapshot_authority()
        assert authority is not None
        assert authority["semantic_hash"] == independent.semantic_hash
    finally:
        broker.close()
        store.close()


def test_blocked_candidate_is_never_promoted_to_broker_authority(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    snapshot = BrokerSnapshot(
        as_of=NOW,
        cash=Decimal("100000"),
        completeness_certificate_id=canonical_hash({"certificate": "blocked"}),
        semantic_hash=canonical_hash({"semantic": "blocked"}),
        visibility_scope_hash=canonical_hash({"scope": "blocked"}),
        orders=(),
        positions={},
        protections={},
        events=(),
    )
    try:
        assert not store.record_broker_snapshot_authority(
            snapshot,
            reconciliation_run_id=canonical_hash({"run": "blocked"}),
            reconciliation_status="BLOCKED",
            at=NOW,
        )
        assert store.latest_broker_snapshot_authority() is None
        candidate = store.connection.execute(
            "SELECT promotion_status FROM broker_authority_candidates"
        ).fetchone()
        assert candidate["promotion_status"] == "REJECTED"
    finally:
        store.close()


def test_converged_reconciliation_cannot_promote_incomplete_cash_authority(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    broker = DurableFakeBroker(tmp_path / "broker.sqlite3")
    try:
        raw = broker.snapshot(at=NOW).model_copy(
            update={
                "cash_snapshot_complete": False,
                "commission_pending_count": 1,
                "semantic_hash": canonical_hash({"semantic": "commission-pending"}),
                "visibility_scope_hash": canonical_hash({"scope": "cash-incomplete"}),
                "completeness_certificate_id": canonical_hash({"certificate": 1}),
                "observation_id": canonical_hash({"observation": 1}),
                "session_id": canonical_hash({"session": 1}),
                "final_watermark": 10,
            }
        )
        assert Reconciler(store).reconcile_authoritative(raw, at=NOW).status == "AWAITING_CONSENSUS"
        second = raw.model_copy(
            update={
                "as_of": NOW + timedelta(seconds=2),
                "completeness_certificate_id": canonical_hash({"certificate": 2}),
                "observation_id": canonical_hash({"observation": 2}),
                "session_id": canonical_hash({"session": 2}),
                "final_watermark": 20,
            }
        )
        report = Reconciler(store).reconcile_authoritative(second, at=NOW + timedelta(seconds=2))
        assert report.status == "AUTHORITY_REJECTED"
        assert store.latest_broker_snapshot_authority() is None
        assert "BROKER_AUTHORITY_COMPONENTS_INCOMPLETE" in store.active_freeze_reasons()
    finally:
        broker.close()
        store.close()


def test_arm_requires_persisted_fresh_quote_and_fresh_authority(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    capsule, reservation, intent = _contracts(
        discriminator="quote-authority", approval_required=True
    )
    try:
        _allow_fixture_staging(store)
        store.stage(capsule, reservation, intent)
        store.approve(intent.intent_id, actor_id="operator", at=NOW)
        authority_id = _record_authority(store, discriminator="quote-authority")
        with pytest.raises(ExecutionInvariantError, match="drift exceeds system policy"):
            store.arm_approved_intent(
                intent.intent_id,
                authority_id=authority_id,
                quote_snapshot_id=canonical_hash({"quote": "not-yet-loaded"}),
                max_drift_bps=Decimal("11"),
                armed_by="operator",
                at=NOW,
                expires_at=NOW + timedelta(seconds=5),
            )
        with pytest.raises(ExecutionInvariantError, match="quote snapshot is unknown"):
            store.arm_approved_intent(
                intent.intent_id,
                authority_id=authority_id,
                quote_snapshot_id=canonical_hash({"caller": "self-reported"}),
                max_drift_bps=Decimal("5"),
                armed_by="operator",
                at=NOW,
                expires_at=NOW + timedelta(seconds=5),
            )
        stale_quote = _record_quote(store, at=NOW - timedelta(seconds=10))
        with pytest.raises(ExecutionInvariantError, match="quote snapshot exceeded"):
            store.arm_approved_intent(
                intent.intent_id,
                authority_id=authority_id,
                quote_snapshot_id=stale_quote,
                max_drift_bps=Decimal("5"),
                armed_by="operator",
                at=NOW,
                expires_at=NOW + timedelta(seconds=5),
            )
        assert "MARKET_QUOTE_STALE" in store.active_freeze_reasons()
    finally:
        store.close()


def test_expired_arm_can_be_superseded_and_consumed_once(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    capsule, reservation, intent = _contracts(discriminator="re-arm", approval_required=True)
    try:
        _allow_fixture_staging(store)
        store.stage(capsule, reservation, intent)
        store.approve(intent.intent_id, actor_id="approver", at=NOW)
        authority_id = _record_authority(store, discriminator="re-arm")
        first_quote = _record_quote(store)
        first_arm = store.arm_approved_intent(
            intent.intent_id,
            authority_id=authority_id,
            quote_snapshot_id=first_quote,
            max_drift_bps=Decimal("5"),
            armed_by="operator-a",
            at=NOW,
            expires_at=NOW + timedelta(seconds=1),
            operator_session_id="session-a",
        )
        lease = store.acquire_lease(
            "broker-writer",
            owner_id="worker",
            at=NOW + timedelta(seconds=2),
            ttl=timedelta(minutes=1),
        )
        with pytest.raises(ExecutionInvariantError, match="arm missing or expired"):
            store.claim_next(lease, at=NOW + timedelta(seconds=2))
        first = store.connection.execute(
            "SELECT status FROM approval_arms WHERE arm_id=?", (first_arm,)
        ).fetchone()
        assert first["status"] == "EXPIRED"

        second_at = NOW + timedelta(seconds=2)
        second_quote = _record_quote(store, at=second_at)
        second_arm = store.arm_approved_intent(
            intent.intent_id,
            authority_id=authority_id,
            quote_snapshot_id=second_quote,
            max_drift_bps=Decimal("5"),
            armed_by="operator-b",
            at=second_at,
            expires_at=second_at + timedelta(seconds=5),
            operator_session_id="session-b",
        )
        assert second_arm != first_arm
        claimed = store.claim_next(lease, at=second_at)
        assert claimed is not None
        rows = store.connection.execute(
            """SELECT version, status, armed_by, operator_session_id
               FROM approval_arms WHERE intent_id=? ORDER BY version""",
            (intent.intent_id,),
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            (1, "EXPIRED", "operator-a", "session-a"),
            (2, "CONSUMED", "operator-b", "session-b"),
        ]
    finally:
        store.close()


def test_active_arm_is_idempotent_then_superseded_by_new_quote(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    capsule, reservation, intent = _contracts(discriminator="active-re-arm", approval_required=True)
    try:
        _allow_fixture_staging(store)
        store.stage(capsule, reservation, intent)
        store.approve(intent.intent_id, actor_id="approver", at=NOW)
        authority_id = _record_authority(store, discriminator="active-re-arm")
        first_quote = _record_quote(store)
        arguments = {
            "authority_id": authority_id,
            "quote_snapshot_id": first_quote,
            "max_drift_bps": Decimal("5"),
            "armed_by": "operator",
            "at": NOW,
            "expires_at": NOW + timedelta(seconds=5),
            "operator_session_id": "operator-session",
        }
        first_arm = store.arm_approved_intent(intent.intent_id, **arguments)
        assert store.arm_approved_intent(intent.intent_id, **arguments) == first_arm
        second_quote = _record_quote(store, provider="fixture-secondary")
        second_arm = store.arm_approved_intent(
            intent.intent_id,
            **{**arguments, "quote_snapshot_id": second_quote},
        )
        assert second_arm != first_arm
        rows = store.connection.execute(
            "SELECT version, status FROM approval_arms WHERE intent_id=? ORDER BY version",
            (intent.intent_id,),
        ).fetchall()
        assert [tuple(row) for row in rows] == [(1, "SUPERSEDED"), (2, "ACTIVE")]
    finally:
        store.close()


@pytest.mark.parametrize(
    ("venue", "currency", "message"),
    [
        ("UNKNOWN", "USD", "VENUE_NOT_AUTHORITATIVE"),
        ("SMART", "EUR", "CURRENCY_MISMATCH"),
    ],
)
def test_arm_rejects_unbound_quote_venue_and_currency(tmp_path, venue, currency, message) -> None:
    store = DurableExecutionStore(tmp_path / f"{venue}-{currency}.sqlite3")
    capsule, reservation, intent = _contracts(
        discriminator=f"{venue}-{currency}", approval_required=True
    )
    try:
        _allow_fixture_staging(store)
        store.stage(capsule, reservation, intent)
        store.approve(intent.intent_id, actor_id="approver", at=NOW)
        authority_id = _record_authority(store, discriminator=f"{venue}-{currency}")
        quote_id = _record_quote(store, venue=venue, currency=currency)
        with pytest.raises(ExecutionInvariantError, match=message):
            store.arm_approved_intent(
                intent.intent_id,
                authority_id=authority_id,
                quote_snapshot_id=quote_id,
                max_drift_bps=Decimal("5"),
                armed_by="operator",
                at=NOW,
                expires_at=NOW + timedelta(seconds=5),
            )
    finally:
        store.close()


def test_legacy_single_arm_schema_migrates_without_losing_receipt(tmp_path) -> None:
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE approval_arms (
           arm_id TEXT PRIMARY KEY, intent_id TEXT UNIQUE NOT NULL,
           broker_snapshot_hash TEXT NOT NULL, quote_hash TEXT NOT NULL,
           approved_limit_price TEXT NOT NULL, max_drift_bps TEXT NOT NULL,
           armed_at TEXT NOT NULL, expires_at TEXT NOT NULL, arm_json TEXT NOT NULL)"""
    )
    connection.execute(
        "INSERT INTO approval_arms VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "arm-legacy",
            "intent-legacy",
            "broker-hash",
            "quote-hash",
            "100",
            "5",
            NOW.isoformat(),
            (NOW + timedelta(seconds=5)).isoformat(),
            "{}",
        ),
    )
    connection.commit()
    connection.close()
    store = DurableExecutionStore(path)
    try:
        row = store.connection.execute(
            """SELECT version, status, armed_by, arm_source
               FROM approval_arms WHERE arm_id='arm-legacy'"""
        ).fetchone()
        assert tuple(row) == (1, "ACTIVE", "LEGACY_UNKNOWN", "LEGACY_MIGRATION")
    finally:
        store.close()


@pytest.mark.parametrize(
    ("feed_mode", "provider_offset", "bid", "ask", "message"),
    [
        ("DELAYED", 0, "100.01", "100.02", "FEED_NOT_REALTIME"),
        ("REALTIME", -10, "100.01", "100.02", "PROVIDER_QUOTE_STALE"),
        ("REALTIME", 2, "100.01", "100.02", "PROVIDER_TIMESTAMP_IN_FUTURE"),
        ("REALTIME", 0, "99", "101", "SPREAD_TOO_WIDE"),
    ],
)
def test_arm_rejects_adversarial_quote_freshness_and_spread(
    tmp_path, feed_mode, provider_offset, bid, ask, message
) -> None:
    store = DurableExecutionStore(tmp_path / f"{feed_mode}-{provider_offset}-{bid}.sqlite3")
    capsule, reservation, intent = _contracts(
        discriminator=f"{feed_mode}-{provider_offset}-{bid}",
        approval_required=True,
    )
    try:
        _allow_fixture_staging(store)
        store.stage(capsule, reservation, intent)
        store.approve(intent.intent_id, actor_id="approver", at=NOW)
        authority_id = _record_authority(
            store, discriminator=f"{feed_mode}-{provider_offset}-{bid}"
        )
        quote = store.record_quote_snapshot(
            symbol="inst-alpha",
            bid=Decimal(bid),
            ask=Decimal(ask),
            last=Decimal("100"),
            observed_at=NOW,
            provider_timestamp=NOW + timedelta(seconds=provider_offset),
            provider="fixture",
            feed_mode=feed_mode,
            market_phase="REGULAR",
            venue="SMART",
            currency="USD",
            recorded_at=NOW,
        )
        with pytest.raises(ExecutionInvariantError, match=message):
            store.arm_approved_intent(
                intent.intent_id,
                authority_id=authority_id,
                quote_snapshot_id=quote.quote_snapshot_id,
                max_drift_bps=Decimal("5"),
                armed_by="operator",
                at=NOW,
                expires_at=NOW + timedelta(seconds=5),
            )
    finally:
        store.close()


def test_arm_expiry_propagates_upstream_budget_and_claim_revalidates(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "freshness-budget.sqlite3")
    capsule, reservation, intent = _contracts(
        discriminator="freshness-budget", approval_required=True
    )
    try:
        _allow_fixture_staging(store)
        store.stage(capsule, reservation, intent)
        store.approve(intent.intent_id, actor_id="approver", at=NOW)
        authority_id = _record_authority(store, discriminator="freshness-budget")
        quote_id = _record_quote(store, at=NOW - timedelta(seconds=4))
        arm_id = store.arm_approved_intent(
            intent.intent_id,
            authority_id=authority_id,
            quote_snapshot_id=quote_id,
            max_drift_bps=Decimal("5"),
            armed_by="operator",
            at=NOW,
            expires_at=NOW + timedelta(seconds=5),
        )
        arm = store.connection.execute(
            "SELECT expires_at, arm_json FROM approval_arms WHERE arm_id=?", (arm_id,)
        ).fetchone()
        assert datetime.fromisoformat(arm["expires_at"]) == NOW + timedelta(seconds=1)
        assert json.loads(arm["arm_json"])["requested_expires_at"] == (
            NOW + timedelta(seconds=5)
        ).isoformat()
        lease = store.acquire_lease(
            "broker-writer", owner_id="worker", at=NOW, ttl=timedelta(seconds=10)
        )
        with pytest.raises(ExecutionInvariantError, match="missing or expired"):
            store.claim_next(lease, at=NOW + timedelta(seconds=1))
        assert (
            store.connection.execute(
                "SELECT status FROM approval_arms WHERE arm_id=?", (arm_id,)
            ).fetchone()[0]
            == "EXPIRED"
        )
    finally:
        store.close()


def test_authority_equivalence_allows_bounded_valuation_drift_only(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    scope = canonical_hash({"scope": "valuation"})
    semantic = canonical_hash({"exact": "economic-state"})
    policy = canonical_hash({"policy": "m7b1"})

    def snapshot(index: int, net_liquidation: str) -> BrokerSnapshot:
        return BrokerSnapshot(
            as_of=NOW + timedelta(seconds=index),
            cash=Decimal("100000"),
            completeness_certificate_id=canonical_hash({"certificate": index}),
            observation_id=canonical_hash({"observation": index}),
            session_id=canonical_hash({"session": index}),
            final_watermark=10 + index,
            semantic_hash=semantic,
            visibility_scope_hash=scope,
            normalization_policy_hash=policy,
            valuation_fields={"NetLiquidation:USD": Decimal(net_liquidation)},
            orders=(),
            positions={},
            protections={},
            events=(),
        )

    try:
        assert store.register_snapshot_consensus(
            snapshot(1, "100000"), at=NOW + timedelta(seconds=1)
        ) == (False, 1)
        assert store.register_snapshot_consensus(
            snapshot(2, "100200"), at=NOW + timedelta(seconds=2)
        ) == (True, 2)
        assert store.register_snapshot_consensus(
            snapshot(3, "101000"), at=NOW + timedelta(seconds=3)
        ) == (False, 1)
        proof = store.connection.execute(
            """SELECT equivalence_json FROM broker_snapshot_votes
               WHERE observation_id=?""",
            (canonical_hash({"observation": 3}),),
        ).fetchone()
        assert json.loads(proof["equivalence_json"])["state_equivalent"] is False
    finally:
        store.close()


def test_cash_bridge_starts_a_new_projection_baseline_epoch(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    try:
        initial = BrokerSnapshot(
            as_of=NOW,
            cash=Decimal("100000"),
            settled_cash=Decimal("100000"),
            buying_power=Decimal("200000"),
            accrued_cash=Decimal("0"),
            orders=(),
            positions={},
            protections={},
            events=(),
        )
        store.set_account_baseline(initial)
        store.connection.execute(
            "UPDATE cash_projection SET cash_delta='-1000', commissions='2' WHERE singleton=1"
        )
        store.connection.commit()
        assert store.expected_account_cash() == Decimal("99000")

        unexplained = store.record_cash_bridge(
            event_type="mystery",
            amount=Decimal("500"),
            currency="USD",
            at=NOW,
            evidence={},
            explained=False,
        )
        with pytest.raises(ExecutionInvariantError, match="explained bridge"):
            store.advance_account_baseline_epoch(initial, bridge_id=unexplained, at=NOW)

        bridge_id = store.record_cash_bridge(
            event_type="DEPOSIT",
            amount=Decimal("500"),
            currency="USD",
            at=NOW + timedelta(seconds=1),
            evidence={"reference_hash": canonical_hash({"deposit": 1})},
            explained=True,
        )
        refreshed = initial.model_copy(
            update={"as_of": NOW + timedelta(seconds=1), "cash": Decimal("99500")}
        )
        store.advance_account_baseline_epoch(
            refreshed, bridge_id=bridge_id, at=NOW + timedelta(seconds=1)
        )
        assert store.expected_account_cash() == Decimal("99500")
        store.connection.execute("UPDATE cash_projection SET cash_delta='-1100' WHERE singleton=1")
        store.connection.commit()
        assert store.expected_account_fields()["cash"] == Decimal("99400")
        assert store.expected_account_fields()["settled_cash"] is None
    finally:
        store.close()


def test_reconciliation_closes_discrepancies_absent_from_later_run(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    discrepancy_id = canonical_hash({"discrepancy": "old"})
    store.connection.execute(
        """INSERT INTO reconciliation_discrepancies
           (discrepancy_id, run_id, severity, kind, entity_key, details_json,
            resolved_at, first_seen_at, last_seen_at, lifecycle_status, resolution_evidence)
           VALUES (?, ?, 'CRITICAL', 'OLD_GAP', 'entity', '{}', NULL, ?, ?, 'OPEN', NULL)""",
        (discrepancy_id, canonical_hash({"run": "old"}), NOW.isoformat(), NOW.isoformat()),
    )
    store.connection.commit()
    try:
        report = Reconciler(store).reconcile(
            BrokerSnapshot(
                as_of=NOW + timedelta(seconds=1),
                cash=Decimal("100000"),
                orders=(),
                positions={},
                protections={},
                events=(),
            ),
            at=NOW + timedelta(seconds=1),
        )
        assert report.status == "CONVERGED"
        row = store.connection.execute(
            "SELECT lifecycle_status, resolution_evidence FROM reconciliation_discrepancies WHERE discrepancy_id=?",
            (discrepancy_id,),
        ).fetchone()
        assert row["lifecycle_status"] == "RESOLVED"
        assert "absent_from_later_reconciliation" in row["resolution_evidence"]
    finally:
        store.close()


def test_reconciliation_supersedes_changed_details_for_same_entity(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    old_id = canonical_hash({"discrepancy": "cash-old-details"})
    old_run = canonical_hash({"run": "cash-old"})
    store.connection.execute(
        """INSERT INTO reconciliation_discrepancies
           (discrepancy_id, run_id, severity, kind, entity_key, details_json,
            resolved_at, first_seen_at, last_seen_at, lifecycle_status,
            resolution_evidence)
           VALUES (?, ?, 'CRITICAL', 'CASH_MISMATCH', 'USD', '{}', NULL, ?, ?,
                   'OPEN', NULL)""",
        (old_id, old_run, NOW.isoformat(), NOW.isoformat()),
    )
    store.connection.commit()
    baseline = BrokerSnapshot(
        as_of=NOW,
        cash=Decimal("100000"),
        settled_cash=Decimal("100000"),
        buying_power=Decimal("100000"),
        accrued_cash=Decimal("0"),
        orders=(),
        positions={},
        protections={},
        events=(),
    )
    store.set_account_baseline(baseline)
    try:
        report = Reconciler(store).reconcile(
            baseline.model_copy(
                update={"as_of": NOW + timedelta(seconds=1), "cash": Decimal("90000")}
            ),
            at=NOW + timedelta(seconds=1),
        )
        assert report.status == "BLOCKED"
        rows = store.connection.execute(
            """SELECT discrepancy_id, lifecycle_status, resolution_evidence
               FROM reconciliation_discrepancies
               WHERE kind='CASH_MISMATCH' AND entity_key='USD'
               ORDER BY first_seen_at"""
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["discrepancy_id"] == old_id
        assert rows[0]["lifecycle_status"] == "SUPERSEDED"
        assert "superseded_by_new_observation" in rows[0]["resolution_evidence"]
        assert rows[1]["lifecycle_status"] == "OPEN"
    finally:
        store.close()


def test_two_writers_cannot_overreserve_same_account_capacity(tmp_path) -> None:
    path = tmp_path / "control.sqlite3"
    first_store = DurableExecutionStore(path)
    second_store = DurableExecutionStore(path)
    first = _contracts(discriminator="capacity-1")
    second = _contracts(discriminator="capacity-2")
    first_reservation = first[1].model_copy(update={"account_notional_capacity": Decimal("1500")})
    first_intent = ExecutionIntent.create(
        capsule=first[0],
        reservation=first_reservation,
        side=Side.BUY,
        quantity=10,
        limit_price=Decimal("100"),
        stop_price=Decimal("90"),
        target_price=Decimal("120"),
        approval_required=False,
    )
    second_reservation = second[1].model_copy(update={"account_notional_capacity": Decimal("1500")})
    second_intent = ExecutionIntent.create(
        capsule=second[0],
        reservation=second_reservation,
        side=Side.BUY,
        quantity=10,
        limit_price=Decimal("100"),
        stop_price=Decimal("90"),
        target_price=Decimal("120"),
        approval_required=False,
    )
    try:
        _allow_fixture_staging(first_store)
        first_store.stage(first[0], first_reservation, first_intent)
        with pytest.raises(ExecutionInvariantError, match="capacity exceeded"):
            second_store.stage(second[0], second_reservation, second_intent)
        assert (
            first_store.connection.execute("SELECT COUNT(*) FROM risk_reservations").fetchone()[0]
            == 1
        )
    finally:
        second_store.close()
        first_store.close()


def test_accept_then_drop_is_not_resent_and_reconciliation_converges(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    broker = DurableFakeBroker(tmp_path / "broker.sqlite3")
    capsule, reservation, intent = _contracts()
    try:
        _unfreeze(store, broker)
        store.stage(capsule, reservation, intent)
        broker.enqueue(FakeScenario.ACCEPT_DROP_RESPONSE)
        lease = store.acquire_lease(
            "broker-writer", owner_id="worker-1", at=NOW, ttl=timedelta(minutes=1)
        )
        assert ExecutionWorker(store, broker, lease).dispatch_once(at=NOW)
        assert store.intent(intent.intent_id)["status"] == ExecutionStatus.SUBMISSION_UNKNOWN
        assert broker.snapshot(at=NOW).orders[0].client_order_key == intent.client_order_key
        assert not ExecutionWorker(store, broker, lease).dispatch_once(at=NOW)

        report = Reconciler(store).reconcile(
            broker.snapshot(at=NOW + timedelta(seconds=1)),
            at=NOW + timedelta(seconds=1),
        )
        assert report.status == "CONVERGED"
        assert store.intent(intent.intent_id)["status"] == ExecutionStatus.ACKNOWLEDGED
        outbox = store.connection.execute("SELECT status FROM outbox_commands").fetchone()
        assert outbox["status"] == OutboxStatus.DELIVERED
        assert len(broker.snapshot(at=NOW).orders) == 1
    finally:
        broker.close()
        store.close()


def test_crash_after_claim_requeues_only_after_authoritative_absence(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    broker = DurableFakeBroker(tmp_path / "broker.sqlite3")
    capsule, reservation, intent = _contracts()
    try:
        _unfreeze(store, broker)
        store.stage(capsule, reservation, intent)
        lease = store.acquire_lease(
            "broker-writer", owner_id="worker-1", at=NOW, ttl=timedelta(minutes=1)
        )
        assert store.claim_next(lease, at=NOW) is not None

        report = Reconciler(store).reconcile(
            broker.snapshot(at=NOW + timedelta(seconds=1)),
            at=NOW + timedelta(seconds=1),
        )
        assert report.status == "CONVERGED"
        outbox = store.connection.execute("SELECT status FROM outbox_commands").fetchone()
        assert outbox["status"] == OutboxStatus.PENDING
        assert store.intent(intent.intent_id)["status"] == ExecutionStatus.OUTBOXED
    finally:
        broker.close()
        store.close()


def test_fencing_and_duplicate_broker_events_preserve_one_economic_order(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    broker = DurableFakeBroker(tmp_path / "broker.sqlite3")
    capsule, reservation, intent = _contracts()
    try:
        _unfreeze(store, broker)
        store.stage(capsule, reservation, intent)
        first = store.acquire_lease(
            "broker-writer", owner_id="worker-1", at=NOW, ttl=timedelta(seconds=1)
        )
        second = store.acquire_lease(
            "broker-writer",
            owner_id="worker-2",
            at=NOW + timedelta(seconds=2),
            ttl=timedelta(minutes=1),
        )
        broker.enqueue(FakeScenario.DUPLICATE_ACK)
        assert ExecutionWorker(store, broker, second).dispatch_once(at=NOW + timedelta(seconds=2))
        with pytest.raises(StaleFencingToken):
            broker.submit(intent, fencing_token=first.fencing_token, at=NOW + timedelta(seconds=3))
        assert len(broker.snapshot(at=NOW).orders) == 1
        assert (
            store.connection.execute("SELECT COUNT(*) FROM broker_event_inbox").fetchone()[0] == 1
        )
    finally:
        broker.close()
        store.close()


def test_partial_fill_restart_projection_and_duplicate_fill_are_idempotent(tmp_path) -> None:
    control_path = tmp_path / "control.sqlite3"
    broker_path = tmp_path / "broker.sqlite3"
    capsule, reservation, intent = _contracts()
    store = DurableExecutionStore(control_path)
    broker = DurableFakeBroker(broker_path)
    _unfreeze(store, broker)
    store.stage(capsule, reservation, intent)
    broker.enqueue(FakeScenario.PARTIAL_FILL)
    lease = store.acquire_lease(
        "broker-writer", owner_id="worker-1", at=NOW, ttl=timedelta(minutes=1)
    )
    ExecutionWorker(store, broker, lease).dispatch_once(at=NOW)
    assert store.intent(intent.intent_id)["status"] == ExecutionStatus.PARTIALLY_FILLED
    store.close()
    broker.close()

    store = DurableExecutionStore(control_path)
    broker = DurableFakeBroker(broker_path)
    try:
        final_fill = broker.fill(
            intent.client_order_key,
            quantity=10,
            price=Decimal("100"),
            at=NOW + timedelta(seconds=1),
        )
        assert store.ingest_broker_event(final_fill)
        assert not store.ingest_broker_event(final_fill)
        row = store.intent(intent.intent_id)
        assert row["status"] == ExecutionStatus.FILLED
        assert int(row["filled_quantity"]) == 10
        assert store.rebuild_projection()[intent.intent_id] == (ExecutionStatus.FILLED, 10)
    finally:
        broker.close()
        store.close()


def test_broker_only_order_and_naked_fill_fail_closed(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    broker = DurableFakeBroker(tmp_path / "broker.sqlite3")
    capsule, reservation, intent = _contracts(discriminator="local")
    try:
        _unfreeze(store, broker)
        store.stage(capsule, reservation, intent)
        broker.enqueue(FakeScenario.MISSING_PROTECTION)
        lease = store.acquire_lease(
            "broker-writer", owner_id="worker-1", at=NOW, ttl=timedelta(minutes=1)
        )
        ExecutionWorker(store, broker, lease).dispatch_once(at=NOW)
        fill = broker.fill(
            intent.client_order_key,
            quantity=10,
            price=Decimal("100"),
            at=NOW + timedelta(seconds=1),
        )
        store.ingest_broker_event(fill)
        report = Reconciler(store).reconcile(
            broker.snapshot(at=NOW + timedelta(seconds=2)),
            at=NOW + timedelta(seconds=2),
        )
        assert report.status == "BLOCKED"
        kinds = {item.kind for item in report.discrepancies}
        assert "ORDER_PROTECTION_SHORTFALL" in kinds
        assert "NAKED_LONG_EXPOSURE" in kinds
        assert store.is_frozen()[0]
    finally:
        broker.close()
        store.close()

    orphan_store = DurableExecutionStore(tmp_path / "orphan-control.sqlite3")
    orphan_broker = DurableFakeBroker(tmp_path / "orphan-broker.sqlite3")
    _, _, orphan_intent = _contracts(discriminator="broker-only")
    try:
        orphan_broker.inject_broker_only_order(orphan_intent, at=NOW)
        report = Reconciler(orphan_store).reconcile(orphan_broker.snapshot(at=NOW), at=NOW)
        assert report.status == "BLOCKED"
        assert "BROKER_ONLY_ORDER" in {item.kind for item in report.discrepancies}
    finally:
        orphan_broker.close()
        orphan_store.close()


def test_fill_cancel_race_and_late_commission_rebuild_without_double_effect(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    broker = DurableFakeBroker(tmp_path / "broker.sqlite3")
    capsule, reservation, intent = _contracts(discriminator="cancel-race")
    try:
        _unfreeze(store, broker)
        store.stage(capsule, reservation, intent)
        lease = store.acquire_lease(
            "broker-writer", owner_id="worker-1", at=NOW, ttl=timedelta(minutes=1)
        )
        ExecutionWorker(store, broker, lease).dispatch_once(at=NOW)
        race_events = broker.cancel(
            intent.client_order_key,
            fencing_token=lease.fencing_token,
            at=NOW + timedelta(seconds=1),
            fill_before_cancel_quantity=4,
        )
        assert [event.event_type for event in race_events] == ["PARTIAL_FILL", "CANCELLED"]
        for event in race_events:
            store.ingest_broker_event(event)
        assert store.intent(intent.intent_id)["status"] == ExecutionStatus.CANCELLED
        assert int(store.intent(intent.intent_id)["filled_quantity"]) == 4

        commission = broker.commission(
            intent.client_order_key,
            amount=Decimal("1.25"),
            at=NOW + timedelta(seconds=2),
        )
        store.ingest_broker_event(commission)
        assert store.intent(intent.intent_id)["status"] == ExecutionStatus.CANCELLED
        projection = store.rebuild_economic_projection()
        assert projection["positions"] == {"inst-alpha": 4}
        assert projection["cash_delta"] == Decimal("-401.25")
        assert projection["commissions"] == Decimal("1.25")
        stored_position = store.connection.execute(
            "SELECT quantity FROM position_projections WHERE instrument_id='inst-alpha'"
        ).fetchone()
        assert stored_position["quantity"] == 4
    finally:
        broker.close()
        store.close()


def test_freeze_ticket_blocks_staging_approval_and_dispatch(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    broker = DurableFakeBroker(tmp_path / "broker.sqlite3")
    capsule, reservation, pending = _contracts(
        discriminator="freeze-authority", approval_required=True
    )
    try:
        _unfreeze(store, broker)
        store.stage(capsule, reservation, pending)
        store.open_freeze_ticket("MARKET_DATA_STALE", source="market", at=NOW)
        with pytest.raises(ExecutionInvariantError, match="approval is frozen"):
            store.approve(pending.intent_id, actor_id="operator-1", at=NOW)
        other = _contracts(discriminator="freeze-second")
        with pytest.raises(ExecutionInvariantError, match="new risk is frozen"):
            store.stage(*other)
        assert store.pending_approval_count() == 1
    finally:
        broker.close()
        store.close()


def test_new_lease_fences_old_writer_before_new_writer_submits(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    broker = DurableFakeBroker(tmp_path / "broker.sqlite3")
    _, _, intent = _contracts(discriminator="fence-window")
    try:
        first = store.acquire_lease(
            "broker-writer", owner_id="old", at=NOW, ttl=timedelta(seconds=1)
        )
        ExecutionWorker(store, broker, first)
        second = store.acquire_lease(
            "broker-writer",
            owner_id="new",
            at=NOW + timedelta(seconds=2),
            ttl=timedelta(minutes=1),
        )
        ExecutionWorker(store, broker, second)
        with pytest.raises(StaleFencingToken):
            broker.submit(intent, fencing_token=first.fencing_token, at=NOW + timedelta(seconds=3))
    finally:
        broker.close()
        store.close()


def test_unknown_absence_requires_snapshot_strictly_after_claim(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    broker = DurableFakeBroker(tmp_path / "broker.sqlite3")
    capsule, reservation, intent = _contracts(discriminator="strict-unknown")
    try:
        _unfreeze(store, broker)
        store.stage(capsule, reservation, intent)
        lease = store.acquire_lease(
            "broker-writer", owner_id="worker", at=NOW, ttl=timedelta(minutes=1)
        )
        assert store.claim_next(lease, at=NOW)
        store.recover_claimed_as_unknown(at=NOW)
        with pytest.raises(ExecutionInvariantError, match="does not post-date"):
            store.requeue_unknown_absent_at_broker(
                intent.client_order_key, snapshot_as_of=NOW, at=NOW
            )
    finally:
        broker.close()
        store.close()


def test_cash_mismatch_is_critical_and_decimal_exact(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    broker = DurableFakeBroker(tmp_path / "broker.sqlite3")
    capsule, reservation, intent = _contracts(discriminator="cash")
    try:
        _unfreeze(store, broker)
        store.stage(capsule, reservation, intent)
        lease = store.acquire_lease(
            "broker-writer", owner_id="worker", at=NOW, ttl=timedelta(minutes=1)
        )
        ExecutionWorker(store, broker, lease).dispatch_once(at=NOW)
        fill = broker.fill(
            intent.client_order_key,
            quantity=10,
            price=Decimal("100.00000001"),
            at=NOW + timedelta(seconds=1),
        )
        store.ingest_broker_event(fill)
        snapshot = broker.snapshot(at=NOW + timedelta(seconds=2))
        assert snapshot.cash == Decimal("98999.99999990")
        corrupted = snapshot.model_copy(update={"cash": snapshot.cash - Decimal("1")})
        report = Reconciler(store).reconcile(corrupted, at=NOW + timedelta(seconds=2))
        assert report.status == "BLOCKED"
        assert "CASH_MISMATCH" in {item.kind for item in report.discrepancies}
    finally:
        broker.close()
        store.close()


def test_every_control_process_restart_requires_reconciliation(tmp_path) -> None:
    path = tmp_path / "control.sqlite3"
    store = DurableExecutionStore(path)
    store.unfreeze_after_reconciliation(at=NOW)
    assert not store.is_frozen()[0]
    store.close()

    reopened = DurableExecutionStore(path)
    try:
        assert reopened.is_frozen()[0]
        assert "STARTUP_RECONCILIATION" in reopened.active_freeze_reasons()
    finally:
        reopened.close()


def test_incomplete_snapshot_is_persisted_and_cannot_unfreeze(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    broker = DurableFakeBroker(tmp_path / "broker.sqlite3")
    try:
        incomplete = broker.snapshot(at=NOW).model_copy(
            update={"complete": False, "completeness_certificate_id": "incomplete-1"}
        )
        report = Reconciler(store).reconcile(incomplete, at=NOW)
        assert report.status == "INCOMPLETE_SNAPSHOT"
        assert store.is_frozen()[0]
        row = store.connection.execute(
            "SELECT status FROM reconciliation_runs WHERE run_id=?", (report.run_id,)
        ).fetchone()
        assert row["status"] == "INCOMPLETE_SNAPSHOT"
    finally:
        broker.close()
        store.close()
