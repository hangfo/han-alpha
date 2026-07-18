# M3 execution plan: preregistered strategy evidence

Status: COMPLETE
Owner: Codex
Created: 2026-07-18

## Objective

Build a research process that preferentially rejects false strategies and emits
decision-grade, reproducible evidence. M3 may validate mechanics on frozen or
synthetic data but cannot claim real-data Alpha.

## WP0: research-truth hardening

- Separate knowledge-only revisions from tradable events.
- Add deterministic candidate identity and ordering.
- Add executable stop/target OCO protection for entry fills.
- Make the default CLI use replay/experiment artifacts; freeze the old verifier
  behind `legacy-backtest`.
- Add balanced monetary journals and adversarial invariants.

## WP1: immutable research contract

- Add `ResearchContext`, point-in-time history, feature hashes and typed events.
- Add preregistration with fixed windows, parameter ranges, success/failure
  thresholds, costs, universe and research budget.
- Preserve rejected candidates and counterfactual variants.

## WP2: interpretable baselines

- Cross-sectional medium-term momentum with skip period and liquidity controls.
- Slow trend/volatility overlay suitable for daily or 60-minute data.
- PEAD candidate requiring actual announcement availability and PIT expectations;
  missing evidence means no trade.

These are falsification baselines, not recommendations.

## WP3: statistical rejection framework

- Rolling walk-forward with purge and embargo.
- Time-weighted portfolio metrics, bootstrap confidence intervals, DSR and CSCV
  PBO with explicit minimum-sample failures.
- Multiple-testing correction, parameter perturbation, doubled-cost and delayed
  execution counterfactuals.
- Contribution/concentration checks by instrument and period.

## WP4: promotion governance

- Remove generic promotion transition.
- Require preregistration, OOS post-cost evidence, statistical/risk/robustness
  gates, reproducibility and independent approval.
- Exhausted search budget or any missing mandatory gate fails closed into review
  or the Strategy Cemetery.

## Exit gates

- Historical revisions and action revisions can never generate fills or duplicate
  cash/position effects.
- Candidate set permutation produces identical decisions, orders and event hash.
- Every filled long quantity has matching live stop protection; OCO cannot double exit.
- Default `hanalpha backtest` produces a registered deterministic result bundle.
- Walk-forward/purge/embargo boundary tests and statistical null tests pass.
- Direct `COMPLETED -> PROMOTED` is impossible.
- Full local and clean hash-locked verification passes at at least 85% branch coverage.

## Explicit blockers and defers

- Real PIT strategy conclusions are BLOCKED until vendor license, timestamp,
  universe, earnings-expectation and corporate-action lifecycle fields are reviewed.
- Full dividend entitlement/payment semantics require expanded source fields.
- LLM evidence, durable execution, IBKR Paper and Dashboard remain M4–M7.
- No vendor, LLM, Broker or order call is made in M3 local implementation.

## Completion evidence

- Revision bars and action revisions are knowledge-only; matching rejects revisions and pre-order market time.
- Content-addressed candidates, executable partial-fill brackets, conservative OCO ordering and balanced journals have adversarial tests.
- `ResearchContext`, three interpretable abstention-capable baselines, preregistration, bounded counterfactual suites, rejected-decision outcomes, walk-forward, DSR, CSCV PBO, bootstrap and Holm correction are implemented.
- Direct promotion is impossible; the dedicated gate requires complete statistical, risk, robustness, reproducibility, artifact and independent-approval evidence.
- `hanalpha backtest` now registers an idempotent deterministic M3 experiment bundle; `legacy-backtest` is explicitly frozen.
- Required local checks pass at more than 85% branch coverage. The live IBKR adapter is omitted from the local coverage denominator because its contract and observation belong to credential-gated M6, not because its safety boundary is relaxed.
