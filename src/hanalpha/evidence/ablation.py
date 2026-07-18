from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from hanalpha.evidence.models import EvidenceDecision


class AblationObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    baseline_allowed: bool
    evidence_decision: EvidenceDecision
    risk_weight: Decimal = Field(default=Decimal("1"), ge=0)
    forward_return: Decimal
    llm_cost: Decimal = Field(ge=0)
    latency_cost: Decimal = Field(default=Decimal("0"), ge=0)


class EvidenceDeltaReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    observations: int
    baseline_mean_return: Decimal
    evidence_mean_return: Decimal
    baseline_total_pnl: Decimal
    evidence_total_pnl: Decimal
    avoided_loss: Decimal
    missed_gain: Decimal
    extra_gain: Decimal
    extra_loss: Decimal
    total_model_cost: Decimal
    total_latency_cost: Decimal
    net_incremental_value: Decimal


def evidence_delta_report(
    observations: tuple[AblationObservation, ...],
) -> EvidenceDeltaReport:
    if not observations:
        raise ValueError("ablation requires observations")
    baseline_pnls = tuple(
        item.risk_weight * item.forward_return if item.baseline_allowed else Decimal("0")
        for item in observations
    )
    evidence_pnls = tuple(
        item.risk_weight * item.forward_return
        if item.baseline_allowed and item.evidence_decision == EvidenceDecision.NO_OBJECTION
        else Decimal("0")
        for item in observations
    )
    baseline_total = sum(baseline_pnls, Decimal("0"))
    gross_evidence_total = sum(evidence_pnls, Decimal("0"))
    baseline_mean = baseline_total / len(observations)
    evidence_mean = gross_evidence_total / len(observations)
    vetoed = [
        item
        for item in observations
        if item.baseline_allowed and item.evidence_decision == EvidenceDecision.VETO
    ]
    avoided = sum(
        (-item.risk_weight * item.forward_return for item in vetoed if item.forward_return < 0),
        Decimal("0"),
    )
    missed = sum(
        (item.risk_weight * item.forward_return for item in vetoed if item.forward_return > 0),
        Decimal("0"),
    )
    extra_gain = Decimal("0")
    extra_loss = Decimal("0")
    model_cost = sum((item.llm_cost for item in observations), Decimal("0"))
    latency_cost = sum((item.latency_cost for item in observations), Decimal("0"))
    evidence_total = gross_evidence_total - model_cost - latency_cost
    incremental = evidence_total - baseline_total
    return EvidenceDeltaReport(
        observations=len(observations),
        baseline_mean_return=baseline_mean,
        evidence_mean_return=evidence_mean,
        baseline_total_pnl=baseline_total,
        evidence_total_pnl=evidence_total,
        avoided_loss=avoided,
        missed_gain=missed,
        extra_gain=extra_gain,
        extra_loss=extra_loss,
        total_model_cost=model_cost,
        total_latency_cost=latency_cost,
        net_incremental_value=incremental,
    )
