import pytest
from pydantic import ValidationError

from hanalpha.config import AppConfig


def base() -> dict:
    return {
        "environment": "live",
        "mode": "external",
        "base_currency": "USD",
        "starting_cash": 1,
        "universe": ["SPY"],
        "benchmarks": {"market": "SPY", "growth": "QQQ"},
        "bar_interval_minutes": 5,
        "lookback_bars": 120,
        "risk": {
            "risk_per_trade_pct": 0.001,
            "max_symbol_weight": 0.03,
            "max_sector_weight": 0.15,
            "max_gross_exposure": 0.2,
            "max_positions": 4,
            "daily_loss_limit_pct": 0.005,
            "max_drawdown_limit_pct": 0.02,
            "max_order_notional": 10000,
            "max_quote_age_seconds": 10,
            "min_price": 5,
            "min_average_dollar_volume": 100000000,
            "allow_earnings_overnight": False,
            "allow_market_orders": False,
        },
        "execution": {
            "broker": "ibkr",
            "auto_submit_paper": False,
            "require_human_approval_live": True,
            "slippage_bps": 8,
            "commission_per_share": 0.005,
            "minimum_commission": 1,
            "order_ttl_seconds": 20,
        },
        "agents": {
            "enabled": True,
            "provider": "deterministic",
            "require_evidence": True,
            "allow_llm_to_size": False,
            "max_news_age_hours": 48,
        },
        "strategies": {},
    }


def test_live_rejects_auto_submit() -> None:
    data = base()
    data["execution"]["auto_submit_paper"] = True
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)


def test_llm_sizing_is_forbidden() -> None:
    data = base()
    data["agents"]["allow_llm_to_size"] = True
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)
