# Changelog

## Unreleased - M0 safety baseline (2026-07-18)

### Added

- V0.1 baseline Git freeze and provenance identifiers.
- Capability-based operating modes with no `live_auto` state.
- Explicit timezone-aware `DecisionClock` for orchestration and agent review.
- Runtime-issued Broker write capability and separate operator API token boundary.
- Structural/adversarial tests for non-paper submission denial, naive time, limit prices and default-deny API behavior.
- ADR, risk register, M0 execution plan and M1 PIT entry decision.

### Changed

- Default configuration is `paper_manual`; paper auto-submit and all API mutations are off.
- Simulated buy/sell fills respect their limit prices after adverse slippage.
- Broker `submit`, `cancel_all` and `flatten_all` require an explicit capability.
- LLM reviewer payloads include the decision `as_of`; LLMs still have no Broker tool.

### Security

- Every POST route now requires an explicitly enabled operator token; cancel/flatten also require Broker write capability.
- `research`, `backtest`, `shadow` and `live_proposal` cannot obtain Broker write capability.

### Verification status

- Preflight, compile, diff check and offline safety/full-cycle smoke passed.
- Canonical ruff, mypy, full pytest/coverage and build are blocked by a missing local dev toolchain and remain required before M1.
