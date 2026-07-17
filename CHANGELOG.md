# Changelog

## Unreleased - M1 PIT data kernel (2026-07-18)

### Added

- Frozen synthetic PIT fixture v1 covering stable instrument IDs, ticker rename/reuse, delisting, late revisions, split/dividend events and DST boundaries.
- Immutable content-addressed raw bytes, SQLite lineage/publication catalog and DuckDB-backed canonical Parquet snapshots.
- Typed `AsOfRepository` with centralized availability, validity interval, snapshot publication and latest-visible-revision enforcement.
- Deterministic snapshot/feature hashing, fail-closed quality reports and fixture ingest/quality/snapshot CLI commands.
- Minimal deterministic XNYS session classifier for fixture validation, with explicit DST ambiguity/nonexistence rejection.

### Changed

- Added and hash-locked DuckDB 1.5.4 plus the explicit editable-build dependency required by clean bootstrap.
- Raised the canonical repository result to 76 tests and 77.41% branch-aware coverage.

### Safety

- M1 makes no vendor, LLM, IBKR or order call and does not weaken any M0 capability boundary.
- Staged or failed-quality snapshots remain non-queryable; canonical snapshot content cannot be overwritten.

## Unreleased - M0 safety baseline (2026-07-18)

### Added

- V0.1 baseline Git freeze and provenance identifiers.
- Capability-based operating modes with no `live_auto` state.
- Explicit timezone-aware `DecisionClock` for orchestration and agent review.
- Runtime-issued Broker write capability and separate operator API token boundary.
- Structural/adversarial tests for non-paper submission denial, naive time, limit prices and default-deny API behavior.
- ADR, risk register, M0 execution plan and M1 PIT entry decision.
- Hash-locked Python 3.12 development requirements and clean-environment bootstrap.

### Changed

- Default configuration is `paper_manual`; paper auto-submit and all API mutations are off.
- Simulated buy/sell fills respect their limit prices after adverse slippage.
- Broker `submit`, `cancel_all` and `flatten_all` require an explicit capability.
- LLM reviewer payloads include the decision `as_of`; LLMs still have no Broker tool.
- Package verification builds without isolation from the locked toolchain.

### Security

- Every POST route now requires an explicitly enabled operator token; cancel/flatten also require Broker write capability.
- `research`, `backtest`, `shadow` and `live_proposal` cannot obtain Broker write capability.

### Verification status

- M0 reproduced in a fresh hash-locked Python 3.12.13 environment.
- Ruff passed; mypy strict passed for 46 source files; 48 tests passed at 72.02% branch-aware coverage; package build, doctor, demo and backtest passed.
