# M6 execution plan: IBKR Paper observation and reality gap

Status: ACTIVE; local hardening complete, real Paper burn-in and adapter acceptance blocked
Owner: Codex
Date: 2026-07-20

## Locally delivered

- Read-only callback collector and append-only fact tape with session epochs.
- Snapshot Completeness Certificate with all required end markers and critical-error gating.
- Broker-native identity reducer for duplicate/out-of-order status, execution, commission and correction facts.
- Durable freeze authority, strict Unknown escrow, account cash fields and per-parent Protection Graph.
- Separate decision, reconciliation, execution and approval CLI entrypoints for the local Fake boundary.
- Shadow execution reality-gap decomposition for price, broker slippage, commission, missed fill and latency.
- Callback Queue single-writer, exact request barriers, clean drain and semantic completeness.
- Visibility scope hash, native order identity, field lattice and numeric correction ordering.
- M5 BrokerSnapshot adapter plus time-separated semantic snapshot consensus.
- Explainable Cash Bridge baseline epochs, two-stage approve/arm and durable fenced cancel.
- Partial-fill schedule, opportunity-cost and protection-ack reality gaps.

## BLOCKED real checks

- Official IBKR TWS Python API is not installed in the current environment.
- Neither standard local Paper port 4002 nor 7497 is listening.
- No authenticated callback tape, nightly reset, reconnect, order identity or account convergence evidence exists.
- Durable cancel is locally verified only against Fake Broker; real IBKR cancel and bracket recovery are not accepted. Therefore no Paper order may be sent.

## Next dependency order

1. Install the official API and start TWS/IB Gateway in Paper/read-only mode.
2. Capture repeated zero-write sessions and promote one sanitized tape to golden replay.
3. Run reconciliation burn-in across reconnect and reset boundaries.
4. Validate durable cancel against real Paper callbacks without creating exposure.
5. Validate bracket construction, transmit sequence and failure recovery without unattended submission.
6. Request separate authorization for one manually approved Paper bracket.
