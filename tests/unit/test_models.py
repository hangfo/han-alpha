from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from hanalpha.domain.models import Bar, Quote


def test_bar_rejects_impossible_high() -> None:
    with pytest.raises(ValidationError):
        Bar(
            symbol="X",
            timestamp=datetime.now(UTC),
            open=10,
            high=9,
            low=8,
            close=10,
            volume=100,
        )


def test_quote_rejects_crossed_market() -> None:
    with pytest.raises(ValidationError):
        Quote(
            symbol="X",
            timestamp=datetime.now(UTC),
            bid=11,
            ask=10,
            last=10.5,
        )


def test_quote_requires_timezone() -> None:
    with pytest.raises(ValidationError):
        Quote(symbol="X", timestamp=datetime.now(), bid=10, ask=11, last=10.5)
