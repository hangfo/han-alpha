from __future__ import annotations

import importlib.util
import socket
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hanalpha.config import AppConfig, SecretSettings
from hanalpha.execution.ibkr_observer import account_hash
from hanalpha.ops.artifacts import write_immutable_json
from hanalpha.simulation.events import canonical_hash


def current_git_commit(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else None


def port_is_listening(host: str, port: int, *, timeout: float = 0.25) -> bool:
    with socket.socket() as probe:
        probe.settimeout(timeout)
        return probe.connect_ex((host, port)) == 0


def build_ibkr_preflight(
    config: AppConfig,
    secrets: SecretSettings,
    *,
    at: datetime,
    repository_root: Path,
    read_only_attested: bool,
    order_visibility_attested: bool = False,
    importable: Callable[[], bool] | None = None,
    listening: Callable[[str, int], bool] | None = None,
) -> dict[str, Any]:
    """Build a redacted, zero-write readiness artifact without connecting to IBKR."""

    ibapi_available = (
        importable() if importable is not None else importlib.util.find_spec("ibapi") is not None
    )
    socket_ready = (
        listening(secrets.ibkr_host, secrets.ibkr_port)
        if listening is not None
        else port_is_listening(secrets.ibkr_host, secrets.ibkr_port)
    )
    mutually_exclusive_operator_mode = read_only_attested != order_visibility_attested
    checks = {
        "environment_is_paper": secrets.hanalpha_env.lower() == "paper",
        "standard_paper_port": secrets.ibkr_port in {4002, 7497},
        "paper_account_explicit": bool(secrets.ibkr_account),
        "official_ibapi_importable": ibapi_available,
        "paper_socket_listening": socket_ready,
        "broker_write_capability_disabled": not config.execution.broker_write_enabled,
        "automatic_submission_disabled": not config.execution.auto_submit_paper,
        "observer_client_write_methods_blocked": True,
        "operator_observation_mode_attested": mutually_exclusive_operator_mode,
    }
    body: dict[str, Any] = {
        "schema_version": "ibkr-zero-write-preflight-v1",
        "created_at": at.astimezone(UTC).isoformat(),
        "git_commit": current_git_commit(repository_root),
        "config_hash": canonical_hash(config),
        "environment": secrets.hanalpha_env.lower(),
        "host": secrets.ibkr_host,
        "paper_port": secrets.ibkr_port,
        "client_id": secrets.ibkr_client_id,
        "account_hash": account_hash(secrets.ibkr_account) if secrets.ibkr_account else None,
        "base_currency": config.base_currency,
        "checks": checks,
        "ready": all(checks.values()),
        "write_capability": False,
        "tws_read_only_operator_attested": read_only_attested,
        "order_visibility_operator_attested": order_visibility_attested,
        "observation_mode": (
            "TWS_READ_ONLY"
            if read_only_attested
            else (
                "ORDER_VISIBILITY_ZERO_WRITE_CLIENT" if order_visibility_attested else "UNATTESTED"
            )
        ),
        "limitations": [
            "The TWS API setting has no trusted remote introspection in this preflight; its mode is an operator attestation.",
            "TWS Read-Only API hides order information. Order visibility therefore requires disabling that TWS setting while the observer-only client still rejects write methods.",
            "Managed Accounts, server time/version and callback behavior require a real Observer session.",
        ],
    }
    return {"artifact_id": canonical_hash(body), **body}


def persist_ibkr_preflight(path: Path, artifact: dict[str, Any]) -> None:
    write_immutable_json(path, artifact)
