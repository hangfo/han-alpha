# Verification and adversarial test plan

## Static checks

- package build;
- Python compile;
- Ruff lint;
- strict configuration validation;
- strict mypy for all source modules.

## Unit tests

- OHLC and quote invariants;
- ATR and relative-strength inputs;
- risk sizing;
- symbol, gross, position-count, drawdown, and daily-loss limits;
- regime strategy allowlist;
- strategy signal geometry;
- ledger idempotency.

## Adversarial tests

- stale quote rejection;
- broker disconnect rejection;
- duplicate order rejection;
- prompt injection in evidence;
- fabricated LLM evidence ID;
- malformed LLM output;
- catalyst unavailable at decision time;
- negative or impossible market data;
- missing quote during flatten;
- repeated cancel-all;
- gap beyond protective stop;
- slippage causing insufficient cash;
- unknown regime;
- live config with paper auto-submit;
- LLM position sizing enabled.

## Integration tests

- full synthetic cycle;
- ledger event generation;
- bracket entry and target/stop exit;
- API startup and health;
- kill-switch control flow.

## M2 replay and experiment tests

- published snapshot/as-of cursor and late-revision visibility;
- same-bar denial, next-eligible-bar fill, limits, stops, gaps, halts, volume and expiry;
- shared-cash/gross/symbol/position/per-trade/aggregate-risk reservation conflicts;
- partial-fill cash reconciliation, FIFO PnL, commissions, splits, dividends and delisting;
- deterministic event/equity hashes and decision parity;
- canonical manifests, append-only legal transitions, failed-run cemetery and counterfactual parent checks;
- immutable JSON/HTML bundles, artifact digest registration and success/failure lifecycle closure;
- local/CI hash-lock contract and generated cache-free project tree.

## Research validation

Before considering alpha credible:

- point-in-time universe;
- delisted symbols;
- realistic costs and spread;
- latency and next-bar execution;
- walk-forward evaluation;
- embargo and purged cross-validation where labels overlap;
- multiple-testing correction;
- parameter perturbation;
- regime and symbol contribution analysis;
- comparison with a non-LLM baseline.

## E1 Broker Truth

- `api` and `all` Completed Orders requests generate different Scope hashes;
- each Observer session exports one isolated tape, certificate and immutable
  hash-verified manifest;
- Manifest ID, Tape/Certificate cross-binding, Scope/Account/Normalization and
  idempotent full-document equality reject tampering;
- Corpus evaluation rejects mixed bindings, incomplete Sessions, fact drops,
  unstable consensus and missing Scope-specific restart/order coverage;
- Observer-only clients reject order placement, cancel, global cancel and option
  exercise even during the separately attested order-visibility phase;
- Golden Tape callback reorder, duplicate, delay, redundancy and overlap
  transforms preserve canonical state or fail the Corpus explicitly;
- Arm/Claim reject expired Quote, Provider, Authority, Approval or Reservation evidence;
- unrelated Heartbeats and unsigned Safety Case Booleans cannot satisfy readiness;
- current-Scope Burn-in never inherits a different Scope's stable count.
- E1 runner resumes the exact API/ALL matrix, counts only verified in-scope
  Sessions and captures at most one Session per invocation;
- Keychain writes never place values in argv, all CLI failure paths redact known
  values/URLs, and human/external/code blockers have distinct exit codes.

## R1 PIT source qualification

- missing license, cache, revision, survivorship or availability-time evidence
  blocks qualification;
- credential preflight exposes only configured/not-configured state;
- placeholder SEC identification, self-reported VERIFIED checks, missing/expired
  artifacts and absent/invalid reviewer signatures fail closed;
- matching only an Artifact type without the exact `qualifies_checks` claim fails;
- bounded SEC/Massive/FRED probes redact keys, bind raw payload hashes and reject
  excessive scope or malformed provider responses;
- compressed HTTP tests prove transport bytes remain byte-exact while normalized
  JSON is decoded and independently hashed;
- strict Artifact documents reject caller type disagreement, and Registry
  authority survives moving the original through a portable content-addressed
  copy while rejecting copied-object tampering;
- R1 dry-runs and missing-secret paths perform no network call; explicit bounded
  execution still remains externally blocked until rights and review exist;
- derived Timestamp/Revision/Symbology/Survivorship audits retain unresolved
  availability semantics as BLOCKED;
- initial vendor templates remain BLOCKED until external evidence is attached.
