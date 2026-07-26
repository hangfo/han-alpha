from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from hanalpha.config import AppConfig, SecretSettings
from hanalpha.data.base import MarketDataProvider
from hanalpha.data.polygon import PolygonMarketDataProvider
from hanalpha.data.synthetic import SyntheticMarketDataProvider
from hanalpha.domain.clock import DecisionClock, SystemDecisionClock, ensure_aware_utc
from hanalpha.domain.enums import OrderStatus
from hanalpha.domain.models import OrderEvent, OrderRequest, Quote, Signal
from hanalpha.evidence.decision import EvidenceReview, validate_review
from hanalpha.evidence.extractors import (
    DeterministicEvidenceExtractor,
    EvidenceExtractor,
    OpenAIResponsesEvidenceExtractor,
)
from hanalpha.evidence.models import ClaimType, EvidenceDecision, EvidenceDocument, EvidenceSnapshot
from hanalpha.evidence.service import EvidenceService
from hanalpha.evidence.store import EvidenceStore
from hanalpha.execution.base import Broker
from hanalpha.execution.control_models import (
    BrokerSnapshot,
    DecisionCapsule,
    ExecutionIntent,
    RiskReservation,
)
from hanalpha.execution.control_store import DurableExecutionStore
from hanalpha.execution.ibkr import IBKRBroker
from hanalpha.execution.reconciliation import Reconciler
from hanalpha.execution.simulated import SimulatedBroker
from hanalpha.features.technical import average_dollar_volume
from hanalpha.portfolio.ledger import Ledger
from hanalpha.regime.engine import RegimeEngine
from hanalpha.risk.engine import KillSwitch, RiskEngine
from hanalpha.runtime.capabilities import RuntimeAccess, build_runtime_access
from hanalpha.simulation.events import canonical_hash
from hanalpha.strategies import BreakoutStrategy, EventContinuationStrategy, TrendPullbackStrategy


class TradingSystem:
    def __init__(
        self,
        *,
        config: AppConfig,
        provider: MarketDataProvider,
        broker: Broker,
        ledger: Ledger,
        evidence_service: EvidenceService,
        execution_store: DurableExecutionStore,
        runtime_access: RuntimeAccess,
        clock: DecisionClock,
    ) -> None:
        self.config = config
        self.provider = provider
        self.broker = broker
        self.ledger = ledger
        self.evidence_service = evidence_service
        self.execution_store = execution_store
        self.runtime_access = runtime_access
        self.clock = clock
        self.kill_switch = KillSwitch()
        self.risk = RiskEngine(config.risk, self.kill_switch)
        self.regime_engine = RegimeEngine()
        self.strategies = self._build_strategies()
        self.last_regime: dict[str, Any] | None = None
        self.last_signals: list[dict[str, Any]] = []
        self.last_orders: list[dict[str, Any]] = []
        self.cycle_count = 0

    def _build_strategies(self) -> list[Any]:
        strategies: list[Any] = []
        if "breakout" in self.config.strategies:
            strategies.append(BreakoutStrategy(self.config.strategies["breakout"]))
        if "trend_pullback" in self.config.strategies:
            strategies.append(TrendPullbackStrategy(self.config.strategies["trend_pullback"]))
        if "event_continuation" in self.config.strategies:
            strategies.append(
                EventContinuationStrategy(self.config.strategies["event_continuation"])
            )
        return strategies

    @staticmethod
    def _document_from_catalyst(catalyst: Any, *, ingested_at: datetime) -> EvidenceDocument:
        return EvidenceDocument.create(
            entity_id=catalyst.symbol,
            source=(
                "synthetic" if catalyst.evidence_ids[0].startswith("synthetic:") else "external"
            ),
            source_uri=catalyst.evidence_ids[0],
            observed_at=catalyst.published_at,
            effective_at=catalyst.published_at,
            available_at=catalyst.available_at,
            ingested_at=ingested_at,
            content=catalyst.headline,
        )

    @staticmethod
    def _review_evidence(
        *, signal: Signal, snapshot: Any, decision_id: str, reviewed_at: datetime
    ) -> EvidenceReview:
        entity_claims = tuple(
            claim for claim in snapshot.claims if claim.entity_id == signal.symbol
        )
        negative = tuple(
            claim
            for claim in entity_claims
            if claim.claim_type
            in {ClaimType.GUIDANCE_CUT, ClaimType.DEMAND_WEAKNESS, ClaimType.ACCOUNTING_RISK}
        )
        if negative:
            evidence_decision = EvidenceDecision.VETO
            selected = negative
            invalidators = tuple(f"claim:{claim.claim_type.value}" for claim in negative)
            rationale = "point-in-time evidence contains a deterministic invalidator"
        elif entity_claims:
            evidence_decision = EvidenceDecision.NO_OBJECTION
            selected = entity_claims
            invalidators = ()
            rationale = "available evidence raises no deterministic objection"
        elif signal.strategy == "event_continuation":
            evidence_decision = EvidenceDecision.VETO
            selected = ()
            invalidators = ("missing_point_in_time_event_evidence",)
            rationale = "event strategy requires point-in-time evidence"
        else:
            evidence_decision = EvidenceDecision.ABSTAIN
            selected = ()
            invalidators = ()
            rationale = "price-derived candidate has no applicable unstructured evidence"
        candidate_id = canonical_hash(signal)
        review = EvidenceReview(
            candidate_id=candidate_id,
            decision_id=decision_id,
            entity_id=signal.symbol,
            evidence_snapshot_id=snapshot.snapshot_id,
            reviewed_at=reviewed_at,
            reviewer_config_hash=canonical_hash(
                {"policy": "deterministic-negative-claim-v1", "event_requires_evidence": True}
            ),
            decision=evidence_decision,
            rationale=rationale,
            claim_ids=tuple(claim.claim_id for claim in selected),
            invalidators=invalidators,
        )
        return validate_review(
            review,
            snapshot,
            candidate_id=candidate_id,
            decision_id=decision_id,
            entity_id=signal.symbol,
        )

    async def _process_existing_positions(self) -> list[OrderEvent]:
        snapshot = await self.broker.get_account_snapshot()
        events: list[OrderEvent] = []
        for position in snapshot.positions:
            quote = await self.provider.get_quote(position.symbol)
            self._record_quote_snapshot(quote, observed_at=self.clock.now())
            events.extend(await self.broker.process_quote(quote))
        for event in events:
            self.ledger.record_order_event(event)
        return events

    async def run_cycle(self, as_of: datetime | None = None) -> dict[str, Any]:
        cycle_now = ensure_aware_utc(as_of or self.clock.now())
        self.cycle_count += 1
        advance = getattr(self.provider, "advance", None)
        if callable(advance):
            advance()
        if not await self.provider.is_healthy():
            self.kill_switch.freeze("market_data_unhealthy")
            return {
                "cycle": self.cycle_count,
                "status": "frozen",
                "reason": self.kill_switch.reason,
            }
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
            self._record_quote_snapshot(quote, observed_at=cycle_now)
            catalysts = await self.provider.get_catalysts(
                symbol, cycle_now - timedelta(hours=self.config.agents.max_news_age_hours)
            )
            for catalyst in catalysts:
                await self.evidence_service.ingest(
                    self._document_from_catalyst(catalyst, ingested_at=cycle_now),
                    as_of=cycle_now,
                )
            global_evidence_snapshot = self.evidence_service.snapshot(as_of=cycle_now)
            entity_claims = tuple(
                claim for claim in global_evidence_snapshot.claims if claim.entity_id == symbol
            )
            entity_claim_ids = {claim.claim_id for claim in entity_claims}
            entity_edges = tuple(
                edge
                for edge in global_evidence_snapshot.contradictions
                if edge.left_claim_id in entity_claim_ids
                and edge.right_claim_id in entity_claim_ids
            )
            evidence_snapshot = EvidenceSnapshot(
                snapshot_id=canonical_hash(
                    {
                        "as_of": cycle_now,
                        "entity_id": symbol,
                        "claims": [claim.claim_id for claim in entity_claims],
                        "edges": [edge.edge_id for edge in entity_edges],
                    }
                ),
                as_of=cycle_now,
                claims=entity_claims,
                contradictions=entity_edges,
            )
            market_snapshot_id = canonical_hash(
                {
                    "as_of": cycle_now,
                    "symbol": symbol,
                    "bars": [bar.model_dump(mode="json") for bar in bars],
                    "quote": quote.model_dump(mode="json"),
                    "regime": regime.model_dump(mode="json"),
                    "catalysts": [item.model_dump(mode="json") for item in catalysts],
                }
            )
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
                candidate_decision_id = canonical_hash(
                    {
                        "candidate_id": canonical_hash(signal),
                        "market_snapshot_id": market_snapshot_id,
                        "account": account.model_dump(mode="json"),
                        "risk_policy_hash": canonical_hash(self.config.risk),
                    }
                )
                evidence_review = self._review_evidence(
                    signal=signal,
                    snapshot=evidence_snapshot,
                    decision_id=candidate_decision_id,
                    reviewed_at=cycle_now,
                )
                signal_row = {
                    **signal.model_dump(mode="json"),
                    "evidence_review": evidence_review.model_dump(mode="json"),
                }
                signals.append(signal_row)
                if evidence_review.decision == EvidenceDecision.VETO:
                    self.execution_store.record_no_trade(
                        candidate_decision_id,
                        reason_code="evidence_veto",
                        source="evidence_service",
                        at=cycle_now,
                        payload={"invalidators": list(evidence_review.invalidators)},
                    )
                    continue
                idempotency_key = f"{self.config.operating_mode.value}:{signal.signal_id}"
                plan = self.risk.create_plan(
                    signal=signal,
                    account=account,
                    regime=regime,
                    quote=quote,
                    idempotency_key=idempotency_key,
                    now=cycle_now,
                )
                if plan is None:
                    self.execution_store.record_no_trade(
                        canonical_hash({"signal_id": signal.signal_id, "as_of": cycle_now}),
                        reason_code="deterministic_sizing_zero",
                        source="risk_engine",
                        at=cycle_now,
                    )
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
                durable_capacity = min(
                    max(
                        0.0,
                        account.buying_power
                        - float(self.execution_store.active_reserved_notional("runtime-paper")),
                    ),
                    max(
                        0.0,
                        account.net_liquidation
                        * min(
                            self.config.risk.max_gross_exposure,
                            regime.max_gross_exposure,
                        )
                        - account.gross_exposure * account.net_liquidation,
                    ),
                )
                if decision.approved and plan.notional > durable_capacity:
                    self.execution_store.record_no_trade(
                        candidate_decision_id,
                        reason_code="durable_capacity_exhausted",
                        source="authoritative_account_read_model",
                        at=cycle_now,
                        payload={
                            "required_notional": plan.notional,
                            "available_notional": durable_capacity,
                        },
                    )
                    order_row["capacity_rejection"] = {
                        "required_notional": plan.notional,
                        "available_notional": durable_capacity,
                    }
                    orders.append(order_row)
                    continue
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
                        created_at=cycle_now,
                    )
                    should_auto_submit = self.runtime_access.capabilities.automatic_submission
                    decision_id = candidate_decision_id
                    capsule = DecisionCapsule(
                        decision_id=decision_id,
                        decision_snapshot_id=canonical_hash(
                            {
                                "decision_id": decision_id,
                                "market_snapshot_id": market_snapshot_id,
                            }
                        ),
                        market_snapshot_id=market_snapshot_id,
                        evidence_snapshot_id=evidence_snapshot.snapshot_id,
                        evidence_review_id=evidence_review.review_id,
                        strategy_id=signal.strategy,
                        strategy_version=str(signal.metadata.get("strategy_version", "runtime")),
                        entity_id=symbol,
                        input_hash=canonical_hash(
                            {
                                "market_snapshot_id": market_snapshot_id,
                                "evidence_review_id": evidence_review.review_id,
                            }
                        ),
                        signal_hash=canonical_hash(signal),
                        risk_policy_hash=canonical_hash(self.config.risk),
                        risk_decision_hash=canonical_hash(decision),
                        config_hash=canonical_hash(self.config),
                        created_at=cycle_now,
                    )
                    reservation = RiskReservation(
                        reservation_id=canonical_hash(
                            {"decision_id": decision_id, "account": "runtime-paper"}
                        ),
                        decision_id=decision_id,
                        account_id="runtime-paper",
                        instrument_id=symbol,
                        cash_reserved=Decimal(str(plan.notional)),
                        notional_reserved=Decimal(str(plan.notional)),
                        risk_reserved=Decimal(str(decision.risk_dollars)),
                        account_notional_capacity=Decimal(str(durable_capacity)),
                        quantity_reserved=decision.approved_quantity,
                        expires_at=cycle_now + timedelta(minutes=5),
                        created_at=cycle_now,
                    )
                    intent = ExecutionIntent.create(
                        capsule=capsule,
                        reservation=reservation,
                        side=plan.side,
                        quantity=decision.approved_quantity,
                        limit_price=Decimal(str(plan.entry_price)),
                        stop_price=Decimal(str(plan.stop_price)),
                        target_price=Decimal(str(plan.target_price)),
                        approval_required=not should_auto_submit,
                    )
                    self.execution_store.stage(capsule, reservation, intent)
                    self.ledger.record_order(order)
                    events = [
                        OrderEvent(
                            order_id=order.order_id,
                            status=OrderStatus.PROPOSED,
                            timestamp=cycle_now,
                            remaining_quantity=order.quantity,
                            message=(
                                "durably_outboxed_awaiting_single_writer"
                                if should_auto_submit
                                else "awaiting_explicit_local_operator_approval"
                            ),
                        )
                    ]
                    for event in events:
                        self.ledger.record_order_event(event)
                    order_row["events"] = [event.model_dump(mode="json") for event in events]
                orders.append(order_row)
                if not decision.approved:
                    self.execution_store.record_no_trade(
                        canonical_hash(
                            {"plan_id": plan.plan_id, "risk": decision.model_dump(mode="json")}
                        ),
                        reason_code="risk_rejected",
                        source="risk_engine",
                        at=cycle_now,
                        payload={"reason_codes": decision.reason_codes},
                    )
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
            "operating_mode": self.config.operating_mode.value,
            "mode": self.config.mode,
            "capabilities": {
                "broker_write": self.runtime_access.capabilities.broker_write,
                "automatic_submission": self.runtime_access.capabilities.automatic_submission,
                "operator_api": self.runtime_access.capabilities.operator_api,
            },
            "cycle_count": self.cycle_count,
            "broker_connected": await self.broker.is_connected(),
            "market_data_healthy": await self.provider.is_healthy(),
            "kill_switch": {"frozen": self.kill_switch.frozen, "reason": self.kill_switch.reason},
            "regime": self.last_regime,
            "pending_orders": self.execution_store.pending_approval_count(),
            "execution_control": {
                "frozen": self.execution_store.is_frozen()[0],
                "freeze_reason": self.execution_store.is_frozen()[1],
                "pending_approvals": self.execution_store.pending_approval_count(),
            },
            "account": (await self.broker.get_account_snapshot()).model_dump(mode="json"),
        }

    def _record_quote_snapshot(self, quote: Quote, *, observed_at: datetime) -> None:
        self.execution_store.record_quote_snapshot(
            symbol=quote.symbol,
            bid=Decimal(str(quote.bid)),
            ask=Decimal(str(quote.ask)),
            last=Decimal(str(quote.last)),
            observed_at=ensure_aware_utc(observed_at),
            provider_timestamp=ensure_aware_utc(quote.timestamp),
            provider=type(self.provider).__name__,
            feed_mode="SYNTHETIC" if self.config.mode == "synthetic" else "EXTERNAL",
            market_phase="UNVERIFIED",
            venue="SMART",
            currency=self.config.base_currency,
            recorded_at=ensure_aware_utc(observed_at),
        )

    async def cancel_all(self) -> list[OrderEvent]:
        events = await self.broker.cancel_all(self.runtime_access.broker_write)
        for event in events:
            self.ledger.record_order_event(event)
        return events

    async def flatten_all(self, quotes: dict[str, Quote]) -> list[OrderEvent]:
        events = await self.broker.flatten_all(quotes, self.runtime_access.broker_write)
        for event in events:
            self.ledger.record_order_event(event)
        return events

    def close(self) -> None:
        self.evidence_service.store.close()
        self.execution_store.close()


async def build_system(config: AppConfig, secrets: SecretSettings, ledger: Ledger) -> TradingSystem:
    runtime_access = build_runtime_access(config, secrets)
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
            base_currency=config.base_currency,
        )
        await ibkr.connect()
        broker = ibkr
    extractor: EvidenceExtractor
    if config.agents.provider == "llm":
        if not (secrets.llm_api_key and secrets.llm_model):
            raise RuntimeError("LLM provider selected but LLM_API_KEY or LLM_MODEL is missing")
        extractor = OpenAIResponsesEvidenceExtractor(
            api_key=secrets.llm_api_key,
            base_url=secrets.llm_base_url,
            model_id=secrets.llm_model,
            model_snapshot=secrets.llm_model,
        )
    else:
        extractor = DeterministicEvidenceExtractor()
    evidence_store = EvidenceStore(ledger.path.with_name(f"{ledger.path.stem}-evidence.sqlite3"))
    evidence_service = EvidenceService(evidence_store, extractor)
    execution_store = DurableExecutionStore(
        ledger.path.with_name(f"{ledger.path.stem}-execution.sqlite3")
    )
    if isinstance(broker, SimulatedBroker):
        # Synthetic mode has a complete, in-process broker truth and must remain secret-free.
        account = await broker.get_account_snapshot()
        Reconciler(execution_store).reconcile(
            BrokerSnapshot(
                as_of=account.timestamp,
                cash=Decimal(str(account.cash)),
                settled_cash=Decimal(str(account.cash)),
                buying_power=Decimal(str(account.buying_power)),
                accrued_cash=Decimal("0"),
                base_currency="USD",
                currency_balances={"USD": Decimal(str(account.cash))},
                complete=True,
                completeness_certificate_id=canonical_hash(
                    {"broker": "simulated", "as_of": account.timestamp}
                ),
                orders=(),
                positions={position.symbol: position.quantity for position in account.positions},
                protections={
                    symbol: protection.quantity for symbol, protection in broker.protections.items()
                },
                events=(),
            ),
            at=account.timestamp,
        )
    return TradingSystem(
        config=config,
        provider=provider,
        broker=broker,
        ledger=ledger,
        evidence_service=evidence_service,
        execution_store=execution_store,
        runtime_access=runtime_access,
        clock=SystemDecisionClock(),
    )
