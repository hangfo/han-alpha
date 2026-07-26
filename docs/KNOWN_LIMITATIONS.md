# Known limitations

Updated: 2026-07-26 after Issue #4 external acceptance hardening.

1. Synthetic data is only for engineering validation. Synthetic returns are not investment evidence.
2. M1 proves PIT contracts only on repository-owned synthetic fixtures. It does not validate any real vendor's timestamps, symbology, revisions, corporate actions, licensing, retention or outage behavior.
3. M2 historical replay and the M5 Decision Capsule are explicit-snapshot/aware-time and deterministic. The parity harness proves equal decision traces only when adapters supply the same typed inputs; IBKR parity is not yet exercised.
4. The M2 simulator is long-only, bar-based and single-process. It models partial fills, participation, costs, halts, gaps and corporate actions, but not queue position, order-book depth, auctions, borrow, margin, tax lots, FX, futures rolls or venue-specific rules.
5. The IBKR adapter has not been tested against an authenticated Paper session. The current machine has no importable official `ibapi`, listening Paper port or configured Paper account. TWS Read-Only can observe account state but hides orders, so order-scope acceptance requires the separately attested zero-write observer-only mode.
6. M5 Broker idempotency, atomic reservations/outbox, single-writer fencing and reconciliation are verified only against the persistent repository-owned Fake Broker. Real IBKR orderRef/permId/execution mapping, bracket transmit, callback ordering, pacing and session-reset recovery remain M6.
7. E1-B Golden Tape and Callback Truth Map tooling is implemented and enforces Scope/scenario/transform coverage, but official Callback visibility, captured Golden Tapes, resets, manual TWS orders and real commissions remain externally BLOCKED.
8. Safety Case verification now requires resolvable artifacts and independent Ed25519 Risk/Execution receipts. No online issuance path or Canary Permit exists; existing Outbox commands cannot be treated as authorized real IBKR writes.
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
22. macOS Keychain and guided runners reduce local secret/configuration risk but
    cannot install or accept third-party licenses, complete GUI login/2FA,
    provision accounts, obtain paid entitlements or issue independent receipts.
23. The local installer can validate and install a user-downloaded official TWS
    API ZIP only after explicit license attestation. It cannot prove download
    provenance, accept terms, install TWS, authenticate an account or approve 2FA.
24. External Acceptance counts are operational evidence summaries, not strategy
    profitability, safety certification or authorization to trade.
