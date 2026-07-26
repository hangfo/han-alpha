from __future__ import annotations

import re
import subprocess
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from hanalpha.config import SecretSettings

KEYCHAIN_SERVICE = "com.hanalpha.local"


class LocalSecret(StrEnum):
    IBKR_ACCOUNT = "ibkr-account"
    MASSIVE_CREDENTIAL = "massive-api-key"
    FRED_CREDENTIAL = "fred-api-key"
    SEC_USER_AGENT = "sec-user-agent"
    ARTIFACT_REGISTRY_PATH = "artifact-registry-path"
    REVIEWER_PUBLIC_KEYS = "reviewer-public-keys"


SECRET_SETTING_FIELDS: dict[LocalSecret, str] = {
    LocalSecret.IBKR_ACCOUNT: "ibkr_account",
    LocalSecret.MASSIVE_CREDENTIAL: "massive_api_key",
    LocalSecret.FRED_CREDENTIAL: "fred_api_key",
    LocalSecret.SEC_USER_AGENT: "sec_user_agent",
    LocalSecret.ARTIFACT_REGISTRY_PATH: "hanalpha_artifact_registry_path",
    LocalSecret.REVIEWER_PUBLIC_KEYS: "hanalpha_safety_case_public_keys",
}
SECRET_ENV_NAMES: dict[LocalSecret, str] = {
    LocalSecret.IBKR_ACCOUNT: "IBKR_ACCOUNT",
    LocalSecret.MASSIVE_CREDENTIAL: "MASSIVE_API_KEY",
    LocalSecret.FRED_CREDENTIAL: "FRED_API_KEY",
    LocalSecret.SEC_USER_AGENT: "SEC_USER_AGENT",
    LocalSecret.ARTIFACT_REGISTRY_PATH: "HANALPHA_ARTIFACT_REGISTRY_PATH",
    LocalSecret.REVIEWER_PUBLIC_KEYS: "HANALPHA_SAFETY_CASE_PUBLIC_KEYS",
}


class SecretProvider(Protocol):
    def get(self, name: LocalSecret) -> str | None: ...

    def set(self, name: LocalSecret, value: str) -> None: ...


class EnvironmentSecretProvider:
    def __init__(self, settings: SecretSettings | None = None) -> None:
        self.settings = settings or SecretSettings()

    def get(self, name: LocalSecret) -> str | None:
        value = getattr(self.settings, SECRET_SETTING_FIELDS[name])
        return str(value) if value else None

    def set(self, name: LocalSecret, value: str) -> None:
        raise RuntimeError("environment secret provider is read-only")


class MacOSKeychainSecretProvider:
    def __init__(
        self,
        *,
        service: str = KEYCHAIN_SERVICE,
        runner: object = subprocess.run,
    ) -> None:
        self.service = service
        self._runner = runner

    def get(self, name: LocalSecret) -> str | None:
        result = self._runner(  # type: ignore[operator]
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                self.service,
                "-a",
                name.value,
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        value = result.stdout.rstrip("\r\n")
        return value or None

    def set(self, name: LocalSecret, value: str) -> None:
        if not value:
            raise ValueError("empty secret values are not stored")
        result = self._runner(  # type: ignore[operator]
            [
                "/usr/bin/security",
                "add-generic-password",
                "-U",
                "-s",
                self.service,
                "-a",
                name.value,
                "-w",
            ],
            input=f"{value}\n",
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Keychain write failed for {name.value}")


def settings_from_provider(
    provider: SecretProvider,
    *,
    fallback: SecretSettings | None = None,
) -> SecretSettings:
    baseline = fallback or SecretSettings()
    values = baseline.model_dump()
    for name, field in SECRET_SETTING_FIELDS.items():
        secret = provider.get(name)
        if secret:
            values[field] = secret
    return SecretSettings.model_validate(values)


def migrate_env_secrets(
    path: Path,
    provider: SecretProvider,
    *,
    scrub: bool,
) -> tuple[LocalSecret, ...]:
    if not path.is_file():
        raise FileNotFoundError(f"environment file not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    migrated: list[LocalSecret] = []
    rewritten: list[str] = []
    names = {environment_name: item for item, environment_name in SECRET_ENV_NAMES.items()}
    for line in lines:
        key, separator, raw_value = line.partition("=")
        normalized_key = key.removeprefix("export ").strip()
        secret_name = names.get(normalized_key)
        if not separator or secret_name is None:
            rewritten.append(line)
            continue
        value = raw_value.strip().strip("\"'")
        if value:
            provider.set(secret_name, value)
            migrated.append(secret_name)
        rewritten.append(f"{normalized_key}=" if scrub else line)
    if scrub:
        path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    return tuple(migrated)


def redact_text(value: str, *, secrets: tuple[str, ...] = ()) -> str:
    redacted = value
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED]")
    redacted = re.sub(
        r"(?i)(api[_-]?key|token|authorization|password|account)"
        r"([\"'=:\s]+)([^&\s,\"'}]+)",
        r"\1\2[REDACTED]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)([?&](?:apiKey|api_key|token|key)=)[^&\s]+",
        r"\1[REDACTED]",
        redacted,
    )
    return redacted
