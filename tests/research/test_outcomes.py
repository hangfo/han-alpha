from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from hanalpha.research.outcomes import evaluate_decision_outcome
from hanalpha.simulation.events import DecisionIdentity, DecisionRecord


def test_rejected_decision_keeps_counterfactual_outcome() -> None:
    identity = DecisionIdentity.build(
        snapshot_id="1" * 64,
        as_of=datetime(2024, 1, 1, tzinfo=UTC),
        strategy_version="1",
        config_hash="2" * 64,
        input_hash="3" * 64,
        signal_hash="4" * 64,
        risk_hash="5" * 64,
    )
    decision = DecisionRecord(
        identity=identity,
        strategy_id="baseline",
        instrument_id="inst-alpha",
        order_id=None,
        approved=False,
        reason="risk limit exceeded",
    )
    outcome = evaluate_decision_outcome(
        decision,
        decision_price=Decimal("100"),
        evaluation_price=Decimal("110"),
    )
    assert not outcome.executed
    assert outcome.gross_return == Decimal("0.1")
    assert outcome.rejection_reason == "risk limit exceeded"
