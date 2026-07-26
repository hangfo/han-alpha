# M7-B.1 execution plan: authority normalization and admission

Status: LOCAL COMPLETE; real Paper burn-in and Canary write path BLOCKED

Last updated: 2026-07-26

## Locally delivered

- Stable Scope Policy separated from per-session Observation Window.
- Canonical account/order/position/execution/commission/protection state builders.
- Exact economic component hashes plus bounded valuation-equivalence receipts.
- Genuine two-cycle Observer consensus test with different sessions and request IDs.
- Completed Orders `apiOnly`, manual visibility and retained-date scope evidence.
- Accepted/written/dropped Fact counters in the completeness certificate and Ops.
- Versioned, actor-attributed, replaceable and atomically consumed Approval Arms.
- Realtime/provider-age/future-clock/spread/phase/venue/currency Quote admission.
- `runtime_control` separated from the full immutable Paper Canary safety case.
- Source-backed runtime status in `/ops/overview`, corrected Unknown age, stable
  session counters, discrepancy supersede and current backup generation evidence.
- Idempotent Generation restore that never deletes the current generation.

## Verified local evidence

- `./scripts/preflight.sh`: PASS in Python 3.12.13 virtual environment.
- `./scripts/verify_all.sh`: PASS.
- Python: 205 tests, 85.14% branch-aware total coverage.
- Ruff and strict mypy: PASS.
- Frontend: 2 Vitest tests, TypeScript, lint and production build PASS.
- Copied pre-M7-B.1 control-store migration and SQLite integrity check: PASS.

## External BLOCKED gates

- Official `ibapi` installation and authenticated Paper TWS/IB Gateway.
- 30 complete independent observations with a separate consecutive-stability goal.
- Manual TWS and other-client order visibility for `apiOnly=True/False`.
- Golden Tape corpus, process/TWS restart and nightly reset evidence.
- Licensed realtime quotes plus verified exchange calendar/session.
- Durable real IBKR writer, real cancel and persistent bracket recovery.
- One-use, quantity/notional-bounded Canary Permit.
- Survivor-bias-free real PIT datasets and forward Alpha evidence.

## Next dependency order

1. Run zero-write Paper Observer burn-in on a static account.
2. Build sanitized Golden Tapes from manual TWS events and failure/reset cases.
3. In parallel, acquire and qualify real PIT data for the three preregistered M3
   baselines: slow trend, cross-sectional momentum/breakout and PEAD.
4. Freeze architecture. Only fix safety defects revealed by the evidence.
5. After all external safety-case checks pass, design the durable writer, real
   cancel/bracket recovery and one-use Canary Permit. Do not send an order earlier.
