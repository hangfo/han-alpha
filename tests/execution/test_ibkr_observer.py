from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hanalpha.execution import ibkr as ibkr_module
from hanalpha.execution.ibkr import IBKRBroker
from hanalpha.execution.ibkr_observer import (
    IBKRCallbackCollector,
    IBKRFactReducer,
    IBKRFactStore,
    IBKRFactType,
)

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def _complete_markers(collector: IBKRCallbackCollector) -> None:
    for kind in (
        IBKRFactType.CONNECTION,
        IBKRFactType.NEXT_VALID_ID,
        IBKRFactType.MANAGED_ACCOUNTS,
        IBKRFactType.SERVER_TIME,
        IBKRFactType.ACCOUNT_END,
        IBKRFactType.OPEN_ORDER_END,
        IBKRFactType.POSITION_END,
        IBKRFactType.EXECUTION_END,
    ):
        collector.record(kind, {}, identity_key=kind.value, at=NOW)


def test_completeness_certificate_fails_closed_until_every_end_marker(tmp_path) -> None:
    store = IBKRFactStore(tmp_path / "observer.sqlite3")
    session = store.start_session(host="127.0.0.1", port=7497, client_id=19, at=NOW)
    collector = IBKRCallbackCollector(store, session)
    try:
        _complete_markers(collector)
        assert collector.certificate(at=NOW).complete
        collector.record(
            IBKRFactType.ERROR,
            {"code": 1100, "message": "connectivity lost"},
            identity_key="1100",
            at=NOW,
        )
        failed = collector.certificate(at=NOW)
        assert not failed.complete
        assert failed.critical_errors == (1100,)
    finally:
        store.close()


def test_reducer_is_order_independent_and_uses_exec_identity(tmp_path) -> None:
    store = IBKRFactStore(tmp_path / "observer.sqlite3")
    session = store.start_session(host="127.0.0.1", port=7497, client_id=19, at=NOW)
    collector = IBKRCallbackCollector(store, session)
    try:
        collector.commission("trade.1.01", {"commission": "1.25"}, at=NOW)
        collector.execution("trade.1.01", {"shares": "4", "price": "100"}, at=NOW)
        collector.execution("trade.1.02", {"shares": "3", "price": "101"}, at=NOW)
        collector.order_status(7, {"status": "Submitted", "filled": "0"}, at=NOW)
        collector.order_status(7, {"status": "Submitted", "filled": "0"}, at=NOW)
        collector.order_status(7, {"status": "Filled", "filled": "10"}, at=NOW)
        facts = store.facts(session)
        assert len([f for f in facts if f.fact_type == IBKRFactType.ORDER_STATUS]) == 2
        forward = IBKRFactReducer.reduce(facts)
        backward = IBKRFactReducer.reduce(tuple(reversed(facts)))
        assert forward == backward
        assert forward.unmatched_commission_exec_ids == ()
        assert forward.corrected_execution_roots == ("trade.1",)
        assert forward.effective_executions["trade.1"]["exec_id"] == "trade.1.02"
        assert forward.orders["7"]["status"] == "Filled"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_observe_read_only_requests_truth_without_order_writes(tmp_path, monkeypatch) -> None:
    class FakeApp:
        next_order_id = 42
        observer: IBKRCallbackCollector | None = None

        def isConnected(self) -> bool:
            return True

        def reqCurrentTime(self) -> None:
            assert self.observer
            self.observer.record(IBKRFactType.SERVER_TIME, {}, identity_key="time", at=NOW)

        def reqManagedAccts(self) -> None:
            assert self.observer
            self.observer.record(IBKRFactType.MANAGED_ACCOUNTS, {}, identity_key="accounts", at=NOW)

        def reqAccountSummary(self, *_args) -> None:
            assert self.observer
            self.observer.record(IBKRFactType.ACCOUNT_END, {}, identity_key="account", at=NOW)

        def reqAllOpenOrders(self) -> None:
            assert self.observer
            self.observer.record(IBKRFactType.OPEN_ORDER_END, {}, identity_key="orders", at=NOW)

        def reqPositions(self) -> None:
            assert self.observer
            self.observer.record(IBKRFactType.POSITION_END, {}, identity_key="positions", at=NOW)

        def reqExecutions(self, *_args) -> None:
            assert self.observer
            self.observer.record(IBKRFactType.EXECUTION_END, {}, identity_key="execs", at=NOW)

    monkeypatch.setattr(ibkr_module, "ExecutionFilter", lambda: object())
    broker = object.__new__(IBKRBroker)
    broker.host = "127.0.0.1"
    broker.port = 7497
    broker.client_id = 19
    broker.app = FakeApp()
    store = IBKRFactStore(tmp_path / "observer.sqlite3")
    try:
        certificate, model = await broker.observe_read_only(store, timeout=0.2)
        assert certificate.complete
        assert model.orders == {}
    finally:
        store.close()


@pytest.mark.asyncio
async def test_observer_rejects_live_port_before_any_request(tmp_path) -> None:
    broker = object.__new__(IBKRBroker)
    broker.host = "127.0.0.1"
    broker.port = 7496
    broker.client_id = 19
    store = IBKRFactStore(tmp_path / "observer.sqlite3")
    try:
        with pytest.raises(RuntimeError, match="paper ports"):
            await broker.observe_read_only(store)
    finally:
        store.close()
