# Changelog

## 2026-07-26 — Secure external onboarding and exact evidence transport

- Added macOS Keychain-backed local secrets, safe `.env` migration, guided IBKR
  readiness checks and structured human/external/code blocker exits.
- Added resumable `e1 run` and bounded `r1 run` orchestration with fixed scenario
  matrices, explicit no-network dry-runs and GitHub-safe summaries.
- Split literal HTTP response bytes, selected headers and normalized JSON into
  independently hashed evidence layers, including compressed-response coverage.
- Added strict authority-document schemas, explicit Artifact identity semantics
  and a portable content-addressed Registry object store.
- Added adversarial secret-redaction, Keychain argv isolation, onboarding,
  runner-resume, Artifact portability/tamper and transport-byte tests.
- Verified 254 Python tests at 85.21% branch-aware coverage, strict mypy over
  115 source files, package/CLI/API/research smoke checks, frontend tests/build
  and zero npm audit vulnerabilities. No Broker or vendor request was made.

## 2026-07-26 — E1-B/R1-B executable acceptance tooling

- Added an observer-only IBKR client that structurally rejects every order write,
  corrected the TWS Read-Only/order-visibility split, and automatically registered
  Preflight and Session evidence.
- Added Golden Tape metamorphic replay, Callback Truth Map, explicit Scope-mixing
  rejection and source-backed Corpus/Evidence views in Ops and React.
- Added bounded secret-redacted SEC/Massive/FRED probes, immutable raw payload
  manifests and typed source audits.
- Bound qualification Artifacts to exact `qualifies_checks`; a generic Artifact
  type can no longer satisfy unrelated evidence requirements.
- Sanitized live Probe errors so request URLs containing API keys cannot leak
  through CLI tracebacks.
- Verified 237 Python tests at 85.00% branch-aware coverage, strict mypy over
  110 source files, package/CLI/API/research smoke checks, frontend tests and
  production build. External Broker/vendor calls remain credential-gated.

## 2026-07-26 — E1-A/R1-A evidence authority

- Made Burn-in Manifest v2 self-verifying across canonical identity, files,
  Certificate, Tape, Scope and current capture inputs.
- Added a typed Artifact Registry/Resolver and Scope-specific Burn-in Corpus
  evaluator with nonzero BLOCKED exit and scenario coverage gates.
- Replaced symmetric Safety Case HMAC with runtime-only Ed25519 public-key
  verification and independent Risk/Execution reviewer receipts.
- Prevented PIT Profiles from self-authorizing: qualification now requires
  registered, unexpired, type-correct artifacts and signed independent reviews.
- Renamed credential output to `credentials_present_for`, added strict redacted
  SEC User-Agent validation and separated research from promotion qualification.
- Verified 223 Python tests at 85.09% branch-aware coverage, strict mypy over
  107 source files, package/CLI/API/research smoke checks, frontend tests and
  production build. No Broker, vendor or LLM request was made.

## 2026-07-26 — E1/R1 evidence-stream entry

- Added Completed Orders `api/all` Scope execution, redacted zero-write IBKR
  Preflight, per-session immutable burn-in tapes/certificates/manifests and
  current-Scope Ops counters.
- Propagated the earliest Authority/Quote/Approval/Reservation deadline into Arm
  expiry and revalidated the same quote policy at Claim.
- Replaced caller-stored Safety Case Booleans with canonical ID, status, expiry,
  revocation, Scope and evidence-hash verification; ADR 0011 subsequently
  supersedes the local HMAC trusted root with offline Ed25519 review.
- Added explicit per-layer Heartbeat sets and separated quote evidence eligibility
  from an unverified intent binding.
- Added fail-closed Massive, SEC EDGAR and FRED/ALFRED PIT qualification profiles
  plus redacted vendor credential preflight.
- Added backup `content_set_hash` and froze post-M7-B.1 architecture expansion
  under E1/R1/E2/E3/R2 evidence-stream names.
- Verified 215 Python tests at 85.04% branch-aware coverage, strict mypy over
  106 source files, package/CLI/API/research smoke checks, frontend tests and
  production build. No Broker, vendor or LLM request was made.

## 2026-07-26 — M7-B.1 authority normalization and admission

- Split Observer envelopes from stable visibility policy and canonical broker state.
- Added exact economic hashes, bounded valuation-equivalence receipts and genuine independent dual-session consensus tests.
- Added versioned actor-attributed re-Arms and strict realtime Quote admission.
- Separated Runtime Control readiness from the complete Paper Canary Safety Case.
- Corrected Fact Drop, Unknown age, discrepancy revision, burn-in and restore truth.
- Verified 205 Python tests at 85.14% branch-aware coverage, strict typing, frontend, package and smoke checks. No Provider or Broker write was performed.

## 2026-07-19 — M5 review hardening and M6 read-only observer kernel

- Unified new-risk safety under durable Freeze Tickets, hardened fencing and Unknown Submission recovery, removed in-memory pending approvals, and added formal approval API/CLI receipts.
- Replaced Fake Broker floating cash updates with exact Decimal text arithmetic; reconciled cash/account fields and per-parent STOP/TARGET protection graphs.
- Added IBKR read-only session epochs, raw callback fact tape, completeness certificates, native-identity reducer and shadow execution reality-gap accounting.
- Real IBKR Paper connectivity and all Broker writes remain blocked and were not attempted.

## Unreleased - M3 preregistered strategy evidence (2026-07-18)

### Added

- Immutable point-in-time research contexts and interpretable momentum, slow-trend and typed PEAD falsification baselines.
- Pre-registered train/validation/test windows, fixed parameter ranges, research budgets, purge/embargo walk-forward folds and budgeted cost/delay/parameter counterfactual manifests.
- Time-weighted portfolio/risk metrics, bootstrap intervals, Deflated Sharpe, CSCV Probability of Backtest Overfitting and Holm multiple-testing correction with fail-closed sample checks.
- Explicit statistical/risk/reproducibility/manual promotion gate and counterfactual outcomes for rejected decisions.
- True balanced journal entries for capital, trades, commissions and corporate actions.

### Fixed

- Historical data revisions can update research knowledge but can no longer create ghost fills; corporate-action revisions cannot duplicate cash or position effects.
- Candidate permutation is deterministic and duplicate candidates fail closed.
- Partial entry fills now create executable reduce-only stop/target OCO children; conservative stop-first matching prevents double exits.
- Re-running a completed deterministic experiment returns its verified immutable result instead of attempting an illegal lifecycle transition.

### Changed

- `hanalpha backtest` now uses portfolio replay plus the experiment registry and emits a deterministic artifact bundle; the former verifier is `legacy-backtest`.
- Backend branch coverage enforcement is raised to 85%; the credential-gated live IBKR adapter remains M6 integration scope and is explicitly excluded from the local denominator.

### Verification and safety

- Ruff, strict mypy, package build, CLI/API smoke, adversarial and full regression checks pass at 85%+ branch coverage.
- No vendor, LLM, IBKR or order call was made. Synthetic results validate mechanics only and are not evidence of profitability.

## Unreleased - M2 deterministic portfolio replay (2026-07-18)

### Added

- Published-snapshot PIT replay cursor, canonical decision identity and historical/runtime parity harness.
- Explicit order states with market/limit/stop behavior, next-eligible-bar timing, partial fills, participation limits, cost scenarios, gaps, halts and expiry release.
- Decimal shared-capital portfolio ledger with atomic cash/exposure/risk reservations, FIFO lots, commissions, splits, dividends, delisting recovery and conservation checks.
- Canonical experiment registry with append-only trial history, Strategy Cemetery, counterfactual linkage, immutable artifact digests and deterministic JSON/HTML result bundles.
- End-to-end local experiment runner that records both completed and failed runs.
- Git-content project-tree generator and CI parity tests.

### Fixed

- The V0.1 backtester no longer marks a next-bar position in the prior bar's equity.
- Gap-through-stop exits now use the adverse opening price rather than the stale stop; entry and exit commissions reconcile separately.

### Changed

- GitHub Actions now uses the same Python 3.12 hash lock, preflight, full verification and `pip check` contract as local development.
- Milestone numbering now follows M2 replay, M3 strategy evidence, M4 LLM evidence, M5 execution control, M6 IBKR Paper, M7 Ops and M8 Live Proposal.

### Verification and safety

- Ruff and strict mypy passed for 72 source files; 110 tests passed at 80.14% branch-aware coverage.
- Build, doctor, three-cycle demo, 400-bar baseline backtest and `pip check` passed locally and in a clean hash-locked Python 3.12.13 environment.
- No vendor, LLM, IBKR or order call was made. M2 validates mechanics, not profitability, capacity or production venue behavior.

## Unreleased - M1 PIT data kernel (2026-07-18)

### Added

- Frozen synthetic PIT fixture v1 covering stable instrument IDs, ticker rename/reuse, delisting, late revisions, split/dividend events and DST boundaries.
- Immutable content-addressed raw bytes, SQLite lineage/publication catalog and DuckDB-backed canonical Parquet snapshots.
- Typed `AsOfRepository` with centralized availability, validity interval, snapshot publication and latest-visible-revision enforcement.
- Deterministic snapshot/feature hashing, fail-closed quality reports and fixture ingest/quality/snapshot CLI commands.
- Minimal deterministic XNYS session classifier for fixture validation, with explicit DST ambiguity/nonexistence rejection.

### Changed

- Added and hash-locked DuckDB 1.5.4 plus the explicit editable-build dependency required by clean bootstrap.
- Raised the canonical repository result to 76 tests and 77.41% branch-aware coverage.

### Safety

- M1 makes no vendor, LLM, IBKR or order call and does not weaken any M0 capability boundary.
- Staged or failed-quality snapshots remain non-queryable; canonical snapshot content cannot be overwritten.

## Unreleased - M0 safety baseline (2026-07-18)

### Added

- V0.1 baseline Git freeze and provenance identifiers.
- Capability-based operating modes with no `live_auto` state.
- Explicit timezone-aware `DecisionClock` for orchestration and agent review.
- Runtime-issued Broker write capability and separate operator API token boundary.
- Structural/adversarial tests for non-paper submission denial, naive time, limit prices and default-deny API behavior.
- ADR, risk register, M0 execution plan and M1 PIT entry decision.
- Hash-locked Python 3.12 development requirements and clean-environment bootstrap.

### Changed

- Default configuration is `paper_manual`; paper auto-submit and all API mutations are off.
- Simulated buy/sell fills respect their limit prices after adverse slippage.
- Broker `submit`, `cancel_all` and `flatten_all` require an explicit capability.
- LLM reviewer payloads include the decision `as_of`; LLMs still have no Broker tool.
- Package verification builds without isolation from the locked toolchain.

### Security

- Every POST route now requires an explicitly enabled operator token; cancel/flatten also require Broker write capability.
- `research`, `backtest`, `shadow` and `live_proposal` cannot obtain Broker write capability.

### Verification status

- M0 reproduced in a fresh hash-locked Python 3.12.13 environment.
- Ruff passed; mypy strict passed for 46 source files; 48 tests passed at 72.02% branch-aware coverage; package build, doctor, demo and backtest passed.
