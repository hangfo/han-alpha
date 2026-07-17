from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hanalpha.pit.models import HASH_PATTERN, require_aware


class AsOfContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str = Field(pattern=HASH_PATTERN)
    as_of: datetime

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: datetime) -> datetime:
        require_aware(value, "as_of")
        return value


def localize_exchange_time(
    wall_time: datetime, zone_name: str, *, fold: int | None = None
) -> datetime:
    """Convert a naive exchange wall time to UTC, rejecting DST gaps/ambiguity."""
    if wall_time.tzinfo is not None:
        raise ValueError("exchange wall_time must be naive")
    if fold not in {None, 0, 1}:
        raise ValueError("fold must be 0, 1, or None")
    zone = ZoneInfo(zone_name)
    candidates: list[datetime] = []
    for candidate_fold in (0, 1):
        candidate = wall_time.replace(tzinfo=zone, fold=candidate_fold)
        round_trip = candidate.astimezone(UTC).astimezone(zone)
        if round_trip.replace(tzinfo=None) == wall_time and round_trip.fold == candidate_fold:
            candidates.append(candidate)
    distinct = {candidate.utcoffset() for candidate in candidates}
    if not candidates:
        raise ValueError("exchange wall_time is nonexistent due to DST transition")
    if len(distinct) > 1 and fold is None:
        raise ValueError("exchange wall_time is ambiguous; explicit fold is required")
    selected_fold = 0 if fold is None else fold
    for candidate in candidates:
        if candidate.fold == selected_fold:
            return candidate.astimezone(UTC)
    raise ValueError("requested fold is invalid for exchange wall_time")
