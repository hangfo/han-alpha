from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from hanalpha.pit.context import AsOfContext


def test_as_of_context_rejects_naive_time(snapshot_id: str) -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        AsOfContext(snapshot_id=snapshot_id, as_of=datetime(2024, 1, 1))


def test_record_rejects_inverted_availability(price_bar) -> None:
    with pytest.raises(ValidationError, match="ingested_at"):
        price_bar.model_copy(
            update={"ingested_at": price_bar.available_at - timedelta(seconds=1)}
        ).model_validate(
            price_bar.model_copy(
                update={"ingested_at": price_bar.available_at - timedelta(seconds=1)}
            ).model_dump()
        )


def test_record_rejects_invalid_validity_interval(alias) -> None:
    data = alias.model_dump()
    data["valid_to"] = alias.valid_from
    with pytest.raises(ValidationError, match="valid_to"):
        type(alias).model_validate(data)


def test_record_rejects_unknown_availability(price_bar) -> None:
    data = price_bar.model_dump()
    del data["available_at"]
    with pytest.raises(ValidationError, match="available_at"):
        type(price_bar).model_validate(data)
