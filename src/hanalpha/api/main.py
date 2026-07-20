from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hanalpha.config import load_config
from hanalpha.ops import OpsService
from hanalpha.orchestrator import TradingSystem, build_system
from hanalpha.portfolio import Ledger


class FreezeRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ApprovalRequest(BaseModel):
    actor_id: str = Field(min_length=3, max_length=200)


class ApprovalArmRequest(BaseModel):
    authority_id: str = Field(min_length=64, max_length=64)
    quote_snapshot_id: str = Field(min_length=64, max_length=64)
    max_drift_bps: Decimal = Field(gt=0, le=10)
    expires_at: datetime


class CancelIntentRequest(BaseModel):
    actor_id: str = Field(min_length=3, max_length=200)


class AppState:
    system: TradingSystem | None = None
    ledger: Ledger | None = None
    observer_path: Path | None = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config, secrets = load_config()
    ledger = Ledger(secrets.hanalpha_ledger_path)
    system = await build_system(config, secrets, ledger)
    state.system = system
    state.ledger = ledger
    state.observer_path = Path(secrets.hanalpha_ibkr_observer_path)
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


def get_ops() -> OpsService:
    return OpsService(get_system().execution_store, observer_path=state.observer_path)


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
    return {"ok": True, "service": "hanalpha-api", "as_of": datetime.now(UTC)}


@app.get("/ready")
async def ready() -> dict[str, Any]:
    system = get_system()
    return get_ops().readiness(await system.status())


@app.get("/ready/service")
async def ready_service() -> dict[str, Any]:
    result = get_ops().readiness(await get_system().status())
    return {"as_of": result["as_of"], **result["layers"]["service"]}


@app.get("/ready/observer")
async def ready_observer() -> dict[str, Any]:
    result = get_ops().readiness(await get_system().status())
    return {"as_of": result["as_of"], **result["layers"]["observer"]}


@app.get("/ready/paper-canary")
async def ready_paper_canary() -> dict[str, Any]:
    result = get_ops().readiness(await get_system().status())
    return {"as_of": result["as_of"], **result["layers"]["paper_canary"]}


@app.get("/ops/overview")
async def ops_overview() -> dict[str, Any]:
    return get_ops().overview()


@app.get("/metrics")
async def metrics() -> Response:
    return Response(get_ops().prometheus(), media_type="text/plain; version=0.0.4")


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


@app.post("/execution/approvals/{intent_id}/arm")
async def arm_intent(
    intent_id: str,
    request: ApprovalArmRequest,
    _: Annotated[None, Depends(require_operator_access)],
) -> dict[str, str]:
    try:
        arm_id = get_system().execution_store.arm_approved_intent(
            intent_id,
            authority_id=request.authority_id,
            quote_snapshot_id=request.quote_snapshot_id,
            max_drift_bps=request.max_drift_bps,
            at=datetime.now(UTC),
            expires_at=request.expires_at,
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"intent_id": intent_id, "arm_id": arm_id, "status": "ARMED"}


@app.post("/execution/intents/{intent_id}/cancel")
async def cancel_intent(
    intent_id: str,
    request: CancelIntentRequest,
    _: Annotated[None, Depends(require_operator_access)],
) -> dict[str, str]:
    try:
        command_id = get_system().execution_store.request_cancel(
            intent_id, actor_id=request.actor_id, at=datetime.now(UTC)
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"intent_id": intent_id, "command_id": command_id, "status": "CANCEL_REQUESTED"}


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


dashboard_dist = Path(__file__).parents[3] / "web" / "dist"
if dashboard_dist.is_dir():
    app.mount("/", StaticFiles(directory=dashboard_dist, html=True), name="dashboard")
