# M0 execution plan: baseline freeze and safety boundary

Status: COMPLETE
Owner: Codex
Completed: 2026-07-18

## Scope completed

- Froze V0.1 provenance, Git tree and source artifact hash.
- Defined capability-based operating modes; no representable `live_auto` path exists.
- Made paper automatic submission and every API mutation default-off.
- Required Broker write capability at public and internal Broker write paths.
- Introduced aware `DecisionClock` at orchestration and agent decisions.
- Corrected simulated buy/sell limit-price semantics.
- Added structural/adversarial tests and updated M0 governance documents.
- Added a Python 3.12 marker, hash-locked dev requirements and reproducible bootstrap/build flow.

## Explicit non-scope preserved

- No market-data, LLM or broker call was made during M0 implementation or verification.
- No IBKR connection or order action occurred.
- No PIT implementation, strategy expansion, portfolio backtester or dashboard was added.
- No claim of alpha, production readiness or overall platform completion is made.

## Checkpoints

- Baseline commit: `0a69b6892c1e6da184ce0fe6d376557ed8a0de82`.
- Safety implementation commit: `43b77f4`.
- Initial M0 design/audit docs: `dc8f08f`.
- Reproducible verification and final hardening: `2b29dec`.
- ADR: `docs/adr/0001-capability-based-operating-modes.md`.
- Risk register: `docs/RISK_REGISTER.md`.

## Verification evidence

Passed in the project `.venv` and again in a newly created clean Python 3.12.13 environment installed with `--require-hashes`:

- `scripts/preflight.sh`;
- `ruff check src tests`;
- `mypy src` strict: 46 source files;
- pytest: 48 passed;
- branch-aware coverage: 72.02%, threshold 70%;
- sdist and wheel build with `--no-isolation`;
- CLI doctor;
- three-cycle synthetic `paper_manual` demo;
- 400-bar synthetic baseline backtest;
- `pip check` and repository secret scan.

One upstream Starlette/FastAPI TestClient deprecation warning remains. It does not change runtime behavior and is recorded as a dependency migration item rather than suppressed.

## Exit decision

M0 is complete. M1 is authorized only for the local fixture-driven PIT data kernel described in `docs/v2-plan/07_M0_CLOSEOUT_AND_M1_DECISION_ZH.md`. Real vendor calls, paid data, LLM calls, IBKR connections and order actions remain separately permission-gated.
