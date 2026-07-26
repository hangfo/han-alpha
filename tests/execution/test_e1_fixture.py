from __future__ import annotations

import importlib.util
from argparse import Namespace
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "e1_paper_fixture.py"
SPEC = importlib.util.spec_from_file_location("e1_paper_fixture", SCRIPT)
assert SPEC and SPEC.loader
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


def _args(**overrides):
    values = {
        "action": "PLACE",
        "symbol": "AAPL",
        "quantity": 1,
        "limit_price": "100",
        "port": 7497,
        "client_id": 9100,
        "broker_order_id": None,
        "expected_order_ref": None,
        "attest_paper": True,
    }
    values.update(overrides)
    return Namespace(**values)


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"port": 7496}, "non-Paper"),
        ({"client_id": 41}, "reserved range"),
        ({"quantity": 2}, "exactly one"),
        ({"limit_price": "1000.01"}, "hard ceiling"),
        ({"attest_paper": False}, "attest-paper"),
        ({"symbol": "AAPL OPT"}, "ASCII stock/ETF"),
    ),
)
def test_fixture_permit_fails_closed(overrides, message) -> None:
    with pytest.raises(ValueError, match=message):
        fixture._permit_body(_args(**overrides), "a" * 64)


def test_fixture_modify_cancel_are_bound_to_own_namespace() -> None:
    with pytest.raises(ValueError, match="exact broker"):
        fixture._permit_body(_args(action="CANCEL"), "a" * 64)
    with pytest.raises(ValueError, match="own namespace"):
        fixture._permit_body(
            _args(
                action="MODIFY",
                broker_order_id=1,
                expected_order_ref="HA:not-fixture",
            ),
            "a" * 64,
        )


def test_fixture_permit_consumption_is_atomic_and_one_shot(tmp_path) -> None:
    ledger = tmp_path / "consumed.sqlite3"
    fixture._consume_permit_once(ledger, "a" * 64)
    with pytest.raises(fixture.sqlite3.IntegrityError):
        fixture._consume_permit_once(ledger, "a" * 64)
