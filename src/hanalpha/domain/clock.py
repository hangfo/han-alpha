from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


def ensure_aware_utc(value: datetime, *, name: str = "as_of") -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


class DecisionClock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True)
class SystemDecisionClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class FixedDecisionClock:
    as_of: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", ensure_aware_utc(self.as_of))

    def now(self) -> datetime:
        return self.as_of
