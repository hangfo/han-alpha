# Product requirements document

## Product name

Han Alpha Trading System (HATS)

## Mission

Create a directly runnable trading-research and paper-execution platform that can discover, test, reject, and operate trading strategies under realistic data, cost, and risk assumptions.

## Success definition

The system is successful only when a strategy demonstrates, after costs:

- positive out-of-sample expectancy;
- stable performance across market regimes;
- acceptable drawdown;
- no dependence on one symbol or one short period;
- robustness to parameter perturbation;
- reproducible point-in-time inputs;
- paper behavior close enough to conservative shadow fills;
- operational reliability under disconnects and duplicate callbacks.

## Non-goals for V1

- guaranteed profits;
- high-frequency trading;
- options or short selling;
- unrestricted autonomous live orders;
- LLM-generated prices, stops, targets, or sizes;
- reinforcement from a handful of recent trades;
- scanning every listed security with an LLM every few minutes.

## V1 user journeys

### Research operator

- Start the system without external credentials.
- Run repeatable synthetic cycles.
- Inspect signals, agent assessments, risk decisions, orders, positions, and ledger events.
- Run a no-look-ahead baseline backtest.

### Paper operator

- Connect TWS/IB Gateway paper account.
- Confirm account and data health.
- Generate bracket orders from deterministic plans.
- Freeze new orders, cancel all, or flatten all.
- Reconcile broker callbacks and local ledger.

### Strategy researcher

- Add a strategy implementing the Strategy protocol.
- Compare it with SPY/QQQ and a non-LLM baseline.
- Run walk-forward, cost, delay, and parameter-stress tests.
- Promote only through a Champion-Challenger process.

## Functional requirements

- Point-in-time data models.
- Strategy isolation.
- Regime gating.
- Read-only agent committee.
- Deterministic risk engine.
- Paper and live environment separation.
- Idempotent broker submission.
- Append-only ledger.
- Local API.
- Kill switch, cancel-all, and flatten-all.
- Backtest metrics.
- Adversarial tests.

## Promotion gates

A strategy cannot enter paper automation unless it has:

- at least 300 out-of-sample trades or a statistically justified alternative;
- cost-adjusted profit factor above 1.25;
- out-of-sample Sharpe above 1.0;
- maximum drawdown below 12%;
- positive results in at least 70% of rolling windows;
- no single symbol contributing more than 25% of profit;
- positive performance under +/-20% parameter perturbation.

A paper strategy cannot enter live pilot unless it has:

- at least 60 trading days of paper observation;
- broker fills compared with shadow fills;
- no unresolved order-state mismatches;
- no risk-limit violations;
- acceptable drawdown and loss clustering;
- operator approval and separate live configuration review.
