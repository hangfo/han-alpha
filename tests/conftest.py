from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hanalpha.config import AppConfig
from hanalpha.domain.enums import MarketRegime, Side, SignalAction
from hanalpha.domain.models import (
    AccountSnapshot,
    Quote,
    RegimeSnapshot,
    Signal,
    TradePlan,
)


@pytest.fixture
def now() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def quote(now: datetime) -> Quote:
    return Quote(symbol="NVDA", timestamp=now, bid=99.9, ask=100.1, last=100.0)


@pytest.fixture
def account(now: datetime) -> AccountSnapshot:
    return AccountSnapshot(
        timestamp=now,
        net_liquidation=100_000,
        cash=100_000,
        buying_power=100_000,
        daily_pnl=0,
        peak_net_liquidation=100_000,
        positions=[],
        connected=True,
    )


@pytest.fixture
def regime(now: datetime) -> RegimeSnapshot:
    return RegimeSnapshot(
        regime=MarketRegime.RISK_ON,
        timestamp=now,
        risk_multiplier=1.0,
        max_gross_exposure=0.5,
        allowed_strategies=["breakout", "trend_pullback", "event_continuation"],
        metrics={},
    )


@pytest.fixture
def signal(now: datetime) -> Signal:
    return Signal(
        signal_id="signal-12345678",
        symbol="NVDA",
        strategy="breakout",
        action=SignalAction.BUY,
        generated_at=now,
        confidence=0.8,
        reference_price=100,
        stop_price=98,
        target_price=105,
    )


@pytest.fixture
def plan(now: datetime) -> TradePlan:
    return TradePlan(
        plan_id="plan-123",
        signal_id="signal-12345678",
        symbol="NVDA",
        strategy="breakout",
        side=Side.BUY,
        created_at=now,
        entry_price=100.1,
        stop_price=98,
        target_price=105,
        quantity=100,
        idempotency_key="paper:signal-12345678",
    )


@pytest.fixture
def risk_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "environment": "paper",
            "mode": "synthetic",
            "base_currency": "USD",
            "starting_cash": 100000,
            "universe": ["NVDA"],
            "benchmarks": {"market": "SPY", "growth": "QQQ"},
            "bar_interval_minutes": 5,
            "lookback_bars": 120,
            "risk": {
                "risk_per_trade_pct": 0.0035,
                "max_symbol_weight": 0.07,
                "max_sector_weight": 0.25,
                "max_gross_exposure": 0.5,
                "max_positions": 8,
                "daily_loss_limit_pct": 0.01,
                "max_drawdown_limit_pct": 0.05,
                "max_order_notional": 50000,
                "max_quote_age_seconds": 20,
                "min_price": 5,
                "min_average_dollar_volume": 50000000,
                "allow_earnings_overnight": False,
                "allow_market_orders": False,
            },
            "execution": {
                "broker": "simulated",
                "auto_submit_paper": True,
                "require_human_approval_live": True,
                "slippage_bps": 5,
                "commission_per_share": 0.005,
                "minimum_commission": 1,
                "order_ttl_seconds": 30,
            },
            "agents": {
                "enabled": True,
                "provider": "deterministic",
                "require_evidence": True,
                "allow_llm_to_size": False,
                "max_news_age_hours": 72,
            },
            "strategies": {
                "breakout": {
                    "enabled": True,
                    "fast_window": 20,
                    "slow_window": 55,
                    "atr_window": 14,
                    "breakout_buffer_atr": 0.05,
                    "stop_atr": 2,
                    "target_r_multiple": 2.5,
                }
            },
        }
    )
