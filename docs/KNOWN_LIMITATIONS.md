# Known limitations

Updated: 2026-07-30 after Issue #7 zero-cost and lifecycle hardening.

1. Synthetic data is only for engineering validation. Synthetic returns are not investment evidence.
2. M1 proves PIT contracts only on repository-owned synthetic fixtures. It does not validate any real vendor's timestamps, symbology, revisions, corporate actions, licensing, retention or outage behavior.
3. M2 historical replay and the M5 Decision Capsule are explicit-snapshot/aware-time and deterministic. The parity harness proves equal decision traces only when adapters supply the same typed inputs; IBKR parity is not yet exercised.
4. The M2 simulator is long-only, bar-based and single-process. It models partial fills, participation, costs, halts, gaps and corporate actions, but not queue position, order-book depth, auctions, borrow, margin, tax lots, FX, futures rolls or venue-specific rules.
5. The official `ibapi 10.48.1` adapter has now been tested against an authenticated
   local TWS Paper session on port 7497. Account summary, positions, open/completed
   API orders and executions were observed with Client ID 41, but this proves only
   the zero-write empty-account slice, not real order submission or recovery.
6. M5 Broker idempotency, atomic reservations/outbox, single-writer fencing and reconciliation are verified only against the persistent repository-owned Fake Broker. Real IBKR orderRef/permId/execution mapping, bracket transmit, callback ordering, pacing and session-reset recovery remain M6.
7. E1-B has five verified `empty_account` API-Scope sessions with no fact drops or
   reconciliation failures. Static positions, API/manual orders, commissions,
   process/TWS/network/nightly recovery, client-ID switching, ALL Scope and the
   complete Golden Tape matrix remain externally BLOCKED.
8. Safety Case verification requires resolvable artifacts and independent Ed25519 Risk/Execution receipts. The isolated E1 fixture has its own one-shot scenario Permit, but this is deliberately not an E2 Canary Permit and gives no authority to the runtime or existing Outbox.
9. Generation Restore is atomic across restored files, but sequential online backups are not a distributed transaction. `content_set_hash` identifies equal database bytes; `generation_id` remains manifest/time addressed. Quiesce writers for a strict cross-store PIT backup.
10. The M0 operator token protects default-local mutation routes but is not remote deployment authentication. Read routes remain unauthenticated; TLS, CSRF, actor identity, rotation, rate limits and network policy remain deployment work.
11. Broker capability is an application boundary, not protection against compromise of the host or the authorized process. Python objects are opaque conventions, not an OS security boundary.
12. Massive, SEC and FRED/ALFRED bounded runners and exact transport-byte probe/audit tooling exist, but production adapters are not qualified or enabled. R1-B remains BLOCKED on actual licenses, entitlements, live sampled payloads, timestamp semantics, survivorship, revisions and independent reviews.
13. End-of-replay holdings remain explicitly marked rather than being liquidated using an invented final fill. A flat-close protocol must provide another eligible bar and explicit exit orders.
14. Sector and fundamental metadata are not supplied by a qualified PIT universe. The M1 calendar is a deterministic fixture classifier, not an authoritative holiday, early-close, halt or venue-rule source.
15. M4 implements local LLM evidence contracts and ablation mechanics. Real Provider value on licensed PIT data remains unvalidated; LLM outputs have no sizing, risk or Broker authority.
16. `live_proposal` is structurally non-writing; a secure human execution service does not yet exist. There is no `live_auto` mode.
17. The suite emits one upstream Starlette/FastAPI TestClient deprecation warning; it is not suppressed.
18. No licensed real-data post-cost Alpha, Paper forward performance or capacity claim is established.
19. Per-intent cancel has a durable fenced path, but real IBKR cancel callback mapping and Bracket recovery are not externally validated.
20. Reality-gap supports partial-fill schedules, opportunity cost and protection delay, but real Replay/Shadow/Paper comparisons require a forward window.
21. The Ops UI remains read-only. Browser mutation controls are intentionally not implemented.
22. macOS Keychain and guided runners now hold the discovered Paper account through
    the native Security framework without exposing it to argv or environment.
    They still cannot provision accounts, obtain paid entitlements or issue
    independent receipts.
23. The local installer installed the user-downloaded official TWS API ZIP after
    explicit license attestation. It cannot independently prove download
    provenance or approve licenses/login/2FA on the user's behalf.
24. External Acceptance counts are operational evidence summaries, not strategy
    profitability, safety certification or authorization to trade.
25. Issue #5 closes label-only restart evidence, mixed-Scope client-switch
    arithmetic, Observer denylist drift and snapshot/binding ambiguity locally.
    Genuine static/API/manual order, restart, network/nightly and client-switch
    callback evidence is still absent.
26. The E1 Paper fixture is hard-limited to Paper ports, a reserved client range,
    one whole STK share and USD 1,000 notional. It has not yet sent a Broker write,
    cannot automate TWS GUI manual orders, and must not be represented as strategy
    execution or profitability evidence.
27. Issue #6 invalidates the earlier API 24 / ALL 10 acceptance totals: those
    totals could not provide disjoint evidence for every required two-Session
    Case. Policy v3 requires API 34 and ALL 16 Sessions.
28. TWS contract qualification for SPY succeeds, but the Paper session currently
    lacks eligible real-time market data. Delayed quotes are not accepted for a
    filling fixture, so no Quote Capsule, Permit, lifecycle or first PLACE exists.
29. Fixture lifecycle recovery is application-auditable but not an OS-isolated
    trading daemon. Host compromise remains outside the Python safety boundary.
30. All three R1 credentials are present in macOS Keychain. A bounded two-request
    SEC probe succeeded at the HTTP/evidence layer, but written rights and
    independent review remain missing. FRED is blocked before network under the
    current terms review; Massive is blocked before network until the exact
    Basic/free or existing fixed plan and entitlement are attested.
31. The operator reports that US Paper real-time data is active, but the current
    TWS API session still rejects the bounded SPY streaming quote. A subscription
    report is not substituted for the Broker callback; relogin/data-sharing/API
    acknowledgement must be verified before a fixture Permit can exist.
32. `51b8c95` was committed and pushed successfully. Its GitHub red check was a
    clean-CI collection failure because the separately licensed official `ibapi`
    package is intentionally absent there. Fixture and observer contract
    fallbacks now support clean-CI safety tests while every real API operation
    still fails closed without it.
