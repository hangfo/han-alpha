# Implementation matrix

| Requirement | Status | Code / document |
|---|---|---|
| Direct local run | Complete | Synthetic provider, CLI demo |
| Quant strategies | Complete V1 | `strategies/` |
| Market regime | Complete V1 | `regime/engine.py` |
| Multi-agent review | Complete V1 | `agents/` |
| Prompt-injection defense | Complete V1 | `agents/firewall.py` |
| Deterministic risk | Complete V1 | `risk/engine.py` |
| Idempotent orders | Complete V1 | Ledger + brokers |
| Conservative paper fills | Complete V1 | `execution/simulated.py` |
| Protective stop/target | Complete V1 | Simulated and IBKR bracket implementation |
| IBKR paper adapter | Implemented, credentials not validated | `execution/ibkr.py` |
| Polygon data | Implemented, key not validated | `data/polygon.py` |
| SEC client | Implemented, not wired to strategy cycle | `data/sec.py` |
| FRED client | Implemented, not wired to regime cycle | `data/fred.py` |
| Backtester | Complete baseline | `backtest/engine.py` |
| Walk-forward/purged CV | Planned | Roadmap V0.3 |
| API controls | Complete local V1 | `api/main.py` |
| Continuous worker | Complete | CLI `worker` |
| Authenticated mobile approval | Planned | Roadmap V0.4/V1.0 |
| Live auto trading | Deliberately disabled | Safety requirement |
| Proven alpha | Not established | Requires real data and forward testing |
| Codex repository instructions | Complete | `AGENTS.md`, `CODEX_START_HERE.md` |
| Codex master/resume/audit prompts | Complete | `docs/codex/` |
| Mechanical platform acceptance criteria | Complete | `docs/codex/ACCEPTANCE_CRITERIA.md` |
| Active long-running execution plan | Complete | `docs/exec-plans/active/001-complete-platform.md` |
| One-command Codex bootstrap | Complete | `scripts/bootstrap_codex.sh` |
| Codex preflight/full verification | Complete | `scripts/preflight.sh`, `scripts/verify_all.sh` |
