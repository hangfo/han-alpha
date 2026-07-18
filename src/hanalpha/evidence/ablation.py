from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AblationObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    baseline_allowed: bool
    evidence_allowed: bool
    forward_return: Decimal
    llm_cost: Decimal = Field(ge=0)
    latency_cost: Decimal = Field(default=Decimal("0"), ge=0)


class EvidenceDeltaReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    observations: int
    baseline_mean_return: Decimal
    evidence_mean_return: Decimal
    avoided_loss: Decimal
    missed_gain: Decimal
    total_model_cost: Decimal
    total_latency_cost: Decimal
    net_incremental_value: Decimal


def evidence_delta_report(
    observations: tuple[AblationObservation, ...],
) -> EvidenceDeltaReport:
    if not observations:
        raise ValueError("ablation requires observations")
    baseline = [item.forward_return for item in observations if item.baseline_allowed]
    evidence = [item.forward_return for item in observations if item.evidence_allowed]
    baseline_mean = sum(baseline, Decimal("0")) / len(baseline) if baseline else Decimal("0")
    evidence_mean = sum(evidence, Decimal("0")) / len(evidence) if evidence else Decimal("0")
    vetoed = [item for item in observations if item.baseline_allowed and not item.evidence_allowed]
    avoided = sum(
        (-item.forward_return for item in vetoed if item.forward_return < 0), Decimal("0")
    )
    missed = sum((item.forward_return for item in vetoed if item.forward_return > 0), Decimal("0"))
    model_cost = sum((item.llm_cost for item in observations), Decimal("0"))
    latency_cost = sum((item.latency_cost for item in observations), Decimal("0"))
    incremental = evidence_mean - baseline_mean + avoided - missed - model_cost - latency_cost
    return EvidenceDeltaReport(
        observations=len(observations),
        baseline_mean_return=baseline_mean,
        evidence_mean_return=evidence_mean,
        avoided_loss=avoided,
        missed_gain=missed,
        total_model_cost=model_cost,
        total_latency_cost=latency_cost,
        net_incremental_value=incremental,
    )
