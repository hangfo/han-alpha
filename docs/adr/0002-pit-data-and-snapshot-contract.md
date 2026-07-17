# ADR 0002: PIT data and immutable snapshot contract

- Status: Accepted for M1 implementation
- Date: 2026-07-18
- Scope: local fixture-driven PIT kernel only

## Context

A historical query is valid only if it reconstructs what could have been known at the decision time. Current tickers, current index members, revised fundamentals or adjusted prices cannot be copied backward. A vendor response is evidence input, not the system of record.

## Decision

Every decision-eligible canonical record must contain:

- stable internal `instrument_id`; ticker is an interval-valued alias, never the primary key;
- timezone-aware `event_time`, `available_at` and `ingested_at`;
- `valid_from` and optional `valid_to` for interval-valued reference facts;
- `source`, `source_record_id`, `source_revision`, `schema_version` and `payload_hash`;
- immutable `snapshot_id`.

The only strategy-facing query port is `AsOfRepository`. It enforces:

```text
available_at <= as_of
valid_from <= as_of < coalesce(valid_to, infinity)
snapshot_id is immutable and explicit
```

Naive datetimes, records whose availability is unknown, overlapping alias intervals, duplicate source revisions and mutable snapshot contents fail closed.

## Storage design

- Raw payload bytes use content-addressed, append-only files keyed by SHA-256; they are never overwritten.
- Raw envelope metadata, snapshot manifests, lineage and quality results use SQLite initially.
- Canonical analytical tables use partitioned Parquet written and queried through DuckDB.
- A snapshot manifest contains sorted content hashes plus schema, normalization-code and configuration hashes. Its ID is the SHA-256 of canonical manifest bytes.
- Corporate actions remain versioned events. Raw prices are preserved; adjusted views declare their adjustment policy and snapshot.
- Strategies cannot receive a DuckDB connection or filesystem path. They receive typed repository results only.

This is a modular monolith. PostgreSQL is reserved for the M5 execution control plane; Kafka and distributed services are rejected until scale evidence requires them.

## Publication gate

A snapshot is queryable only after quality checks pass:

- key uniqueness and non-overlapping validity intervals;
- valid aware timestamps and exchange-calendar alignment;
- deterministic duplicate/revision policy;
- no orphan aliases or actions;
- expected partition and row-count reconciliation;
- deterministic replay/hash test.

Failed snapshots remain auditable but cannot become the active research snapshot.

## Consequences

- M1 can be built and tested entirely from synthetic frozen fixtures.
- Vendor adapters remain replaceable and cannot leak vendor response shapes into strategies.
- Storage costs increase because raw and revised records are retained; this is required for auditability.
- DuckDB becomes an M1 dependency only when the first tests require it; no dependency is added speculatively in M0.
- Real data procurement, licensing and retention policies require a separate decision before any adapter call.
