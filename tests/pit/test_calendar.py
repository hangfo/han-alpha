from __future__ import annotations

from datetime import UTC, date, datetime

from hanalpha.pit.calendar import ExchangeCalendar, MarketPhase


def test_exchange_calendar_classifies_dst_and_weekend_decision_points() -> None:
    calendar = ExchangeCalendar()
    assert calendar.phase(datetime(2024, 3, 8, 13, tzinfo=UTC)) == MarketPhase.PRE_MARKET
    assert calendar.phase(datetime(2024, 3, 11, 14, tzinfo=UTC)) == MarketPhase.RTH
    assert calendar.phase(datetime(2024, 11, 4, 22, tzinfo=UTC)) == MarketPhase.POST_MARKET
    assert calendar.phase(datetime(2024, 11, 2, 16, tzinfo=UTC)) == MarketPhase.CLOSED


def test_exchange_calendar_accepts_explicit_holiday_set() -> None:
    calendar = ExchangeCalendar(holidays=frozenset({date(2024, 7, 4)}))
    assert calendar.phase(datetime(2024, 7, 4, 15, tzinfo=UTC)) == MarketPhase.CLOSED
