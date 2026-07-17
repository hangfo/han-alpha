# Han Alpha Trading System

A directly runnable, evidence-grounded trading research and IBKR paper-execution system.

The system is built around one rule: **LLMs may interpret evidence and veto trades, but deterministic code controls prices, position size, risk limits, order state, and broker access.**

## What works now

- Deterministic synthetic market-data mode requiring no keys.
- Three independent long-only strategies: breakout, trend pullback, event continuation.
- Market-regime gating.
- Evidence, market-alignment, and skeptic agents.
- Prompt-injection filtering and fabricated-evidence rejection.
- Deterministic position sizing and portfolio risk limits.
- Conservative simulated broker with slippage, commissions, bracket protection, idempotency, cancel-all, and flatten-all.
- Optional official IBKR TWS API bracket-order adapter.
- Append-only SQLite audit ledger.
- FastAPI control plane and CLI.
- Event-driven baseline backtester.
- Unit, integration, and adversarial tests.

## Safety boundary

This repository is not a promise of profitability. Its purpose is to produce a system whose behavior can be measured, replayed, falsified, and safely tested. Live trading is deliberately harder to enable than paper trading.

## Quick start

```bash
cd han-alpha
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
hanalpha doctor
hanalpha demo --cycles 10
hanalpha backtest --symbol NVDA --bars 1000
pytest
```

Start the local API:

```bash
hanalpha serve
```

Then visit `http://127.0.0.1:8000/docs`.

## IBKR paper setup

1. Use an approved and funded IBKR Pro account with a Paper Trading account.
2. Install current stable TWS or IB Gateway and the matching official TWS API.
3. Enable socket clients in TWS/IB Gateway.
4. For Gateway paper use port `4002`; for TWS paper use `7497` unless changed locally.
5. Keep `configs/paper.yaml` and a paper-only client ID.
6. Install the official Python API from the TWS API distribution so `import ibapi` works.
7. Change `mode` only after adding a real market-data provider; change `execution.broker` to `ibkr` only for paper testing.

## Architecture

```text
Market data / SEC / FRED
          |
Point-in-time evidence + features
          |
Deterministic strategies
          |
Read-only research agents and skeptic
          |
Deterministic risk engine
          |
Order state machine and broker adapter
          |
Append-only ledger + API + monitoring
```

## Important commands

```bash
hanalpha doctor
hanalpha demo --cycles 20
hanalpha backtest --symbol CRDO --bars 1500
hanalpha serve --host 127.0.0.1 --port 8000
pytest
ruff check src tests
```


## Codex handoff

This repository includes a complete Codex task package. Start with `CODEX_START_HERE.md`; repository-wide instructions live in `AGENTS.md`, and the exact completion criteria live in `docs/codex/ACCEPTANCE_CRITERIA.md`. The copy-paste master prompt is `docs/codex/CODEX_PROMPT_ZH.md`. For a one-command local setup run `./scripts/bootstrap_codex.sh`; user preparation and resume/audit prompts are in `docs/codex/`.

```bash
./scripts/preflight.sh
./scripts/verify_all.sh
```

## Documentation

- `docs/CONVERSATION_SYNTHESIS.md`
- `docs/PRD.md`
- `docs/ARCHITECTURE.md`
- `docs/STRATEGY_SPEC.md`
- `docs/DATA_AND_PERMISSIONS.md`
- `docs/SECURITY_THREAT_MODEL.md`
- `docs/TEST_PLAN.md`
- `docs/IBKR_PAPER_RUNBOOK.md`
- `docs/ROADMAP.md`
- `docs/VERIFICATION_REPORT.md`
