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
| Explicit aware decision time | PARTIAL | Orchestrator/agents use `DecisionClock`; provider/execution wall-clock removal continues in M1/M2 |
| Simulated limit semantics | DONE | Buy cannot fill above limit; sell cannot fill below limit; unit tests |
| Direct local synthetic run | PARTIAL | V0.1 baseline and offline M0 full-cycle smoke; canonical full suite pending toolchain |
| Deterministic risk baseline | PARTIAL | V0.1 engine exists; order reservations/worst-case portfolio risk are M2/M5 |
| Idempotent order baseline | PARTIAL | Ledger and broker-local checks exist; atomic reservation/outbox/replay are M5 |
| Prompt-injection defense | PARTIAL | Deterministic firewall and schema checks exist; frozen eval/caching/ablation are M4 |
| PIT security master and symbology | PLANNED M1 | Stable IDs, listing intervals, aliases, inactive/delisted universe |
| PIT prices, corporate actions and calendar | PLANNED M1 | Bitemporal contracts, raw/canonical storage, frozen fixtures |
| Immutable snapshot/lineage catalog | PLANNED M1 | Content/schema/code/config hashes and quality publication gate |
| Portfolio backtest / parity | PLANNED M2 | Cash, orders, partial fills, costs, halts, gap and accounting invariants |
| Preregistered strategy evidence | PLANNED M3 | Momentum/PEAD/trend overlay, OOS, DSR/PBO, factor attribution |
| LLM Evidence Service | PLANNED M4 | Citation/abstention/caching/budget/model registry and on/off ablation |
| Durable execution control plane | PLANNED M5 | State machine, reservation, outbox, lease, FakeBroker and reconciler |
| IBKR Paper validation | PLANNED M6 | No connection attempted in M0; requires explicit user authorization |
| Ops Dashboard | PLANNED M7 | Read-only first, authenticated controls, CSRF, actor audit, double confirm |
| Live Proposal review | PLANNED M8 | Proposal-only; independent security/legal/operational approval |
| Proven post-cost alpha | NOT ESTABLISHED | Cannot be assessed before M1–M3 gates and forward observation |

The older V0.1 modules remain useful scaffolding, but “implemented adapter” does not mean vendor-, broker-, PIT-, or production-validated.
