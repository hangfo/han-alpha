# Conversation synthesis and final product decision

## Starting point

The discussion compared three different ideas that are often incorrectly grouped together:

1. A social-media demo combining quant scans, machine learning, multiple LLM personas, risk review, IBKR execution, dashboards, and rapid parameter mutation.
2. TauricResearch TradingAgents, a research-oriented multi-agent framework that simulates analyst, bull/bear researcher, trader, risk, and portfolio-manager roles.
3. An IBKR MCP/CLI bridge that exposes account, position, quote, option, and risk data to an AI client but deliberately limits broker writes.

## Final interpretation

- The social-media system is an end-to-end automation demo. Its execution and dashboard ideas are useful, but a few days of paper P&L and fast parameter mutation do not prove alpha.
- TradingAgents is useful as a research-workflow reference. It is not an execution-grade strategy or evidence that multi-agent debate beats markets.
- The IBKR bridge is useful infrastructure. It gives an AI access to real account context but does not supply a profitable strategy.

## Product decision

Build a clean system rather than fork any of them:

- Borrow research-role separation from TradingAgents.
- Borrow account observability and local-data principles from IBKR MCP projects.
- Borrow multi-strategy accounting, dashboards, and paper execution from the social-media demo.
- Reject unrestricted LLM order placement, per-trade parameter mutation, ungrounded probability claims, and short sample performance marketing.

## First-principles objective

The system's objective is not to imitate a trading desk. It is to maximize the probability of producing a repeatable, cost-adjusted, risk-controlled edge while making false discoveries difficult.

That means:

- Every signal is reproducible from timestamped inputs.
- Every external fact has an availability timestamp.
- Every trade has an idempotency key and audit trail.
- Every risk decision is deterministic.
- The system remains operable when LLMs are unavailable.
- New strategies must beat a non-LLM baseline out of sample.
- Paper performance is marked with conservative shadow slippage.
- Live trading remains human-approved until explicit promotion criteria are met.
