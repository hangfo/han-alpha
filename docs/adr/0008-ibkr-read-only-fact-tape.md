# ADR 0008: IBKR Paper starts as a read-only fact tape

Status: Accepted  
Date: 2026-07-19

## Context

Repository-owned Fake Broker semantics cannot prove IBKR callback completeness, identity, ordering,
session reset behavior or account convergence. Sending a Paper order before understanding those facts
would combine observation and mutation and make failures ambiguous.

## Decision

M6 starts with a zero-write Observer. Every connection has a session epoch. Raw callbacks are persisted
append-only using broker-native identities. A snapshot is authoritative only with a completeness
certificate containing connection readiness, server time, managed account acknowledgement and account,
open-order, position and execution end markers, with no critical disconnect/error.

Reducers must be deterministic under callback reordering and duplicate delivery. `execId` identifies
executions, commission binds by `execId`, and order status has no global sequence watermark. Incomplete
snapshots freeze new risk and may never resolve or requeue Unknown Submission.

Observer code permits only Paper ports 4002 and 7497 and exposes no order-write capability. Paper Manual
orders remain a later, separately authorized stage after read-only burn-in, durable cancel and bracket
recovery tests.

## Consequences

- Broker facts can be replayed and audited without relying on callback arrival order.
- Connectivity without every end marker is explicitly incomplete, not healthy.
- No claim about IBKR integration or profitability is made from local collector tests.
- Real Paper callback evidence remains BLOCKED until the official package and local Paper endpoint exist.
