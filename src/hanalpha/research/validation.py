from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from hanalpha.pit.models import require_aware


class WalkForwardFold(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]


class LabelInterval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_id: str
    information_start: datetime
    label_end: datetime

    def model_post_init(self, __context: object) -> None:
        require_aware(self.information_start, "information_start")
        require_aware(self.label_end, "label_end")
        if self.label_end < self.information_start:
            raise ValueError("label interval ends before it starts")


def purge_overlapping_labels(
    train: tuple[LabelInterval, ...],
    test: tuple[LabelInterval, ...],
) -> tuple[LabelInterval, ...]:
    def overlaps(left: LabelInterval, right: LabelInterval) -> bool:
        return (
            left.information_start <= right.label_end and right.information_start <= left.label_end
        )

    return tuple(
        candidate
        for candidate in train
        if not any(overlaps(candidate, test_item) for test_item in test)
    )


def rolling_walk_forward(
    *,
    observation_count: int,
    train_size: int,
    test_size: int,
    step: int,
    purge: int,
    embargo: int,
) -> list[WalkForwardFold]:
    if min(observation_count, train_size, test_size, step) <= 0:
        raise ValueError("walk-forward sizes must be positive")
    if purge < 0 or embargo < 0:
        raise ValueError("purge and embargo must not be negative")
    folds: list[WalkForwardFold] = []
    raw_train_end = train_size
    while True:
        test_start = raw_train_end + embargo
        test_end = test_start + test_size
        if test_end > observation_count:
            break
        train_end = raw_train_end - purge
        if train_end > 0:
            folds.append(
                WalkForwardFold(
                    train_indices=tuple(range(max(0, raw_train_end - train_size), train_end)),
                    test_indices=tuple(range(test_start, test_end)),
                )
            )
        raw_train_end += step
    return folds
