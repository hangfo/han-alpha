#!/usr/bin/env python3
"""Isolated, one-shot IBKR Paper fact producer for E1 acceptance evidence.

This script is intentionally not imported by the Han Alpha runtime. It cannot
connect to live ports, does not expose global cancel, and consumes each permit
before the first broker write so an uncertain outcome is never retried.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic_core import to_jsonable_python

from hanalpha.config import load_config
from hanalpha.execution.ibkr_observer import account_hash, broker_account_identity
from hanalpha.ops.artifact_registry import ArtifactRegistry, ArtifactType
from hanalpha.ops.artifacts import write_immutable_json
from hanalpha.ops.external_cost import (
    ExternalAction,
    ExternalProvider,
    external_cost_receipt,
)
from hanalpha.ops.secrets import LocalSecret, MacOSKeychainSecretProvider
from hanalpha.simulation.events import canonical_hash

try:
    from ibapi.client import EClient
    from ibapi.contract import Contract
    from ibapi.order import Order
    from ibapi.order_cancel import OrderCancel
    from ibapi.wrapper import EWrapper

    IBAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised by clean Linux CI
    IBAPI_AVAILABLE = False

    class EWrapper:  # type: ignore[no-redef]
        pass

    class EClient:  # type: ignore[no-redef]
        def __init__(self, _wrapper: Any) -> None:
            pass

    class Contract:  # type: ignore[no-redef]
        pass

    class Order:  # type: ignore[no-redef]
        pass

    class OrderCancel:  # type: ignore[no-redef]
        pass


PAPER_PORTS = frozenset({4002, 7497})
FIXTURE_CLIENT_IDS = range(9100, 9200)
MAX_QUANTITY = 1
MAX_NOTIONAL = Decimal("1000")
PERMIT_TTL_MINUTES = 15
QUOTE_TTL_SECONDS = 15
MAX_SPREAD = Decimal("0.10")
MAX_RELATIVE_SPREAD = Decimal("0.001")
PRICE_COLLAR = Decimal("0.05")
SAFE_FAILURE_CODES = {
    "contract qualification timed out": "CONTRACT_QUALIFICATION_TIMEOUT",
    "complete real-time quote was not received": "REALTIME_QUOTE_TIMEOUT",
    "real-time market data entitlement is unavailable": "REALTIME_MARKET_DATA_ENTITLEMENT_REQUIRED",
    "fixture connection did not become ready": "PAPER_CONNECTION_TIMEOUT",
    "fixture state snapshot timed out": "FIXTURE_STATE_TIMEOUT",
    "open-order lookup timed out": "OPEN_ORDER_LOOKUP_TIMEOUT",
    "position lookup timed out": "POSITION_LOOKUP_TIMEOUT",
    "fixture lifecycle requires a zero contract baseline": "ZERO_BASELINE_REQUIRED",
}
INFORMATIONAL_IBKR_CODES = {1102, 2104, 2106, 2158}
FEED_SCOPES = {"NON_CONSOLIDATED", "CONSOLIDATED_NBBO", "UNKNOWN"}


class FixtureAction(StrEnum):
    PLACE = "PLACE"
    MODIFY = "MODIFY"
    CANCEL = "CANCEL"
    CLOSE_POSITION = "CLOSE_POSITION"


class FixtureClient(EWrapper, EClient):  # type: ignore[misc]
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.ready = threading.Event()
        self.open_orders_end = threading.Event()
        self.positions_end = threading.Event()
        self.order_update = threading.Event()
        self.managed_accounts: tuple[str, ...] = ()
        self.next_order_id: int | None = None
        self.open_orders: dict[int, tuple[Any, Any]] = {}
        self.positions: dict[str, Decimal] = {}
        self.status_by_order: dict[int, str] = {}
        self.errors: list[tuple[int, str]] = []
        self.contract_details: list[Any] = []
        self.contract_details_end = threading.Event()
        self.quote_update = threading.Event()
        self.market_data_type: int | None = None
        self.ticks: dict[str, Decimal] = {}
        self.bbo_exchange: str | None = None
        self.snapshot_permissions: int | None = None

    def nextValidId(self, orderId: int) -> None:
        self.next_order_id = orderId
        self.ready.set()

    def managedAccounts(self, accountsList: str) -> None:
        self.managed_accounts = tuple(item for item in accountsList.split(",") if item)

    def openOrder(self, orderId: int, contract: Any, order: Any, _state: Any) -> None:
        self.open_orders[orderId] = (contract, order)
        self.order_update.set()

    def openOrderEnd(self) -> None:
        self.open_orders_end.set()

    def position(self, account: str, contract: Any, position: Any, _avgCost: float) -> None:
        if account in self.managed_accounts:
            self.positions[str(contract.symbol)] = Decimal(str(position))
            self.positions[str(int(getattr(contract, "conId", 0)))] = Decimal(str(position))

    def positionEnd(self) -> None:
        self.positions_end.set()

    def orderStatus(
        self,
        orderId: int,
        status: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        self.status_by_order[orderId] = status
        self.order_update.set()

    def contractDetails(self, _reqId: int, contractDetails: Any) -> None:
        self.contract_details.append(contractDetails)

    def contractDetailsEnd(self, _reqId: int) -> None:
        self.contract_details_end.set()

    def marketDataType(self, _reqId: int, marketDataType: int) -> None:
        self.market_data_type = int(marketDataType)
        self.quote_update.set()

    def tickPrice(self, _reqId: int, tickType: int, price: float, _attrib: Any) -> None:
        tick_names = {1: "bid", 2: "ask", 4: "last", 66: "bid", 67: "ask", 68: "last"}
        name = tick_names.get(int(tickType))
        if name is not None and price > 0:
            self.ticks[name] = Decimal(str(price))
            if {"bid", "ask", "last"} <= self.ticks.keys():
                self.quote_update.set()

    def tickReqParams(
        self, _tickerId: int, _minTick: float, bboExchange: str, snapshotPermissions: int
    ) -> None:
        self.bbo_exchange = bboExchange or None
        self.snapshot_permissions = int(snapshotPermissions)

    def error(self, reqId: int, *args: Any) -> None:
        if len(args) >= 3 and isinstance(args[0], int) and isinstance(args[1], int):
            code = int(args[1])
            message = str(args[2])
        elif len(args) >= 2 and isinstance(args[-2], int):
            code = int(args[-2])
            message = str(args[-1])
        elif len(args) >= 2 and isinstance(args[0], int):
            code = int(args[0])
            message = str(args[1])
        else:
            return
        if code not in {2104, 2106, 2158}:
            self.errors.append((code, message[:160]))
            self.order_update.set()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_ibapi() -> None:
    if not IBAPI_AVAILABLE:
        raise RuntimeError("official IBKR ibapi is not installed")


def _market_phase_from_liquid_hours(details: Any, observed_at: datetime) -> str:
    timezone_name = str(getattr(details, "timeZoneId", ""))
    try:
        timezone = ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError("contract timezone is not authoritative") from exc
    local = observed_at.astimezone(timezone)
    liquid_hours = str(getattr(details, "liquidHours", ""))
    for segment in liquid_hours.split(";"):
        if not segment or "CLOSED" in segment or "-" not in segment:
            continue
        start_raw, end_raw = segment.split("-", 1)
        try:
            start = datetime.strptime(start_raw, "%Y%m%d:%H%M").replace(tzinfo=timezone)
            end = datetime.strptime(end_raw, "%Y%m%d:%H%M").replace(tzinfo=timezone)
        except ValueError:
            continue
        if start <= local <= end:
            return "REGULAR"
    return "CLOSED"


def _quote_capsule_body(
    *,
    account_identity_hash: str,
    details: Any,
    ticks: dict[str, Decimal],
    market_data_type: int | None,
    observed_at: datetime,
    feed_scope: str = "UNKNOWN",
    bbo_exchange: str | None = None,
    snapshot_permissions: int | None = None,
) -> dict[str, Any]:
    contract = details.contract
    con_id = int(getattr(contract, "conId", 0))
    security_type = str(getattr(contract, "secType", ""))
    currency = str(getattr(contract, "currency", ""))
    exchange = str(getattr(contract, "exchange", ""))
    required_contract: dict[str, Any] = {
        "con_id": con_id,
        "symbol": str(getattr(contract, "symbol", "")).upper(),
        "security_type": security_type,
        "currency": currency,
        "exchange": exchange,
    }
    if con_id <= 0 or security_type != "STK" or currency != "USD" or exchange != "SMART":
        raise ValueError("contract identity is not an exact SMART USD stock")
    if market_data_type != 1:
        raise ValueError("fixture requires real-time market data")
    if feed_scope not in FEED_SCOPES:
        raise ValueError("unsupported feed scope")
    if not {"bid", "ask", "last"} <= ticks.keys():
        raise ValueError("fixture quote is incomplete")
    bid, ask, last = ticks["bid"], ticks["ask"], ticks["last"]
    if bid <= 0 or ask <= bid or last <= 0:
        raise ValueError("fixture quote is crossed or non-positive")
    spread = ask - bid
    midpoint = (ask + bid) / 2
    if spread > MAX_SPREAD or spread / midpoint > MAX_RELATIVE_SPREAD:
        raise ValueError("fixture quote spread exceeds hard collar")
    market_phase = _market_phase_from_liquid_hours(details, observed_at)
    if market_phase != "REGULAR":
        raise ValueError("fixture quote is outside the contract regular session")
    expires_at = observed_at + timedelta(seconds=QUOTE_TTL_SECONDS)
    normalized = to_jsonable_python(
        {
            "schema_version": "e1-quote-capsule-v1",
            "artifact_type": "E1_QUOTE_CAPSULE",
            "account_identity_hash": account_identity_hash,
            **required_contract,
            "primary_exchange": str(getattr(contract, "primaryExchange", "")),
            "quote_source": "IBKR_TWS",
            "market_data_type": "REALTIME",
            "market_data_type_code": market_data_type,
            "feed_scope": feed_scope,
            "bbo_exchange": bbo_exchange,
            "snapshot_permissions": snapshot_permissions,
            "fit_for_purpose": {
                "CONNECTIVITY_ONLY": "PASS",
                "PAPER_FIXTURE": (
                    "PASS" if feed_scope != "UNKNOWN" else "BLOCKED_FEED_SCOPE_UNKNOWN"
                ),
                "SLIPPAGE_CALIBRATION": (
                    "PASS"
                    if feed_scope == "CONSOLIDATED_NBBO"
                    else "BLOCKED_CONSOLIDATED_NBBO_REQUIRED"
                ),
                "CANARY_PRICE_PROTECTION": (
                    "PASS"
                    if feed_scope == "CONSOLIDATED_NBBO"
                    else "BLOCKED_CONSOLIDATED_NBBO_REQUIRED"
                ),
                "LIVE_PROPOSAL": (
                    "PASS"
                    if feed_scope == "CONSOLIDATED_NBBO"
                    else "BLOCKED_CONSOLIDATED_NBBO_REQUIRED"
                ),
            },
            "observed_at": observed_at,
            "expires_at": expires_at,
            "market_phase": market_phase,
            "bid": str(bid),
            "ask": str(ask),
            "last": str(last),
            "spread": str(spread),
            "liquid_hours_hash": canonical_hash(
                {"liquid_hours": str(getattr(details, "liquidHours", ""))}
            ),
            "decision": "PASS",
            "secrets_redacted": True,
        }
    )
    if not isinstance(normalized, dict):
        raise TypeError("quote capsule normalization must produce an object")
    return normalized


def capture_quote(args: argparse.Namespace) -> int:
    _require_ibapi()
    config, secrets = load_config()
    if config.execution.broker_write_enabled or config.execution.auto_submit_paper:
        raise ValueError("production execution configuration must remain disabled")
    if args.port not in PAPER_PORTS or args.client_id not in FIXTURE_CLIENT_IDS:
        raise ValueError("quote capture requires reserved Paper fixture transport")
    if not args.attest_paper:
        raise ValueError("explicit --attest-paper is required")
    cost = external_cost_receipt(
        provider=ExternalProvider.IBKR,
        action=ExternalAction.STREAMING_QUOTE,
        request_count=1,
        max_new_cost=Decimal(str(args.max_new_cost)),
        existing_entitlement=bool(args.existing_entitlement_attested),
        current_plan="EXISTING_MARKET_DATA_ENTITLEMENT",
    )
    cost_path = args.cost_output / f"{cost['artifact_id']}.json"
    write_immutable_json(cost_path, cost)
    cost_registry = ArtifactRegistry(args.registry)
    try:
        cost_registry.register(
            cost_path,
            artifact_type=ArtifactType.EXTERNAL_COST_RECEIPT,
            status="VERIFIED" if cost["decision"] == "ALLOW" else "REJECTED",
        )
    finally:
        cost_registry.close()
    if cost["decision"] != "ALLOW":
        raise PermissionError("external quote cost is not authorized")
    account = MacOSKeychainSecretProvider().get(LocalSecret.IBKR_ACCOUNT)
    if not account:
        raise ValueError("Paper account is missing from macOS Keychain")
    identity = broker_account_identity(
        account_hash_value=account_hash(account),
        environment=secrets.hanalpha_env,
        host="127.0.0.1",
        port=args.port,
    )
    permit_stub = {
        "paper_port": args.port,
        "fixture_client_id": args.client_id,
    }
    app, thread = _connect_verified(permit_stub, account)
    try:
        request_id = 8801
        app.reqContractDetails(request_id, _stock_contract(args.symbol.upper()))
        if not app.contract_details_end.wait(8):
            raise RuntimeError("contract qualification timed out")
        if len(app.contract_details) != 1:
            raise ValueError("symbol did not resolve to exactly one contract")
        details = app.contract_details[0]
        qualified = details.contract
        app.reqMarketDataType(1)
        app.reqMktData(request_id + 1, qualified, "", False, False, [])
        quote_deadline = time.monotonic() + 8
        while not {"bid", "ask", "last"} <= app.ticks.keys() and time.monotonic() < quote_deadline:
            app.quote_update.wait(0.2)
            app.quote_update.clear()
        if not {"bid", "ask", "last"} <= app.ticks.keys():
            if {354, 10089, 10167, 10168} & {code for code, _ in app.errors}:
                raise RuntimeError("real-time market data entitlement is unavailable")
            raise RuntimeError("complete real-time quote was not received")
        observed_at = _utc_now()
        body = _quote_capsule_body(
            account_identity_hash=identity.identity_hash,
            details=details,
            ticks=app.ticks,
            market_data_type=app.market_data_type,
            observed_at=observed_at,
            feed_scope=args.feed_scope,
            bbo_exchange=app.bbo_exchange,
            snapshot_permissions=app.snapshot_permissions,
        )
        app.cancelMktData(request_id + 1)
    finally:
        app.disconnect()
        thread.join(timeout=2)
    capsule = {"artifact_id": canonical_hash(body), **body}
    destination = args.output / f"{capsule['artifact_id']}.quote.json"
    write_immutable_json(destination, capsule)
    registry = ArtifactRegistry(args.registry)
    try:
        registry.register(
            destination,
            artifact_type=ArtifactType.E1_QUOTE_CAPSULE,
            status="VERIFIED",
            account_hash=identity.identity_hash,
        )
    finally:
        registry.close()
    print(json.dumps({"quote_capsule": str(destination), "secrets_redacted": True}))
    return 0


def _load_quote_capsule(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("quote capsule must be a JSON object")
    claimed = document.get("artifact_id")
    body = {key: value for key, value in document.items() if key != "artifact_id"}
    if claimed != canonical_hash(body):
        raise ValueError("quote capsule hash mismatch")
    if document.get("schema_version") != "e1-quote-capsule-v1":
        raise ValueError("unsupported quote capsule")
    if (
        document.get("decision") != "PASS"
        or document.get("market_data_type") != "REALTIME"
        or document.get("market_phase") != "REGULAR"
    ):
        raise ValueError("quote capsule is not eligible for a filling fixture")
    if document.get("fit_for_purpose", {}).get("PAPER_FIXTURE") != "PASS":
        raise ValueError("quote capsule is not fit for a Paper fixture")
    if datetime.fromisoformat(str(document["expires_at"])) < _utc_now():
        raise ValueError("quote capsule is stale")
    return document


def _permit_body(args: argparse.Namespace, account_identity_hash: str) -> dict[str, Any]:
    now = _utc_now()
    action = FixtureAction(args.action)
    if args.port not in PAPER_PORTS:
        raise ValueError("fixture refuses non-Paper ports")
    if args.client_id not in FIXTURE_CLIENT_IDS:
        raise ValueError("fixture client ID must be in reserved range 9100-9199")
    if not args.attest_paper:
        raise ValueError("explicit --attest-paper is required")
    if args.quantity != 1:
        raise ValueError("fixture quantity must be exactly one whole share")
    price = Decimal(args.limit_price)
    if price <= 0 or price * args.quantity > MAX_NOTIONAL:
        raise ValueError("fixture notional exceeds the hard ceiling")
    if not args.symbol.isascii() or not args.symbol.isalpha() or len(args.symbol) > 8:
        raise ValueError("fixture symbol must be a short ASCII stock/ETF ticker")
    if action in {FixtureAction.MODIFY, FixtureAction.CANCEL}:
        if args.broker_order_id is None or not args.expected_order_ref:
            raise ValueError("modify/cancel requires exact broker order ID and order ref")
        if not args.expected_order_ref.startswith("E1FIX:"):
            raise ValueError("fixture may only modify/cancel its own namespace")
    elif args.broker_order_id is not None or args.expected_order_ref:
        raise ValueError("broker order binding is only valid for modify/cancel")
    quote: dict[str, Any] | None = None
    if action in {FixtureAction.PLACE, FixtureAction.MODIFY, FixtureAction.CLOSE_POSITION}:
        quote_path = getattr(args, "quote_capsule", None)
        if quote_path is None:
            raise ValueError("quote-bound fixture action requires --quote-capsule")
        quote = _load_quote_capsule(Path(quote_path))
        if quote["account_identity_hash"] != account_identity_hash:
            raise PermissionError("quote capsule account identity mismatch")
        if quote["symbol"] != args.symbol.upper():
            raise ValueError("quote capsule symbol mismatch")
        side = "SELL" if action is FixtureAction.CLOSE_POSITION else str(args.side)
        bid = Decimal(str(quote["bid"]))
        ask = Decimal(str(quote["ask"]))
        if side == "BUY" and not ask - Decimal("0.01") <= price <= ask + PRICE_COLLAR:
            raise ValueError("buy limit price is outside the fresh ask collar")
        if side == "SELL" and not bid - PRICE_COLLAR <= price <= bid + Decimal("0.01"):
            raise ValueError("sell limit price is outside the fresh bid collar")
    else:
        side = str(args.side)
    quote_expiry = (
        datetime.fromisoformat(str(quote["expires_at"]))
        if quote is not None
        else now + timedelta(minutes=PERMIT_TTL_MINUTES)
    )
    body = {
        "schema_version": "e1-fixture-permit-v2",
        "artifact_type": "E1_FIXTURE_PERMIT",
        "action": action,
        "account_identity_hash": account_identity_hash,
        "host": "127.0.0.1",
        "paper_port": args.port,
        "fixture_client_id": args.client_id,
        "symbol": args.symbol.upper(),
        "quote_capsule_id": quote["artifact_id"] if quote is not None else None,
        "con_id": int(quote["con_id"]) if quote is not None else None,
        "security_type": "STK",
        "currency": "USD",
        "exchange": "SMART",
        "side": side,
        "quantity": args.quantity,
        "limit_price": str(price),
        "max_notional": str(MAX_NOTIONAL),
        "broker_order_id": args.broker_order_id,
        "expected_order_ref": args.expected_order_ref,
        "issued_at": now,
        "expires_at": min(now + timedelta(minutes=PERMIT_TTL_MINUTES), quote_expiry),
        "operator_attested_paper": True,
        "one_shot": True,
        "secrets_redacted": True,
    }
    return body


def create_permit(args: argparse.Namespace) -> int:
    config, secrets = load_config()
    if config.execution.broker_write_enabled or config.execution.auto_submit_paper:
        raise ValueError("production execution configuration must remain disabled")
    account = MacOSKeychainSecretProvider().get(LocalSecret.IBKR_ACCOUNT)
    if not account:
        raise ValueError("Paper account is missing from macOS Keychain")
    identity = broker_account_identity(
        account_hash_value=account_hash(account),
        environment=secrets.hanalpha_env,
        host="127.0.0.1",
        port=args.port,
    )
    body = to_jsonable_python(_permit_body(args, identity.identity_hash))
    permit = {"artifact_id": canonical_hash(body), **body}
    destination = args.output / f"{permit['artifact_id']}.permit.json"
    write_immutable_json(destination, permit)
    registry = ArtifactRegistry(args.registry)
    try:
        registry.register(
            destination,
            artifact_type=ArtifactType.E1_FIXTURE_PERMIT,
            status="VERIFIED",
            account_hash=identity.identity_hash,
        )
    finally:
        registry.close()
    print(json.dumps({"permit": str(destination), "secrets_redacted": True}))
    return 0


def _load_permit(path: Path) -> dict[str, Any]:
    loaded: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("fixture permit must be a JSON object")
    permit: dict[str, Any] = loaded
    claimed = permit.get("artifact_id")
    body = {key: value for key, value in permit.items() if key != "artifact_id"}
    if claimed != canonical_hash(body):
        raise ValueError("fixture permit hash mismatch")
    if permit.get("schema_version") != "e1-fixture-permit-v2":
        raise ValueError("unsupported fixture permit")
    if not permit.get("one_shot") or not permit.get("operator_attested_paper"):
        raise ValueError("fixture permit lacks one-shot Paper attestation")
    if datetime.fromisoformat(str(permit["expires_at"])) < _utc_now():
        raise ValueError("fixture permit expired")
    if int(permit["paper_port"]) not in PAPER_PORTS:
        raise ValueError("fixture refuses non-Paper ports")
    if int(permit["fixture_client_id"]) not in FIXTURE_CLIENT_IDS:
        raise ValueError("fixture client ID is outside the reserved range")
    if int(permit["quantity"]) != MAX_QUANTITY:
        raise ValueError("fixture quantity ceiling violated")
    if Decimal(str(permit["limit_price"])) * int(permit["quantity"]) > MAX_NOTIONAL:
        raise ValueError("fixture notional ceiling violated")
    action = FixtureAction(str(permit["action"]))
    if action in {
        FixtureAction.PLACE,
        FixtureAction.MODIFY,
        FixtureAction.CLOSE_POSITION,
    } and (not permit.get("quote_capsule_id") or int(permit.get("con_id") or 0) <= 0):
        raise ValueError("fixture permit lacks quote and contract binding")
    return permit


def _verify_permit_quote_binding(permit: dict[str, Any], quote_root: Path) -> dict[str, Any] | None:
    if not permit.get("quote_capsule_id"):
        return None
    quote_id = str(permit["quote_capsule_id"])
    quote = _load_quote_capsule(quote_root / f"{quote_id}.quote.json")
    for field in (
        "account_identity_hash",
        "symbol",
        "con_id",
        "security_type",
        "currency",
        "exchange",
    ):
        if permit.get(field) != quote.get(field):
            raise PermissionError(f"permit quote binding mismatch: {field}")
    return quote


def _consume_permit_once(ledger: Path, permit_id: str) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(ledger, isolation_level=None)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS consumed_fixture_permits "
            "(permit_id TEXT PRIMARY KEY, consumed_at TEXT NOT NULL)"
        )
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO consumed_fixture_permits(permit_id, consumed_at) VALUES (?, ?)",
            (permit_id, _utc_now().isoformat()),
        )
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _fixture_state(app: FixtureClient, account: str) -> dict[str, Any]:
    app.open_orders.clear()
    app.open_orders_end.clear()
    app.positions.clear()
    app.positions_end.clear()
    app.reqAllOpenOrders()
    app.reqPositions()
    if not app.open_orders_end.wait(5) or not app.positions_end.wait(5):
        raise RuntimeError("fixture state snapshot timed out")
    fixture_orders = [
        {
            "broker_order_id": order_id,
            "order_ref": str(getattr(order, "orderRef", "")),
            "con_id": int(getattr(contract, "conId", 0)),
            "symbol": str(getattr(contract, "symbol", "")),
            "side": str(getattr(order, "action", "")),
            "status": app.status_by_order.get(order_id),
        }
        for order_id, (contract, order) in sorted(app.open_orders.items())
        if str(getattr(order, "account", "")) == account
        and str(getattr(order, "orderRef", "")).startswith("E1FIX:")
    ]
    return {
        "fixture_orders": fixture_orders,
        "positions": dict(sorted(app.positions.items())),
    }


def _initialize_lifecycle_ledger(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS fixture_lifecycles ("
        "lifecycle_id TEXT PRIMARY KEY, quote_capsule_id TEXT NOT NULL, "
        "account_identity_hash TEXT NOT NULL, con_id INTEGER NOT NULL, symbol TEXT NOT NULL, "
        "security_type TEXT NOT NULL DEFAULT 'STK', currency TEXT NOT NULL DEFAULT 'USD', "
        "exchange TEXT NOT NULL DEFAULT 'SMART', baseline_quantity TEXT NOT NULL, "
        "max_quantity INTEGER NOT NULL DEFAULT 1, max_notional TEXT NOT NULL DEFAULT '1000', "
        "created_at TEXT NOT NULL, state TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS fixture_lifecycle_actions ("
        "lifecycle_id TEXT NOT NULL, permit_id TEXT NOT NULL UNIQUE, receipt_id TEXT NOT NULL, "
        "decision TEXT NOT NULL, observed_at TEXT NOT NULL, "
        "FOREIGN KEY(lifecycle_id) REFERENCES fixture_lifecycles(lifecycle_id))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS fixture_lifecycle_quotes ("
        "lifecycle_id TEXT NOT NULL, action TEXT NOT NULL, permit_id TEXT NOT NULL UNIQUE, "
        "quote_capsule_id TEXT UNIQUE, observed_at TEXT, expires_at TEXT, decision TEXT NOT NULL, "
        "FOREIGN KEY(lifecycle_id) REFERENCES fixture_lifecycles(lifecycle_id))"
    )
    lifecycle_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(fixture_lifecycles)").fetchall()
    }
    lifecycle_migrations = {
        "security_type": "TEXT NOT NULL DEFAULT 'STK'",
        "currency": "TEXT NOT NULL DEFAULT 'USD'",
        "exchange": "TEXT NOT NULL DEFAULT 'SMART'",
        "max_quantity": "INTEGER NOT NULL DEFAULT 1",
        "max_notional": "TEXT NOT NULL DEFAULT '1000'",
    }
    for column, declaration in lifecycle_migrations.items():
        if column not in lifecycle_columns:
            connection.execute(
                f"ALTER TABLE fixture_lifecycles ADD COLUMN {column} {declaration}"
            )
    connection.commit()
    return connection


def start_lifecycle(args: argparse.Namespace) -> int:
    _require_ibapi()
    config, secrets = load_config()
    if config.execution.broker_write_enabled or config.execution.auto_submit_paper:
        raise ValueError("production execution configuration must remain disabled")
    quote = _load_quote_capsule(args.quote_capsule)
    account = MacOSKeychainSecretProvider().get(LocalSecret.IBKR_ACCOUNT)
    if not account:
        raise ValueError("Paper account is missing from macOS Keychain")
    expected_identity = broker_account_identity(
        account_hash_value=account_hash(account),
        environment=secrets.hanalpha_env,
        host="127.0.0.1",
        port=args.port,
    )
    if expected_identity.identity_hash != quote["account_identity_hash"]:
        raise PermissionError("lifecycle quote account identity mismatch")
    transport = {"paper_port": args.port, "fixture_client_id": args.client_id}
    app, thread = _connect_verified(transport, account)
    try:
        snapshot = _fixture_state(app, account)
    finally:
        app.disconnect()
        thread.join(timeout=2)
    if snapshot["fixture_orders"]:
        raise RuntimeError("cannot start lifecycle with outstanding fixture orders")
    baseline = Decimal(str(snapshot["positions"].get(str(quote["con_id"]), "0")))
    if baseline != 0:
        raise RuntimeError("fixture lifecycle requires a zero contract baseline")
    body = {
        "quote_capsule_id": quote["artifact_id"],
        "account_identity_hash": quote["account_identity_hash"],
        "con_id": int(quote["con_id"]),
        "symbol": quote["symbol"],
        "baseline_quantity": str(baseline),
        "created_at": _utc_now().isoformat(),
    }
    lifecycle_id = canonical_hash(body)
    connection = _initialize_lifecycle_ledger(args.ledger)
    try:
        connection.execute(
            "INSERT INTO fixture_lifecycles ("
            "lifecycle_id, quote_capsule_id, account_identity_hash, con_id, symbol, "
            "security_type, currency, exchange, baseline_quantity, max_quantity, "
            "max_notional, created_at, state"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                lifecycle_id,
                quote["artifact_id"],
                quote["account_identity_hash"],
                int(quote["con_id"]),
                quote["symbol"],
                quote["security_type"],
                quote["currency"],
                quote["exchange"],
                str(baseline),
                MAX_QUANTITY,
                str(MAX_NOTIONAL),
                body["created_at"],
                "STARTED",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    print(
        json.dumps(
            {
                "lifecycle_id": lifecycle_id,
                "baseline_quantity": str(baseline),
                "cleanup_required": False,
                "secrets_redacted": True,
            }
        )
    )
    return 0


def _load_lifecycle(path: Path, lifecycle_id: str) -> dict[str, Any]:
    connection = _initialize_lifecycle_ledger(path)
    try:
        row = connection.execute(
            "SELECT lifecycle_id, quote_capsule_id, account_identity_hash, con_id, "
            "symbol, security_type, currency, exchange, baseline_quantity, "
            "max_quantity, max_notional, created_at, state "
            "FROM fixture_lifecycles WHERE lifecycle_id=?",
            (lifecycle_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError("fixture lifecycle does not exist")
    keys = (
        "lifecycle_id",
        "quote_capsule_id",
        "account_identity_hash",
        "con_id",
        "symbol",
        "security_type",
        "currency",
        "exchange",
        "baseline_quantity",
        "max_quantity",
        "max_notional",
        "created_at",
        "state",
    )
    return dict(zip(keys, row, strict=True))


def _record_lifecycle_action(
    path: Path,
    lifecycle_id: str,
    permit: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    lifecycle = _load_lifecycle(path, lifecycle_id)
    if lifecycle["account_identity_hash"] != permit["account_identity_hash"]:
        raise PermissionError("permit and lifecycle account identity mismatch")
    if permit.get("con_id") is not None and int(permit["con_id"]) != lifecycle["con_id"]:
        raise PermissionError("permit and lifecycle contract mismatch")
    connection = _initialize_lifecycle_ledger(path)
    try:
        connection.execute(
            "INSERT INTO fixture_lifecycle_actions VALUES (?, ?, ?, ?, ?)",
            (
                lifecycle_id,
                permit["artifact_id"],
                receipt["artifact_id"],
                receipt["decision"],
                receipt["observed_at"],
            ),
        )
        connection.execute(
            "UPDATE fixture_lifecycle_quotes SET decision=? WHERE lifecycle_id=? AND permit_id=?",
            (receipt["decision"], lifecycle_id, permit["artifact_id"]),
        )
        connection.execute(
            "UPDATE fixture_lifecycles SET state=? WHERE lifecycle_id=?",
            ("CLEANUP_REQUIRED", lifecycle_id),
        )
        connection.commit()
    finally:
        connection.close()


def _validate_lifecycle_action(
    path: Path,
    lifecycle_id: str,
    permit: dict[str, Any],
) -> dict[str, Any]:
    lifecycle = _load_lifecycle(path, lifecycle_id)
    if lifecycle["state"] == "CLEAN":
        raise PermissionError("fixture lifecycle is already clean and closed")
    for field in ("account_identity_hash", "symbol"):
        if lifecycle[field] != permit[field]:
            raise PermissionError(f"permit and lifecycle {field} mismatch")
    if permit.get("con_id") is not None and int(permit["con_id"]) != lifecycle["con_id"]:
        raise PermissionError("permit and lifecycle contract mismatch")
    for field in ("security_type", "currency", "exchange"):
        if permit.get(field) != lifecycle[field]:
            raise PermissionError(f"permit and lifecycle {field} mismatch")
    if int(permit["quantity"]) > int(lifecycle["max_quantity"]):
        raise PermissionError("permit exceeds lifecycle quantity limit")
    if Decimal(str(permit["limit_price"])) * int(permit["quantity"]) > Decimal(
        str(lifecycle["max_notional"])
    ):
        raise PermissionError("permit exceeds lifecycle notional limit")
    return lifecycle


def _reserve_lifecycle_action(
    path: Path,
    lifecycle_id: str,
    permit: dict[str, Any],
    quote: dict[str, Any] | None,
) -> None:
    _validate_lifecycle_action(path, lifecycle_id, permit)
    connection = _initialize_lifecycle_ledger(path)
    try:
        connection.execute(
            "INSERT INTO fixture_lifecycle_quotes VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                lifecycle_id,
                permit["action"],
                permit["artifact_id"],
                quote["artifact_id"] if quote is not None else None,
                quote["observed_at"] if quote is not None else None,
                quote["expires_at"] if quote is not None else None,
                "AUTHORIZED_NOT_YET_SENT",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _lifecycle_action_links(path: Path, lifecycle_id: str) -> list[dict[str, Any]]:
    connection = _initialize_lifecycle_ledger(path)
    try:
        rows = connection.execute(
            "SELECT q.action, q.permit_id, q.quote_capsule_id, q.observed_at, "
            "q.expires_at, q.decision, a.receipt_id "
            "FROM fixture_lifecycle_quotes q LEFT JOIN fixture_lifecycle_actions a "
            "ON q.lifecycle_id=a.lifecycle_id AND q.permit_id=a.permit_id "
            "WHERE q.lifecycle_id=? ORDER BY q.rowid",
            (lifecycle_id,),
        ).fetchall()
    finally:
        connection.close()
    keys = (
        "action",
        "permit_id",
        "quote_capsule_id",
        "quote_observed_at",
        "quote_expires_at",
        "decision",
        "receipt_id",
    )
    return [dict(zip(keys, row, strict=True)) for row in rows]


def _cleanup_is_complete(lifecycle: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    current_quantity = Decimal(str(snapshot["positions"].get(str(lifecycle["con_id"]), "0")))
    baseline_quantity = Decimal(str(lifecycle["baseline_quantity"]))
    return not snapshot["fixture_orders"] and current_quantity == baseline_quantity


def inspect_or_finish_lifecycle(args: argparse.Namespace, *, finish: bool) -> int:
    _require_ibapi()
    lifecycle = _load_lifecycle(args.ledger, args.lifecycle_id)
    config, secrets = load_config()
    if config.execution.broker_write_enabled or config.execution.auto_submit_paper:
        raise ValueError("production execution configuration must remain disabled")
    account = MacOSKeychainSecretProvider().get(LocalSecret.IBKR_ACCOUNT)
    if not account:
        raise ValueError("Paper account is missing from macOS Keychain")
    expected_identity = broker_account_identity(
        account_hash_value=account_hash(account),
        environment=secrets.hanalpha_env,
        host="127.0.0.1",
        port=args.port,
    )
    if expected_identity.identity_hash != lifecycle["account_identity_hash"]:
        raise PermissionError("lifecycle account identity mismatch")
    transport = {"paper_port": args.port, "fixture_client_id": args.client_id}
    app, thread = _connect_verified(transport, account)
    try:
        snapshot = _fixture_state(app, account)
    finally:
        app.disconnect()
        thread.join(timeout=2)
    current_quantity = Decimal(str(snapshot["positions"].get(str(lifecycle["con_id"]), "0")))
    baseline_quantity = Decimal(str(lifecycle["baseline_quantity"]))
    clean = _cleanup_is_complete(lifecycle, snapshot)
    body = to_jsonable_python(
        {
            "schema_version": "e1-cleanup-receipt-v1",
            "artifact_type": "E1_CLEANUP_RECEIPT",
            "lifecycle_id": lifecycle["lifecycle_id"],
            "quote_capsule_id": lifecycle["quote_capsule_id"],
            "account_identity_hash": lifecycle["account_identity_hash"],
            "con_id": lifecycle["con_id"],
            "symbol": lifecycle["symbol"],
            "baseline_quantity": str(baseline_quantity),
            "current_quantity": str(current_quantity),
            "outstanding_fixture_orders": snapshot["fixture_orders"],
            "action_links": _lifecycle_action_links(args.ledger, args.lifecycle_id),
            "observed_at": _utc_now(),
            "decision": "CLEAN" if clean else "CLEANUP_REQUIRED",
            "secrets_redacted": True,
        }
    )
    receipt = {"artifact_id": canonical_hash(body), **body}
    if finish:
        destination = args.output / f"{receipt['artifact_id']}.cleanup.json"
        write_immutable_json(destination, receipt)
        registry = ArtifactRegistry(args.registry)
        try:
            registry.register(
                destination,
                artifact_type=ArtifactType.E1_CLEANUP_RECEIPT,
                status="VERIFIED" if clean else "REJECTED",
                account_hash=str(lifecycle["account_identity_hash"]),
            )
        finally:
            registry.close()
        if clean:
            connection = _initialize_lifecycle_ledger(args.ledger)
            try:
                connection.execute(
                    "UPDATE fixture_lifecycles SET state='CLEAN' WHERE lifecycle_id=?",
                    (args.lifecycle_id,),
                )
                connection.commit()
            finally:
                connection.close()
    print(json.dumps(receipt, sort_keys=True))
    return 0 if clean else 2


def inspect_lifecycle(args: argparse.Namespace) -> int:
    return inspect_or_finish_lifecycle(args, finish=False)


def finish_lifecycle(args: argparse.Namespace) -> int:
    return inspect_or_finish_lifecycle(args, finish=True)


def _receipt(
    permit: dict[str, Any],
    *,
    phase: str,
    decision: str,
    broker_order_id: int | None,
    broker_status: str | None,
    reasons: list[str],
) -> dict[str, Any]:
    body = to_jsonable_python(
        {
            "schema_version": "e1-fixture-receipt-v1",
            "artifact_type": "E1_FIXTURE_RECEIPT",
            "permit_id": permit["artifact_id"],
            "phase": phase,
            "observed_at": _utc_now(),
            "action": permit["action"],
            "account_identity_hash": permit["account_identity_hash"],
            "quote_capsule_id": permit.get("quote_capsule_id"),
            "con_id": permit.get("con_id"),
            "fixture_client_id": permit["fixture_client_id"],
            "symbol": permit["symbol"],
            "quantity": permit["quantity"],
            "order_ref": (
                permit.get("expected_order_ref") or f"E1FIX:{str(permit['artifact_id'])[:40]}"
            ),
            "broker_order_id": broker_order_id,
            "broker_status": broker_status,
            "decision": decision,
            "reasons": sorted(set(reasons)),
            "secrets_redacted": True,
        }
    )
    return {"artifact_id": canonical_hash(body), **body}


def _connect_verified(
    permit: dict[str, Any], account: str
) -> tuple[FixtureClient, threading.Thread]:
    app = FixtureClient()
    app.connect(
        "127.0.0.1",
        int(permit["paper_port"]),
        clientId=int(permit["fixture_client_id"]),
    )
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    if not app.ready.wait(10):
        app.disconnect()
        raise RuntimeError("fixture connection did not become ready")
    deadline = time.monotonic() + 5
    while not app.managed_accounts and time.monotonic() < deadline:
        time.sleep(0.05)
    if app.managed_accounts != (account,):
        app.disconnect()
        raise PermissionError("managed Paper account does not exactly match Keychain")
    return app, thread


def _stock_contract(symbol: str, con_id: int | None = None) -> Contract:
    contract = Contract()
    if con_id is not None:
        contract.conId = con_id
    contract.symbol = symbol
    contract.secType = "STK"
    contract.exchange = "SMART"
    contract.currency = "USD"
    return contract


def _make_order(permit: dict[str, Any], order_id: int, account: str) -> Order:
    order = Order()
    order.orderId = order_id
    order.action = str(permit["side"])
    order.orderType = "LMT"
    order.totalQuantity = int(permit["quantity"])
    order.lmtPrice = float(permit["limit_price"])
    order.tif = "DAY"
    order.transmit = True
    order.account = account
    order.orderRef = (
        str(permit.get("expected_order_ref"))
        if permit.get("expected_order_ref")
        else f"E1FIX:{str(permit['artifact_id'])[:40]}"
    )
    return order


def _execute_action(app: FixtureClient, permit: dict[str, Any], account: str) -> int:
    action = FixtureAction(permit["action"])
    if action in {FixtureAction.MODIFY, FixtureAction.CANCEL}:
        app.reqOpenOrders()
        if not app.open_orders_end.wait(5):
            raise RuntimeError("open-order lookup timed out")
        order_id = int(permit["broker_order_id"])
        found = app.open_orders.get(order_id)
        if found is None:
            raise RuntimeError("bound fixture order is not open")
        contract, existing = found
        if str(getattr(existing, "orderRef", "")) != permit["expected_order_ref"]:
            raise PermissionError("fixture order-ref binding mismatch")
        if str(getattr(contract, "secType", "")) != "STK":
            raise PermissionError("fixture refuses non-stock instruments")
        if str(getattr(contract, "symbol", "")).upper() != str(permit["symbol"]):
            raise PermissionError("fixture contract symbol binding mismatch")
        app.open_orders.pop(order_id, None)
        app.status_by_order.pop(order_id, None)
        app.order_update.clear()
        if action is FixtureAction.CANCEL:
            app.cancelOrder(order_id, OrderCancel())
            return order_id
        if int(getattr(contract, "conId", 0)) != int(permit["con_id"]):
            raise PermissionError("fixture contract conId binding mismatch")
        if str(getattr(existing, "action", "")) != str(permit["side"]):
            raise PermissionError("fixture modify cannot flip order side")
        if str(getattr(existing, "orderType", "")) != "LMT":
            raise PermissionError("fixture modify cannot change order type")
        if Decimal(str(getattr(existing, "totalQuantity", "0"))) != Decimal("1"):
            raise PermissionError("fixture modify cannot change order quantity")
        if str(getattr(existing, "account", "")) != account:
            raise PermissionError("fixture modify account binding mismatch")
        replacement = _make_order(permit, order_id, account)
        app.placeOrder(order_id, contract, replacement)
        return order_id
    if action is FixtureAction.CLOSE_POSITION:
        app.reqPositions()
        if not app.positions_end.wait(5):
            raise RuntimeError("position lookup timed out")
        if app.positions.get(str(permit["con_id"])) != Decimal("1"):
            raise PermissionError("fixture close requires exactly one long share")
    if app.next_order_id is None:
        raise RuntimeError("broker order ID unavailable")
    order_id = app.next_order_id
    app.order_update.clear()
    app.placeOrder(
        order_id,
        _stock_contract(str(permit["symbol"]), int(permit["con_id"])),
        _make_order(permit, order_id, account),
    )
    return order_id


def _classify_outcome(
    action: FixtureAction,
    *,
    status: str | None,
    open_order_seen: bool,
    errors: list[tuple[int, str]],
) -> str:
    actionable_errors = [
        (code, message) for code, message in errors if code not in INFORMATIONAL_IBKR_CODES
    ]
    if actionable_errors or status in {"Inactive", "Rejected"}:
        return "BROKER_REJECTED"
    if status == "Filled":
        return "BROKER_FILLED"
    if status in {"Cancelled", "ApiCancelled"}:
        return "BROKER_CANCELLED"
    if status in {"Submitted", "PreSubmitted"} and open_order_seen:
        return "BROKER_ACCEPTED_OPEN"
    return "OUTCOME_UNKNOWN"


def execute_permit(args: argparse.Namespace) -> int:
    _require_ibapi()
    permit = _load_permit(args.permit)
    quote = _verify_permit_quote_binding(permit, args.quote_root)
    _validate_lifecycle_action(
        args.lifecycle_ledger,
        args.lifecycle_id,
        permit,
    )
    config, secrets = load_config()
    if config.execution.broker_write_enabled or config.execution.auto_submit_paper:
        raise ValueError("production execution configuration must remain disabled")
    cost = external_cost_receipt(
        provider=ExternalProvider.IBKR,
        action=ExternalAction.PAPER_FIXTURE,
        request_count=1,
        max_new_cost=Decimal(str(args.max_new_cost)),
        existing_entitlement=True,
        current_plan="PAPER_ACCOUNT",
    )
    cost_path = args.cost_output / f"{cost['artifact_id']}.json"
    write_immutable_json(cost_path, cost)
    cost_registry = ArtifactRegistry(args.registry)
    try:
        cost_registry.register(
            cost_path,
            artifact_type=ArtifactType.EXTERNAL_COST_RECEIPT,
            status="VERIFIED" if cost["decision"] == "ALLOW" else "REJECTED",
        )
    finally:
        cost_registry.close()
    if cost["decision"] != "ALLOW":
        raise PermissionError("external Paper fixture cost is not authorized")
    account = MacOSKeychainSecretProvider().get(LocalSecret.IBKR_ACCOUNT)
    if not account:
        raise ValueError("Paper account is missing from macOS Keychain")
    expected_identity = broker_account_identity(
        account_hash_value=account_hash(account),
        environment=secrets.hanalpha_env,
        host="127.0.0.1",
        port=int(permit["paper_port"]),
    )
    if expected_identity.identity_hash != permit["account_identity_hash"]:
        raise PermissionError("fixture permit account identity mismatch")
    app, thread = _connect_verified(permit, account)
    receipts = args.output
    pre = _receipt(
        permit,
        phase="PRE_WRITE",
        decision="AUTHORIZED_NOT_YET_SENT",
        broker_order_id=permit.get("broker_order_id"),
        broker_status=None,
        reasons=[],
    )
    pre_path = receipts / f"{pre['artifact_id']}.fixture.json"
    write_immutable_json(pre_path, pre)
    registry = ArtifactRegistry(args.registry)
    try:
        registry.register(
            pre_path,
            artifact_type=ArtifactType.E1_FIXTURE_RECEIPT,
            status="CAPTURED",
            account_hash=str(permit["account_identity_hash"]),
        )
    finally:
        registry.close()
    broker_order_id: int | None = None
    reasons: list[str] = []
    decision = "OUTCOME_UNKNOWN"
    status: str | None = None
    try:
        _reserve_lifecycle_action(
            args.lifecycle_ledger,
            args.lifecycle_id,
            permit,
            quote,
        )
        _consume_permit_once(args.ledger, str(permit["artifact_id"]))
        broker_order_id = _execute_action(app, permit, account)
        app.order_update.wait(5)
        status = app.status_by_order.get(broker_order_id)
        decision = _classify_outcome(
            FixtureAction(str(permit["action"])),
            status=status,
            open_order_seen=broker_order_id in app.open_orders,
            errors=app.errors,
        )
        reasons.extend(
            f"IBKR_{code}" for code, _ in app.errors if code not in INFORMATIONAL_IBKR_CODES
        )
    except sqlite3.IntegrityError:
        decision = "BROKER_REJECTED"
        reasons.append("PERMIT_ALREADY_CONSUMED")
    except BaseException as exc:
        reasons.append(type(exc).__name__)
    finally:
        app.disconnect()
        thread.join(timeout=2)
    post = _receipt(
        permit,
        phase="POST_WRITE",
        decision=decision,
        broker_order_id=broker_order_id,
        broker_status=status,
        reasons=reasons,
    )
    destination = receipts / f"{post['artifact_id']}.fixture.json"
    write_immutable_json(destination, post)
    registry = ArtifactRegistry(args.registry)
    try:
        registry.register(
            destination,
            artifact_type=ArtifactType.E1_FIXTURE_RECEIPT,
            status=(
                "VERIFIED"
                if decision in {"BROKER_ACCEPTED_OPEN", "BROKER_FILLED", "BROKER_CANCELLED"}
                else "REJECTED"
            ),
            account_hash=str(permit["account_identity_hash"]),
        )
    finally:
        registry.close()
    if args.lifecycle_id is not None:
        _record_lifecycle_action(
            args.lifecycle_ledger,
            args.lifecycle_id,
            permit,
            post,
        )
    print(
        json.dumps(
            {
                "decision": decision,
                "receipt": str(destination),
                "secrets_redacted": True,
            }
        )
    )
    successful_for_action = {
        FixtureAction.PLACE: {"BROKER_ACCEPTED_OPEN", "BROKER_FILLED"},
        FixtureAction.MODIFY: {"BROKER_ACCEPTED_OPEN", "BROKER_FILLED"},
        FixtureAction.CANCEL: {"BROKER_CANCELLED"},
        FixtureAction.CLOSE_POSITION: {"BROKER_FILLED"},
    }[FixtureAction(str(permit["action"]))]
    return 0 if decision in successful_for_action else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    quote = subparsers.add_parser("capture-quote")
    quote.add_argument("--symbol", required=True)
    quote.add_argument("--port", type=int, required=True)
    quote.add_argument("--client-id", type=int, required=True)
    quote.add_argument("--attest-paper", action="store_true")
    quote.add_argument(
        "--feed-scope",
        choices=sorted(FEED_SCOPES),
        default="UNKNOWN",
    )
    quote.add_argument("--existing-entitlement-attested", action="store_true")
    quote.add_argument("--max-new-cost", default="0")
    quote.add_argument("--output", type=Path, default=Path(".state/e1/fixture/quotes"))
    quote.add_argument(
        "--cost-output",
        type=Path,
        default=Path(".state/external-costs"),
    )
    quote.add_argument(
        "--registry",
        type=Path,
        default=Path(".state/evidence-artifacts.sqlite3"),
    )
    quote.set_defaults(handler=capture_quote)
    create = subparsers.add_parser("create-permit")
    create.add_argument("--action", choices=[item.value for item in FixtureAction], required=True)
    create.add_argument("--symbol", required=True)
    create.add_argument("--quantity", type=int, default=1)
    create.add_argument("--limit-price", required=True)
    create.add_argument("--side", choices=["BUY", "SELL"], default="BUY")
    create.add_argument("--quote-capsule", type=Path)
    create.add_argument("--port", type=int, required=True)
    create.add_argument("--client-id", type=int, required=True)
    create.add_argument("--broker-order-id", type=int)
    create.add_argument("--expected-order-ref")
    create.add_argument("--attest-paper", action="store_true")
    create.add_argument("--output", type=Path, default=Path(".state/e1/fixture/permits"))
    create.add_argument(
        "--registry",
        type=Path,
        default=Path(".state/evidence-artifacts.sqlite3"),
    )
    create.set_defaults(handler=create_permit)
    execute = subparsers.add_parser("execute")
    execute.add_argument("--permit", type=Path, required=True)
    execute.add_argument(
        "--quote-root",
        type=Path,
        default=Path(".state/e1/fixture/quotes"),
    )
    execute.add_argument("--ledger", type=Path, default=Path(".state/e1/fixture/consumed.sqlite3"))
    execute.add_argument("--lifecycle-id", required=True)
    execute.add_argument(
        "--lifecycle-ledger",
        type=Path,
        default=Path(".state/e1/fixture/lifecycles.sqlite3"),
    )
    execute.add_argument("--output", type=Path, default=Path(".state/e1/fixture/receipts"))
    execute.add_argument("--max-new-cost", default="0")
    execute.add_argument(
        "--cost-output",
        type=Path,
        default=Path(".state/external-costs"),
    )
    execute.add_argument(
        "--registry",
        type=Path,
        default=Path(".state/evidence-artifacts.sqlite3"),
    )
    execute.set_defaults(handler=execute_permit)
    start = subparsers.add_parser("start-lifecycle")
    start.add_argument("--quote-capsule", type=Path, required=True)
    start.add_argument("--port", type=int, required=True)
    start.add_argument("--client-id", type=int, required=True)
    start.add_argument(
        "--ledger",
        type=Path,
        default=Path(".state/e1/fixture/lifecycles.sqlite3"),
    )
    start.set_defaults(handler=start_lifecycle)
    for command, handler in (
        ("status-lifecycle", inspect_lifecycle),
        ("finish-lifecycle", finish_lifecycle),
    ):
        lifecycle = subparsers.add_parser(command)
        lifecycle.add_argument("--lifecycle-id", required=True)
        lifecycle.add_argument("--port", type=int, required=True)
        lifecycle.add_argument("--client-id", type=int, required=True)
        lifecycle.add_argument(
            "--ledger",
            type=Path,
            default=Path(".state/e1/fixture/lifecycles.sqlite3"),
        )
        lifecycle.add_argument(
            "--output",
            type=Path,
            default=Path(".state/e1/fixture/cleanup"),
        )
        lifecycle.add_argument(
            "--registry",
            type=Path,
            default=Path(".state/evidence-artifacts.sqlite3"),
        )
        lifecycle.set_defaults(handler=handler)
    return parser


def main() -> int:
    try:
        args = _parser().parse_args()
        return int(args.handler(args))
    except (OSError, RuntimeError, ValueError, PermissionError, sqlite3.Error) as exc:
        reason_code = SAFE_FAILURE_CODES.get(str(exc), type(exc).__name__)
        print(
            json.dumps(
                {
                    "decision": "REJECTED",
                    "reason": reason_code,
                    "secrets_redacted": True,
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
