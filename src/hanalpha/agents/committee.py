from __future__ import annotations

from hanalpha.agents.base import ResearchAgent
from hanalpha.domain.enums import SignalAction
from hanalpha.domain.models import AgentAssessment, Evidence, RegimeSnapshot, Signal


class AgentCommittee:
    def __init__(self, agents: list[ResearchAgent]) -> None:
        self.agents = agents

    async def review(
        self,
        signal: Signal,
        evidence: list[Evidence],
        regime: RegimeSnapshot,
    ) -> tuple[bool, list[AgentAssessment]]:
        assessments = [await agent.assess(signal, evidence, regime) for agent in self.agents]
        vetoed = any(item.veto or item.action == SignalAction.VETO for item in assessments)
        if vetoed:
            return False, assessments
        supportive = [item for item in assessments if item.action == signal.action]
        weighted_confidence = sum(item.confidence for item in supportive) / max(1, len(assessments))
        return weighted_confidence >= 0.55, assessments
