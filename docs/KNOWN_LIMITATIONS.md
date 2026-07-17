# Known limitations

Updated: 2026-07-18 after M1 local PIT implementation.

1. Synthetic data is only for engineering validation. Synthetic returns are not investment evidence.
2. M1 proves PIT contracts only on repository-owned synthetic fixtures. It does not validate any real vendor's timestamps, symbology, revisions, corporate actions, licensing, retention or outage behavior.
3. `DecisionClock` governs orchestration/agent review and `AsOfContext` governs the new PIT repository, but legacy synthetic/external providers and execution-event timestamps still contain wall-clock calls. M2 must route historical feature generation through the PIT port before replay parity can be claimed.
4. The current backtester is one-position, long-only and cannot establish portfolio accounting, realistic fills, capacity, multiple-testing control or post-cost alpha.
5. The IBKR adapter has not been tested against an authenticated Paper session. No IBKR connection or order action was attempted in M0.
6. Broker idempotency is not yet backed by atomic durable reservations, outbox, a single-writer lease or full startup/continuous reconciliation.
7. The M0 operator token protects default-local mutation routes but is not remote deployment authentication. Read routes remain unauthenticated; TLS, CSRF, actor identity, rotation, rate limits and network policy are M7 work.
8. Broker capability is an application boundary, not protection against compromise of the host or the authorized process. Python objects are opaque conventions, not an OS security boundary; process isolation is deferred.
9. Polygon, SEC and FRED adapters are V0.1 scaffolding and have not been validated against current production responses, subscriptions, licensing or PIT semantics.
10. Simulated limit prices no longer cross, but partial fills, queue priority, market depth, participation, halts, gap behavior and venue rules are not modeled.
11. Sector and fundamental metadata are not supplied by a point-in-time universe. The M1 exchange calendar is a deterministic fixture classifier, not an authoritative holiday, early-close, halt or venue-rule source.
12. LLM evaluation, caching, budget controls, model pinning, reproducibility and incremental-alpha ablation are not implemented. LLM outputs remain advisory only.
13. `live_proposal` is structurally non-writing; a secure human approval/execution service does not yet exist. There is no `live_auto` mode.
14. The test suite emits one upstream Starlette/FastAPI TestClient deprecation warning; migration should be handled when the dependency ecosystem stabilizes rather than by suppressing the warning.
