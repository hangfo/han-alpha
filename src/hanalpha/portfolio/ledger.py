from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from hanalpha.domain.models import Fill, OrderEvent, OrderRequest, Signal, TradePlan


class Ledger:
    """Append-only local audit ledger. All payloads are stored as canonical JSON."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._initialize()

    def _initialize(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_id);
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    key TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def append(self, event_type: str, entity_id: str, payload: dict[str, Any], created_at: str) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO events(event_type, entity_id, created_at, payload) VALUES (?, ?, ?, ?)",
                (event_type, entity_id, created_at, encoded),
            )

    def record_signal(self, signal: Signal) -> None:
        self.append("signal", signal.signal_id, signal.model_dump(mode="json"), signal.generated_at.isoformat())

    def record_plan(self, plan: TradePlan) -> None:
        self.append("trade_plan", plan.plan_id, plan.model_dump(mode="json"), plan.created_at.isoformat())

    def record_order(self, order: OrderRequest) -> None:
        self.append("order", order.order_id, order.model_dump(mode="json"), order.created_at.isoformat())
        self.reserve_idempotency(order.idempotency_key, order.order_id, order.created_at.isoformat())

    def record_order_event(self, event: OrderEvent) -> None:
        self.append("order_event", event.order_id, event.model_dump(mode="json"), event.timestamp.isoformat())

    def record_fill(self, fill: Fill) -> None:
        self.append("fill", fill.order_id, fill.model_dump(mode="json"), fill.timestamp.isoformat())

    def reserve_idempotency(self, key: str, entity_id: str, created_at: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO idempotency_keys(key, entity_id, created_at) VALUES (?, ?, ?)",
                (key, entity_id, created_at),
            )

    def has_idempotency_key(self, key: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM idempotency_keys WHERE key = ? LIMIT 1", (key,)
        ).fetchone()
        return row is not None

    def idempotency_keys(self) -> set[str]:
        rows = self._connection.execute("SELECT key FROM idempotency_keys").fetchall()
        return {row[0] for row in rows}

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT event_type, entity_id, created_at, payload FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "event_type": event_type,
                "entity_id": entity_id,
                "created_at": created_at,
                "payload": json.loads(payload),
            }
            for event_type, entity_id, created_at, payload in rows
        ]

    def close(self) -> None:
        self._connection.close()
