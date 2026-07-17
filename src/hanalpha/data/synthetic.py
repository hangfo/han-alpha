from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime, timedelta

import numpy as np

from hanalpha.domain.enums import SignalAction
from hanalpha.domain.models import Bar, Catalyst, Quote


class SyntheticMarketDataProvider:
    """Deterministic synthetic data for local development and repeatable tests."""

    def __init__(self, interval_minutes: int = 5, seed: int = 7) -> None:
        self.interval_minutes = interval_minutes
        self.seed = seed
        self._cycle = 0
        self._bars: dict[str, list[Bar]] = {}

    def _symbol_seed(self, symbol: str) -> int:
        digest = hashlib.sha256(f"{symbol}:{self.seed}".encode()).hexdigest()
        return int(digest[:8], 16)

    def _ensure(self, symbol: str, limit: int) -> None:
        required = max(limit, 150)
        current = self._bars.get(symbol, [])
        if len(current) >= required:
            return
        rng = np.random.default_rng(self._symbol_seed(symbol))
        start = datetime.now(UTC) - timedelta(minutes=self.interval_minutes * required)
        base = 25 + self._symbol_seed(symbol) % 300
        trend = 0.0008 + (self._symbol_seed(symbol) % 9) / 10000
        price = float(base)
        bars: list[Bar] = []
        for index in range(required):
            cyclical = math.sin(index / 11) * 0.002
            shock = float(rng.normal(trend + cyclical, 0.006))
            open_price = price
            close_price = max(1.0, price * (1 + shock))
            intrabar = abs(float(rng.normal(0.003, 0.0015)))
            high = max(open_price, close_price) * (1 + intrabar)
            low = min(open_price, close_price) * max(0.1, 1 - intrabar)
            volume = float(max(100_000, rng.lognormal(13.2, 0.4)))
            bars.append(
                Bar(
                    symbol=symbol,
                    timestamp=start + timedelta(minutes=index * self.interval_minutes),
                    open=open_price,
                    high=high,
                    low=low,
                    close=close_price,
                    volume=volume,
                )
            )
            price = close_price
        self._bars[symbol] = bars

    async def get_bars(self, symbol: str, limit: int) -> list[Bar]:
        self._ensure(symbol, limit)
        return list(self._bars[symbol][-limit:])

    async def get_quote(self, symbol: str) -> Quote:
        self._ensure(symbol, 2)
        last_bar = self._bars[symbol][-1]
        spread = max(0.01, last_bar.close * 0.0004)
        return Quote(
            symbol=symbol,
            timestamp=datetime.now(UTC),
            bid=last_bar.close - spread / 2,
            ask=last_bar.close + spread / 2,
            last=last_bar.close,
            bid_size=1000,
            ask_size=1000,
        )

    async def get_catalysts(self, symbol: str, since: datetime) -> list[Catalyst]:
        if self._cycle % 7 != 0 or symbol not in {"NVDA", "CRDO", "PLTR"}:
            return []
        published = datetime.now(UTC) - timedelta(hours=2)
        if published < since:
            return []
        return [
            Catalyst(
                symbol=symbol,
                category="synthetic_positive_revision",
                score=0.78,
                direction=SignalAction.BUY,
                published_at=published,
                available_at=published,
                headline=f"Synthetic verified catalyst for {symbol}",
                evidence_ids=[f"synthetic:{symbol}:{published.isoformat()}"],
            )
        ]

    async def is_healthy(self) -> bool:
        return True

    def advance(self) -> None:
        self._cycle += 1
        for symbol, bars in self._bars.items():
            last = bars[-1]
            rng = np.random.default_rng(self._symbol_seed(symbol) + self._cycle)
            change = float(rng.normal(0.001, 0.005))
            open_price = last.close
            close_price = max(1.0, open_price * (1 + change))
            intrabar = abs(float(rng.normal(0.0025, 0.001)))
            bars.append(
                Bar(
                    symbol=symbol,
                    timestamp=datetime.now(UTC),
                    open=open_price,
                    high=max(open_price, close_price) * (1 + intrabar),
                    low=min(open_price, close_price) * max(0.1, 1 - intrabar),
                    close=close_price,
                    volume=float(max(100_000, rng.lognormal(13.2, 0.4))),
                )
            )
