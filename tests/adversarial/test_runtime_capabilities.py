from __future__ import annotations

import pytest
from pydantic import ValidationError

from hanalpha.config import AppConfig, ExecutionConfig, SecretSettings
from hanalpha.domain.enums import OperatingMode, Side
from hanalpha.domain.models import OrderRequest
from hanalpha.execution import SimulatedBroker
from hanalpha.runtime.capabilities import build_runtime_access


def test_paper_auto_is_off_by_default() -> None:
    execution = ExecutionConfig(
        slippage_bps=5,
        commission_per_share=0.005,
        minimum_commission=1,
        order_ttl_seconds=30,
    )
    assert not execution.auto_submit_paper
    assert not execution.broker_write_enabled
    assert not execution.operator_api_enabled


@pytest.mark.parametrize(
    "mode",
    [
        OperatingMode.RESEARCH,
        OperatingMode.BACKTEST,
        OperatingMode.SHADOW,
        OperatingMode.LIVE_PROPOSAL,
    ],
)
def test_non_paper_modes_cannot_receive_broker_write_capability(risk_config, mode) -> None:
    execution = risk_config.execution.model_copy(
        update={"auto_submit_paper": False, "broker_write_enabled": False, "broker": "simulated"}
    )
    config = risk_config.model_copy(update={"operating_mode": mode, "execution": execution})
    access = build_runtime_access(config, SecretSettings(_env_file=None))
    assert access.broker_write is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        OperatingMode.RESEARCH,
        OperatingMode.BACKTEST,
        OperatingMode.SHADOW,
        OperatingMode.LIVE_PROPOSAL,
    ],
)
async def test_non_paper_modes_cannot_submit(risk_config, quote, mode) -> None:
    execution = risk_config.execution.model_copy(
        update={"auto_submit_paper": False, "broker_write_enabled": False, "broker": "simulated"}
    )
    config = risk_config.model_copy(update={"operating_mode": mode, "execution": execution})
    access = build_runtime_access(config, SecretSettings(_env_file=None))
    broker = SimulatedBroker(config.starting_cash, config.execution)
    order = OrderRequest(
        order_id=f"blocked-{mode.value}",
        plan_id="blocked-plan",
        symbol=quote.symbol,
        side=Side.BUY,
        quantity=1,
        limit_price=quote.ask,
        stop_price=quote.bid * 0.9,
        target_price=quote.ask * 1.1,
        idempotency_key=f"blocked-{mode.value}",
    )
    with pytest.raises(PermissionError, match="broker_write_capability_required"):
        await broker.submit(order, quote, access.broker_write)


def test_paper_auto_requires_explicit_write_token(risk_config) -> None:
    with pytest.raises(RuntimeError, match="broker write token"):
        build_runtime_access(risk_config, SecretSettings(_env_file=None))


def test_operator_api_token_is_explicit_and_constant_time_comparable(risk_config) -> None:
    execution = risk_config.execution.model_copy(update={"operator_api_enabled": True})
    config = risk_config.model_copy(update={"execution": execution})
    access = build_runtime_access(
        config,
        SecretSettings(
            _env_file=None,
            hanalpha_broker_write_token="b" * 32,
            hanalpha_operator_token="o" * 32,
        ),
    )
    assert access.authorize_operator("o" * 32)
    assert not access.authorize_operator("x" * 32)


def test_live_auto_mode_does_not_exist(risk_config) -> None:
    data = risk_config.model_dump(mode="python")
    data["operating_mode"] = "live_auto"
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)
