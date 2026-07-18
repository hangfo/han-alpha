# M4 execution plan: evidence service and LLM firewall

Status: COMPLETE LOCALLY
Owner: Codex
Date: 2026-07-18

## Delivered

- M3 authority amendment: persistent protocol/trial allocation, executed
  counterfactuals, derived signed promotion, adverse same-bar protection,
  dependent bootstrap, interval purge and explicit ledger artifacts.
- Immutable point-in-time evidence documents and exact source spans.
- Typed claims, expiry, contradiction graph and deterministic snapshots.
- Deterministic extractor plus OpenAI Responses strict-schema adapter with no tools.
- Content/schema/model/prompt/version cache key, persistent call budgets and
  success/failure attempt audit.
- Evidence-only allow/veto/abstain review firewall and fabricated-claim rejection.
- Baseline/evidence ablation accounting including missed gain, model and latency cost.
- Adversarial tests for future evidence, prompt injection payloads, cache reuse,
  expiry, contradictions, budget exhaustion, timeout audit and authority separation.

## External blockers

- Real Provider acceptance is BLOCKED on an explicitly supplied API key and cost
  authorization. No call was made in this milestone.
- Real-data incremental value is BLOCKED on licensed PIT documents, source clock
  review and frozen forward outcomes.
- M4 does not integrate with Broker code and grants no execution authority.

## Verification

Final command evidence is recorded in `docs/VERIFICATION_REPORT.md`: 144 tests
passed at 85.56% branch coverage, with Ruff, mypy strict, package build, CLI/API
smoke and safety checks passing. M5 may begin with a local Fake Broker and
durable execution state machine; IBKR remains M6.
