# Architecture

## Design laws

1. Data and evidence are untrusted until validated.
2. Availability time is separate from event time.
3. LLMs are read-only researchers.
4. Risk and execution are deterministic.
5. Broker state is authoritative for positions and orders.
6. The ledger is append-only.
7. Every external dependency can fail closed.
8. Paper and live configurations are physically and logically separate.

## Components

### Data plane

- MarketDataProvider protocol.
- Synthetic provider for direct local execution.
- Planned providers for Polygon/Databento, SEC EDGAR, and FRED/ALFRED.
- Bar and quote validators reject impossible values and naive timestamps.

### Feature plane

- SMA, rolling high/low, ATR, RSI, relative strength, average dollar volume, volume z-score.
- No feature reads data after the decision timestamp.

### Strategy plane

- Breakout.
- Trend pullback.
- Event continuation.
- Each strategy produces a Signal, never an order.

### Agent plane

- Evidence agent validates point-in-time evidence coverage.
- Market-alignment agent checks regime compatibility.
- Skeptic agent searches for stale evidence, low confidence, and prompt injection.
- Optional LLM agent receives sanitized evidence and cannot access broker functions.

### Risk plane

- Position size is limited by per-trade risk, symbol weight, order notional, buying power, regime multiplier, and quote price.
- Approval checks daily loss, drawdown, gross exposure, number of positions, sector exposure, liquidity, earnings blackout, stale quotes, broker health, and duplicate idempotency.

### Execution plane

- SimulatedBroker provides conservative adverse slippage, commissions, protection orders, cancel-all, and flatten-all.
- IBKRBroker uses the official TWS API and bracket orders.
- Order and execution callbacks are converted to internal OrderEvent records.

### Control plane

- FastAPI exposes health, status, manual cycle, signals, orders, audit events, freeze, unfreeze, cancel-all, and flatten-all.
- The API is localhost-only by default and has no remote authentication in V1.

### Audit plane

- SQLite WAL ledger records canonical JSON for signals, plans, orders, order events, fills, and idempotency keys.
- Production expansion should add cryptographic chain hashes and remote immutable backups.

## Failure behavior

- Market-data unhealthy -> freeze.
- Broker disconnected -> reject.
- Stale quote -> reject.
- LLM malformed output -> veto.
- Fabricated evidence ID -> veto.
- Duplicate idempotency key -> reject.
- Missing flatten quote -> do not guess; return error.
- Unknown regime -> no new risk.
