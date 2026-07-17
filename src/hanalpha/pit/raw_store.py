from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from hanalpha.pit.models import HASH_PATTERN, require_aware


class RawRecordConflict(RuntimeError):
    """A source revision was observed with non-identical bytes."""


class RawEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    payload_hash: str = Field(pattern=HASH_PATTERN)
    source: str
    source_record_id: str
    source_revision: int = Field(ge=1)
    event_time: datetime
    available_at: datetime
    ingested_at: datetime
    schema_version: str
    object_path: str


class ContentAddressedRawStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)

    def put(
        self,
        payload: bytes,
        *,
        source: str,
        source_record_id: str,
        source_revision: int,
        event_time: datetime,
        available_at: datetime,
        ingested_at: datetime,
        schema_version: str,
    ) -> RawEnvelope:
        for name, value in (
            ("event_time", event_time),
            ("available_at", available_at),
            ("ingested_at", ingested_at),
        ):
            require_aware(value, name)
        if ingested_at < available_at:
            raise ValueError("ingested_at must not precede available_at")
        payload_hash = hashlib.sha256(payload).hexdigest()
        destination = self._path(payload_hash)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != payload:
                raise RawRecordConflict(f"content hash collision: {payload_hash}")
        else:
            temporary = destination.with_suffix(f".{os.getpid()}.tmp")
            temporary.write_bytes(payload)
            os.replace(temporary, destination)
        return RawEnvelope(
            payload_hash=payload_hash,
            source=source,
            source_record_id=source_record_id,
            source_revision=source_revision,
            event_time=event_time,
            available_at=available_at,
            ingested_at=ingested_at,
            schema_version=schema_version,
            object_path=str(destination.relative_to(self.root)),
        )

    def read(self, payload_hash: str) -> bytes:
        return self._path(payload_hash).read_bytes()

    def _path(self, payload_hash: str) -> Path:
        if len(payload_hash) != 64 or any(ch not in "0123456789abcdef" for ch in payload_hash):
            raise ValueError("invalid payload hash")
        return self.objects / payload_hash[:2] / payload_hash
