# M3 research method evidence and limits

## Decision objective

M3 optimizes for rejecting false trading claims before any strategy can influence paper-trading decisions. A high synthetic return is irrelevant; the useful output is a reproducible record of what was knowable, what was proposed or rejected, how it would have filled, and which independent gates failed.

## Primary-method basis

- Cross-sectional momentum is included only as an interpretable falsification baseline, following the formation/holding-period idea in Jegadeesh and Titman, *Returns to Buying Winners and Selling Losers* ([author-hosted paper](https://www.bauer.uh.edu/rsusmel/phd/jegadeesh-titman93.pdf)).
- PEAD is represented as a typed event strategy requiring both announcement availability and a frozen expectations snapshot; this preserves the information-timing premise associated with Bernard and Thomas ([publication record](https://oamonitor.ireland.openaire.eu/rfo/sfi_rfo/search/publication?pid=10.2307%2F2491062)). Missing expectations means abstain.
- Deflated Sharpe is a multiple-testing rejection diagnostic based on Bailey and López de Prado ([original paper](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)). It is not treated as proof of future returns.
- CSCV Probability of Backtest Overfitting follows Bailey et al. ([paper record](https://escholarship.org/uc/item/4hn4t174)). Insufficient trials, partitions, or observations return `sufficient=false` and cannot satisfy promotion.

## Evidence flow

1. Freeze snapshot, universe, feature schema, costs, hypothesis, ranges, windows, seed and research budget.
2. Assemble immutable point-in-time contexts; revisions may change later knowledge but cannot become tradable events.
3. Run train/validation/test or rolling walk-forward folds with purge and embargo.
4. Register base and counterfactual experiments for doubled cost, delayed execution and parameter perturbation. Rejected decisions receive the same future-outcome measurement contract as executed candidates.
5. Compute post-cost metrics, concentration and statistical diagnostics. Any missing mandatory diagnostic fails closed.
6. Promotion requires a dedicated evidence packet plus reproducible artifacts and independent human approval. Generic lifecycle transitions cannot promote.

## Known limits and blockers

- Synthetic and frozen fixture results are engineering evidence, not real-data Alpha, capacity, market-impact or venue evidence.
- Real strategy conclusions remain BLOCKED until data license, survivorship-free universe, timestamp semantics, earnings expectations, and corporate-action lifecycle fields are reviewed.
- The current fixture cannot prove dividend entitlement or payable-date cash timing. M3 models lifecycle phases and prevents revision duplication but does not invent absent dates.
- Annualized metrics on short intraday synthetic samples can be numerically extreme and are never eligible evidence without the pre-registered minimum observation and duration rules.
- LLM research assistance is M4 scope. LLMs remain unable to size positions, change risk, promote experiments, or call a Broker.
