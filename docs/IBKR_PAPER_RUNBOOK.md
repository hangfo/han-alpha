# IBKR Paper runbook

## Preflight

1. Confirm `configs/paper.yaml` is loaded.
2. Confirm the port is Gateway paper `4002` or TWS paper `7497`; the observer rejects every other port.
3. Confirm the account is the paper account.
4. Confirm a dedicated API client ID.
5. Confirm TWS/IB Gateway socket clients are enabled.
6. Initially keep TWS API read-only while testing account and position retrieval.
7. Verify market-data permissions and data freshness.
8. Run `hanalpha ibkr-preflight --read-only-attested`; preserve its artifact.
9. Run `hanalpha doctor` and the test suite.
10. Run repeated zero-write Observer sessions before considering any order.

## Zero-write burn-in sequence

- Start TWS/IB Gateway and authenticate with supported 2FA.
- Run scoped `hanalpha ibkr-burn-in` captures with explicit
  `--capture-scenario`, then run `hanalpha ibkr-burn-in-evaluate`. Capture success
  is not acceptance; the evaluator returns exit code 2 for incomplete stability
  or scenario coverage.
- Labels schedule capture only. Build real event receipts with
  `hanalpha e1 event-receipt` and typed cases with `hanalpha e1 build-case`;
  restart/recovery/client-switch coverage is zero until the Case passes.
- Require `complete=true`; a TCP connection without all end markers is incomplete.
- Require `accepted_facts == written_facts`, `dropped_facts == 0` and no writer error.
- Track complete observations separately from consecutive stable Authority sessions; a divergent reset is not a stable vote.
- Test Completed Orders twice: `--completed-orders-scope api` for Han Alpha/API
  scope, then `--completed-orders-scope all` for manually submitted TWS order
  visibility. Treat them as different Scope hashes and separate Burn-in counters.
- IBKR documents that TWS Read-Only hides order information. Keep it enabled for
  account/position-only captures. For the explicit order-visibility matrix, disable
  that TWS setting, run `ibkr-preflight --order-visibility-attested`, and use only
  Han Alpha's observer-only client. Its write methods are structurally blocked.
- Preserve each generated `manifest.json`, `certificate.json` and `tape.sqlite3`.
- Restart the process and TWS/Gateway, then repeat across a reset boundary.
- Replay the fact tape and require the same reduced account/order/position/execution state.
- Run `ibkr-golden-tape-evaluate`; require callback reorder, duplicate, delayed
  commission/correction, redundant-status removal and open/completed overlap
  transform coverage across the corpus.
- Check `/health` and `/status`.
- Compare account values with TWS manually.
- Compare positions and open orders.
- Generate an order plan without submission.

## Isolated E1 Paper fixture

`scripts/e1_paper_fixture.py` is test infrastructure, not the Han Alpha Writer.
It refuses non-Paper ports, production write-enabled configuration, non-STK
instruments, fractional/multiple shares, more than USD 1,000 notional, ambiguous
accounts and client IDs outside 9100–9199. It has no global-cancel operation.

Create and execute exactly one Permit at a time. Never place account identifiers
or credentials in arguments:

```bash
.venv/bin/python scripts/e1_paper_fixture.py create-permit \
  --action PLACE --symbol SPY --quantity 1 --limit-price <REVIEWED_LIMIT> \
  --port 7497 --client-id 9100 --attest-paper

.venv/bin/python scripts/e1_paper_fixture.py execute \
  --permit <IMMUTABLE_PERMIT_PATH>
```

Modification/cancellation requires a new Permit bound to the exact fixture
Broker order ID and `E1FIX:` order ref. Position removal uses
`CLOSE_POSITION` and fails unless the Broker proves exactly one long share.
Each Permit is consumed before the write; an uncertain outcome is inspected and
never retried. Keep TWS API Read-Only enabled until the operator explicitly
chooses to run this fixture, then re-enable it after the bounded action.

Do not enable Paper submission until 30 observations, consecutive stability, Golden Tapes,
nightly reset, realtime Quote/calendar authority, durable writer, real cancel, bracket
recovery, Paper-account proof and a one-use Canary Permit are separately accepted. The
current M7-B.1 state does not meet that gate.

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
