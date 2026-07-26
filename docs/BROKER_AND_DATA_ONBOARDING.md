# Broker and real-data onboarding

Updated: 2026-07-26

## Current local result

The repository environment currently reports:

```text
official ibapi importable: false
localhost:4002 listening: false
localhost:7497 listening: false
IBKR_ACCOUNT configured: false
MASSIVE_API_KEY configured: false
FRED_API_KEY configured: false
SEC_USER_AGENT configured: false
```

This is a credential/environment BLOCKED state, not a code failure. No Broker or
vendor request was made.

The preferred local secret store is macOS Keychain. Secret values are read from
stdin by the onboarding CLI, are never placed in command arguments, and are not
printed. Environment variables and an ignored `.env` remain compatibility
fallbacks:

```bash
hanalpha local-onboard set-secret --name ibkr-account
hanalpha local-onboard set-secret --name sec-user-agent
hanalpha local-onboard set-secret --name fred-api-key
hanalpha local-onboard set-secret --name massive-api-key

# Optional one-time migration after reviewing the ignored local file.
hanalpha local-onboard migrate-env --env-file .env --scrub
```

Never paste values into chat, Issue comments, command arguments, screenshots or
committed files.

## Install the official IBKR stack on macOS

Use the current matching Stable/Offline TWS or IB Gateway and TWS API from IBKR.
IBKR documents Python 3.11+ as supported and recommends matching TWS/API versions:

- <https://ibkrcampus.com/campus/ibkr-api-page/twsapi-doc/>
- <https://ibkrcampus.com/campus/trading-lessons/accessing-the-tws-python-api-source-code/>
- <https://ibkrcampus.com/campus/trading-lessons/installing-configuring-tws-for-the-api/>

The download requires accepting IBKR's API license and therefore remains a user
action. After downloading the Mac/Unix archive:

```bash
cd ~/Downloads
unzip twsapi_macunix.*.zip
source /Users/rich/han-alpha/.venv/bin/activate
cd <unzipped-directory>/IBJts/source/pythonclient
python setup.py install
python -m pip show ibapi
python -c 'from ibapi.client import EClient; print("ibapi import OK")'
```

Do not install an unrelated package merely because it uses the `ibapi` name.
Record the official download version and match it to TWS/IB Gateway.

In TWS/IB Gateway:

1. log into the Paper account with normal GUI/2FA;
2. enable ActiveX and Socket Clients;
3. use Paper port 7497 for TWS or 4002 for Gateway unless deliberately changed;
4. keep API Read-Only enabled for account/position-only captures;
5. use a dedicated client ID;
6. enable detailed API logs for the bounded burn-in window;
7. verify account and market-data entitlements manually.

TWS Read-Only is an operator configuration and is not trusted as remotely
introspectable. IBKR documents that order information is unavailable while that
setting is enabled. Therefore ALL-Scope manual-order visibility uses a distinct
operator attestation after disabling the TWS setting; Han Alpha still instantiates
an observer-only client whose order-mutating methods raise `PermissionError`.

Configure `.env` locally without committing it:

```dotenv
HANALPHA_ENV=paper
HANALPHA_CONFIG_PATH=configs/paper.yaml
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=41
IBKR_ACCOUNT=<paper-account>
```

Then:

```bash
hanalpha local-onboard ibkr --read-only-attested --github-summary

# The runner is resumable and captures at most one verified Session per
# invocation, then recomputes and registers its Scope Corpus. Dry-run performs
# no Broker request.
hanalpha e1 run --scope api --dry-run --github-summary

hanalpha ibkr-preflight --read-only-attested

hanalpha ibkr-burn-in \
  --state .state/ibkr-observer.sqlite3 \
  --control .state/execution-control.sqlite3 \
  --sessions 30 \
  --completed-orders-scope api \
  --capture-scenario empty_account \
  --output .state/burn-in/api

# For ALL/manual-order visibility only: disable TWS Read-Only, keep Han Alpha's
# observer-only client, and record the distinct preflight.
hanalpha ibkr-preflight --order-visibility-attested

hanalpha ibkr-burn-in \
  --state .state/ibkr-observer.sqlite3 \
  --control .state/execution-control.sqlite3 \
  --sessions 10 \
  --completed-orders-scope all \
  --capture-scenario manual_order \
  --output .state/burn-in/all

hanalpha ibkr-burn-in-evaluate \
  --input .state/burn-in/api \
  --output .state/burn-in/api-corpus.json

hanalpha ibkr-burn-in-evaluate \
  --input .state/burn-in/all \
  --output .state/burn-in/all-corpus.json

hanalpha ibkr-golden-tape-evaluate \
  --input .state/burn-in/golden \
  --output .state/burn-in/golden-tape-corpus.json
```

`all` is a different Scope and is intended to test manually submitted TWS
Completed Orders. Its votes never count toward the `api` Scope. The two sample
capture commands are not the complete matrix: use separate immutable sessions for
process/TWS restart, network recovery, nightly reset and client-ID switching.
`capture` preserves facts; only `evaluate` can return PASS.

## Real PIT source order

### 1. Massive US equities

Use for unadjusted daily/minute bars, trades/quotes where licensed, ticker
reference, delisted symbols and corporate actions. Massive documents Flat Files
as unadjusted and REST adjusted data as a separate policy:
<https://massive.com/docs/flat-files/stocks/overview>.

Before purchase, confirm in writing:

- systematic backtesting and local caching rights;
- retention after subscription termination;
- delisted/ticker-history coverage;
- corporate-action announcement/availability semantics;
- revision/backfill notification;
- the exact historical depth and quote/trade entitlement.

Configure `MASSIVE_API_KEY`; `POLYGON_API_KEY` remains a compatibility alias.

### 2. SEC EDGAR

SEC's submissions and XBRL APIs do not require an API key and publish nightly bulk
archives, but automated access must use a descriptive User-Agent and comply with
SEC access policy:
<https://www.sec.gov/search-filings/edgar-application-programming-interfaces>.

Configure:

```dotenv
SEC_USER_AGENT=HanAlphaResearch operations@your-real-domain.tld
```

Acceptance time, amendment lineage, historical CIK/ticker mapping and next
tradable session must still be proven on real accessions.

### 3. FRED/ALFRED

Use ALFRED vintages for historical decisions. FRED's latest revised value is not
what was known in the past:
<https://fred.stlouisfed.org/docs/api/fred/fred_vs_alfred.html>.
Vintage dates are available from:
<https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html>.

Configure `FRED_API_KEY`, then register a conservative release-time lag for any
series that lacks an authoritative intraday publication timestamp.

## Qualification commands

Credential presence:

```bash
hanalpha pit vendor-preflight
```

This reports `credentials_present_for`, never `ready_sources`. SEC identification
must include a project name and a non-placeholder contact email; only its SHA256
and the request-throttle policy hash are persisted.

Run bounded real probes only after configuring the corresponding local identity
or key:

```bash
hanalpha r1 run --source sec_edgar --dry-run --github-summary
hanalpha r1 run --source fred_alfred --dry-run --github-summary
hanalpha r1 run --source massive --dry-run --github-summary

# --execute is an explicit, bounded real network action. Start with SEC only
# after storing a descriptive User-Agent and reviewing provider terms.
hanalpha r1 run --source sec_edgar --execute --github-summary

hanalpha pit probe-source --source sec_edgar \
  --identifier 320193 \
  --output .state/pit/probes/sec

hanalpha pit probe-source --source fred_alfred \
  --identifier CPIAUCSL \
  --output .state/pit/probes/fred

hanalpha pit probe-source --source massive \
  --identifier AAPL \
  --output .state/pit/probes/massive

hanalpha pit audit-probe \
  --manifest <content-addressed-probe-manifest.json> \
  --output .state/pit/audits

hanalpha pit evidence-list
```

Probe failures are redacted before reaching the CLI, including HTTP request URLs
that may otherwise contain API keys. The probe preserves literal response bytes,
selected safe headers and normalized JSON as three independently hashed layers;
normalization never replaces transport evidence. A successful Probe proves only
bounded payload access. Audit Artifacts declare the exact `qualifies_checks`
they can support; a shared Artifact type cannot satisfy unrelated checks.

Fail-closed source qualification:

```bash
hanalpha pit qualify-source \
  --profile configs/data-sources/massive-price-profile.json \
  --registry .state/evidence-artifacts.sqlite3 \
  --output .state/pit/qualifications/massive
```

The repository templates intentionally exit with code 2 until all required
license, timestamp, survivorship and revision evidence resolves to registered,
unexpired artifacts with independent Ed25519 Reviewer Receipts. A profile edited
to say `VERIFIED` cannot qualify itself. Only `PROMOTION_QUALIFIED` data may publish
a promotion-grade PIT snapshot or enter R2.

Runtime configuration contains public keys only:

```dotenv
HANALPHA_SAFETY_CASE_PUBLIC_KEYS={"risk-key":"<base64-raw-ed25519-public-key>","execution-key":"<base64-raw-ed25519-public-key>"}
HANALPHA_ARTIFACT_REGISTRY_PATH=.state/evidence-artifacts.sqlite3
```

Private reviewer keys must remain offline and outside the repository, runtime
environment and application database.

## Runner status contract

External runners use stable process classes:

```text
0  PASS
1  FAILED_CODE
20 BLOCKED_HUMAN_ACTION
21 BLOCKED_EXTERNAL_RIGHTS
```

`BLOCKED_HUMAN_ACTION` means the next step is an installation, license acceptance,
login/2FA, local secret entry or bounded scenario performed by the user.
`BLOCKED_EXTERNAL_RIGHTS` means payload access may work but written rights and/or
independent Review are still missing. Neither state may be relabeled as a code
success.
