from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from typer.testing import CliRunner

from hanalpha.cli import app
from hanalpha.config import SecretSettings
from hanalpha.ops.artifact_registry import ArtifactRegistry, ArtifactType
from hanalpha.ops.artifacts import sha256_file, write_immutable_json
from hanalpha.pit.source_audit import audit_probe_manifest
from hanalpha.pit.source_probe import ProbeSource, SourceProbeError, run_bounded_source_probe

NOW = datetime(2024, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_sec_probe_is_bounded_redacted_and_registry_resolvable(tmp_path) -> None:
    seen_user_agent = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_user_agent
        seen_user_agent = request.headers["user-agent"]
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "cik": "320193",
                "tickers": ["AAPL"],
                "filings": {
                    "recent": {
                        "form": ["10-K", "10-K/A"],
                        "acceptanceDateTime": [
                            "2023-01-01T15:00:00Z",
                            "2023-01-02T21:00:00Z",
                        ],
                    }
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        path, manifest = await run_bounded_source_probe(
            ProbeSource.SEC_EDGAR,
            ("320193",),
            output_root=tmp_path / "sec",
            secrets=SecretSettings(sec_user_agent="Han Alpha Research operations@hanalpha.test"),
            at=NOW,
            client=client,
        )
    serialized = json.dumps(manifest)
    assert seen_user_agent == "Han Alpha Research operations@hanalpha.test"
    assert "operations@hanalpha.test" not in serialized
    assert manifest["bounded"] is True
    assert manifest["secrets_redacted"] is True
    assert manifest["responses"][0]["effective_time_semantics"].startswith("EDGAR")
    registry = ArtifactRegistry(tmp_path / "registry.sqlite3")
    try:
        artifact_id = registry.register(
            path,
            artifact_type=ArtifactType.RAW_SAMPLE_MANIFEST,
            status="VERIFIED",
            at=NOW,
        )
        assert registry.resolve(
            artifact_id, expected_type=ArtifactType.RAW_SAMPLE_MANIFEST
        ).verified
        audits = audit_probe_manifest(path, output_root=tmp_path / "sec-audits")
        assert {document["decision"] for _, _, document in audits} == {"PASS"}
        for audit_path, artifact_type, document in audits:
            audit_id = registry.register(
                audit_path,
                artifact_type=artifact_type,
                status="VERIFIED",
                at=NOW,
            )
            claim = document["qualifies_checks"][0]
            assert registry.resolve(
                audit_id,
                expected_type=artifact_type,
                required_claim=claim,
            ).verified
    finally:
        registry.close()


@pytest.mark.asyncio
async def test_fred_probe_preserves_vintages_without_serializing_key(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = (
            {"vintage_dates": ["2023-01-01", "2024-01-01"]}
            if request.url.path.endswith("vintagedates")
            else {
                "observations": [
                    {
                        "date": "2023-01-01",
                        "realtime_start": "2023-01-01",
                        "realtime_end": "2023-01-31",
                        "value": "1.0",
                    }
                ]
            }
        )
        assert request.url.params["api_key"] == "fred-secret"
        return httpx.Response(200, headers={"content-type": "application/json"}, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        path, manifest = await run_bounded_source_probe(
            ProbeSource.FRED_ALFRED,
            ("CPIAUCSL",),
            output_root=tmp_path / "fred",
            secrets=SecretSettings(fred_api_key="fred-secret"),
            at=NOW,
            client=client,
        )
    assert manifest["request_count"] == 2
    assert "fred-secret" not in json.dumps(manifest)
    assert {item["name"] for item in manifest["responses"]} == {
        "observations-CPIAUCSL",
        "vintages-CPIAUCSL",
    }
    audits = audit_probe_manifest(path, output_root=tmp_path / "fred-audits")
    decisions = {artifact_type: document["decision"] for _, artifact_type, document in audits}
    assert decisions[ArtifactType.REVISION_AUDIT] == "PASS"
    assert decisions[ArtifactType.TIMESTAMP_AUDIT] == "BLOCKED"


@pytest.mark.asyncio
async def test_probe_rejects_missing_identity_credentials_and_unbounded_scope(tmp_path) -> None:
    with pytest.raises(ValueError, match="at least one"):
        await run_bounded_source_probe(
            ProbeSource.SEC_EDGAR,
            (),
            output_root=tmp_path,
            secrets=SecretSettings(sec_user_agent="Han Alpha ops@hanalpha.test"),
            at=NOW,
        )
    with pytest.raises(ValueError, match="real project identity"):
        await run_bounded_source_probe(
            ProbeSource.SEC_EDGAR,
            ("320193",),
            output_root=tmp_path,
            secrets=SecretSettings(sec_user_agent="contact@example.com"),
            at=NOW,
        )
    with pytest.raises(ValueError, match="invalid SEC CIK"):
        await run_bounded_source_probe(
            ProbeSource.SEC_EDGAR,
            ("invalid",),
            output_root=tmp_path,
            secrets=SecretSettings(sec_user_agent="Han Alpha ops@hanalpha.test"),
            at=NOW,
        )
    with pytest.raises(ValueError, match="FRED_API_KEY"):
        await run_bounded_source_probe(
            ProbeSource.FRED_ALFRED,
            ("CPIAUCSL",),
            output_root=tmp_path,
            secrets=SecretSettings(),
            at=NOW,
        )

    with pytest.raises(ValueError, match="MASSIVE_API_KEY"):
        await run_bounded_source_probe(
            ProbeSource.MASSIVE,
            ("AAPL",),
            output_root=tmp_path,
            secrets=SecretSettings(),
            at=NOW,
        )
    with pytest.raises(ValueError, match="bounded"):
        await run_bounded_source_probe(
            ProbeSource.MASSIVE,
            tuple(f"TICKER{index}" for index in range(8)),
            output_root=tmp_path,
            secrets=SecretSettings(massive_api_key="secret"),
            at=NOW,
        )


def test_probe_cli_reports_configuration_error_without_traceback(tmp_path) -> None:
    cli = CliRunner().invoke(
        app,
        [
            "pit",
            "probe-source",
            "--source",
            "sec_edgar",
            "--identifier",
            "320193",
            "--output",
            str(tmp_path / "cli"),
        ],
    )
    assert cli.exit_code == 2
    assert "SEC_USER_AGENT must contain a real project identity" in cli.output
    assert "Traceback" not in cli.output


@pytest.mark.asyncio
async def test_massive_probe_audits_stable_ids_and_delisted_history(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        ticker = request.url.params.get("ticker") or request.url.path.rsplit("/", 1)[-1]
        if "/tickers/" in request.url.path:
            payload = {
                "status": "OK",
                "results": {
                    "ticker": ticker,
                    "cik": "0000000001",
                    "active": ticker == "LIVE",
                },
            }
        elif request.url.path.endswith("splits"):
            payload = {
                "status": "OK",
                "results": [{"execution_date": "2023-01-03"}],
            }
        else:
            payload = {
                "status": "DELAYED",
                "results": [{"declaration_date": "2023-01-02"}],
            }
        assert request.url.params["apiKey"] == "massive-secret"
        return httpx.Response(200, headers={"content-type": "application/json"}, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        path, manifest = await run_bounded_source_probe(
            ProbeSource.MASSIVE,
            ("LIVE", "DEAD"),
            output_root=tmp_path / "massive",
            secrets=SecretSettings(massive_api_key="massive-secret"),
            at=NOW,
            client=client,
        )
    assert manifest["request_count"] == 6
    assert "massive-secret" not in json.dumps(manifest)
    audits = audit_probe_manifest(path, output_root=tmp_path / "massive-audits")
    decisions = {artifact_type: document["decision"] for _, artifact_type, document in audits}
    assert decisions[ArtifactType.SYMBOLOGY_AUDIT] == "PASS"
    assert decisions[ArtifactType.SURVIVORSHIP_AUDIT] == "PASS"
    assert decisions[ArtifactType.TIMESTAMP_AUDIT] == "BLOCKED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(200, headers={"content-type": "text/html"}, text="no"), "NON_JSON"),
        (httpx.Response(200, headers={"content-type": "application/json"}, json=[]), "NON_OBJECT"),
        (
            httpx.Response(200, headers={"content-type": "application/json"}, content=b"{"),
            "JSONDecodeError",
        ),
        (
            httpx.Response(
                500,
                headers={"content-type": "application/json"},
                json={"cik": "1", "filings": {}},
            ),
            "HTTPStatusError",
        ),
        (
            httpx.Response(200, headers={"content-type": "application/json"}, json={}),
            "SUBMISSIONS_FIELDS_MISSING",
        ),
    ],
)
async def test_probe_fails_closed_on_protocol_errors(tmp_path, response, error) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: response)
    ) as client:
        with pytest.raises(SourceProbeError, match=error):
            await run_bounded_source_probe(
                ProbeSource.SEC_EDGAR,
                ("1",),
                output_root=tmp_path,
                secrets=SecretSettings(sec_user_agent="Han Alpha ops@hanalpha.test"),
                at=NOW,
                client=client,
            )


def test_probe_audit_rejects_unbound_or_invalid_evidence(tmp_path) -> None:
    manifest_path = tmp_path / "manifest.json"
    write_immutable_json(manifest_path, {"schema_version": "wrong"})
    with pytest.raises(ValueError, match="unsupported"):
        audit_probe_manifest(manifest_path, output_root=tmp_path / "audit")

    blocked_path = tmp_path / "blocked.json"
    write_immutable_json(
        blocked_path,
        {
            "schema_version": "pit-raw-sample-manifest-v1",
            "decision": "BLOCKED",
            "bounded": True,
        },
    )
    with pytest.raises(ValueError, match="did not pass"):
        audit_probe_manifest(blocked_path, output_root=tmp_path / "audit")

    raw = tmp_path / "raw.json"
    write_immutable_json(raw, ["not", "an", "object"])
    invalid_payload_path = tmp_path / "invalid-payload.json"
    write_immutable_json(
        invalid_payload_path,
        {
            "schema_version": "pit-raw-sample-manifest-v1",
            "decision": "PASS",
            "bounded": True,
            "source_id": "sec_edgar",
            "responses": [
                {
                    "name": "bad",
                    "file": raw.name,
                    "sha256": sha256_file(raw),
                }
            ],
        },
    )
    with pytest.raises(ValueError, match="not an object"):
        audit_probe_manifest(invalid_payload_path, output_root=tmp_path / "audit")

    empty_path = tmp_path / "empty.json"
    write_immutable_json(
        empty_path,
        {
            "schema_version": "pit-raw-sample-manifest-v1",
            "decision": "PASS",
            "bounded": True,
            "source_id": "unknown",
            "responses": [],
        },
    )
    with pytest.raises(ValueError, match="no payloads"):
        audit_probe_manifest(empty_path, output_root=tmp_path / "audit")

    object_payload = tmp_path / "object.json"
    write_immutable_json(object_payload, {})
    unknown_path = tmp_path / "unknown.json"
    write_immutable_json(
        unknown_path,
        {
            "schema_version": "pit-raw-sample-manifest-v1",
            "decision": "PASS",
            "bounded": True,
            "source_id": "unknown",
            "responses": [
                {
                    "name": "unknown",
                    "file": object_payload.name,
                    "sha256": sha256_file(object_payload),
                }
            ],
        },
    )
    with pytest.raises(ValueError, match="unsupported source probe"):
        audit_probe_manifest(unknown_path, output_root=tmp_path / "audit")

    hash_mismatch_path = tmp_path / "hash-mismatch.json"
    write_immutable_json(
        hash_mismatch_path,
        {
            "schema_version": "pit-raw-sample-manifest-v1",
            "decision": "PASS",
            "bounded": True,
            "source_id": "sec_edgar",
            "responses": [
                {
                    "name": "tampered",
                    "file": object_payload.name,
                    "sha256": "0" * 64,
                }
            ],
        },
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        audit_probe_manifest(hash_mismatch_path, output_root=tmp_path / "audit")

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    traversal_path = evidence_dir / "traversal.json"
    write_immutable_json(
        traversal_path,
        {
            "schema_version": "pit-raw-sample-manifest-v1",
            "decision": "PASS",
            "bounded": True,
            "source_id": "sec_edgar",
            "responses": [
                {
                    "name": "escape",
                    "file": "../object.json",
                    "sha256": sha256_file(object_payload),
                }
            ],
        },
    )
    with pytest.raises(ValueError, match="escapes"):
        audit_probe_manifest(traversal_path, output_root=tmp_path / "audit")


def test_sec_audit_blocks_naive_timestamps_and_missing_lineage(tmp_path) -> None:
    raw = tmp_path / "raw.json"
    write_immutable_json(
        raw,
        {
            "cik": "",
            "tickers": [],
            "filings": {
                "recent": {
                    "form": ["10-K"],
                    "acceptanceDateTime": ["not-a-timestamp"],
                }
            },
        },
    )
    manifest_path = tmp_path / "manifest.json"
    write_immutable_json(
        manifest_path,
        {
            "schema_version": "pit-raw-sample-manifest-v1",
            "decision": "PASS",
            "bounded": True,
            "source_id": "sec_edgar",
            "responses": [
                {
                    "name": "submissions",
                    "file": raw.name,
                    "sha256": sha256_file(raw),
                }
            ],
        },
    )
    audits = audit_probe_manifest(manifest_path, output_root=tmp_path / "audits")
    assert {document["decision"] for _, _, document in audits} == {"BLOCKED"}
    assert all(not document["qualifies_checks"] for _, _, document in audits)
