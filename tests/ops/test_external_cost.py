from datetime import UTC, datetime
from decimal import Decimal

import pytest

from hanalpha.ops.external_cost import (
    ExternalAction,
    ExternalProvider,
    external_cost_receipt,
)

NOW = datetime(2026, 7, 30, tzinfo=UTC)


def test_zero_cost_policy_allows_only_known_existing_entitlements() -> None:
    ibkr = external_cost_receipt(
        provider=ExternalProvider.IBKR,
        action=ExternalAction.STREAMING_QUOTE,
        request_count=1,
        max_new_cost=Decimal("0"),
        existing_entitlement=True,
        at=NOW,
    )
    assert ibkr["decision"] == "ALLOW"
    assert ibkr["expected_incremental_cost_usd"] == "0"

    unknown_massive = external_cost_receipt(
        provider=ExternalProvider.MASSIVE,
        action=ExternalAction.BOUNDED_GET,
        request_count=3,
        max_new_cost=Decimal("0"),
        existing_entitlement=True,
        current_plan=None,
        at=NOW,
    )
    assert unknown_massive["decision"] == "BLOCK"
    assert unknown_massive["expected_incremental_cost_usd"] == "UNKNOWN"


def test_fred_and_regulatory_snapshots_fail_closed() -> None:
    fred = external_cost_receipt(
        provider=ExternalProvider.FRED,
        action=ExternalAction.BOUNDED_GET,
        request_count=1,
        max_new_cost=Decimal("0"),
        existing_entitlement=True,
        at=NOW,
    )
    snapshot = external_cost_receipt(
        provider=ExternalProvider.IBKR,
        action=ExternalAction.REGULATORY_SNAPSHOT,
        request_count=1,
        max_new_cost=Decimal("0"),
        existing_entitlement=True,
        at=NOW,
    )
    assert fred["decision"] == "BLOCK"
    assert "FRED_POLICY_REVIEW_REQUIRED" in fred["reasons"]
    assert snapshot["decision"] == "BLOCK"
    assert "METERED_REGULATORY_SNAPSHOT_FORBIDDEN" in snapshot["reasons"]


@pytest.mark.parametrize(
    ("provider", "action", "count", "entitled", "plan", "decision", "reason"),
    [
        (
            ExternalProvider.SEC,
            ExternalAction.BOUNDED_GET,
            2,
            False,
            None,
            "ALLOW",
            None,
        ),
        (
            ExternalProvider.SEC,
            ExternalAction.BOUNDED_GET,
            3,
            False,
            None,
            "BLOCK",
            "SEC_PROOF_RUN_LIMIT_EXCEEDED",
        ),
        (
            ExternalProvider.MASSIVE,
            ExternalAction.BOUNDED_GET,
            3,
            True,
            "BASIC_FREE",
            "ALLOW",
            None,
        ),
        (
            ExternalProvider.MASSIVE,
            ExternalAction.BOUNDED_GET,
            4,
            True,
            "EXISTING_FIXED_SUBSCRIPTION",
            "BLOCK",
            "MASSIVE_PLAN_OR_ENTITLEMENT_UNCONFIRMED",
        ),
        (
            ExternalProvider.IBKR,
            ExternalAction.STREAMING_QUOTE,
            1,
            False,
            None,
            "BLOCK",
            "EXISTING_ENTITLEMENT_NOT_CONFIRMED",
        ),
        (
            ExternalProvider.IBKR,
            ExternalAction.PAPER_FIXTURE,
            1,
            False,
            None,
            "ALLOW",
            None,
        ),
    ],
)
def test_provider_specific_zero_cost_boundaries(
    provider,
    action,
    count,
    entitled,
    plan,
    decision,
    reason,
) -> None:
    receipt = external_cost_receipt(
        provider=provider,
        action=action,
        request_count=count,
        max_new_cost=Decimal("0"),
        existing_entitlement=entitled,
        current_plan=plan,
        at=NOW,
    )
    assert receipt["decision"] == decision
    if reason is not None:
        assert reason in receipt["reasons"]
    else:
        assert receipt["reasons"] == []


def test_cost_receipt_rejects_nonzero_policy_and_invalid_count() -> None:
    blocked = external_cost_receipt(
        provider=ExternalProvider.SEC,
        action=ExternalAction.BOUNDED_GET,
        request_count=1,
        max_new_cost=Decimal("1"),
        existing_entitlement=False,
        at=NOW,
    )
    assert blocked["decision"] == "BLOCK"
    assert "ONLY_ZERO_INCREMENTAL_COST_IS_SUPPORTED" in blocked["reasons"]
    negative_limit = external_cost_receipt(
        provider=ExternalProvider.SEC,
        action=ExternalAction.BOUNDED_GET,
        request_count=1,
        max_new_cost=Decimal("-1"),
        existing_entitlement=False,
        at=NOW,
    )
    assert "INCREMENTAL_COST_EXCEEDS_LIMIT" in negative_limit["reasons"]
    with pytest.raises(ValueError, match="positive"):
        external_cost_receipt(
            provider=ExternalProvider.SEC,
            action=ExternalAction.BOUNDED_GET,
            request_count=0,
            max_new_cost=Decimal("0"),
            existing_entitlement=False,
            at=NOW,
        )
