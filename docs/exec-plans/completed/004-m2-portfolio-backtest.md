# M2 execution plan: portfolio replay and experiment contracts

Status: COMPLETE
Owner: Codex
Created: 2026-07-18

## First-principles objective

A backtest is credible only if it is an auditable capital-and-order state machine driven by facts visible at each decision time. M2 will therefore prove accounting conservation, no-look-ahead portfolio replay and deterministic experiment identity before adding more strategies, real data, UI or LLMs.

M2 does not aim to prove alpha. Its output is a trustworthy falsification instrument.

## Scope and authority

- Input is the M1 published frozen snapshot through `AsOfRepository`; raw SQL, Parquet paths and current-symbol lists remain forbidden to strategies.
- Execution is a deterministic local simulator. No vendor, LLM, IBKR or order call is authorized.
- Existing V0.1 strategies are compatibility fixtures, not validated strategies.
- SQLite stores experiment/control metadata; append-only event artifacts and larger result tables may use Parquet. No PostgreSQL/Kafka/distributed service is justified in M2.

## Invariants

1. Every decision carries explicit `snapshot_id`, aware `as_of`, strategy/config/code hashes and experiment ID.
2. Cash, positions, open orders, reservations, commissions and realized/unrealized PnL reconcile after every event.
3. An order cannot fill before submission or from a bar unavailable at the decision/fill time.
4. Buy fills never exceed their limit; sell fills never fall below it.
5. Risk uses executable plan price to stop distance and includes positions plus open/reserved exposure.
6. Corporate actions affect holdings/cash through explicit ledger events; raw prices remain unchanged.
7. Identical snapshot/code/config/seed/event order yields identical event and metric hashes.
8. Unknown, duplicate, late or out-of-order events fail closed or follow a documented deterministic replay policy.

## Architecture

```text
published PIT snapshot + AsOfContext
              |
      deterministic event cursor
              |
    strategy candidate interface
              |
 portfolio/risk reservation policy
              |
 order state machine + fill model
              |
 double-entry cash/position ledger
              |
 experiment registry + artifacts
```

Historical and later runtime modes must share candidate, risk and order-domain contracts. Only clock/data cursor and execution adapter may differ.

## Work packages

### WP1: failing accounting and time contracts

- Add property/scenario tests for cash conservation, position lots, realized PnL, commissions, reservations and corporate actions.
- Add adversarial no-look-ahead tests for future bars, current ticker leakage, same-bar decision/fill leakage and out-of-order events.
- Freeze deterministic event ordering and collision policy in ADR 0003.
- Incorporate the accepted findings in `docs/v2-plan/09_PASTED_REVIEW_AND_M2_DECISIONS_ZH.md`.

### WP2: portfolio ledger and order state machine

- Introduce typed `OrderIntent`, `OrderState`, `Fill`, `CashEntry`, `PositionLot`, `Reservation` and `PortfolioSnapshot`.
- Make state transitions explicit and reject illegal/repeated transitions.
- Keep this local simulator separate from the M5 durable Broker control plane while preserving compatible domain events.

### WP3: deterministic execution model

- Model market/limit orders, next-eligible-bar fills, configurable spread/slippage/commission, partial fills, volume participation, gaps and halts.
- Version every cost/fill policy and include it in experiment identity.
- Provide optimistic/base/adverse cost scenarios; never select the best scenario after seeing results.

### WP4: portfolio engine and risk parity

- Replay multiple symbols/strategies over one cash pool.
- Account for open orders and reservations in gross, symbol, sector and cash constraints.
- Route candidate generation through explicit M1 `AsOfContext`; remove wall clock from historical paths.

### WP5: experiment registry and metrics

- Hash snapshot, code, strategy config, cost policy, universe rule, seed and metric schema into an immutable experiment ID.
- Persist run state, artifacts, failure reason and environment metadata.
- Produce returns, drawdown, turnover, exposure, capacity proxies and benchmark/factor-ready series; do not add data-mined strategy claims in M2.
- Preserve failed hypotheses as a strategy cemetery and link counterfactual variants without permitting failed-run promotion.
- Emit deterministic JSON plus a minimal static HTML research report; defer the React dashboard.

### WP6: verification and closeout

- Reproduce from the hash lock in a clean Python 3.12 environment.
- Add parity tests proving the same candidate/risk core is used by historical and simulated runtime adapters.
- Update implementation matrix, risks, limitations, changelog and verification evidence.

## Planned code boundaries

```text
src/hanalpha/simulation/events.py
src/hanalpha/simulation/orders.py
src/hanalpha/simulation/fills.py
src/hanalpha/simulation/portfolio.py
src/hanalpha/simulation/engine.py
src/hanalpha/experiments/models.py
src/hanalpha/experiments/registry.py
src/hanalpha/metrics/portfolio.py
tests/simulation/
tests/experiments/
tests/parity/
```

Names require ADR/plan updates if responsibilities move; strategy logic must not be duplicated inside adapters.

## Exit gates

- Conservation/property tests pass across long sequences, partial fills and corporate actions.
- No event can observe a record with `available_at > as_of` or fill before eligibility.
- Multi-symbol/strategy cash and exposure reservations cannot oversubscribe the portfolio.
- Same experiment inputs reproduce event, equity-curve and metric hashes.
- Cost scenarios and all failures remain auditable; failed runs cannot be promoted.
- M0 capability and M1 PIT suites remain green.

## Stop conditions and explicit defers

- Stop before real provider/data purchase, LLM call, IBKR connection or order action.
- Stop if M2 would require weakening M0 capability boundaries or bypassing M1 `AsOfRepository`.
- Preregistered real-data strategy evaluation, multiple-testing correction and factor attribution are M3.
- Durable single-writer/outbox/reconciliation and Broker recovery are later execution milestones.

## Completion evidence

Implemented on 2026-07-18:

- published-snapshot PIT cursor with revision-aware, aware-`as_of` frames;
- deterministic order state machine, next-eligible-bar fill model, partial fills,
  cost scenarios, limit/stop/gap/halt/volume rules and expiry release;
- Decimal cash/lot ledger with atomic shared-cash/gross/symbol/position/risk
  reservations, FIFO PnL, commissions, split/dividend/delisting events and
  conservation checks;
- shared decision identity and parity harness for later shadow/paper adapters;
- canonical experiment manifests, append-only state history, Strategy Cemetery,
  counterfactual links, immutable artifact hashes and deterministic JSON/HTML bundles;
- end-to-end local experiment runner that records both completion and failure;
- V0.1 next-bar-equity and gap-stop regressions corrected;
- CI aligned to the Python 3.12 hash lock and full local verification contract.

Verification passed in both the project environment and a newly created Python
3.12.13 environment installed from `requirements-dev.lock --require-hashes`:

- Ruff and strict mypy: PASS (72 source files);
- pytest: PASS (110 tests, one upstream deprecation warning);
- branch coverage: 80.14% (70% required);
- package build, doctor, three-cycle demo, 400-bar baseline backtest and
  `pip check`: PASS.

M2 remains an engineering-validity result. Sector constraints need PIT sector
membership, real venue queue/depth semantics need licensed market data, and
statistical strategy selection belongs to M3. No vendor, LLM, IBKR or order call
was made.
