from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from hanalpha.execution import ibkr as ibkr_module
from hanalpha.execution.control_store import DurableExecutionStore
from hanalpha.execution.ibkr import IBKRBroker
from hanalpha.execution.ibkr_observer import (
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


def _semantic_facts(collector: IBKRCallbackCollector) -> None:
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
        ("TotalCashValue", "100000"),
        ("SettledCash", "100000"),
        ("BuyingPower", "100000"),
        ("AccruedCash", "0"),
    ):
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
        complete = collector.certificate(
            store, at=NOW, queue_drained=True, final_watermark=12
        )
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
            {"client_id": 1, "perm_id": 0, "status": "Filled", "filled": "10", "remaining": "0", "avg_fill_price": "101"},
            at=NOW,
        )
        collector.order_status(
            7,
            {"client_id": 1, "perm_id": 0, "status": "Submitted", "filled": "0", "remaining": "10", "avg_fill_price": "0"},
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


class _ObserverFakeApp:
    next_order_id = 42
    observer: IBKRCallbackCollector | None = None

    def __init__(self) -> None:
        self.cancelled_account: int | None = None
        self.disconnected = False

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

    def reqAccountSummary(self, request_id: int, account: str, _tags: str) -> None:
        assert self.observer and account == ACCOUNT
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
                    "account_hash": account_hash(account),
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
            },
            at=NOW,
        )
        self.observer.commission(
            "exec.1", {"commission": "1.25", "currency": "USD"}, at=NOW
        )
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
        first = control.register_snapshot_consensus(
            snapshot, at=NOW, minimum_interval=timedelta(seconds=1)
        )
        second = control.register_snapshot_consensus(
            snapshot,
            at=NOW + timedelta(seconds=2),
            minimum_interval=timedelta(seconds=1),
        )
        assert first == (False, 1)
        assert second == (True, 2)
    finally:
        control.close()
        fact_store.close()


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
