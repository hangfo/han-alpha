from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from pydantic import SecretStr

from hanalpha.config import AppConfig, SecretSettings
from hanalpha.domain.enums import OperatingMode

_ISSUER = object()
_MIN_TOKEN_LENGTH = 32


class BrokerWriteCapability:
    """Unforgeable-in-process authority required by every broker write method."""

    __slots__ = ("_issuer", "operating_mode")

    _issuer: object
    operating_mode: OperatingMode

    def __init__(self, issuer: object, operating_mode: OperatingMode) -> None:
        if issuer is not _ISSUER:
            raise TypeError("BrokerWriteCapability can only be issued by runtime policy")
        self._issuer = issuer
        self.operating_mode = operating_mode

    def _is_valid(self) -> bool:
        return self._issuer is _ISSUER and self.operating_mode in {
            OperatingMode.PAPER_MANUAL,
            OperatingMode.PAPER_AUTO,
        }


def require_broker_write(capability: BrokerWriteCapability | None) -> None:
    if capability is None or not capability._is_valid():
        raise PermissionError("broker_write_capability_required")


@dataclass(frozen=True)
class RuntimeCapabilities:
    broker_write: bool
    automatic_submission: bool
    operator_api: bool


@dataclass(frozen=True)
class RuntimeAccess:
    operating_mode: OperatingMode
    capabilities: RuntimeCapabilities
    broker_write: BrokerWriteCapability | None
    _operator_token_digest: bytes | None

    def authorize_operator(self, supplied_token: str | None) -> bool:
        if not self.capabilities.operator_api or self._operator_token_digest is None:
            return False
        if supplied_token is None:
            return False
        supplied_digest = hashlib.sha256(supplied_token.encode("utf-8")).digest()
        return hmac.compare_digest(self._operator_token_digest, supplied_digest)


def _secret_value(secret: SecretStr | None, *, label: str) -> str | None:
    if secret is None:
        return None
    value = secret.get_secret_value()
    if len(value) < _MIN_TOKEN_LENGTH:
        raise RuntimeError(f"{label} must be at least {_MIN_TOKEN_LENGTH} characters")
    return value


def build_runtime_access(config: AppConfig, secrets: SecretSettings) -> RuntimeAccess:
    mode = config.operating_mode
    execution = config.execution
    broker_write_allowed = (
        mode in {OperatingMode.PAPER_MANUAL, OperatingMode.PAPER_AUTO}
        and execution.broker_write_enabled
    )
    broker_write: BrokerWriteCapability | None = None
    if broker_write_allowed:
        token = _secret_value(
            secrets.hanalpha_broker_write_token,
            label="broker write token",
        )
        if token is None:
            raise RuntimeError("broker write token is required when broker writes are enabled")
        broker_write = BrokerWriteCapability(_ISSUER, mode)

    operator_digest: bytes | None = None
    if execution.operator_api_enabled:
        operator_token = _secret_value(
            secrets.hanalpha_operator_token,
            label="operator API token",
        )
        if operator_token is None:
            raise RuntimeError("operator API token is required when operator API is enabled")
        operator_digest = hashlib.sha256(operator_token.encode("utf-8")).digest()

    return RuntimeAccess(
        operating_mode=mode,
        capabilities=RuntimeCapabilities(
            broker_write=broker_write is not None,
            automatic_submission=(
                mode == OperatingMode.PAPER_AUTO
                and execution.auto_submit_paper
                and broker_write is not None
            ),
            operator_api=execution.operator_api_enabled and operator_digest is not None,
        ),
        broker_write=broker_write,
        _operator_token_digest=operator_digest,
    )
