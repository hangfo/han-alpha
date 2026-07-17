from __future__ import annotations

import asyncio
from typing import Any, cast

import httpx


class SECClient:
    """Rate-limited client for public data.sec.gov submissions and XBRL APIs."""

    def __init__(
        self,
        *,
        user_agent: str,
        requests_per_second: float = 5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if "@" not in user_agent or len(user_agent) < 8:
            raise ValueError("SEC User-Agent must identify an organization and contact email")
        if not 0 < requests_per_second <= 10:
            raise ValueError("SEC rate must be between 0 and 10 requests per second")
        self.user_agent = user_agent
        self.interval = 1 / requests_per_second
        self._last_request = 0.0
        self._lock = asyncio.Lock()
        self._external_client = client

    async def _get(self, url: str) -> dict[str, Any]:
        async with self._lock:
            loop = asyncio.get_running_loop()
            delay = self.interval - (loop.time() - self._last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            headers = {
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json",
            }
            if self._external_client is not None:
                response = await self._external_client.get(url, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.get(url, headers=headers)
            self._last_request = loop.time()
            response.raise_for_status()
            return cast(dict[str, Any], response.json())

    @staticmethod
    def normalize_cik(cik: str | int) -> str:
        digits = "".join(character for character in str(cik) if character.isdigit())
        if not digits:
            raise ValueError("CIK must contain digits")
        return digits.zfill(10)

    async def submissions(self, cik: str | int) -> dict[str, Any]:
        normalized = self.normalize_cik(cik)
        return await self._get(f"https://data.sec.gov/submissions/CIK{normalized}.json")

    async def company_facts(self, cik: str | int) -> dict[str, Any]:
        normalized = self.normalize_cik(cik)
        return await self._get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{normalized}.json")
