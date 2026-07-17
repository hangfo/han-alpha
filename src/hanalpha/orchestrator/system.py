from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from hanalpha.agents import (
    AgentCommittee,
    EvidenceAgent,
    LLMResearchAgent,
    MarketAlignmentAgent,
    SkepticAgent,
)
from hanalpha.config import AppConfig, SecretSettings
from hanalpha.data.base import MarketDataProvider
from hanalpha.data.polygon import PolygonMarketDataProvider
from hanalpha.data.synthetic import SyntheticMarketDataProvider
from hanalpha.domain.enums import OrderStatus
from hanalpha.domain.models import Evidence, OrderEvent, OrderRequest, Signal, utc_now
from hanalpha.execution.base import Broker
from hanalpha.execution.ibkr import IBKRBroker
from hanalpha.execution.simulated import SimulatedBroker
from hanalpha.features.technical import average_dollar_volume
from hanalpha.portfolio.ledger import Ledger
from hanalpha.regime.engine import RegimeEngine
from hanalpha.risk.engine import KillSwitch, RiskEngine
from hanalpha.strategies import BreakoutStrategy, EventContinuationStrategy, TrendPullbackStrategy


class TradingSystem:
    def __init__(
        self,
        *,
        config: AppConfig,
        provider: MarketDataProvider,
        broker: Broker,
        ledger: Ledger,
        committee: AgentCommittee,
    ) -> None:
        self.config = config
        self.provider = provider
        self.broker = broker
        self.ledger = ledger
        self.committee = committee
        self.kill_switch = KillSwitch()
        self.risk = RiskEngine(config.risk, self.kill_switch)
        self.regime_engine = RegimeEngine()
        self.strategies = self._build_strategies()
        self.last_regime: dict[str, Any] | None = None
        self.last_signals: list[dict[str, Any]] = []
        self.last_orders: list[dict[str, Any]] = []
        self.pending_orders: dict[str, tuple[OrderRequest, Any]] = {}
        self.cycle_count = 0

    def _build_strategies(self) -> list[Any]:
        strategies: list[Any] = []
        if "breakout" in self.config.strategies:
            strategies.append(BreakoutStrategy(self.config.strategies["breakout"]))
        if "trend_pullback" in self.config.strategies:
            strategies.append(TrendPullbackStrategy(self.config.strategies["trend_pullback"]))
        if "event_continuation" in self.config.strategies:
            strategies.append(EventContinuationStrategy(self.config.strategies["event_continuation"]))
        return strategies

    @staticmethod
    def _evidence_from_catalyst(catalyst: Any) -> list[Evidence]:
        evidence: list[Evidence] = []
        for evidence_id in catalyst.evidence_ids:
            digest = hashlib.sha256(catalyst.headline.encode()).hexdigest()
            evidence.append(
                Evidence(
                    evidence_id=evidence_id,
                    source="synthetic" if evidence_id.startswith("synthetic:") else "external",
                    title=catalyst.headline,
                    observed_at=max(catalyst.published_at, catalyst.available_at),
                    available_at=catalyst.available_at,
                    payload_hash=digest,
                    summary=f"{catalyst.category}; score={catalyst.score:.2f}",
                    metadata={"symbol": catalyst.symbol, "category": catalyst.category},
                )
            )
        return evidence

    async def _process_existing_positions(self) -> list[OrderEvent]:
        snapshot = await self.broker.get_account_snapshot()
        events: list[OrderEvent] = []
        for position in snapshot.positions:
            quote = await self.provider.get_quote(position.symbol)
            events.extend(await self.broker.process_quote(quote))
        for event in events:
            self.ledger.record_order_event(event)
        return events

    async def run_cycle(self, now: datetime | None = None) -> dict[str, Any]:
        cycle_now = now or utc_now()
        if cycle_now.tzinfo is None:
            cycle_now = cycle_now.replace(tzinfo=UTC)
        self.cycle_count += 1
        advance = getattr(self.provider, "advance", None)
        if callable(advance):
            advance()
        if not await self.provider.is_healthy():
            self.kill_switch.freeze("market_data_unhealthy")
            return {"cycle": self.cycle_count, "status": "frozen", "reason": self.kill_switch.reason}
        protection_events = await self._process_existing_positions()
        market_symbol = self.config.benchmarks["market"]
        growth_symbol = self.config.benchmarks["growth"]
        market_bars = await self.provider.get_bars(market_symbol, self.config.lookback_bars)
        growth_bars = await self.provider.get_bars(growth_symbol, self.config.lookback_bars)
        regime = self.regime_engine.evaluate(
            market_bars=market_bars,
            growth_bars=growth_bars,
            now=cycle_now,
        )
        self.last_regime = regime.model_dump(mode="json")
        account = await self.broker.get_account_snapshot()
        signals: list[dict[str, Any]] = []
        orders: list[dict[str, Any]] = []
        for symbol in self.config.universe:
            bars = await self.provider.get_bars(symbol, self.config.lookback_bars)
            quote = await self.provider.get_quote(symbol)
            catalysts = await self.provider.get_catalysts(
                symbol, cycle_now - timedelta(hours=self.config.agents.max_news_age_hours)
            )
            evidence = [item for catalyst in catalysts for item in self._evidence_from_catalyst(catalyst)]
            for strategy in self.strategies:
                signal: Signal | None = strategy.generate(
                    symbol=symbol,
                    bars=bars,
                    benchmark_bars=market_bars,
                    catalysts=catalysts,
                    now=cycle_now,
                )
                if signal is None:
                    continue
                self.ledger.record_signal(signal)
                approved_by_agents, assessments = await self.committee.review(signal, evidence, regime)
                signal_row = {
                    **signal.model_dump(mode="json"),
                    "agent_approved": approved_by_agents,
                    "assessments": [item.model_dump(mode="json") for item in assessments],
                }
                signals.append(signal_row)
                if not approved_by_agents:
                    continue
                idempotency_key = f"{self.config.environment}:{signal.signal_id}"
                plan = self.risk.create_plan(
                    signal=signal,
                    account=account,
                    regime=regime,
                    quote=quote,
                    idempotency_key=idempotency_key,
                    now=cycle_now,
                )
                if plan is None:
                    continue
                decision = self.risk.evaluate(
                    plan=plan,
                    account=account,
                    quote=quote,
                    regime=regime,
                    existing_idempotency_keys=self.ledger.idempotency_keys(),
                    average_dollar_volume=average_dollar_volume(bars, 20),
                    sector=str(signal.metadata.get("sector", "UNKNOWN")),
                    earnings_soon=bool(signal.metadata.get("earnings_soon", False)),
                    now=cycle_now,
                )
                self.ledger.record_plan(plan)
                order_row: dict[str, Any] = {
                    "plan": plan.model_dump(mode="json"),
                    "risk": decision.model_dump(mode="json"),
                    "events": [],
                }
                if decision.approved:
                    order = OrderRequest(
                        order_id=f"order:{plan.plan_id}",
                        plan_id=plan.plan_id,
                        symbol=plan.symbol,
                        side=plan.side,
                        quantity=decision.approved_quantity,
                        limit_price=plan.entry_price,
                        stop_price=plan.stop_price,
                        target_price=plan.target_price,
                        idempotency_key=plan.idempotency_key,
                        status=OrderStatus.RISK_APPROVED,
                    )
                    self.ledger.record_order(order)
                    should_auto_submit = (
                        self.config.environment == "paper"
                        and self.config.execution.auto_submit_paper
                    )
                    if should_auto_submit:
                        events = await self.broker.submit(order, quote)
                        account = await self.broker.get_account_snapshot()
                    else:
                        self.pending_orders[order.order_id] = (order, quote)
                        events = [
                            OrderEvent(
                                order_id=order.order_id,
                                status=OrderStatus.PROPOSED,
                                remaining_quantity=order.quantity,
                                message="awaiting_explicit_local_operator_approval",
                            )
                        ]
                    for event in events:
                        self.ledger.record_order_event(event)
                    order_row["events"] = [event.model_dump(mode="json") for event in events]
                orders.append(order_row)
        self.last_signals = signals[-100:]
        self.last_orders = orders[-100:]
        return {
            "cycle": self.cycle_count,
            "timestamp": cycle_now.isoformat(),
            "regime": self.last_regime,
            "signals": signals,
            "orders": orders,
            "protection_events": [event.model_dump(mode="json") for event in protection_events],
            "account": (await self.broker.get_account_snapshot()).model_dump(mode="json"),
            "kill_switch": {"frozen": self.kill_switch.frozen, "reason": self.kill_switch.reason},
        }

    async def status(self) -> dict[str, Any]:
        return {
            "environment": self.config.environment,
            "mode": self.config.mode,
            "cycle_count": self.cycle_count,
            "broker_connected": await self.broker.is_connected(),
            "market_data_healthy": await self.provider.is_healthy(),
            "kill_switch": {"frozen": self.kill_switch.frozen, "reason": self.kill_switch.reason},
            "regime": self.last_regime,
            "pending_orders": len(self.pending_orders),
            "account": (await self.broker.get_account_snapshot()).model_dump(mode="json"),
        }


async def build_system(config: AppConfig, secrets: SecretSettings, ledger: Ledger) -> TradingSystem:
    if config.mode == "synthetic":
        provider: MarketDataProvider = SyntheticMarketDataProvider(config.bar_interval_minutes)
    else:
        if not secrets.polygon_api_key:
            raise RuntimeError("External mode requires POLYGON_API_KEY")
        provider = PolygonMarketDataProvider(
            api_key=secrets.polygon_api_key,
            interval_minutes=config.bar_interval_minutes,
        )
    if config.execution.broker == "simulated":
        broker: Broker = SimulatedBroker(config.starting_cash, config.execution)
    else:
        ibkr = IBKRBroker(
            host=secrets.ibkr_host,
            port=secrets.ibkr_port,
            client_id=secrets.ibkr_client_id,
            account=secrets.ibkr_account,
        )
        await ibkr.connect()
        broker = ibkr
    agents: list[Any] = [EvidenceAgent(), MarketAlignmentAgent(), SkepticAgent()]
    if config.agents.provider == "llm":
        if not (secrets.llm_api_key and secrets.llm_model):
            raise RuntimeError("LLM provider selected but LLM_API_KEY or LLM_MODEL is missing")
        agents.append(
            LLMResearchAgent(
                api_key=secrets.llm_api_key,
                base_url=secrets.llm_base_url,
                model=secrets.llm_model,
            )
        )
    committee = AgentCommittee(agents)
    return TradingSystem(
        config=config,
        provider=provider,
        broker=broker,
        ledger=ledger,
        committee=committee,
    )
