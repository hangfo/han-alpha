from __future__ import annotations

from datetime import datetime

import pytest

from hanalpha.pit.context import localize_exchange_time


def test_dst_nonexistent_wall_time_fails_closed() -> None:
    with pytest.raises(ValueError, match="nonexistent"):
        localize_exchange_time(datetime(2024, 3, 10, 2, 30), "America/New_York")


def test_dst_ambiguous_wall_time_requires_explicit_fold() -> None:
    wall_time = datetime(2024, 11, 3, 1, 30)
    with pytest.raises(ValueError, match="ambiguous"):
        localize_exchange_time(wall_time, "America/New_York")
    first = localize_exchange_time(wall_time, "America/New_York", fold=0)
    second = localize_exchange_time(wall_time, "America/New_York", fold=1)
    assert first != second
    assert abs((second - first).total_seconds()) == 3600
