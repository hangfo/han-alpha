from __future__ import annotations

from datetime import datetime
from typing import Protocol

from hanalpha.domain.models import Bar, Catalyst, Quote


class MarketDataProvider(Protocol):
    async def get_bars(self, symbol: str, limit: int) -> list[Bar]: ...

    async def get_quote(self, symbol: str) -> Quote: ...

    async def get_catalysts(self, symbol: str, since: datetime) -> list[Catalyst]: ...

    async def is_healthy(self) -> bool: ...
