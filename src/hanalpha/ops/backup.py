from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _fsync_path(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def backup_databases(sources: tuple[Path, ...], destination: Path) -> Path:
    """Create one validated cross-store backup generation and manifest."""
    names = [source.name for source in sources]
    if len(names) != len(set(names)):
        raise ValueError("backup sources must have unique database names")
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
        _fsync_path(target)
        entries.append(
            {"name": source.name, "sha256": file_sha256(target), "size": target.stat().st_size}
        )
    created_at = datetime.now(UTC).isoformat()
    content_set_hash = _canonical_hash({"databases": entries})
    generation_id = _canonical_hash({"created_at": created_at, "databases": entries})
    manifest_body: dict[str, Any] = {
        "schema_version": 3,
        "generation_id": generation_id,
        "content_set_hash": content_set_hash,
        "created_at": created_at,
        "databases": entries,
    }
    manifest_body["cross_store_manifest_hash"] = _canonical_hash(manifest_body)
    manifest = destination / "manifest.json"
    manifest.write_text(
        json.dumps(manifest_body, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    _fsync_path(manifest)
    _fsync_path(destination)
    return manifest


def _validated_manifest(manifest: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(manifest.read_text(encoding="utf-8"))
    expected = str(document.pop("cross_store_manifest_hash", ""))
    if _canonical_hash(document) != expected:
        raise RuntimeError("cross-store manifest hash mismatch")
    document["cross_store_manifest_hash"] = expected
    names = [str(entry["name"]) for entry in document["databases"]]
    if len(names) != len(set(names)):
        raise RuntimeError("backup manifest contains duplicate database names")
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
    return document


def restore_databases(
    manifest: Path,
    destination: Path,
    *,
    overwrite: bool = False,
    fail_after_files: int | None = None,
) -> Path:
    """Restore all stores into a generation, then atomically switch CURRENT."""
    document = _validated_manifest(manifest)
    destination.mkdir(parents=True, exist_ok=True)
    generations = destination / "generations"
    generations.mkdir(exist_ok=True)
    generation_id = str(document["generation_id"])
    final_generation = generations / generation_id
    current = destination / "CURRENT"
    current_target = current_generation(destination)
    if current.is_symlink() and not overwrite:
        raise FileExistsError(current)
    if final_generation.exists():
        installed_manifest = final_generation / "manifest.json"
        if (
            not installed_manifest.is_file()
            or _validated_manifest(installed_manifest)["cross_store_manifest_hash"]
            != document["cross_store_manifest_hash"]
        ):
            raise RuntimeError("existing generation is not the requested complete generation")
        if current_target == final_generation.resolve():
            return final_generation
        if not overwrite and current.is_symlink():
            raise FileExistsError(current)
        temporary_link = destination / ".CURRENT.restore-tmp"
        temporary_link.unlink(missing_ok=True)
        temporary_link.symlink_to(Path("generations") / generation_id)
        os.replace(temporary_link, current)
        _fsync_path(destination)
        return final_generation
    temporary = generations / f".{generation_id}.restore-tmp"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir()
    try:
        for index, entry in enumerate(document["databases"], start=1):
            source = manifest.parent / str(entry["name"])
            target = temporary / source.name
            shutil.copyfile(source, target)
            _fsync_path(target)
            if fail_after_files is not None and index >= fail_after_files:
                raise RuntimeError("injected restore interruption")
        copied_manifest = temporary / "manifest.json"
        shutil.copyfile(manifest, copied_manifest)
        _fsync_path(copied_manifest)
        _fsync_path(temporary)
        os.replace(temporary, final_generation)
        _fsync_path(generations)
        temporary_link = destination / ".CURRENT.restore-tmp"
        temporary_link.unlink(missing_ok=True)
        temporary_link.symlink_to(Path("generations") / generation_id)
        os.replace(temporary_link, current)
        _fsync_path(destination)
        return final_generation
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def current_generation(destination: Path) -> Path | None:
    current = destination / "CURRENT"
    return current.resolve(strict=True) if current.is_symlink() else None
