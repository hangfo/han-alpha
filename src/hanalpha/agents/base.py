from __future__ import annotations

from datetime import datetime
from typing import Protocol

from hanalpha.domain.models import AgentAssessment, Evidence, RegimeSnapshot, Signal


class ResearchAgent(Protocol):
    name: str

    async def assess(
        self,
        signal: Signal,
        evidence: list[Evidence],
        regime: RegimeSnapshot,
        as_of: datetime,
    ) -> AgentAssessment: ...
