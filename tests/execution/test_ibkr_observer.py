from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from hanalpha.execution import ibkr as ibkr_module
from hanalpha.execution.control_store import DurableExecutionStore
from hanalpha.execution.ibkr import IBKRBroker
from hanalpha.execution.ibkr_observer import (
    CompletedOrdersScope,
    IBKRCallbackCollector,
    IBKRFactBridge,
    IBKRFactReducer,
    IBKRFactStore,
    IBKRFactType,
    ObserverRequestBarrier,
    account_hash,
)
from hanalpha.execution.ibkr_snapshot import IBKRBrokerSnapshotAdapter

NOW = datetime(2024, 1, 1, tzinfo=UTC)
ACCOUNT = "DU1234567"


def _barrier() -> ObserverRequestBarrier:
    return ObserverRequestBarrier(
        account_request_id=101,
        execution_request_id=102,
        position_epoch="p" * 64,
        open_orders_epoch="o" * 64,
        execution_history_start=NOW - timedelta(days=1),
        execution_history_end=NOW,
    )


def _semantic_facts(
    collector: IBKRCallbackCollector,
    *,
    cash: str = "100000",
    omitted_account_tags: frozenset[str] = frozenset(),
) -> None:
    barrier = collector.barrier
    assert barrier is not None
    collector.record(IBKRFactType.CONNECTION, {}, identity_key="connected", at=NOW)
    collector.record(IBKRFactType.NEXT_VALID_ID, {"order_id": 1}, identity_key="1", at=NOW)
    collector.record(
        IBKRFactType.MANAGED_ACCOUNTS,
        {"account_count": 1, "account_hashes": [account_hash(ACCOUNT)]},
        identity_key="accounts",
        at=NOW,
    )
    collector.record(IBKRFactType.SERVER_TIME, {}, identity_key="time", at=NOW)
    for tag, value in (
        ("NetLiquidation", "100000"),
        ("TotalCashValue", cash),
        ("SettledCash", cash),
        ("BuyingPower", cash),
        ("AccruedCash", "0"),
    ):
        if tag in omitted_account_tags:
            continue
        collector.record(
            IBKRFactType.ACCOUNT_VALUE,
            {
                "request_id": barrier.account_request_id,
                "account_hash": account_hash(ACCOUNT),
                "tag": tag,
                "value": value,
                "currency": "USD",
            },
            identity_key=tag,
            at=NOW,
        )
    collector.record(
        IBKRFactType.ACCOUNT_END,
        {"request_id": barrier.account_request_id},
        identity_key="account-end",
        at=NOW,
    )
    collector.record(
        IBKRFactType.OPEN_ORDER_END,
        {"epoch": barrier.open_orders_epoch},
        identity_key="orders-end",
        at=NOW,
    )
    collector.record(
        IBKRFactType.POSITION_END,
        {"epoch": barrier.position_epoch},
        identity_key="positions-end",
        at=NOW,
    )
    collector.record(
        IBKRFactType.EXECUTION_END,
        {"request_id": barrier.execution_request_id},
        identity_key="exec-end",
        at=NOW,
    )


def test_semantic_certificate_rejects_wrong_request_barrier(tmp_path) -> None:
    store = IBKRFactStore(tmp_path / "observer.sqlite3")
    session = store.start_session(host="127.0.0.1", port=7497, client_id=19, at=NOW)
    collector = IBKRCallbackCollector(
        store,
        session,
        barrier=_barrier(),
        configured_account=ACCOUNT,
        base_currency="USD",
        client_id=19,
    )
    try:
        _semantic_facts(collector)
        complete = collector.certificate(store, at=NOW, queue_drained=True, final_watermark=12)
        assert complete.complete
        collector.record(
            IBKRFactType.ERROR,
            {"code": 1100, "message": "connectivity lost"},
            identity_key="1100",
            at=NOW,
        )
        assert not collector.certificate(
            store, at=NOW, queue_drained=True, final_watermark=13
        ).complete

        wrong = IBKRCallbackCollector(
            store,
            session,
            barrier=_barrier().model_copy(update={"account_request_id": 9001}),
            configured_account=ACCOUNT,
            client_id=19,
        )
        assert not wrong.certificate(
            store, at=NOW, queue_drained=True, final_watermark=13
        ).request_ids_match
    finally:
        store.close()


def test_optional_account_summary_tags_do_not_block_completeness(tmp_path) -> None:
    store = IBKRFactStore(tmp_path / "observer.sqlite3")
    session = store.start_session(host="127.0.0.1", port=7497, client_id=19, at=NOW)
    collector = IBKRCallbackCollector(
        store,
        session,
        barrier=_barrier(),
        configured_account=ACCOUNT,
        base_currency="USD",
        client_id=19,
    )
    try:
        _semantic_facts(
            collector,
            omitted_account_tags=frozenset({"SettledCash", "AccruedCash"}),
        )
        certificate = collector.certificate(
            store, at=NOW, queue_drained=True, final_watermark=10
        )
        assert certificate.required_account_tags_seen
        assert certificate.cash_snapshot_complete
        assert certificate.complete
    finally:
        store.close()


@pytest.mark.parametrize("missing_tag", ["NetLiquidation", "TotalCashValue", "BuyingPower"])
def test_missing_authoritative_account_tag_rejects_completeness(
    tmp_path, missing_tag: str
) -> None:
    store = IBKRFactStore(tmp_path / f"{missing_tag}.sqlite3")
    session = store.start_session(host="127.0.0.1", port=7497, client_id=19, at=NOW)
    collector = IBKRCallbackCollector(
        store,
        session,
        barrier=_barrier(),
        configured_account=ACCOUNT,
        base_currency="USD",
        client_id=19,
    )
    try:
        _semantic_facts(collector, omitted_account_tags=frozenset({missing_tag}))
        certificate = collector.certificate(
            store, at=NOW, queue_drained=True, final_watermark=10
        )
        assert not certificate.required_account_tags_seen
        assert not certificate.cash_snapshot_complete
        assert not certificate.complete
    finally:
        store.close()


def test_account_amounts_change_component_and_combined_authority_hashes(tmp_path) -> None:
    hashes: list[tuple[str, str]] = []
    for index, cash in enumerate(("100000", "50000")):
        store = IBKRFactStore(tmp_path / f"observer-{index}.sqlite3")
        session = store.start_session(
            host="127.0.0.1", port=7497, client_id=19, at=NOW + timedelta(seconds=index)
        )
        collector = IBKRCallbackCollector(
            store,
            session,
            barrier=_barrier(),
            configured_account=ACCOUNT,
            base_currency="USD",
            client_id=19,
        )
        _semantic_facts(collector, cash=cash)
        certificate = collector.certificate(
            store, at=NOW + timedelta(seconds=index), queue_drained=True, final_watermark=12
        )
        hashes.append((certificate.account_hash, certificate.semantic_hash))
        store.close()
    assert hashes[0][0] != hashes[1][0]
    assert hashes[0][1] != hashes[1][1]


def test_scope_policy_excludes_observation_window_and_certificate_counts_drops(
    tmp_path,
) -> None:
    certificates = []
    for index in range(2):
        store = IBKRFactStore(tmp_path / f"scope-{index}.sqlite3")
        at = NOW + timedelta(seconds=index)
        session = store.start_session(host="127.0.0.1", port=7497, client_id=19, at=at)
        barrier = _barrier().model_copy(
            update={
                "account_request_id": 101 + index * 10,
                "execution_request_id": 102 + index * 10,
                "execution_history_end": at,
                "completed_orders_requested": True,
                "completed_orders_api_only": True,
            }
        )
        collector = IBKRCallbackCollector(
            store,
            session,
            barrier=barrier,
            configured_account=ACCOUNT,
            base_currency="USD",
            client_id=19,
        )
        _semantic_facts(collector)
        collector.record(
            IBKRFactType.COMPLETED_ORDER_END,
            {},
            identity_key="completed-end",
            at=at,
        )
        certificate = collector.certificate(
            store,
            at=at,
            queue_drained=True,
            accepted_facts=20,
            written_facts=20,
            dropped_facts=0,
            final_watermark=20 + index,
        )
        certificates.append(certificate)
        store.close()
    assert certificates[0].visibility.scope_hash == certificates[1].visibility.scope_hash
    assert (
        certificates[0].visibility.observation_window.envelope_hash
        != certificates[1].visibility.observation_window.envelope_hash
    )
    assert certificates[0].visibility.completed_orders_api_only is True
    assert not certificates[0].visibility.manual_completed_orders_visible

    store = IBKRFactStore(tmp_path / "dropped.sqlite3")
    session = store.start_session(host="127.0.0.1", port=7497, client_id=19, at=NOW)
    collector = IBKRCallbackCollector(
        store,
        session,
        barrier=_barrier(),
        configured_account=ACCOUNT,
        client_id=19,
    )
    _semantic_facts(collector)
    dropped = collector.certificate(
        store,
        at=NOW,
        queue_drained=False,
        accepted_facts=20,
        written_facts=19,
        dropped_facts=1,
        final_watermark=19,
    )
    assert not dropped.complete
    assert (dropped.accepted_facts, dropped.written_facts, dropped.dropped_facts) == (
        20,
        19,
        1,
    )
    store.close()


def test_callback_threads_use_queue_and_single_sqlite_writer(tmp_path) -> None:
    path = tmp_path / "observer.sqlite3"
    store = IBKRFactStore(path)
    session = store.start_session(host="127.0.0.1", port=7497, client_id=19, at=NOW)
    bridge = IBKRFactBridge(path, max_queue=2_000)
    collector = IBKRCallbackCollector(bridge, session)
    try:

        def produce(offset: int) -> None:
            for index in range(250):
                collector.record(
                    IBKRFactType.ORDER_STATUS,
                    {"order_id": offset + index, "status": "Submitted"},
                    identity_key=f"{offset + index}",
                    at=NOW,
                )

        threads = [threading.Thread(target=produce, args=(index * 250,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert bridge.drain(timeout=5, quiet_period=0.01)
        bridge.close()
        assert bridge.writer_error is None
        assert bridge.written == 1_000
        assert len(store.facts(session)) == 1_000
    finally:
        bridge.close()
        store.close()


def test_reducer_uses_native_order_identity_field_lattice_and_numeric_corrections(tmp_path) -> None:
    store = IBKRFactStore(tmp_path / "observer.sqlite3")
    session = store.start_session(host="127.0.0.1", port=7497, client_id=19, at=NOW)
    collector = IBKRCallbackCollector(store, session, client_id=19)
    try:
        collector.order_status(
            7,
            {
                "client_id": 1,
                "perm_id": 0,
                "status": "Filled",
                "filled": "10",
                "remaining": "0",
                "avg_fill_price": "101",
            },
            at=NOW,
        )
        collector.order_status(
            7,
            {
                "client_id": 1,
                "perm_id": 0,
                "status": "Submitted",
                "filled": "0",
                "remaining": "10",
                "avg_fill_price": "0",
            },
            at=NOW,
        )
        collector.order_status(
            7,
            {"client_id": 2, "perm_id": 0, "status": "Submitted", "filled": "0", "remaining": "5"},
            at=NOW,
        )
        collector.execution("trade.1.2", {"shares": "4", "price": "100"}, at=NOW)
        collector.execution("trade.1.10", {"shares": "3", "price": "101"}, at=NOW)
        collector.commission("trade.1.10", {"commission": "1.25"}, at=NOW)
        facts = store.facts(session)
        forward = IBKRFactReducer.reduce(facts)
        backward = IBKRFactReducer.reduce(tuple(reversed(facts)))
        assert forward == backward
        assert len(forward.orders) == 2
        filled = next(order for order in forward.orders.values() if order["status"] == "Filled")
        assert filled["filled"] == "10"
        assert filled["remaining"] == "0"
        assert filled["avg_fill_price"] == "101"
        assert forward.effective_executions["trade.1"]["exec_id"] == "trade.1.10"
        assert forward.effective_commissions["trade.1"]["commission"] == "1.25"
    finally:
        store.close()


def test_perm_id_zero_bracket_legs_remain_distinct_by_leg_order_ref(tmp_path) -> None:
    store = IBKRFactStore(tmp_path / "observer.sqlite3")
    session = store.start_session(host="127.0.0.1", port=7497, client_id=19, at=NOW)
    collector = IBKRCallbackCollector(store, session, client_id=19)
    try:
        for order_id, parent_id, leg in ((10, 0, "P"), (11, 10, "T"), (12, 10, "S")):
            payload = {
                "order_id": order_id,
                "parent_id": parent_id,
                "client_id": 19,
                "perm_id": 0,
                "order_ref": f"HA:{'a' * 44}:{leg}",
                "status": "Submitted",
            }
            collector.record(
                IBKRFactType.OPEN_ORDER,
                payload,
                identity_key=collector.order_identity(payload),
                at=NOW,
            )
        model = IBKRFactReducer.reduce(store.facts(session))
        assert len(model.orders) == 3
    finally:
        store.close()


class _ObserverFakeApp:
    next_order_id = 42
    observer: IBKRCallbackCollector | None = None

    def __init__(self) -> None:
        self.cancelled_account: int | None = None
        self.disconnected = False
        self.completed_order_scopes: list[bool] = []

    def isConnected(self) -> bool:
        return True

    def reqCurrentTime(self) -> None:
        assert self.observer
        self.observer.record(IBKRFactType.SERVER_TIME, {}, identity_key="time", at=NOW)

    def reqManagedAccts(self) -> None:
        assert self.observer
        self.observer.record(
            IBKRFactType.MANAGED_ACCOUNTS,
            {"account_count": 1, "account_hashes": [account_hash(ACCOUNT)]},
            identity_key="accounts",
            at=NOW,
        )

    def reqAccountSummary(self, request_id: int, account_group: str, _tags: str) -> None:
        assert self.observer and account_group == "All"
        for tag, value in (
            ("NetLiquidation", "100000"),
            ("TotalCashValue", "100000"),
            ("SettledCash", "100000"),
            ("BuyingPower", "100000"),
            ("AccruedCash", "0"),
        ):
            self.observer.record(
                IBKRFactType.ACCOUNT_VALUE,
                {
                    "request_id": request_id,
                    "account_hash": account_hash(ACCOUNT),
                    "tag": tag,
                    "value": value,
                    "currency": "USD",
                },
                identity_key=f"{request_id}:{tag}",
                at=NOW,
            )
        self.observer.record(
            IBKRFactType.ACCOUNT_END,
            {"request_id": request_id},
            identity_key=f"end:{request_id}",
            at=NOW,
        )

    def reqAllOpenOrders(self) -> None:
        assert self.observer and self.observer.barrier
        base = {
            "perm_id": 9001,
            "client_id": 19,
            "account_hash": account_hash(ACCOUNT),
            "order_ref": "HA:" + "a" * 64,
            "symbol": "NVDA",
            "con_id": 42,
            "action": "BUY",
            "quantity": "10",
            "filled": "2",
            "status": "Submitted",
        }
        parent = {**base, "order_id": 10, "parent_id": 0, "order_type": "LMT"}
        target = {
            **base,
            "order_id": 11,
            "perm_id": 9002,
            "parent_id": 10,
            "action": "SELL",
            "order_type": "LMT",
        }
        stop = {
            **base,
            "order_id": 12,
            "perm_id": 9003,
            "parent_id": 10,
            "action": "SELL",
            "order_type": "STP",
        }
        for payload in (parent, target, stop):
            self.observer.record(
                IBKRFactType.OPEN_ORDER,
                payload,
                identity_key=self.observer.order_identity(payload),
                at=NOW,
            )
        self.observer.record(
            IBKRFactType.OPEN_ORDER_END,
            {"epoch": self.observer.barrier.open_orders_epoch},
            identity_key="orders",
            at=NOW,
        )

    def reqCompletedOrders(self, api_only: bool) -> None:
        assert self.observer
        self.completed_order_scopes.append(api_only)
        self.observer.record(
            IBKRFactType.COMPLETED_ORDER_END,
            {},
            identity_key=f"completed:{api_only}",
            at=NOW,
        )

    def reqPositions(self) -> None:
        assert self.observer and self.observer.barrier
        self.observer.record(
            IBKRFactType.POSITION,
            {
                "account_hash": account_hash(ACCOUNT),
                "con_id": 42,
                "symbol": "NVDA",
                "position": "2",
                "average_cost": "100",
            },
            identity_key="position:42",
            at=NOW,
        )
        self.observer.record(
            IBKRFactType.POSITION_END,
            {"epoch": self.observer.barrier.position_epoch},
            identity_key="positions",
            at=NOW,
        )

    def reqExecutions(self, request_id: int, _filter: object) -> None:
        assert self.observer
        self.observer.execution(
            "exec.1",
            {
                "request_id": request_id,
                "exec_id": "exec.1",
                "account_hash": account_hash(ACCOUNT),
                "order_id": 10,
                "perm_id": 9001,
                "client_id": 19,
                "order_ref": "HA:" + "a" * 64,
                "shares": "2",
                "price": "100.25",
                "time": "2023-12-31T23:59:59+00:00",
            },
            at=NOW,
        )
        self.observer.commission("exec.1", {"commission": "1.25", "currency": "USD"}, at=NOW)
        self.observer.record(
            IBKRFactType.EXECUTION_END,
            {"request_id": request_id},
            identity_key="execs",
            at=NOW,
        )

    def cancelAccountSummary(self, request_id: int) -> None:
        self.cancelled_account = request_id

    def cancelPositions(self) -> None:
        return

    def disconnect(self) -> None:
        self.disconnected = True


@pytest.mark.asyncio
async def test_observer_has_no_prerequests_drains_and_builds_reconciliation_snapshot(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(ibkr_module, "ExecutionFilter", lambda: object())
    broker = object.__new__(IBKRBroker)
    broker.host = "127.0.0.1"
    broker.port = 7497
    broker.client_id = 19
    broker.account = ACCOUNT
    broker.app = _ObserverFakeApp()
    broker.thread = None
    fact_store = IBKRFactStore(tmp_path / "observer.sqlite3")
    control = DurableExecutionStore(tmp_path / "control.sqlite3")
    try:
        certificate, model = await broker.observe_read_only(
            fact_store, timeout=0.5, drain_quiet_period=0.01
        )
        assert certificate.complete
        assert certificate.queue_drained
        assert certificate.visibility.completed_orders_api_only is True
        assert broker.app.completed_order_scopes == [True]
        assert broker.app.cancelled_account is not None
        assert broker.app.disconnected
        snapshot = IBKRBrokerSnapshotAdapter.build(
            model,
            certificate,
            configured_account=ACCOUNT,
            key_resolver=control,
        )
        assert snapshot.complete
        assert snapshot.cash == Decimal("100000")
        assert snapshot.positions == {"NVDA": 2}
        assert len(snapshot.orders) == 1
        assert len(snapshot.protection_orders) == 2
        assert snapshot.protections == {"NVDA": 10}
        assert snapshot.events[0].commission == Decimal("1.25")
        assert snapshot.events[0].occurred_at == NOW - timedelta(seconds=1)
        assert snapshot.events[0].received_at == NOW
        first = control.register_snapshot_consensus(
            snapshot, at=snapshot.as_of, minimum_interval=timedelta(0)
        )
        assert first == (False, 1)
        replay = control.register_snapshot_consensus(
            snapshot, at=snapshot.as_of, minimum_interval=timedelta(0)
        )
        assert replay == (False, 1)
        second_certificate, second_model = await broker.observe_read_only(
            fact_store, timeout=0.5, drain_quiet_period=0.01
        )
        independent = IBKRBrokerSnapshotAdapter.build(
            second_model,
            second_certificate,
            configured_account=ACCOUNT,
            key_resolver=control,
        )
        assert independent.session_id != snapshot.session_id
        assert independent.observation_id != snapshot.observation_id
        assert independent.final_watermark > snapshot.final_watermark
        assert independent.visibility_scope_hash == snapshot.visibility_scope_hash
        assert independent.semantic_hash == snapshot.semantic_hash
        assert control.register_snapshot_consensus(
            independent,
            at=independent.as_of,
            minimum_interval=timedelta(0),
        ) == (True, 2)
    finally:
        control.close()
        fact_store.close()


@pytest.mark.asyncio
async def test_observer_completed_order_scopes_are_distinct_and_auditable(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(ibkr_module, "ExecutionFilter", lambda: object())
    broker = object.__new__(IBKRBroker)
    broker.host = "127.0.0.1"
    broker.port = 7497
    broker.client_id = 19
    broker.account = ACCOUNT
    broker.app = _ObserverFakeApp()
    broker.thread = None
    store = IBKRFactStore(tmp_path / "scope-observer.sqlite3")
    try:
        api_certificate, _ = await broker.observe_read_only(
            store,
            timeout=0.5,
            drain_quiet_period=0.01,
            completed_orders_scope=CompletedOrdersScope.API,
        )
        all_certificate, _ = await broker.observe_read_only(
            store,
            timeout=0.5,
            drain_quiet_period=0.01,
            completed_orders_scope=CompletedOrdersScope.ALL,
        )
        assert broker.app.completed_order_scopes == [True, False]
        assert api_certificate.visibility.completed_orders_api_only is True
        assert all_certificate.visibility.completed_orders_api_only is False
        assert not api_certificate.visibility.manual_completed_orders_visible
        assert all_certificate.visibility.manual_completed_orders_visible
        assert (
            api_certificate.visibility.scope_hash
            != all_certificate.visibility.scope_hash
        )
    finally:
        store.close()


@pytest.mark.asyncio
async def test_observer_rejects_live_port_and_missing_account_before_requests(tmp_path) -> None:
    broker = object.__new__(IBKRBroker)
    broker.host = "127.0.0.1"
    broker.port = 7496
    broker.client_id = 19
    broker.account = ACCOUNT
    store = IBKRFactStore(tmp_path / "observer.sqlite3")
    try:
        with pytest.raises(RuntimeError, match="paper ports"):
            await broker.observe_read_only(store)
        broker.port = 7497
        broker.account = None
        with pytest.raises(RuntimeError, match="explicitly configured"):
            await broker.observe_read_only(store)
    finally:
        store.close()
