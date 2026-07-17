# Han Alpha repository instructions

## Mission
Complete a production-quality, paper-trading-first research and execution platform. Profitability is a research objective, never an unverified claim. Safety, reproducibility, point-in-time correctness, and broker-state reconciliation take priority over UI polish.

## Start here
Read these files in order before changing code:
1. `CODEX_START_HERE.md`
2. `docs/codex/MASTER_TASK_ZH.md`
3. `docs/codex/ACCEPTANCE_CRITERIA.md`
4. `docs/exec-plans/active/001-complete-platform.md`
5. Relevant existing design docs under `docs/`

Treat the repository docs as the system of record. Update them when behavior changes.

## Non-negotiable safety rules
- Never enable unattended live trading.
- Live mode remains proposal-only and requires human approval.
- Never weaken risk limits, idempotency, stale-data checks, or reconciliation to make tests pass.
- LLMs may classify and critique evidence; they may not size positions, change risk policy, or call the broker.
- Broker state is authoritative for orders, fills, positions, cash, and buying power.
- Do not commit credentials, account identifiers, tokens, cookies, or private market data.
- Do not fabricate successful external integration. Mark credential-gated checks as BLOCKED with exact commands to run.

## Execution behavior
- Do not stop after writing a plan. Implement the plan in dependency order.
- Keep the active execution plan current after each milestone.
- Prefer small coherent commits with passing tests.
- Preserve backward-compatible synthetic mode so the repository runs without secrets.
- Use UTC internally and timezone-aware datetimes everywhere.
- All externally sourced observations must carry source, observed time, effective time, and ingestion time.

## Required checks
Run after every material change and before finishing:

```bash
./scripts/preflight.sh
./scripts/verify_all.sh
```

At minimum this includes formatting/lint, strict typing, unit/integration/adversarial tests, coverage threshold, package build, CLI smoke tests, API smoke tests, frontend tests when present, and secret scanning.

## Completion standard
A task is not complete because code exists. It is complete only when:
- acceptance criteria are satisfied;
- tests demonstrate the behavior and failure modes;
- docs and runbooks match the implementation;
- no critical TODO/FIXME remains in the changed scope;
- the worktree is clean and changes are committed;
- the final report distinguishes VERIFIED, BLOCKED, and NOT IMPLEMENTED.
