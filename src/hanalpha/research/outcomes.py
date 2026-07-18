from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from hanalpha.simulation.events import DecisionRecord


class DecisionOutcome(BaseModel):
    """Comparable realized/counterfactual outcome for traded and rejected decisions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    instrument_id: str
    executed: bool
    decision_price: Decimal = Field(gt=0)
    evaluation_price: Decimal = Field(gt=0)
    gross_return: Decimal
    rejection_reason: str | None


def evaluate_decision_outcome(
    decision: DecisionRecord,
    *,
    decision_price: Decimal,
    evaluation_price: Decimal,
) -> DecisionOutcome:
    if decision_price <= 0 or evaluation_price <= 0:
        raise ValueError("outcome prices must be positive")
    return DecisionOutcome(
        decision_id=decision.identity.decision_id,
        instrument_id=decision.instrument_id,
        executed=decision.approved,
        decision_price=decision_price,
        evaluation_price=evaluation_price,
        gross_return=evaluation_price / decision_price - Decimal("1"),
        rejection_reason=None if decision.approved else decision.reason,
    )
