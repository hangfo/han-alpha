from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import duckdb

from hanalpha.pit.models import CanonicalRecord


class CanonicalStore:
    """Immutable Parquet snapshots with a deliberately narrow internal query API."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, snapshot_id: str, records: list[CanonicalRecord]) -> Path:
        records = [
            type(record).model_validate(record.model_dump(mode="python")) for record in records
        ]
        if any(record.snapshot_id != snapshot_id for record in records):
            raise ValueError("all records must be bound to the target snapshot")
        destination = self.path(snapshot_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            existing = sorted(
                self.query_payloads(snapshot_id, "TRUE", [], latest_revisions=False),
                key=_record_sort_key,
            )
            desired = sorted(
                [record.model_dump(mode="json") for record in records], key=_record_sort_key
            )
            if existing != desired:
                raise RuntimeError("immutable canonical snapshot already exists with other content")
            return destination

        temporary = destination.with_suffix(f".{os.getpid()}.tmp.parquet")
        connection = duckdb.connect()
        try:
            connection.execute(
                """
                CREATE TABLE canonical_records (
                  record_type VARCHAR NOT NULL,
                  instrument_id VARCHAR NOT NULL,
                  record_id VARCHAR NOT NULL,
                  event_time TIMESTAMPTZ NOT NULL,
                  available_at TIMESTAMPTZ NOT NULL,
                  ingested_at TIMESTAMPTZ NOT NULL,
                  valid_from TIMESTAMPTZ NOT NULL,
                  valid_to TIMESTAMPTZ,
                  source VARCHAR NOT NULL,
                  source_record_id VARCHAR NOT NULL,
                  source_revision INTEGER NOT NULL,
                  snapshot_id VARCHAR NOT NULL,
                  payload_json VARCHAR NOT NULL
                )
                """
            )
            rows = [
                (
                    record.record_type,
                    record.instrument_id,
                    record.record_id,
                    record.event_time,
                    record.available_at,
                    record.ingested_at,
                    record.valid_from,
                    record.valid_to,
                    record.source,
                    record.source_record_id,
                    record.source_revision,
                    record.snapshot_id,
                    record.model_dump_json(),
                )
                for record in records
            ]
            connection.executemany(
                "INSERT INTO canonical_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            quoted = str(temporary).replace("'", "''")
            connection.execute(
                f"COPY canonical_records TO '{quoted}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            os.replace(temporary, destination)
        finally:
            connection.close()
            temporary.unlink(missing_ok=True)
        return destination

    def path(self, snapshot_id: str) -> Path:
        return self.root / snapshot_id / "records.parquet"

    def query_payloads(
        self,
        snapshot_id: str,
        predicate: str,
        parameters: list[object],
        *,
        latest_revisions: bool = True,
    ) -> list[dict[str, Any]]:
        path = self.path(snapshot_id)
        if not path.exists():
            raise KeyError(f"canonical snapshot not found: {snapshot_id}")
        quoted = str(path).replace("'", "''")
        connection = duckdb.connect()
        try:
            revision_clause = (
                """QUALIFY row_number() OVER (
                    PARTITION BY source, source_record_id
                    ORDER BY source_revision DESC, ingested_at DESC
                ) = 1"""
                if latest_revisions
                else ""
            )
            rows = connection.execute(
                f"""
                SELECT payload_json
                FROM read_parquet('{quoted}')
                WHERE {predicate}
                {revision_clause}
                ORDER BY event_time, record_id
                """,
                parameters,
            ).fetchall()
            return [json.loads(row[0]) for row in rows]
        finally:
            connection.close()


def _record_sort_key(payload: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(payload["source"]),
        str(payload["source_record_id"]),
        int(payload["source_revision"]),
    )
