# Strategy specification

## Common contract

A strategy receives only:

- bars available by the current timestamp;
- benchmark bars available by the current timestamp;
- catalysts whose `available_at` is not later than the current timestamp;
- current decision time.

It returns a Signal or no signal. It cannot access cash, positions, broker APIs, or secrets.

## Breakout

Purpose: participate in persistent relative-strength trends.

Conditions:

- fast moving average above slow moving average;
- current price above prior rolling high plus an ATR buffer;
- positive relative strength versus the market benchmark;
- acceptable volume z-score.

Risk geometry:

- stop below entry by ATR multiple;
- target as an R multiple;
- regime must explicitly allow breakout.

Primary failure modes:

- late-cycle breakouts;
- earnings gaps;
- crowded momentum reversal;
- false breaks in weak breadth.

## Trend pullback

Purpose: enter an established trend after a controlled retracement.

Conditions:

- price above long trend average;
- prior close at or below short average;
- current close recovers above short average;
- RSI below an overbought ceiling;
- relative strength not materially negative.

Primary failure modes:

- trend transition mistaken for pullback;
- sector-wide de-rating;
- gap through stop.

## Event continuation

Purpose: capture post-event expectation revisions.

Conditions:

- catalyst is available by decision time;
- catalyst score exceeds threshold;
- catalyst is fresh;
- direction is positive;
- price relative strength is not materially negative;
- evidence IDs are complete.

Primary failure modes:

- recycled old news;
- narrative without estimate revision;
- event already fully priced;
- incorrect entity mapping;
- filing timestamp or embargo errors.

## Research extensions

Future strategies must be added as separate modules, not hidden conditions inside existing strategies. Candidates:

- earnings estimate revision drift;
- industry supply-chain bottleneck propagation;
- medium-term cross-sectional momentum;
- volatility-controlled trend;
- catalyst plus analyst revision confirmation.
