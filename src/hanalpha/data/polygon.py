from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx

from hanalpha.agents.firewall import sanitize_untrusted_text
from hanalpha.domain.enums import SignalAction
from hanalpha.domain.models import Bar, Catalyst, Quote


class PolygonMarketDataProvider:
    """Polygon REST provider for bars, snapshots, and conservative news catalysts."""

    def __init__(
        self,
        *,
        api_key: str,
        interval_minutes: int = 5,
        base_url: str = "https://api.polygon.io",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Polygon API key is required")
        self.api_key = api_key
        self.interval_minutes = interval_minutes
        self.base_url = base_url.rstrip("/")
        self._external_client = client

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = dict(params or {})
        query["apiKey"] = self.api_key
        if self._external_client is not None:
            response = await self._external_client.get(f"{self.base_url}{path}", params=query)
            response.raise_for_status()
            return cast(dict[str, Any], response.json())
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.base_url}{path}", params=query)
            response.raise_for_status()
            return cast(dict[str, Any], response.json())

    async def get_bars(self, symbol: str, limit: int) -> list[Bar]:
        days = max(7, int(limit * self.interval_minutes / 390 * 2) + 5)
        end = datetime.now(UTC).date()
        start = end - timedelta(days=days)
        payload = await self._get(
            f"/v2/aggs/ticker/{symbol}/range/{self.interval_minutes}/minute/{start}/{end}",
            {"adjusted": "true", "sort": "asc", "limit": 50000},
        )
        results = payload.get("results") or []
        bars = [
            Bar(
                symbol=symbol,
                timestamp=datetime.fromtimestamp(int(row["t"]) / 1000, tz=UTC),
                open=float(row["o"]),
                high=float(row["h"]),
                low=float(row["l"]),
                close=float(row["c"]),
                volume=float(row.get("v", 0)),
            )
            for row in results
        ]
        if len(bars) < limit:
            raise RuntimeError(f"Polygon returned only {len(bars)} bars for {symbol}; need {limit}")
        return bars[-limit:]

    @staticmethod
    def _first_number(mapping: dict[str, Any], keys: list[str]) -> float | None:
        for key in keys:
            value = mapping.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return None

    async def get_quote(self, symbol: str) -> Quote:
        payload = await self._get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}")
        ticker = payload.get("ticker") or {}
        last_quote = ticker.get("lastQuote") or {}
        last_trade = ticker.get("lastTrade") or {}
        minute = ticker.get("min") or {}
        bid = self._first_number(last_quote, ["P", "bid", "bid_price"])
        ask = self._first_number(last_quote, ["p", "ask", "ask_price"])
        last = self._first_number(last_trade, ["p", "price"]) or self._first_number(
            minute, ["c", "close"]
        )
        timestamp_ns = last_quote.get("t") or last_trade.get("t") or ticker.get("updated")
        if bid is None or ask is None or last is None or timestamp_ns is None:
            raise RuntimeError(f"Polygon snapshot missing quote fields for {symbol}")
        timestamp_value = int(timestamp_ns)
        divisor = 1_000_000_000 if timestamp_value > 10**17 else 1000
        timestamp = datetime.fromtimestamp(timestamp_value / divisor, tz=UTC)
        return Quote(
            symbol=symbol,
            timestamp=timestamp,
            bid=bid,
            ask=ask,
            last=last,
            bid_size=self._first_number(last_quote, ["S", "bid_size"]) or 0,
            ask_size=self._first_number(last_quote, ["s", "ask_size"]) or 0,
        )

    @staticmethod
    def _score_news(text: str) -> tuple[float, SignalAction]:
        lower = text.lower()
        positive = [
            "raises guidance",
            "guidance raised",
            "beats estimates",
            "record order",
            "contract award",
            "approval granted",
            "revenue outlook raised",
        ]
        negative = [
            "cuts guidance",
            "guidance lowered",
            "misses estimates",
            "investigation",
            "recall",
            "offering announced",
        ]
        if any(term in lower for term in positive):
            return 0.78, SignalAction.BUY
        if any(term in lower for term in negative):
            return 0.82, SignalAction.SELL
        return 0.45, SignalAction.HOLD

    async def get_catalysts(self, symbol: str, since: datetime) -> list[Catalyst]:
        payload = await self._get(
            "/v2/reference/news",
            {
                "ticker": symbol,
                "published_utc.gte": since.astimezone(UTC).isoformat(),
                "order": "desc",
                "sort": "published_utc",
                "limit": 50,
            },
        )
        catalysts: list[Catalyst] = []
        for row in payload.get("results") or []:
            published_raw = row.get("published_utc")
            if not published_raw:
                continue
            published = datetime.fromisoformat(str(published_raw).replace("Z", "+00:00"))
            title = sanitize_untrusted_text(str(row.get("title") or "Untitled"), 1000)
            description = sanitize_untrusted_text(str(row.get("description") or ""), 2000)
            score, direction = self._score_news(f"{title} {description}")
            article_id = str(row.get("id") or hashlib.sha256(title.encode()).hexdigest()[:24])
            catalysts.append(
                Catalyst(
                    symbol=symbol,
                    category="polygon_news",
                    score=score,
                    direction=direction,
                    published_at=published,
                    available_at=published,
                    headline=title,
                    evidence_ids=[f"polygon-news:{article_id}"],
                )
            )
        return catalysts

    async def is_healthy(self) -> bool:
        try:
            await self._get("/v3/reference/tickers", {"ticker": "SPY", "limit": 1})
        except (httpx.HTTPError, RuntimeError):
            return False
        return True
