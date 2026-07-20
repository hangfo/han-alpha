from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field

from hanalpha.simulation.events import canonical_hash


def account_hash(account: str) -> str:
    return canonical_hash({"ibkr_account": account})


class IBKRFactType(StrEnum):
    CONNECTION = "CONNECTION"
    SERVER_TIME = "SERVER_TIME"
    MANAGED_ACCOUNTS = "MANAGED_ACCOUNTS"
    NEXT_VALID_ID = "NEXT_VALID_ID"
    REQUEST_START = "REQUEST_START"
    REQUEST_CANCEL = "REQUEST_CANCEL"
    ACCOUNT_VALUE = "ACCOUNT_VALUE"
    ACCOUNT_END = "ACCOUNT_END"
    OPEN_ORDER = "OPEN_ORDER"
    OPEN_ORDER_END = "OPEN_ORDER_END"
    COMPLETED_ORDER = "COMPLETED_ORDER"
    COMPLETED_ORDER_END = "COMPLETED_ORDER_END"
    ORDER_STATUS = "ORDER_STATUS"
    POSITION = "POSITION"
    POSITION_END = "POSITION_END"
    EXECUTION = "EXECUTION"
    EXECUTION_END = "EXECUTION_END"
    COMMISSION = "COMMISSION"
    ERROR = "ERROR"
    DISCONNECT = "DISCONNECT"
    DRAIN_WATERMARK = "DRAIN_WATERMARK"


class IBKRFactDraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    fact_type: IBKRFactType
    identity_key: str
    payload: dict[str, Any]
    received_at: datetime


class IBKRFact(IBKRFactDraft):
    fact_id: str


class ObserverRequestBarrier(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    account_request_id: int
    execution_request_id: int
    position_epoch: str
    open_orders_epoch: str
    execution_history_start: datetime
    execution_history_end: datetime
    open_order_query: str = "ALL_OPEN_ORDERS"
    execution_query_scope: str = "BROKER_DEFAULT_CURRENT_DAY"
    completed_orders_requested: bool = False


class VisibilityScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    configured_account_hash: str
    managed_accounts_count: int = Field(ge=0)
    configured_account_seen: bool
    client_id: int
    master_client: bool
    manual_tws_orders_visible: bool
    other_api_clients_visible: bool
    execution_history_start: datetime
    execution_history_end: datetime
    execution_query_scope: str
    open_order_query: str
    scope_hash: str
    scope_complete: bool


class SnapshotCompletenessCertificate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    certificate_id: str
    session_id: str
    as_of: datetime
    connected: bool
    next_valid_id_seen: bool
    managed_accounts_seen: bool
    server_time_seen: bool
    account_end_seen: bool
    open_order_end_seen: bool
    completed_order_end_seen: bool
    position_end_seen: bool
    execution_end_seen: bool
    request_ids_match: bool
    configured_account_seen: bool
    required_account_tags_seen: bool
    base_currency: str
    base_currency_seen: bool
    account_scope_unambiguous: bool
    queue_drained: bool
    queue_depth: int = Field(ge=0)
    writer_error: str | None = None
    unmatched_commission_count: int = Field(ge=0)
    executions_missing_commission_count: int = Field(ge=0)
    final_watermark: int = Field(ge=0)
    visibility: VisibilityScope
    account_hash: str
    orders_hash: str
    positions_hash: str
    executions_hash: str
    commissions_hash: str
    protection_hash: str
    semantic_hash: str
    order_snapshot_complete: bool
    position_snapshot_complete: bool
    execution_snapshot_complete: bool
    cash_snapshot_complete: bool
    critical_errors: tuple[int, ...] = ()
    disconnected: bool = False
    complete: bool


class IBKRReadModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    orders: dict[str, dict[str, Any]]
    executions: dict[str, dict[str, Any]]
    execution_corrections: dict[str, tuple[str, ...]]
    effective_executions: dict[str, dict[str, Any]]
    commissions: dict[str, dict[str, Any]]
    effective_commissions: dict[str, dict[str, Any]]
    positions: dict[str, dict[str, Any]]
    account_values: dict[str, dict[str, Any]]
    unmatched_commission_exec_ids: tuple[str, ...]
    executions_missing_commission_exec_ids: tuple[str, ...]
    corrected_execution_roots: tuple[str, ...]
    reducer_conflicts: tuple[str, ...]


class FactSink(Protocol):
    def write_draft(self, draft: IBKRFactDraft) -> None: ...


class IBKRFactStore:
    """Append-only callback tape. Each instance keeps its SQLite connection in one thread."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS ibkr_sessions (
              session_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, client_id INTEGER NOT NULL,
              host TEXT NOT NULL, port INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ibkr_facts (
              fact_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, fact_type TEXT NOT NULL,
              identity_key TEXT NOT NULL, payload_json TEXT NOT NULL, received_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ibkr_facts_session
              ON ibkr_facts(session_id, received_at, fact_id);
            CREATE TABLE IF NOT EXISTS ibkr_completeness_certificates (
              certificate_id TEXT PRIMARY KEY, session_id TEXT UNIQUE NOT NULL,
              certificate_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            """
        )

    def start_session(
        self, *, host: str, port: int, client_id: int, at: datetime
    ) -> str:
        session_id = canonical_hash(
            {"host": host, "port": port, "client_id": client_id, "started_at": at}
        )
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO ibkr_sessions VALUES (?, ?, ?, ?, ?)",
                (session_id, at.isoformat(), client_id, host, port),
            )
        return session_id

    def write_draft(self, draft: IBKRFactDraft) -> None:
        self.append(
            session_id=draft.session_id,
            fact_type=draft.fact_type,
            identity_key=draft.identity_key,
            payload=draft.payload,
            received_at=draft.received_at,
        )

    def append(
        self,
        *,
        session_id: str,
        fact_type: IBKRFactType,
        identity_key: str,
        payload: dict[str, Any],
        received_at: datetime,
    ) -> IBKRFact:
        normalized = json.loads(json.dumps(payload, sort_keys=True, default=str))
        fact_id = canonical_hash(
            {
                "session_id": session_id,
                "fact_type": fact_type,
                "identity_key": identity_key,
                "payload": normalized,
            }
        )
        fact = IBKRFact(
            fact_id=fact_id,
            session_id=session_id,
            fact_type=fact_type,
            identity_key=identity_key,
            payload=normalized,
            received_at=received_at,
        )
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO ibkr_facts VALUES (?, ?, ?, ?, ?, ?)",
                (
                    fact.fact_id,
                    session_id,
                    fact_type.value,
                    identity_key,
                    json.dumps(normalized, sort_keys=True, separators=(",", ":")),
                    received_at.isoformat(),
                ),
            )
        return fact

    def facts(self, session_id: str) -> tuple[IBKRFact, ...]:
        return tuple(
            IBKRFact(
                fact_id=row["fact_id"],
                session_id=row["session_id"],
                fact_type=IBKRFactType(row["fact_type"]),
                identity_key=row["identity_key"],
                payload=json.loads(row["payload_json"]),
                received_at=datetime.fromisoformat(row["received_at"]),
            )
            for row in self.connection.execute(
                "SELECT * FROM ibkr_facts WHERE session_id=? ORDER BY received_at, fact_id",
                (session_id,),
            )
        )

    def save_certificate(self, certificate: SnapshotCompletenessCertificate) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO ibkr_completeness_certificates VALUES (?, ?, ?, ?)",
                (
                    certificate.certificate_id,
                    certificate.session_id,
                    certificate.model_dump_json(),
                    certificate.as_of.isoformat(),
                ),
            )

    def latest_certificate(self) -> SnapshotCompletenessCertificate | None:
        row = self.connection.execute(
            "SELECT certificate_json FROM ibkr_completeness_certificates ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return SnapshotCompletenessCertificate.model_validate_json(row[0]) if row else None

    def close(self) -> None:
        self.connection.close()

    def fact_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM ibkr_facts").fetchone()[0])


class IBKRFactBridge:
    """Non-blocking callback queue with one SQLite writer and an explicit drain watermark."""

    def __init__(
        self,
        path: Path,
        *,
        max_queue: int = 10_000,
        writer_factory: Callable[[Path], IBKRFactStore] = IBKRFactStore,
    ) -> None:
        self.path = path
        self._queue: queue.Queue[IBKRFactDraft | None] = queue.Queue(maxsize=max_queue)
        self._writer_factory = writer_factory
        self._thread = threading.Thread(target=self._run, name="ibkr-fact-writer", daemon=True)
        self._lock = threading.Lock()
        self._accepted = 0
        self._written = 0
        self._dropped = 0
        self._last_enqueue = time.monotonic()
        self._writer_error: str | None = None
        self._closed = False
        self._thread.start()

    @property
    def depth(self) -> int:
        return self._queue.qsize()

    @property
    def accepted(self) -> int:
        with self._lock:
            return self._accepted

    @property
    def written(self) -> int:
        with self._lock:
            return self._written

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    @property
    def writer_error(self) -> str | None:
        with self._lock:
            return self._writer_error

    def write_draft(self, draft: IBKRFactDraft) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(draft)
        except queue.Full:
            with self._lock:
                self._dropped += 1
                self._writer_error = "fact_queue_overflow"
            return
        with self._lock:
            self._accepted += 1
            self._last_enqueue = time.monotonic()

    def drain(self, *, timeout: float = 5, quiet_period: float = 0.1) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                quiet = time.monotonic() - self._last_enqueue >= quiet_period
                caught_up = self._written == self._accepted
                failed = self._writer_error is not None or self._dropped > 0
            if quiet and caught_up and self._queue.empty():
                return not failed
            time.sleep(0.005)
        return False

    def close(self, *, timeout: float = 5) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.put(None, timeout=timeout)
        self._thread.join(timeout)
        if self._thread.is_alive():
            with self._lock:
                self._writer_error = "fact_writer_join_timeout"

    def _run(self) -> None:
        store: IBKRFactStore | None = None
        try:
            store = self._writer_factory(self.path)
            while True:
                draft = self._queue.get()
                try:
                    if draft is None:
                        return
                    store.write_draft(draft)
                    with self._lock:
                        self._written += 1
                finally:
                    self._queue.task_done()
        except BaseException as exc:
            with self._lock:
                self._writer_error = f"{type(exc).__name__}:{exc}"
        finally:
            if store is not None:
                store.close()


class IBKRCallbackCollector:
    """Callback sink that only creates fact drafts; it never touches SQLite on callback threads."""

    _CRITICAL_ERROR_CODES: ClassVar[set[int]] = {502, 503, 504, 1100, 1300}
    _REQUIRED_TAGS: ClassVar[set[str]] = {
        "NetLiquidation",
        "TotalCashValue",
        "SettledCash",
        "BuyingPower",
        "AccruedCash",
    }

    def __init__(
        self,
        sink: FactSink,
        session_id: str,
        *,
        barrier: ObserverRequestBarrier | None = None,
        configured_account: str | None = None,
        base_currency: str = "USD",
        client_id: int = 0,
        master_client: bool = False,
    ) -> None:
        self.sink = sink
        self.session_id = session_id
        self.barrier = barrier
        self.configured_account_hash = account_hash(configured_account or "UNCONFIGURED")
        self.base_currency = base_currency
        self.client_id = client_id
        self.master_client = master_client

    def record(
        self,
        fact_type: IBKRFactType,
        payload: dict[str, Any] | None = None,
        *,
        identity_key: str | None = None,
        at: datetime | None = None,
    ) -> None:
        payload = payload or {}
        self.sink.write_draft(
            IBKRFactDraft(
                session_id=self.session_id,
                fact_type=fact_type,
                identity_key=identity_key or canonical_hash(payload),
                payload=payload,
                received_at=at or datetime.now(UTC),
            )
        )

    def order_status(self, order_id: int, payload: dict[str, Any], *, at: datetime) -> None:
        identity = self.order_identity({"order_id": order_id, **payload})
        self.record(
            IBKRFactType.ORDER_STATUS,
            {"order_id": order_id, **payload},
            identity_key=f"{identity}:{canonical_hash(payload)}",
            at=at,
        )

    def execution(self, exec_id: str, payload: dict[str, Any], *, at: datetime) -> None:
        self.record(
            IBKRFactType.EXECUTION,
            {"exec_id": exec_id, **payload},
            identity_key=exec_id,
            at=at,
        )

    def commission(self, exec_id: str, payload: dict[str, Any], *, at: datetime) -> None:
        self.record(
            IBKRFactType.COMMISSION,
            {"exec_id": exec_id, **payload},
            identity_key=exec_id,
            at=at,
        )

    def order_identity(self, payload: dict[str, Any]) -> str:
        perm_id = int(payload.get("perm_id", 0) or 0)
        order_ref = str(payload.get("order_ref", "") or "")
        if perm_id:
            return f"perm:{perm_id}"
        if order_ref:
            return f"ref:{order_ref}"
        return (
            f"session:{self.session_id}:client:{int(payload.get('client_id', self.client_id) or 0)}:"
            f"order:{int(payload['order_id'])}"
        )

    def certificate(
        self,
        store: IBKRFactStore,
        *,
        at: datetime,
        queue_drained: bool,
        queue_depth: int = 0,
        writer_error: str | None = None,
        final_watermark: int = 0,
    ) -> SnapshotCompletenessCertificate:
        facts = store.facts(self.session_id)
        kinds = {fact.fact_type for fact in facts}
        model = IBKRFactReducer.reduce(facts) if facts else None
        errors = tuple(
            sorted(
                {
                    int(fact.payload["code"])
                    for fact in facts
                    if fact.fact_type == IBKRFactType.ERROR
                    and int(fact.payload.get("code", -1)) in self._CRITICAL_ERROR_CODES
                }
            )
        )
        barrier = self.barrier
        account_end = any(
            fact.fact_type == IBKRFactType.ACCOUNT_END
            and barrier is not None
            and int(fact.payload.get("request_id", -1)) == barrier.account_request_id
            for fact in facts
        )
        execution_end = any(
            fact.fact_type == IBKRFactType.EXECUTION_END
            and barrier is not None
            and int(fact.payload.get("request_id", -1)) == barrier.execution_request_id
            for fact in facts
        )
        position_end = any(
            fact.fact_type == IBKRFactType.POSITION_END
            and barrier is not None
            and fact.payload.get("epoch") == barrier.position_epoch
            for fact in facts
        )
        open_end = any(
            fact.fact_type == IBKRFactType.OPEN_ORDER_END
            and barrier is not None
            and fact.payload.get("epoch") == barrier.open_orders_epoch
            for fact in facts
        )
        completed_end = any(
            fact.fact_type == IBKRFactType.COMPLETED_ORDER_END for fact in facts
        )
        account_facts = [
            fact
            for fact in facts
            if fact.fact_type == IBKRFactType.ACCOUNT_VALUE
            and fact.payload.get("account_hash") == self.configured_account_hash
            and barrier is not None
            and int(fact.payload.get("request_id", -1)) == barrier.account_request_id
        ]
        tags = {str(fact.payload.get("tag")) for fact in account_facts}
        currencies = {str(fact.payload.get("currency")) for fact in account_facts}
        managed = [fact for fact in facts if fact.fact_type == IBKRFactType.MANAGED_ACCOUNTS]
        managed_count = max((int(fact.payload.get("account_count", 0)) for fact in managed), default=0)
        configured_seen = any(
            self.configured_account_hash in tuple(fact.payload.get("account_hashes", ()))
            for fact in managed
        )
        request_ids_match = bool(barrier and account_end and execution_end and position_end and open_end)
        required_tags = tags >= self._REQUIRED_TAGS
        base_currency_seen = self.base_currency in currencies
        unmatched = len(model.unmatched_commission_exec_ids) if model else 0
        missing_commission = len(model.executions_missing_commission_exec_ids) if model else 0
        scope_body = {
            "configured_account_hash": self.configured_account_hash,
            "managed_accounts_count": managed_count,
            "configured_account_seen": configured_seen,
            "client_id": self.client_id,
            "master_client": self.master_client,
            "manual_tws_orders_visible": self.client_id == 0 or self.master_client,
            "other_api_clients_visible": self.master_client,
            "execution_history_start": barrier.execution_history_start if barrier else at,
            "execution_history_end": barrier.execution_history_end if barrier else at,
            "execution_query_scope": (
                barrier.execution_query_scope if barrier else "UNDECLARED"
            ),
            "open_order_query": barrier.open_order_query if barrier else "UNDECLARED",
        }
        scope_complete = configured_seen and managed_count == 1 and barrier is not None
        visibility = VisibilityScope.model_validate(
            {
                **scope_body,
                "scope_hash": canonical_hash(scope_body),
                "scope_complete": scope_complete,
            }
        )
        flags = {
            "connected": IBKRFactType.CONNECTION in kinds,
            "next_valid_id_seen": IBKRFactType.NEXT_VALID_ID in kinds,
            "managed_accounts_seen": bool(managed),
            "server_time_seen": IBKRFactType.SERVER_TIME in kinds,
            "account_end_seen": account_end,
            "open_order_end_seen": open_end,
            "completed_order_end_seen": (
                completed_end if barrier and barrier.completed_orders_requested else True
            ),
            "position_end_seen": position_end,
            "execution_end_seen": execution_end,
        }
        disconnected = IBKRFactType.DISCONNECT in kinds
        semantic = {
            "flags": flags,
            "visibility_scope_hash": visibility.scope_hash,
            "base_currency": self.base_currency,
        }
        account_values = (
            {
                key: value
                for key, value in self._semantic_payload(model.account_values).items()
                if value.get("account_hash") == self.configured_account_hash
            }
            if model
            else {}
        )
        orders = self._semantic_payload(model.orders) if model else {}
        positions = self._semantic_payload(model.positions) if model else {}
        executions = self._semantic_payload(model.effective_executions) if model else {}
        commissions = self._semantic_payload(model.effective_commissions) if model else {}
        protection = {
            key: value
            for key, value in orders.items()
            if int(value.get("parent_id", 0) or 0) != 0
        }
        component_hashes = {
            "account_hash": canonical_hash(account_values),
            "orders_hash": canonical_hash(orders),
            "positions_hash": canonical_hash(positions),
            "executions_hash": canonical_hash(executions),
            "commissions_hash": canonical_hash(commissions),
            "protection_hash": canonical_hash(protection),
        }
        semantic.update(component_hashes)
        order_complete = (
            flags["open_order_end_seen"]
            and flags["completed_order_end_seen"]
            and queue_drained
            and writer_error is None
        )
        position_complete = flags["position_end_seen"] and queue_drained and writer_error is None
        execution_complete = flags["execution_end_seen"] and queue_drained and writer_error is None
        cash_complete = (
            flags["account_end_seen"]
            and required_tags
            and base_currency_seen
            and missing_commission == 0
            and unmatched == 0
            and queue_drained
            and writer_error is None
        )
        complete = (
            all(flags.values())
            and request_ids_match
            and configured_seen
            and required_tags
            and base_currency_seen
            and scope_complete
            and queue_drained
            and queue_depth == 0
            and writer_error is None
            and not errors
            and not disconnected
        )
        body = {
            "session_id": self.session_id,
            "as_of": at,
            **flags,
            "request_ids_match": request_ids_match,
            "configured_account_seen": configured_seen,
            "required_account_tags_seen": required_tags,
            "base_currency": self.base_currency,
            "base_currency_seen": base_currency_seen,
            "account_scope_unambiguous": scope_complete,
            "queue_drained": queue_drained,
            "queue_depth": queue_depth,
            "writer_error": writer_error,
            "unmatched_commission_count": unmatched,
            "executions_missing_commission_count": missing_commission,
            "final_watermark": final_watermark,
            "visibility": visibility,
            **component_hashes,
            "semantic_hash": canonical_hash(semantic),
            "order_snapshot_complete": order_complete,
            "position_snapshot_complete": position_complete,
            "execution_snapshot_complete": execution_complete,
            "cash_snapshot_complete": cash_complete,
            "critical_errors": errors,
            "disconnected": disconnected,
            "complete": complete,
        }
        certificate = SnapshotCompletenessCertificate.model_validate(
            {"certificate_id": canonical_hash(body), **body}
        )
        store.save_certificate(certificate)
        return certificate

    @classmethod
    def _semantic_payload(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: cls._semantic_payload(item)
                for key, item in value.items()
                if not str(key).startswith("_")
            }
        if isinstance(value, list | tuple):
            return [cls._semantic_payload(item) for item in value]
        return value


class IBKRFactReducer:
    """Field-lattice reducer using native order and execution identities."""

    _STATUS_RANK: ClassVar[dict[str, int]] = {
        "PendingSubmit": 1,
        "PreSubmitted": 2,
        "Submitted": 3,
        "PendingCancel": 4,
        "Cancelled": 5,
        "ApiCancelled": 5,
        "Inactive": 5,
        "Filled": 6,
    }

    @classmethod
    def reduce(cls, facts: tuple[IBKRFact, ...]) -> IBKRReadModel:
        if not facts:
            raise ValueError("cannot reduce an empty IBKR fact tape")
        orders: dict[str, dict[str, Any]] = {}
        aliases: dict[tuple[int, int], str] = {}
        executions: dict[str, dict[str, Any]] = {}
        commissions: dict[str, dict[str, Any]] = {}
        positions: dict[str, dict[str, Any]] = {}
        accounts: dict[str, dict[str, Any]] = {}
        conflicts: set[str] = set()
        for fact in sorted(
            facts, key=lambda item: (item.fact_type.value, item.identity_key, item.fact_id)
        ):
            payload = {**fact.payload, "_received_at": fact.received_at.isoformat()}
            if fact.fact_type in {
                IBKRFactType.OPEN_ORDER,
                IBKRFactType.COMPLETED_ORDER,
                IBKRFactType.ORDER_STATUS,
            }:
                client_id = int(payload.get("client_id", 0) or 0)
                order_id = int(payload.get("order_id") or 0)
                perm_id = int(payload.get("perm_id", 0) or 0)
                order_ref = str(payload.get("order_ref", "") or "")
                identity = (
                    f"perm:{perm_id}"
                    if perm_id
                    else (
                        f"ref:{order_ref}"
                        if order_ref
                        else aliases.get(
                            (client_id, order_id),
                            f"session:{fact.session_id}:client:{client_id}:order:{order_id}",
                        )
                    )
                )
                aliases[(client_id, order_id)] = identity
                orders[identity] = cls._merge_order(orders.get(identity, {}), payload, conflicts)
            elif fact.fact_type == IBKRFactType.EXECUTION:
                executions[str(payload["exec_id"])] = payload
            elif fact.fact_type == IBKRFactType.COMMISSION:
                commissions[str(payload["exec_id"])] = payload
            elif fact.fact_type == IBKRFactType.POSITION:
                positions[fact.identity_key] = payload
            elif fact.fact_type == IBKRFactType.ACCOUNT_VALUE:
                accounts[fact.identity_key] = payload
        corrections: dict[str, list[tuple[int, str]]] = {}
        for exec_id in executions:
            root, revision = cls._execution_revision(exec_id)
            corrections.setdefault(root, []).append((revision, exec_id))
        effective_executions: dict[str, dict[str, Any]] = {}
        effective_commissions: dict[str, dict[str, Any]] = {}
        correction_ids: dict[str, tuple[str, ...]] = {}
        for root, versions in corrections.items():
            ordered = tuple(exec_id for _, exec_id in sorted(versions))
            correction_ids[root] = ordered
            effective_id = ordered[-1]
            effective_executions[root] = executions[effective_id]
            if effective_id in commissions:
                effective_commissions[root] = commissions[effective_id]
        effective_ids = {
            str(payload["exec_id"]) for payload in effective_executions.values()
        }
        return IBKRReadModel(
            session_id=facts[0].session_id,
            orders=orders,
            executions=executions,
            execution_corrections=correction_ids,
            effective_executions=effective_executions,
            commissions=commissions,
            effective_commissions=effective_commissions,
            positions=positions,
            account_values=accounts,
            unmatched_commission_exec_ids=tuple(sorted(set(commissions) - set(executions))),
            executions_missing_commission_exec_ids=tuple(
                sorted(effective_ids - set(commissions))
            ),
            corrected_execution_roots=tuple(
                sorted(root for root, versions in corrections.items() if len(versions) > 1)
            ),
            reducer_conflicts=tuple(sorted(conflicts)),
        )

    @classmethod
    def _merge_order(
        cls,
        current: dict[str, Any],
        incoming: dict[str, Any],
        conflicts: set[str],
    ) -> dict[str, Any]:
        merged = {**current, **incoming}
        current_status = str(current.get("status", ""))
        incoming_status = str(incoming.get("status", ""))
        if cls._STATUS_RANK.get(current_status, 0) > cls._STATUS_RANK.get(incoming_status, 0):
            merged["status"] = current_status
        merged["filled"] = str(max(cls._decimal(current.get("filled")), cls._decimal(incoming.get("filled"))))
        remaining_values = [
            cls._decimal(value)
            for value in (current.get("remaining"), incoming.get("remaining"))
            if value is not None
        ]
        if remaining_values:
            merged["remaining"] = str(min(remaining_values))
        for field in ("perm_id", "parent_id", "client_id"):
            values = {
                int(str(value))
                for value in (current.get(field), incoming.get(field))
                if value not in (None, "", 0, "0")
            }
            if len(values) > 1:
                conflicts.add(f"order_{field}_conflict:{sorted(values)}")
            if values:
                merged[field] = min(values)
        current_filled = cls._decimal(current.get("filled"))
        incoming_filled = cls._decimal(incoming.get("filled"))
        if current_filled > incoming_filled and current.get("avg_fill_price") is not None:
            merged["avg_fill_price"] = current["avg_fill_price"]
        return merged

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        try:
            return Decimal(str(value or "0"))
        except InvalidOperation:
            return Decimal("0")

    @staticmethod
    def _execution_revision(exec_id: str) -> tuple[str, int]:
        if "." not in exec_id:
            return exec_id, 0
        root, suffix = exec_id.rsplit(".", 1)
        try:
            return root, int(suffix)
        except ValueError:
            return exec_id, 0
