# Security and adversarial threat model

## Protected assets

- brokerage account;
- cash and positions;
- API keys and account identifiers;
- strategy source code;
- historical research data;
- audit ledger;
- operator control endpoints.

## Threats and controls

### Prompt injection through news or filings

Threat: external text tells an LLM to ignore rules, reveal secrets, or place orders.

Controls:

- evidence is explicitly untrusted;
- blocked patterns are sanitized;
- agents have no broker tools;
- outputs are schema-validated;
- fabricated evidence IDs cause veto;
- deterministic risk remains authoritative.

### Duplicate order submission

Threat: retries, timeouts, callbacks, or process restarts submit the same order twice.

Controls:

- stable idempotency key;
- ledger reservation;
- broker-local duplicate check;
- order-state audit trail.

### Stale or corrupted prices

Controls:

- timezone-aware timestamps;
- quote age limit;
- positive bid/ask/last validation;
- ask cannot be below bid;
- no flatten without a fresh quote.

### Broker disconnect and nightly reset

Controls:

- connected state in account snapshot;
- fail-closed risk decision;
- callback and status reconciliation;
- no new order while disconnected.

### Strategy data leakage

Controls:

- separate `available_at` and event timestamps;
- backtester filters catalysts by availability time;
- next-bar entry after a signal;
- benchmark and symbol histories truncated at each decision.

### Unauthorized remote control

V1 API has no remote authentication and must remain on localhost. Any remote deployment requires TLS, authentication, network allowlists, CSRF protection, audit logs, and secret rotation.

### Live activation error

Controls:

- strict live config validator;
- live requires IBKR broker;
- live requires human approval;
- paper auto-submit must be false;
- LLM sizing is forbidden.

## Remaining risks

- gap risk beyond stops;
- broker-side rejects and exchange halts;
- data-vendor timestamp errors;
- model risk and regime shifts;
- market impact not represented by simple slippage;
- local machine compromise.
