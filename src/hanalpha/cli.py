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
from hanalpha.experiments.models import ExperimentManifest
from hanalpha.experiments.registry import ExperimentRegistry
from hanalpha.experiments.runner import ExperimentRunner
from hanalpha.orchestrator import build_system
from hanalpha.pit.catalog import PITCatalog
from hanalpha.portfolio import Ledger
from hanalpha.research.adapter import ResearchPolicyAdapter
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
        manifest = ExperimentManifest(
            snapshot_id=snapshot_id,
            code_hash=canonical_hash({"package": "han-alpha", "m3_schema": "1"}),
            config_hash=engine_config_hash,
            cost_policy_hash=fill_policy.policy_hash,
            universe_hash=canonical_hash([symbol]),
            metric_schema_version="2",
            seed=provider.seed,
            strategy_id=policy.name,
            strategy_version=policy.version,
            hypothesis="synthetic trend baseline validates mechanics; it is not alpha evidence",
            parameters={"fast_window": 50, "slow_window": 200, "quantity": 10},
        )
        registry = ExperimentRegistry(state / "experiments.sqlite3")
        try:
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
