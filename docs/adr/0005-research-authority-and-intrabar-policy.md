# ADR 0005: research authority and conservative intrabar policy

- Status: Accepted as M3 closeout amendment
- Date: 2026-07-18
- Scope: experiment authorization, promotion, counterfactual execution and OHLC ambiguity

## Context

The first M3 implementation made preregistration and promotion explicit, but a
caller could still report that budget, robustness, artifacts and independent
approval had passed. Counterfactuals were manifests rather than executed runs.
An entry fill created protection only for a later bar, even when the entry bar's
low had already crossed the stop. Those are authority and chronology defects,
not statistical refinements.

## Decisions

1. A frozen protocol is registered before a trial. SQLite allocates each trial
   under `BEGIN IMMEDIATE` and binds protocol, research program, parameter hash,
   window role and a retry-safe idempotency key. A manifest cannot register
   without consuming a matching allocation.
2. Promotion booleans are not a public API. Promotion derives from registered
   artifact hashes, the result, protocol thresholds, a signed offline validation
   assessment and a separately signed independent approval. The researcher
   cannot approve their own research program.
3. Counterfactuals execute through the same replay runner. Cost stress changes
   the actual exchange cost policy; delay stress buffers actual proposals; every
   variant consumes a registry allocation and links to its parent.
4. When an entry and its bracket share one OHLC bar, protection is eligible on
   that bar and ambiguity is resolved adversely: stop before target. Same-bar
   matching is restricted to newly created reduce-only protection.
5. `average_gross_exposure` is an observation mean;
   `time_weighted_exposure_ratio` is duration-weighted; `time_in_market` is the
   duration share with nonzero exposure. They are no longer aliases.
6. Cash entries, balanced journal entries and lots are separate immutable JSONL
   artifacts in every experiment bundle.

## Statistical amendments

- Dependent returns use a deterministic moving-block bootstrap option.
- Leakage purging accepts explicit information-start and label-end intervals;
  bar-count purge remains a convenience only when the label horizon is known.
- DSR/PBO remain fail-closed diagnostics. Trial-family accounting now comes from
  the persistent research program, not an in-memory counter.

## Consequences

Retries do not spend research budget twice, but a distinct logical experiment
does. Signed files are an auditable local authority mechanism, not a claim of a
hardware-backed institutional approval system. Production key custody and role
provisioning remain later operational work.

