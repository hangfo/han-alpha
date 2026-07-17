from __future__ import annotations

from datetime import timedelta

from hanalpha.agents.firewall import contains_prompt_injection
from hanalpha.domain.enums import MarketRegime, SignalAction
from hanalpha.domain.models import AgentAssessment, Evidence, RegimeSnapshot, Signal, utc_now


class EvidenceAgent:
    name = "evidence_agent"

    async def assess(
        self,
        signal: Signal,
        evidence: list[Evidence],
        regime: RegimeSnapshot,
    ) -> AgentAssessment:
        evidence_ids = {item.evidence_id for item in evidence}
        missing = [item for item in signal.evidence_ids if item not in evidence_ids]
        if signal.strategy == "event_continuation" and (not signal.evidence_ids or missing):
            return AgentAssessment(
                agent_name=self.name,
                action=SignalAction.VETO,
                confidence=1.0,
                rationale="Event signal lacks complete point-in-time evidence.",
                evidence_ids=list(evidence_ids),
                invalidators=["missing_evidence"],
                veto=True,
            )
        return AgentAssessment(
            agent_name=self.name,
            action=signal.action,
            confidence=0.8,
            rationale="Required evidence is present or strategy is price-derived.",
            evidence_ids=list(evidence_ids),
        )


class SkepticAgent:
    name = "skeptic_agent"

    async def assess(
        self,
        signal: Signal,
        evidence: list[Evidence],
        regime: RegimeSnapshot,
    ) -> AgentAssessment:
        now = utc_now()
        reasons: list[str] = []
        if regime.regime in {MarketRegime.RISK_OFF, MarketRegime.UNKNOWN} and signal.strategy == "breakout":
            reasons.append("breakout_not_allowed_in_current_regime")
        for item in evidence:
            if now - item.available_at > timedelta(days=7):
                reasons.append(f"stale_evidence:{item.evidence_id}")
            if contains_prompt_injection(item.summary) or contains_prompt_injection(item.title):
                reasons.append(f"prompt_injection:{item.evidence_id}")
        if signal.confidence < 0.55:
            reasons.append("low_signal_confidence")
        veto = bool(reasons)
        return AgentAssessment(
            agent_name=self.name,
            action=SignalAction.VETO if veto else signal.action,
            confidence=0.95 if veto else 0.7,
            rationale="; ".join(reasons) if reasons else "No deterministic contradiction found.",
            evidence_ids=[item.evidence_id for item in evidence],
            invalidators=reasons,
            veto=veto,
        )


class MarketAlignmentAgent:
    name = "market_alignment_agent"

    async def assess(
        self,
        signal: Signal,
        evidence: list[Evidence],
        regime: RegimeSnapshot,
    ) -> AgentAssessment:
        allowed = signal.strategy in regime.allowed_strategies
        return AgentAssessment(
            agent_name=self.name,
            action=signal.action if allowed else SignalAction.VETO,
            confidence=0.85,
            rationale=(
                f"Strategy {signal.strategy} is allowed in {regime.regime}."
                if allowed
                else f"Strategy {signal.strategy} is blocked in {regime.regime}."
            ),
            evidence_ids=[item.evidence_id for item in evidence],
            invalidators=[] if allowed else ["regime_strategy_mismatch"],
            veto=not allowed,
        )
