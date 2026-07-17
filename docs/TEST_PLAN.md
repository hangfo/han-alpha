# Verification and adversarial test plan

## Static checks

- package build;
- Python compile;
- Ruff lint;
- strict configuration validation;
- optional mypy after adapter stubs mature.

## Unit tests

- OHLC and quote invariants;
- ATR and relative-strength inputs;
- risk sizing;
- symbol, gross, position-count, drawdown, and daily-loss limits;
- regime strategy allowlist;
- strategy signal geometry;
- ledger idempotency.

## Adversarial tests

- stale quote rejection;
- broker disconnect rejection;
- duplicate order rejection;
- prompt injection in evidence;
- fabricated LLM evidence ID;
- malformed LLM output;
- catalyst unavailable at decision time;
- negative or impossible market data;
- missing quote during flatten;
- repeated cancel-all;
- gap beyond protective stop;
- slippage causing insufficient cash;
- unknown regime;
- live config with paper auto-submit;
- LLM position sizing enabled.

## Integration tests

- full synthetic cycle;
- ledger event generation;
- bracket entry and target/stop exit;
- API startup and health;
- kill-switch control flow.

## Research validation

Before considering alpha credible:

- point-in-time universe;
- delisted symbols;
- realistic costs and spread;
- latency and next-bar execution;
- walk-forward evaluation;
- embargo and purged cross-validation where labels overlap;
- multiple-testing correction;
- parameter perturbation;
- regime and symbol contribution analysis;
- comparison with a non-LLM baseline.
