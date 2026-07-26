from __future__ import annotations

import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import hanalpha.cli as cli_module
import hanalpha.ops.external_runners as external_runners_module
import hanalpha.ops.onboarding as onboarding_module
from hanalpha.cli import app
from hanalpha.config import (
    SecretSettings,
    clear_secret_overrides,
    install_secret_overrides,
    load_config,
)
from hanalpha.ops.artifact_registry import ArtifactRegistry, ArtifactType
from hanalpha.ops.artifacts import write_immutable_json
from hanalpha.ops.external_runners import E1Scope, e1_progress, run_r1_source
from hanalpha.ops.onboarding import (
    OperatorStatus,
    github_safe_summary,
    inspect_ibkr_onboarding,
    install_official_ibapi_archive,
    launch_ibkr_application,
    status_exit,
    wait_for_ibkr_socket,
)
from hanalpha.ops.secrets import (
    EnvironmentSecretProvider,
    LocalSecret,
    MacOSKeychainSecretProvider,
    migrate_env_secrets,
    redact_text,
    settings_from_provider,
)
from hanalpha.pit.source_probe import ProbeSource

NOW = datetime(2024, 1, 1, tzinfo=UTC)


class FakeProvider:
    def __init__(self, values: dict[LocalSecret, str] | None = None) -> None:
        self.values = values or {}

    def get(self, name: LocalSecret) -> str | None:
        return self.values.get(name)

    def set(self, name: LocalSecret, value: str) -> None:
        self.values[name] = value


def test_keychain_backend_never_places_secret_in_argv() -> None:
    calls: list[tuple[list[str], str | None]] = []

    def runner(arguments, **kwargs):
        calls.append((arguments, kwargs.get("input")))
        if "find-generic-password" in arguments:
            return subprocess.CompletedProcess(arguments, 0, "keychain-value\n", "")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    provider = MacOSKeychainSecretProvider(runner=runner)
    assert provider.get(LocalSecret.FRED_CREDENTIAL) == "keychain-value"
    provider.set(LocalSecret.FRED_CREDENTIAL, "top-secret")
    assert all("top-secret" not in argument for arguments, _ in calls for argument in arguments)
    assert calls[-1][1] == "top-secret\n"


def test_secret_child_uses_stdin_ipc_and_scrubs_inherited_environment(monkeypatch) -> None:
    captured = {}

    def run(arguments, **kwargs):
        captured["arguments"] = arguments
        captured.update(kwargs)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setenv("IBKR_ACCOUNT", "inherited-account")
    monkeypatch.setenv("FRED_API_KEY", "inherited-key")
    monkeypatch.setattr(cli_module.subprocess, "run", run)
    secrets = SecretSettings(
        _env_file=None,
        ibkr_account="paper-account",
        fred_api_key="fred-value",
    )
    assert cli_module._run_secret_child(["doctor"], secrets) == 0
    assert "paper-account" not in " ".join(captured["arguments"])
    assert "IBKR_ACCOUNT" not in captured["env"]
    assert "FRED_API_KEY" not in captured["env"]
    assert captured["env"][cli_module.SECRET_STDIN_MARKER] == "1"
    assert '"ibkr_account": "paper-account"' in captured["input"]
    assert '"fred_api_key": "fred-value"' in captured["input"]

    install_secret_overrides({"ibkr_account": "ipc-account"})
    try:
        _, loaded = load_config()
        assert loaded.ibkr_account == "ipc-account"
        with pytest.raises(ValueError, match="unsupported"):
            install_secret_overrides({"not_allowed": "value"})
    finally:
        clear_secret_overrides()


def test_official_ibapi_installer_requires_attestation_and_rejects_traversal(
    tmp_path, monkeypatch
) -> None:
    valid = tmp_path / "twsapi_macunix.1048.01.zip"
    with zipfile.ZipFile(valid, "w") as bundle:
        bundle.writestr("IBJts/source/pythonclient/setup.py", "pass")
    with pytest.raises(ValueError, match="LICENSE"):
        install_official_ibapi_archive(valid, license_accepted=False)

    calls: list[list[str]] = []
    monkeypatch.setattr(onboarding_module, "_ibapi_version", lambda: "10.48.1")
    version = install_official_ibapi_archive(
        valid,
        license_accepted=True,
        runner=lambda arguments, **_kwargs: (
            calls.append(arguments)
            or subprocess.CompletedProcess(arguments, 0, "", "")
        ),
    )
    assert version == "10.48.1"
    assert calls[0][:4] == [
        onboarding_module.sys.executable,
        "-m",
        "pip",
        "install",
    ]
    assert "--no-deps" in calls[0]

    unsafe = tmp_path / "twsapi-unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as bundle:
        bundle.writestr("../escape", "bad")
    with pytest.raises(ValueError, match="UNSAFE_ARCHIVE_MEMBER"):
        install_official_ibapi_archive(unsafe, license_accepted=True)


def test_secret_provider_failure_paths_remain_value_free(tmp_path) -> None:
    environment = EnvironmentSecretProvider(SecretSettings(_env_file=None))
    assert environment.get(LocalSecret.IBKR_ACCOUNT) is None
    with pytest.raises(RuntimeError, match="read-only"):
        environment.set(LocalSecret.IBKR_ACCOUNT, "not-stored")

    def failed(arguments, **kwargs):
        return subprocess.CompletedProcess(arguments, 44, "", "private-error")

    keychain = MacOSKeychainSecretProvider(runner=failed)
    assert keychain.get(LocalSecret.IBKR_ACCOUNT) is None
    with pytest.raises(ValueError, match="empty"):
        keychain.set(LocalSecret.IBKR_ACCOUNT, "")
    with pytest.raises(RuntimeError, match="Keychain write failed"):
        keychain.set(LocalSecret.IBKR_ACCOUNT, "not-rendered")
    with pytest.raises(FileNotFoundError):
        migrate_env_secrets(tmp_path / "missing", keychain, scrub=True)


def test_env_migration_can_scrub_values_and_overlay_settings(tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(("IBKR_ACCOUNT=DU1", "FRED_API_KEY=fred", "IBKR_PORT=7497")) + "\n",
        encoding="utf-8",
    )
    provider = FakeProvider()
    migrated = migrate_env_secrets(env_path, provider, scrub=True)
    assert set(migrated) == {LocalSecret.IBKR_ACCOUNT, LocalSecret.FRED_CREDENTIAL}
    assert "DU1" not in env_path.read_text(encoding="utf-8")
    settings = settings_from_provider(
        provider,
        fallback=SecretSettings(_env_file=None, ibkr_port=7497),
    )
    assert settings.ibkr_account == "DU1"
    assert settings.fred_api_key == "fred"


def test_redaction_covers_urls_headers_tracebacks_and_known_values() -> None:
    secret = "sk-sensitive-value"
    rendered = redact_text(
        "GET https://vendor.test/x?apiKey=sk-sensitive-value "
        "Authorization: BearerToken account=DU1234567 password=hunter2",
        secrets=(secret,),
    )
    assert secret not in rendered
    assert "DU1234567" not in rendered
    assert "hunter2" not in rendered
    assert rendered.count("[REDACTED]") >= 3


def test_ibkr_onboarding_is_redacted_and_classifies_human_gates(tmp_path) -> None:
    config, _ = load_config()
    provider = FakeProvider({LocalSecret.IBKR_ACCOUNT: "DU-LOCAL"})
    secrets = SecretSettings(
        _env_file=None,
        hanalpha_env="paper",
        ibkr_port=7497,
        ibkr_client_id=41,
    )
    blocked = inspect_ibkr_onboarding(
        config,
        secrets,
        repository_root=tmp_path,
        provider=provider,
        at=NOW,
        applications=(),
        archives=(),
        module_available=lambda: False,
        socket_available=lambda _host, _port: False,
    )
    assert blocked["status"] == OperatorStatus.BLOCKED_HUMAN_ACTION
    assert "DU-LOCAL" not in str(blocked)
    assert status_exit(blocked["status"]) == 20
    summary = github_safe_summary(blocked)
    assert "secrets_redacted=true" in summary
    assert "DU-LOCAL" not in summary

    (tmp_path / "pyproject.toml").touch()
    ready = inspect_ibkr_onboarding(
        config,
        secrets,
        repository_root=tmp_path,
        provider=provider,
        at=NOW,
        applications=(tmp_path / "Trader Workstation.app",),
        archives=(),
        module_available=lambda: True,
        socket_available=lambda _host, _port: True,
    )
    assert ready["status"] == OperatorStatus.PASS
    assert ready["next_permitted_command"] == "hanalpha e1 run --scope api"

    unsafe_config = config.model_copy(
        update={"execution": config.execution.model_copy(update={"broker_write_enabled": True})}
    )
    ambiguous = inspect_ibkr_onboarding(
        unsafe_config,
        SecretSettings(_env_file=None, hanalpha_env="live", ibkr_port=1234),
        repository_root=tmp_path,
        provider=FakeProvider(),
        at=NOW,
        applications=(tmp_path / "TWS.app",),
        archives=(tmp_path / "twsapi.zip",),
        module_available=lambda: False,
        socket_available=lambda _host, _port: False,
    )
    assert "INSTALL_OFFICIAL_IBAPI_FROM_LOCAL_ARCHIVE" in ambiguous["blockers"]
    assert "LOGIN_PAPER_COMPLETE_2FA_AND_ENABLE_SOCKET" in ambiguous["blockers"]
    assert "RESOLVE_PAPER_LIVE_ENVIRONMENT_AMBIGUITY" in ambiguous["blockers"]
    assert "RESTORE_ZERO_WRITE_CONFIGURATION" in ambiguous["blockers"]


def test_onboarding_launch_is_bounded_to_detected_application(tmp_path, monkeypatch) -> None:
    with pytest.raises(RuntimeError, match="not installed"):
        launch_ibkr_application(())

    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(onboarding_module.subprocess, "run", run)
    application = tmp_path / "IB Gateway.app"
    assert launch_ibkr_application((application,)) == "IB_GATEWAY"
    assert calls == [["/usr/bin/open", str(application)]]

    monkeypatch.setattr(
        onboarding_module.subprocess,
        "run",
        lambda arguments, **kwargs: subprocess.CompletedProcess(arguments, 1, "", ""),
    )
    with pytest.raises(RuntimeError, match="failed to launch"):
        launch_ibkr_application((application,))


def test_local_detection_helpers_are_bounded_and_non_mutating() -> None:
    assert isinstance(onboarding_module._ibkr_applications(), tuple)
    assert isinstance(onboarding_module._api_archives(), tuple)
    assert onboarding_module._port_ready("127.0.0.1", 1) is False
    assert onboarding_module._ibapi_version() is None
    assert onboarding_module._app_kind(Path("TWS.app")) == "TWS"
    attempts = iter((False, True))
    assert wait_for_ibkr_socket(
        "127.0.0.1",
        7497,
        timeout_seconds=1,
        probe=lambda _host, _port: next(attempts),
        interval_seconds=0,
    )
    assert (
        wait_for_ibkr_socket(
            "127.0.0.1",
            7497,
            timeout_seconds=0,
            probe=lambda _host, _port: False,
        )
        is False
    )
    with pytest.raises(ValueError, match="between 0 and 300"):
        wait_for_ibkr_socket("127.0.0.1", 7497, timeout_seconds=301)


def test_e1_progress_starts_with_bounded_next_action(tmp_path) -> None:
    progress = e1_progress(tmp_path / "api", E1Scope.API)
    assert progress["status"] == OperatorStatus.BLOCKED_HUMAN_ACTION
    assert progress["next_scenario"] == "empty_account"
    assert progress["missing_counts"]["empty_account"] == 5
    assert progress["invalid_session_count"] == 0


def test_e1_progress_counts_only_verified_eligible_scope_sessions(tmp_path, monkeypatch) -> None:
    sessions = tmp_path / "api" / "sessions"
    sessions.mkdir(parents=True)
    for scenario, target in external_runners_module.E1_SCENARIOS[E1Scope.API]:
        for index in range(target):
            (sessions / f"{scenario}-{index}").mkdir()
    (sessions / "wrong-scope").mkdir()

    def verify(path):
        if path.name == "wrong-scope":
            return SimpleNamespace(
                verified=True,
                manifest={
                    "safety_case_eligible": True,
                    "completed_orders_scope": "all",
                    "capture_scenario": "manual_order",
                },
            )
        return SimpleNamespace(
            verified=True,
            manifest={
                "safety_case_eligible": True,
                "completed_orders_scope": "api",
                "capture_scenario": path.name.rsplit("-", 1)[0],
            },
        )

    monkeypatch.setattr(external_runners_module, "verify_burn_in_manifest", verify)
    progress = e1_progress(tmp_path / "api", E1Scope.API)
    assert progress["status"] == OperatorStatus.PASS
    assert progress["next_scenario"] is None
    assert progress["invalid_session_count"] == 1


@pytest.mark.asyncio
async def test_r1_runner_fails_closed_before_network_and_before_rights(tmp_path) -> None:
    registry = ArtifactRegistry(tmp_path / "registry.sqlite3")
    try:
        missing = await run_r1_source(
            ProbeSource.SEC_EDGAR,
            output_root=tmp_path / "r1",
            registry=registry,
            secrets=SecretSettings(_env_file=None),
            at=NOW,
            execute=True,
        )
        assert missing["status"] == OperatorStatus.BLOCKED_HUMAN_ACTION
        assert missing["artifact_ids"] == []

        dry_run = await run_r1_source(
            ProbeSource.SEC_EDGAR,
            output_root=tmp_path / "r1",
            registry=registry,
            secrets=SecretSettings(
                _env_file=None,
                sec_user_agent="Han Alpha operations@hanalpha.test",
            ),
            at=NOW,
            execute=False,
        )
        assert dry_run["status"] == OperatorStatus.BLOCKED_HUMAN_ACTION
        assert dry_run["reason"] == "REAL_PROBE_REQUIRES_EXPLICIT_EXECUTE"
    finally:
        registry.close()


@pytest.mark.asyncio
async def test_r1_runner_executes_bounded_bundle_but_still_blocks_external_rights(
    tmp_path, monkeypatch
) -> None:
    async def fake_probe(source, identifiers, *, output_root, secrets, at):
        body = {
            "schema_version": "pit-raw-sample-manifest-v1",
            "artifact_type": ArtifactType.RAW_SAMPLE_MANIFEST.value,
            "artifact_id": "a" * 64,
            "decision": "PASS",
            "source_id": source.value,
            "identifiers": list(identifiers),
            "request_count": 1,
            "bounded": True,
            "all_http_success": True,
            "secrets_redacted": True,
            "qualifies_checks": [],
            "responses": [{"name": "fixture"}],
        }
        body["artifact_id"] = external_runners_module.canonical_hash(
            {key: value for key, value in body.items() if key != "artifact_id"}
        )
        path = output_root / "manifest.json"
        write_immutable_json(path, body)
        return path, body

    def fake_audit(manifest_path, *, output_root):
        document = {
            "schema_version": "pit-timestamp-audit-v1",
            "artifact_type": ArtifactType.TIMESTAMP_AUDIT.value,
            "decision": "BLOCKED",
            "qualifies_checks": [],
            "effective_from": NOW.isoformat(),
            "expires_at": datetime(2024, 2, 1, tzinfo=UTC).isoformat(),
        }
        path = output_root / "audit.json"
        write_immutable_json(path, document)
        return ((path, ArtifactType.TIMESTAMP_AUDIT, document),)

    monkeypatch.setattr(external_runners_module, "run_bounded_source_probe", fake_probe)
    monkeypatch.setattr(external_runners_module, "audit_probe_manifest", fake_audit)
    registry = ArtifactRegistry(tmp_path / "registry.sqlite3")
    try:
        report = await run_r1_source(
            ProbeSource.SEC_EDGAR,
            output_root=tmp_path / "r1",
            registry=registry,
            secrets=SecretSettings(
                _env_file=None,
                sec_user_agent="Han Alpha operations@hanalpha.test",
            ),
            at=NOW,
            execute=True,
        )
    finally:
        registry.close()
    assert report["status"] == OperatorStatus.BLOCKED_EXTERNAL_RIGHTS
    assert len(report["artifact_ids"]) == 2
    assert report["reviewer_bundle_id"]


def test_external_runner_cli_paths_are_structured_and_redacted(tmp_path, monkeypatch) -> None:
    provider = FakeProvider()
    settings = SecretSettings(_env_file=None)
    monkeypatch.setattr(cli_module, "_local_settings", lambda: (settings, provider))
    blocked_onboarding = {
        "schema_version": "hanalpha-local-onboarding-v1",
        "report_id": "b" * 64,
        "status": OperatorStatus.BLOCKED_HUMAN_ACTION,
        "checks": {"tws": False},
        "blockers": ["INSTALL_TWS"],
        "git_commit": "c" * 40,
        "secrets_redacted": True,
    }
    monkeypatch.setattr(
        cli_module,
        "inspect_ibkr_onboarding",
        lambda *args, **kwargs: blocked_onboarding,
    )
    runner = CliRunner()
    onboard = runner.invoke(
        app,
        [
            "local-onboard",
            "ibkr",
            "--output",
            str(tmp_path / "onboard"),
            "--github-summary",
        ],
    )
    assert onboard.exit_code == 20
    assert "secrets_redacted=true" in onboard.output

    e1 = runner.invoke(
        app,
        ["e1", "run", "--scope", "api", "--output", str(tmp_path / "e1")],
    )
    assert e1.exit_code == 20
    assert "INSTALL_TWS" in e1.output

    r1 = runner.invoke(
        app,
        [
            "r1",
            "run",
            "--source",
            "sec_edgar",
            "--output",
            str(tmp_path / "r1"),
            "--github-summary",
        ],
    )
    assert r1.exit_code == 20
    assert "STORE_REQUIRED_LOCAL_SECRET" in r1.output


def test_e1_cli_ready_path_runs_one_redacted_child_capture(tmp_path, monkeypatch) -> None:
    provider = FakeProvider({LocalSecret.IBKR_ACCOUNT: "DU-LOCAL"})
    settings = SecretSettings(
        _env_file=None,
        ibkr_account="DU-LOCAL",
        ibkr_port=7497,
        hanalpha_artifact_registry_path=str(tmp_path / "registry.sqlite3"),
    )
    monkeypatch.setattr(cli_module, "_local_settings", lambda: (settings, provider))
    monkeypatch.setattr(
        cli_module,
        "inspect_ibkr_onboarding",
        lambda *args, **kwargs: {
            "schema_version": "hanalpha-local-onboarding-v1",
            "report_id": "a" * 64,
            "status": OperatorStatus.PASS,
            "checks": {"ready": True},
            "blockers": [],
            "git_commit": "c" * 40,
            "secrets_redacted": True,
        },
    )
    child_calls: list[list[str]] = []

    def child(arguments, _secrets):
        child_calls.append(arguments)
        return 0

    monkeypatch.setattr(cli_module, "_run_secret_child", child)
    reports = iter(
        (
            {
                "schema_version": "e1-external-runner-progress-v1",
                "report_id": "1" * 64,
                "scope": E1Scope.API,
                "status": OperatorStatus.BLOCKED_HUMAN_ACTION,
                "verified_counts": {},
                "required_counts": {"empty_account": 5},
                "missing_counts": {"empty_account": 5},
                "invalid_session_count": 0,
                "next_scenario": "empty_account",
                "next_human_action": "CAPTURE_EMPTY_ACCOUNT",
                "secrets_redacted": True,
            },
            {
                "schema_version": "e1-external-runner-progress-v1",
                "report_id": "2" * 64,
                "scope": E1Scope.API,
                "status": OperatorStatus.PASS,
                "verified_counts": {"empty_account": 5},
                "required_counts": {"empty_account": 5},
                "missing_counts": {"empty_account": 0},
                "invalid_session_count": 0,
                "next_scenario": None,
                "next_human_action": None,
                "secrets_redacted": True,
            },
        )
    )
    monkeypatch.setattr(cli_module, "e1_progress", lambda *_args: next(reports))
    result = CliRunner().invoke(
        app,
        [
            "e1",
            "run",
            "--scope",
            "api",
            "--output",
            str(tmp_path / "e1"),
            "--execute",
            "--read-only-attested",
            "--github-summary",
        ],
    )
    assert result.exit_code == 0
    assert len(child_calls) == 3
    assert all("DU-LOCAL" not in " ".join(arguments) for arguments in child_calls)
    assert "--read-only-attested" in child_calls[0]
    assert child_calls[2][0] == "ibkr-burn-in-evaluate"
    assert "secrets_redacted=true" in result.output


def test_e1_cli_classifies_preflight_and_capture_failures(tmp_path, monkeypatch) -> None:
    provider = FakeProvider({LocalSecret.IBKR_ACCOUNT: "DU-LOCAL"})
    settings = SecretSettings(_env_file=None, ibkr_account="DU-LOCAL", ibkr_port=7497)
    monkeypatch.setattr(cli_module, "_local_settings", lambda: (settings, provider))
    monkeypatch.setattr(
        cli_module,
        "inspect_ibkr_onboarding",
        lambda *args, **kwargs: {"status": OperatorStatus.PASS},
    )
    base_report = {
        "schema_version": "e1-external-runner-progress-v1",
        "report_id": "3" * 64,
        "scope": E1Scope.ALL,
        "status": OperatorStatus.BLOCKED_HUMAN_ACTION,
        "verified_counts": {},
        "required_counts": {"manual_order": 4},
        "missing_counts": {"manual_order": 4},
        "invalid_session_count": 0,
        "next_scenario": "manual_order",
        "next_human_action": "CREATE_EVENT",
        "secrets_redacted": True,
    }
    monkeypatch.setattr(cli_module, "e1_progress", lambda *_args: dict(base_report))
    monkeypatch.setattr(cli_module, "_run_secret_child", lambda *_args: 2)
    preflight = CliRunner().invoke(
        app,
        [
            "e1",
            "run",
            "--scope",
            "all",
            "--output",
            str(tmp_path / "preflight"),
            "--execute",
        ],
    )
    assert preflight.exit_code == 20
    assert "ATTEST_CORRECT_TWS_OBSERVATION_MODE" in preflight.output

    outcomes = iter((0, 1))
    monkeypatch.setattr(cli_module, "_run_secret_child", lambda *_args: next(outcomes))
    capture = CliRunner().invoke(
        app,
        [
            "e1",
            "run",
            "--scope",
            "all",
            "--output",
            str(tmp_path / "capture"),
            "--execute",
            "--order-visibility-attested",
        ],
    )
    assert capture.exit_code == 1
    assert "INSPECT_REDACTED_LOCAL_CAPTURE_LOGS" in capture.output


def test_onboarding_ready_path_requires_attestation_then_registers_preflight(
    tmp_path, monkeypatch
) -> None:
    provider = FakeProvider({LocalSecret.IBKR_ACCOUNT: "DU-LOCAL"})
    settings = SecretSettings(
        _env_file=None,
        ibkr_account="DU-LOCAL",
        ibkr_port=7497,
        hanalpha_artifact_registry_path=str(tmp_path / "registry.sqlite3"),
    )
    monkeypatch.setattr(cli_module, "_local_settings", lambda: (settings, provider))
    monkeypatch.setattr(
        cli_module,
        "inspect_ibkr_onboarding",
        lambda *args, **kwargs: {
            "schema_version": "hanalpha-local-onboarding-v1",
            "report_id": "a" * 64,
            "status": OperatorStatus.PASS,
            "checks": {"ready": True},
            "blockers": [],
            "git_commit": "c" * 40,
            "next_permitted_command": "hanalpha e1 run --scope api",
            "secrets_redacted": True,
        },
    )
    runner = CliRunner()
    unattested = runner.invoke(
        app,
        ["local-onboard", "ibkr", "--output", str(tmp_path / "unattested")],
    )
    assert unattested.exit_code == 20
    assert "ATTEST_TWS_READ_ONLY_FOR_ACCOUNT_PREFLIGHT" in unattested.output

    child_calls: list[list[str]] = []
    monkeypatch.setattr(
        cli_module,
        "_run_secret_child",
        lambda arguments, _secrets: child_calls.append(arguments) or 0,
    )
    ready = runner.invoke(
        app,
        [
            "local-onboard",
            "ibkr",
            "--output",
            str(tmp_path / "ready"),
            "--read-only-attested",
        ],
    )
    assert ready.exit_code == 0
    assert child_calls[0][0] == "ibkr-preflight"
    assert "preflight_registered" in ready.output


def test_r1_cli_sanitizes_runner_exception(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        cli_module,
        "_local_settings",
        lambda: (
            SecretSettings(
                _env_file=None,
                sec_user_agent="Han Alpha operations@hanalpha.test",
            ),
            FakeProvider(),
        ),
    )

    async def failed(*args, **kwargs):
        raise cli_module.SourceProbeError("must-not-be-rendered")

    monkeypatch.setattr(cli_module, "run_r1_source", failed)
    result = CliRunner().invoke(
        app,
        [
            "r1",
            "run",
            "--source",
            "sec_edgar",
            "--output",
            str(tmp_path),
            "--execute",
        ],
    )
    assert result.exit_code == 1
    assert "must-not-be-rendered" not in result.output
    assert "SourceProbeError" in result.output


def test_local_secret_cli_migration_and_hidden_prompt(tmp_path, monkeypatch) -> None:
    provider = FakeProvider()
    monkeypatch.setattr(cli_module, "MacOSKeychainSecretProvider", lambda: provider)
    env_path = tmp_path / ".env"
    env_path.write_text("FRED_API_KEY=fred" + "\n", encoding="utf-8")
    runner = CliRunner()
    migration = runner.invoke(
        app,
        [
            "local-onboard",
            "migrate-env",
            "--env-file",
            str(env_path),
            "--scrub",
        ],
    )
    assert migration.exit_code == 0
    assert "migrated_secret_count" in migration.output
    secret = runner.invoke(
        app,
        ["local-onboard", "set-secret", "--name", "fred-api-key"],
        input="hidden-value\n",
    )
    assert secret.exit_code == 0
    assert "hidden-value" not in secret.output
    assert provider.get(LocalSecret.FRED_CREDENTIAL) == "hidden-value"
