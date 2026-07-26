from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from hanalpha.domain.enums import OperatingMode

_SECRET_OVERRIDES: dict[str, Any] = {}
_SECRET_OVERRIDE_FIELDS = frozenset(
    {
        "ibkr_account",
        "massive_api_key",
        "polygon_api_key",
        "fred_api_key",
        "sec_user_agent",
        "hanalpha_artifact_registry_path",
        "hanalpha_safety_case_public_keys",
    }
)


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RiskConfig(FrozenModel):
    risk_per_trade_pct: float = Field(gt=0, le=0.02)
    max_symbol_weight: float = Field(gt=0, le=0.25)
    max_sector_weight: float = Field(gt=0, le=0.50)
    max_gross_exposure: float = Field(gt=0, le=1.0)
    max_positions: int = Field(gt=0, le=50)
    daily_loss_limit_pct: float = Field(gt=0, le=0.10)
    max_drawdown_limit_pct: float = Field(gt=0, le=0.30)
    max_order_notional: float = Field(gt=0)
    max_quote_age_seconds: int = Field(gt=0, le=300)
    min_price: float = Field(gt=0)
    min_average_dollar_volume: float = Field(gt=0)
    allow_earnings_overnight: bool = False
    allow_market_orders: bool = False


class ExecutionConfig(FrozenModel):
    broker: Literal["simulated", "ibkr"] = "simulated"
    auto_submit_paper: bool = False
    broker_write_enabled: bool = False
    operator_api_enabled: bool = False
    require_human_approval_live: bool = True
    slippage_bps: float = Field(ge=0, le=100)
    commission_per_share: float = Field(ge=0, le=1)
    minimum_commission: float = Field(ge=0)
    order_ttl_seconds: int = Field(gt=0, le=3600)


class AgentConfig(FrozenModel):
    enabled: bool = True
    provider: Literal["deterministic", "llm", "disabled"] = "deterministic"
    require_evidence: bool = True
    allow_llm_to_size: bool = False
    max_news_age_hours: int = Field(gt=0, le=720)


class StrategyConfig(FrozenModel):
    enabled: bool = True
    fast_window: int | None = Field(default=None, gt=1)
    slow_window: int | None = Field(default=None, gt=2)
    trend_window: int | None = Field(default=None, gt=2)
    pullback_window: int | None = Field(default=None, gt=1)
    atr_window: int = Field(default=14, gt=1)
    breakout_buffer_atr: float | None = Field(default=None, ge=0, le=1)
    stop_atr: float = Field(default=2, gt=0, le=10)
    target_r_multiple: float = Field(default=2, gt=0, le=20)
    min_catalyst_score: float | None = Field(default=None, ge=0, le=1)
    max_catalyst_age_hours: int | None = Field(default=None, gt=0, le=720)


class AppConfig(FrozenModel):
    operating_mode: OperatingMode = OperatingMode.RESEARCH
    mode: Literal["synthetic", "external"] = "synthetic"
    base_currency: str = "USD"
    starting_cash: float = Field(gt=0)
    universe: list[str] = Field(min_length=1)
    benchmarks: dict[str, str]
    bar_interval_minutes: int = Field(gt=0, le=1440)
    lookback_bars: int = Field(gt=60, le=5000)
    risk: RiskConfig
    execution: ExecutionConfig
    agents: AgentConfig
    strategies: dict[str, StrategyConfig]

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_environment(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "environment" not in data:
            return data
        migrated = dict(data)
        legacy = migrated.pop("environment")
        execution = migrated.get("execution", {})
        auto_submit = bool(execution.get("auto_submit_paper", False))
        mapping = {
            "paper": OperatingMode.PAPER_AUTO if auto_submit else OperatingMode.PAPER_MANUAL,
            "live": OperatingMode.LIVE_PROPOSAL,
            "backtest": OperatingMode.BACKTEST,
        }
        if legacy not in mapping:
            raise ValueError(f"unsupported legacy environment: {legacy}")
        migrated.setdefault("operating_mode", mapping[legacy])
        return migrated

    @model_validator(mode="after")
    def safety_boundaries(self) -> AppConfig:
        mode = self.operating_mode
        execution = self.execution
        if mode == OperatingMode.LIVE_PROPOSAL:
            if self.execution.broker != "ibkr":
                raise ValueError("live_proposal mode requires IBKR broker")
            if not self.execution.require_human_approval_live:
                raise ValueError("live_proposal mode requires human approval")
        if mode == OperatingMode.PAPER_AUTO:
            if not execution.auto_submit_paper or not execution.broker_write_enabled:
                raise ValueError(
                    "paper_auto requires auto_submit_paper and broker_write_enabled"
                )
        elif execution.auto_submit_paper:
            raise ValueError("auto_submit_paper is only valid in paper_auto mode")
        if (
            mode not in {OperatingMode.PAPER_MANUAL, OperatingMode.PAPER_AUTO}
            and execution.broker_write_enabled
        ):
            raise ValueError(f"broker writes are forbidden in {mode.value} mode")
        if self.agents.allow_llm_to_size:
            raise ValueError("LLM position sizing is forbidden")
        return self


class SecretSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    hanalpha_env: str = "paper"
    hanalpha_config_path: str = "configs/paper.yaml"
    hanalpha_ledger_path: str = ".state/ledger.sqlite3"
    hanalpha_ibkr_observer_path: str = ".state/ibkr-observer.sqlite3"
    massive_api_key: str | None = None
    polygon_api_key: str | None = None
    fred_api_key: str | None = None
    sec_user_agent: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str | None = None
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 4002
    ibkr_client_id: int = 41
    ibkr_account: str | None = None
    hanalpha_broker_write_token: SecretStr | None = None
    hanalpha_operator_token: SecretStr | None = None
    hanalpha_safety_case_public_keys: str | None = None
    hanalpha_artifact_registry_path: str = ".state/evidence-artifacts.sqlite3"


def load_config(path: str | Path | None = None) -> tuple[AppConfig, SecretSettings]:
    secrets = SecretSettings(**_SECRET_OVERRIDES)
    selected_path = path or os.getenv("HANALPHA_CONFIG_PATH") or secrets.hanalpha_config_path
    config_path = Path(selected_path)
    if not config_path.exists():
        raise FileNotFoundError(f"configuration file not found: {config_path}")
    raw: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config = AppConfig.model_validate(raw)
    return config, secrets


def install_secret_overrides(values: dict[str, object]) -> None:
    """Install a process-local, whitelisted secret payload received over IPC."""

    if not values.keys() <= _SECRET_OVERRIDE_FIELDS:
        raise ValueError("secret IPC payload contains unsupported fields")
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise ValueError("secret IPC payload values must be non-empty strings")
    _SECRET_OVERRIDES.clear()
    _SECRET_OVERRIDES.update(values)


def clear_secret_overrides() -> None:
    """Clear process-local overrides; primarily used by isolated tests."""

    _SECRET_OVERRIDES.clear()
