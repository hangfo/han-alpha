# Known limitations

Updated: 2026-07-18 after M2 local portfolio replay implementation.

1. Synthetic data is only for engineering validation. Synthetic returns are not investment evidence.
2. M1 proves PIT contracts only on repository-owned synthetic fixtures. It does not validate any real vendor's timestamps, symbology, revisions, corporate actions, licensing, retention or outage behavior.
3. M2 historical replay is explicit-snapshot/aware-time and deterministic, but legacy synthetic/external provider and runtime execution paths still contain wall-clock calls. The parity harness proves equal decision traces only when adapters supply the same typed inputs; Fake Broker/IBKR parity is not yet exercised.
4. The M2 simulator is long-only, bar-based and single-process. It models partial fills, participation, costs, halts, gaps and corporate actions, but not queue position, order-book depth, auctions, borrow, margin, tax lots, FX, futures rolls or venue-specific rules.
5. The IBKR adapter has not been tested against an authenticated Paper session. No IBKR connection or order action was attempted in M0.
6. Broker idempotency is not yet backed by atomic durable reservations, outbox, a single-writer lease or full startup/continuous reconciliation.
7. The M0 operator token protects default-local mutation routes but is not remote deployment authentication. Read routes remain unauthenticated; TLS, CSRF, actor identity, rotation, rate limits and network policy are M7 work.
8. Broker capability is an application boundary, not protection against compromise of the host or the authorized process. Python objects are opaque conventions, not an OS security boundary; process isolation is deferred.
9. Polygon, SEC and FRED adapters are V0.1 scaffolding and have not been validated against current production responses, subscriptions, licensing or PIT semantics.
10. End-of-replay holdings remain explicitly marked rather than being liquidated using an invented final fill. A strategy protocol that requires flat closeout must provide another eligible bar and explicit exit orders.
11. Sector and fundamental metadata are not supplied by a point-in-time universe, so M2 cannot enforce sector exposure. The M1 exchange calendar is a deterministic fixture classifier, not an authoritative holiday, early-close, halt or venue-rule source.
12. LLM evaluation, caching, budget controls, model pinning, reproducibility and incremental-alpha ablation are not implemented. LLM outputs remain advisory only.
13. `live_proposal` is structurally non-writing; a secure human approval/execution service does not yet exist. There is no `live_auto` mode.
14. The test suite emits one upstream Starlette/FastAPI TestClient deprecation warning; migration should be handled when the dependency ecosystem stabilizes rather than by suppressing the warning.
15. M2 metrics (return, drawdown, turnover and exposure) validate deterministic mechanics only. Capacity, factor attribution, DSR/PBO, walk-forward, purge/embargo and post-cost alpha are M3 gates and are not established.
