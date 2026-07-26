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
4. keep API Read-Only enabled for E1;
5. use a dedicated client ID;
6. enable detailed API logs for the bounded burn-in window;
7. verify account and market-data entitlements manually.

TWS Read-Only is an operator configuration and is not trusted as remotely
introspectable. The Preflight records an explicit attestation, and Broker write
capability remains disabled in Han Alpha regardless.

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
hanalpha ibkr-preflight --read-only-attested

hanalpha ibkr-burn-in \
  --state .state/ibkr-observer.sqlite3 \
  --control .state/execution-control.sqlite3 \
  --sessions 30 \
  --completed-orders-scope api \
  --output .state/burn-in/api

hanalpha ibkr-burn-in \
  --state .state/ibkr-observer.sqlite3 \
  --control .state/execution-control.sqlite3 \
  --sessions 10 \
  --completed-orders-scope all \
  --output .state/burn-in/all
```

`all` is a different Scope and is intended to test manually submitted TWS
Completed Orders. Its votes never count toward the `api` Scope.

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
SEC_USER_AGENT=HanAlphaResearch contact@example.com
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

Fail-closed source qualification:

```bash
hanalpha pit qualify-source \
  --profile configs/data-sources/massive-price-profile.json \
  --output .state/pit/qualifications/massive.json
```

The repository templates intentionally exit with code 2 until all required
license, timestamp, survivorship and revision evidence is VERIFIED. Only then
should a vendor adapter publish a real PIT snapshot or run a return experiment.
