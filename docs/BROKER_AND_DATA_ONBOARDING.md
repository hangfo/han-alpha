# Broker and real-data onboarding

Updated: 2026-07-30

## Current local result

The local Broker environment now reports:

```text
TWS Paper installed and authenticated: true
official ibapi importable: true (10.48.1)
localhost:4002 listening: false
localhost:7497 listening: true
IBKR_ACCOUNT stored in macOS Keychain: true
E1 API empty_account sessions: 5/5
MASSIVE_API_KEY configured: true
FRED_API_KEY configured: true
SEC_USER_AGENT configured: true
TWS API Read-Only disabled for bounded Paper fixture: true
SPY real-time market-data entitlement in current API session: false
```

TWS Server Version 225, the single authenticated managed Paper account, account
summary, positions, API completed/open orders and executions were observed through
the official API without printing the identifier or persisting it outside
Keychain. E1-B is
still `BLOCKED_EXTERNAL_RIGHTS` before `static_position`: the quote-bound fixture
resolves the unique SPY contract but TWS does not provide eligible real-time
bid/ask/last data. The remaining matrix also requires genuine Paper
positions/orders and bounded restart, recovery, nightly-reset and client-switch
events. A bounded SEC probe was made on 2026-07-30; FRED and Massive were
blocked before network, and no Broker write was made.

Credential presence is not source acceptance. Every external action now requires
an immutable zero-incremental-cost receipt. IBKR regulatory snapshots are
forbidden; streaming quotes require an attested existing subscription. SEC is
limited to two proof requests with a 0.5 second inter-request delay. Massive
requires an explicit `BASIC_FREE` or `EXISTING_FIXED_SUBSCRIPTION` plan plus an
existing-entitlement attestation. FRED/ALFRED is blocked before network pending
review of the current API/content terms for software, AI and storage use.

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

This Apple Silicon Mac should use TWS Latest plus the current Mac/Unix API Latest.
As of 2026-07-26, API Stable 10.45 does not include Python for Mac/Unix, while
Latest 10.48 does. Use the official pages and re-check the displayed versions:

- <https://www.interactivebrokers.com/en/trading/download-tws.php?p=latest>
- <https://interactivebrokers.github.io/>
- <https://ibkrcampus.com/campus/ibkr-api-page/twsapi-doc/>
- <https://ibkrcampus.com/campus/trading-lessons/accessing-the-tws-python-api-source-code/>
- <https://ibkrcampus.com/campus/trading-lessons/installing-configuring-tws-for-the-api/>

The download requires accepting IBKR's API license and therefore remains a user
action. After personally accepting it and downloading the official Mac/Unix ZIP:

```bash
cd /Users/rich/han-alpha
source .venv/bin/activate
hanalpha local-onboard install-ibapi \
  --archive ~/Downloads/twsapi_macunix.1048.01.zip \
  --license-accepted
python -m pip show ibapi
python -c 'from ibapi.client import EClient; print("ibapi import OK")'
```

Do not install an unrelated package merely because it uses the `ibapi` name.
Record the official download version and match it to TWS/IB Gateway.

In TWS/IB Gateway:

1. log into the Paper account with normal GUI/2FA;
2. enable ActiveX and Socket Clients;
3. use Paper port 7497 for TWS or 4002 for Gateway unless deliberately changed;
4. keep API Read-Only enabled for account/position-only captures; disable it only
   for the separately audited bounded Paper fixture/manual-order phase;
5. use a dedicated client ID;
6. enable detailed API logs for the bounded burn-in window;
7. verify account and market-data entitlements manually.

TWS Read-Only is an operator configuration and is not trusted as remotely
introspectable. IBKR documents that order information is unavailable while that
setting is enabled. Therefore ALL-Scope manual-order visibility uses a distinct
operator attestation after disabling the TWS setting; Han Alpha still instantiates
an observer-only client whose order-mutating methods raise `PermissionError`.

Before the first fixture write, confirm a real-time US equity Level 1 entitlement
is active for the Paper session. Han Alpha refuses delayed data for a filling
test. A successful bounded sequence begins with:

Official requirements and the Paper/live sharing rules are maintained at
<https://www.interactivebrokers.com/campus/ibkr-api-page/market-data-subscriptions/>.
In Client Portal use **Settings → Trading Platform → Market Data Subscriptions**,
enable the Market Data API acknowledgement, and either subscribe the relevant
live username or share its market data with the Paper username. SPY is listed by
IBKR under US Network B; the exact package, subscriber status, fees and account
minimums must be reviewed by the account owner before purchase.

```bash
python scripts/e1_paper_fixture.py capture-quote \
  --symbol SPY --port 7497 --client-id 9100 --attest-paper
```

`REALTIME_MARKET_DATA_ENTITLEMENT_REQUIRED` is a hard stop. Do not manually
construct a permit or substitute a delayed/browser price. After a Quote Capsule
is produced, `start-lifecycle` records the Broker baseline; PLACE/MODIFY/CANCEL/
CLOSE permits must remain bound to that capsule and lifecycle. The `execute`
command requires `--lifecycle-id`; there is no lifecycle-free fixture-write path.
`finish-lifecycle` passes only after no `E1FIX:` order remains and the position
returns to baseline.

Store the Paper account in Keychain. When exactly one Paper account is logged in,
prefer automatic redacted discovery:

```bash
hanalpha local-onboard discover-ibkr-account

# Manual stdin entry remains available if discovery is not applicable.
hanalpha local-onboard set-secret --name ibkr-account
```

Paper environment, host, TWS port `7497` and client ID `41` remain non-secret
local configuration. Client ID `41` is passed by Han Alpha during connection; do
not enter it into TWS's optional **Master API Client ID** field. Leave that field
blank unless a separately reviewed multi-client design requires one. The complete
novice-safe installation, 2FA, socket and
attestation sequence is in
`docs/v2-plan/21_E1B_R1B_ISSUE4_REVIEW_AND_OPERATOR_GUIDE_ZH.md`.

Then:

```bash
hanalpha local-onboard ibkr --read-only-attested --github-summary

# The runner is resumable and captures at most one verified Session per
# invocation, then recomputes and registers its Scope Corpus. Dry-run performs
# no Broker request.
hanalpha e1 run --scope api --dry-run --github-summary

hanalpha ibkr-preflight --read-only-attested

# Full order-state observation requires TWS API Read-Only to be unchecked while
# Han Alpha remains a structurally zero-write client.
hanalpha e1 run --scope api --execute --order-visibility-attested --github-summary

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

# Massive is still blocked unless the operator can truthfully select one:
hanalpha r1 run --source massive --execute --max-new-cost 0 \
  --massive-plan BASIC_FREE --existing-entitlement-attested --github-summary

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
