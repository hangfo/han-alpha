# Active execution plan: complete Han Alpha platform

Status: ACTIVE; E1-A/R1-A complete, E1-B/R1-B external evidence blocked
Owner: Codex
Last updated: 2026-07-26

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
- [ ] M6 IBKR Paper integration and observation (local hardening complete; real burn-in blocked)
- [ ] M7 Ops Dashboard, observability and recovery operations (M7-B read-only local slice complete; deployed operations blocked)
- [x] E1-A Evidence Integrity (self-verifying manifests, artifact resolver, corpus gate)
- [ ] E1-B Broker Acceptance (authenticated matrix and Golden Tapes blocked)
- [x] R1-A Qualification Authority (artifact-backed, reviewed, expiring evidence)
- [ ] R1-B Source Acceptance (license, entitlement and bounded samples blocked)
- [ ] E2 Canary Authorization and E3 Paper Manual Execution
- [ ] R2 Friction-aware out-of-sample and forward evidence
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
- 2026-07-20: M6 audit hardening added callback Queue single-writer, transport-only observation, semantic request barriers, visibility scope, native identity, M5 snapshot adapter, two-snapshot consensus, cash epochs, two-stage approve/arm, durable cancel and schedule-aware reality gaps. M7-A added source-backed read-only Ops API/dashboard plus backup/restore. No Provider or Broker write was made; real Paper burn-in remains blocked.
- 2026-07-20: M7-A review hardening made Snapshot consensus non-replayable, split component Authority hashes, restricted promotion to complete CONVERGED candidates, replaced caller-reported quote evidence with persisted Quote Capsules, separated Bracket leg identity, added Completed Orders facts, discrepancy lifecycle and Generation Restore. M7-B added layered readiness, fact-age status, Authority timeline, backup and honest burn-in progress. No Provider or Broker write was made.
- 2026-07-26: M7-B.1 separated Observation Window, Scope Policy and Canonical Broker State; added bounded valuation-equivalence receipts, genuine dual-session consensus, versioned re-Arms, strict Quote admission, full Canary Safety Case gating, corrected Ops metrics and non-destructive idempotent restore. Local verification passed 205 Python tests at 85.14% branch-aware coverage plus frontend/build checks. Real IBKR burn-in, PIT Alpha evidence and every Broker write remain blocked.
- 2026-07-26: ADR 0010 freezes architecture expansion and replaces M7-B.x naming with E1/R1 evidence streams. E1 adds Completed Orders dual Scope, zero-write Preflight, immutable Session artifacts, freshness propagation, current-Scope burn-in, explicit Heartbeat sets and verified Safety Case semantics. R1 adds fail-closed vendor/license/PIT qualification profiles. No Broker/vendor request or order was made.
- 2026-07-26: ADR 0011 closes local evidence-authority gaps. E1-A adds
  Manifest/Tape/Certificate self-verification, Artifact resolution, Scope-specific
  coverage Corpus evaluation and nonzero acceptance exits. R1-A requires typed
  artifacts, expiry and signed independent review. Safety Case HMAC is replaced by
  two independent offline Ed25519 reviews. Full local verification passed 223
  Python tests at 85.09% branch-aware coverage, strict mypy over 107 source
  files, package/CLI/API/research smoke checks and the frontend suite/build.
  E1-B/R1-B remain externally blocked.
- 2026-07-26: The webpage review and Issues #1/#2 exposed an unmodeled TWS
  Read-Only/order-visibility conflict. The Observer now structurally blocks write
  methods; account-only and manual-order visibility attestations are distinct.
  Golden Tape transforms, Callback Truth Map, claim-scoped qualification evidence,
  bounded live-source probes and source-backed Evidence/Corpus views are locally
  implemented. External accounts, licenses, real samples and independent review
  still block E1-B/R1-B completion.
- 2026-07-26: Issue #3 local onboarding is complete. macOS Keychain is the
  preferred SecretProvider; E1/R1 runners are resumable and fail closed;
  qualification documents are strict and Registry objects portable; probes bind
  literal transport bytes, safe headers and normalized JSON separately. Full
  local verification passed 255 Python tests at 85.23% branch coverage and the
  complete package/API/frontend/security suite. The local machine still lacks
  TWS/Gateway, official `ibapi`, Paper login/account and data-source identities,
  so no Broker/vendor request was made and E1-B/R1-B remain external.
- 2026-07-26: Issue #4 review hardening moved child Secrets from environment to
  bounded stdin IPC, introduced composite Broker/account/environment identity,
  added a license-attested safe official ibapi installer, fail-closed R1 rights
  templates and a Registry-backed external acceptance panel. Independent signing
  and Evidence Passport are deliberately deferred until real E1/R1 evidence
  exists; human license acceptance, Paper login/2FA and data rights remain gates.

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

M7-B.1 local evidence is archived in
`../completed/011-m7b1-normalization-admission.md`. The current parallel work is
tracked in `012-e1-broker-truth-readiness.md` and
`013-r1-pit-data-qualification.md`; review integration decisions are recorded in
`../../v2-plan/18_E1_R1_REVIEW_AND_EVIDENCE_AUTHORITY_ZH.md` and
`../../v2-plan/19_E1B_R1B_WEB_REVIEW_AND_REALITY_GAPS_ZH.md`.
Issue #3 decisions and the post-qualification sequence are recorded in
`../../v2-plan/20_E1B_R1B_ISSUE3_REVIEW_AND_ONBOARDING_ZH.md`.
Issue #4 decisions and the beginner-safe real setup sequence are recorded in
`../../v2-plan/21_E1B_R1B_ISSUE4_REVIEW_AND_OPERATOR_GUIDE_ZH.md`.
