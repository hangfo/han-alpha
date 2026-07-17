# Known limitations

Updated: 2026-07-18 after M0 safety implementation.

1. Canonical ruff, mypy strict, full pytest/coverage and package-build verification have not been rerun because the available local Python runtimes do not contain the complete dev toolchain. This is a hard M1 entry blocker, not a test pass.
2. Synthetic data is only for engineering validation. Synthetic returns are not investment evidence.
3. The data layer is not point-in-time complete: no stable security master, delisting history, ticker-validity intervals, full corporate-action event store, exchange calendar, revision policy or immutable dataset catalog exists yet.
4. `DecisionClock` governs orchestration and agent review, but synthetic/external providers and execution-event timestamps still contain wall-clock calls. M1/M2 must propagate snapshot/as-of semantics before replay equivalence can be claimed.
5. The current backtester is one-position, long-only and cannot establish portfolio accounting, realistic fills, capacity, multiple-testing control or post-cost alpha.
6. The IBKR adapter has not been tested against an authenticated Paper session. No IBKR connection or order action was attempted in M0.
7. Broker idempotency is not yet backed by atomic durable reservations, outbox, a single-writer lease or full startup/continuous reconciliation.
8. The M0 operator token protects default-local mutation routes but is not remote deployment authentication. Read routes remain unauthenticated; TLS, CSRF, actor identity, rotation, rate limits and network policy are M7 work.
9. Broker capability is an application boundary, not protection against compromise of the host or the authorized process. Process/OS isolation is deferred.
10. Polygon, SEC and FRED adapters are V0.1 scaffolding and have not been validated against current production responses, subscriptions, licensing or PIT semantics.
11. Simulated limit prices no longer cross, but partial fills, queue priority, market depth, participation, halts, gap behavior and venue rules are not modeled.
12. Sector and fundamental metadata are not supplied by a point-in-time universe.
13. LLM evaluation, caching, budget controls, model pinning, reproducibility and incremental-alpha ablation are not implemented. LLM outputs remain advisory only.
14. `live_proposal` is structurally non-writing; a secure human approval/execution service does not yet exist. There is no `live_auto` mode.
