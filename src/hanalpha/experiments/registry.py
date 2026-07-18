from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from hanalpha.experiments.models import (
    ArtifactDigest,
    ArtifactRecord,
    ExperimentManifest,
    TrialAllocation,
    TrialEvent,
    TrialStatus,
    TrialView,
    WindowRole,
)
from hanalpha.research.protocol import PreregisteredProtocol
from hanalpha.simulation.events import canonical_hash


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
            CREATE TABLE IF NOT EXISTS research_protocols (
              protocol_hash TEXT PRIMARY KEY,
              research_program_id TEXT NOT NULL,
              protocol_json TEXT NOT NULL,
              max_trials INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trial_allocations (
              allocation_id TEXT PRIMARY KEY,
              protocol_hash TEXT NOT NULL REFERENCES research_protocols(protocol_hash),
              research_program_id TEXT NOT NULL,
              trial_number INTEGER NOT NULL,
              parameter_point_hash TEXT NOT NULL,
              window_role TEXT NOT NULL,
              idempotency_key TEXT,
              allocated_at TEXT NOT NULL,
              experiment_id TEXT UNIQUE REFERENCES experiments(experiment_id),
              UNIQUE(protocol_hash, trial_number)
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
        columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(trial_allocations)")
        }
        if "idempotency_key" not in columns:
            self.connection.execute("ALTER TABLE trial_allocations ADD COLUMN idempotency_key TEXT")
        self.connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS trial_allocation_idempotency
               ON trial_allocations(protocol_hash, idempotency_key)
               WHERE idempotency_key IS NOT NULL"""
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def register_protocol(self, protocol: PreregisteredProtocol) -> str:
        frozen = protocol.model_copy(
            update={"budget": protocol.budget.model_copy(update={"used_trials": 0})}
        )
        serialized = json.dumps(
            frozen.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        row = self.connection.execute(
            "SELECT protocol_json FROM research_protocols WHERE protocol_hash=?",
            (protocol.protocol_hash,),
        ).fetchone()
        if row is not None:
            if row["protocol_json"] != serialized:
                raise RuntimeError("protocol hash collision")
            return protocol.protocol_hash
        with self.connection:
            self.connection.execute(
                "INSERT INTO research_protocols VALUES (?, ?, ?, ?)",
                (
                    protocol.protocol_hash,
                    protocol.research_program_id,
                    serialized,
                    protocol.budget.max_trials,
                ),
            )
        return protocol.protocol_hash

    def allocate_trial(
        self,
        protocol_hash: str,
        *,
        parameters: Mapping[str, object],
        window_role: WindowRole,
        idempotency_key: str,
        at: datetime,
    ) -> TrialAllocation:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key must not be blank")
        parameter_hash = canonical_hash(parameters)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            protocol = self.connection.execute(
                "SELECT * FROM research_protocols WHERE protocol_hash=?", (protocol_hash,)
            ).fetchone()
            if protocol is None:
                raise KeyError("protocol is not registered")
            existing = self.connection.execute(
                """SELECT allocation_id, parameter_point_hash, window_role
                   FROM trial_allocations
                   WHERE protocol_hash=? AND idempotency_key=?""",
                (protocol_hash, idempotency_key),
            ).fetchone()
            if existing is not None:
                if (
                    existing["parameter_point_hash"] != parameter_hash
                    or existing["window_role"] != window_role.value
                ):
                    raise RuntimeError("idempotency key conflicts with trial definition")
                self.connection.commit()
                return self.allocation(existing["allocation_id"])
            count = int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM trial_allocations WHERE protocol_hash=?",
                    (protocol_hash,),
                ).fetchone()[0]
            )
            if count >= int(protocol["max_trials"]):
                raise RuntimeError("research budget exhausted")
            trial_number = count + 1
            allocation_id = canonical_hash(
                {
                    "protocol_hash": protocol_hash,
                    "trial_number": trial_number,
                    "parameter_point_hash": parameter_hash,
                    "window_role": window_role,
                    "idempotency_key": idempotency_key,
                }
            )
            self.connection.execute(
                """INSERT INTO trial_allocations
                   (allocation_id, protocol_hash, research_program_id, trial_number,
                    parameter_point_hash, window_role, idempotency_key, allocated_at,
                    experiment_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                (
                    allocation_id,
                    protocol_hash,
                    protocol["research_program_id"],
                    trial_number,
                    parameter_hash,
                    window_role.value,
                    idempotency_key,
                    at.isoformat(),
                ),
            )
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        return self.allocation(allocation_id)

    def allocation(self, allocation_id: str) -> TrialAllocation:
        row = self.connection.execute(
            "SELECT * FROM trial_allocations WHERE allocation_id=?", (allocation_id,)
        ).fetchone()
        if row is None:
            raise KeyError(allocation_id)
        return TrialAllocation(
            allocation_id=row["allocation_id"],
            protocol_hash=row["protocol_hash"],
            research_program_id=row["research_program_id"],
            trial_number=int(row["trial_number"]),
            parameter_point_hash=row["parameter_point_hash"],
            window_role=WindowRole(row["window_role"]),
            allocated_at=datetime.fromisoformat(row["allocated_at"]),
            experiment_id=row["experiment_id"],
        )

    def protocol(self, protocol_hash: str) -> PreregisteredProtocol:
        row = self.connection.execute(
            "SELECT protocol_json FROM research_protocols WHERE protocol_hash=?",
            (protocol_hash,),
        ).fetchone()
        if row is None:
            raise KeyError(protocol_hash)
        return PreregisteredProtocol.model_validate_json(row["protocol_json"])

    def register(self, manifest: ExperimentManifest, *, at: datetime) -> str:
        allocation = self.allocation(manifest.trial_allocation_id)
        if allocation.experiment_id not in {None, manifest.experiment_id}:
            raise RuntimeError("trial allocation already consumed")
        if (
            allocation.protocol_hash != manifest.protocol_hash
            or allocation.research_program_id != manifest.research_program_id
            or allocation.parameter_point_hash != manifest.parameter_point_hash
            or allocation.window_role != manifest.window_role
        ):
            raise RuntimeError("manifest does not match trial allocation")
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
            updated = self.connection.execute(
                """UPDATE trial_allocations SET experiment_id=?
                   WHERE allocation_id=? AND experiment_id IS NULL""",
                (experiment_id, manifest.trial_allocation_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("trial allocation was consumed concurrently")
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
        at: datetime,
    ) -> None:
        """Deprecated: promotion must be derived by PromotionService."""
        raise IllegalTrialTransition("self-reported promotion evidence is forbidden")

    def _promote_verified(
        self,
        experiment_id: str,
        *,
        at: datetime,
        metadata: dict[str, object],
    ) -> None:
        """Append a promotion derived by the authority service, never caller booleans."""
        history = self.history(experiment_id)
        if not history or history[-1].status != TrialStatus.COMPLETED:
            raise IllegalTrialTransition("only a completed trial can be promoted")
        if at < history[-1].occurred_at:
            raise IllegalTrialTransition("promotion time precedes completed trial")
        with self.connection:
            self._append(
                experiment_id,
                TrialStatus.PROMOTED,
                at=at,
                result_hash=history[-1].result_hash,
                failure_reason=None,
                metadata=metadata,
            )

    def manifest(self, experiment_id: str) -> ExperimentManifest:
        row = self.connection.execute(
            "SELECT manifest_json FROM experiments WHERE experiment_id=?", (experiment_id,)
        ).fetchone()
        if row is None:
            raise KeyError(experiment_id)
        return ExperimentManifest.model_validate_json(row["manifest_json"])

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
