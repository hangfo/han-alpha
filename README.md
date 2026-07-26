# Han Alpha Trading System

> E1-B/R1-B local tooling status (2026-07-26): observer writes are structurally
> blocked, Artifact/Claim resolution, Golden-Tape replay, bounded real-source
> probes and Evidence/Corpus dashboards are implemented. Official IBKR callbacks,
> licensed PIT data, external review, Alpha and every Paper write remain blocked.

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
- Immutable local PIT raw/catalog/Parquet snapshots with typed as-of queries.
- Frozen synthetic symbology, delisting, revision, corporate-action and DST fixtures.
- Deterministic PIT portfolio replay with shared cash/risk reservations, explicit orders/fills, corporate actions and parity hashes.
- Canonical experiment manifests, failed-trial cemetery and immutable JSON/HTML result artifacts.
- Point-in-time research contexts, interpretable baselines, walk-forward diagnostics, bounded counterfactuals and fail-closed promotion review.
- Durable capsule/reservation/outbox/inbox execution control, persistent freeze tickets, exact cash/protection reconciliation and fault-injectable Fake Broker.
- Read-only IBKR callback fact tape, snapshot completeness certificates, order-independent reducer and shadow execution reality-gap ledger.
- Stable Observer Scope Policy, canonical broker-state Authority, versioned Approval Arms and source-backed read-only Ops Dashboard.
- Unit, integration, and adversarial tests.

## Safety boundary

This repository is not a promise of profitability. Its purpose is to produce a system whose behavior can be measured, replayed, falsified, and safely tested. Live trading is deliberately harder to enable than paper trading.

## Quick start

```bash
cd han-alpha
python3.12 -m venv .venv
source .venv/bin/activate
pip install --require-hashes -r requirements-dev.lock
pip install --no-deps --no-build-isolation -e .
cp .env.example .env
hanalpha doctor
hanalpha demo --cycles 10
hanalpha backtest --symbol NVDA --bars 1000
hanalpha pit ingest-fixture --fixture tests/pit/fixtures/v1 --state .state/pit
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
8. Run `hanalpha ibkr-preflight --read-only-attested` for account facts. IBKR
   Read-Only hides order information, so the separate manual-order matrix uses
   `--order-visibility-attested` with Han Alpha's structurally write-blocked
   observer. Run scoped zero-write
   `ibkr-burn-in` captures, and `ibkr-burn-in-evaluate`; do not enable writes
   until E1-B and E2 pass.

See `docs/BROKER_AND_DATA_ONBOARDING.md` for external setup and
`docs/R2_STRATEGY_AND_LLM_AGENT_POSITIONING.md` for the post-qualification
strategy and LLM boundary.

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
hanalpha pit quality --state .state/pit --snapshot <snapshot_id>
hanalpha pit snapshot --state .state/pit --snapshot <snapshot_id>
hanalpha execution-reconcile --control <control.sqlite3> --broker-state <fake-broker.sqlite3>
hanalpha execution-approvals --control <control.sqlite3>
hanalpha ibkr-preflight --read-only-attested
hanalpha ibkr-observe --state .state/ibkr-observer.sqlite3 --control .state/execution-control.sqlite3 --completed-orders-scope api --timeout 15
hanalpha pit vendor-preflight
hanalpha pit probe-source --source sec_edgar --identifier 320193 --output .state/pit/probes/sec
hanalpha pit audit-probe --manifest <probe-manifest.json> --output .state/pit/audits
hanalpha pit evidence-list
hanalpha pit qualify-source --profile configs/data-sources/massive-price-profile.json --output .state/pit/qualifications/massive
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
- `docs/BROKER_AND_DATA_ONBOARDING.md`
- `docs/ROADMAP.md`
- `docs/VERIFICATION_REPORT.md`
### Deterministic research backtest

```bash
hanalpha backtest --symbol NVDA --bars 400 --state .state/research
```

This command uses the portfolio replay and append-only experiment registry and writes immutable `manifest.json`, `result.json`, and `report.html` artifacts. Its built-in data is synthetic and validates mechanics only; it is not Alpha evidence. The pre-M2 verifier remains available as the hidden `legacy-backtest` compatibility command.
