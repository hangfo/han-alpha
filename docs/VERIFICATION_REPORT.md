# Verification report

## Issue #3 secure onboarding closure - 2026-07-26

Baseline: `10f5fd3b029634d35d9a2b02ea75d2e53e834dda`.

Detailed review decisions:
`docs/v2-plan/20_E1B_R1B_ISSUE3_REVIEW_AND_ONBOARDING_ZH.md`.

VERIFIED:

- macOS Keychain is the preferred SecretProvider; secret writes use stdin,
  values never enter argv/output, `.env` migration is explicit and scrub is
  optional.
- `local-onboard ibkr` produces redacted, structured readiness and may launch an
  already installed application, but never accepts a license, logs in or handles
  2FA for the user. It can poll the configured socket for at most five minutes
  and, after explicit Read-Only attestation, runs and registers Preflight.
- `e1 run` resumes independent API/ALL matrices, counts only verified eligible
  in-scope Sessions and captures at most one Session per explicit invocation.
- `r1 run` uses fixed bounded source slates, makes no network request in dry-run
  or missing-secret states, and cannot convert successful access into data rights.
- Probe evidence independently binds literal HTTP bytes, safe headers and
  normalized JSON. Strict authority documents declare their own type/schema/
  effective window, and Registry authority is stored in portable
  content-addressed objects.
- Runner failure reports are self-hashed after final status mutation. CLI error
  paths disclose exception class only and redact known values, query keys,
  authorization headers, account fields and tracebacks.
- `./scripts/preflight.sh`: PASS in Python 3.12.13.
- `./scripts/verify_all.sh`: PASS; 255 Python tests, 85.23% branch-aware
  coverage, Ruff, strict mypy over 115 source files, sdist/wheel,
  CLI/API/synthetic/backtest smoke checks, 2 Vitest tests, frontend
  lint/typecheck and Vite production build.
- `npm audit`: zero vulnerabilities.

BLOCKED:

- Local IBKR onboarding: no installed TWS/Gateway, accepted official TWS API,
  importable `ibapi`, listening Paper socket or Keychain Paper account.
- R1 execution: no local SEC identity, FRED key or Massive key; written rights
  and independent Reviewer Receipts remain external even after transport access.
- GitHub #1 and #2 therefore remain external acceptance work. Issue #3 local
  implementation is complete but its human/external checklist cannot be closed.

NOT IMPLEMENTED:

- Automatic license acceptance, account creation, GUI login/2FA or credential
  acquisition; these are intentionally user-controlled.
- Evidence Firewall/Research Sandbox/Alpha Confidence runtime. These are R2
  research-governance candidates after E1/R1 qualification, not E1/R1 defects.
- E2/E3 Paper Canary, production vendor adapters or any live order path.

## E1-B/R1-B executable acceptance tooling - 2026-07-26

Baseline: `0b9b9879071b928e6524917263e90904aaaf962f`.

Detailed review decisions:
`docs/v2-plan/19_E1B_R1B_WEB_REVIEW_AND_REALITY_GAPS_ZH.md`.

VERIFIED:

- The IBKR observation process uses an observer-only client whose order placement,
  cancellation, global cancellation and option exercise methods fail structurally.
- Preflight distinguishes TWS Read-Only account/position observation from the
  order-visible zero-write phase. Preflights and capture sessions are registered
  automatically as typed, hash-resolved evidence.
- Golden Tape evaluation now runs six deterministic metamorphic transforms across
  fourteen required Broker scenarios and emits a machine-readable Callback Truth
  Map. Mixed Completed Orders scopes fail closed.
- Bounded SEC, Massive and FRED/ALFRED probes preserve immutable raw bytes and
  redacted provenance. Typed audits separate access, timestamp, revision,
  symbology and survivorship claims.
- Qualification artifacts must explicitly declare the exact
  `qualifies_checks` claim they satisfy; matching only the broad artifact type is
  insufficient.
- Ops and React expose source-backed Artifact Registry and Corpus status rather
  than placeholder counters.
- Local preflights remained fail-closed: the official IBKR API, Paper account,
  Paper socket, SEC identity and vendor credentials are absent. Probe CLI errors
  are sanitized and do not expose request URLs, keys or tracebacks.
- `./scripts/preflight.sh`: PASS in Python 3.12.13.
- `./scripts/verify_all.sh`: PASS; 237 Python tests, 85.00% branch-aware
  coverage, Ruff, strict mypy over 110 source files, sdist/wheel,
  CLI/API/synthetic/backtest smoke checks, 2 Vitest tests, frontend
  lint/typecheck and Vite production build.
- `npm audit`: zero vulnerabilities.

BLOCKED:

- GitHub #1 external acceptance: IBKR license/TWS installation, authenticated
  Paper login, API and ALL scope callback captures, reset/nightly scenarios,
  Golden Tape corpus and independent Safety Case reviews.
- GitHub #2 external acceptance: real SEC identity, Massive/FRED credentials,
  written vendor rights, bounded live samples and independent qualification
  reviews.
- Any real PIT OOS, post-cost capacity, forward performance or profitability
  claim.

NOT IMPLEMENTED:

- E2 Canary Permit and E3 first human-approved Paper order.
- Production vendor ingestion or R2 strategy promotion.
- Unattended Paper or live trading; no `live_auto` state exists.

## E1-A/R1-A evidence-authority closure - 2026-07-26

Baseline: `778fac41b95efde6e0a8551cd455732754e58b54`.

Detailed review decisions:
`docs/v2-plan/18_E1_R1_REVIEW_AND_EVIDENCE_AUTHORITY_ZH.md`.

VERIFIED:

- Burn-in Session v2 re-verifies its canonical identity, exact file set and
  hashes, Certificate bindings, single-session Tape and observation directory.
- Burn-in capture is not acceptance. A separate Corpus evaluator requires
  homogeneous bindings, eligible sessions, stable consecutive consensus and
  Scope-specific scenario coverage; BLOCKED exits nonzero.
- The immutable typed Artifact Registry resolves every Safety Case and PIT
  evidence hash back to a present, hash-valid, schema-valid, policy-passing file.
- Safety Case trust uses two independent offline Ed25519 reviews (Risk and
  Execution) bound to the exact case hash. Runtime contains public keys only.
- Source qualification requires type-correct registered evidence, bounded
  expiry and an independently signed review receipt. Caller-provided
  `VERIFIED` text cannot authorize research or promotion.
- Vendor preflight distinguishes credential presence from access readiness,
  redacts secret values and rejects unidentified or placeholder SEC User-Agents.
- Local zero-network preflights remained fail-closed: IBKR API/account/socket
  readiness was false and all three vendor access-readiness sets were empty.
  No Broker, vendor or LLM request was attempted.
- `./scripts/preflight.sh`: PASS in the repository Python 3.12.13 environment.
- `./scripts/verify_all.sh`: PASS; 223 Python tests, 85.09% branch-aware
  coverage, Ruff, strict mypy over 107 source files, sdist/wheel and
  CLI/API/synthetic/backtest smoke checks, 2 Vitest tests, frontend
  lint/typecheck and Vite production build.
- `npm audit`: zero vulnerabilities. `git diff --check`: PASS.

BLOCKED:

- E1-B: authenticated IBKR Paper preflight, API/all Burn-in matrix, resets,
  Golden Tapes, cancel/Bracket/account/calendar proof and issued Safety Case.
- R1-B: written vendor rights, entitlement probes, bounded raw samples,
  timestamp/revision/symbology/survivorship audits and approved profiles.
- R2: real PIT out-of-sample, friction, capacity and forward/shadow evidence.

NOT IMPLEMENTED:

- E2 one-use Canary Permit and E3 first human-approved Paper order.
- Production vendor ingestion and any real-data strategy promotion.
- Unattended Paper or live trading; no `live_auto` state exists.

## E1/R1 local evidence entry (superseded authority design) - 2026-07-26

Baseline: `99053d998a6fdff10b4b996c475ffed8dcaa0289`.

Detailed review decisions:
`docs/v2-plan/17_M7B1_REVIEW_AND_E1_R1_DECISIONS_ZH.md`.

VERIFIED:

- Completed Orders `api/all` scopes are explicit and map to distinct IBKR requests,
  Scope Policies and burn-in counters.
- Redacted zero-write Broker preflight, immutable per-session tape/certificate/manifest
  export, hash verification and idempotent persistence are implemented.
- Arm freshness is bounded by every upstream authority and Claim revalidates the
  current Authority plus the shared quote-admission policy.
- Safety Cases require canonical identity, active validity, non-revocation, current
  Scope, complete artifact hashes and a trusted HMAC signature; persisted booleans
  cannot make a case pass.
- Readiness layers require explicit component Heartbeat sets, and current-Scope
  stability is separated from all-Scope audit history.
- Price, filing/event and macro source qualification fails closed on licensing,
  PIT/revision/time semantics, symbology, survivorship and intended-use evidence.
- Local environment probes were redacted and zero-write: official `ibapi`, Paper
  ports, Paper account and vendor credentials were absent; no Broker or vendor
  request was attempted.
- `./scripts/preflight.sh`: PASS under Python 3.12.13.
- `./scripts/verify_all.sh`: PASS; 215 Python tests, 85.04% branch-aware coverage,
  Ruff, strict mypy over 106 source files, package/CLI/API/synthetic/backtest smoke,
  2 Vitest tests, TypeScript/lint/Vite production build and zero npm vulnerabilities.
- Real-browser QA against isolated FastAPI: the Scope and Canary reason graph
  rendered from `/ops/overview` (200), the DOM had zero buttons, links or forms,
  viewport overflow was absent and the console had no warning/error. The optional
  unconfigured `favicon.ico` returned 404 and has no application effect.
- `git diff --check`: PASS.

BLOCKED:

- Official authenticated IBKR Paper preflight, dual-Scope burn-in, resets, Golden
  Tapes, callback truth map, real cancel/Bracket behavior and Safety Case issuance.
- Written vendor retention/backtest rights, bounded raw samples and QUALIFIED
  Massive/SEC/ALFRED source profiles.
- Any real-data OOS alpha, capacity, profitability or production-readiness claim.

NOT IMPLEMENTED:

- Durable IBKR writer, Permit issuance/atomic consumption and first Paper Canary;
  these remain intentionally gated behind E1 and E2.
- Production vendor adapters and R2 strategy optimization; qualification must pass
  before either begins.
- Unattended Paper or live trading; no `live_auto` state exists.

## M7-B.1 authority normalization and admission - 2026-07-26

Baseline: `ba85691581a3729dbfdaef97c6a5072f0f138b62`.

Detailed review decisions:
`docs/v2-plan/16_M7B_REVIEW_AND_M7B1_DECISIONS_ZH.md`.

VERIFIED:

- Observation Window, Scope Policy and Canonical Broker State are separate hashes.
- Two complete Observer cycles with distinct Session/Request IDs, certificates and watermarks produce one stable policy/state and reach two-vote consensus.
- Cash/order/position/execution/commission/protection remain exact; bounded NetLiquidation/BuyingPower drift produces an explicit non-causal equivalence proof.
- Approval Arms are versioned, actor-attributed, replaceable after expiry and consumed atomically with the claimed outbox command; legacy schema migration preserves rows.
- Quote admission rejects delayed, stale-provider, future-clock, wide-spread, unverified-venue and currency-mismatched evidence.
- Runtime Control is source-backed; Paper Canary cannot pass without an immutable external safety case and realtime Quote Authority.
- `./scripts/preflight.sh`: PASS under repository Python 3.12.13 environment.
- `./scripts/verify_all.sh`: PASS; 205 Python tests, 85.14% branch-aware coverage, Ruff, strict mypy, package/CLI/API/synthetic/backtest smoke, 2 Vitest tests, TypeScript/lint/Vite build and zero high npm vulnerabilities.
- A copied pre-M7-B.1 local control store migrated successfully and passed `PRAGMA integrity_check`.
- Chrome QA against an isolated real FastAPI instance: all six readiness layers, provider quote age, complete/stable/reset burn-in counters and the Canary admission reason graph rendered correctly; the DOM contained no buttons or links. All application requests returned 200. Console diagnostics were limited to unrelated installed wallet-extension injection warnings/errors.

BLOCKED:

- Official IBKR API and authenticated Paper TWS/Gateway burn-in.
- 30 observations, consecutive stability, Golden Tapes, reset, real cancel/bracket, Paper account/session proof and one-use Canary Permit.
- Real survivor-bias-free PIT data, forward evidence and any profitability claim.

NOT IMPLEMENTED:

- Durable real IBKR writer and Canary Permit issuance, intentionally gated after external zero-write acceptance.
- Browser mutation controls, intentionally outside the read-only Ops milestone.

## M7-A authority hardening and M7-B read-only operations - 2026-07-20

VERIFIED locally: non-replayable independent Snapshot voting; account/order/position/execution/commission/protection component hashes; complete-CONVERGED-only Authority promotion; system-generated persisted Quote Capsules and ID-only Arm; Bracket leg identity; Completed Orders facts; explicit execution scope; Broker occurred/received time separation; discrepancy lifecycle; layered readiness and expanded metrics; Authority/freshness/burn-in dashboard; cross-store manifest and atomic Generation Restore with interruption tests.

BLOCKED externally: official authenticated IBKR Paper callbacks, market-data entitlement and exchange-session authority, 30-session zero-write burn-in, TWS/process/nightly resets, Golden Tape corpus, durable real cancel/bracket recovery, one-use Canary Permit, production alert delivery, quiesced production restore drill, and real survivor-bias-free PIT Alpha evidence.

NOT IMPLEMENTED: browser mutation controls, unattended Paper/Live trading, durable IBKR write adapter, deployed Playwright/topology acceptance, or any claim of proven profitability.

Detailed review decisions: `docs/v2-plan/15_M7A_REVIEW_AND_M7B_DECISIONS_ZH.md`.

Canonical local verification: `preflight: OK`; Ruff and strict mypy PASS; 192 Python tests PASS at 85.07% branch coverage with two-decimal enforcement; package/CLI/API/synthetic/backtest smoke PASS; 2 Vitest tests PASS; TypeScript strict/lint and Vite production build PASS; `npm audit --audit-level=high` reports 0 vulnerabilities. Browser QA is recorded after the source-backed local API validation.

Browser QA: the in-app browser loaded the Vite dashboard against the real local FastAPI `/ops/overview`; the DOM exposed all five readiness layers, independent fact ages, Authority candidates, discrepancy lifecycle, backup and burn-in empty states. API calls returned 200, document width equaled viewport width, and browser logs contained no warning or error. Narrow/deployed topology Playwright remains NOT IMPLEMENTED.

## M6 audit hardening and M7-A read-only operations - 2026-07-20

VERIFIED locally: callback Queue single-writer and clean drain, transport-only Observer startup, semantic request barriers and visibility scope, native IBKR identity/reducer, M5 BrokerSnapshot adapter, two-snapshot consensus, Cash Bridge baseline epochs, two-stage approve/arm, fenced durable cancel, schedule-aware reality gaps, liveness/readiness, Ops metrics/dashboard unit tests, and hash/integrity checked backup-restore drill.

BLOCKED externally: official IBKR TWS API installation in the active environment, authenticated Paper account proof, real callback/reset Golden Tape, durable real cancel and Bracket behavior, first Paper Manual Canary, 20-day Shadow plus 20-day controlled Paper evidence, deployed alerting and production restore drill.

NOT IMPLEMENTED: unattended Paper/Live trading, M7 destructive-action UI, browser session/CSRF/double confirmation, deployed Playwright, or any claim of proven profitability.

Detailed review decisions: `docs/v2-plan/14_M6_REVIEW_AND_M7_DECISIONS_ZH.md`.

Canonical local verification: `preflight: OK`; Ruff and strict mypy PASS; 184 Python tests PASS at 85.11% branch coverage; package build and CLI/API smoke PASS; 2 Vitest component tests PASS; TypeScript strict/lint and Vite production build PASS; `npm audit --audit-level=high` reports 0 vulnerabilities.

Browser QA: local Vite dashboard against the real local FastAPI `/ops/overview` rendered the safety, Observer, reconciliation, execution-empty and evidence states correctly; browser console warning/error list was empty. No destructive control was present.

## M5 review hardening and M6 read-only kernel - 2026-07-19

Implemented and verified locally without Provider, vendor or Broker writes:

- persistent Freeze Tickets gate staging, approval and dispatch; startup opens a new reconciliation ticket;
- early Fake-Broker fence publication plus lease revalidation closes the pre-submit stale-writer window;
- strict post-claim Unknown absence, discovered-order binding and fact-identity event reduction;
- exact Decimal cash, cash/account-field reconciliation and per-parent STOP/TARGET Protection Graph;
- SQLite-only pending approvals, immutable approval receipts and authenticated API plus CLI entrypoints;
- reservation-aware combined account capacity and explicit capacity No-Trade outcomes;
- read-only IBKR session epochs, raw callback fact tape, snapshot completeness certificate and deterministic reducer;
- execution correction/commission identity and shadow implementation-shortfall decomposition.

Canonical local result:

- `scripts/preflight.sh`: PASS on Python 3.12.13;
- `scripts/verify_all.sh`: PASS;
- Ruff: PASS;
- mypy strict: PASS, 96 source files;
- pytest: PASS, 171 tests;
- branch-aware coverage: 85.20%, required threshold 85%;
- sdist/wheel, doctor, three-cycle synthetic demo and 400-bar registered backtest: PASS;
- local execution reconciliation/approval-list CLI smoke: PASS;
- `git diff --check`: PASS.

The existing upstream Starlette/FastAPI TestClient warning remains non-fatal. Official `ibapi` is not
installed and local Paper ports 4002/7497 are not listening. Therefore authenticated callbacks,
golden-tape burn-in, session reset, durable cancel, bracket recovery and every Paper order are BLOCKED.
No IBKR request or Broker write was made. Profitability remains NOT ESTABLISHED.

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

## M3 authority amendment and M4 Evidence Service - 2026-07-18

Implemented and verified locally without vendor, Provider, LLM, IBKR or external
order access:

- registered protocols and atomic persistent trial allocations bind research
  program, parameter hash and window role; retry idempotency does not bypass budget;
- promotion is derived from immutable artifact digests, protocol/result binding,
  signed validation and a separate signed independent approval; caller booleans
  and researcher self-approval fail closed;
- doubled-cost and delayed counterfactuals now execute through the replay runner;
- entry-bar OHLC ambiguity uses adverse stop-first reduce-only protection;
- moving-block bootstrap and event-label interval purging supplement M3 validation;
- exposure metrics have distinct definitions and journal/cash/lot JSONL artifacts;
- immutable PIT evidence documents, exact citation spans, claim expiry,
  contradictions and content-addressed snapshots;
- strict-schema/no-tool Responses adapter, deterministic extractor, exact cache
  key, persistent call budget and success/failure attempt audit;
- evidence review is limited to allow/veto/abstain on an existing candidate and
  cannot fabricate a claim, size, change risk or call a Broker;
- ablation accounting charges missed gain, Provider cost and latency.

Canonical local result (project `.venv`, Python 3.12.13):

- `./scripts/preflight.sh`: PASS after explicit `.venv` activation;
- `./scripts/verify_all.sh`: PASS;
- Ruff: PASS;
- mypy strict: PASS, 89 source files;
- pytest: PASS, 144 tests;
- branch-aware coverage: 85.56%, required threshold 85%;
- sdist/wheel, doctor, three-cycle synthetic demo and 400-bar registered
  backtest: PASS;
- the existing Starlette/FastAPI TestClient deprecation warning remains non-fatal.

VERIFIED: M3 research-authority defects from the supplied audit are closed, and
M4's local evidence-only boundary is complete. BLOCKED: real OpenAI authentication,
429/5xx/latency/cost behavior and real PIT Agent on/off incremental value; exact
commands depend on a future credentialed acceptance harness and explicit cost
authorization. NOT IMPLEMENTED: durable execution/Fake Broker (M5), IBKR Paper
reconciliation (M6), Ops Dashboard (M7), and live-proposal independent review
(M8). No profitability claim is made.

## M4 audit amendment and M5 durable execution - 2026-07-19

Implemented and verified locally without real Provider, vendor, IBKR or external
order access:

- raw Responses HTTP parsing over `output[].content[]`, refusal handling and
  Provider request/model/token/cache/reasoning/latency audit;
- backend exact-quote span/hash resolution, deterministic claim expiry, scoped
  contradictions, immutable conflicts and atomic extraction finalization;
- evidence review bound to candidate/decision/entity/snapshot/time/config and
  `NO_OBJECTION` semantics;
- fixed-decision-set, risk-weighted ablation without denominator or attribution
  double counting;
- TEST-only, non-counterfactual promotion with real fill, time-in-market and
  benchmark-excess gates;
- runtime M4 Evidence Snapshot/Review to immutable Decision Capsule boundary;
  new exposure is staged to M5 and never directly submitted by the decision loop;
- capacity-checked durable reservation, manual approval, economic intent,
  transactional outbox/inbox, single-writer lease and Broker fencing;
- persistent fault Fake Broker with accepted/dropped response, duplicate Ack,
  partial fill/restart, reject, Broker-only, missing protection, Fill/Cancel race,
  late commission and Broker tape;
- order/fill/position/cash projections, startup reconciliation, Unknown Submit
  resolution, Critical freeze, no-trade/reality-gap and naked-exposure ledgers.

Canonical local result in project `.venv` on Python 3.12.13:

- `source .venv/bin/activate && ./scripts/preflight.sh`: PASS;
- `source .venv/bin/activate && ./scripts/verify_all.sh`: PASS;
- Ruff: PASS;
- mypy strict: PASS, 94 source files;
- pytest: PASS, 159 tests;
- branch-aware coverage: 85.54%, required threshold 85%;
- sdist/wheel, doctor, three-cycle zero-credential synthetic demo and 400-bar
  registered backtest: PASS;
- `git diff --check`: PASS;
- one existing upstream Starlette/FastAPI TestClient deprecation warning remains
  visible and non-fatal.

VERIFIED: all supplied M4 P0/P1 and Promotion recommendations were either
implemented or deliberately narrowed as documented in
`docs/v2-plan/12_M4_M5_AUDIT_INTEGRATION_DECISIONS_ZH.md`; M5 local Fake Broker
control-plane invariants pass. BLOCKED: real Provider billing/429/5xx behavior,
licensed PIT incremental value, authenticated IBKR Paper reconciliation and
callbacks, real bracket transmit/session reset, and forward Paper observation.
NOT IMPLEMENTED in M5: durable IBKR cancel/flatten commands (the current
authenticated emergency path is risk-reducing only), Dashboard (M7), and Live
Proposal independent review (M8). No profitability or production-readiness claim
is made.
