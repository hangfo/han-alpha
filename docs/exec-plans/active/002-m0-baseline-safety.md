# M0 execution plan: baseline freeze and safety boundary

Status: CODE COMPLETE, VERIFICATION BLOCKED
Owner: Codex
Updated: 2026-07-18

## Scope

- Freeze V0.1 provenance, Git tree and source artifact hash.
- Define capability-based operating modes; remove any representable `live_auto` path.
- Make paper automatic submission and every API mutation default-off.
- Require Broker write capability at Broker method boundaries.
- Introduce aware `DecisionClock` at orchestration and agent decisions.
- Correct simulated limit-price semantics.
- Add structural/adversarial tests and update M0 governance documents.

## Explicit non-scope

- No market-data, LLM or broker network call.
- No IBKR connection or order action.
- No PIT implementation, strategy expansion, portfolio backtester or dashboard.
- No claim that V0.1 alpha, production readiness or the full platform is complete.

## Checkpoints

- Baseline commit: `0a69b6892c1e6da184ce0fe6d376557ed8a0de82`.
- Safety implementation commit: `43b77f4`.
- ADR: `docs/adr/0001-capability-based-operating-modes.md`.
- Risk register: `docs/RISK_REGISTER.md`.

## Verification evidence

Passed locally without network:

- `scripts/preflight.sh` under bundled Python 3.12.13;
- `python3 -m compileall -q src tests`;
- `git diff --check`;
- offline capability/clock/limit smoke using temporary import-only stubs;
- offline full synthetic cycle smoke in `paper_manual`, confirming no Broker capability.

Blocked, not failed:

- `scripts/verify_all.sh` stops immediately because `ruff` is not installed in the available Python runtime;
- the runtime also lacks the complete project/dev dependency set required for canonical pytest, mypy and build;
- no dependency was downloaded because M0 explicitly forbids network access.

## Remaining exit gate

M0 may be marked complete only after a clean Python >=3.12 environment runs:

```bash
./scripts/verify_all.sh
```

and ruff, mypy strict, full pytest/coverage, package build, doctor, demo and baseline backtest all pass. Until then, M1 implementation is NO-GO.
