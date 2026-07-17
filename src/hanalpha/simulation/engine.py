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
    expires_at: datetime | None = None
    input_hash: str = Field(pattern=HASH_PATTERN)
    signal_hash: str = Field(pattern=HASH_PATTERN)


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
            actions: list[SimulationCorporateAction] = []
            for instrument_id in sorted(set(instrument_ids)):
                for bar_record in self.repository.price_bars(instrument_id, context):
                    key = (
                        bar_record.instrument_id,
                        bar_record.source,
                        bar_record.source_record_id,
                    )
                    if bar_record.source_revision > seen_bars.get(key, 0):
                        bars.append(SimulationBar.from_record(bar_record))
                        seen_bars[key] = bar_record.source_revision
                for action_record in self.repository.corporate_actions(instrument_id, context):
                    key = (
                        action_record.instrument_id,
                        action_record.source,
                        action_record.source_record_id,
                    )
                    if action_record.source_revision > seen_actions.get(key, 0):
                        actions.append(SimulationCorporateAction.from_record(action_record))
                        seen_actions[key] = action_record.source_revision
            bars.sort(key=lambda item: (item.available_at, item.event_time, item.source_record_id))
            actions.sort(key=lambda item: (item.available_at, item.event_time, item.action_id))
            frames.append(
                ReplayFrame(
                    snapshot_id=self.snapshot_id,
                    as_of=decision_time,
                    bars=bars,
                    actions=actions,
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
                for order_id in sorted(orders):
                    order = orders[order_id]
                    fill = self.exchange.match(order, bar, as_of=frame.as_of)
                    if fill is None:
                        continue
                    ledger.apply_fill(fill)
                    updated = order.apply_fill(
                        fill_id=fill.fill_id,
                        quantity=fill.quantity,
                        price=fill.price,
                        at=fill.occurred_at,
                    )
                    orders[order_id] = updated
                    fills.append(fill)
                    if updated.remaining_quantity == 0:
                        ledger.release(order_id)
                ledger.mark(bar.instrument_id, Decimal(str(bar.close)))
            ledger.assert_conservation()
            portfolio = ledger.snapshot(frame.as_of)
            for index, proposal in enumerate(policy.propose(frame, portfolio)):
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
                    {"decision_id": identity.decision_id, "proposal_index": index}
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
