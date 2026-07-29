# Implementation matrix

Status values: `DONE` means implemented with local evidence; `PARTIAL` means useful code exists but a gate remains; `PLANNED` means no production claim.

| Requirement | V2 status | Evidence / next gate |
|---|---|---|
| V0.1 provenance and immutable baseline | DONE | Archive SHA plus Git commit `0a69b689`, tree `b7d7d35` |
| Capability-based operating modes | DONE | ADR 0001, `domain/enums.py`, `runtime/capabilities.py` |
| No autonomous live mode | DONE | `OperatingMode` has no `live_auto`; validation/adversarial test |
| Paper automatic submission default-off | DONE | `ExecutionConfig`, `configs/paper.yaml`, config tests |
| Broker write isolation | DONE | Capability required by Broker protocol, simulated adapter and IBKR adapter |
| Dangerous API default-deny | DONE | All POST routes require explicit operator capability; tests expect 403 |
| Explicit aware decision time | DONE HISTORICAL | Orchestrator/agents use `DecisionClock`; M1 PIT queries and M2 replay use explicit aware `AsOfContext`/frames; live adapter callback clocks remain an execution concern |
| Simulated limit semantics | DONE | Buy cannot fill above limit; sell cannot fill below limit; unit tests |
| Direct local synthetic run | DONE M0 | Canonical suite, build, doctor, demo and backtest reproduced from hash lock |
| Reproducible Python dev environment | DONE M1 | `.python-version`, hash lock including DuckDB/editables, locked bootstrap and clean-environment reproduction |
| Deterministic risk baseline | DONE M2 LOCAL | Shared cash, gross, symbol, position-count, per-trade and aggregate open/reserved risk budgets are enforced atomically in replay; durable reservations remain M5 |
| Idempotent order baseline | DONE M5 LOCAL | Economic client key, atomic reservation/intent/outbox, Broker inbox dedupe, unknown-submit reconciliation and adversarial restart tests |
| Prompt-injection defense | DONE M4 LOCAL | Untrusted-document instruction, strict schema/no tools, exact-span validation, fabricated-claim rejection and adversarial fixture; real Provider behavior remains BLOCKED |
| PIT security master and symbology | DONE M1 LOCAL | Stable IDs, half-open alias/listing intervals, rename/delist/reuse frozen-fixture tests |
| PIT prices and corporate actions | DONE M1 LOCAL | Bitemporal bars/revisions, raw-preserving split/dividend policy and typed as-of repository |
| Exchange calendar | PARTIAL M1 | DST-safe XNYS fixture session classifier exists; authoritative holidays, early closes, halts and vendor calendar reconciliation remain before real-data claims |
| Immutable snapshot/lineage catalog | DONE M1 LOCAL | Content-addressed raw objects, SQLite staged/published catalog, canonical Parquet and content/schema/code/config hashes |
| Portfolio backtest / parity | DONE M2 LOCAL | PIT cursor, shared portfolio ledger, order states, partial/expiry/corporate-action flows, cost/gap/halt rules, deterministic hashes and parity harness |
| Experiment registry / Strategy Cemetery | DONE M2 LOCAL | Canonical manifest ID, append-only state history, immutable artifact digest registration, failed-run retention, counterfactual link and JSON/HTML bundle |
| Preregistered strategy evidence | DONE M3 LOCAL | Interpretable baselines, persistent protocol/trial authority, moving-block bootstrap, interval purge, DSR/PBO, executed counterfactuals and signed derived promotion; real Alpha is not established |
| LLM Evidence Service | DONE M4 LOCAL | PIT documents, exact citations, expiry/conflicts, abstention, cache, persistent budgets/attempts, no-trade review firewall and ablation accounting; real Provider and PIT value are BLOCKED |
| Durable execution control plane | DONE M5 LOCAL | Frozen capsule, combined account reservation, approval API/CLI receipt, outbox/inbox, durable freeze tickets, early fence publication, exact cash, per-parent Protection Graph, strict Unknown escrow, persistent Fake Broker and reconciliation |
| IBKR Paper validation | E1-B PARTIAL REAL / EXTERNAL BLOCKED | TWS Paper 7497, official ibapi 10.48.1, Keychain account discovery and five eligible empty-account API sessions are VERIFIED. Case v2 anti-reuse allocation, corrected API 30+4 / ALL 14+2 topology, raw-transport isolation, quote-bound precise-outcome fixture and resumable cleanup are locally verified. Real Observer 33/33 passed; SPY real-time entitlement is missing, so no fixture write occurred and static positions, API/ALL orders, resets/recovery and full Golden Tapes remain BLOCKED |
| PIT vendor qualification | R1-B CODE READY / EXTERNAL BLOCKED | Bounded runner, exact transport/header/normalized evidence, fail-closed rights templates, strict portable Artifact authority, typed audits, expiry and independent Ed25519 review exist; every initial profile remains BLOCKED pending real rights, credentials, samples and review receipts |
| Ops Dashboard | PARTIAL E1 LOCAL | Explicit Heartbeats, current Scope, shared Quote gate, Artifact Registry, Corpus and external API/ALL/R1 acceptance status are source-backed/read-only; deployed alerts/E2E and authenticated write controls are BLOCKED/NOT IMPLEMENTED |
| Live Proposal review | PLANNED M8 | Proposal-only; independent security/legal/operational approval |
| Proven post-cost alpha | NOT ESTABLISHED | Cannot be assessed before M1–M3 gates and forward observation |

The older V0.1 modules remain useful scaffolding, but “implemented adapter” does not mean vendor-, broker-, PIT-, or production-validated.
