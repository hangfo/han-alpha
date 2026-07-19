# Active execution plan: complete Han Alpha platform

Status: ACTIVE; M5 hardened, M6 read-only kernel complete locally and Paper burn-in blocked
Owner: Codex
Last updated: 2026-07-19

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

- [x] M0 baseline freeze, capability safety and reproducible verification
- [x] M1 point-in-time data and persistent contracts
- [x] M2 deterministic portfolio replay and experiment registry
- [x] M3 preregistered strategy baselines and statistical evidence
- [x] M4 LLM Evidence Service, caching, budgets and ablation
- [x] M5 durable execution control plane and Fake Broker
- [ ] M6 IBKR Paper integration and observation
- [ ] M7 Ops Dashboard, observability and recovery operations
- [ ] M8 Live Proposal independent review

## Decision log

Record important decisions here with date, alternatives, and consequences. Do not silently change risk or execution semantics.

- 2026-07-18: Accepted ADR 0001. Operating authority is capability-based; `live_auto` does not exist; API and paper auto writes are default-off.
- 2026-07-18: M0 canonical verification passed twice, including a clean hash-locked Python 3.12 environment. M1 is GO for a local fixture-driven PIT data vertical slice, not UI or new agents.
- 2026-07-18: M1 frozen-fixture PIT kernel passed local and clean hash-locked verification. Real vendor data remains gated; M2 is a local portfolio replay/experiment milestone.
- 2026-07-18: M2 deterministic portfolio replay and experiment lifecycle passed 110 tests at 80.14% branch coverage in local and clean hash-locked Python 3.12.13 environments. M3 may design preregistered strategy evidence, but real data acquisition remains separately gated.
- 2026-07-18: M3 closed the replay truth gaps, added preregistered interpretable baselines and fail-closed statistical/promotion governance. Local verification passed 133 tests at 85.48% branch coverage; the live IBKR adapter is explicitly excluded because it is credential-gated M6 scope. M4 may add evidence-only LLM assistance without changing sizing, risk or Broker authority.
- 2026-07-18: M3 authority amendment removed caller-reported promotion and descriptive counterfactuals, persisted atomic research allocations, and adopted adverse same-bar protection. M4 added a citation-bound, expiring, cached and budgeted Evidence Service with no Broker/sizing/risk authority. No real Provider call or real-data Alpha evaluation was performed. M5 is the next local milestone.
- 2026-07-19: M4 audit amendments fixed the raw Responses boundary, backend citation resolution, review binding, ablation arithmetic, cache/audit scope and no-trade promotion. M5 added the durable capsule/reservation/outbox/inbox/single-writer/Fake-Broker/reconciliation control plane and removed direct new-exposure Broker submission from the runtime. No real Provider or Broker call was made. M6 is authorized only for explicit IBKR Paper integration and observation.
- 2026-07-19: M5 review hardening unified durable freeze authority, closed fencing/Unknown/cash/protection/account-read gaps and removed in-memory pending orders. M6-A through M6-E now have a local read-only fact-tape, completeness-certificate, reducer and shadow-gap kernel. Real Paper burn-in and M6-F remain blocked; no Broker write was made.

## Verification log

For each milestone record:

- commit SHA;
- commands run;
- result summary;
- coverage;
- remaining BLOCKED external checks;
- newly discovered risks.

M0 evidence is maintained in `../completed/002-m0-baseline-safety.md` and `docs/VERIFICATION_REPORT.md`.

M1 evidence is maintained in `../completed/003-m1-pit-data-kernel.md`.

M2 evidence is maintained in `../completed/004-m2-portfolio-backtest.md`.

M3 evidence is maintained in `../completed/005-m3-strategy-evidence.md`; its
authority amendment is recorded in ADR 0005.

M4 evidence is maintained in `../completed/006-m4-evidence-service.md`. The next
audit amendment is in `../../v2-plan/12_M4_M5_AUDIT_INTEGRATION_DECISIONS_ZH.md`.

M5 evidence is maintained in `../completed/007-m5-durable-execution.md`. The next
bounded milestone is tracked in `008-m6-ibkr-observation.md`; real connectivity,
callback burn-in, durable cancel and the first Paper Manual order remain blocked.
