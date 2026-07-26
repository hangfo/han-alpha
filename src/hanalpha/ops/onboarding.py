from __future__ import annotations

import importlib.metadata
import importlib.util
import platform
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any

from hanalpha.config import AppConfig, SecretSettings
from hanalpha.execution.ibkr_observer import account_hash
from hanalpha.execution.ibkr_preflight import current_git_commit
from hanalpha.ops.secrets import LocalSecret, SecretProvider
from hanalpha.simulation.events import canonical_hash


class OperatorStatus(StrEnum):
    PASS = "PASS"
    BLOCKED_HUMAN_ACTION = "BLOCKED_HUMAN_ACTION"
    BLOCKED_EXTERNAL_RIGHTS = "BLOCKED_EXTERNAL_RIGHTS"
    FAILED_CODE = "FAILED_CODE"


class OperatorExit(IntEnum):
    PASS = 0
    FAILED_CODE = 1
    BLOCKED_HUMAN_ACTION = 20
    BLOCKED_EXTERNAL_RIGHTS = 21


def status_exit(status: OperatorStatus) -> int:
    return {
        OperatorStatus.PASS: OperatorExit.PASS,
        OperatorStatus.BLOCKED_HUMAN_ACTION: OperatorExit.BLOCKED_HUMAN_ACTION,
        OperatorStatus.BLOCKED_EXTERNAL_RIGHTS: OperatorExit.BLOCKED_EXTERNAL_RIGHTS,
        OperatorStatus.FAILED_CODE: OperatorExit.FAILED_CODE,
    }[status]


def inspect_ibkr_onboarding(
    config: AppConfig,
    secrets: SecretSettings,
    *,
    repository_root: Path,
    provider: SecretProvider,
    at: datetime,
    applications: tuple[Path, ...] | None = None,
    archives: tuple[Path, ...] | None = None,
    module_available: Callable[[], bool] | None = None,
    socket_available: Callable[[str, int], bool] | None = None,
) -> dict[str, Any]:
    detected_apps = applications if applications is not None else _ibkr_applications()
    detected_archives = archives if archives is not None else _api_archives()
    ibapi_available = (
        module_available()
        if module_available is not None
        else importlib.util.find_spec("ibapi") is not None
    )
    socket_ready = (
        socket_available(secrets.ibkr_host, secrets.ibkr_port)
        if socket_available is not None
        else _port_ready(secrets.ibkr_host, secrets.ibkr_port)
    )
    account = provider.get(LocalSecret.IBKR_ACCOUNT) or secrets.ibkr_account
    checks = {
        "macos": platform.system() == "Darwin",
        "repository": (repository_root / "pyproject.toml").is_file(),
        "virtual_environment": sys.prefix != sys.base_prefix,
        "paper_environment": secrets.hanalpha_env.lower() == "paper",
        "paper_port": secrets.ibkr_port in {4002, 7497},
        "broker_writes_disabled": not config.execution.broker_write_enabled,
        "automatic_submission_disabled": not config.execution.auto_submit_paper,
        "tws_or_gateway_installed": bool(detected_apps),
        "official_ibapi_importable": ibapi_available,
        "paper_account_explicit": bool(account),
        "paper_socket_listening": socket_ready,
    }
    blockers: list[str] = []
    if not checks["tws_or_gateway_installed"]:
        blockers.append("INSTALL_TWS_OR_GATEWAY_AND_ACCEPT_LICENSE")
    if not checks["official_ibapi_importable"]:
        blockers.append(
            "INSTALL_OFFICIAL_IBAPI_FROM_LOCAL_ARCHIVE"
            if detected_archives
            else "DOWNLOAD_OFFICIAL_TWS_API_AND_ACCEPT_LICENSE"
        )
    if not checks["paper_account_explicit"]:
        blockers.append("STORE_IBKR_PAPER_ACCOUNT_IN_KEYCHAIN")
    if checks["tws_or_gateway_installed"] and not checks["paper_socket_listening"]:
        blockers.append("LOGIN_PAPER_COMPLETE_2FA_AND_ENABLE_SOCKET")
    if not checks["paper_environment"] or not checks["paper_port"]:
        blockers.append("RESOLVE_PAPER_LIVE_ENVIRONMENT_AMBIGUITY")
    if (
        checks["broker_writes_disabled"] is False
        or checks["automatic_submission_disabled"] is False
    ):
        blockers.append("RESTORE_ZERO_WRITE_CONFIGURATION")
    status = OperatorStatus.PASS if not blockers else OperatorStatus.BLOCKED_HUMAN_ACTION
    body = {
        "schema_version": "hanalpha-local-onboarding-v1",
        "created_at": at.astimezone(UTC).isoformat(),
        "status": status,
        "checks": checks,
        "blockers": blockers,
        "git_commit": current_git_commit(repository_root),
        "ibapi_version": _ibapi_version() if ibapi_available else None,
        "installed_app_kinds": sorted({_app_kind(path) for path in detected_apps}),
        "local_api_archive_count": len(detected_archives),
        "paper_port": secrets.ibkr_port,
        "client_id": secrets.ibkr_client_id,
        "account_hash": account_hash(account) if account else None,
        "observer_only": True,
        "next_permitted_command": (
            "hanalpha e1 run --scope api" if status is OperatorStatus.PASS else None
        ),
        "secrets_redacted": True,
    }
    return {"report_id": canonical_hash(body), **body}


def launch_ibkr_application(applications: tuple[Path, ...] | None = None) -> str:
    candidates = applications if applications is not None else _ibkr_applications()
    if not candidates:
        raise RuntimeError("TWS or IB Gateway is not installed")
    selected = candidates[0]
    result = subprocess.run(
        ["/usr/bin/open", str(selected)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("failed to launch installed IBKR application")
    return _app_kind(selected)


def wait_for_ibkr_socket(
    host: str,
    port: int,
    *,
    timeout_seconds: float,
    probe: Callable[[str, int], bool] | None = None,
    interval_seconds: float = 1.0,
) -> bool:
    """Poll only the configured local Paper socket for a bounded interval."""

    if timeout_seconds < 0 or timeout_seconds > 300:
        raise ValueError("timeout_seconds must be between 0 and 300")
    check = probe or _port_ready
    deadline = time.monotonic() + timeout_seconds
    while True:
        if check(host, port):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(interval_seconds, remaining))


def github_safe_summary(report: dict[str, Any]) -> str:
    status = str(report["status"])
    checks = report.get("checks", {})
    passed = sum(value is True for value in checks.values())
    total = len(checks)
    blockers = ", ".join(str(item) for item in report.get("blockers", [])) or "none"
    commit = str(report.get("git_commit") or "unknown")[:12]
    return (
        f"status={status}\ncommit={commit}\nchecks={passed}/{total}\n"
        f"blockers={blockers}\nsecrets_redacted=true"
    )


def _ibkr_applications() -> tuple[Path, ...]:
    roots = (Path("/Applications"), Path.home() / "Applications")
    candidates: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        candidates.extend(root.glob("*Trader Workstation*.app"))
        candidates.extend(root.glob("*IB Gateway*.app"))
        candidates.extend(root.glob("TWS*.app"))
    return tuple(sorted(set(candidates)))


def _api_archives() -> tuple[Path, ...]:
    downloads = Path.home() / "Downloads"
    if not downloads.is_dir():
        return ()
    return tuple(
        sorted(
            {
                *downloads.glob("twsapi*.zip"),
                *downloads.glob("twsapi*.tar.gz"),
                *downloads.glob("twsapi*.dmg"),
            }
        )
    )


def _port_ready(host: str, port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.25)
        return probe.connect_ex((host, port)) == 0


def _ibapi_version() -> str | None:
    try:
        return importlib.metadata.version("ibapi")
    except importlib.metadata.PackageNotFoundError:
        return None


def _app_kind(path: Path) -> str:
    return "IB_GATEWAY" if "gateway" in path.name.lower() else "TWS"
