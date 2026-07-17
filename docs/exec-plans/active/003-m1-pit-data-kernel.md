# M1 execution plan: point-in-time data kernel

Status: READY, NOT STARTED
Owner: next Codex Goal
Created: 2026-07-18

## Objective

Implement the smallest end-to-end PIT slice that proves a historical decision can only query securities and facts available at its explicit `as_of`, with immutable raw lineage and deterministic snapshot replay.

## Inputs and authority

- M0 is complete and verified in a clean hash-locked Python 3.12 environment.
- ADR 0001 remains the execution safety boundary.
- ADR 0002 is the M1 data/time/storage contract.
- `docs/v2-plan/08_M1_FROZEN_FIXTURE_SPEC_ZH.md` defines the first dataset and expected outcomes.
- M1 uses only repository-owned synthetic fixtures. It has no authority to call vendors, LLMs or brokers.

## Work packages

### WP1: Failing contracts first

- Add bitemporal model tests for aware times, availability and validity intervals.
- Add security-master tests for ticker rename, delisting and symbol reuse.
- Add corporate-action tests for split/dividend event replay.
- Add snapshot immutability/hash tests and quality fail-closed tests.

### WP2: Immutable raw layer

- Implement `RawEnvelope`, content hashing and append-only content-addressed storage.
- Implement SQLite manifest/lineage schema with atomic publication states.
- Reject a hash/path collision whose bytes differ.

### WP3: Canonical PIT layer

- Implement stable instrument IDs, listing intervals, aliases and corporate actions.
- Normalize frozen fixture records into versioned canonical rows.
- Write canonical Parquet and query through DuckDB.

### WP4: As-of repository

- Implement typed `AsOfRepository`; no strategy receives raw SQL/storage handles.
- Enforce availability and validity predicates centrally.
- Propagate `DecisionClock`/`AsOfContext` into the first feature query.

### WP5: Snapshot and quality gate

- Canonicalize and hash manifests.
- Record schema/code/config/input hashes.
- Block publication on duplicates, overlap, orphan records, unknown time or nondeterministic output.
- Add CLI commands for fixture ingest, quality report and snapshot inspection.

### WP6: Verification and closeout

- Run full repository verification from the lock file.
- Update implementation matrix, risk register, limitations, changelog and verification report.
- Do not start M2 until all M1 exit gates pass.

## Planned code boundaries

```text
src/hanalpha/pit/models.py
src/hanalpha/pit/context.py
src/hanalpha/pit/raw_store.py
src/hanalpha/pit/catalog.py
src/hanalpha/pit/canonical_store.py
src/hanalpha/pit/repository.py
src/hanalpha/pit/symbology.py
src/hanalpha/pit/actions.py
src/hanalpha/pit/quality.py
src/hanalpha/data/fixtures.py
tests/pit/
```

Names may change only through an ADR/plan update; responsibilities must remain separated.

## Exit gates

- No current constituent/ticker can leak into an earlier `as_of`.
- Delisted instruments remain queryable in their historical interval.
- `available_at > as_of` is never returned.
- DST ambiguity and naive timestamps fail closed.
- Split/dividend views reproduce expected fixture results without overwriting raw prices.
- Duplicate, late and revised inputs follow explicit deterministic policy.
- Same inputs/schema/code/config produce identical snapshot and feature hashes.
- Failed quality results cannot publish a snapshot.
- M0 execution capability tests remain green.

## Stop conditions

Stop and report before any real provider call, paid dependency, private dataset inclusion, LLM call, IBKR connection or order action. Stop if the design requires weakening an M0 boundary.
