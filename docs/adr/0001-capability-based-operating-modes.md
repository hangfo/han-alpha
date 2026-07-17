# ADR 0001: Capability-based operating modes

- Status: Accepted for M0
- Date: 2026-07-18
- Decision commit: `43b77f4`

## Context

The V0.1 configuration combined an `environment` string, a data-source `mode`, and `auto_submit_paper=true`. That representation could not prove which process was allowed to write to a broker. It also left local POST routes writable by default and allowed a simulated limit fill to cross its limit.

The protected property is not “the UI says paper.” It is: code without explicitly issued authority cannot reach a broker write method.

## Decision

The only operating modes are:

| Mode | Data clock | Broker write capability | Automatic submit |
|---|---|---:|---:|
| `research` | explicit historical/current `as_of` | never | never |
| `backtest` | explicit historical `as_of` | never | never |
| `shadow` | current decision clock | never | never |
| `paper_manual` | current decision clock | optional, explicit | never |
| `paper_auto` | current decision clock | required, explicit | allowed |
| `live_proposal` | current decision clock | never | never |

There is no `live_auto` enum value, configuration path, or runtime capability.

Broker writes require all of the following:

1. a mode that permits paper writes;
2. `execution.broker_write_enabled=true`;
3. a separate `HANALPHA_BROKER_WRITE_TOKEN` of at least 32 characters;
4. an in-process `BrokerWriteCapability` issued by the runtime policy factory and passed to the broker method.

Local API mutations require `execution.operator_api_enabled=true`, a distinct `HANALPHA_OPERATOR_TOKEN`, and the `X-Hanalpha-Operator-Token` header. All mutating endpoints return 403 by default. Cancel/flatten additionally require Broker write capability.

`paper_auto` is doubly opt-in: both `auto_submit_paper` and `broker_write_enabled` must be true, then runtime token validation must succeed. The repository default is `paper_manual` with all write switches false.

All strategy/agent decisions receive an explicit timezone-aware `as_of` from `DecisionClock`. Naive values fail; they are never relabeled as UTC.

## Consequences

- Configuration labels alone can no longer authorize submission.
- LLM agents still receive no Broker object or capability.
- `live_proposal` can connect to a read/reconciliation adapter in a future milestone, but cannot submit through the Broker protocol.
- Legacy `environment` config is migrated only to a safer equivalent and then subjected to the new validators.
- API authentication is a localhost operator boundary, not a remote-deployment security claim. TLS, CSRF, sessions, actor audit, and network policy remain M7 work.
- A token stored in the same compromised process is not protection against host compromise. Process/OS isolation is deferred to the execution-control milestone.

## Rejected alternatives

- Boolean-only `is_live`/`is_paper`: too easy to combine into an invalid state.
- Route-only checks: internal callers could bypass the API.
- Broker class chosen by config only: possession of an adapter would imply authority.
- Autonomous live mode: outside the product safety boundary.
