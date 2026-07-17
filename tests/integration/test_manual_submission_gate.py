from __future__ import annotations

import pytest

from hanalpha.agents import AgentCommittee, EvidenceAgent, MarketAlignmentAgent, SkepticAgent
from hanalpha.data.synthetic import SyntheticMarketDataProvider
from hanalpha.execution import SimulatedBroker
from hanalpha.orchestrator import TradingSystem
from hanalpha.portfolio import Ledger


@pytest.mark.asyncio
async def test_paper_auto_submit_can_be_disabled(tmp_path, risk_config) -> None:
    gated_execution = risk_config.execution.model_copy(update={"auto_submit_paper": False})
    gated = risk_config.model_copy(update={"execution": gated_execution})
    ledger = Ledger(tmp_path / "gated.sqlite3")
    system = TradingSystem(
        config=gated,
        provider=SyntheticMarketDataProvider(gated.bar_interval_minutes),
        broker=SimulatedBroker(gated.starting_cash, gated.execution),
        ledger=ledger,
        committee=AgentCommittee([EvidenceAgent(), MarketAlignmentAgent(), SkepticAgent()]),
    )
    # Run enough deterministic cycles to reach at least one risk-approved candidate.
    for _ in range(20):
        result = await system.run_cycle()
        if system.pending_orders:
            break
    assert system.pending_orders
    snapshot = await system.broker.get_account_snapshot()
    assert not snapshot.positions
    assert any(
        event["status"] == "PROPOSED"
        for row in result["orders"]
        for event in row["events"]
    )
    ledger.close()
