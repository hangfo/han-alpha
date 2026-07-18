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

### Evidence plane

- Immutable documents carry observed/effective/available/ingested time and exact source quotes.
- The configured deterministic or strict-schema Responses extractor produces claims or abstains; it cannot produce candidates, quantities, risk or Broker commands.
- Candidate review binds entity, candidate, decision, Evidence Snapshot and reviewer configuration, and can only return NO_OBJECTION, VETO or ABSTAIN.
- The earlier AgentCommittee remains isolated test scaffolding and is not in the runtime order-authority chain.

### Risk plane

- Position size is limited by per-trade risk, symbol weight, order notional, buying power, regime multiplier, and quote price.
- Approval checks daily loss, drawdown, gross exposure, number of positions, sector exposure, liquidity, earnings blackout, stale quotes, broker health, and duplicate idempotency.

### Execution plane

- M2 `PortfolioReplayEngine` consumes published PIT frames through a deterministic cursor, then uses shared decision identities, atomic portfolio reservations, explicit order states and a replaceable historical exchange adapter.
- The local Decimal ledger records cash, FIFO lots, commissions, aggregate open risk, splits, dividends and delisting recovery; experiment manifests and artifact hashes make replay results reproducible.
- M5 freezes a Decision Capsule and atomically writes capacity-checked Risk Reservation, Execution Intent and Outbox. New exposure never calls a Broker from the decision loop.
- A single writer holds a fenced lease. Persistent Fake Broker fault scenarios feed a deduplicating Inbox and transactional order/fill/position/cash projections.
- Startup reconciliation is frozen until Broker truth converges; unknown submits, broker-only orders, mismatched fills/positions and missing protection have explicit recovery/freeze behavior.
- The IBKR adapter is M6 scope and is not validated by the Fake Broker result. Authenticated emergency cancel/flatten remains a direct risk-reducing compatibility path until M6 adds durable cancel commands.

### Control plane

- FastAPI exposes health, status, manual cycle, signals, orders, audit events, freeze, unfreeze, cancel-all, and flatten-all.
- The API is localhost-only by default and has no remote authentication in V1.

### Audit plane

- SQLite WAL ledger records canonical JSON for signals, plans, orders, order events, fills, and idempotency keys.
- Dedicated M4/M5 stores retain Provider attempts, capsules, approvals, reservations, outbox/inbox, reconciliation discrepancies, Broker tape, no-trade, reality-gap and naked-exposure records.
- Production expansion should add cryptographic chain hashes and remote immutable backups.

## Failure behavior

- Market-data unhealthy -> freeze.
- Broker disconnected -> reject.
- Stale quote -> reject.
- LLM malformed output or unresolved quote -> fail closed and persist failed attempt.
- Fabricated claim or cross-snapshot review -> reject.
- Duplicate idempotency key -> reject.
- Submission outcome unknown -> reconcile before any retry.
- Broker-only order, position/fill mismatch or missing protection -> persistent freeze.
- Missing flatten quote -> do not guess; return error.
- Unknown regime -> no new risk.
