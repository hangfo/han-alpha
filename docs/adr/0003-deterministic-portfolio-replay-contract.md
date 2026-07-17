# ADR 0003: deterministic portfolio replay and experiment contract

- Status: Accepted for M2 implementation
- Date: 2026-07-18
- Scope: local historical/shadow simulation only

## Context

The V0.1 verifier is single-symbol and can create a next-bar position before the
current bar's equity mark. It also fills a stop near the stop price when the next
bar gaps through it. More importantly, separate backtest and runtime decision
paths would make discrepancies impossible to attribute.

M2 needs a falsification instrument, not a faster return calculator. The same
candidate identity, risk reservation and order transition contracts must be
reusable by historical, shadow and later paper adapters. Only the event cursor
and exchange adapter may differ.

## Decision

The replay core is an event-sourced modular monolith with these laws:

1. Every decision is bound to a published M1 `snapshot_id` and aware `as_of`.
2. A strategy receives typed PIT repository results, never storage handles.
3. Orders submitted at a decision cannot fill from the bar that created them.
4. Order transitions are explicit; duplicate fills and illegal transitions fail closed.
5. Buy limit fills never exceed the limit and sell limit fills never fall below it.
6. Stop-market gaps fill from the adverse opening price, not the stale stop.
7. Volume participation limits quantity and can produce partial fills; zero-volume
   and halted bars do not fill.
8. Cash, lots, commissions, reservations and corporate-action cash flows use an
   append-only ledger and reconcile after every event.
9. Experiment identity hashes data, code, config, universe, cost policy, metric
   schema and seed. Status changes are append-only and failed trials cannot be deleted.
10. Parity compares decision/signal/risk hashes; fill differences are expected and
    attributed to the exchange adapter.

Event ordering for one replay frame is fixed:

```text
newly available PIT facts
-> cancel stale open orders affected by corporate actions
-> apply corporate actions
-> expire orders whose eligibility window has closed
-> match previously accepted orders
-> apply fills
-> mark portfolio
-> generate candidates
-> reserve risk/cash atomically
-> accept or reject orders
-> persist decision/equity events
```

## Storage and boundaries

- The simulator is in-memory and deterministic; it is not the durable Broker control plane.
- SQLite stores immutable experiment manifests and append-only trial/artifact events.
- JSON/HTML result artifacts are derived outputs whose hashes are registered.
- PostgreSQL reservation/outbox, single-writer leases and Broker reconciliation remain M5 work.

## Explicit non-decisions

- Walk-forward, DSR/PBO and strategy selection are M3 evidence gates, not M2
  simulator mechanics.
- Agent expiry/delta gates are M4.
- Shadow-vs-IBKR fill twins are M6.
- No real data, LLM or Broker call is authorized by this ADR.

## Consequences

- Backtest and shadow can share deterministic decisions while using different fills.
- Conservation and no-look-ahead failures become testable at the event boundary.
- The extra event/manifest data is intentional audit cost.
- M2 can validate mechanics but cannot establish profitability or capacity.
