from __future__ import annotations

from datetime import datetime
from typing import Protocol

from hanalpha.domain.models import Bar, Catalyst, Signal


class Strategy(Protocol):
    name: str

    def generate(
        self,
        *,
        symbol: str,
        bars: list[Bar],
        benchmark_bars: list[Bar],
        catalysts: list[Catalyst],
        now: datetime,
    ) -> Signal | None: ...
