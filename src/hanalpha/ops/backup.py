from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_databases(sources: tuple[Path, ...], destination: Path) -> Path:
    """Create consistent SQLite online backups and a hash manifest."""
    destination.mkdir(parents=True, exist_ok=False)
    entries: list[dict[str, object]] = []
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(source)
        target = destination / source.name
        source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        target_connection = sqlite3.connect(target)
        try:
            source_connection.backup(target_connection)
            result = target_connection.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"backup integrity check failed for {source.name}: {result}")
        finally:
            target_connection.close()
            source_connection.close()
        entries.append(
            {"name": source.name, "sha256": file_sha256(target), "size": target.stat().st_size}
        )
    manifest = destination / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"created_at": datetime.now(UTC).isoformat(), "databases": entries},
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def restore_databases(manifest: Path, destination: Path, *, overwrite: bool = False) -> None:
    """Verify every artifact before atomically restoring it."""
    document = json.loads(manifest.read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=True)
    verified: list[tuple[Path, Path]] = []
    for entry in document["databases"]:
        source = manifest.parent / str(entry["name"])
        if file_sha256(source) != entry["sha256"]:
            raise RuntimeError(f"backup hash mismatch: {source.name}")
        connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError(f"backup integrity check failed: {source.name}")
        finally:
            connection.close()
        target = destination / source.name
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        verified.append((source, target))
    for source, target in verified:
        temporary = target.with_suffix(target.suffix + ".restore-tmp")
        temporary.write_bytes(source.read_bytes())
        os.replace(temporary, target)
