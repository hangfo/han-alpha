from datetime import datetime

import pytest

from hanalpha.agents import AgentCommittee, EvidenceAgent, MarketAlignmentAgent, SkepticAgent
from hanalpha.data.synthetic import SyntheticMarketDataProvider
from hanalpha.domain.clock import FixedDecisionClock
from hanalpha.execution import SimulatedBroker
from hanalpha.orchestrator import TradingSystem
from hanalpha.portfolio import Ledger


@pytest.mark.asyncio
async def test_full_synthetic_cycle(tmp_path, risk_config, runtime_access, now) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    provider = SyntheticMarketDataProvider(risk_config.bar_interval_minutes)
    broker = SimulatedBroker(risk_config.starting_cash, risk_config.execution)
    system = TradingSystem(
        config=risk_config,
        provider=provider,
        broker=broker,
        ledger=ledger,
        committee=AgentCommittee([EvidenceAgent(), MarketAlignmentAgent(), SkepticAgent()]),
        runtime_access=runtime_access,
        clock=FixedDecisionClock(now),
    )
    result = await system.run_cycle()
    assert result["cycle"] == 1
    assert result["regime"]["regime"] in {"RISK_ON", "NEUTRAL", "RISK_OFF", "UNKNOWN"}
    assert result["account"]["net_liquidation"] > 0
    assert ledger.recent_events(10) is not None
    with pytest.raises(ValueError, match="timezone-aware"):
        await system.run_cycle(datetime(2025, 1, 1))
    ledger.close()
