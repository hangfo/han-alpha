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

from pydantic_core import to_jsonable_python

from hanalpha.config import load_config
from hanalpha.execution.ibkr_observer import account_hash, broker_account_identity
from hanalpha.ops.artifact_registry import ArtifactRegistry, ArtifactType
from hanalpha.ops.artifacts import write_immutable_json
from hanalpha.ops.secrets import LocalSecret, MacOSKeychainSecretProvider
from hanalpha.simulation.events import canonical_hash

try:
    from ibapi.client import EClient
    from ibapi.contract import Contract
    from ibapi.order import Order
    from ibapi.order_cancel import OrderCancel
    from ibapi.wrapper import EWrapper
except ImportError as exc:  # pragma: no cover - environment preflight
    raise SystemExit("official IBKR ibapi is not installed") from exc


PAPER_PORTS = frozenset({4002, 7497})
FIXTURE_CLIENT_IDS = range(9100, 9200)
MAX_QUANTITY = 1
MAX_NOTIONAL = Decimal("1000")
PERMIT_TTL_MINUTES = 15


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

    def error(self, reqId: int, *args: Any) -> None:
        if len(args) >= 2 and isinstance(args[-2], int):
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
    body = {
        "schema_version": "e1-fixture-permit-v1",
        "artifact_type": "E1_FIXTURE_PERMIT",
        "action": action,
        "account_identity_hash": account_identity_hash,
        "host": "127.0.0.1",
        "paper_port": args.port,
        "fixture_client_id": args.client_id,
        "symbol": args.symbol.upper(),
        "security_type": "STK",
        "side": "SELL" if action is FixtureAction.CLOSE_POSITION else "BUY",
        "quantity": args.quantity,
        "limit_price": str(price),
        "max_notional": str(MAX_NOTIONAL),
        "broker_order_id": args.broker_order_id,
        "expected_order_ref": args.expected_order_ref,
        "issued_at": now,
        "expires_at": now + timedelta(minutes=PERMIT_TTL_MINUTES),
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
    if permit.get("schema_version") != "e1-fixture-permit-v1":
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
    if Decimal(str(permit["limit_price"])) > MAX_NOTIONAL:
        raise ValueError("fixture notional ceiling violated")
    return permit


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


def _stock_contract(symbol: str) -> Contract:
    contract = Contract()
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
        app.open_orders.pop(order_id, None)
        app.status_by_order.pop(order_id, None)
        app.order_update.clear()
        if action is FixtureAction.CANCEL:
            app.cancelOrder(order_id, OrderCancel())
            return order_id
        replacement = _make_order(permit, order_id, account)
        app.placeOrder(order_id, contract, replacement)
        return order_id
    if action is FixtureAction.CLOSE_POSITION:
        app.reqPositions()
        if not app.positions_end.wait(5):
            raise RuntimeError("position lookup timed out")
        if app.positions.get(str(permit["symbol"])) != Decimal("1"):
            raise PermissionError("fixture close requires exactly one long share")
    if app.next_order_id is None:
        raise RuntimeError("broker order ID unavailable")
    order_id = app.next_order_id
    app.order_update.clear()
    app.placeOrder(
        order_id,
        _stock_contract(str(permit["symbol"])),
        _make_order(permit, order_id, account),
    )
    return order_id


def execute_permit(args: argparse.Namespace) -> int:
    permit = _load_permit(args.permit)
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
        _consume_permit_once(args.ledger, str(permit["artifact_id"]))
        broker_order_id = _execute_action(app, permit, account)
        app.order_update.wait(5)
        status = app.status_by_order.get(broker_order_id)
        decision = (
            "BROKER_ACKNOWLEDGED"
            if status or broker_order_id in app.open_orders
            else "OUTCOME_UNKNOWN"
        )
        reasons.extend(f"IBKR_{code}" for code, _ in app.errors)
    except sqlite3.IntegrityError:
        decision = "REJECTED"
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
            status=("VERIFIED" if decision == "BROKER_ACKNOWLEDGED" else "REJECTED"),
            account_hash=str(permit["account_identity_hash"]),
        )
    finally:
        registry.close()
    print(
        json.dumps(
            {
                "decision": decision,
                "receipt": str(destination),
                "secrets_redacted": True,
            }
        )
    )
    return 0 if decision == "BROKER_ACKNOWLEDGED" else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create-permit")
    create.add_argument("--action", choices=[item.value for item in FixtureAction], required=True)
    create.add_argument("--symbol", required=True)
    create.add_argument("--quantity", type=int, default=1)
    create.add_argument("--limit-price", required=True)
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
    execute.add_argument("--ledger", type=Path, default=Path(".state/e1/fixture/consumed.sqlite3"))
    execute.add_argument("--output", type=Path, default=Path(".state/e1/fixture/receipts"))
    execute.add_argument(
        "--registry",
        type=Path,
        default=Path(".state/evidence-artifacts.sqlite3"),
    )
    execute.set_defaults(handler=execute_permit)
    return parser


def main() -> int:
    try:
        args = _parser().parse_args()
        return int(args.handler(args))
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        print(
            json.dumps(
                {
                    "decision": "REJECTED",
                    "reason": type(exc).__name__,
                    "secrets_redacted": True,
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
