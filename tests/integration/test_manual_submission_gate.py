from __future__ import annotations

import pytest

from hanalpha.config import SecretSettings
from hanalpha.data.synthetic import SyntheticMarketDataProvider
from hanalpha.domain.clock import FixedDecisionClock
from hanalpha.domain.enums import OperatingMode
from hanalpha.evidence.extractors import DeterministicEvidenceExtractor
from hanalpha.evidence.service import EvidenceService
from hanalpha.evidence.store import EvidenceStore
from hanalpha.execution import DurableExecutionStore, SimulatedBroker
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
    execution_store = DurableExecutionStore(tmp_path / "execution.sqlite3")
    execution_store.unfreeze_after_reconciliation(at=now)
    system = TradingSystem(
        config=gated,
        provider=SyntheticMarketDataProvider(gated.bar_interval_minutes),
        broker=SimulatedBroker(gated.starting_cash, gated.execution),
        ledger=ledger,
        evidence_service=EvidenceService(
            EvidenceStore(tmp_path / "evidence.sqlite3"), DeterministicEvidenceExtractor()
        ),
        execution_store=execution_store,
        runtime_access=runtime_access,
        clock=FixedDecisionClock(now),
    )
    # Run enough deterministic cycles to reach at least one risk-approved candidate.
    for _ in range(20):
        result = await system.run_cycle()
        if execution_store.pending_approval_count():
            break
    assert execution_store.pending_approval_count() > 0
    snapshot = await system.broker.get_account_snapshot()
    assert not snapshot.positions
    assert any(event["status"] == "PROPOSED" for row in result["orders"] for event in row["events"])
    system.close()
    ledger.close()
