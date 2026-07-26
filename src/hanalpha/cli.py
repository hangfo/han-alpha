from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from hanalpha.backtest import BacktestEngine
from hanalpha.config import load_config
from hanalpha.data.fixtures import run_fixture_pipeline
from hanalpha.data.synthetic import SyntheticMarketDataProvider
from hanalpha.execution.control_store import DurableExecutionStore
from hanalpha.execution.fake_broker import DurableFakeBroker
from hanalpha.execution.ibkr import IBKRBroker
from hanalpha.execution.ibkr_observer import IBKRFactStore
from hanalpha.execution.ibkr_snapshot import IBKRBrokerSnapshotAdapter
from hanalpha.execution.reconciliation import Reconciler
from hanalpha.execution.worker import ExecutionWorker
from hanalpha.experiments.models import ExperimentManifest, WindowRole
from hanalpha.experiments.registry import ExperimentRegistry
from hanalpha.experiments.runner import ExperimentRunner
from hanalpha.orchestrator import build_system
from hanalpha.pit.catalog import PITCatalog
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
app.add_typer(pit_app, name="pit")
console = Console()


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
    snapshots: Annotated[int, typer.Option("--snapshots", min=1, max=20)] = 2,
    timeout: Annotated[float, typer.Option("--timeout", min=1, max=120)] = 15,
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
        )
        store = IBKRFactStore(state_path)
        execution_store = DurableExecutionStore(control)
        try:
            for index in range(snapshots):
                certificate, model = await broker.observe_read_only(store, timeout=timeout)
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

    asyncio.run(_run())


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
