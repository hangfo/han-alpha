from __future__ import annotations

import json

import httpx
import pytest

from hanalpha.agents.llm import LLMResearchAgent
from hanalpha.domain.enums import SignalAction
from hanalpha.domain.models import Evidence


@pytest.mark.asyncio
async def test_llm_malformed_output_fails_closed(signal, regime, now) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output_text": "not-json"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        agent = LLMResearchAgent(
            api_key="x",
            base_url="https://example.test/v1",
            model="test-model",
            client=client,
        )
        result = await agent.assess(signal, [], regime, now)
    assert result.veto
    assert "malformed_llm_output" in result.invalidators


@pytest.mark.asyncio
async def test_llm_fabricated_evidence_fails_closed(signal, regime, now) -> None:
    response = {
        "agent_name": "llm",
        "action": SignalAction.BUY,
        "confidence": 0.9,
        "rationale": "Looks good",
        "evidence_ids": ["invented-id"],
        "invalidators": [],
        "veto": False,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output_text": json.dumps(response)})

    evidence = Evidence(
        evidence_id="real-id",
        source="news",
        title="Verified news",
        observed_at=now,
        available_at=now,
        payload_hash="12345678abcdef",
        summary="Verified summary",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        agent = LLMResearchAgent(
            api_key="x",
            base_url="https://example.test/v1",
            model="test-model",
            client=client,
        )
        result = await agent.assess(signal, [evidence], regime, now)
    assert result.veto
    assert "fabricated_evidence_id" in result.invalidators
