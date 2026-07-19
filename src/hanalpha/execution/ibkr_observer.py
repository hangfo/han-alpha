from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from hanalpha.simulation.events import canonical_hash


class IBKRFactType(StrEnum):
    CONNECTION = "CONNECTION"
    SERVER_TIME = "SERVER_TIME"
    MANAGED_ACCOUNTS = "MANAGED_ACCOUNTS"
    NEXT_VALID_ID = "NEXT_VALID_ID"
    ACCOUNT_VALUE = "ACCOUNT_VALUE"
    ACCOUNT_END = "ACCOUNT_END"
    OPEN_ORDER = "OPEN_ORDER"
    OPEN_ORDER_END = "OPEN_ORDER_END"
    ORDER_STATUS = "ORDER_STATUS"
    POSITION = "POSITION"
    POSITION_END = "POSITION_END"
    EXECUTION = "EXECUTION"
    EXECUTION_END = "EXECUTION_END"
    COMMISSION = "COMMISSION"
    ERROR = "ERROR"
    DISCONNECT = "DISCONNECT"


class IBKRFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fact_id: str
    session_id: str
    fact_type: IBKRFactType
    identity_key: str
    payload: dict[str, Any]
    received_at: datetime


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
    position_end_seen: bool
    execution_end_seen: bool
    critical_errors: tuple[int, ...] = ()
    disconnected: bool = False
    complete: bool


class IBKRReadModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    orders: dict[str, dict[str, Any]]
    executions: dict[str, dict[str, Any]]
    effective_executions: dict[str, dict[str, Any]]
    commissions: dict[str, dict[str, Any]]
    positions: dict[str, dict[str, Any]]
    account_values: dict[str, dict[str, Any]]
    unmatched_commission_exec_ids: tuple[str, ...]
    corrected_execution_roots: tuple[str, ...]


class IBKRFactStore:
    """Append-only raw callback tape. Broker-native identities, not callback order, dedupe facts."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
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

    def close(self) -> None:
        self.connection.close()


class IBKRCallbackCollector:
    """Callback sink for a strictly read-only IBKR snapshot session."""

    _CRITICAL_ERROR_CODES: ClassVar[set[int]] = {502, 503, 504, 1100, 1300}

    def __init__(self, store: IBKRFactStore, session_id: str) -> None:
        self.store = store
        self.session_id = session_id

    def record(
        self,
        fact_type: IBKRFactType,
        payload: dict[str, Any] | None = None,
        *,
        identity_key: str | None = None,
        at: datetime | None = None,
    ) -> IBKRFact:
        payload = payload or {}
        observed = at or datetime.now(UTC)
        key = identity_key or canonical_hash(payload)
        return self.store.append(
            session_id=self.session_id,
            fact_type=fact_type,
            identity_key=key,
            payload=payload,
            received_at=observed,
        )

    def order_status(self, order_id: int, payload: dict[str, Any], *, at: datetime) -> None:
        # IBKR documents duplicate orderStatus callbacks; payload identity makes them harmless.
        self.record(
            IBKRFactType.ORDER_STATUS,
            {"order_id": order_id, **payload},
            identity_key=f"{order_id}:{canonical_hash(payload)}",
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

    def certificate(self, *, at: datetime) -> SnapshotCompletenessCertificate:
        facts = self.store.facts(self.session_id)
        kinds = {fact.fact_type for fact in facts}
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
        flags = {
            "connected": IBKRFactType.CONNECTION in kinds,
            "next_valid_id_seen": IBKRFactType.NEXT_VALID_ID in kinds,
            "managed_accounts_seen": IBKRFactType.MANAGED_ACCOUNTS in kinds,
            "server_time_seen": IBKRFactType.SERVER_TIME in kinds,
            "account_end_seen": IBKRFactType.ACCOUNT_END in kinds,
            "open_order_end_seen": IBKRFactType.OPEN_ORDER_END in kinds,
            "position_end_seen": IBKRFactType.POSITION_END in kinds,
            "execution_end_seen": IBKRFactType.EXECUTION_END in kinds,
        }
        disconnected = IBKRFactType.DISCONNECT in kinds
        complete = all(flags.values()) and not errors and not disconnected
        body = {
            "session_id": self.session_id,
            "as_of": at,
            **flags,
            "critical_errors": errors,
            "disconnected": disconnected,
            "complete": complete,
        }
        certificate = SnapshotCompletenessCertificate(
            certificate_id=canonical_hash(body),
            session_id=self.session_id,
            as_of=at,
            connected=flags["connected"],
            next_valid_id_seen=flags["next_valid_id_seen"],
            managed_accounts_seen=flags["managed_accounts_seen"],
            server_time_seen=flags["server_time_seen"],
            account_end_seen=flags["account_end_seen"],
            open_order_end_seen=flags["open_order_end_seen"],
            position_end_seen=flags["position_end_seen"],
            execution_end_seen=flags["execution_end_seen"],
            critical_errors=errors,
            disconnected=disconnected,
            complete=complete,
        )
        self.store.save_certificate(certificate)
        return certificate


class IBKRFactReducer:
    """Order-independent reducer: broker identities define state, never a global watermark."""

    @staticmethod
    def reduce(facts: tuple[IBKRFact, ...]) -> IBKRReadModel:
        if not facts:
            raise ValueError("cannot reduce an empty IBKR fact tape")
        orders: dict[str, dict[str, Any]] = {}
        executions: dict[str, dict[str, Any]] = {}
        commissions: dict[str, dict[str, Any]] = {}
        positions: dict[str, dict[str, Any]] = {}
        accounts: dict[str, dict[str, Any]] = {}
        status_rank = {
            "PendingSubmit": 1,
            "PreSubmitted": 2,
            "Submitted": 3,
            "PendingCancel": 4,
            "Cancelled": 5,
            "ApiCancelled": 5,
            "Inactive": 5,
            "Filled": 6,
        }
        for fact in sorted(
            facts, key=lambda item: (item.fact_type.value, item.identity_key, item.fact_id)
        ):
            payload = fact.payload
            if fact.fact_type == IBKRFactType.OPEN_ORDER:
                order_id = str(payload["order_id"])
                orders[order_id] = {**orders.get(order_id, {}), **payload}
            elif fact.fact_type == IBKRFactType.ORDER_STATUS:
                order_id = str(payload["order_id"])
                current = orders.get(order_id, {})
                current_status = str(current.get("status", ""))
                incoming_status = str(payload.get("status", ""))
                merged = {**current, **payload}
                if status_rank.get(current_status, 0) > status_rank.get(incoming_status, 0):
                    merged["status"] = current_status
                merged["filled"] = str(
                    max(
                        Decimal(str(current.get("filled", "0"))),
                        Decimal(str(payload.get("filled", "0"))),
                    )
                )
                orders[order_id] = merged
            elif fact.fact_type == IBKRFactType.EXECUTION:
                executions[str(payload["exec_id"])] = payload
            elif fact.fact_type == IBKRFactType.COMMISSION:
                commissions[str(payload["exec_id"])] = payload
            elif fact.fact_type == IBKRFactType.POSITION:
                positions[fact.identity_key] = payload
            elif fact.fact_type == IBKRFactType.ACCOUNT_VALUE:
                accounts[fact.identity_key] = payload
        roots: dict[str, int] = {}
        for exec_id in executions:
            root = exec_id.rsplit(".", 1)[0] if "." in exec_id else exec_id
            roots[root] = roots.get(root, 0) + 1
        effective_executions: dict[str, dict[str, Any]] = {}
        for exec_id in sorted(executions):
            root = exec_id.rsplit(".", 1)[0] if "." in exec_id else exec_id
            effective_executions[root] = executions[exec_id]
        return IBKRReadModel(
            session_id=facts[0].session_id,
            orders=orders,
            executions=executions,
            effective_executions=effective_executions,
            commissions=commissions,
            positions=positions,
            account_values=accounts,
            unmatched_commission_exec_ids=tuple(sorted(set(commissions) - set(executions))),
            corrected_execution_roots=tuple(sorted(root for root, count in roots.items() if count > 1)),
        )
