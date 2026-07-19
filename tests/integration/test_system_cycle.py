from datetime import datetime

import pytest

from hanalpha.data.synthetic import SyntheticMarketDataProvider
from hanalpha.domain.clock import FixedDecisionClock
from hanalpha.evidence.extractors import DeterministicEvidenceExtractor
from hanalpha.evidence.service import EvidenceService
from hanalpha.evidence.store import EvidenceStore
from hanalpha.execution import DurableExecutionStore, SimulatedBroker
from hanalpha.orchestrator import TradingSystem
from hanalpha.portfolio import Ledger


class CountingBroker(SimulatedBroker):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.submit_calls = 0

    async def submit(self, order, quote, capability):
        self.submit_calls += 1
        return await super().submit(order, quote, capability)


@pytest.mark.asyncio
async def test_full_synthetic_cycle(tmp_path, risk_config, runtime_access, now) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    provider = SyntheticMarketDataProvider(risk_config.bar_interval_minutes)
    broker = SimulatedBroker(risk_config.starting_cash, risk_config.execution)
    execution_store = DurableExecutionStore(tmp_path / "execution.sqlite3")
    execution_store.unfreeze_after_reconciliation(at=now)
    system = TradingSystem(
        config=risk_config,
        provider=provider,
        broker=broker,
        ledger=ledger,
        evidence_service=EvidenceService(
            EvidenceStore(tmp_path / "evidence.sqlite3"), DeterministicEvidenceExtractor()
        ),
        execution_store=execution_store,
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
    system.close()
    ledger.close()


@pytest.mark.asyncio
async def test_runtime_freezes_capsule_instead_of_calling_broker_directly(
    tmp_path, risk_config, runtime_access, now
) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    broker = CountingBroker(risk_config.starting_cash, risk_config.execution)
    execution_store = DurableExecutionStore(tmp_path / "execution.sqlite3")
    execution_store.unfreeze_after_reconciliation(at=now)
    system = TradingSystem(
        config=risk_config,
        provider=SyntheticMarketDataProvider(risk_config.bar_interval_minutes),
        broker=broker,
        ledger=ledger,
        evidence_service=EvidenceService(
            EvidenceStore(tmp_path / "evidence.sqlite3"), DeterministicEvidenceExtractor()
        ),
        execution_store=execution_store,
        runtime_access=runtime_access,
        clock=FixedDecisionClock(now),
    )
    try:
        for _ in range(20):
            await system.run_cycle()
            if execution_store.connection.execute(
                "SELECT COUNT(*) FROM outbox_commands"
            ).fetchone()[0]:
                break
        assert (
            execution_store.connection.execute("SELECT COUNT(*) FROM decision_capsules").fetchone()[
                0
            ]
            > 0
        )
        assert broker.submit_calls == 0
    finally:
        system.close()
        ledger.close()
