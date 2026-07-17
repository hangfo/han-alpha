from __future__ import annotations

from datetime import date
from typing import Any

import httpx


class FREDClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.stlouisfed.org/fred",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("FRED API key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._external_client = client

    async def series_observations(
        self,
        series_id: str,
        *,
        observation_start: date | None = None,
        realtime_start: date | None = None,
        realtime_end: date | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
        }
        if observation_start:
            params["observation_start"] = observation_start.isoformat()
        if realtime_start:
            params["realtime_start"] = realtime_start.isoformat()
        if realtime_end:
            params["realtime_end"] = realtime_end.isoformat()
        url = f"{self.base_url}/series/observations"
        if self._external_client is not None:
            response = await self._external_client.get(url, params=params)
        else:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url, params=params)
        response.raise_for_status()
        return list(response.json().get("observations") or [])
