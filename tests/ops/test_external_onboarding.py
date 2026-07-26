from __future__ import annotations

import ctypes
import subprocess
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import hanalpha.cli as cli_module
import hanalpha.execution.e1_scenarios as e1_scenarios_module
import hanalpha.ops.external_runners as external_runners_module
import hanalpha.ops.onboarding as onboarding_module
import hanalpha.ops.secrets as secrets_module
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


def test_native_keychain_provider_delegates_without_subprocess(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        secrets_module,
        "_macos_keychain_get",
        lambda service, account: calls.append(("get", service, account)) or "value",
    )
    monkeypatch.setattr(
        secrets_module,
        "_macos_keychain_set",
        lambda service, account, value: calls.append(("set", service, account, value)),
    )
    provider = MacOSKeychainSecretProvider(service="test.service")
    assert provider.get(LocalSecret.IBKR_ACCOUNT) == "value"
    provider.set(LocalSecret.IBKR_ACCOUNT, "secret")
    assert calls == [
        ("get", "test.service", "ibkr-account"),
        ("set", "test.service", "ibkr-account", "secret"),
    ]


class _FakeNativeFunction:
    def __init__(self, result=0) -> None:
        self.result = result
        self.restype = None
        self.argtypes = None

    def __call__(self, *args):
        return self.result


class _FakeSecurityFramework:
    def __init__(self) -> None:
        self.SecKeychainFindGenericPassword = _FakeNativeFunction()
        self.SecKeychainAddGenericPassword = _FakeNativeFunction()
        self.SecKeychainItemModifyAttributesAndData = _FakeNativeFunction()
        self.SecKeychainItemFreeContent = _FakeNativeFunction()


class _FakeCoreFoundation:
    def __init__(self) -> None:
        self.CFRelease = _FakeNativeFunction()


def test_native_keychain_framework_and_find_bridge(monkeypatch) -> None:
    security = _FakeSecurityFramework()
    core = _FakeCoreFoundation()
    loaded = iter((security, core))
    monkeypatch.setattr(secrets_module.ctypes, "CDLL", lambda _path: next(loaded))
    assert secrets_module._macos_security_framework() == (security, core)
    assert security.SecKeychainFindGenericPassword.restype is ctypes.c_int32
    assert core.CFRelease.argtypes == [ctypes.c_void_p]

    password = ctypes.create_string_buffer(b"secret")

    def find(*args):
        ctypes.cast(args[5], ctypes.POINTER(ctypes.c_uint32)).contents.value = 6
        ctypes.cast(args[6], ctypes.POINTER(ctypes.c_void_p)).contents.value = ctypes.addressof(
            password
        )
        ctypes.cast(args[7], ctypes.POINTER(ctypes.c_void_p)).contents.value = 123
        return 0

    security.SecKeychainFindGenericPassword = find
    monkeypatch.setattr(
        secrets_module,
        "_macos_security_framework",
        lambda: (security, core),
    )
    result = secrets_module._macos_keychain_find("service", "account")
    assert result[2:4] == (0, 6)
    assert ctypes.string_at(result[4], result[3]) == b"secret"
    assert result[5].value == 123


def test_native_keychain_get_and_set_paths(monkeypatch) -> None:
    password = ctypes.create_string_buffer(b"secret")
    security = _FakeSecurityFramework()
    core = _FakeCoreFoundation()
    released: list[int | None] = []
    freed: list[int | None] = []
    core.CFRelease = lambda pointer: released.append(pointer.value)
    security.SecKeychainItemFreeContent = lambda _attributes, pointer: (
        freed.append(pointer.value) or 0
    )

    def found(status: int):
        return (
            security,
            core,
            status,
            6,
            ctypes.c_void_p(ctypes.addressof(password)),
            ctypes.c_void_p(123),
        )

    monkeypatch.setattr(secrets_module, "_macos_keychain_find", lambda *_: found(0))
    assert secrets_module._macos_keychain_get("service", "account") == "secret"
    assert freed and released == [123]

    monkeypatch.setattr(
        secrets_module,
        "_macos_keychain_find",
        lambda *_: found(secrets_module.ERR_SEC_ITEM_NOT_FOUND),
    )
    assert secrets_module._macos_keychain_get("service", "account") is None
    monkeypatch.setattr(secrets_module, "_macos_keychain_find", lambda *_: found(-1))
    with pytest.raises(RuntimeError, match="Keychain lookup failed"):
        secrets_module._macos_keychain_get("service", "account")

    monkeypatch.setattr(secrets_module, "_macos_keychain_find", lambda *_: found(0))
    security.SecKeychainItemModifyAttributesAndData = lambda *_: 0
    secrets_module._macos_keychain_set("service", "account", "updated")
    security.SecKeychainItemModifyAttributesAndData = lambda *_: 7
    with pytest.raises(RuntimeError, match="Keychain update failed"):
        secrets_module._macos_keychain_set("service", "account", "updated")

    created_item = ctypes.c_void_p(456)

    def create(*args):
        ctypes.cast(args[7], ctypes.POINTER(ctypes.c_void_p)).contents.value = created_item.value
        return 0

    monkeypatch.setattr(
        secrets_module,
        "_macos_keychain_find",
        lambda *_: found(secrets_module.ERR_SEC_ITEM_NOT_FOUND),
    )
    security.SecKeychainAddGenericPassword = create
    secrets_module._macos_keychain_set("service", "account", "created")
    assert 456 in released
    security.SecKeychainAddGenericPassword = lambda *_: 9
    with pytest.raises(RuntimeError, match="Keychain create failed"):
        secrets_module._macos_keychain_set("service", "account", "created")
    monkeypatch.setattr(secrets_module, "_macos_keychain_find", lambda *_: found(-1))
    with pytest.raises(RuntimeError, match="Keychain lookup failed"):
        secrets_module._macos_keychain_set("service", "account", "created")


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
    monkeypatch.setattr(onboarding_module, "_ibapi_importable", lambda: True)
    version = install_official_ibapi_archive(
        valid,
        license_accepted=True,
        runner=lambda arguments, **_kwargs: (
            calls.append(arguments) or subprocess.CompletedProcess(arguments, 0, "", "")
        ),
    )
    assert version == "10.48.1"
    assert calls[0][-1] == "protobuf==5.29.5"
    assert calls[1][:4] == [
        onboarding_module.sys.executable,
        "-m",
        "pip",
        "install",
    ]
    assert "--no-deps" in calls[1]

    unsafe = tmp_path / "twsapi-unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as bundle:
        bundle.writestr("../escape", "bad")
    with pytest.raises(ValueError, match="UNSAFE_ARCHIVE_MEMBER"):
        install_official_ibapi_archive(unsafe, license_accepted=True)


def test_ibkr_application_detection_supports_nested_macos_install(tmp_path, monkeypatch) -> None:
    nested = tmp_path / "Applications" / "Trader Workstation"
    nested.mkdir(parents=True)
    application = nested / "Trader Workstation.app"
    application.mkdir()
    monkeypatch.setattr(onboarding_module.Path, "home", lambda: tmp_path)
    detected = onboarding_module._ibkr_applications()
    assert application in detected
    assert onboarding_module._app_kind(application) == "TWS"


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
    version = onboarding_module._ibapi_version()
    assert version is None or isinstance(version, str)
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
    assert progress["status"] == OperatorStatus.BLOCKED_HUMAN_ACTION
    assert progress["next_scenario"] == "static_position"
    assert progress["next_action_kind"] == "SCENARIO_CASE"
    assert progress["missing_counts"] == {
        scenario: 0 for scenario, _ in external_runners_module.E1_SCENARIOS[E1Scope.API]
    }
    assert progress["invalid_session_count"] == 1


def test_e1_event_receipt_cli_binds_verified_session_and_registers(tmp_path, monkeypatch) -> None:
    session_dir = tmp_path / "api" / "sessions" / "session"
    session_dir.mkdir(parents=True)
    manifest = {
        "account_identity_hash": "a" * 64,
        "git_commit": "b" * 40,
        "config_hash": "c" * 64,
        "process_boot_id": "boot-1",
    }
    verification = SimpleNamespace(
        verified=True,
        manifest_id="d" * 64,
        manifest=manifest,
    )
    monkeypatch.setattr(
        cli_module,
        "_e1_session_by_manifest_id",
        lambda *_args: session_dir,
    )
    monkeypatch.setattr(
        cli_module,
        "verify_burn_in_manifest",
        lambda *_args: verification,
    )
    details = tmp_path / "details.json"
    write_immutable_json(details, {"boot_id": "boot-1"})
    registry = tmp_path / "registry.sqlite3"
    result = CliRunner().invoke(
        app,
        [
            "e1",
            "event-receipt",
            "--input",
            str(tmp_path / "api"),
            "--session-id",
            "d" * 64,
            "--event-type",
            "PROCESS_BOOT",
            "--phase",
            "POST",
            "--details",
            str(details),
            "--observed-at",
            NOW.isoformat(),
            "--registry",
            str(registry),
        ],
    )
    assert result.exit_code == 0, result.output
    receipts = tuple((tmp_path / "api" / "receipts").glob("*.json"))
    assert len(receipts) == 1
    artifact_registry = ArtifactRegistry(registry)
    try:
        assert artifact_registry.ops_summary()["type_counts"] == {
            ArtifactType.E1_EVENT_RECEIPT.value: 1
        }
    finally:
        artifact_registry.close()


def test_e1_build_case_cli_persists_passed_cross_scope_case(tmp_path, monkeypatch) -> None:
    manifests = [
        {
            "manifest_id": "1" * 64,
            "account_identity_hash": "a" * 64,
            "git_commit": "b" * 40,
            "config_hash": "c" * 64,
            "normalization_policy_hash": "d" * 64,
            "tws_server_version": "188",
            "ibapi_version": "10.48.1",
            "scope_hash": "4" * 64,
            "client_id": 41,
        },
        {
            "manifest_id": "2" * 64,
            "account_identity_hash": "a" * 64,
            "git_commit": "b" * 40,
            "config_hash": "c" * 64,
            "normalization_policy_hash": "d" * 64,
            "tws_server_version": "188",
            "ibapi_version": "10.48.1",
            "scope_hash": "5" * 64,
            "client_id": 42,
        },
    ]
    case = e1_scenarios_module._scenario_case_document(
        scenario_type=e1_scenarios_module.E1ScenarioType.CLIENT_ID_SWITCH,
        scope=e1_scenarios_module.E1ScopeName.API,
        manifests=manifests,
        receipts=(),
        expected_transition="CROSS_SCOPE_STATE_COMPATIBLE",
        observed_transition="CLIENT_AND_SCOPE_CHANGED_STATE_COMPATIBLE",
        reasons=[],
        effective_from=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    monkeypatch.setattr(
        cli_module,
        "_e1_session_by_manifest_id",
        lambda _root, manifest_id: tmp_path / manifest_id,
    )
    monkeypatch.setattr(cli_module, "build_scenario_case", lambda **_kwargs: case)
    registry = tmp_path / "registry.sqlite3"
    input_root = tmp_path / "api"
    input_root.mkdir()
    result = CliRunner().invoke(
        app,
        [
            "e1",
            "build-case",
            "--input",
            str(input_root),
            "--scope",
            "api",
            "--scenario",
            "client_id_switch",
            "--session-id",
            "1" * 64,
            "--session-id",
            "2" * 64,
            "--registry",
            str(registry),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (input_root / "cases" / f"{case.artifact_id}.json").is_file()


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
    corpus_output = child_calls[2][child_calls[2].index("--output") + 1]
    assert "/corpora/" in corpus_output
    assert corpus_output.endswith(f"/{'2' * 64}.json")
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
