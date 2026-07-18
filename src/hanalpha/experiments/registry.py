from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from hanalpha.experiments.models import (
    ArtifactDigest,
    ArtifactRecord,
    ExperimentManifest,
    TrialEvent,
    TrialStatus,
    TrialView,
)
from hanalpha.research.promotion import (
    PromotionEvidence,
    PromotionThresholds,
    promotion_failures,
)


class IllegalTrialTransition(RuntimeError):
    pass


_ALLOWED: dict[TrialStatus, set[TrialStatus]] = {
    TrialStatus.REGISTERED: {TrialStatus.RUNNING, TrialStatus.ABORTED},
    TrialStatus.RUNNING: {
        TrialStatus.COMPLETED,
        TrialStatus.FAILED,
        TrialStatus.ABORTED,
    },
    TrialStatus.COMPLETED: set(),
    TrialStatus.FAILED: set(),
    TrialStatus.ABORTED: set(),
    TrialStatus.PROMOTED: set(),
}


class ExperimentRegistry:
    """Append-only trial registry. Deliberately has no delete operation."""

    def __init__(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS experiments (
              experiment_id TEXT PRIMARY KEY,
              manifest_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trial_events (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT,
              experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
              status TEXT NOT NULL,
              occurred_at TEXT NOT NULL,
              result_hash TEXT,
              failure_reason TEXT,
              metadata_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifacts (
              experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
              name TEXT NOT NULL,
              sha256 TEXT NOT NULL,
              size INTEGER NOT NULL,
              relative_path TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY (experiment_id, name)
            );
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def register(self, manifest: ExperimentManifest, *, at: datetime) -> str:
        if manifest.counterfactual_of is not None:
            parent = self.connection.execute(
                "SELECT 1 FROM experiments WHERE experiment_id=?",
                (manifest.counterfactual_of,),
            ).fetchone()
            if parent is None:
                raise KeyError("counterfactual parent is not registered")
        experiment_id = manifest.experiment_id
        serialized = json.dumps(
            manifest.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )
        row = self.connection.execute(
            "SELECT manifest_json FROM experiments WHERE experiment_id=?",
            (experiment_id,),
        ).fetchone()
        if row is not None:
            if row["manifest_json"] != serialized:
                raise RuntimeError("experiment hash collision")
            return experiment_id
        with self.connection:
            self.connection.execute(
                "INSERT INTO experiments VALUES (?, ?)", (experiment_id, serialized)
            )
            self._append(
                experiment_id,
                TrialStatus.REGISTERED,
                at=at,
                result_hash=None,
                failure_reason=None,
                metadata={},
            )
        return experiment_id

    def transition(
        self,
        experiment_id: str,
        status: TrialStatus,
        *,
        at: datetime,
        result_hash: str | None = None,
        failure_reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        history = self.history(experiment_id)
        if not history:
            raise KeyError(experiment_id)
        current = history[-1]
        if status not in _ALLOWED[current.status]:
            raise IllegalTrialTransition(f"{current.status} -> {status}")
        if at < current.occurred_at:
            raise IllegalTrialTransition("trial events must be monotonic")
        event = TrialEvent(
            sequence=current.sequence + 1,
            experiment_id=experiment_id,
            status=status,
            occurred_at=at,
            result_hash=result_hash,
            failure_reason=failure_reason,
            metadata=metadata or {},
        )
        with self.connection:
            self._append(
                experiment_id,
                event.status,
                at=event.occurred_at,
                result_hash=event.result_hash,
                failure_reason=event.failure_reason,
                metadata=event.metadata,
            )

    def promote(
        self,
        experiment_id: str,
        *,
        evidence: PromotionEvidence,
        thresholds: PromotionThresholds,
        at: datetime,
    ) -> None:
        """Promote only through the explicit statistical and human review gate."""
        history = self.history(experiment_id)
        if not history:
            raise KeyError(experiment_id)
        current = history[-1]
        if current.status != TrialStatus.COMPLETED:
            raise IllegalTrialTransition(f"{current.status} -> {TrialStatus.PROMOTED}")
        if at < current.occurred_at:
            raise IllegalTrialTransition("trial events must be monotonic")
        failures = promotion_failures(evidence, thresholds)
        if failures:
            raise IllegalTrialTransition("promotion rejected: " + ", ".join(failures))
        with self.connection:
            self._append(
                experiment_id,
                TrialStatus.PROMOTED,
                at=at,
                result_hash=current.result_hash,
                failure_reason=None,
                metadata={
                    "promotion_evidence": evidence.model_dump(mode="json"),
                    "promotion_thresholds": thresholds.model_dump(mode="json"),
                },
            )

    def record_artifact(
        self,
        experiment_id: str,
        digest: ArtifactDigest,
        *,
        relative_path: str,
        at: datetime,
    ) -> ArtifactRecord:
        if not self.history(experiment_id):
            raise KeyError(experiment_id)
        record = ArtifactRecord(
            experiment_id=experiment_id,
            digest=digest,
            relative_path=relative_path,
            created_at=at,
        )
        row = self.connection.execute(
            "SELECT * FROM artifacts WHERE experiment_id=? AND name=?",
            (experiment_id, digest.name),
        ).fetchone()
        if row is not None:
            current = self._artifact_from_row(row)
            if current.digest != record.digest or current.relative_path != record.relative_path:
                raise RuntimeError("artifact conflict")
            return current
        with self.connection:
            self.connection.execute(
                """INSERT INTO artifacts
                   (experiment_id, name, sha256, size, relative_path, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    experiment_id,
                    digest.name,
                    digest.sha256,
                    digest.size,
                    relative_path,
                    at.isoformat(),
                ),
            )
        return record

    def artifacts(self, experiment_id: str) -> list[ArtifactRecord]:
        rows = self.connection.execute(
            "SELECT * FROM artifacts WHERE experiment_id=? ORDER BY name",
            (experiment_id,),
        ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def history(self, experiment_id: str) -> list[TrialEvent]:
        rows = self.connection.execute(
            "SELECT * FROM trial_events WHERE experiment_id=? ORDER BY sequence",
            (experiment_id,),
        ).fetchall()
        return [
            TrialEvent(
                sequence=int(row["sequence"]),
                experiment_id=row["experiment_id"],
                status=TrialStatus(row["status"]),
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
                result_hash=row["result_hash"],
                failure_reason=row["failure_reason"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def strategy_cemetery(self) -> list[TrialView]:
        rows = self.connection.execute(
            "SELECT experiment_id, manifest_json FROM experiments ORDER BY experiment_id"
        ).fetchall()
        views: list[TrialView] = []
        for row in rows:
            history = self.history(row["experiment_id"])
            if not history or history[-1].status not in {
                TrialStatus.FAILED,
                TrialStatus.ABORTED,
            }:
                continue
            last = history[-1]
            views.append(
                TrialView(
                    experiment_id=row["experiment_id"],
                    manifest=ExperimentManifest.model_validate_json(row["manifest_json"]),
                    status=last.status,
                    failure_reason=last.failure_reason,
                    result_hash=last.result_hash,
                    event_count=len(history),
                )
            )
        return views

    def _append(
        self,
        experiment_id: str,
        status: TrialStatus,
        *,
        at: datetime,
        result_hash: str | None,
        failure_reason: str | None,
        metadata: dict[str, object],
    ) -> None:
        TrialEvent(
            sequence=1,
            experiment_id=experiment_id,
            status=status,
            occurred_at=at,
            result_hash=result_hash,
            failure_reason=failure_reason,
            metadata=metadata,
        )
        self.connection.execute(
            """INSERT INTO trial_events
               (experiment_id, status, occurred_at, result_hash, failure_reason, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                experiment_id,
                status.value,
                at.isoformat(),
                result_hash,
                failure_reason,
                json.dumps(metadata, sort_keys=True, separators=(",", ":")),
            ),
        )

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> ArtifactRecord:
        return ArtifactRecord(
            experiment_id=row["experiment_id"],
            digest=ArtifactDigest(name=row["name"], sha256=row["sha256"], size=int(row["size"])),
            relative_path=row["relative_path"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
