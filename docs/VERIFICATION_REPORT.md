# Verification report

Verification date: 2026-07-17

## Automated checks

- `ruff check src tests`: passed.
- `mypy src`: passed with strict mode; 43 source files checked.
- `pytest`: 32 passed; one upstream FastAPI/Starlette TestClient deprecation warning.
- Branch-aware coverage: 72% overall.
- `python -m compileall -q src`: passed.
- Editable package install: passed on Python 3.13; project minimum is Python 3.12.

## Runtime smoke tests

- `hanalpha doctor`: configuration validated.
- `hanalpha demo --cycles 10`: completed, produced signals, orders, positions, NLV updates, and protection events.
- `hanalpha backtest --symbol NVDA --bars 1000`: completed.
- `hanalpha worker --cycles 2`: completed.
- Uvicorn actual process startup: passed.
- `GET /health`: returned healthy.
- `POST /cycles/run`: completed a full cycle.

## Adversarial coverage

Validated rejection or fail-closed behavior for:

- impossible OHLC;
- crossed quotes;
- naive timestamps;
- stale quotes;
- broker disconnect;
- duplicate idempotency;
- duplicate same-symbol exposure;
- kill switch;
- invalid live configuration;
- LLM position sizing;
- prompt injection;
- malformed LLM output;
- fabricated evidence IDs;
- future/unavailable catalyst;
- missing quote during flatten;
- disabled paper auto-submit;
- protective stop exit.

## Not validated

- Real Polygon subscription responses.
- Real SEC/FRED production ingestion volume.
- Authenticated IBKR Paper connection and exchange callbacks.
- Live orders.
- Strategy alpha on real point-in-time data.

These omissions are explicit blockers for any claim of production readiness or profitability.

## Codex handoff verification - 2026-07-18

Added a repository-native Codex execution package:

- root `AGENTS.md` map and mandatory safety instructions;
- `CODEX_START_HERE.md` entrypoint;
- master implementation, resume, and independent audit prompts;
- mechanical acceptance criteria and adversarial test matrix;
- active execution plan with milestone and evidence logs;
- one-command local bootstrap;
- preflight and full verification scripts;
- machine-readable `codex_task.yaml`.

Verified after the handoff changes:

```text
preflight: PASS
ruff: PASS
mypy strict: PASS (43 source files)
pytest: PASS (32 tests)
branch coverage: 71.63% baseline
package build: PASS
CLI doctor: PASS
synthetic demo: PASS
baseline backtest smoke: PASS
```

The 85% coverage target applies to the completed platform and is deliberately recorded as an acceptance criterion, not misrepresented as already achieved by V0.1.

## M0 verification - 2026-07-18

Baseline freeze:

- V0.1 commit: `0a69b6892c1e6da184ce0fe6d376557ed8a0de82`;
- V0.1 tree: `b7d7d35fdf53f701f856513c05bf5450be7e2640`;
- M0 safety implementation: `43b77f4`.

Passed without network, vendor, LLM or broker access:

- `scripts/preflight.sh` with bundled Python 3.12.13: PASS;
- `python3 -m compileall -q src tests`: PASS;
- `git diff --check`: PASS;
- direct offline M0 safety smoke: PASS for mode/capability denial, missing token denial, nonexistent `live_auto`, naive clock rejection and buy/sell limit semantics;
- direct offline full synthetic `paper_manual` cycle: PASS with Broker write capability false.

The initial missing-toolchain blocker was resolved after explicit authorization. Final canonical verification passed twice: once in the project `.venv`, then in a newly created clean Python 3.12.13 environment installed from `requirements-dev.lock` with `--require-hashes`.

Final results:

- `ruff check src tests`: PASS;
- `mypy src` strict: PASS, 46 source files;
- pytest: PASS, 48 tests;
- branch-aware coverage: 72.02%, required threshold 70%;
- sdist/wheel build with no isolation: PASS;
- CLI doctor: PASS, `paper_manual`, all write capabilities false;
- synthetic demo, three cycles: PASS;
- synthetic 400-bar baseline backtest: PASS;
- `pip check`: PASS;
- clean hash-locked environment reproduction: PASS.

The test run emits one upstream Starlette/FastAPI TestClient deprecation warning. It is non-fatal, not suppressed, and does not alter the M0 result. The earlier V0.1 32-test evidence remains historical; the 48-test result is the M0 baseline.

M0 is VERIFIED. This authorizes local M1 PIT implementation only; it does not authorize vendor, LLM or broker access and does not establish alpha or production readiness.
