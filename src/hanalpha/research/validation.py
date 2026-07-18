from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class WalkForwardFold(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]


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
