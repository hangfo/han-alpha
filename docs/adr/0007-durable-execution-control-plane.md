# ADR 0007: Durable execution control plane

- Status: Accepted for M5
- Date: 2026-07-19
- Scope: decision-to-broker safety and crash recovery

## Context

An order is not a function call. Process death, network ambiguity, duplicate callbacks and broker restarts can occur between every local state change. Broker state is authoritative, while local state must remain sufficient to explain intent, reserve risk and recover without a second economic order.

## Decision

The decision plane emits one immutable, content-addressed Decision Capsule. It binds market/evidence snapshots, evidence review, strategy, signal, risk policy, risk decision and configuration. The execution plane accepts only this capsule plus a durable reservation and intent; it cannot invoke strategies, LLMs or reinterpret market data.

Capsule, active reservation, intent and submit outbox are committed atomically. Manual approval is a separate immutable artifact. A database lease issues monotonically increasing fencing tokens, and the Broker rejects stale writers. `client_order_key` is derived from economic order meaning and is the Broker idempotency key.

All Broker callbacks enter a unique inbox before the same transaction updates order, fill, position, cash and reservation projections. `SUBMISSION_UNKNOWN` is not retried. Reconciliation first queries Broker truth: an existing order binds and completes the outbox; only a snapshot newer than the uncertain claim may prove absence and permit requeue.

Startup is frozen until reconciliation converges. Broker-only orders, fill/position mismatch and missing protection are Critical and retain the freeze. Naked exposure duration is recorded. No-trade and reality-gap ledgers preserve rejected decisions and later replay/shadow/paper differences.

Emergency cancel/flatten remains an authenticated, risk-reducing legacy Broker path until the M6 IBKR command adapter implements durable cancel outbox semantics. New exposure submission has no direct Broker path.

## Consequences

- At-least-once command delivery has exactly-once economic effect under the Fake Broker contract.
- A crash can delay execution but cannot justify a blind duplicate submit.
- SQLite proves local semantics, not distributed database availability or IBKR behavior.
- Fake Broker validation authorizes M6 adapter work; it does not authorize unattended Paper or any live transmit.
