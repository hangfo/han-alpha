# M5 execution plan: durable execution control plane and Fake Broker

Status: COMPLETE LOCALLY
Owner: Codex
Date: 2026-07-19

## Delivered

- M4 WP0 hardening: raw Responses parsing, backend quote resolution, fully bound reviews, corrected fixed-set ablation, complete cache configuration, deterministic expiry, scoped contradictions, atomic finalization and Provider usage audit.
- Promotion authority now requires a TEST non-counterfactual with actual fills, time in market and benchmark-relative evidence.
- Runtime Decision Plane uses the M4 snapshot/review contract and freezes a Decision Capsule; new exposure never calls the legacy Broker directly.
- Atomic capsule/reservation/intent/outbox staging, durable manual approval, economic idempotency keys and expiring reservations.
- Single-writer lease and Broker-enforced fencing token.
- Persistent fault-injectable Fake Broker, event inbox, order/fill/position/cash projections, Broker tape, late commission and Fill/Cancel race handling.
- Startup/continuous reconciliation, unknown-submit resolution, Broker-only/local-only/fill/position/protection discrepancy classification and persistent freeze.
- No-trade, reality-gap and naked-exposure ledgers.
- Adversarial recovery tests covering transaction failpoints, restart, duplicate and out-of-order-equivalent callbacks, partial fill, split brain, accepted/dropped response, missing protection and projection rebuild.
- Review hardening added persistent Freeze Tickets, pre-submit lease revalidation and early broker fence publication, strict post-claim Unknown absence, discovered-order binding, Decimal cash, account-field reconciliation, per-parent STOP/TARGET Protection Graph, formal approval API/CLI and authoritative reservation-aware capacity.

## Explicit boundary

M5 uses no real Provider, vendor or Broker. The durable Fake Broker proves repository-owned semantics only. IBKR Paper connectivity, callbacks, bracket transmit, session reset and shadow-vs-paper reality-gap population remain M6 and are BLOCKED until an authenticated Paper environment is explicitly used.

## Verification

Canonical results are recorded in `docs/VERIFICATION_REPORT.md`. Required commands are `./scripts/preflight.sh` and `./scripts/verify_all.sh`.
