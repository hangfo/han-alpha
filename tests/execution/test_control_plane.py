from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from hanalpha.domain.enums import Side
from hanalpha.execution.control_models import (
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


@pytest.mark.parametrize("failpoint", ["after_capsule", "after_reservation", "after_outbox"])
def test_stage_is_atomic_across_crash_boundaries(tmp_path, failpoint) -> None:
    store = DurableExecutionStore(tmp_path / f"{failpoint}.sqlite3")
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
    store.stage(capsule, reservation, intent)
    assert store.pending_approval_count() == 1
    store.close()

    reopened = DurableExecutionStore(path)
    try:
        approval_id = reopened.approve(intent.intent_id, actor_id="operator-1", at=NOW)
        assert len(approval_id) == 64
        assert reopened.pending_approval_count() == 0
        assert (
            reopened.connection.execute("SELECT COUNT(*) FROM operator_approvals").fetchone()[0]
            == 1
        )
        assert (
            reopened.connection.execute("SELECT COUNT(*) FROM outbox_commands").fetchone()[0] == 1
        )
        with pytest.raises(ExecutionInvariantError, match="different approval"):
            reopened.approve(intent.intent_id, actor_id="operator-2", at=NOW)
    finally:
        reopened.close()


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
        assert "NAKED_LONG_EXPOSURE" in {item.kind for item in report.discrepancies}
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
