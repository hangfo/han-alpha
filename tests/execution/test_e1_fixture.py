from __future__ import annotations

import importlib.util
import json
from argparse import Namespace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

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
        "side": "BUY",
        "quote_capsule": None,
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


def _contract_details(**contract_overrides):
    contract_values = {
        "conId": 756733,
        "symbol": "SPY",
        "secType": "STK",
        "currency": "USD",
        "exchange": "SMART",
        "primaryExchange": "ARCA",
        **contract_overrides,
    }
    contract = SimpleNamespace(**contract_values)
    return SimpleNamespace(
        contract=contract,
        timeZoneId="America/New_York",
        liquidHours="20260729:0930-20260729:1600",
    )


def test_quote_capsule_requires_exact_realtime_regular_tight_market() -> None:
    observed = datetime(2026, 7, 29, 15, 0, tzinfo=UTC)
    capsule = fixture._quote_capsule_body(
        account_identity_hash="a" * 64,
        details=_contract_details(),
        ticks={"bid": Decimal("630.00"), "ask": Decimal("630.01"), "last": Decimal("630.00")},
        market_data_type=1,
        observed_at=observed,
    )
    assert capsule["decision"] == "PASS"
    assert capsule["con_id"] == 756733
    with pytest.raises(ValueError, match="real-time"):
        fixture._quote_capsule_body(
            account_identity_hash="a" * 64,
            details=_contract_details(),
            ticks={"bid": Decimal("630"), "ask": Decimal("630.01"), "last": Decimal("630")},
            market_data_type=3,
            observed_at=observed,
        )
    with pytest.raises(ValueError, match="spread"):
        fixture._quote_capsule_body(
            account_identity_hash="a" * 64,
            details=_contract_details(),
            ticks={"bid": Decimal("630"), "ask": Decimal("631"), "last": Decimal("630")},
            market_data_type=1,
            observed_at=observed,
        )
    with pytest.raises(ValueError, match="exact SMART"):
        fixture._quote_capsule_body(
            account_identity_hash="a" * 64,
            details=_contract_details(conId=0),
            ticks={"bid": Decimal("630"), "ask": Decimal("630.01"), "last": Decimal("630")},
            market_data_type=1,
            observed_at=observed,
        )


def test_stale_quote_capsule_and_off_collar_permit_are_rejected(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed = datetime(2026, 7, 29, 15, 0, tzinfo=UTC)
    body = fixture._quote_capsule_body(
        account_identity_hash="a" * 64,
        details=_contract_details(),
        ticks={"bid": Decimal("630.00"), "ask": Decimal("630.01"), "last": Decimal("630.00")},
        market_data_type=1,
        observed_at=observed,
    )
    capsule = {"artifact_id": fixture.canonical_hash(body), **body}
    path = tmp_path / f"{capsule['artifact_id']}.quote.json"
    path.write_text(json.dumps(capsule), encoding="utf-8")
    monkeypatch.setattr(fixture, "_utc_now", lambda: observed + fixture.timedelta(seconds=30))
    with pytest.raises(ValueError, match="stale"):
        fixture._load_quote_capsule(path)
    monkeypatch.setattr(fixture, "_utc_now", lambda: observed + fixture.timedelta(seconds=1))
    with pytest.raises(ValueError, match="ask collar"):
        fixture._permit_body(
            _args(
                symbol="SPY",
                limit_price="629",
                quote_capsule=path,
            ),
            "a" * 64,
        )


@pytest.mark.parametrize(
    ("status", "open_seen", "errors", "expected"),
    (
        ("Submitted", True, [], "BROKER_ACCEPTED_OPEN"),
        ("Filled", False, [], "BROKER_FILLED"),
        ("Cancelled", False, [], "BROKER_CANCELLED"),
        ("Inactive", True, [], "BROKER_REJECTED"),
        (None, False, [], "OUTCOME_UNKNOWN"),
        ("Submitted", True, [(201, "rejected")], "BROKER_REJECTED"),
        (
            "Submitted",
            True,
            [(2104, "market data farm connection is OK")],
            "BROKER_ACCEPTED_OPEN",
        ),
    ),
)
def test_fixture_outcomes_are_phase_precise(status, open_seen, errors, expected) -> None:
    assert (
        fixture._classify_outcome(
            fixture.FixtureAction.PLACE,
            status=status,
            open_order_seen=open_seen,
            errors=errors,
        )
        == expected
    )


def test_fixture_error_callback_parses_current_ibapi_signature() -> None:
    app = fixture.FixtureClient()
    app.error(1, 1_785_336_346_000, 354, "not subscribed", "")
    assert app.errors == [(354, "not subscribed")]


def test_modify_cannot_flip_side_or_contract() -> None:
    class FakeApp:
        def __init__(self):
            self.open_orders_end = fixture.threading.Event()
            self.open_orders = {
                7: (
                    SimpleNamespace(conId=11, symbol="SPY", secType="STK"),
                    SimpleNamespace(
                        orderRef="E1FIX:known",
                        action="SELL",
                        orderType="LMT",
                        totalQuantity=1,
                        account="paper",
                    ),
                )
            }
            self.status_by_order = {}
            self.order_update = fixture.threading.Event()

        def reqOpenOrders(self):
            self.open_orders_end.set()

    permit = {
        "action": "MODIFY",
        "broker_order_id": 7,
        "expected_order_ref": "E1FIX:known",
        "con_id": 11,
        "symbol": "SPY",
        "side": "BUY",
        "quantity": 1,
        "limit_price": "630",
    }
    with pytest.raises(PermissionError, match="cannot flip"):
        fixture._execute_action(FakeApp(), permit, "paper")


def test_lifecycle_records_unknown_write_and_cleanup_requires_baseline(tmp_path) -> None:
    ledger = tmp_path / "lifecycle.sqlite3"
    connection = fixture._initialize_lifecycle_ledger(ledger)
    try:
        connection.execute(
            "INSERT INTO fixture_lifecycles VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("lifecycle", "q" * 64, "a" * 64, 11, "SPY", "0", "now", "STARTED"),
        )
        connection.commit()
    finally:
        connection.close()
    permit = {
        "artifact_id": "p" * 64,
        "account_identity_hash": "a" * 64,
        "con_id": 11,
    }
    receipt = {
        "artifact_id": "r" * 64,
        "decision": "OUTCOME_UNKNOWN",
        "observed_at": "2026-07-29T15:00:00+00:00",
    }
    fixture._record_lifecycle_action(ledger, "lifecycle", permit, receipt)
    assert fixture._load_lifecycle(ledger, "lifecycle")["state"] == "CLEANUP_REQUIRED"
    lifecycle = fixture._load_lifecycle(ledger, "lifecycle")
    assert not fixture._cleanup_is_complete(
        lifecycle,
        {"fixture_orders": [{"order_ref": "E1FIX:x"}], "positions": {"11": "0"}},
    )
    assert not fixture._cleanup_is_complete(
        lifecycle,
        {"fixture_orders": [], "positions": {"11": "1"}},
    )
    assert fixture._cleanup_is_complete(
        lifecycle,
        {"fixture_orders": [], "positions": {"11": "0"}},
    )


def test_lifecycle_is_validated_before_every_fixture_write(tmp_path) -> None:
    ledger = tmp_path / "lifecycle.sqlite3"
    connection = fixture._initialize_lifecycle_ledger(ledger)
    try:
        connection.execute(
            "INSERT INTO fixture_lifecycles VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("lifecycle", "q" * 64, "a" * 64, 11, "SPY", "0", "now", "STARTED"),
        )
        connection.execute(
            "INSERT INTO fixture_lifecycles VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("closed", "q" * 64, "a" * 64, 11, "SPY", "0", "now", "CLEAN"),
        )
        connection.commit()
    finally:
        connection.close()
    permit = {
        "account_identity_hash": "a" * 64,
        "symbol": "SPY",
        "con_id": 11,
        "quote_capsule_id": "q" * 64,
    }
    assert fixture._validate_lifecycle_action(ledger, "lifecycle", permit)["state"] == "STARTED"
    with pytest.raises(PermissionError, match="contract mismatch"):
        fixture._validate_lifecycle_action(
            ledger,
            "lifecycle",
            {**permit, "con_id": 12},
        )
    with pytest.raises(PermissionError, match="already clean"):
        fixture._validate_lifecycle_action(ledger, "closed", permit)
