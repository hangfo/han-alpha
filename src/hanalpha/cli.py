from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from hanalpha.backtest import BacktestEngine
from hanalpha.config import load_config
from hanalpha.data.synthetic import SyntheticMarketDataProvider
from hanalpha.orchestrator import build_system
from hanalpha.portfolio import Ledger
from hanalpha.strategies import BreakoutStrategy

app = typer.Typer(no_args_is_help=True, help="Han Alpha trading system CLI")
console = Console()


@app.command()
def doctor(
    config_path: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Validate local configuration and safety invariants."""
    config, secrets = load_config(config_path)
    rows = [
        ("environment", config.environment),
        ("mode", config.mode),
        ("broker", config.execution.broker),
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
    if config.environment == "live":
        console.print("[bold red]LIVE configuration loaded. Orders still require human approval.[/bold red]")
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
    config_path: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    """Run a repeatable synthetic no-look-ahead baseline backtest."""

    async def _run() -> None:
        config, _ = load_config(config_path)
        provider = SyntheticMarketDataProvider(config.bar_interval_minutes)
        symbol_bars = await provider.get_bars(symbol, bars)
        benchmark_bars = await provider.get_bars(config.benchmarks["market"], bars)
        strategy = BreakoutStrategy(config.strategies["breakout"])
        engine = BacktestEngine(starting_cash=100_000)
        metrics, trades = engine.run(
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
    """Start the local API. Bind to localhost unless you have added authentication."""
    if host not in {"127.0.0.1", "localhost"}:
        console.print(
            "[bold yellow]Warning: API has no remote authentication. Do not expose it to the internet.[/bold yellow]"
        )
    uvicorn.run("hanalpha.api.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
