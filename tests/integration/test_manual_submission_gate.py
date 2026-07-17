from __future__ import annotations

import pytest

from hanalpha.agents import AgentCommittee, EvidenceAgent, MarketAlignmentAgent, SkepticAgent
from hanalpha.config import SecretSettings
from hanalpha.data.synthetic import SyntheticMarketDataProvider
from hanalpha.domain.clock import FixedDecisionClock
from hanalpha.domain.enums import OperatingMode
from hanalpha.execution import SimulatedBroker
from hanalpha.orchestrator import TradingSystem
from hanalpha.portfolio import Ledger
from hanalpha.runtime.capabilities import build_runtime_access


@pytest.mark.asyncio
async def test_paper_manual_never_auto_submits(tmp_path, risk_config, now) -> None:
    gated_execution = risk_config.execution.model_copy(
        update={"auto_submit_paper": False, "broker_write_enabled": False}
    )
    gated = risk_config.model_copy(
        update={"operating_mode": OperatingMode.PAPER_MANUAL, "execution": gated_execution}
    )
    runtime_access = build_runtime_access(gated, SecretSettings(_env_file=None))
    ledger = Ledger(tmp_path / "gated.sqlite3")
    system = TradingSystem(
        config=gated,
        provider=SyntheticMarketDataProvider(gated.bar_interval_minutes),
        broker=SimulatedBroker(gated.starting_cash, gated.execution),
        ledger=ledger,
        committee=AgentCommittee([EvidenceAgent(), MarketAlignmentAgent(), SkepticAgent()]),
        runtime_access=runtime_access,
        clock=FixedDecisionClock(now),
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
