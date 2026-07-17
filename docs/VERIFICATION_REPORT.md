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

Canonical full verification is **BLOCKED, not passed**:

- `scripts/verify_all.sh` stopped at `ruff: command not found`;
- the available runtimes also lack the complete declared dev dependency set for full pytest, mypy and package build;
- dependencies were not downloaded because this M0 run was explicitly local/no-network.

Therefore the earlier V0.1 32-test/coverage evidence remains historical only. It must not be used as proof that the M0 diff is fully green. M1 remains gated on a fresh successful `scripts/verify_all.sh` run in a clean Python >=3.12 environment.
