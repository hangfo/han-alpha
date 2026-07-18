# ADR 0004: research truth, protection, and promotion contract

- Status: Accepted for M3
- Date: 2026-07-18
- Scope: local research and deterministic historical replay

## Context

M2 can replay a portfolio, but strategy evidence is invalid if a late historical
revision can fill an old order, a risk stop is not an executable child order, or
the CLI still invokes the legacy verifier. M3 must first make the simulator able
to reject false evidence before adding strategy families.

## Decisions

1. Knowledge events and tradable market events are distinct. A revision updates
   future research context but never enters exchange matching. A tradable bar
   must be an initial source revision and its market time cannot precede the order.
2. Candidate identity is content-addressed. The engine sorts by stable candidate
   ID and rejects duplicates; caller iteration order cannot change decisions.
3. Every accepted long entry requires a protective stop. Entry fills create
   reduce-only stop children and, when configured, target children in an OCO
   group. Partial entry fills receive protection for the filled quantity.
4. Research strategies receive an immutable `ResearchContext` assembled by the
   engine adapter. They cannot query DuckDB, the wall clock, secrets, or Broker.
5. `hanalpha backtest` uses the M2/M3 replay and experiment path. The old engine
   is exposed only as `legacy-backtest` during migration.
6. Experiment promotion is not a generic state transition. It requires a frozen
   preregistration, unused research budget, reproducible artifacts, positive
   post-cost OOS evidence, robustness gates, and explicit independent approval.
7. Statistical diagnostics are rejection tools, not Alpha certificates. DSR,
   PBO, bootstrap intervals, walk-forward and multiple-testing corrections must
   report insufficient sample or invalid assumptions instead of manufacturing a
   pass.
8. Monetary portfolio events emit balanced debit/credit journal entries. The
   FIFO lot view remains a derived operational view.

## Corporate-action boundary

The current frozen fixture provides only an atomic action event. M3 will prevent
revised actions from being applied twice and define announcement, entitlement,
effective, settlement and revision phases. It will not infer ex-date ownership
or payment timing absent source fields. Full dividend entitlement validation is
BLOCKED on an expanded licensed PIT contract and is not a reason to fabricate
cash flows.

## Strategy boundary

M3 implements only interpretable baselines: cross-sectional momentum,
volatility-controlled slow trend, and a typed PEAD candidate that refuses to
trade without a point-in-time earnings announcement and expectations snapshot.
No five-minute Alpha, LLM selection, Broker integration, or live action is in
scope.

## Consequences

- Correctness work precedes attractive performance charts.
- Failed and rejected decisions become first-class evidence.
- A promoted strategy means the configured gates passed on the registered data;
  it still does not establish future profitability.
