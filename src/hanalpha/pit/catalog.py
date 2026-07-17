from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hanalpha.pit.models import HASH_PATTERN
from hanalpha.pit.quality import QualityReport
from hanalpha.pit.raw_store import RawEnvelope, RawRecordConflict


class SnapshotManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    input_hashes: list[str]
    schema_version: str
    normalization_code_hash: str = Field(pattern=HASH_PATTERN)
    config_hash: str = Field(pattern=HASH_PATTERN)
    fixture_version: str

    @field_validator("input_hashes")
    @classmethod
    def normalize_hashes(cls, values: list[str]) -> list[str]:
        for value in values:
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError("input_hashes must contain SHA-256 hex digests")
        return sorted(set(values))

    @property
    def snapshot_id(self) -> str:
        document = self.model_dump(mode="json", exclude_none=True)
        document["input_hashes"] = sorted(set(self.input_hashes))
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


class PITCatalog:
    def __init__(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS raw_records (
              source TEXT NOT NULL,
              source_record_id TEXT NOT NULL,
              source_revision INTEGER NOT NULL,
              payload_hash TEXT NOT NULL,
              envelope_json TEXT NOT NULL,
              PRIMARY KEY (source, source_record_id, source_revision)
            );
            CREATE TABLE IF NOT EXISTS snapshots (
              snapshot_id TEXT PRIMARY KEY,
              manifest_json TEXT NOT NULL,
              state TEXT NOT NULL CHECK (state IN ('staged', 'published')),
              quality_json TEXT
            );
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def register_raw(self, envelope: RawEnvelope) -> None:
        existing = self.connection.execute(
            """SELECT payload_hash FROM raw_records
               WHERE source=? AND source_record_id=? AND source_revision=?""",
            (envelope.source, envelope.source_record_id, envelope.source_revision),
        ).fetchone()
        if existing is not None:
            if existing["payload_hash"] != envelope.payload_hash:
                raise RawRecordConflict(
                    "same source record revision contains different payload bytes"
                )
            return
        self.connection.execute(
            "INSERT INTO raw_records VALUES (?, ?, ?, ?, ?)",
            (
                envelope.source,
                envelope.source_record_id,
                envelope.source_revision,
                envelope.payload_hash,
                envelope.model_dump_json(),
            ),
        )
        self.connection.commit()

    def create_snapshot(self, manifest: SnapshotManifest) -> str:
        manifest = SnapshotManifest.model_validate(manifest.model_dump())
        snapshot_id = manifest.snapshot_id
        serialized = manifest.model_dump_json()
        existing = self.connection.execute(
            "SELECT manifest_json FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        if existing is not None and existing["manifest_json"] != serialized:
            raise RuntimeError("snapshot hash collision")
        self.connection.execute(
            "INSERT OR IGNORE INTO snapshots VALUES (?, ?, 'staged', NULL)",
            (snapshot_id, serialized),
        )
        self.connection.commit()
        return snapshot_id

    def record_quality(self, snapshot_id: str, report: QualityReport) -> None:
        cursor = self.connection.execute(
            "UPDATE snapshots SET quality_json=? WHERE snapshot_id=?",
            (report.model_dump_json(), snapshot_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(snapshot_id)
        self.connection.commit()

    def publish_snapshot(self, snapshot_id: str) -> None:
        report = self.get_quality(snapshot_id)
        if report is None or not report.passed:
            raise RuntimeError("snapshot cannot publish without a passing quality report")
        self.connection.execute(
            "UPDATE snapshots SET state='published' WHERE snapshot_id=?", (snapshot_id,)
        )
        self.connection.commit()

    def is_published(self, snapshot_id: str) -> bool:
        row = self.connection.execute(
            "SELECT state FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        return row is not None and row["state"] == "published"

    def get_manifest(self, snapshot_id: str) -> SnapshotManifest:
        row = self.connection.execute(
            "SELECT manifest_json FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        if row is None:
            raise KeyError(snapshot_id)
        return SnapshotManifest.model_validate_json(row["manifest_json"])

    def get_quality(self, snapshot_id: str) -> QualityReport | None:
        row = self.connection.execute(
            "SELECT quality_json FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        if row is None:
            raise KeyError(snapshot_id)
        if row["quality_json"] is None:
            return None
        return QualityReport.model_validate_json(row["quality_json"])

    def snapshot_document(self, snapshot_id: str) -> dict[str, object]:
        row = self.connection.execute(
            "SELECT manifest_json, state, quality_json FROM snapshots WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            raise KeyError(snapshot_id)
        return {
            "snapshot_id": snapshot_id,
            "state": row["state"],
            "manifest": json.loads(row["manifest_json"]),
            "quality": json.loads(row["quality_json"]) if row["quality_json"] else None,
        }
