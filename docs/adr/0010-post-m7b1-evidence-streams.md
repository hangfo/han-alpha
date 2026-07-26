# ADR 0010: post-M7-B.1 work is named by evidence stream

Status: accepted

## Decision

M7-B.1 ends the architecture-expansion phase. There will be no M7-B.2.
Subsequent work is named by the external fact it must establish:

- `E1 Broker Truth Readiness`: zero-write IBKR Preflight, scoped Observer burn-in,
  immutable session artifacts and Golden Tape replay.
- `R1 PIT Data Qualification`: license, retention, lineage, availability-time,
  survivorship and revision qualification before real ingestion.
- `E2 Canary Authorization`: independently verified Safety Case, freshness
  propagation and one-use Permit bound to an exact intent.
- `E3 Paper Manual Execution`: durable IBKR writer, real cancel/bracket recovery
  and one-share manual Canary.
- `R2 Friction-aware OOS Evidence`: registered low-degree-of-freedom baselines,
  post-cost out-of-sample evidence and forward Shadow/Paper comparison.
- `M8 Live Proposal Review`: independent security, legal and operations review;
  still proposal-only.

E1 and R1 may proceed in parallel. E2 depends on accepted E1 evidence. E3 depends
on E2. R2 depends on qualified R1 data. M8 depends on E3 and R2 but never creates
an unattended live mode.

## Rationale

Milestone names should expose the missing truth, not imply that more framework
code creates readiness. The two current bottlenecks are independent:

1. whether the Broker facts and recovery behavior are trustworthy;
2. whether historical information was actually knowable and tradable at each
   decision time.

Keeping these streams separate prevents a passing backtest from authorizing an
order and prevents stable Broker connectivity from being mistaken for Alpha.

## Architecture freeze

New foundational services are allowed only when real Broker evidence, qualified
PIT data, measured execution friction or a recovery drill proves that the current
contracts cannot express reality. More trading Agents, reinforcement-learning
order logic, options, high-frequency execution, autonomous tuning and browser
trading controls are excluded.
