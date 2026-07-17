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
- decision inputs reject naive `as_of` rather than silently attaching UTC.

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

All POST routes are disabled by default. Enabling them requires a separate operator token, and Broker mutations additionally require Broker write capability. Read routes remain unauthenticated, so the API must remain on localhost. Any remote deployment still requires TLS, authenticated sessions, network allowlists, CSRF protection, actor audit, rate limits and secret rotation.

### Live activation error

Controls:

- the enum contains no `live_auto` value;
- `live_proposal` requires IBKR and human-approval policy but can never obtain Broker write capability;
- `paper_auto` is default-off and requires config flags, an independent token and a runtime-issued capability;
- LLM sizing is forbidden.

### Confused deputy inside the application

Threat: research, API, agent or orchestration code obtains a Broker object and invokes a write method outside its declared mode.

Controls:

- every public Broker write method requires `BrokerWriteCapability`;
- the capability factory issues it only to explicitly enabled paper modes;
- research, backtest, shadow and live proposal receive no write capability;
- API operator authorization and Broker authority are distinct checks;
- LLM agents receive neither the Broker nor its capability.

## Remaining risks

- gap risk beyond stops;
- broker-side rejects and exchange halts;
- data-vendor timestamp errors;
- model risk and regime shifts;
- market impact not represented by simple slippage;
- local machine compromise.
- incomplete process/OS isolation around the capability-bearing paper process;
- incomplete PIT/vendor correctness until M1.
