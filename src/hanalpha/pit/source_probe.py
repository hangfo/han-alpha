from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx

from hanalpha.config import SecretSettings
from hanalpha.ops.artifacts import sha256_file, write_immutable_bytes, write_immutable_json
from hanalpha.simulation.events import canonical_hash


class ProbeSource(StrEnum):
    MASSIVE = "massive"
    SEC_EDGAR = "sec_edgar"
    FRED_ALFRED = "fred_alfred"


class SourceProbeError(RuntimeError):
    pass


async def run_bounded_source_probe(
    source: ProbeSource,
    identifiers: tuple[str, ...],
    *,
    output_root: Path,
    secrets: SecretSettings,
    at: datetime,
    client: httpx.AsyncClient | None = None,
) -> tuple[Path, dict[str, Any]]:
    if not identifiers:
        raise ValueError("at least one bounded probe identifier is required")
    maximum = 7 if source is ProbeSource.MASSIVE else 10
    if len(identifiers) > maximum:
        raise ValueError(f"{source.value} probe is bounded to {maximum} identifiers")
    requests = _requests(source, identifiers, secrets)
    external_client = client is not None
    http = client or httpx.AsyncClient(timeout=30, follow_redirects=False)
    responses: list[dict[str, Any]] = []
    try:
        for index, request in enumerate(requests):
            try:
                response = await http.get(
                    request["url"],
                    params=request["params"],
                    headers=request["headers"],
                )
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type.lower():
                    raise SourceProbeError(
                        f"{source.value}:{request['name']}:NON_JSON_RESPONSE"
                    )
                payload = response.json()
                if not isinstance(payload, dict):
                    raise SourceProbeError(
                        f"{source.value}:{request['name']}:NON_OBJECT_RESPONSE"
                    )
                response.raise_for_status()
                _validate_payload(source, request["name"], payload)
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                raise SourceProbeError(
                    f"{source.value}:{request['name']}:{type(exc).__name__}"
                ) from None
            destination = output_root / "raw" / f"{index:03d}-{request['name']}.json"
            write_immutable_bytes(
                destination,
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode()
                + b"\n",
            )
            responses.append(
                {
                    "name": request["name"],
                    "source_url": request["public_url"],
                    "file": str(destination.relative_to(output_root)),
                    "sha256": sha256_file(destination),
                    "bytes": destination.stat().st_size,
                    "http_status": response.status_code,
                    "content_type": content_type.split(";", 1)[0],
                    "observed_at": at.astimezone(UTC).isoformat(),
                    "effective_time_semantics": request["effective_time_semantics"],
                    "ingested_at": at.astimezone(UTC).isoformat(),
                }
            )
    finally:
        if not external_client:
            await http.aclose()
    body: dict[str, Any] = {
        "schema_version": "pit-raw-sample-manifest-v1",
        "decision": "PASS",
        "source_id": source.value,
        "identifiers": sorted(identifiers),
        "request_count": len(responses),
        "bounded": True,
        "all_http_success": all(item["http_status"] == 200 for item in responses),
        "secrets_redacted": True,
        "qualifies_checks": [],
        "responses": responses,
        "limitations": [
            "A successful bounded probe proves payload access, not license, retention, PIT semantics, survivorship or promotion qualification.",
            "Independent typed audits and reviewer receipts remain mandatory.",
        ],
    }
    manifest = {"artifact_id": canonical_hash(body), **body}
    manifest_path = output_root / f"{manifest['artifact_id']}.json"
    write_immutable_json(manifest_path, manifest)
    return manifest_path, manifest


def _requests(
    source: ProbeSource,
    identifiers: tuple[str, ...],
    secrets: SecretSettings,
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    if source is ProbeSource.SEC_EDGAR:
        user_agent = (secrets.sec_user_agent or "").strip()
        if "@" not in user_agent or "example." in user_agent.lower():
            raise ValueError("SEC_USER_AGENT must contain a real project identity and contact")
        for identifier in identifiers:
            digits = "".join(character for character in identifier if character.isdigit())
            if not digits or len(digits) > 10:
                raise ValueError(f"invalid SEC CIK: {identifier}")
            cik = digits.zfill(10)
            url = f"https://data.sec.gov/submissions/CIK{cik}.json"
            requests.append(
                {
                    "name": f"submissions-{cik}",
                    "url": url,
                    "public_url": url,
                    "params": {},
                    "headers": {
                        "User-Agent": user_agent,
                        "Accept": "application/json",
                        "Accept-Encoding": "gzip, deflate",
                    },
                    "effective_time_semantics": "EDGAR acceptanceDateTime per filing",
                }
            )
        return requests
    if source is ProbeSource.FRED_ALFRED:
        if not secrets.fred_api_key:
            raise ValueError("FRED_API_KEY is required")
        for identifier in identifiers:
            common = {
                "series_id": identifier,
                "api_key": secrets.fred_api_key,
                "file_type": "json",
            }
            requests.extend(
                [
                    {
                        "name": f"observations-{identifier}",
                        "url": "https://api.stlouisfed.org/fred/series/observations",
                        "public_url": "https://api.stlouisfed.org/fred/series/observations",
                        "params": {
                            **common,
                            "realtime_start": "1776-07-04",
                            "realtime_end": "9999-12-31",
                            "limit": 5000,
                            "sort_order": "desc",
                        },
                        "headers": {"Accept": "application/json"},
                        "effective_time_semantics": "ALFRED realtime_start/realtime_end",
                    },
                    {
                        "name": f"vintages-{identifier}",
                        "url": "https://api.stlouisfed.org/fred/series/vintagedates",
                        "public_url": "https://api.stlouisfed.org/fred/series/vintagedates",
                        "params": {**common, "limit": 1000, "sort_order": "desc"},
                        "headers": {"Accept": "application/json"},
                        "effective_time_semantics": "ALFRED vintage publication date",
                    },
                ]
            )
        return requests
    api_key = secrets.massive_api_key or secrets.polygon_api_key
    if not api_key:
        raise ValueError("MASSIVE_API_KEY is required")
    for identifier in identifiers:
        ticker = identifier.upper()
        requests.extend(
            [
                {
                    "name": f"ticker-{ticker}",
                    "url": f"https://api.massive.com/v3/reference/tickers/{ticker}",
                    "public_url": f"https://api.massive.com/v3/reference/tickers/{ticker}",
                    "params": {"apiKey": api_key},
                    "headers": {"Accept": "application/json"},
                    "effective_time_semantics": "reference record as returned at observed_at",
                },
                {
                    "name": f"splits-{ticker}",
                    "url": "https://api.massive.com/stocks/v1/splits",
                    "public_url": "https://api.massive.com/stocks/v1/splits",
                    "params": {"ticker": ticker, "limit": 100, "apiKey": api_key},
                    "headers": {"Accept": "application/json"},
                    "effective_time_semantics": "execution_date and observed_at",
                },
                {
                    "name": f"dividends-{ticker}",
                    "url": "https://api.massive.com/stocks/v1/dividends",
                    "public_url": "https://api.massive.com/stocks/v1/dividends",
                    "params": {"ticker": ticker, "limit": 100, "apiKey": api_key},
                    "headers": {"Accept": "application/json"},
                    "effective_time_semantics": "declaration/ex-dividend/pay dates and observed_at",
                },
            ]
        )
    return requests


def _validate_payload(source: ProbeSource, name: str, payload: dict[str, Any]) -> None:
    if source is ProbeSource.SEC_EDGAR:
        if "cik" not in payload or "filings" not in payload:
            raise SourceProbeError(f"sec_edgar:{name}:SUBMISSIONS_FIELDS_MISSING")
    elif source is ProbeSource.FRED_ALFRED:
        expected = "vintage_dates" if name.startswith("vintages-") else "observations"
        if not isinstance(payload.get(expected), list):
            raise SourceProbeError(f"fred_alfred:{name}:{expected.upper()}_MISSING")
    elif payload.get("status") not in {"OK", "DELAYED"} and "results" not in payload:
        raise SourceProbeError(f"massive:{name}:SUCCESS_STATUS_MISSING")
