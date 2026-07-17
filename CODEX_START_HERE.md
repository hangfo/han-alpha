# Codex start here

This repository already contains a runnable V0.1 core. Your task is to turn it into a complete paper-trading platform without discarding the existing safety architecture.

## Read first

- `AGENTS.md`
- `docs/codex/MASTER_TASK_ZH.md`
- `docs/codex/ACCEPTANCE_CRITERIA.md`
- `docs/codex/EXECUTION_PLAN.md`
- `docs/codex/TEST_MATRIX.md`
- `docs/exec-plans/active/001-complete-platform.md`

## Baseline commands

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
./scripts/preflight.sh
./scripts/verify_all.sh
```

## Operating modes that must remain distinct

1. `synthetic`: no credentials, deterministic local demo.
2. `historical`: real cached data, no broker writes.
3. `shadow`: live data and decisions, no broker writes.
4. `paper_manual`: IBKR Paper proposals require approval.
5. `paper_auto`: IBKR Paper may auto-submit within paper risk limits.
6. `live_proposal`: live account read and proposal only; no automatic transmission.

There is no unattended `live_auto` mode in scope.

## Definition of done

Do not claim completion until `docs/codex/ACCEPTANCE_CRITERIA.md` is checked line by line and `docs/VERIFICATION_REPORT.md` contains evidence for every implemented claim.
