from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from hanalpha.domain.enums import Side
from hanalpha.pit.context import AsOfContext
from hanalpha.pit.models import HASH_PATTERN, CorporateActionType, require_aware
from hanalpha.pit.repository import AsOfRepository
from hanalpha.simulation.events import (
    CorporateActionPhase,
    DecisionIdentity,
    DecisionRecord,
    EquityPoint,
    FillEvent,
    ReplayFrame,
    SimulationBar,
    SimulationCorporateAction,
    canonical_hash,
)
from hanalpha.simulation.fills import HistoricalExchange
from hanalpha.simulation.orders import (
    OrderIntent,
    OrderKind,
    SimulationOrderState,
    TrackedOrder,
)
from hanalpha.simulation.portfolio import (
    PortfolioLedger,
    PortfolioPolicy,
    PortfolioSnapshot,
    ReservationRejected,
)


class OrderProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument_id: str
    strategy_id: str
    strategy_version: str
    side: Side
    kind: OrderKind
    quantity: int = Field(gt=0)
    planned_price: float = Field(gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    protective_stop: float | None = Field(default=None, gt=0)
    protective_target: float | None = Field(default=None, gt=0)
    expires_at: datetime | None = None
    input_hash: str = Field(pattern=HASH_PATTERN)
    signal_hash: str = Field(pattern=HASH_PATTERN)

    @property
    def candidate_id(self) -> str:
        return canonical_hash(self)


class CandidatePolicy(Protocol):
    name: str
    version: str

    def propose(self, frame: ReplayFrame, portfolio: PortfolioSnapshot) -> list[OrderProposal]: ...


class ReplayResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_hash: str = Field(pattern=HASH_PATTERN)
    equity_hash: str = Field(pattern=HASH_PATTERN)
    decisions: list[DecisionRecord]
    fills: list[FillEvent]
    equity_points: list[EquityPoint]
    final_orders: list[TrackedOrder]


class PITEventCursor:
    def __init__(self, repository: AsOfRepository, snapshot_id: str) -> None:
        self.repository = repository
        self.snapshot_id = snapshot_id

    def frames(
        self, instrument_ids: list[str], decision_times: list[datetime]
    ) -> list[ReplayFrame]:
        if decision_times != sorted(decision_times):
            raise ValueError("decision times must be monotonic")
        seen_bars: dict[tuple[str, str, str], int] = {}
        seen_actions: dict[tuple[str, str, str], int] = {}
        frames: list[ReplayFrame] = []
        for decision_time in decision_times:
            require_aware(decision_time, "decision_time")
            context = AsOfContext(snapshot_id=self.snapshot_id, as_of=decision_time)
            bars: list[SimulationBar] = []
            bar_revisions: list[SimulationBar] = []
            actions: list[SimulationCorporateAction] = []
            action_revisions: list[SimulationCorporateAction] = []
            for instrument_id in sorted(set(instrument_ids)):
                for bar_record in self.repository.price_bars(instrument_id, context):
                    key = (
                        bar_record.instrument_id,
                        bar_record.source,
                        bar_record.source_record_id,
                    )
                    if bar_record.source_revision > seen_bars.get(key, 0):
                        bar_event = SimulationBar.from_record(bar_record)
                        if bar_record.source_revision == 1:
                            bars.append(bar_event)
                        else:
                            bar_revisions.append(bar_event)
                        seen_bars[key] = bar_record.source_revision
                for action_record in self.repository.corporate_actions(instrument_id, context):
                    key = (
                        action_record.instrument_id,
                        action_record.source,
                        action_record.source_record_id,
                    )
                    if action_record.source_revision > seen_actions.get(key, 0):
                        action_event = SimulationCorporateAction.from_record(action_record)
                        if action_record.source_revision == 1:
                            actions.append(action_event)
                        else:
                            action_revisions.append(action_event)
                        seen_actions[key] = action_record.source_revision
            bars.sort(key=lambda item: (item.available_at, item.event_time, item.source_record_id))
            bar_revisions.sort(
                key=lambda item: (item.available_at, item.event_time, item.source_record_id)
            )
            actions.sort(key=lambda item: (item.available_at, item.event_time, item.action_id))
            action_revisions.sort(
                key=lambda item: (item.available_at, item.event_time, item.action_id)
            )
            frames.append(
                ReplayFrame(
                    snapshot_id=self.snapshot_id,
                    as_of=decision_time,
                    bars=bars,
                    bar_revisions=bar_revisions,
                    actions=actions,
                    action_revisions=action_revisions,
                )
            )
        return frames


class PortfolioReplayEngine:
    def __init__(
        self,
        *,
        starting_cash: Decimal,
        portfolio_policy: PortfolioPolicy,
        exchange: HistoricalExchange,
        config_hash: str,
    ) -> None:
        self.starting_cash = starting_cash
        self.portfolio_policy = portfolio_policy
        self.exchange = exchange
        self.config_hash = config_hash

    def run(self, frames: list[ReplayFrame], policy: CandidatePolicy) -> ReplayResult:
        if not frames:
            raise ValueError("replay requires at least one frame")
        times = [frame.as_of for frame in frames]
        if times != sorted(times):
            raise ValueError("replay frames must be monotonic")
        snapshot_ids = {frame.snapshot_id for frame in frames}
        if len(snapshot_ids) != 1:
            raise ValueError("replay frames must use one snapshot")
        snapshot_id = next(iter(snapshot_ids))
        ledger = PortfolioLedger(self.starting_cash, self.portfolio_policy)
        orders: dict[str, TrackedOrder] = {}
        fills: list[FillEvent] = []
        decisions: list[DecisionRecord] = []
        equity_points: list[EquityPoint] = []

        for frame in frames:
            for order_id in sorted(orders):
                order = orders[order_id]
                expires_at = order.intent.expires_at
                if (
                    expires_at is not None
                    and frame.as_of > expires_at
                    and order.state
                    in {
                        SimulationOrderState.ACCEPTED,
                        SimulationOrderState.PARTIALLY_FILLED,
                    }
                ):
                    orders[order_id] = order.expire(expires_at)
                    ledger.release(order_id)
            for action in frame.actions:
                if action.phase in {
                    CorporateActionPhase.ANNOUNCED,
                    CorporateActionPhase.EX_DATE,
                    CorporateActionPhase.RECORD_DATE,
                }:
                    continue
                self._cancel_orders_for_action(orders, ledger, action.instrument_id, frame.as_of)
                if action.action_type == CorporateActionType.SPLIT and action.ratio is not None:
                    ledger.apply_split(
                        action_id=action.action_id,
                        instrument_id=action.instrument_id,
                        ratio=action.ratio,
                        at=frame.as_of,
                    )
                elif (
                    action.action_type == CorporateActionType.DIVIDEND
                    and action.cash_amount is not None
                ):
                    ledger.apply_dividend(
                        action_id=action.action_id,
                        instrument_id=action.instrument_id,
                        cash_per_share=action.cash_amount,
                        at=frame.as_of,
                    )
                elif action.action_type == CorporateActionType.DELIST:
                    ledger.apply_delisting(
                        action_id=action.action_id,
                        instrument_id=action.instrument_id,
                        cash_per_share=action.cash_amount or Decimal("0"),
                        at=frame.as_of,
                    )
            for bar in frame.bars:
                for order_id in sorted(orders, key=lambda key: self._match_priority(orders[key])):
                    order = orders[order_id]
                    fill = self.exchange.match(order, bar, as_of=frame.as_of)
                    if fill is None:
                        continue
                    if order.intent.oco_group_id is not None:
                        self._cancel_oco_siblings(orders, ledger, order, fill.occurred_at)
                    ledger.apply_fill(fill)
                    updated = order.apply_fill(
                        fill_id=fill.fill_id,
                        quantity=fill.quantity,
                        price=fill.price,
                        at=fill.occurred_at,
                    )
                    orders[order_id] = updated
                    fills.append(fill)
                    if fill.side == Side.BUY:
                        self._create_protection(orders, ledger, updated, fill)
                    elif updated.state == SimulationOrderState.PARTIALLY_FILLED:
                        self._replace_oco_sibling(orders, ledger, updated, fill)
                    if updated.remaining_quantity == 0:
                        ledger.release(order_id)
                ledger.mark(bar.instrument_id, Decimal(str(bar.close)))
            ledger.assert_conservation()
            portfolio = ledger.snapshot(frame.as_of)
            proposals = sorted(policy.propose(frame, portfolio), key=lambda item: item.candidate_id)
            candidate_ids = [proposal.candidate_id for proposal in proposals]
            if len(candidate_ids) != len(set(candidate_ids)):
                raise ValueError("candidate policy returned duplicate proposals")
            for proposal in proposals:
                risk_hash = canonical_hash(
                    {
                        "proposal": proposal.model_dump(mode="json"),
                        "net_liquidation": str(portfolio.net_liquidation),
                        "portfolio_policy": self.portfolio_policy.model_dump(mode="json"),
                    }
                )
                identity = DecisionIdentity.build(
                    snapshot_id=snapshot_id,
                    as_of=frame.as_of,
                    strategy_version=proposal.strategy_version,
                    config_hash=self.config_hash,
                    input_hash=proposal.input_hash,
                    signal_hash=proposal.signal_hash,
                    risk_hash=risk_hash,
                )
                order_id = canonical_hash(
                    {"decision_id": identity.decision_id, "candidate_id": proposal.candidate_id}
                )
                intent = OrderIntent(
                    order_id=order_id,
                    decision_id=identity.decision_id,
                    instrument_id=proposal.instrument_id,
                    strategy_id=proposal.strategy_id,
                    side=proposal.side,
                    kind=proposal.kind,
                    quantity=proposal.quantity,
                    submitted_at=frame.as_of,
                    earliest_fill_at=frame.as_of + timedelta(microseconds=1),
                    planned_price=proposal.planned_price,
                    limit_price=proposal.limit_price,
                    stop_price=proposal.stop_price,
                    protective_stop=proposal.protective_stop,
                    protective_target=proposal.protective_target,
                    expires_at=proposal.expires_at,
                )
                try:
                    ledger.reserve(intent)
                except ReservationRejected as exc:
                    decisions.append(
                        DecisionRecord(
                            identity=identity,
                            strategy_id=proposal.strategy_id,
                            instrument_id=proposal.instrument_id,
                            order_id=None,
                            approved=False,
                            reason=str(exc),
                        )
                    )
                    continue
                orders[order_id] = TrackedOrder.proposed(intent).accept(frame.as_of)
                decisions.append(
                    DecisionRecord(
                        identity=identity,
                        strategy_id=proposal.strategy_id,
                        instrument_id=proposal.instrument_id,
                        order_id=order_id,
                        approved=True,
                        reason="approved",
                    )
                )
            point = ledger.snapshot(frame.as_of)
            equity_points.append(
                EquityPoint(
                    as_of=frame.as_of,
                    net_liquidation=point.net_liquidation,
                    cash=point.cash,
                    gross_exposure=point.gross_exposure,
                )
            )

        final_orders = [orders[key] for key in sorted(orders)]
        return ReplayResult(
            event_hash=canonical_hash(
                {
                    "decisions": [item.model_dump(mode="json") for item in decisions],
                    "fills": [item.model_dump(mode="json") for item in fills],
                    "orders": [item.model_dump(mode="json") for item in final_orders],
                }
            ),
            equity_hash=canonical_hash([item.model_dump(mode="json") for item in equity_points]),
            decisions=decisions,
            fills=fills,
            equity_points=equity_points,
            final_orders=final_orders,
        )

    @staticmethod
    def _cancel_orders_for_action(
        orders: dict[str, TrackedOrder],
        ledger: PortfolioLedger,
        instrument_id: str,
        at: datetime,
    ) -> None:
        for order_id in sorted(orders):
            order = orders[order_id]
            if order.intent.instrument_id == instrument_id and order.state in {
                SimulationOrderState.ACCEPTED,
                SimulationOrderState.PARTIALLY_FILLED,
            }:
                orders[order_id] = order.cancel(at)
                ledger.release(order_id)

    @staticmethod
    def _match_priority(order: TrackedOrder) -> tuple[int, str]:
        if order.intent.reduce_only and order.intent.kind == OrderKind.STOP_MARKET:
            return (0, order.intent.order_id)
        if order.intent.reduce_only:
            return (1, order.intent.order_id)
        return (2, order.intent.order_id)

    @staticmethod
    def _cancel_oco_siblings(
        orders: dict[str, TrackedOrder],
        ledger: PortfolioLedger,
        matched: TrackedOrder,
        at: datetime,
    ) -> None:
        group_id = matched.intent.oco_group_id
        if group_id is None:
            return
        for order_id in sorted(orders):
            sibling = orders[order_id]
            if (
                order_id != matched.intent.order_id
                and sibling.intent.oco_group_id == group_id
                and sibling.state
                in {SimulationOrderState.ACCEPTED, SimulationOrderState.PARTIALLY_FILLED}
            ):
                orders[order_id] = sibling.cancel(at)
                ledger.release(order_id)

    @staticmethod
    def _create_protection(
        orders: dict[str, TrackedOrder],
        ledger: PortfolioLedger,
        parent: TrackedOrder,
        fill: FillEvent,
    ) -> None:
        stop = parent.intent.protective_stop
        if stop is None:
            raise ReservationRejected("filled long entry has no protective stop")
        group_id = canonical_hash({"entry_fill": fill.fill_id, "role": "protection"})
        children = [
            OrderIntent(
                order_id=canonical_hash({"group_id": group_id, "role": "stop"}),
                decision_id=parent.intent.decision_id,
                instrument_id=parent.intent.instrument_id,
                strategy_id=parent.intent.strategy_id,
                side=Side.SELL,
                kind=OrderKind.STOP_MARKET,
                quantity=fill.quantity,
                submitted_at=fill.occurred_at,
                earliest_fill_at=fill.occurred_at + timedelta(microseconds=1),
                planned_price=stop,
                stop_price=stop,
                parent_order_id=parent.intent.order_id,
                oco_group_id=group_id,
                reduce_only=True,
            )
        ]
        if parent.intent.protective_target is not None:
            target = parent.intent.protective_target
            children.append(
                OrderIntent(
                    order_id=canonical_hash({"group_id": group_id, "role": "target"}),
                    decision_id=parent.intent.decision_id,
                    instrument_id=parent.intent.instrument_id,
                    strategy_id=parent.intent.strategy_id,
                    side=Side.SELL,
                    kind=OrderKind.LIMIT,
                    quantity=fill.quantity,
                    submitted_at=fill.occurred_at,
                    earliest_fill_at=fill.occurred_at + timedelta(microseconds=1),
                    planned_price=target,
                    limit_price=target,
                    parent_order_id=parent.intent.order_id,
                    oco_group_id=group_id,
                    reduce_only=True,
                )
            )
        for intent in children:
            ledger.reserve(intent)
            orders[intent.order_id] = TrackedOrder.proposed(intent).accept(fill.occurred_at)

    @staticmethod
    def _replace_oco_sibling(
        orders: dict[str, TrackedOrder],
        ledger: PortfolioLedger,
        matched: TrackedOrder,
        fill: FillEvent,
    ) -> None:
        group_id = matched.intent.oco_group_id
        if group_id is None or matched.remaining_quantity == 0:
            return
        if matched.intent.kind == OrderKind.STOP_MARKET:
            parent_target = next(
                (
                    item.intent.limit_price
                    for item in orders.values()
                    if item.intent.oco_group_id == group_id and item.intent.kind == OrderKind.LIMIT
                ),
                None,
            )
            if parent_target is None:
                return
            kind = OrderKind.LIMIT
            planned = parent_target
            limit_price = parent_target
            stop_price = None
            role = "target-replacement"
        else:
            parent_stop = next(
                (
                    item.intent.stop_price
                    for item in orders.values()
                    if item.intent.oco_group_id == group_id
                    and item.intent.kind == OrderKind.STOP_MARKET
                ),
                None,
            )
            if parent_stop is None:
                return
            kind = OrderKind.STOP_MARKET
            planned = parent_stop
            limit_price = None
            stop_price = parent_stop
            role = "stop-replacement"
        intent = OrderIntent(
            order_id=canonical_hash({"fill_id": fill.fill_id, "role": role}),
            decision_id=matched.intent.decision_id,
            instrument_id=matched.intent.instrument_id,
            strategy_id=matched.intent.strategy_id,
            side=Side.SELL,
            kind=kind,
            quantity=matched.remaining_quantity,
            submitted_at=fill.occurred_at,
            earliest_fill_at=fill.occurred_at + timedelta(microseconds=1),
            planned_price=planned,
            limit_price=limit_price,
            stop_price=stop_price,
            parent_order_id=matched.intent.parent_order_id,
            oco_group_id=group_id,
            reduce_only=True,
        )
        ledger.reserve(intent)
        orders[intent.order_id] = TrackedOrder.proposed(intent).accept(fill.occurred_at)
