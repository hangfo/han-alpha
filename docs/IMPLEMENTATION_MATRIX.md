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
| Idempotent order baseline | PARTIAL | Ledger and broker-local checks exist; atomic reservation/outbox/replay are M5 |
| Prompt-injection defense | PARTIAL | Deterministic firewall and schema checks exist; frozen eval/caching/ablation are M4 |
| PIT security master and symbology | DONE M1 LOCAL | Stable IDs, half-open alias/listing intervals, rename/delist/reuse frozen-fixture tests |
| PIT prices and corporate actions | DONE M1 LOCAL | Bitemporal bars/revisions, raw-preserving split/dividend policy and typed as-of repository |
| Exchange calendar | PARTIAL M1 | DST-safe XNYS fixture session classifier exists; authoritative holidays, early closes, halts and vendor calendar reconciliation remain before real-data claims |
| Immutable snapshot/lineage catalog | DONE M1 LOCAL | Content-addressed raw objects, SQLite staged/published catalog, canonical Parquet and content/schema/code/config hashes |
| Portfolio backtest / parity | DONE M2 LOCAL | PIT cursor, shared portfolio ledger, order states, partial/expiry/corporate-action flows, cost/gap/halt rules, deterministic hashes and parity harness |
| Experiment registry / Strategy Cemetery | DONE M2 LOCAL | Canonical manifest ID, append-only state history, immutable artifact digest registration, failed-run retention, counterfactual link and JSON/HTML bundle |
| Preregistered strategy evidence | PLANNED M3 | Momentum/PEAD/trend overlay, OOS, DSR/PBO, factor attribution |
| LLM Evidence Service | PLANNED M4 | Citation/abstention/caching/budget/model registry and on/off ablation |
| Durable execution control plane | PLANNED M5 | State machine, reservation, outbox, lease, FakeBroker and reconciler |
| IBKR Paper validation | PLANNED M6 | No connection attempted in M0; requires explicit user authorization |
| Ops Dashboard | PLANNED M7 | Read-only first, authenticated controls, CSRF, actor audit, double confirm |
| Live Proposal review | PLANNED M8 | Proposal-only; independent security/legal/operational approval |
| Proven post-cost alpha | NOT ESTABLISHED | Cannot be assessed before M1–M3 gates and forward observation |

The older V0.1 modules remain useful scaffolding, but “implemented adapter” does not mean vendor-, broker-, PIT-, or production-validated.
