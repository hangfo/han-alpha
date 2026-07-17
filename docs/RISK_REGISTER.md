# Han Alpha risk register

Updated: 2026-07-18 after M0 code checkpoint `43b77f4`.

| ID | Severity | Risk | Current control | Residual / next milestone |
|---|---|---|---|---|
| R-001 | P0 | Future information or current constituents leak into historical decisions | Explicit aware `DecisionClock`; evidence has `available_at` | PIT storage/query enforcement, delistings, corporate actions and snapshot tests in M1 |
| R-002 | P0 | Unauthorized order submission | Capability-gated Broker methods; non-paper modes cannot obtain capability; no `live_auto` | Process/OS separation and durable single-writer lease in M5 |
| R-003 | P0 | Local HTTP mutation without operator intent | Every POST defaults to 403; distinct operator token when enabled | Authenticated session, CSRF, actor audit and double confirmation in M7 |
| R-004 | P0 | Simulated fill violates limit semantics | Buy fill capped at limit; sell fill floored at limit; adversarial tests added | Partial fills, queue/volume, halts and gap behavior in M2 |
| R-006 | P1 | V0.1 synthetic metrics are mistaken for alpha | Documentation labels them engineering-only | M1 real PIT fixtures, then M2/M3 preregistered OOS evaluation |
| R-007 | P1 | Broker/local state diverges after callbacks, restart or nightly reset | Idempotency and ledger baseline only | Durable state machine, reservations, outbox and reconciler in M5–M6 |
| R-008 | P1 | Decision outputs remain partly nondeterministic because providers/events use wall clock | Orchestrator and agents use DecisionClock | Propagate snapshot/as-of contracts through providers in M1 and execution simulation in M2 |
| R-009 | P1 | Vendor timestamps, symbol history or adjustments are wrong | No production claim | Source-specific validation, immutable raw payloads, lineage and reconciliation in M1 |
| R-010 | P1 | LLM hallucination, prompt injection or model drift changes decisions | Read-only schema-validated evidence role; deterministic veto/risk; no Broker capability | Frozen eval set, cache, budget, abstention and ablation gate in M4 |
| R-011 | P2 | Secret theft or local host compromise bypasses application policy | Secrets excluded from repo; separate tokens; constant-time digest comparison | Keychain/secret manager, separate UID/process, rotation and incident runbook in M5–M7 |
| R-012 | P2 | Overbuilding UI/agents before data truth wastes effort | Milestone gates put PIT and backtest first | Do not start dashboard or new LLM agents before M1–M4 evidence gates |

No risk above is evidence of profitability. P0 means a safety or validity blocker, not an estimate of likelihood.

Resolved in M0: R-005, the missing-toolchain verification gap. A hash-locked Python 3.12 environment reproduced the full suite.
