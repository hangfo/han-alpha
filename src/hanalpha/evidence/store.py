from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from hanalpha.evidence.models import (
    ContradictionEdge,
    EvidenceClaim,
    EvidenceDocument,
    ExtractionResult,
)


class EvidenceBudgetPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_documents_per_entity_day: int = Field(default=20, gt=0)
    max_calls_per_event: int = Field(default=2, gt=0)
    max_claims_per_document: int = Field(default=20, gt=0)
    max_document_characters: int = Field(default=100_000, gt=0)


class EvidenceBudgetExceeded(RuntimeError):
    pass


class EvidenceStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS documents (
              document_id TEXT PRIMARY KEY,
              entity_id TEXT NOT NULL,
              available_day TEXT NOT NULL,
              document_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claims (
              claim_id TEXT PRIMARY KEY,
              document_id TEXT NOT NULL REFERENCES documents(document_id),
              claim_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contradiction_edges (
              edge_id TEXT PRIMARY KEY,
              edge_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS extraction_cache (
              cache_key TEXT PRIMARY KEY,
              result_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS call_budget (
              event_key TEXT PRIMARY KEY,
              calls INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_call_attempts (
              attempt_id TEXT PRIMARY KEY,
              event_key TEXT NOT NULL,
              cache_key TEXT NOT NULL,
              extractor_id TEXT NOT NULL,
              started_at TEXT NOT NULL,
              completed_at TEXT,
              status TEXT NOT NULL,
              error_type TEXT
            );
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def put_document(self, document: EvidenceDocument, policy: EvidenceBudgetPolicy) -> None:
        if len(document.content) > policy.max_document_characters:
            raise EvidenceBudgetExceeded("document character budget exceeded")
        row = self.connection.execute(
            "SELECT document_json FROM documents WHERE document_id=?", (document.document_id,)
        ).fetchone()
        serialized = document.model_dump_json()
        if row is not None:
            if row["document_json"] != serialized:
                raise RuntimeError("immutable document conflict")
            return
        count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM documents WHERE entity_id=? AND available_day=?",
                (document.entity_id, document.available_at.date().isoformat()),
            ).fetchone()[0]
        )
        if count >= policy.max_documents_per_entity_day:
            raise EvidenceBudgetExceeded("entity daily document budget exceeded")
        with self.connection:
            self.connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?)",
                (
                    document.document_id,
                    document.entity_id,
                    document.available_at.date().isoformat(),
                    serialized,
                ),
            )

    def reserve_call(
        self,
        event_key: str,
        policy: EvidenceBudgetPolicy,
        *,
        cache_key: str,
        extractor_id: str,
        at: datetime,
    ) -> str:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                "SELECT calls FROM call_budget WHERE event_key=?", (event_key,)
            ).fetchone()
            calls = int(row["calls"]) if row is not None else 0
            if calls >= policy.max_calls_per_event:
                raise EvidenceBudgetExceeded("event model-call budget exceeded")
            attempt_id = f"{event_key}:{calls + 1}"
            self.connection.execute(
                """INSERT INTO call_budget VALUES (?, 1)
                   ON CONFLICT(event_key) DO UPDATE SET calls=calls+1""",
                (event_key,),
            )
            self.connection.execute(
                """INSERT INTO model_call_attempts
                   (attempt_id, event_key, cache_key, extractor_id, started_at, status)
                   VALUES (?, ?, ?, ?, ?, 'started')""",
                (attempt_id, event_key, cache_key, extractor_id, at.isoformat()),
            )
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        return attempt_id

    def complete_call(
        self,
        attempt_id: str,
        *,
        at: datetime,
        error_type: str | None = None,
    ) -> None:
        status = "failed" if error_type else "completed"
        with self.connection:
            updated = self.connection.execute(
                """UPDATE model_call_attempts
                   SET completed_at=?, status=?, error_type=?
                   WHERE attempt_id=? AND status='started'""",
                (at.isoformat(), status, error_type, attempt_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("model call attempt is missing or already completed")

    def call_attempts(self, event_key: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT * FROM model_call_attempts
               WHERE event_key=? ORDER BY started_at, attempt_id""",
            (event_key,),
        ).fetchall()

    def cached(self, cache_key: str) -> ExtractionResult | None:
        row = self.connection.execute(
            "SELECT result_json FROM extraction_cache WHERE cache_key=?", (cache_key,)
        ).fetchone()
        return ExtractionResult.model_validate_json(row["result_json"]) if row else None

    def put_cache(self, cache_key: str, result: ExtractionResult, at: datetime) -> None:
        serialized = result.model_dump_json()
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO extraction_cache VALUES (?, ?, ?)",
                (cache_key, serialized, at.isoformat()),
            )
        row = self.connection.execute(
            "SELECT result_json FROM extraction_cache WHERE cache_key=?", (cache_key,)
        ).fetchone()
        if row["result_json"] != serialized:
            raise RuntimeError("extraction cache conflict")

    def put_claims(
        self,
        claims: tuple[EvidenceClaim, ...],
        edges: tuple[ContradictionEdge, ...],
    ) -> None:
        with self.connection:
            for claim in claims:
                self.connection.execute(
                    "INSERT OR IGNORE INTO claims VALUES (?, ?, ?)",
                    (claim.claim_id, claim.source_document_id, claim.model_dump_json()),
                )
            for edge in edges:
                self.connection.execute(
                    "INSERT OR IGNORE INTO contradiction_edges VALUES (?, ?)",
                    (edge.edge_id, edge.model_dump_json()),
                )

    def claims_as_of(self, as_of: datetime) -> tuple[EvidenceClaim, ...]:
        rows = self.connection.execute("SELECT claim_json FROM claims ORDER BY claim_id").fetchall()
        claims = (EvidenceClaim.model_validate_json(row["claim_json"]) for row in rows)
        return tuple(claim for claim in claims if claim.available_at <= as_of < claim.expires_at)

    def edges_for(self, claim_ids: set[str]) -> tuple[ContradictionEdge, ...]:
        rows = self.connection.execute(
            "SELECT edge_json FROM contradiction_edges ORDER BY edge_id"
        ).fetchall()
        edges = (ContradictionEdge.model_validate_json(row["edge_json"]) for row in rows)
        return tuple(
            edge
            for edge in edges
            if edge.left_claim_id in claim_ids and edge.right_claim_id in claim_ids
        )

    def document_count(self, entity_id: str, day: date) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM documents WHERE entity_id=? AND available_day=?",
                (entity_id, day.isoformat()),
            ).fetchone()[0]
        )
