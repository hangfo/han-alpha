from __future__ import annotations

import asyncio
import base64
import importlib.metadata
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from hanalpha.backtest import BacktestEngine
from hanalpha.config import SecretSettings, install_secret_overrides, load_config
from hanalpha.data.fixtures import run_fixture_pipeline
from hanalpha.data.synthetic import SyntheticMarketDataProvider
from hanalpha.execution.burn_in import (
    evaluate_burn_in_corpus,
    persist_burn_in_session,
)
from hanalpha.execution.control_store import DurableExecutionStore
from hanalpha.execution.fake_broker import DurableFakeBroker
from hanalpha.execution.golden_tape import evaluate_golden_tape_corpus
from hanalpha.execution.ibkr import IBKRBroker
from hanalpha.execution.ibkr_observer import CompletedOrdersScope, IBKRFactStore
from hanalpha.execution.ibkr_preflight import (
    build_ibkr_preflight,
    current_git_commit,
    persist_ibkr_preflight,
)
from hanalpha.execution.ibkr_snapshot import IBKRBrokerSnapshotAdapter
from hanalpha.execution.reconciliation import Reconciler
from hanalpha.execution.worker import ExecutionWorker
from hanalpha.experiments.models import ExperimentManifest, WindowRole
from hanalpha.experiments.registry import ExperimentRegistry
from hanalpha.experiments.runner import ExperimentRunner
from hanalpha.ops.artifact_registry import ArtifactRegistry, ArtifactType
from hanalpha.ops.artifacts import write_immutable_json
from hanalpha.ops.external_runners import (
    E1Scope,
    e1_progress,
    run_r1_source,
    runner_github_summary,
)
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
    LocalSecret,
    MacOSKeychainSecretProvider,
    migrate_env_secrets,
    settings_from_provider,
)
from hanalpha.orchestrator import build_system
from hanalpha.pit.catalog import PITCatalog
from hanalpha.pit.qualification import (
    DataSourceProfile,
    evaluate_source_profile,
    persist_qualification,
    vendor_access_preflight,
)
from hanalpha.pit.source_audit import audit_probe_manifest
from hanalpha.pit.source_probe import (
    ProbeSource,
    SourceProbeError,
    run_bounded_source_probe,
)
from hanalpha.portfolio import Ledger
from hanalpha.research.adapter import ResearchPolicyAdapter
from hanalpha.research.protocol import (
    DateWindow,
    PreregisteredProtocol,
    ResearchBudget,
    SuccessCriteria,
)
from hanalpha.research.strategies import SlowTrendStrategy
from hanalpha.simulation.engine import PortfolioReplayEngine
from hanalpha.simulation.events import ReplayFrame, SimulationBar, canonical_hash
from hanalpha.simulation.fills import FillPolicy, HistoricalExchange
from hanalpha.simulation.portfolio import PortfolioPolicy
from hanalpha.strategies import BreakoutStrategy

app = typer.Typer(no_args_is_help=True, help="Han Alpha trading system CLI")
pit_app = typer.Typer(no_args_is_help=True, help="Point-in-time fixture data tools")
local_onboard_app = typer.Typer(no_args_is_help=True, help="Secure local external onboarding")
e1_app = typer.Typer(no_args_is_help=True, help="E1-B external Broker acceptance runner")
r1_app = typer.Typer(no_args_is_help=True, help="R1-B external source acceptance runner")
app.add_typer(pit_app, name="pit")
app.add_typer(local_onboard_app, name="local-onboard")
app.add_typer(e1_app, name="e1")
app.add_typer(r1_app, name="r1")
console = Console()
SECRET_STDIN_MARKER = "HANALPHA_SECRET_STDIN_V1"
SECRET_STDIN_LIMIT = 65_536


@app.callback()
def load_secret_ipc() -> None:
    """Load an internal one-shot secret payload from stdin, never argv or env."""

    if os.getenv(SECRET_STDIN_MARKER) != "1":
        return
    payload = sys.stdin.read(SECRET_STDIN_LIMIT + 1)
    if len(payload) > SECRET_STDIN_LIMIT:
        raise typer.Exit(code=1)
    try:
        document = json.loads(payload)
        if not isinstance(document, dict):
            raise ValueError
        install_secret_overrides(document)
    except (json.JSONDecodeError, ValueError, TypeError):
        raise typer.Exit(code=1) from None


def _local_settings() -> tuple[SecretSettings, MacOSKeychainSecretProvider]:
    provider = MacOSKeychainSecretProvider()
    return settings_from_provider(provider), provider


def _secret_child_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in (
        "IBKR_ACCOUNT",
        "MASSIVE_API_KEY",
        "POLYGON_API_KEY",
        "FRED_API_KEY",
        "SEC_USER_AGENT",
        "HANALPHA_ARTIFACT_REGISTRY_PATH",
        "HANALPHA_SAFETY_CASE_PUBLIC_KEYS",
    ):
        environment.pop(name, None)
    environment[SECRET_STDIN_MARKER] = "1"
    return environment


def _secret_child_payload(secrets: SecretSettings) -> str:
    values = {
        "ibkr_account": secrets.ibkr_account,
        "massive_api_key": secrets.massive_api_key,
        "polygon_api_key": secrets.polygon_api_key,
        "fred_api_key": secrets.fred_api_key,
        "sec_user_agent": secrets.sec_user_agent,
        "hanalpha_artifact_registry_path": secrets.hanalpha_artifact_registry_path,
        "hanalpha_safety_case_public_keys": secrets.hanalpha_safety_case_public_keys,
    }
    return json.dumps({key: value for key, value in values.items() if value})


def _run_secret_child(arguments: list[str], secrets: SecretSettings) -> int:
    result = subprocess.run(
        [sys.executable, "-m", "hanalpha", *arguments],
        env=_secret_child_environment(),
        input=_secret_child_payload(secrets),
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode


@app.command("execution-reconcile")
def execution_reconcile(
    control: Annotated[Path, typer.Option("--control")],
    broker_state: Annotated[Path, typer.Option("--broker-state")],
) -> None:
    """Reconcile the durable control plane against the local fault-injecting broker."""
    at = datetime.now(UTC)
    store = DurableExecutionStore(control)
    broker = DurableFakeBroker(broker_state)
    try:
        report = Reconciler(store).reconcile(broker.snapshot(at=at), at=at)
        console.print_json(report.model_dump_json(indent=2))
    finally:
        broker.close()
        store.close()


@app.command("execution-dispatch")
def execution_dispatch(
    control: Annotated[Path, typer.Option("--control")],
    broker_state: Annotated[Path, typer.Option("--broker-state")],
    owner: Annotated[str, typer.Option("--owner")] = "local-worker",
) -> None:
    """Reconcile then dispatch one local Fake-Broker outbox command."""
    at = datetime.now(UTC)
    store = DurableExecutionStore(control)
    broker = DurableFakeBroker(broker_state)
    try:
        report = Reconciler(store).reconcile(broker.snapshot(at=at), at=at)
        if report.status not in {"CONVERGED", "DEGRADED"}:
            raise typer.BadParameter(f"reconciliation blocked dispatch: {report.status}")
        lease = store.acquire_lease(
            "broker-writer", owner_id=owner, at=at, ttl=timedelta(seconds=30)
        )
        dispatched = ExecutionWorker(store, broker, lease).dispatch_once(at=at)
        console.print(f"dispatched={str(dispatched).lower()} fencing_token={lease.fencing_token}")
    finally:
        broker.close()
        store.close()


@app.command("execution-approvals")
def execution_approvals(
    control: Annotated[Path, typer.Option("--control")],
) -> None:
    """List durable approval-pending intents without exposing account identifiers."""
    store = DurableExecutionStore(control)
    try:
        rows = [
            {
                "intent_id": row["intent_id"],
                "decision_id": row["decision_id"],
                "status": row["status"],
                "version": row["version"],
            }
            for row in store.pending_approvals()
        ]
        console.print_json(json.dumps(rows, sort_keys=True))
    finally:
        store.close()


@app.command("execution-approve")
def execution_approve(
    control: Annotated[Path, typer.Option("--control")],
    broker_state: Annotated[Path, typer.Option("--broker-state")],
    intent_id: Annotated[str, typer.Option("--intent-id")],
    actor: Annotated[str, typer.Option("--actor")],
) -> None:
    """Persist an immutable approval receipt for one exact intent specification."""
    store = DurableExecutionStore(control)
    broker = DurableFakeBroker(broker_state)
    try:
        report = Reconciler(store).reconcile(
            broker.snapshot(at=datetime.now(UTC)), at=datetime.now(UTC)
        )
        if report.status not in {"CONVERGED", "DEGRADED"}:
            raise typer.BadParameter(f"reconciliation blocked approval: {report.status}")
        approval_id = store.approve(intent_id, actor_id=actor, at=datetime.now(UTC))
        console.print(f"approval_id={approval_id} status=APPROVED_UNARMED")
    finally:
        broker.close()
        store.close()


@app.command("execution-arm")
def execution_arm(
    control: Annotated[Path, typer.Option("--control")],
    intent_id: Annotated[str, typer.Option("--intent-id")],
    authority_id: Annotated[str, typer.Option("--authority-id")],
    quote_snapshot_id: Annotated[str, typer.Option("--quote-snapshot-id")],
    actor: Annotated[str, typer.Option("--actor")],
    operator_session_id: Annotated[str, typer.Option("--operator-session-id")],
    max_drift_bps: Annotated[str, typer.Option("--max-drift-bps")] = "10",
    ttl_seconds: Annotated[int, typer.Option("--ttl-seconds", min=1, max=5)] = 5,
) -> None:
    """Bind an approved intent to current broker and quote truth, then outbox it."""
    store = DurableExecutionStore(control)
    try:
        at = datetime.now(UTC)
        arm_id = store.arm_approved_intent(
            intent_id,
            authority_id=authority_id,
            quote_snapshot_id=quote_snapshot_id,
            max_drift_bps=Decimal(max_drift_bps),
            armed_by=actor,
            at=at,
            expires_at=at + timedelta(seconds=ttl_seconds),
            arm_source="LOCAL_CLI",
            operator_session_id=operator_session_id,
        )
        console.print(f"arm_id={arm_id} status=ARMED")
    finally:
        store.close()


@app.command("ibkr-observe")
def ibkr_observe(
    state_path: Annotated[Path, typer.Option("--state")],
    control: Annotated[Path, typer.Option("--control")],
    snapshots: Annotated[int, typer.Option("--snapshots", min=1, max=100)] = 2,
    timeout: Annotated[float, typer.Option("--timeout", min=1, max=120)] = 15,
    completed_orders_scope: Annotated[
        CompletedOrdersScope, typer.Option("--completed-orders-scope")
    ] = CompletedOrdersScope.API,
    artifact_root: Annotated[Path, typer.Option("--artifact-root")] = Path(".state/burn-in"),
    capture_scenario: Annotated[str, typer.Option("--capture-scenario")] = ("repeated_connection"),
    registry_path: Annotated[Path, typer.Option("--registry")] = Path(
        ".state/evidence-artifacts.sqlite3"
    ),
) -> None:
    """Capture a read-only IBKR Paper fact tape and completeness certificate."""

    async def _run() -> None:
        config, secrets = load_config()
        if secrets.hanalpha_env.lower() != "paper":
            raise typer.BadParameter("IBKR observer requires HANALPHA_ENV=paper")
        if secrets.ibkr_port not in {4002, 7497}:
            raise typer.BadParameter("IBKR observer only permits Paper ports 4002 or 7497")
        if not secrets.ibkr_account:
            raise typer.BadParameter("IBKR_ACCOUNT must explicitly identify the Paper account")
        broker = IBKRBroker(
            host=secrets.ibkr_host,
            port=secrets.ibkr_port,
            client_id=secrets.ibkr_client_id,
            account=secrets.ibkr_account,
            base_currency=config.base_currency,
            observer_only=True,
        )
        store = IBKRFactStore(state_path)
        execution_store = DurableExecutionStore(control)
        registry = ArtifactRegistry(registry_path)
        try:
            for index in range(snapshots):
                certificate, model = await broker.observe_read_only(
                    store,
                    timeout=timeout,
                    completed_orders_scope=completed_orders_scope,
                )
                try:
                    snapshot = IBKRBrokerSnapshotAdapter.build(
                        model,
                        certificate,
                        configured_account=secrets.ibkr_account,
                        key_resolver=execution_store,
                    )
                except ValueError:
                    execution_store.open_freeze_ticket(
                        "BROKER_SNAPSHOT_ADAPTER_REJECTED",
                        source="ibkr_observer",
                        at=datetime.now(UTC),
                    )
                    raise
                report = Reconciler(execution_store).reconcile_authoritative(
                    snapshot,
                    at=datetime.now(UTC),
                    minimum_consensus_interval=timedelta(seconds=1),
                )
                vote = execution_store.connection.execute(
                    """SELECT disposition, equivalence_json
                       FROM broker_snapshot_votes WHERE observation_id=?""",
                    (snapshot.observation_id,),
                ).fetchone()
                consensus = execution_store.connection.execute(
                    """SELECT consecutive_count FROM broker_snapshot_consensus
                       WHERE visibility_scope_hash=?""",
                    (snapshot.visibility_scope_hash,),
                ).fetchone()
                authority = execution_store.latest_broker_snapshot_authority()
                server_version = broker.server_version
                try:
                    ibapi_version = importlib.metadata.version("ibapi")
                except importlib.metadata.PackageNotFoundError:
                    ibapi_version = None
                session_dir = persist_burn_in_session(
                    source_store=store,
                    certificate=certificate,
                    snapshot=snapshot,
                    output_root=artifact_root,
                    git_commit=current_git_commit(Path.cwd()),
                    config_hash=canonical_hash(config),
                    client_id=secrets.ibkr_client_id,
                    paper_port=secrets.ibkr_port,
                    reconciliation_status=report.status,
                    tws_server_version=server_version,
                    ibapi_version=ibapi_version,
                    vote_disposition=str(vote["disposition"]) if vote else None,
                    consensus_count_after_vote=(
                        int(consensus["consecutive_count"]) if consensus else 0
                    ),
                    equivalence_receipt=(
                        json.loads(vote["equivalence_json"])
                        if vote and vote["equivalence_json"]
                        else None
                    ),
                    authority_promoted=bool(
                        authority
                        and authority["certificate_id"] == snapshot.completeness_certificate_id
                    ),
                    capture_scenario=capture_scenario,
                    environment=secrets.hanalpha_env,
                    broker_host=secrets.ibkr_host,
                )
                manifest = json.loads((session_dir / "manifest.json").read_text(encoding="utf-8"))
                registry.register(
                    session_dir / "manifest.json",
                    artifact_type=ArtifactType.BURN_IN_SESSION,
                    status="VERIFIED" if manifest["safety_case_eligible"] else "CAPTURED",
                    git_commit=manifest.get("git_commit"),
                    config_hash=manifest.get("config_hash"),
                    scope_hash=manifest.get("scope_hash"),
                    account_hash=manifest.get("account_hash"),
                )
                execution_store.record_heartbeat(
                    "broker-observer",
                    status="OK" if certificate.complete else "ERROR",
                    at=datetime.now(UTC),
                    details={
                        "certificate_id": certificate.certificate_id,
                        "queue_depth": certificate.queue_depth,
                        "writer_error": certificate.writer_error,
                    },
                )
                console.print(
                    f"snapshot={index + 1}/{snapshots} "
                    f"complete={str(certificate.complete).lower()} "
                    f"reconciliation={report.status} "
                    f"certificate_id={certificate.certificate_id} "
                    f"scope={completed_orders_scope.value} "
                    f"artifact={session_dir} "
                    f"orders={len(model.orders)} executions={len(model.executions)} "
                    f"positions={len(model.positions)}"
                )
                if index + 1 < snapshots:
                    await asyncio.sleep(1)
        finally:
            if hasattr(broker.app, "disconnect"):
                broker.app.disconnect()
            store.close()
            execution_store.close()
            registry.close()

    asyncio.run(_run())


@app.command("ibkr-burn-in")
def ibkr_burn_in(
    state_path: Annotated[Path, typer.Option("--state")],
    control: Annotated[Path, typer.Option("--control")],
    sessions: Annotated[int, typer.Option("--sessions", min=1, max=100)] = 30,
    timeout: Annotated[float, typer.Option("--timeout", min=1, max=120)] = 15,
    completed_orders_scope: Annotated[
        CompletedOrdersScope, typer.Option("--completed-orders-scope")
    ] = CompletedOrdersScope.API,
    output: Annotated[Path, typer.Option("--output")] = Path(".state/burn-in"),
    capture_scenario: Annotated[str, typer.Option("--capture-scenario")] = ("repeated_connection"),
    registry_path: Annotated[Path, typer.Option("--registry")] = Path(
        ".state/evidence-artifacts.sqlite3"
    ),
) -> None:
    """Capture repeated zero-write Observer sessions; this does not imply acceptance."""

    ibkr_observe(
        state_path=state_path,
        control=control,
        snapshots=sessions,
        timeout=timeout,
        completed_orders_scope=completed_orders_scope,
        artifact_root=output,
        capture_scenario=capture_scenario,
        registry_path=registry_path,
    )


@app.command("ibkr-burn-in-evaluate")
def ibkr_burn_in_evaluate(
    input_root: Annotated[Path, typer.Option("--input", exists=True, file_okay=False)],
    output: Annotated[Path, typer.Option("--output")],
    minimum_sessions: Annotated[int | None, typer.Option("--minimum-sessions", min=1)] = None,
    registry_path: Annotated[Path, typer.Option("--registry")] = Path(
        ".state/evidence-artifacts.sqlite3"
    ),
) -> None:
    """Evaluate captured sessions and fail nonzero unless the corpus passes."""

    session_dirs = tuple(path for path in (input_root / "sessions").iterdir() if path.is_dir())
    evaluation = evaluate_burn_in_corpus(session_dirs, minimum_sessions=minimum_sessions)
    write_immutable_json(output, evaluation.corpus)
    registry = ArtifactRegistry(registry_path)
    try:
        registry.register(
            output,
            artifact_type=ArtifactType.BURN_IN_CORPUS,
            status="VERIFIED" if evaluation.decision == "PASS" else "REJECTED",
        )
    finally:
        registry.close()
    console.print_json(json.dumps(evaluation.corpus, sort_keys=True))
    if evaluation.decision != "PASS":
        raise typer.Exit(code=2)


@app.command("ibkr-golden-tape-evaluate")
def ibkr_golden_tape_evaluate(
    input_root: Annotated[Path, typer.Option("--input", exists=True, file_okay=False)],
    output: Annotated[Path, typer.Option("--output")],
    registry_path: Annotated[Path, typer.Option("--registry")] = Path(
        ".state/evidence-artifacts.sqlite3"
    ),
) -> None:
    """Replay the preregistered Golden Tape matrix and emit a callback truth map."""

    session_dirs = tuple(path for path in (input_root / "sessions").iterdir() if path.is_dir())
    report = evaluate_golden_tape_corpus(session_dirs)
    write_immutable_json(output, report)
    registry = ArtifactRegistry(registry_path)
    try:
        registry.register(
            output,
            artifact_type=ArtifactType.GOLDEN_TAPE,
            status="VERIFIED" if report["decision"] == "PASS" else "REJECTED",
        )
    finally:
        registry.close()
    console.print_json(json.dumps(report, sort_keys=True))
    if report["decision"] != "PASS":
        raise typer.Exit(code=2)


@app.command("ibkr-preflight")
def ibkr_preflight(
    output: Annotated[Path, typer.Option("--output")] = Path(".state/ibkr-preflight"),
    read_only_attested: Annotated[
        bool, typer.Option("--read-only-attested/--read-only-not-attested")
    ] = False,
    order_visibility_attested: Annotated[
        bool,
        typer.Option("--order-visibility-attested/--order-visibility-not-attested"),
    ] = False,
    registry_path: Annotated[Path, typer.Option("--registry")] = Path(
        ".state/evidence-artifacts.sqlite3"
    ),
) -> None:
    """Create a redacted zero-write IBKR environment preflight artifact."""

    config, secrets = load_config()
    artifact = build_ibkr_preflight(
        config,
        secrets,
        at=datetime.now(UTC),
        repository_root=Path.cwd(),
        read_only_attested=read_only_attested,
        order_visibility_attested=order_visibility_attested,
    )
    destination = output / f"{artifact['artifact_id']}.json"
    persist_ibkr_preflight(destination, artifact)
    registry = ArtifactRegistry(registry_path)
    try:
        registered_id = registry.register(
            destination,
            artifact_type=ArtifactType.IBKR_PREFLIGHT,
            status="VERIFIED" if artifact["ready"] else "REJECTED",
            git_commit=artifact.get("git_commit"),
            config_hash=artifact.get("config_hash"),
            account_hash=artifact.get("account_hash"),
        )
    finally:
        registry.close()
    console.print_json(json.dumps(artifact, sort_keys=True))
    console.print(f"artifact={destination} registry_id={registered_id}")
    if not artifact["ready"]:
        raise typer.Exit(code=2)


@pit_app.command("ingest-fixture")
def pit_ingest_fixture(
    fixture: Annotated[Path, typer.Option("--fixture", exists=True, file_okay=False)],
    state: Annotated[Path, typer.Option("--state", file_okay=False)],
) -> None:
    """Verify, normalize, quality-gate, and publish a frozen local fixture."""
    result = run_fixture_pipeline(fixture, state)
    console.print(
        f"snapshot_id={result.snapshot_id} feature_hash={result.feature_hash} "
        f"records={result.record_count}"
    )


@pit_app.command("qualify-source")
def pit_qualify_source(
    profile_path: Annotated[Path, typer.Option("--profile", exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output")],
    registry_path: Annotated[Path, typer.Option("--registry")] = Path(
        ".state/evidence-artifacts.sqlite3"
    ),
) -> None:
    """Fail closed unless a vendor profile proves all PIT and license requirements."""

    profile = DataSourceProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    _, secrets = load_config()
    reviewer_keys = (
        {
            str(key_id): base64.b64decode(str(value), validate=True)
            for key_id, value in json.loads(secrets.hanalpha_safety_case_public_keys).items()
        }
        if secrets.hanalpha_safety_case_public_keys
        else None
    )
    registry = ArtifactRegistry(registry_path)
    try:
        report = evaluate_source_profile(
            profile,
            at=datetime.now(UTC),
            registry=registry,
            reviewer_keys=reviewer_keys,
        )
    finally:
        registry.close()
    destination = output / f"{report.report_id}.json"
    persist_qualification(destination, report)
    console.print_json(report.model_dump_json())
    console.print(f"artifact={destination}")
    if report.decision.value != "PROMOTION_QUALIFIED":
        raise typer.Exit(code=2)


@pit_app.command("vendor-preflight")
def pit_vendor_preflight(
    output: Annotated[Path, typer.Option("--output")] = Path(".state/pit/vendor-preflight"),
) -> None:
    """Report configured vendor access without exposing any credential value."""

    _, secrets = load_config()
    artifact = vendor_access_preflight(secrets, at=datetime.now(UTC))
    destination = output / f"{artifact['artifact_id']}.json"
    persist_qualification(destination, artifact)
    console.print_json(json.dumps(artifact, sort_keys=True))
    console.print(f"artifact={destination}")


@pit_app.command("probe-source")
def pit_probe_source(
    source: Annotated[ProbeSource, typer.Option("--source")],
    identifier: Annotated[list[str], typer.Option("--identifier")],
    output: Annotated[Path, typer.Option("--output")],
    registry_path: Annotated[Path, typer.Option("--registry")] = Path(
        ".state/evidence-artifacts.sqlite3"
    ),
) -> None:
    """Run a bounded, secret-redacted real source probe and preserve raw payloads."""

    async def _run() -> None:
        _, secrets = load_config()
        try:
            manifest_path, manifest = await run_bounded_source_probe(
                source,
                tuple(identifier),
                output_root=output,
                secrets=secrets,
                at=datetime.now(UTC),
            )
        except (ValueError, SourceProbeError) as exc:
            raise typer.BadParameter(str(exc)) from None
        registry = ArtifactRegistry(registry_path)
        try:
            artifact_id = registry.register(
                manifest_path,
                artifact_type=ArtifactType.RAW_SAMPLE_MANIFEST,
                status="VERIFIED",
            )
        finally:
            registry.close()
        console.print_json(json.dumps(manifest, sort_keys=True))
        console.print(f"artifact={manifest_path} registry_id={artifact_id}")

    asyncio.run(_run())


@pit_app.command("audit-probe")
def pit_audit_probe(
    manifest: Annotated[Path, typer.Option("--manifest", exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output")],
    registry_path: Annotated[Path, typer.Option("--registry")] = Path(
        ".state/evidence-artifacts.sqlite3"
    ),
) -> None:
    """Derive typed, claim-scoped audits from one hash-bound bounded probe."""

    audits = audit_probe_manifest(manifest, output_root=output)
    registry = ArtifactRegistry(registry_path)
    results = []
    try:
        for path, artifact_type, document in audits:
            artifact_id = registry.register(
                path,
                artifact_type=artifact_type,
                status="VERIFIED" if document["decision"] == "PASS" else "REJECTED",
            )
            results.append(
                {
                    "artifact_type": artifact_type,
                    "decision": document["decision"],
                    "artifact": str(path),
                    "registry_id": artifact_id,
                    "qualifies_checks": document["qualifies_checks"],
                }
            )
    finally:
        registry.close()
    console.print_json(json.dumps(results, sort_keys=True))
    if not any(item["decision"] == "PASS" for item in results):
        raise typer.Exit(code=2)


@pit_app.command("register-artifact")
def pit_register_artifact(
    artifact: Annotated[Path, typer.Option("--artifact", exists=True, dir_okay=False)],
    artifact_type: Annotated[ArtifactType, typer.Option("--type")],
    status: Annotated[str, typer.Option("--status")] = "CAPTURED",
    registry_path: Annotated[Path, typer.Option("--registry")] = Path(
        ".state/evidence-artifacts.sqlite3"
    ),
) -> None:
    """Register a local immutable evidence file; registration cannot replace review."""

    registry = ArtifactRegistry(registry_path)
    try:
        artifact_id = registry.register(
            artifact,
            artifact_type=artifact_type,
            status=status.upper(),
        )
        resolution = registry.resolve(artifact_id, expected_type=artifact_type)
    finally:
        registry.close()
    console.print_json(resolution.model_dump_json())
    console.print(f"registry_id={artifact_id}")


@pit_app.command("evidence-list")
def pit_evidence_list(
    registry_path: Annotated[Path, typer.Option("--registry")] = Path(
        ".state/evidence-artifacts.sqlite3"
    ),
) -> None:
    """Show redacted Artifact Registry and Corpus Explorer evidence."""

    registry = ArtifactRegistry(registry_path)
    try:
        summary = registry.ops_summary()
        burn_in = registry.latest_verified_document(ArtifactType.BURN_IN_CORPUS)
        golden_tapes = registry.latest_verified_document(ArtifactType.GOLDEN_TAPE)
    finally:
        registry.close()
    console.print_json(
        json.dumps(
            {
                "registry": summary,
                "burn_in_corpus": burn_in,
                "golden_tape_corpus": golden_tapes,
            },
            sort_keys=True,
        )
    )


@local_onboard_app.command("ibkr")
def local_onboard_ibkr(
    output: Annotated[Path, typer.Option("--output")] = Path(".state/onboarding"),
    launch: Annotated[bool, typer.Option("--launch/--no-launch")] = False,
    wait_seconds: Annotated[
        float, typer.Option("--wait-seconds", min=0.0, max=300.0)
    ] = 0.0,
    read_only_attested: Annotated[
        bool, typer.Option("--read-only-attested/--read-only-not-attested")
    ] = False,
    github_summary_output: Annotated[
        bool, typer.Option("--github-summary/--no-github-summary")
    ] = False,
) -> None:
    """Inspect local IBKR prerequisites without reading or printing credentials."""

    config, _ = load_config()
    secrets, provider = _local_settings()
    if launch:
        try:
            launch_ibkr_application()
        except RuntimeError as exc:
            report = {
                "schema_version": "hanalpha-local-onboarding-v1",
                "report_id": "launch-blocked",
                "status": OperatorStatus.BLOCKED_HUMAN_ACTION,
                "checks": {},
                "blockers": [str(exc)],
                "secrets_redacted": True,
            }
            console.print(github_safe_summary(report))
            raise typer.Exit(code=status_exit(OperatorStatus.BLOCKED_HUMAN_ACTION)) from None
    if wait_seconds:
        wait_for_ibkr_socket(
            secrets.ibkr_host,
            secrets.ibkr_port,
            timeout_seconds=wait_seconds,
        )
    report = inspect_ibkr_onboarding(
        config,
        secrets,
        repository_root=Path.cwd(),
        provider=provider,
        at=datetime.now(UTC),
    )
    if report["status"] is OperatorStatus.PASS and not read_only_attested:
        report_body = {
            key: value for key, value in report.items() if key != "report_id"
        }
        report_body["status"] = OperatorStatus.BLOCKED_HUMAN_ACTION
        report_body["blockers"] = ["ATTEST_TWS_READ_ONLY_FOR_ACCOUNT_PREFLIGHT"]
        report_body["next_permitted_command"] = (
            "hanalpha local-onboard ibkr --read-only-attested"
        )
        report = {"report_id": canonical_hash(report_body), **report_body}
    elif report["status"] is OperatorStatus.PASS:
        preflight_code = _run_secret_child(
            [
                "ibkr-preflight",
                "--read-only-attested",
                "--output",
                str(output / "preflight"),
                "--registry",
                secrets.hanalpha_artifact_registry_path,
            ],
            secrets,
        )
        report_body = {
            key: value for key, value in report.items() if key != "report_id"
        }
        report_body["preflight_registered"] = preflight_code == 0
        if preflight_code != 0:
            report_body["status"] = OperatorStatus.FAILED_CODE
            report_body["blockers"] = ["INSPECT_REDACTED_IBKR_PREFLIGHT"]
            report_body["next_permitted_command"] = None
        report = {"report_id": canonical_hash(report_body), **report_body}
    destination = output / f"{report['report_id']}.json"
    write_immutable_json(destination, report)
    if github_summary_output:
        console.print(github_safe_summary(report))
    else:
        console.print_json(json.dumps(report, sort_keys=True))
        console.print(f"artifact={destination}")
    report_status = OperatorStatus(str(report["status"]))
    if report_status is not OperatorStatus.PASS:
        raise typer.Exit(code=status_exit(report_status))


@local_onboard_app.command("install-ibapi")
def local_onboard_install_ibapi(
    archive: Annotated[Path, typer.Option("--archive", exists=True, dir_okay=False)],
    license_accepted: Annotated[
        bool, typer.Option("--license-accepted/--license-not-accepted")
    ] = False,
) -> None:
    """Install a user-downloaded official TWS API ZIP without accepting its license."""

    try:
        version = install_official_ibapi_archive(
            archive,
            license_accepted=license_accepted,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        console.print(
            json.dumps(
                {
                    "status": OperatorStatus.BLOCKED_HUMAN_ACTION,
                    "blocker": type(exc).__name__ + ":" + str(exc),
                    "secrets_redacted": True,
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=status_exit(OperatorStatus.BLOCKED_HUMAN_ACTION)) from None
    console.print_json(
        json.dumps(
            {
                "status": OperatorStatus.PASS,
                "ibapi_version": version,
                "secrets_redacted": True,
            },
            sort_keys=True,
        )
    )


@local_onboard_app.command("discover-ibkr-account")
def local_onboard_discover_ibkr_account() -> None:
    """Store the single authenticated Paper account in Keychain without displaying it."""

    secrets, provider = _local_settings()
    if secrets.hanalpha_env.lower() != "paper" or secrets.ibkr_port not in {4002, 7497}:
        console.print(
            json.dumps(
                {
                    "status": OperatorStatus.BLOCKED_HUMAN_ACTION,
                    "blocker": "RESOLVE_PAPER_LIVE_ENVIRONMENT_AMBIGUITY",
                    "secrets_redacted": True,
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=status_exit(OperatorStatus.BLOCKED_HUMAN_ACTION))
    broker = IBKRBroker(
        host=secrets.ibkr_host,
        port=secrets.ibkr_port,
        client_id=secrets.ibkr_client_id,
        observer_only=True,
    )
    try:
        account = asyncio.run(broker.discover_single_managed_account())
        provider.set(LocalSecret.IBKR_ACCOUNT, account)
    except (RuntimeError, TimeoutError, OSError):
        console.print(
            json.dumps(
                {
                    "status": OperatorStatus.FAILED_CODE,
                    "blocker": "INSPECT_REDACTED_IBKR_ACCOUNT_DISCOVERY",
                    "secrets_redacted": True,
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=status_exit(OperatorStatus.FAILED_CODE)) from None
    console.print_json(
        json.dumps(
            {
                "status": OperatorStatus.PASS,
                "managed_account_count": 1,
                "stored_in_keychain": True,
                "secrets_redacted": True,
            },
            sort_keys=True,
        )
    )


@local_onboard_app.command("migrate-env")
def local_onboard_migrate_env(
    env_file: Annotated[Path, typer.Option("--env-file", exists=True, dir_okay=False)] = Path(
        ".env"
    ),
    scrub: Annotated[bool, typer.Option("--scrub/--keep-env")] = False,
) -> None:
    """Import supported ignored .env values into Keychain without printing them."""

    provider = MacOSKeychainSecretProvider()
    migrated = migrate_env_secrets(env_file, provider, scrub=scrub)
    console.print(
        json.dumps(
            {
                "status": OperatorStatus.PASS,
                "migrated_secret_count": len(migrated),
                "env_scrubbed": scrub,
                "secrets_redacted": True,
            },
            sort_keys=True,
        )
    )


@local_onboard_app.command("set-secret")
def local_onboard_set_secret(
    name: Annotated[LocalSecret, typer.Option("--name")],
) -> None:
    """Store one local value in macOS Keychain without exposing it in argv or output."""

    value = typer.prompt(f"Enter local value for {name.value}", hide_input=True)
    MacOSKeychainSecretProvider().set(name, value)
    console.print(
        json.dumps(
            {
                "status": OperatorStatus.PASS,
                "stored": name.value,
                "secrets_redacted": True,
            },
            sort_keys=True,
        )
    )


@e1_app.command("run")
def e1_run(
    scope: Annotated[E1Scope, typer.Option("--scope")],
    output: Annotated[Path, typer.Option("--output")] = Path(".state/e1"),
    execute: Annotated[bool, typer.Option("--execute/--dry-run")] = False,
    read_only_attested: Annotated[
        bool, typer.Option("--read-only-attested/--read-only-not-attested")
    ] = False,
    order_visibility_attested: Annotated[
        bool,
        typer.Option("--order-visibility-attested/--order-visibility-not-attested"),
    ] = False,
    github_summary_output: Annotated[
        bool, typer.Option("--github-summary/--no-github-summary")
    ] = False,
) -> None:
    """Resume one E1-B scope and capture at most one verified session per invocation."""

    config, _ = load_config()
    secrets, provider = _local_settings()
    onboarding = inspect_ibkr_onboarding(
        config,
        secrets,
        repository_root=Path.cwd(),
        provider=provider,
        at=datetime.now(UTC),
    )
    if onboarding["status"] is not OperatorStatus.PASS:
        console.print(
            github_safe_summary(onboarding)
            if github_summary_output
            else json.dumps(onboarding, sort_keys=True)
        )
        raise typer.Exit(code=status_exit(onboarding["status"]))
    scope_root = output / scope.value
    progress = e1_progress(scope_root, scope)
    if execute and progress["next_scenario"]:
        mode_flags = (
            ["--read-only-attested"]
            if read_only_attested
            else (
                ["--order-visibility-attested"]
                if order_visibility_attested
                else ["--read-only-not-attested", "--order-visibility-not-attested"]
            )
        )
        preflight_code = _run_secret_child(
            [
                "ibkr-preflight",
                *mode_flags,
                "--output",
                str(scope_root / "preflight"),
                "--registry",
                secrets.hanalpha_artifact_registry_path,
            ],
            secrets,
        )
        if preflight_code != 0:
            progress = {
                **progress,
                "status": OperatorStatus.BLOCKED_HUMAN_ACTION,
                "next_human_action": "ATTEST_CORRECT_TWS_OBSERVATION_MODE",
            }
        else:
            capture_code = _run_secret_child(
                [
                    "ibkr-burn-in",
                    "--state",
                    secrets.hanalpha_ibkr_observer_path,
                    "--control",
                    ".state/execution-control.sqlite3",
                    "--sessions",
                    "1",
                    "--completed-orders-scope",
                    scope.value,
                    "--capture-scenario",
                    str(progress["next_scenario"]),
                    "--output",
                    str(scope_root),
                    "--registry",
                    secrets.hanalpha_artifact_registry_path,
                ],
                secrets,
            )
            if capture_code != 0:
                progress = {
                    **progress,
                    "status": OperatorStatus.FAILED_CODE,
                    "next_human_action": "INSPECT_REDACTED_LOCAL_CAPTURE_LOGS",
                }
            else:
                progress = e1_progress(scope_root, scope)
                corpus_code = _run_secret_child(
                    [
                        "ibkr-burn-in-evaluate",
                        "--input",
                        str(scope_root),
                        "--output",
                        str(
                            scope_root
                            / "corpora"
                            / f"{progress['report_id']}.json"
                        ),
                        "--registry",
                        secrets.hanalpha_artifact_registry_path,
                    ],
                    secrets,
                )
                if corpus_code not in {0, 2}:
                    progress = {
                        **progress,
                        "status": OperatorStatus.FAILED_CODE,
                        "next_human_action": "INSPECT_REDACTED_CORPUS_EVALUATION",
                    }
    progress_body = {key: value for key, value in progress.items() if key != "report_id"}
    progress = {"report_id": canonical_hash(progress_body), **progress_body}
    destination = scope_root / f"{progress['report_id']}.runner.json"
    write_immutable_json(destination, progress)
    console.print(
        runner_github_summary(progress)
        if github_summary_output
        else json.dumps(progress, sort_keys=True)
    )
    if progress["status"] is not OperatorStatus.PASS:
        raise typer.Exit(code=status_exit(progress["status"]))


@r1_app.command("run")
def r1_run(
    source: Annotated[ProbeSource, typer.Option("--source")],
    output: Annotated[Path, typer.Option("--output")] = Path(".state/r1"),
    registry_path: Annotated[Path, typer.Option("--registry")] = Path(
        ".state/evidence-artifacts.sqlite3"
    ),
    execute: Annotated[bool, typer.Option("--execute/--dry-run")] = False,
    github_summary_output: Annotated[
        bool, typer.Option("--github-summary/--no-github-summary")
    ] = False,
) -> None:
    """Run one bounded R1-B source bundle; rights and review remain human gates."""

    secrets, _ = _local_settings()

    async def _run() -> dict[str, object]:
        registry = ArtifactRegistry(registry_path)
        try:
            return await run_r1_source(
                source,
                output_root=output,
                registry=registry,
                secrets=secrets,
                at=datetime.now(UTC),
                execute=execute,
            )
        finally:
            registry.close()

    try:
        report = asyncio.run(_run())
    except (ValueError, SourceProbeError) as exc:
        report_body: dict[str, object] = {
            "schema_version": "r1-external-runner-progress-v1",
            "source_id": source.value,
            "status": OperatorStatus.FAILED_CODE,
            "reason": type(exc).__name__,
            "artifact_ids": [],
            "secrets_redacted": True,
        }
        report = {"report_id": canonical_hash(report_body), **report_body}
    destination = output / source.value / f"{report['report_id']}.runner.json"
    write_immutable_json(destination, report)
    console.print(
        runner_github_summary(report)
        if github_summary_output
        else json.dumps(report, sort_keys=True)
    )
    report_status = OperatorStatus(str(report["status"]))
    if report_status is not OperatorStatus.PASS:
        raise typer.Exit(code=status_exit(report_status))


@pit_app.command("quality")
def pit_quality(
    state: Annotated[Path, typer.Option("--state", exists=True, file_okay=False)],
    snapshot: Annotated[str, typer.Option("--snapshot")],
) -> None:
    """Show the stored quality decision for a snapshot."""
    catalog = PITCatalog(state / "catalog.sqlite3")
    try:
        report = catalog.get_quality(snapshot)
        if report is None:
            raise typer.BadParameter("snapshot has no quality report")
        console.print(f"passed={report.passed} digest={report.digest} issues={len(report.issues)}")
    finally:
        catalog.close()


@pit_app.command("snapshot")
def pit_snapshot(
    state: Annotated[Path, typer.Option("--state", exists=True, file_okay=False)],
    snapshot: Annotated[str, typer.Option("--snapshot")],
) -> None:
    """Show a snapshot manifest, quality decision, and publication state."""
    catalog = PITCatalog(state / "catalog.sqlite3")
    try:
        console.print_json(json.dumps(catalog.snapshot_document(snapshot), sort_keys=True))
    finally:
        catalog.close()


@app.command()
def doctor(
    config_path: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Validate local configuration and safety invariants."""
    config, secrets = load_config(config_path)
    rows = [
        ("operating mode", config.operating_mode.value),
        ("mode", config.mode),
        ("broker", config.execution.broker),
        ("broker writes enabled", str(config.execution.broker_write_enabled)),
        ("operator API enabled", str(config.execution.operator_api_enabled)),
        ("universe", str(len(config.universe))),
        ("ledger", secrets.hanalpha_ledger_path),
        ("IBKR port", str(secrets.ibkr_port)),
        ("LLM configured", str(bool(secrets.llm_api_key and secrets.llm_model))),
    ]
    table = Table(title="Han Alpha Doctor")
    table.add_column("Check")
    table.add_column("Value")
    for key, value in rows:
        table.add_row(key, value)
    console.print(table)
    if config.operating_mode.value == "live_proposal":
        console.print(
            "[bold red]LIVE PROPOSAL configuration loaded. Broker writes are structurally disabled.[/bold red]"
        )
    else:
        console.print("[green]Configuration validated.[/green]")


@app.command()
def demo(
    cycles: Annotated[int, typer.Option(min=1, max=100)] = 5,
    config_path: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Run deterministic local paper cycles without external credentials."""

    async def _run() -> None:
        config, secrets = load_config(config_path)
        ledger_path = Path(secrets.hanalpha_ledger_path)
        if os.getenv("HANALPHA_DEMO_RESET", "1") == "1" and ledger_path.exists():
            ledger_path.unlink()
        ledger = Ledger(ledger_path)
        try:
            system = await build_system(config, secrets, ledger)
            for _ in range(cycles):
                result = await system.run_cycle()
                console.print(
                    f"cycle={result['cycle']} regime={result['regime']['regime']} "
                    f"signals={len(result['signals'])} orders={len(result['orders'])} "
                    f"nlv={result['account']['net_liquidation']:.2f}"
                )
            console.print_json(json.dumps(await system.status(), default=str))
        finally:
            if "system" in locals():
                system.close()
            ledger.close()

    asyncio.run(_run())


@app.command()
def backtest(
    symbol: str = "NVDA",
    bars: Annotated[int, typer.Option(min=200, max=5000)] = 1000,
    state: Annotated[Path, typer.Option("--state", file_okay=False)] = Path(".state/research"),
    config_path: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Run the deterministic M3 replay and register a reproducible result bundle."""

    async def _run() -> None:
        config, _ = load_config(config_path)
        provider = SyntheticMarketDataProvider(config.bar_interval_minutes)
        symbol_bars = await provider.get_bars(symbol, bars)
        fixed_start = datetime(2020, 1, 1, tzinfo=UTC)
        normalized = [
            bar.model_copy(
                update={
                    "timestamp": fixed_start
                    + timedelta(minutes=index * config.bar_interval_minutes)
                }
            )
            for index, bar in enumerate(symbol_bars)
        ]
        snapshot_id = canonical_hash(
            {
                "provider": "synthetic-v1",
                "seed": provider.seed,
                "symbol": symbol,
                "bars": [bar.model_dump(mode="json") for bar in normalized],
            }
        )
        frames = [
            ReplayFrame(
                snapshot_id=snapshot_id,
                as_of=bar.timestamp,
                bars=[
                    SimulationBar(
                        snapshot_id=snapshot_id,
                        instrument_id=symbol,
                        source_record_id=f"synthetic:{symbol}:{index}",
                        source_revision=1,
                        event_time=bar.timestamp,
                        available_at=bar.timestamp,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=bar.volume,
                    )
                ],
            )
            for index, bar in enumerate(normalized)
        ]
        fill_policy = FillPolicy()
        portfolio_policy = PortfolioPolicy()
        engine_config_hash = canonical_hash(
            {
                "starting_cash": "100000",
                "portfolio_policy": portfolio_policy,
                "fill_policy": fill_policy,
            }
        )
        engine = PortfolioReplayEngine(
            starting_cash=Decimal("100000"),
            portfolio_policy=portfolio_policy,
            exchange=HistoricalExchange(fill_policy),
            config_hash=engine_config_hash,
        )
        strategy = SlowTrendStrategy(fast_window=50, slow_window=200, quantity=10)
        policy = ResearchPolicyAdapter(strategy)
        registry = ExperimentRegistry(state / "experiments.sqlite3")
        try:
            parameters = {"fast_window": 50, "slow_window": 200, "quantity": 10}
            anchor = datetime(2020, 1, 1, tzinfo=UTC)
            protocol = PreregisteredProtocol(
                name="synthetic-trend-mechanics",
                version="1",
                researcher_id="hanalpha-cli",
                hypothesis=(
                    "synthetic trend baseline validates mechanics; it is not alpha evidence"
                ),
                snapshot_id=snapshot_id,
                universe_hash=canonical_hash([symbol]),
                feature_schema_hash=canonical_hash({"synthetic-bars": "1"}),
                cost_policy_hash=fill_policy.policy_hash,
                train=DateWindow(start=anchor, end=anchor + timedelta(days=100)),
                validation=DateWindow(
                    start=anchor + timedelta(days=101), end=anchor + timedelta(days=150)
                ),
                test=DateWindow(
                    start=anchor + timedelta(days=151), end=anchor + timedelta(days=250)
                ),
                parameter_ranges={},
                success=SuccessCriteria(
                    minimum_oos_return=Decimal("0"),
                    maximum_drawdown=Decimal("0.25"),
                    minimum_dsr_probability=Decimal("0.95"),
                    maximum_pbo=Decimal("0.20"),
                    minimum_cost_stress_return=Decimal("0"),
                    maximum_contribution_share=Decimal("0.35"),
                    minimum_observations=60,
                ),
                budget=ResearchBudget(max_trials=8, used_trials=0),
                benchmarks=("cash", "buy-and-hold"),
                purge_bars=5,
                embargo_bars=5,
            )
            registry.register_protocol(protocol)
            allocation = registry.allocate_trial(
                protocol.protocol_hash,
                parameters=parameters,
                window_role=WindowRole.TEST,
                idempotency_key=f"synthetic:{symbol}:{bars}:{provider.seed}",
                at=frames[-1].as_of,
            )
            manifest = ExperimentManifest(
                snapshot_id=snapshot_id,
                code_hash=canonical_hash({"package": "han-alpha", "m3_schema": "2"}),
                config_hash=engine_config_hash,
                cost_policy_hash=fill_policy.policy_hash,
                universe_hash=protocol.universe_hash,
                metric_schema_version="2",
                seed=provider.seed,
                strategy_id=policy.name,
                strategy_version=policy.version,
                hypothesis=protocol.hypothesis,
                parameters=parameters,
                protocol_hash=protocol.protocol_hash,
                trial_allocation_id=allocation.allocation_id,
                parameter_point_hash=allocation.parameter_point_hash,
                window_role=allocation.window_role,
                research_program_id=protocol.research_program_id,
            )
            result = ExperimentRunner(registry, state / "artifacts").run(
                manifest=manifest,
                engine=engine,
                frames=frames,
                policy=policy,
                at=frames[-1].as_of,
            )
        finally:
            registry.close()
        console.print_json(result.metrics.model_dump_json(indent=2))
        console.print(f"fills={result.fill_count} result_hash={result.result_hash}")
        console.print(
            f"experiment_id={result.experiment_id} "
            f"artifacts={state / 'artifacts' / result.experiment_id}"
        )

    asyncio.run(_run())


@app.command("legacy-backtest", hidden=True)
def legacy_backtest(
    symbol: str = "NVDA",
    bars: Annotated[int, typer.Option(min=200, max=5000)] = 1000,
    config_path: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Run the frozen M0 verifier retained only for backward comparison."""

    async def _run() -> None:
        config, _ = load_config(config_path)
        provider = SyntheticMarketDataProvider(config.bar_interval_minutes)
        symbol_bars = await provider.get_bars(symbol, bars)
        benchmark_bars = await provider.get_bars(config.benchmarks["market"], bars)
        strategy = BreakoutStrategy(config.strategies["breakout"])
        metrics, trades = BacktestEngine(starting_cash=100_000).run(
            symbol=symbol,
            bars=symbol_bars,
            benchmark_bars=benchmark_bars,
            strategy=strategy,
        )
        console.print_json(metrics.model_dump_json(indent=2))
        console.print(f"trades={len(trades)}")

    asyncio.run(_run())


@app.command()
def worker(
    interval_seconds: Annotated[int, typer.Option(min=5, max=3600)] = 60,
    cycles: Annotated[int, typer.Option(min=0, max=1000000)] = 0,
    config_path: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Run scheduled trading cycles. cycles=0 continues until interrupted."""

    async def _run() -> None:
        config, secrets = load_config(config_path)
        ledger = Ledger(secrets.hanalpha_ledger_path)
        system = await build_system(config, secrets, ledger)
        completed = 0
        try:
            while cycles == 0 or completed < cycles:
                try:
                    result = await system.run_cycle()
                    console.print(
                        f"cycle={result['cycle']} signals={len(result.get('signals', []))} "
                        f"orders={len(result.get('orders', []))} "
                        f"frozen={result.get('kill_switch', {}).get('frozen', False)}"
                    )
                except Exception as exc:
                    system.kill_switch.freeze(f"worker_exception:{type(exc).__name__}")
                    console.print(f"[bold red]cycle failed closed: {exc}[/bold red]")
                completed += 1
                if cycles == 0 or completed < cycles:
                    await asyncio.sleep(interval_seconds)
        finally:
            system.close()
            ledger.close()

    asyncio.run(_run())


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = False,
) -> None:
    """Start the local API. Mutating routes are disabled unless explicitly authorized."""
    if host not in {"127.0.0.1", "localhost"}:
        console.print(
            "[bold yellow]Warning: read routes are unauthenticated. Do not expose this API to the internet.[/bold yellow]"
        )
    uvicorn.run("hanalpha.api.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
