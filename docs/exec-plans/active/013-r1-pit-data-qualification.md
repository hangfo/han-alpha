# R1 execution plan: PIT Data Qualification

Status: R1-A QUALIFICATION AUTHORITY COMPLETE; R1-B SOURCE ACCEPTANCE BLOCKED
Owner: Codex and data owner
Started: 2026-07-26

## Objective

Qualify real data for a specific research use before ingestion or return
optimization. A vendor name, API response or adjusted-price series is not PIT
evidence by itself.

## Implemented local entry slice

- Typed source profiles for price, event and macro backtests.
- Fail-closed checks for license, local caching, revisions, stable identifiers,
  timezones and source timestamp semantics.
- Price checks cover delisted history, PIT universe, ticker history, corporate
  action availability, raw prices and halt/no-trade states.
- Event checks cover public acceptance time, original filing, amendments,
  historical CIK mapping and session classification.
- Macro checks cover vintages, release-time policy, revision dates and metadata
  history.
- `hanalpha pit qualify-source` emits an immutable report and exits nonzero while
  any required check is BLOCKED.
- `hanalpha pit vendor-preflight` reports only credential presence and never
  serializes credential values.
- Initial Massive, SEC EDGAR and FRED/ALFRED profiles are deliberately BLOCKED.
- Profiles cannot self-authorize: every VERIFIED check must resolve a typed,
  unexpired Artifact plus an independent Ed25519 Reviewer Receipt.
- Reports distinguish exploratory `RESEARCH_QUALIFIED` from
  `PROMOTION_QUALIFIED`; strategy promotion accepts only the latter.
- Vendor Preflight reports credential presence only. It never labels a source
  access-ready without license and entitlement evidence.
- Bounded live Probe commands preserve redacted, immutable SEC/Massive/FRED
  payloads and their observed/effective/ingested semantics.
- Probe audits produce typed, content-addressed Timestamp, Revision, Symbology
  and Survivorship evidence without converting unresolved availability semantics
  into PASS.
- Every Artifact must declare the exact `qualifies_checks` it supports; matching
  only the broad Artifact type is insufficient.

## Next external work

1. Select the exact vendor plan and obtain written cache/backtest/retention rights.
2. Configure credentials locally; never commit them.
3. Download a small bounded sample containing active, delisted, renamed, split,
   dividend, halt and revised records.
4. Preserve raw bytes and retrieval headers; reconcile against an independent source.
5. Prove `available_at` for every strategy-visible field.
6. Only after a QUALIFIED report, implement the production adapter and publish a
   content-addressed PIT snapshot.

## First research slate after qualification

- slow trend;
- cross-sectional momentum/breakout;
- PEAD/event continuation.

Promotion remains based on post-cost out-of-sample evidence, DSR/PBO, drawdown,
capacity, turnover, parameter/Regime stability and factor exposures, never the
largest in-sample CAGR.
