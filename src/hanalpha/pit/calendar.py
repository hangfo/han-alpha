from __future__ import annotations

from datetime import date, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo

from hanalpha.pit.models import require_aware


class MarketPhase(StrEnum):
    CLOSED = "closed"
    PRE_MARKET = "pre_market"
    RTH = "rth"
    POST_MARKET = "post_market"


class ExchangeCalendar:
    """Deterministic session classifier for frozen fixtures, not a holiday authority."""

    def __init__(
        self,
        *,
        timezone: str = "America/New_York",
        holidays: frozenset[date] = frozenset(),
    ) -> None:
        self.timezone = ZoneInfo(timezone)
        self.holidays = holidays

    def phase(self, instant: datetime) -> MarketPhase:
        require_aware(instant, "instant")
        local = instant.astimezone(self.timezone)
        if local.weekday() >= 5 or local.date() in self.holidays:
            return MarketPhase.CLOSED
        clock = local.time().replace(tzinfo=None)
        if time(4) <= clock < time(9, 30):
            return MarketPhase.PRE_MARKET
        if time(9, 30) <= clock < time(16):
            return MarketPhase.RTH
        if time(16) <= clock < time(20):
            return MarketPhase.POST_MARKET
        return MarketPhase.CLOSED
