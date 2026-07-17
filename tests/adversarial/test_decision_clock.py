from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from hanalpha.agents import SkepticAgent
from hanalpha.domain.clock import FixedDecisionClock
from hanalpha.domain.models import Evidence


def test_fixed_decision_clock_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FixedDecisionClock(datetime(2025, 1, 1))


@pytest.mark.asyncio
async def test_skeptic_uses_replay_as_of_not_wall_clock(signal, regime, now) -> None:
    replay_as_of = now - timedelta(days=365)
    evidence = Evidence(
        evidence_id="historical-evidence",
        source="news",
        title="Historical verified news",
        observed_at=replay_as_of - timedelta(days=1),
        available_at=replay_as_of - timedelta(days=1),
        payload_hash="12345678abcdef",
        summary="Historical verified summary",
    )
    assessment = await SkepticAgent().assess(signal, [evidence], regime, replay_as_of)
    assert not any(item.startswith("stale_evidence") for item in assessment.invalidators)
