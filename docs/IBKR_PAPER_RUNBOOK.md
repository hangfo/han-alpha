# IBKR Paper runbook

## Preflight

1. Confirm `configs/paper.yaml` is loaded.
2. Confirm the port is Gateway paper `4002` or TWS paper `7497`, unless intentionally customized.
3. Confirm the account is the paper account.
4. Confirm a dedicated API client ID.
5. Confirm TWS/IB Gateway socket clients are enabled.
6. Initially keep TWS API read-only while testing account and position retrieval.
7. Verify market-data permissions and data freshness.
8. Run `hanalpha doctor`.
9. Run the test suite.
10. Start with one highly liquid symbol and very small simulated risk.

## Activation sequence

- Start TWS/IB Gateway and authenticate with supported 2FA.
- Start Han Alpha locally.
- Check `/health` and `/status`.
- Compare account values with TWS manually.
- Compare positions and open orders.
- Generate an order plan without submission.
- Enable paper submission only after manual review.
- Confirm parent, target, and stop IDs in TWS.

## Daily operation

- Check broker connection and market-data freshness.
- Check previous-day reconciliation.
- Check kill switch is in expected state.
- Review permitted strategies and risk regime.
- Inspect rejected trades as carefully as accepted trades.
- At close, reconcile positions, fills, commissions, and shadow slippage.

## Incident actions

### Unexpected order

- Freeze new orders.
- Cancel all open orders.
- Compare IBKR open orders with ledger.
- Do not restart until idempotency and order state are understood.

### Position mismatch

- Freeze.
- Treat IBKR as authoritative.
- Refresh positions and executions.
- Correct local projections through a reconciliation event, never by deleting history.

### Data outage

- Freeze new orders.
- Do not flatten without fresh quotes unless using a deliberate emergency manual procedure in TWS.

### Broker disconnect

- Freeze new orders.
- Wait for reconnection callbacks.
- Re-request positions, account summary, market data, and open orders where required.
