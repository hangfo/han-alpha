from __future__ import annotations

from typing import Protocol

from hanalpha.domain.models import AgentAssessment, Evidence, RegimeSnapshot, Signal


class ResearchAgent(Protocol):
    name: str

    async def assess(
        self,
        signal: Signal,
        evidence: list[Evidence],
        regime: RegimeSnapshot,
    ) -> AgentAssessment: ...
