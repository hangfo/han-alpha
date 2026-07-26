# R2 strategy and LLM-agent positioning

Updated: 2026-07-26

## Decision

Do not transplant an autonomous multi-agent trader into Han Alpha. The latest
TradingAgents releases add useful engineering patterns—typed structured output,
checkpoint resume, decision logs and provider abstraction—but the project itself
describes performance as research-dependent and routes an approved proposal to a
simulated exchange. Those patterns do not prove PIT correctness, capacity or live
profitability:

- <https://github.com/TauricResearch/TradingAgents>
- <https://github.com/TauricResearch/TradingAgents/releases>
- <https://arxiv.org/abs/2412.20138>

Han Alpha already has stricter boundaries: LLMs may extract claims, cite evidence,
abstain and veto. They may not select position size, alter risk, issue a Permit or
call the Broker. R2 should measure whether the Evidence layer adds value over the
same deterministic signal with identical data and execution.

## Preregistered strategy slate

### Slow trend

- Monthly/weekly rebalance, broad liquid universe.
- Small fixed grid of lookbacks and volatility scaling.
- Primary hypothesis: compensated persistence after conservative turnover costs.
- Failure conditions: factor-adjusted return disappears, capacity is too small,
  or performance concentrates in one crisis/sector.

### Cross-sectional momentum / breakout

- Rank only instruments that were in the PIT universe.
- Explicit delay, volume participation, spread and tail-slippage scenarios.
- Neutralize or report market, size, sector and liquidity exposures.
- Failure conditions: delisted inclusion, halt/no-trade handling or conservative
  impact turns post-cost OOS return non-positive.

### PEAD / event continuation

- Signal clock begins at verified SEC acceptance and the next tradable session,
  never fiscal-period end or today's revised fundamentals.
- Amendment and CIK/ticker lineage are mandatory.
- Failure conditions: timestamp perturbation, amendment removal or delayed entry
  eliminates the effect.

## Required comparisons

Every candidate runs:

1. raw deterministic signal;
2. conservative historical friction;
3. Shadow/Paper-calibrated friction;
4. Evidence OFF;
5. Evidence ON with identical candidates and risk;
6. random signal;
7. time-permuted signal;
8. equal-weight PIT universe;
9. simple momentum benchmark.

Promotion requires positive post-cost OOS evidence, acceptable drawdown and tail
loss, DSR/PBO and multiple-testing gates, capacity and turnover, parameter/Regime
stability, factor attribution and a useful No-Trade opportunity-cost profile.
Largest CAGR is never the selection rule.

## Real-data entry

R2 cannot start until a source is `PROMOTION_QUALIFIED`. Massive Flat Files are
documented as unadjusted and UTC, SEC filings must retain public acceptance and
amendment lineage, and ALFRED real-time periods must replace today's FRED view:

- <https://massive.com/docs/flat-files/stocks/overview>
- <https://www.sec.gov/search-filings/edgar-application-programming-interfaces>
- <https://www.sec.gov/about/developer-resources>
- <https://fred.stlouisfed.org/docs/api/fred/realtime_period.html>
- <https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html>

Only bounded qualification samples are authorized before license and entitlement
receipts pass. No API purchase, large download or Provider call is implied by this
plan.
