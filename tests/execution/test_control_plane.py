from __future__ import annotations

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


def _record_quote(store: DurableExecutionStore, *, at: datetime = NOW) -> str:
    return store.record_quote_snapshot(
        symbol="inst-alpha",
        bid=Decimal("100.01"),
        ask=Decimal("100.02"),
        last=Decimal("100.015"),
        observed_at=at,
        provider_timestamp=at,
        provider="fixture",
        feed_mode="REALTIME",
        market_phase="REGULAR",
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
        assert reopened.connection.execute("SELECT COUNT(*) FROM outbox_commands").fetchone()[0] == 0
        authority_id = _record_authority(reopened)
        quote_snapshot_id = _record_quote(reopened)
        arm_id = reopened.arm_approved_intent(
            intent.intent_id,
            authority_id=authority_id,
            quote_snapshot_id=quote_snapshot_id,
            max_drift_bps=Decimal("5"),
            at=NOW,
            expires_at=NOW + timedelta(seconds=5),
        )
        assert len(arm_id) == 64
        assert reopened.connection.execute("SELECT COUNT(*) FROM outbox_commands").fetchone()[0] == 1
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
        assert store.connection.execute("SELECT status FROM outbox_commands").fetchone()[0] == "DELIVERED"
        assert store.connection.execute("SELECT status FROM cancel_commands").fetchone()[0] == "DELIVERED"
        assert store.active_reserved_notional("paper-account") == Decimal("0")
    finally:
        store.close()


def test_authoritative_reconciliation_requires_semantic_consensus(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    broker = DurableFakeBroker(tmp_path / "broker.sqlite3")
    try:
        raw = broker.snapshot(at=NOW)
        incomplete = raw.model_copy(update={"complete": False})
        assert Reconciler(store).reconcile_authoritative(incomplete, at=NOW).status == "INCOMPLETE_SNAPSHOT"

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
        replay = Reconciler(store).reconcile_authoritative(
            snapshot, at=NOW + timedelta(seconds=2)
        )
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
        report = Reconciler(store).reconcile_authoritative(
            second, at=NOW + timedelta(seconds=2)
        )
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
        with pytest.raises(ExecutionInvariantError, match="TTL exceeds"):
            store.arm_approved_intent(
                intent.intent_id,
                authority_id=authority_id,
                quote_snapshot_id=canonical_hash({"quote": "not-yet-loaded"}),
                max_drift_bps=Decimal("5"),
                at=NOW,
                expires_at=NOW + timedelta(seconds=6),
            )
        with pytest.raises(ExecutionInvariantError, match="drift exceeds system policy"):
            store.arm_approved_intent(
                intent.intent_id,
                authority_id=authority_id,
                quote_snapshot_id=canonical_hash({"quote": "not-yet-loaded"}),
                max_drift_bps=Decimal("11"),
                at=NOW,
                expires_at=NOW + timedelta(seconds=5),
            )
        with pytest.raises(ExecutionInvariantError, match="quote snapshot is unknown"):
            store.arm_approved_intent(
                intent.intent_id,
                authority_id=authority_id,
                quote_snapshot_id=canonical_hash({"caller": "self-reported"}),
                max_drift_bps=Decimal("5"),
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
                at=NOW,
                expires_at=NOW + timedelta(seconds=5),
            )
        assert "MARKET_QUOTE_STALE" in store.active_freeze_reasons()
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
        store.connection.execute(
            "UPDATE cash_projection SET cash_delta='-1100' WHERE singleton=1"
        )
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
                orders=(), positions={}, protections={}, events=(),
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
            broker.submit(
                intent, fencing_token=first.fencing_token, at=NOW + timedelta(seconds=3)
            )
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
