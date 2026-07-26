# Data and permissions

## Minimum direct-run mode

No external data or credentials are required. Synthetic mode produces deterministic bars, quotes, and occasional catalysts.

## Paper environment inputs

### IBKR

Required:

- IBKR Pro account;
- approved and funded live account plus Paper Trading account;
- current stable TWS or IB Gateway;
- matching official TWS API;
- socket client access enabled;
- paper port and dedicated client ID;
- API market-data permissions for the paper username where needed;
- automation disclosure completed accurately if orders are automated.

Never provide passwords, 2FA codes, private keys, or full API keys in chat or source control.

### Market data

Recommended first production provider:

- minute bars;
- quotes with timestamps;
- corporate actions;
- symbol reference data;
- delisted securities for research;
- news timestamps and identifiers.

IBKR should remain the broker and execution source of truth, not the sole research-history database because historical requests are filtered and paced.

R1 requires a passing immutable source qualification before production ingestion:

```bash
hanalpha pit vendor-preflight
hanalpha pit qualify-source \
  --profile configs/data-sources/massive-price-profile.json \
  --registry .state/evidence-artifacts.sqlite3 \
  --output .state/pit/qualifications/massive
```

The repository Massive, SEC and FRED/ALFRED profiles intentionally remain BLOCKED
until license, retention, timestamp, revision and survivorship evidence is supplied
as registered immutable artifacts with an unexpired independent reviewer signature.
Caller-written `VERIFIED` text has no authority.

### SEC EDGAR

Use public submissions and company-facts APIs with a descriptive User-Agent and rate limiting. Store:

- CIK and ticker mapping;
- accession number;
- filing and acceptance timestamps;
- form type;
- original filing URL/reference;
- XBRL facts plus context;
- content hash.

### FRED/ALFRED

Store observation date, release date, vintage date, and retrieval time. Backtests must use the vintage that was known at the decision time.

### LLM

Required only for optional research review. The model receives sanitized evidence packets, never raw secrets or broker capabilities.

## Environment separation

- Paper config uses paper port, paper account, paper client ID, and separate ledger.
- Live config uses a different file, account allowlist, client ID, ledger, and human approval.
- There is no UI toggle that silently converts paper into live.
