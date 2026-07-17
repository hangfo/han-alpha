from __future__ import annotations

import math
from datetime import datetime

from hanalpha.config import RiskConfig
from hanalpha.domain.enums import MarketRegime, Side
from hanalpha.domain.models import (
    AccountSnapshot,
    Quote,
    RegimeSnapshot,
    RiskDecision,
    Signal,
    TradePlan,
)


class KillSwitch:
    def __init__(self) -> None:
        self._frozen = False
        self._reason = ""

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def reason(self) -> str:
        return self._reason

    def freeze(self, reason: str) -> None:
        self._frozen = True
        self._reason = reason[:500]

    def unfreeze(self) -> None:
        self._frozen = False
        self._reason = ""


class RiskEngine:
    def __init__(self, config: RiskConfig, kill_switch: KillSwitch | None = None) -> None:
        self.config = config
        self.kill_switch = kill_switch or KillSwitch()

    def size_position(
        self,
        *,
        signal: Signal,
        account: AccountSnapshot,
        regime: RegimeSnapshot,
        quote: Quote,
    ) -> int:
        per_share_risk = abs(signal.reference_price - signal.stop_price)
        if not math.isfinite(per_share_risk) or per_share_risk <= 0:
            return 0
        risk_budget = (
            account.net_liquidation * self.config.risk_per_trade_pct * regime.risk_multiplier
        )
        risk_quantity = math.floor(risk_budget / per_share_risk)
        notional_cap = min(
            account.net_liquidation * self.config.max_symbol_weight,
            self.config.max_order_notional,
            account.buying_power,
        )
        notional_quantity = math.floor(notional_cap / quote.ask)
        return max(0, min(risk_quantity, notional_quantity))

    def create_plan(
        self,
        *,
        signal: Signal,
        account: AccountSnapshot,
        regime: RegimeSnapshot,
        quote: Quote,
        idempotency_key: str,
        now: datetime,
    ) -> TradePlan | None:
        quantity = self.size_position(signal=signal, account=account, regime=regime, quote=quote)
        if quantity <= 0:
            return None
        side = Side.BUY if signal.action.value == "BUY" else Side.SELL
        return TradePlan(
            plan_id=f"plan:{signal.signal_id}",
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            strategy=signal.strategy,
            side=side,
            created_at=now,
            entry_price=quote.ask if side == Side.BUY else quote.bid,
            stop_price=signal.stop_price,
            target_price=signal.target_price,
            quantity=quantity,
            evidence_ids=signal.evidence_ids,
            invalidators=[],
            idempotency_key=idempotency_key,
            metadata={"signal_confidence": signal.confidence},
        )

    def evaluate(
        self,
        *,
        plan: TradePlan,
        account: AccountSnapshot,
        quote: Quote,
        regime: RegimeSnapshot,
        existing_idempotency_keys: set[str],
        average_dollar_volume: float,
        sector: str = "UNKNOWN",
        earnings_soon: bool = False,
        now: datetime,
    ) -> RiskDecision:
        reasons: list[str] = []
        if self.kill_switch.frozen:
            reasons.append("kill_switch_frozen")
        if not account.connected:
            reasons.append("broker_disconnected")
        if quote.age_seconds(now) > self.config.max_quote_age_seconds:
            reasons.append("stale_quote")
        if quote.last < self.config.min_price:
            reasons.append("price_below_minimum")
        if average_dollar_volume < self.config.min_average_dollar_volume:
            reasons.append("insufficient_liquidity")
        if plan.idempotency_key in existing_idempotency_keys:
            reasons.append("duplicate_idempotency_key")
        existing_symbol = any(item.symbol == plan.symbol for item in account.positions)
        if existing_symbol:
            reasons.append("existing_symbol_position")
        if len(account.positions) >= self.config.max_positions and not existing_symbol:
            reasons.append("max_positions_reached")
        if plan.side != Side.BUY:
            reasons.append("v1_long_only")
        if account.daily_pnl <= -account.net_liquidation * self.config.daily_loss_limit_pct:
            reasons.append("daily_loss_limit")
        if account.drawdown_pct >= self.config.max_drawdown_limit_pct:
            reasons.append("drawdown_limit")
        if regime.regime == MarketRegime.UNKNOWN or regime.risk_multiplier <= 0:
            reasons.append("unknown_or_disabled_regime")
        if plan.strategy not in regime.allowed_strategies:
            reasons.append("strategy_not_allowed")
        if plan.notional > self.config.max_order_notional:
            reasons.append("max_order_notional")
        if earnings_soon and not self.config.allow_earnings_overnight:
            reasons.append("earnings_blackout")
        if plan.side == Side.BUY and not plan.stop_price < plan.entry_price < plan.target_price:
            reasons.append("invalid_long_geometry")
        symbol_market_value = sum(
            item.market_value for item in account.positions if item.symbol == plan.symbol
        ) + plan.notional
        if symbol_market_value / account.net_liquidation > self.config.max_symbol_weight + 1e-9:
            reasons.append("max_symbol_weight")
        sector_market_value = sum(
            abs(item.market_value) for item in account.positions if item.sector == sector
        ) + plan.notional
        if sector != "UNKNOWN" and sector_market_value / account.net_liquidation > self.config.max_sector_weight:
            reasons.append("max_sector_weight")
        gross_after = account.gross_exposure + plan.notional / account.net_liquidation
        gross_cap = min(self.config.max_gross_exposure, regime.max_gross_exposure)
        if gross_after > gross_cap + 1e-9:
            reasons.append("max_gross_exposure")
        if not math.isfinite(plan.risk_dollars) or plan.risk_dollars <= 0:
            reasons.append("invalid_risk")
        approved = not reasons
        return RiskDecision(
            approved=approved,
            reason_codes=reasons or ["approved"],
            approved_quantity=plan.quantity if approved else 0,
            risk_dollars=plan.risk_dollars if approved else 0,
            gross_exposure_after=max(0.0, gross_after),
            reviewed_at=now,
        )
