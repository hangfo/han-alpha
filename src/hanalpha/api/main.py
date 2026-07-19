from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from hanalpha.config import load_config
from hanalpha.orchestrator import TradingSystem, build_system
from hanalpha.portfolio import Ledger


class FreezeRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ApprovalRequest(BaseModel):
    actor_id: str = Field(min_length=3, max_length=200)


class AppState:
    system: TradingSystem | None = None
    ledger: Ledger | None = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config, secrets = load_config()
    ledger = Ledger(secrets.hanalpha_ledger_path)
    system = await build_system(config, secrets, ledger)
    state.system = system
    state.ledger = ledger
    yield
    system.close()
    ledger.close()


app = FastAPI(
    title="Han Alpha",
    version="0.1.0",
    description="Evidence-grounded paper trading and research system",
    lifespan=lifespan,
)


def get_system() -> TradingSystem:
    if state.system is None:
        raise HTTPException(status_code=503, detail="system_not_ready")
    return state.system


def require_operator_access(
    token: Annotated[str | None, Header(alias="X-Hanalpha-Operator-Token")] = None,
) -> None:
    system = get_system()
    if not system.runtime_access.authorize_operator(token):
        raise HTTPException(status_code=403, detail="operator_api_disabled_or_unauthorized")


def require_broker_write_access(
    _: Annotated[None, Depends(require_operator_access)],
) -> None:
    if not get_system().runtime_access.capabilities.broker_write:
        raise HTTPException(status_code=403, detail="broker_write_capability_unavailable")


@app.get("/health")
async def health() -> dict[str, Any]:
    system = get_system()
    status = await system.status()
    healthy = status["broker_connected"] and status["market_data_healthy"]
    return {"ok": healthy, "status": status}


@app.get("/status")
async def status() -> dict[str, Any]:
    return await get_system().status()


@app.post("/cycles/run")
async def run_cycle(_: Annotated[None, Depends(require_operator_access)]) -> dict[str, Any]:
    return await get_system().run_cycle()


@app.get("/signals")
async def signals() -> list[dict[str, Any]]:
    return get_system().last_signals


@app.get("/orders")
async def orders() -> list[dict[str, Any]]:
    return get_system().last_orders


@app.get("/events")
async def events(limit: int = 100) -> list[dict[str, Any]]:
    if state.ledger is None:
        raise HTTPException(status_code=503, detail="ledger_not_ready")
    return state.ledger.recent_events(max(1, min(limit, 1000)))


@app.post("/risk/freeze")
async def freeze(
    request: FreezeRequest,
    _: Annotated[None, Depends(require_operator_access)],
) -> dict[str, Any]:
    system = get_system()
    system.kill_switch.freeze(request.reason)
    system.execution_store.open_freeze_ticket(
        "MANUAL_OPERATOR_FREEZE", source="operator_api", at=datetime.now(UTC)
    )
    return {"frozen": True, "reason": request.reason}


@app.post("/risk/unfreeze")
async def unfreeze(_: Annotated[None, Depends(require_operator_access)]) -> dict[str, Any]:
    system = get_system()
    system.execution_store.resolve_freeze_ticket(
        "MANUAL_OPERATOR_FREEZE",
        source="operator_api",
        at=datetime.now(UTC),
        evidence="authenticated operator request",
    )
    frozen, reason = system.execution_store.is_frozen()
    if not frozen:
        system.kill_switch.unfreeze()
    return {"frozen": frozen, "reason": reason}


@app.get("/execution/approvals")
async def pending_approvals(
    _: Annotated[None, Depends(require_operator_access)],
) -> list[dict[str, Any]]:
    return [
        {
            "intent_id": row["intent_id"],
            "decision_id": row["decision_id"],
            "client_order_key": row["client_order_key"],
            "status": row["status"],
            "version": row["version"],
        }
        for row in get_system().execution_store.pending_approvals()
    ]


@app.post("/execution/approvals/{intent_id}")
async def approve_intent(
    intent_id: str,
    request: ApprovalRequest,
    _: Annotated[None, Depends(require_operator_access)],
) -> dict[str, str]:
    try:
        approval_id = get_system().execution_store.approve(
            intent_id, actor_id=request.actor_id, at=datetime.now(UTC)
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"intent_id": intent_id, "approval_id": approval_id, "status": "APPROVED"}


@app.post("/orders/cancel-all")
async def cancel_all(_: Annotated[None, Depends(require_broker_write_access)]) -> dict[str, Any]:
    system = get_system()
    system.kill_switch.freeze("cancel_all_requested")
    result = await system.cancel_all()
    return {"events": [event.model_dump(mode="json") for event in result]}


@app.post("/positions/flatten-all")
async def flatten_all(_: Annotated[None, Depends(require_broker_write_access)]) -> dict[str, Any]:
    system = get_system()
    system.kill_switch.freeze("flatten_all_requested")
    snapshot = await system.broker.get_account_snapshot()
    quotes = {
        position.symbol: await system.provider.get_quote(position.symbol)
        for position in snapshot.positions
    }
    result = await system.flatten_all(quotes)
    return {"events": [event.model_dump(mode="json") for event in result]}
