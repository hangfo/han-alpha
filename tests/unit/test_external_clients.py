from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest

from hanalpha.data.fred import FREDClient
from hanalpha.data.polygon import PolygonMarketDataProvider
from hanalpha.data.sec import SECClient


@pytest.mark.asyncio
async def test_polygon_parses_bars_quote_and_news() -> None:
    timestamp_ms = int(datetime(2026, 7, 17, 15, 0, tzinfo=UTC).timestamp() * 1000)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/v2/aggs/" in path:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"t": timestamp_ms, "o": 100, "h": 102, "l": 99, "c": 101, "v": 1_000_000},
                        {"t": timestamp_ms + 300_000, "o": 101, "h": 103, "l": 100, "c": 102, "v": 1_100_000},
                    ]
                },
            )
        if "/v2/snapshot/" in path:
            return httpx.Response(
                200,
                json={
                    "ticker": {
                        "lastQuote": {
                            "bid": 101.9,
                            "ask": 102.1,
                            "bid_size": 500,
                            "ask_size": 400,
                            "t": timestamp_ms,
                        },
                        "lastTrade": {"price": 102.0, "t": timestamp_ms},
                    }
                },
            )
        if path == "/v2/reference/news":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "n1",
                            "published_utc": "2026-07-17T14:00:00Z",
                            "title": "Company raises guidance after record order",
                            "description": "Revenue outlook raised.",
                        }
                    ]
                },
            )
        if path == "/v3/reference/tickers":
            return httpx.Response(200, json={"results": [{"ticker": "SPY"}]})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = PolygonMarketDataProvider(api_key="test", client=client)
        bars = await provider.get_bars("NVDA", 2)
        quote = await provider.get_quote("NVDA")
        news = await provider.get_catalysts("NVDA", datetime(2026, 7, 17, tzinfo=UTC))
        assert len(bars) == 2
        assert quote.bid == 101.9
        assert quote.ask == 102.1
        assert news[0].score > 0.7
        assert await provider.is_healthy()


@pytest.mark.asyncio
async def test_sec_client_normalizes_cik_and_headers() -> None:
    seen_user_agent = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_user_agent
        seen_user_agent = request.headers.get("User-Agent", "")
        assert request.url.path.endswith("CIK0000320193.json")
        return httpx.Response(200, json={"cik": "320193"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sec = SECClient(user_agent="Han Alpha admin@example.com", client=client)
        payload = await sec.submissions(320193)
    assert payload["cik"] == "320193"
    assert "admin@example.com" in seen_user_agent


@pytest.mark.asyncio
async def test_fred_client_parses_observations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["series_id"] == "DGS10"
        return httpx.Response(200, json={"observations": [{"date": "2026-07-16", "value": "4.2"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fred = FREDClient(api_key="test", client=client)
        rows = await fred.series_observations("DGS10", observation_start=date(2026, 1, 1))
    assert rows[0]["value"] == "4.2"
