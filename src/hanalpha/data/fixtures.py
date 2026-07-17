from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from hanalpha.pit.canonical_store import CanonicalStore
from hanalpha.pit.catalog import PITCatalog, SnapshotManifest
from hanalpha.pit.context import AsOfContext
from hanalpha.pit.models import CanonicalRecord, PriceBarRecord, parse_record
from hanalpha.pit.quality import DataQualityGate
from hanalpha.pit.raw_store import ContentAddressedRawStore
from hanalpha.pit.repository import AsOfRepository


class FixtureClassification(StrEnum):
    PUBLISH = "publish"
    REJECT_INGEST = "reject_ingest"
    REJECT_QUALITY = "reject_quality"
    EXPECTED = "expected"


class FixtureFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    classification: FixtureClassification


class FixtureDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    fixture_version: str
    generator_version: str
    schema_version: str
    files: list[FixtureFile]


class FixturePipelineResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    snapshot_id: str
    feature_hash: str
    quality_passed: bool
    record_count: int


def run_fixture_pipeline(fixture_root: Path, state_root: Path) -> FixturePipelineResult:
    fixture_root = Path(fixture_root)
    state_root = Path(state_root)
    definition = FixtureDefinition.model_validate_json(
        (fixture_root / "manifest.json").read_text(encoding="utf-8")
    )
    inputs = _verified_inputs(fixture_root, definition)
    config_payload = {
        "fixture_version": definition.fixture_version,
        "generator_version": definition.generator_version,
        "schema_version": definition.schema_version,
        "normalizer": "hanalpha-pit-normalizer-v1",
    }
    config_hash = _hash_json(config_payload)
    normalization_hash = hashlib.sha256(b"hanalpha-pit-normalizer-v1").hexdigest()
    manifest = SnapshotManifest(
        input_hashes=[
            item.sha256
            for item, _ in inputs
            if item.classification == FixtureClassification.PUBLISH
        ],
        schema_version=definition.schema_version,
        normalization_code_hash=normalization_hash,
        config_hash=config_hash,
        fixture_version=definition.fixture_version,
    )
    snapshot_id = manifest.snapshot_id

    state_root.mkdir(parents=True, exist_ok=True)
    raw_store = ContentAddressedRawStore(state_root / "raw")
    catalog = PITCatalog(state_root / "catalog.sqlite3")
    canonical_store = CanonicalStore(state_root / "canonical")
    try:
        catalog.create_snapshot(manifest)
        records: list[CanonicalRecord] = []
        seen_inputs: set[tuple[str, str, int, str]] = set()
        for fixture_file, content in inputs:
            if fixture_file.classification != FixtureClassification.PUBLISH:
                continue
            for line_number, raw_line in enumerate(content.splitlines(), start=1):
                if not raw_line.strip():
                    continue
                data = json.loads(raw_line)
                line_hash = hashlib.sha256(raw_line).hexdigest()
                data["payload_hash"] = line_hash
                data["snapshot_id"] = snapshot_id
                record = parse_record(data)
                envelope = raw_store.put(
                    raw_line,
                    source=record.source,
                    source_record_id=record.source_record_id,
                    source_revision=record.source_revision,
                    event_time=record.event_time,
                    available_at=record.available_at,
                    ingested_at=record.ingested_at,
                    schema_version=record.schema_version,
                )
                if envelope.payload_hash != record.payload_hash:
                    raise RuntimeError(
                        f"line hash drift in {fixture_file.path}:{line_number}"
                    )
                catalog.register_raw(envelope)
                identity = (
                    record.source,
                    record.source_record_id,
                    record.source_revision,
                    record.payload_hash,
                )
                if identity in seen_inputs:
                    continue
                seen_inputs.add(identity)
                records.append(record)

        report = DataQualityGate().evaluate(records)
        catalog.record_quality(snapshot_id, report)
        if not report.passed:
            raise RuntimeError(
                "fixture quality gate failed: "
                + ", ".join(issue.code for issue in report.issues)
            )
        canonical_store.write(snapshot_id, records)
        catalog.publish_snapshot(snapshot_id)
        feature_hash = _feature_hash(catalog, canonical_store, snapshot_id, records)
        return FixturePipelineResult(
            snapshot_id=snapshot_id,
            feature_hash=feature_hash,
            quality_passed=report.passed,
            record_count=len(records),
        )
    finally:
        catalog.close()


def _verified_inputs(
    fixture_root: Path, definition: FixtureDefinition
) -> list[tuple[FixtureFile, bytes]]:
    inputs: list[tuple[FixtureFile, bytes]] = []
    resolved_root = fixture_root.resolve()
    for item in sorted(definition.files, key=lambda value: value.path):
        path = (fixture_root / item.path).resolve()
        if not path.is_relative_to(resolved_root):
            raise ValueError(f"fixture path escapes root: {item.path}")
        content = path.read_bytes()
        observed = hashlib.sha256(content).hexdigest()
        if observed != item.sha256:
            raise ValueError(f"fixture hash mismatch: {item.path}")
        inputs.append((item, content))
    return inputs


def _feature_hash(
    catalog: PITCatalog,
    store: CanonicalStore,
    snapshot_id: str,
    records: list[CanonicalRecord],
) -> str:
    as_of = max(_effective_query_time(record) for record in records)
    repository = AsOfRepository(catalog, store)
    context = AsOfContext(snapshot_id=snapshot_id, as_of=as_of)
    instruments = repository.active_instruments(context)
    features: list[dict[str, object]] = []
    for instrument in instruments:
        bars = repository.price_bars(instrument.instrument_id, context)
        closes = [bar.close for bar in bars]
        features.append(
            {
                "instrument_id": instrument.instrument_id,
                "bar_count": len(bars),
                "last_close": closes[-1] if closes else None,
                "mean_close": sum(closes) / len(closes) if closes else None,
            }
        )
    return _hash_json(features)


def _effective_query_time(record: CanonicalRecord) -> datetime:
    if isinstance(record, PriceBarRecord):
        return max(record.available_at, record.event_time)
    return record.available_at


def _hash_json(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
