from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PromotionThresholds(BaseModel):
    """Pre-registered, fail-closed research promotion thresholds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    minimum_observations: int = Field(default=252, ge=30)
    minimum_oos_return_after_costs: Decimal = Decimal("0")
    minimum_deflated_sharpe_probability: Decimal = Field(default=Decimal("0.95"), ge=0, le=1)
    maximum_pbo: Decimal = Field(default=Decimal("0.20"), ge=0, le=1)
    maximum_drawdown: Decimal = Field(default=Decimal("0.25"), ge=0, le=1)
    minimum_cost_stress_return: Decimal = Decimal("0")
    maximum_single_instrument_contribution: Decimal = Field(default=Decimal("0.35"), ge=0, le=1)


class PromotionEvidence(BaseModel):
    """Evidence packet; missing diagnostics are deliberately represented by None."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_hash: str
    expected_protocol_hash: str
    observations: int = Field(ge=0)
    oos_return_after_costs: Decimal
    deflated_sharpe_probability: Decimal | None = Field(default=None, ge=0, le=1)
    pbo: Decimal | None = Field(default=None, ge=0, le=1)
    max_drawdown: Decimal = Field(ge=0)
    cost_stress_return: Decimal
    largest_instrument_contribution: Decimal = Field(ge=0)
    parameter_stable: bool
    artifacts_verified: bool
    reproducible: bool
    independent_approved: bool
    budget_exhausted: bool = False


def promotion_failures(
    evidence: PromotionEvidence, thresholds: PromotionThresholds
) -> tuple[str, ...]:
    checks = (
        (evidence.protocol_hash == evidence.expected_protocol_hash, "protocol_hash_mismatch"),
        (not evidence.budget_exhausted, "research_budget_exhausted"),
        (evidence.observations >= thresholds.minimum_observations, "insufficient_observations"),
        (
            evidence.oos_return_after_costs >= thresholds.minimum_oos_return_after_costs,
            "oos_return_below_threshold",
        ),
        (
            evidence.deflated_sharpe_probability is not None
            and evidence.deflated_sharpe_probability
            >= thresholds.minimum_deflated_sharpe_probability,
            "deflated_sharpe_gate_failed_or_missing",
        ),
        (
            evidence.pbo is not None and evidence.pbo <= thresholds.maximum_pbo,
            "pbo_gate_failed_or_missing",
        ),
        (evidence.max_drawdown <= thresholds.maximum_drawdown, "drawdown_gate_failed"),
        (
            evidence.cost_stress_return >= thresholds.minimum_cost_stress_return,
            "cost_stress_gate_failed",
        ),
        (
            evidence.largest_instrument_contribution
            <= thresholds.maximum_single_instrument_contribution,
            "concentration_gate_failed",
        ),
        (evidence.parameter_stable, "parameter_instability"),
        (evidence.artifacts_verified, "artifact_verification_failed"),
        (evidence.reproducible, "reproducibility_failed"),
        (evidence.independent_approved, "independent_approval_missing"),
    )
    return tuple(reason for passed, reason in checks if not passed)
