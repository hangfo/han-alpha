from __future__ import annotations

import ctypes
import re
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from hanalpha.config import SecretSettings

KEYCHAIN_SERVICE = "com.hanalpha.local"
ERR_SEC_ITEM_NOT_FOUND = -25300


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
        runner: object | None = None,
    ) -> None:
        self.service = service
        self._runner = runner

    def get(self, name: LocalSecret) -> str | None:
        if self._runner is None:
            return _macos_keychain_get(self.service, name.value)
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
        if self._runner is None:
            _macos_keychain_set(self.service, name.value, value)
            return
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


def _macos_security_framework() -> tuple[ctypes.CDLL, ctypes.CDLL]:
    security = ctypes.CDLL(
        "/System/Library/Frameworks/Security.framework/Security"
    )
    core_foundation = ctypes.CDLL(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    )
    security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    security.SecKeychainFindGenericPassword.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
    security.SecKeychainAddGenericPassword.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
    security.SecKeychainItemModifyAttributesAndData.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
    ]
    security.SecKeychainItemFreeContent.restype = ctypes.c_int32
    security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
    return security, core_foundation


def _macos_keychain_find(
    service: str,
    account: str,
) -> tuple[ctypes.CDLL, ctypes.CDLL, int, int, ctypes.c_void_p, ctypes.c_void_p]:
    security, core_foundation = _macos_security_framework()
    service_bytes = service.encode()
    account_bytes = account.encode()
    password_length = ctypes.c_uint32()
    password_data = ctypes.c_void_p()
    item_ref = ctypes.c_void_p()
    status = security.SecKeychainFindGenericPassword(
        None,
        len(service_bytes),
        service_bytes,
        len(account_bytes),
        account_bytes,
        ctypes.byref(password_length),
        ctypes.byref(password_data),
        ctypes.byref(item_ref),
    )
    return (
        security,
        core_foundation,
        status,
        password_length.value,
        password_data,
        item_ref,
    )


def _macos_keychain_get(service: str, account: str) -> str | None:
    (
        security,
        core_foundation,
        status,
        password_length,
        password_data,
        item_ref,
    ) = _macos_keychain_find(service, account)
    if status == ERR_SEC_ITEM_NOT_FOUND:
        return None
    if status != 0:
        raise RuntimeError(f"Keychain lookup failed for {account}")
    try:
        value = ctypes.string_at(password_data, password_length).decode()
        return value or None
    finally:
        security.SecKeychainItemFreeContent(None, password_data)
        if item_ref:
            core_foundation.CFRelease(item_ref)


def _macos_keychain_set(service: str, account: str, value: str) -> None:
    security, core_foundation, status, _, password_data, item_ref = _macos_keychain_find(
        service, account
    )
    value_bytes = value.encode()
    if status == 0:
        try:
            security.SecKeychainItemFreeContent(None, password_data)
            update_status = security.SecKeychainItemModifyAttributesAndData(
                item_ref,
                None,
                len(value_bytes),
                value_bytes,
            )
            if update_status != 0:
                raise RuntimeError(f"Keychain update failed for {account}")
        finally:
            if item_ref:
                core_foundation.CFRelease(item_ref)
        return
    if status != ERR_SEC_ITEM_NOT_FOUND:
        raise RuntimeError(f"Keychain lookup failed for {account}")
    service_bytes = service.encode()
    account_bytes = account.encode()
    created_item = ctypes.c_void_p()
    create_status = security.SecKeychainAddGenericPassword(
        None,
        len(service_bytes),
        service_bytes,
        len(account_bytes),
        account_bytes,
        len(value_bytes),
        value_bytes,
        ctypes.byref(created_item),
    )
    if created_item:
        core_foundation.CFRelease(created_item)
    if create_status != 0:
        raise RuntimeError(f"Keychain create failed for {account}")


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
