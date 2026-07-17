# Public evidence register

Snapshot date: 2026-07-18. Public research is used as design evidence, not proof of deployable alpha.

## LLM agents and benchmarks

| Source | Evidence used | Design implication |
|---|---|---|
| [Agentic Trading survey, arXiv:2605.19337](https://arxiv.org/abs/2605.19337) | 77-study audit; the primary subset has very weak time-consistent splits, cost modeling, survivorship handling, and reproducibility. | Evaluation protocol and evidence ledger matter more than another debate agent. |
| [KTD-Fin, arXiv:2605.28359](https://arxiv.org/abs/2605.28359) | Identifier/date masking changes reasoning; much apparent return is beta/style, with limited persistent selection alpha. | Add leakage-controlled evaluation and factor attribution. |
| [LiveTradeBench, arXiv:2511.03628](https://arxiv.org/abs/2511.03628) | 50-day, 21-model live benchmark; general arena strength does not imply trading strength. | Select models on task-specific evals; forward/live observation is mandatory. |
| [When Agents Trade, arXiv:2510.11695](https://arxiv.org/abs/2510.11695) | Multi-market live agent benchmark; architecture and risk behavior are material. | Treat agent topology as a controlled variable, not a marketing feature. |
| [Fin-Analyst, arXiv:2607.12233](https://arxiv.org/abs/2607.12233) | Eight specialists, short live TSLA/BTC challenge; 8-K events mattered, rankings changed with the window. | Event extraction is promising, but short-window returns are not durable proof. |
| [Finance Agent Benchmark, arXiv:2508.00828](https://arxiv.org/abs/2508.00828) | 537 expert finance tasks; the reported best model reached 46.8% at nontrivial cost. | High-stakes finance agents need abstention, citations and deterministic checks. |
| [TradingAgents repository](https://github.com/TauricResearch/TradingAgents) | v0.2.5 adds structured output, checkpoints, decision logs, multi-provider and grounded sentiment; project remains research-oriented. | Reuse patterns, not performance claims; keep our execution and risk authority deterministic. |
| [FinMem, arXiv:2311.13743](https://arxiv.org/abs/2311.13743) | Layered memory and reflection for financial agents. | Memory should be immutable, time-scoped evidence with outcome labels. |
| [FinAgent, arXiv:2402.18485](https://arxiv.org/abs/2402.18485) | Multimodal market intelligence, tools and reflection. | Tool/evidence orchestration is useful, but outputs remain advisory. |

## Strategy and validation

| Source | Evidence used | Design implication |
|---|---|---|
| [Time Series Momentum, SSRN 2089463](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463) | Persistent trend evidence across markets/horizons. | Prefer slower trend/momentum hypotheses to unproven 5-minute alpha. |
| [Fact, Fiction and Momentum Investing](https://www.aqr.com/Insights/Research/Journal-Article/Fact-Fiction-and-Momentum-Investing) | Momentum evidence and implementation caveats. | Use explicit benchmark/factor exposure and turnover controls. |
| [Momentum Crashes, NBER w20439](https://www.nber.org/papers/w20439) | Momentum can crash in rebounds/high-volatility states. | Add regime-aware de-risking, not a binary LLM macro call. |
| [Volatility Managed Portfolios, NBER w22208](https://www.nber.org/papers/w22208) | Scaling exposure by volatility can improve risk-adjusted behavior in tested factors. | Risk targeting belongs in deterministic portfolio policy. |
| [Deflated Sharpe Ratio, SSRN 2460551](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551) | Corrects Sharpe for selection bias and non-normality. | Make DSR part of research gates. |
| [All that Glitters, SSRN 2745220](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2745220) | Backtest metrics weakly predict out-of-sample results; more trials widen the gap. | Track trials and apply PBO/DSR/pre-registration. |
| [PEAD and liquidity, SSRN 937257](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=937257) | Post-earnings drift interacts with timing and liquidity. | Build event signals from timestamped earnings facts and executable liquidity. |

## Data, execution and platform docs

| Source | Evidence used | Design implication |
|---|---|---|
| [Databento symbology](https://databento.com/docs/standards-and-conventions/symbology) | Event-time symbology and instrument mapping. | Persist vendor instrument ids and PIT symbol mapping. |
| [Databento corporate actions](https://databento.com/docs/venues-and-datasets/corporate-actions) | Dedicated reference feed for corporate actions. | Treat adjustments as versioned events, not a current-price convenience flag. |
| [Massive Stocks API](https://massive.com/docs/rest/stocks) | Active/inactive tickers and reference endpoints. | Include inactive/delisted securities in the universe pipeline. |
| [IBKR TWS API documentation](https://interactivebrokers.github.io/tws-api/) | Asynchronous orders, executions and account callbacks. | Build a durable state machine and reconciliation loop around broker callbacks. |
| [OpenAI model catalog](https://developers.openai.com/api/docs/models) | Current Sol/Terra/Luna model families. | Route by measured task quality/cost; do not use the nonexistent “Sol Pro” name. |
| [Codex manual](https://developers.openai.com/codex) | Goals should be bounded; complex work benefits from plans and repo instructions. | Keep detailed specs in versioned files and one milestone per Goal. |

## Evidence limitations

- Most LLM-trading papers are preprints, short-window experiments, simulated markets, or narrowly scoped competitions.
- Reported return/Sharpe values are not comparable without identical universe, timing, costs, capital, constraints and leakage controls.
- No source above establishes that a multi-agent LLM system has durable, capacity-adjusted, post-cost alpha suitable for unattended trading.
- Vendor features and pricing can change; re-verify before procurement or implementation.

