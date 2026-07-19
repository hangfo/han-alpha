# M6 execution plan: IBKR Paper observation and reality gap

Status: ACTIVE; local observer kernel complete, real Paper burn-in blocked
Owner: Codex
Date: 2026-07-19

## Locally delivered

- Read-only callback collector and append-only fact tape with session epochs.
- Snapshot Completeness Certificate with all required end markers and critical-error gating.
- Broker-native identity reducer for duplicate/out-of-order status, execution, commission and correction facts.
- Durable freeze authority, strict Unknown escrow, account cash fields and per-parent Protection Graph.
- Separate decision, reconciliation, execution and approval CLI entrypoints for the local Fake boundary.
- Shadow execution reality-gap decomposition for price, broker slippage, commission, missed fill and latency.

## BLOCKED real checks

- Official IBKR TWS Python API is not installed in the current environment.
- Neither standard local Paper port 4002 nor 7497 is listening.
- No authenticated callback tape, nightly reset, reconnect, order identity or account convergence evidence exists.
- Durable cancel and real bracket recovery are not complete; therefore no Paper order may be sent.

## Next dependency order

1. Install the official API and start TWS/IB Gateway in Paper/read-only mode.
2. Capture repeated zero-write sessions and promote one sanitized tape to golden replay.
3. Run reconciliation burn-in across reconnect and reset boundaries.
4. Implement durable cancel in the same outbox/single-writer authority.
5. Validate bracket construction and failure recovery without unattended submission.
6. Request separate authorization for one manually approved Paper bracket.
