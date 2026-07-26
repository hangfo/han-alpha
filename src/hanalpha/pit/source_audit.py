from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from hanalpha.ops.artifact_registry import ArtifactType
from hanalpha.ops.artifacts import sha256_file, write_immutable_json
from hanalpha.simulation.events import canonical_hash


def audit_probe_manifest(
    manifest_path: Path,
    *,
    output_root: Path,
) -> tuple[tuple[Path, ArtifactType, dict[str, Any]], ...]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "pit-raw-sample-manifest-v1":
        raise ValueError("unsupported raw sample manifest")
    if manifest.get("decision") != "PASS" or manifest.get("bounded") is not True:
        raise ValueError("raw sample manifest did not pass its bounded access checks")
    source = str(manifest.get("source_id"))
    payloads = _load_bound_payloads(manifest_path.parent, manifest)
    if source == "sec_edgar":
        audits = _audit_sec(payloads)
    elif source == "fred_alfred":
        audits = _audit_fred(payloads)
    elif source == "massive":
        audits = _audit_massive(payloads)
    else:
        raise ValueError(f"unsupported source probe: {source}")
    written: list[tuple[Path, ArtifactType, dict[str, Any]]] = []
    for artifact_type, payload in audits:
        effective_from = _manifest_observed_at(manifest)
        body = {
            "schema_version": f"pit-{artifact_type.value.lower().replace('_', '-')}-v1",
            "artifact_type": artifact_type.value,
            "source_id": source,
            "raw_sample_manifest_sha256": sha256_file(manifest_path),
            "effective_from": effective_from.isoformat(),
            "expires_at": (effective_from + timedelta(days=90)).isoformat(),
            **payload,
        }
        document = {"artifact_id": canonical_hash(body), **body}
        path = output_root / f"{document['artifact_id']}.json"
        write_immutable_json(path, document)
        written.append((path, artifact_type, document))
    return tuple(written)


def _load_bound_payloads(root: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    resolved_root = root.resolve()
    for response in manifest.get("responses", []):
        path = (root / str(response["normalized_file"])).resolve()
        if not path.is_relative_to(resolved_root):
            raise ValueError("raw sample path escapes the evidence directory")
        if sha256_file(path) != response["normalized_sha256"]:
            raise ValueError(f"raw sample hash mismatch: {response['name']}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"raw sample is not an object: {response['name']}")
        payloads[str(response["name"])] = payload
    if not payloads:
        raise ValueError("raw sample manifest contains no payloads")
    return payloads


def _audit_sec(
    payloads: dict[str, dict[str, Any]],
) -> tuple[tuple[ArtifactType, dict[str, Any]], ...]:
    forms: set[str] = set()
    timestamps: list[str] = []
    ciks: set[str] = set()
    tickers: set[str] = set()
    for payload in payloads.values():
        ciks.add(str(payload.get("cik", "")))
        tickers.update(str(value) for value in payload.get("tickers", []))
        recent = payload.get("filings", {}).get("recent", {})
        forms.update(str(value) for value in recent.get("form", []))
        timestamps.extend(str(value) for value in recent.get("acceptanceDateTime", []))
    timezone_aware = bool(timestamps) and all(_timezone_aware(value) for value in timestamps)
    amendment_forms = {"10-K/A", "10-Q/A"} & forms
    return (
        (
            ArtifactType.TIMESTAMP_AUDIT,
            {
                "decision": "PASS" if timezone_aware else "BLOCKED",
                "qualifies_checks": (
                    [
                        "public_acceptance_timestamp",
                        "source_timestamp_semantics",
                        "timezone_defined",
                    ]
                    if timezone_aware
                    else []
                ),
                "acceptance_timestamp_count": len(timestamps),
                "timezone_aware": timezone_aware,
                "available_at_policy": "EDGAR acceptanceDateTime then next exchange-tradable instant",
                "limitations": ["Exchange-calendar mapping is a separate required artifact."],
            },
        ),
        (
            ArtifactType.REVISION_AUDIT,
            {
                "decision": "PASS" if amendment_forms else "BLOCKED",
                "qualifies_checks": (
                    ["amendment_and_revision_lineage", "revision_retention"]
                    if amendment_forms
                    else []
                ),
                "forms_observed": sorted(forms),
                "amendment_forms_observed": sorted(amendment_forms),
                "lineage_key": "CIK + accessionNumber + form amendment suffix",
            },
        ),
        (
            ArtifactType.SYMBOLOGY_AUDIT,
            {
                "decision": "PASS" if all(ciks) and tickers else "BLOCKED",
                "qualifies_checks": (
                    ["stable_instrument_identifier"] if all(ciks) and tickers else []
                ),
                "ciks": sorted(ciks),
                "tickers": sorted(tickers),
                "mapping_policy": "CIK authoritative; ticker aliases are time-bounded evidence",
            },
        ),
    )


def _audit_fred(
    payloads: dict[str, dict[str, Any]],
) -> tuple[tuple[ArtifactType, dict[str, Any]], ...]:
    observations = [
        item
        for name, payload in payloads.items()
        if name.startswith("observations-")
        for item in payload.get("observations", [])
    ]
    vintages = {
        str(value)
        for name, payload in payloads.items()
        if name.startswith("vintages-")
        for value in payload.get("vintage_dates", [])
    }
    realtime_complete = bool(observations) and all(
        item.get("realtime_start") and item.get("realtime_end") for item in observations
    )
    return (
        (
            ArtifactType.REVISION_AUDIT,
            {
                "decision": "PASS" if realtime_complete and vintages else "BLOCKED",
                "qualifies_checks": (
                    ["revision_retention", "vintage_observations", "revision_dates"]
                    if realtime_complete and vintages
                    else []
                ),
                "observation_count": len(observations),
                "vintage_count": len(vintages),
                "realtime_periods_present": realtime_complete,
                "vintage_dates": sorted(vintages),
            },
        ),
        (
            ArtifactType.TIMESTAMP_AUDIT,
            {
                "decision": "BLOCKED",
                "qualifies_checks": [],
                "date_level_vintages_present": bool(vintages),
                "release_time_policy": None,
                "limitations": [
                    "ALFRED vintage dates do not prove an intraday tradable release time.",
                    "Register an authoritative release timestamp or a conservative next-session lag.",
                ],
            },
        ),
    )


def _audit_massive(
    payloads: dict[str, dict[str, Any]],
) -> tuple[tuple[ArtifactType, dict[str, Any]], ...]:
    ticker_records = [
        payload.get("results", {})
        for name, payload in payloads.items()
        if name.startswith("ticker-")
    ]
    active_states = {record.get("active") for record in ticker_records}
    stable_ids = all(
        record.get("ticker") and (record.get("cik") or record.get("composite_figi"))
        for record in ticker_records
    )
    action_dates = [
        row.get("execution_date") or row.get("declaration_date") or row.get("ex_dividend_date")
        for name, payload in payloads.items()
        if name.startswith(("splits-", "dividends-"))
        for row in payload.get("results", [])
    ]
    return (
        (
            ArtifactType.SYMBOLOGY_AUDIT,
            {
                "decision": "PASS" if ticker_records and stable_ids else "BLOCKED",
                "qualifies_checks": (
                    ["stable_instrument_identifier"] if ticker_records and stable_ids else []
                ),
                "record_count": len(ticker_records),
                "stable_identifiers_present": stable_ids,
            },
        ),
        (
            ArtifactType.SURVIVORSHIP_AUDIT,
            {
                "decision": "PASS" if active_states == {True, False} else "BLOCKED",
                "qualifies_checks": (
                    ["delisted_history"] if active_states == {True, False} else []
                ),
                "active_states_observed": sorted(
                    str(value) for value in active_states if value is not None
                ),
                "limitations": ["Both active and delisted samples are mandatory."],
            },
        ),
        (
            ArtifactType.TIMESTAMP_AUDIT,
            {
                "decision": "BLOCKED",
                "qualifies_checks": [],
                "corporate_action_date_count": len(action_dates),
                "availability_time_policy": None,
                "limitations": [
                    "Event dates alone do not prove the vendor's historical availability timestamp."
                ],
            },
        ),
    )


def _timezone_aware(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _manifest_observed_at(manifest: dict[str, Any]) -> datetime:
    values = [
        datetime.fromisoformat(str(response["observed_at"]))
        for response in manifest.get("responses", [])
    ]
    if not values or any(value.tzinfo is None for value in values):
        raise ValueError("raw sample manifest has no timezone-aware observation time")
    return min(values).astimezone(UTC)
