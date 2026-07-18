# ADR 0006: LLM Evidence Service boundary

- Status: Accepted for M4
- Date: 2026-07-18
- Scope: unstructured evidence extraction and decision review

## First-principles objective

A trading decision is improved only if additional evidence changes a pre-existing
quantitative candidate with positive net incremental value after missed gains,
model cost and latency. Fluent text is not evidence. The system therefore keeps
the LLM outside signal generation, sizing, risk policy and Broker authority.

## Decisions

1. Every source document is immutable and content-addressed, with source URI,
   observed, effective, available and ingestion times. Future-unavailable
   documents are rejected.
2. An extracted claim requires an exact character span whose hash matches the
   frozen document. Claims have availability and expiry; expired claims cannot
   enter a snapshot.
3. Contradictory typed claims remain visible as deterministic graph edges. The
   service does not silently choose the more confident prose.
4. Extractors return a strict `ExtractionResult`: supported claims or explicit
   abstention. A review may only `allow`, `veto` or `abstain` on an existing
   candidate and may cite only claims in its snapshot. Veto requires a concrete
   invalidator.
5. The OpenAI adapter uses the Responses API, strict Structured Outputs, no
   tools, `store=false`, a stable prompt cache key and an instruction that treats
   document text as untrusted. Default production configuration is
   `gpt-5.6-terra` at medium effort; `gpt-5.6-sol` at high effort is reserved for
   measured offline hard-case review, never the hot path.
6. The exact document, schema, model, extractor version and prompt hashes form
   the local cache key. Event call budgets are atomically persisted. Failed
   calls consume budget and leave an attempt record.
7. Tests use deterministic and fake extractors only. A real Provider call is a
   credential- and cost-gated external acceptance step.

## No-trade firewall

The evidence package has no import or reference to Broker adapters, position
sizing or mutable risk configuration. Model payloads expose no tools. Evidence
can veto an existing candidate; it cannot create an order proposal. Timeout,
rate limit, malformed output, fabricated claim, expired evidence, budget
exhaustion and prompt injection all end in error or abstention.

## Evaluation

The ablation report charges avoided losses, missed gains, model cost and latency
against the no-LLM baseline. Local code and adversarial fixtures validate the
measurement contract. A claim that LLM evidence adds Alpha remains BLOCKED until
real PIT documents and frozen forward outcomes exist.

## Current public API basis

Design was checked against current official OpenAI guidance on 2026-07-18:

- Responses/model selection: <https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.6>
- Structured Outputs: <https://developers.openai.com/api/docs/guides/structured-outputs>
- Prompt caching: <https://developers.openai.com/api/docs/guides/prompt-caching>
- Evaluation guidance: <https://developers.openai.com/api/docs/guides/evals>

