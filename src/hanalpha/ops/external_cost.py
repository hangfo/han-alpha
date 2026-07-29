from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic_core import to_jsonable_python

from hanalpha.simulation.events import canonical_hash


class ExternalProvider(StrEnum):
    IBKR = "IBKR"
    SEC = "SEC_EDGAR"
    MASSIVE = "MASSIVE"
    FRED = "FRED_ALFRED"


class ExternalAction(StrEnum):
    STREAMING_QUOTE = "STREAMING_QUOTE"
    REGULATORY_SNAPSHOT = "REGULATORY_SNAPSHOT"
    PAPER_FIXTURE = "PAPER_FIXTURE"
    BOUNDED_GET = "BOUNDED_GET"


def external_cost_receipt(
    *,
    provider: ExternalProvider,
    action: ExternalAction,
    request_count: int,
    max_new_cost: Decimal,
    existing_entitlement: bool,
    current_plan: str | None = None,
    at: datetime | None = None,
) -> dict[str, Any]:
    if request_count < 1:
        raise ValueError("external request count must be positive")
    reasons: list[str] = []
    expected: Decimal | None = None
    if max_new_cost != 0:
        reasons.append("ONLY_ZERO_INCREMENTAL_COST_IS_SUPPORTED")
    if action is ExternalAction.REGULATORY_SNAPSHOT:
        reasons.append("METERED_REGULATORY_SNAPSHOT_FORBIDDEN")
    elif provider is ExternalProvider.FRED:
        reasons.append("FRED_POLICY_REVIEW_REQUIRED")
    elif provider is ExternalProvider.IBKR:
        if (action is ExternalAction.STREAMING_QUOTE and existing_entitlement) or action is ExternalAction.PAPER_FIXTURE:
            expected = Decimal("0")
        else:
            reasons.append("EXISTING_ENTITLEMENT_NOT_CONFIRMED")
    elif provider is ExternalProvider.SEC:
        if action is ExternalAction.BOUNDED_GET and request_count <= 2:
            expected = Decimal("0")
        else:
            reasons.append("SEC_PROOF_RUN_LIMIT_EXCEEDED")
    elif provider is ExternalProvider.MASSIVE:
        if (
            action is ExternalAction.BOUNDED_GET
            and request_count <= 3
            and current_plan in {"BASIC_FREE", "EXISTING_FIXED_SUBSCRIPTION"}
            and existing_entitlement
        ):
            expected = Decimal("0")
        else:
            reasons.append("MASSIVE_PLAN_OR_ENTITLEMENT_UNCONFIRMED")
    if expected is None:
        reasons.append("INCREMENTAL_COST_UNKNOWN")
    elif expected > max_new_cost:
        reasons.append("INCREMENTAL_COST_EXCEEDS_LIMIT")
    body = to_jsonable_python(
        {
            "schema_version": "external-cost-receipt-v1",
            "artifact_type": "EXTERNAL_COST_RECEIPT",
            "provider": provider,
            "action": action,
            "request_count": request_count,
            "current_plan": current_plan,
            "existing_entitlement": existing_entitlement,
            "expected_incremental_cost_usd": (str(expected) if expected is not None else "UNKNOWN"),
            "max_new_cost_usd": str(max_new_cost),
            "metered_request": action is ExternalAction.REGULATORY_SNAPSHOT,
            "decision": "ALLOW" if not reasons else "BLOCK",
            "reasons": sorted(set(reasons)),
            "evaluated_at": (at or datetime.now(UTC)).astimezone(UTC),
            "secrets_redacted": True,
        }
    )
    if not isinstance(body, dict):
        raise TypeError("cost receipt must normalize to an object")
    return {"artifact_id": canonical_hash(body), **body}
