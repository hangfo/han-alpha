# Han Alpha risk register

Updated: 2026-07-18 after M2 local replay verification.

| ID | Severity | Risk | Current control | Residual / next milestone |
|---|---|---|---|---|
| R-001 | P0 | Future information or current constituents leak into historical decisions | M1 `AsOfRepository` plus M2 `PITEventCursor` enforce published snapshot, aware `as_of`, availability, validity and visible revisions; same-bar fill is rejected | Validate real vendor semantics and feature pipelines before M3 real-data evidence |
| R-002 | P0 | Unauthorized order submission | Capability-gated Broker methods; non-paper modes cannot obtain capability; no `live_auto`; M5 new exposure uses fenced single-writer outbox | Process/OS separation and real IBKR enforcement in M6 |
| R-003 | P0 | Local HTTP mutation without operator intent | Every POST defaults to 403; distinct operator token when enabled | Authenticated session, CSRF, actor audit and double confirmation in M7 |
| R-004 | P0 | Simulated fill violates execution semantics | M2 tests limit caps, next-eligible-bar timing, partial fills, participation, halts, gaps, stop-limit non-fill and order expiry | Queue priority, depth and venue-specific auctions require licensed data; never interpret M2 fills as venue validation |
| R-006 | P1 | Synthetic metrics are mistaken for alpha | M2 result report says engineering evidence only; failed hypotheses are retained | M3 preregistration, real PIT data review, OOS evaluation and multiple-testing control |
| R-007 | P1 | Broker/local state diverges after callbacks, restart or nightly reset | M5 durable state machine, projections, outbox/inbox and Fake Broker reconciliation | Validate IBKR callbacks, nightly reset and Paper truth in M6 |
| R-008 | P1 | Historical and runtime decisions diverge | M2 decision identity hashes snapshot/as-of/config/input/signal/risk and parity compares decision traces; historical replay has no wall clock | Exercise the same candidate/risk core through Fake Broker in M5 and IBKR Paper in M6 |
| R-009 | P1 | Vendor timestamps, symbol history or adjustments are wrong | M1 immutable raw/lineage and local contract tests; no production claim | Source-specific licensing/semantic review, golden payloads and reconciliation before any real adapter is accepted |
| R-010 | P1 | LLM hallucination, prompt injection or model drift changes decisions | M4 strict no-tool extraction, backend citation resolution, bound review, cache/budget/audit and fixed-set ablation; no Broker capability | Real Provider adversarial acceptance and licensed PIT incremental-value study |
| R-011 | P2 | Secret theft or local host compromise bypasses application policy | Secrets excluded from repo; separate tokens; constant-time digest comparison | Keychain/secret manager, separate UID/process, rotation and incident runbook in M5–M7 |
| R-012 | P2 | Overbuilding UI/agents before data truth wastes effort | Milestone gates put PIT and backtest first | Do not start dashboard or new LLM agents before M1–M4 evidence gates |

No risk above is evidence of profitability. P0 means a safety or validity blocker, not an estimate of likelihood.

Resolved in M0: R-005, the missing-toolchain verification gap. A hash-locked Python 3.12 environment reproduced the full suite.
