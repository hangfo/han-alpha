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

## M1 local PIT verification - 2026-07-18

Implemented without vendor, LLM, IBKR or order access:

- immutable content-addressed raw objects and source-revision conflict rejection;
- SQLite staged/published manifest, lineage and quality catalog;
- canonical Parquet snapshots written/read with DuckDB 1.5.4;
- stable instrument IDs, half-open ticker/listing intervals, delisting and symbol reuse;
- centralized typed `AsOfRepository` predicates for snapshot, availability, validity and visible revision;
- raw-preserving split/dividend adjustment policies with snapshot and policy trace;
- DST-safe exchange wall-time conversion plus deterministic frozen-fixture XNYS phase checks;
- manifest-classified valid/invalid fixture files and deterministic snapshot/feature replay;
- CLI fixture ingest, quality inspection and snapshot inspection.

Canonical local result:

- `scripts/preflight.sh`: PASS;
- `scripts/verify_all.sh`: PASS;
- Ruff: PASS;
- mypy strict: PASS, 58 source files;
- pytest: PASS, 76 tests;
- branch-aware coverage: 77.41%, required threshold 70%;
- sdist/wheel, doctor, three-cycle demo and 400-bar synthetic backtest: PASS;
- repeated fixture ingest into the same state: PASS after an idempotency regression was found and fixed;
- clean Python 3.12.13 environment installed only with `--require-hashes`: PASS after explicitly locking the editable-build dependency.

Frozen fixture v1 evidence:

- snapshot ID: `1741368ff587ab3b09a8c44c5353cf2a4c50a9aecbdc531457dbb93f83eafc76`;
- feature hash: `56ede5afa4f3336613a6bdaf0fb2ab7432a0bc9029110219e9d2baa91e9df88a`;
- quality digest: `5af0fe7f45a043afed563c06538174a5268fa86a5f7c37e5c207f39275f34321`;
- records: 20; publication state: `published`; issues: 0.

M1 is VERIFIED for the repository-owned synthetic fixture boundary. It does not prove production calendar completeness, vendor PIT correctness, strategy profitability, portfolio replay parity or broker readiness. M2 may start locally; real data remains separately gated.

## M2 deterministic portfolio replay verification - 2026-07-18

Implemented without vendor, LLM, IBKR or order access:

- revision-aware `PITEventCursor` over the published M1 `AsOfRepository`;
- canonical decision hashes and a parity harness shared across replaceable adapters;
- explicit order transitions and next-eligible-bar market/limit/stop fills with
  partial quantity, participation, cost scenarios, halt, gap and expiry behavior;
- Decimal shared-cash ledger, FIFO lots, commissions, atomic cash/gross/symbol/
  position/per-trade/aggregate-risk reservations and split/dividend/delisting events;
- canonical experiment manifests, append-only legal state transitions, Strategy
  Cemetery, counterfactual links, immutable artifact digests and deterministic
  JSON/HTML results;
- end-to-end local experiment runner for success and failure lifecycle closure;
- V0.1 next-bar-equity and gap-stop semantic regressions fixed;
- Python 3.12 hash-locked CI aligned with the full local verification contract.

Canonical result, repeated in the project environment and a newly created clean
Python 3.12.13 environment installed from `requirements-dev.lock --require-hashes`:

- `scripts/preflight.sh`: PASS;
- `scripts/verify_all.sh`: PASS;
- Ruff: PASS;
- mypy strict: PASS, 72 source files;
- pytest: PASS, 110 tests;
- branch-aware coverage: 80.14%, required threshold 70%;
- sdist/wheel, doctor, three-cycle demo and 400-bar synthetic baseline backtest: PASS;
- `pip check` and `git diff --check`: PASS.

The one warning is the already documented upstream Starlette/FastAPI TestClient
deprecation. M2 is VERIFIED only as a local deterministic replay and experiment
mechanics boundary. It does not validate real vendor timestamps, queue/depth or
auction behavior, sector PIT data, strategy alpha, IBKR Paper or live execution.
M3 may proceed to preregistration and strategy-evidence design; any real data
acquisition remains separately permission-gated.

## M3 preregistered strategy evidence verification - 2026-07-18

Implemented locally without vendor, LLM, IBKR or order access:

- separate knowledge-only revisions from tradable bars/actions, including explicit corporate-action phases;
- stable content-addressed candidates, next-event matching and executable partial-fill stop/target OCO protection;
- balanced debit/credit monetary journals with FIFO lots retained as an operational view;
- immutable point-in-time research contexts and momentum, slow-trend and PIT-expectation-gated PEAD baselines;
- frozen research windows, parameter ranges, success criteria and trial budgets;
- purge/embargo walk-forward, time-weighted metrics, bootstrap intervals, Deflated Sharpe, CSCV PBO and Holm correction;
- budgeted doubled-cost, delayed-execution and parameter-perturbation counterfactual manifests plus rejected-decision outcomes;
- dedicated fail-closed promotion review requiring complete statistical, risk, robustness, reproducibility, artifact and independent-human evidence;
- idempotent `hanalpha backtest` registration and immutable artifacts; the old verifier is explicitly `legacy-backtest`.

Canonical local result:

- `scripts/preflight.sh`: PASS on Python 3.12.13;
- `scripts/verify_all.sh`: PASS;
- Ruff: PASS;
- mypy strict: PASS, 82 source files;
- pytest: PASS, 133 tests;
- branch-aware coverage: 85.48%, required threshold 85%;
- sdist/wheel build, doctor, three-cycle demo and 400-bar registered backtest: PASS;
- `git diff --check`: PASS.

The local coverage denominator explicitly omits `execution/ibkr.py`, whose real callback/reconciliation behavior is credential-gated M6 scope. Its capability and no-live-auto boundaries remain tested and unchanged. The existing upstream Starlette/FastAPI TestClient deprecation warning remains non-fatal.

M3 is VERIFIED for local research and replay mechanics. Real Alpha evidence remains BLOCKED on licensed point-in-time data, timestamp and universe review, PIT earnings expectations, and a complete corporate-action entitlement/payment contract. Synthetic annualized metrics are not decision evidence. M4 may add evidence-only LLM assistance; LLMs still cannot size, change risk, promote experiments, or access a Broker.
