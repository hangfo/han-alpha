from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hanalpha.domain.enums import Side
from hanalpha.execution.control_store import DurableExecutionStore
from hanalpha.execution.shadow import ExecutionSlice, ShadowExecutionEvaluator

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def test_shadow_execution_decomposes_cost_and_persists_reality_gap(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    try:
        gap = ShadowExecutionEvaluator(store).evaluate(
            decision_id="decision-1",
            client_order_key="a" * 64,
            side=Side.BUY,
            quantity=10,
            decision_price=Decimal("100"),
            shadow_fill_price=Decimal("100.10"),
            broker_fill_price=Decimal("100.25"),
            broker_commission=Decimal("1.25"),
            observed_latency_ms=250,
            at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert gap.decision_to_shadow == Decimal("1.00")
        assert gap.shadow_to_broker == Decimal("1.50")
        assert gap.total_implementation_shortfall == Decimal("3.75")
        assert store.connection.execute("SELECT COUNT(*) FROM reality_gap_ledger").fetchone()[0] == 1
    finally:
        store.close()


def test_shadow_missed_fill_is_explicit_not_zero_cost(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    try:
        gap = ShadowExecutionEvaluator(store).evaluate(
            decision_id="decision-2",
            client_order_key="b" * 64,
            side=Side.SELL,
            quantity=5,
            decision_price=Decimal("50"),
            shadow_fill_price=None,
            broker_fill_price=None,
            broker_commission=Decimal("0"),
            observed_latency_ms=1_000,
            at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert gap.missed_fill
        assert gap.total_implementation_shortfall is None
    finally:
        store.close()


def test_shadow_schedule_measures_partial_fill_opportunity_and_protection(tmp_path) -> None:
    store = DurableExecutionStore(tmp_path / "control.sqlite3")
    try:
        gap = ShadowExecutionEvaluator(store).evaluate_schedule(
            decision_id="decision-schedule",
            client_order_key="c" * 64,
            side=Side.BUY,
            quantity=10,
            decision_price=Decimal("100"),
            shadow_slices=(
                ExecutionSlice(quantity=10, price=Decimal("100.10"), occurred_at=NOW),
            ),
            broker_slices=(
                ExecutionSlice(
                    quantity=3,
                    price=Decimal("100.20"),
                    commission=Decimal("0.50"),
                    occurred_at=NOW + timedelta(milliseconds=200),
                ),
                ExecutionSlice(
                    quantity=2,
                    price=Decimal("100.40"),
                    commission=Decimal("0.25"),
                    occurred_at=NOW + timedelta(milliseconds=400),
                ),
            ),
            terminal_mark=Decimal("101"),
            submitted_at=NOW,
            protection_ack_at=NOW + timedelta(milliseconds=650),
            at=NOW + timedelta(seconds=1),
        )
        assert gap.broker_fill_price == Decimal("100.28")
        assert gap.broker_filled_quantity == 5
        assert gap.broker_unfilled_quantity == 5
        assert gap.opportunity_cost == Decimal("5")
        assert gap.protection_delay_ms == 650
        assert gap.broker_fill_slices == 2
    finally:
        store.close()
