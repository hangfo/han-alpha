from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_immutable_json(path: Path, document: dict[str, Any]) -> None:
    """Atomically create or idempotently confirm one canonical JSON artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode()
    if path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(f"immutable artifact already exists with different bytes: {path}")
        return
    write_immutable_bytes(path, encoded)


def write_immutable_bytes(path: Path, encoded: bytes) -> None:
    """Atomically create or idempotently confirm one immutable byte artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(f"immutable artifact already exists with different bytes: {path}")
        return
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    temporary.write_bytes(encoded)
    _fsync(temporary)
    try:
        os.link(temporary, path)
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise FileExistsError(
                f"immutable artifact concurrently created with different bytes: {path}"
            ) from None
    finally:
        temporary.unlink(missing_ok=True)
    _fsync(path.parent)


def _fsync(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
