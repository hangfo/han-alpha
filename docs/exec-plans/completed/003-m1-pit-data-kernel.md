# M1 execution plan: point-in-time data kernel

Status: COMPLETED AND VERIFIED
Owner: Codex
Created: 2026-07-18
Completed: 2026-07-18

## Objective

Implement the smallest end-to-end PIT slice that proves a historical decision can only query securities and facts available at its explicit `as_of`, with immutable raw lineage and deterministic snapshot replay.

## Authority and boundary

- M0 and ADR 0001 remain the execution safety boundary.
- ADR 0002 is the implemented M1 data/time/storage contract.
- `docs/v2-plan/08_M1_FROZEN_FIXTURE_SPEC_ZH.md` is the frozen dataset contract.
- M1 used only repository-owned synthetic fixtures. No vendor, LLM, IBKR or order call was made.

## Completed work packages

### WP1: contracts first

- Added aware-time, availability, interval, DST, symbology, revision, corporate-action, snapshot and fail-closed publication tests before implementation.

### WP2: immutable raw layer

- Implemented `RawEnvelope`, SHA-256 content-addressed append-only objects and idempotent input handling.
- Implemented SQLite source-revision conflict detection plus staged/published snapshots.

### WP3: canonical PIT layer

- Implemented stable instrument, alias, bar and corporate-action records.
- Added canonical immutable Parquet snapshots backed by DuckDB 1.5.4.
- Added minimal deterministic XNYS fixture-session checks and explicit DST gap/fold handling.

### WP4: as-of repository

- Implemented typed `AsOfRepository`; strategies receive no DuckDB connection or filesystem path.
- Centralized published-snapshot, availability, half-open validity and latest-visible-revision predicates.
- Used this repository to compute the deterministic fixture feature hash.

### WP5: snapshot and quality gate

- Canonicalized manifests from sorted input plus schema/code/config hashes.
- Blocked publication for orphan references, conflicting source revisions, ticker overlap, mixed snapshots and out-of-session fixture bars.
- Added `pit ingest-fixture`, `pit quality` and `pit snapshot` CLI commands.

### WP6: verification and closeout

- Updated the implementation matrix, risk register, limitations, changelog and verification report.
- Regenerated the hash lock and reproduced the suite in a newly created Python 3.12.13 environment.

## Exit-gate result

- [x] Earlier `as_of` cannot see future ticker or revision state.
- [x] Delisted instruments remain historically visible and leave the later active universe.
- [x] `available_at > as_of` is not returned.
- [x] Naive, nonexistent DST and ambiguous DST wall times fail closed.
- [x] Split/dividend adjustment is explicit, traceable and does not rewrite raw prices.
- [x] Duplicate/conflict/revision policy is deterministic; failed quality cannot publish.
- [x] Same fixture/schema/code/config reproduces snapshot and feature hashes, including same-state replay.
- [x] M0 capability tests remain green.

## Canonical evidence

- Frozen snapshot: `1741368ff587ab3b09a8c44c5353cf2a4c50a9aecbdc531457dbb93f83eafc76`.
- Feature hash: `56ede5afa4f3336613a6bdaf0fb2ab7432a0bc9029110219e9d2baa91e9df88a`.
- Quality digest: `5af0fe7f45a043afed563c06538174a5268fa86a5f7c37e5c207f39275f34321`.
- Final canonical run: 76 tests, 77.41% branch-aware coverage, Ruff/mypy/build/CLI smoke PASS.
- Clean hash-locked Python 3.12.13 reproduction: PASS.

## Explicit defers

- Real vendor adapters, licensing/retention review and golden vendor payload reconciliation: deferred until separately authorized data procurement.
- Authoritative exchange holidays, early closes, halts and venue rules: required before a real-data production claim.
- Portfolio event replay, accounting, realistic execution costs and research/run parity: M2.
- LLM evaluation and Broker integration: later gated milestones; not part of M1.
