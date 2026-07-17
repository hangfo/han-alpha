import pytest

from hanalpha.agents import AgentCommittee, EvidenceAgent, MarketAlignmentAgent, SkepticAgent
from hanalpha.domain.enums import MarketRegime


@pytest.mark.asyncio
async def test_committee_approves_clean_price_signal(signal, regime) -> None:
    committee = AgentCommittee([EvidenceAgent(), MarketAlignmentAgent(), SkepticAgent()])
    approved, assessments = await committee.review(signal, [], regime, signal.generated_at)
    assert approved
    assert len(assessments) == 3


@pytest.mark.asyncio
async def test_committee_vetoes_regime_mismatch(signal, regime) -> None:
    blocked = regime.model_copy(
        update={"regime": MarketRegime.RISK_OFF, "allowed_strategies": ["event_continuation"]}
    )
    committee = AgentCommittee([EvidenceAgent(), MarketAlignmentAgent(), SkepticAgent()])
    approved, assessments = await committee.review(signal, [], blocked, signal.generated_at)
    assert not approved
    assert any(item.veto for item in assessments)
