# Active execution plan: complete Han Alpha platform

Status: ACTIVE; M0 verification gate open
Owner: Codex
Last updated: 2026-07-18

## Goal

Satisfy every item in `docs/codex/ACCEPTANCE_CRITERIA.md` while preserving all safety invariants.

## Baseline

- Existing V0.1 has 32 passing tests.
- Ruff and mypy strict previously passed.
- Synthetic CLI/API demo works.
- IBKR adapter exists but has not been validated against the user's local Paper session.
- No frontend currently exists.

Codex must rerun and replace these statements with current command evidence.

## Milestones

- [ ] M0 baseline and safety code implemented; full toolchain verification blocked
- [ ] M1 point-in-time data and persistent contracts
- [ ] M2 portfolio backtest and experiment registry
- [ ] M3 productionized IBKR Paper recovery/reconciliation
- [ ] M4 evidence agents, caching, budgets, ablation
- [ ] M5 React Dashboard and authenticated controls
- [ ] M6 observability, alerts, deployment, backup/restore
- [ ] M7 full adversarial verification and release

## Decision log

Record important decisions here with date, alternatives, and consequences. Do not silently change risk or execution semantics.

- 2026-07-18: Accepted ADR 0001. Operating authority is capability-based; `live_auto` does not exist; API and paper auto writes are default-off.
- 2026-07-18: M1 is NO-GO until the M0 canonical verification command passes. After that, platform work starts with a local fixture-driven PIT data vertical slice, not UI or new agents.

## Verification log

For each milestone record:

- commit SHA;
- commands run;
- result summary;
- coverage;
- remaining BLOCKED external checks;
- newly discovered risks.

M0 evidence and blocker details are maintained in `002-m0-baseline-safety.md` and `docs/VERIFICATION_REPORT.md`.
