# ADR 0009: Authority normalization and canary admission

Status: ACCEPTED

Date: 2026-07-26

## Context

M7-B mixed observation-specific request metadata with broker economic state:

- absolute execution-window timestamps were part of Visibility Scope identity;
- account and execution component hashes retained request IDs;
- `NetLiquidation` and `BuyingPower` were hashed together with exact cash truth;
- the dashboard's `paper_canary` label represented only runtime controls;
- an expired one-row-per-intent Arm could not be replaced.

The design failed closed, but two genuine Observer sessions could remain in separate
consensus buckets or produce different state hashes while the broker economic state
was unchanged.

## Decision

Use three independent artifacts:

1. `ObservationWindow` is the per-session envelope. It contains request IDs, epochs,
   session ID and absolute query times. Its hash proves observation independence.
2. `VisibilityScope.scope_hash` is a stable policy identity. It contains account
   hash, client visibility policy, query modes, completed-order policy and configured
   base currency, but no absolute request window.
3. Canonical Broker State removes request/session/callback metadata. Cash, orders,
   positions, executions, commissions and protection are exact components.
   `NetLiquidation` and `BuyingPower` are separate valuation observations.

Consensus requires exact component equality, an identical normalization policy and
valuation drift within a fail-closed 25 bps / 1 base-currency-unit budget. The
equivalence receipt explicitly says that this is a bounded observation difference;
it does not infer market causality.

The prior runtime gate is renamed `runtime_control`. `paper_canary` additionally
requires a fresh realtime Quote Capsule and an immutable external safety case for
burn-in, Golden Tapes, nightly reset, market calendar, real cancel, real bracket,
Paper-account proof, durable writer and a one-use permit. There is no local issuance
path that can manufacture those external facts.

Approval remains immutable. Arms are versioned and separately attributed. An
expired or superseded Arm can be replaced; claim consumes exactly one Active Arm in
the same transaction that claims the outbox command.

## Consequences

- Cross-session authority can progress without treating request metadata as money.
- Dynamic account valuation cannot silently rewrite cash authority.
- Real Paper Canary remains blocked until external evidence exists.
- Existing Arm rows migrate in place with explicit `LEGACY_UNKNOWN` actor evidence.
- Old normalized votes without a comparable receipt cannot establish new authority
  by replay alone.
- Infrastructure is frozen after M7-B.1 except for defects found by real Paper
  observation. New work should improve PIT Alpha evidence, broker truth, execution
  friction measurement or recovery evidence.
