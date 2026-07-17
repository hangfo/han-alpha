from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from hanalpha.pit.models import CorporateActionRecord, CorporateActionType, require_aware


class AdjustmentPolicy(StrEnum):
    RAW = "raw"
    SPLIT = "split"
    SPLIT_AND_CASH = "split_and_cash"


class AdjustedPrice(BaseModel):
    model_config = ConfigDict(frozen=True)
    value: float
    policy: AdjustmentPolicy
    action_ids: list[str]
    snapshot_id: str | None = None
    policy_version: str = "1"


def adjust_price(
    raw_value: float,
    *,
    price_time: datetime,
    as_of: datetime,
    actions: list[CorporateActionRecord],
    policy: AdjustmentPolicy,
) -> AdjustedPrice:
    require_aware(price_time, "price_time")
    require_aware(as_of, "as_of")
    value = float(raw_value)
    applied: list[str] = []
    snapshot_ids = {action.snapshot_id for action in actions}
    if len(snapshot_ids) > 1:
        raise ValueError("corporate actions must come from one snapshot")
    snapshot_id = next(iter(snapshot_ids), None)
    if policy == AdjustmentPolicy.RAW:
        return AdjustedPrice(
            value=value, policy=policy, action_ids=[], snapshot_id=snapshot_id
        )
    for action in sorted(actions, key=lambda item: (item.event_time, item.record_id)):
        if not (price_time < action.event_time <= as_of and action.available_at <= as_of):
            continue
        if action.action_type == CorporateActionType.SPLIT and action.ratio is not None:
            value /= action.ratio
            applied.append(action.record_id)
        elif (
            policy == AdjustmentPolicy.SPLIT_AND_CASH
            and action.action_type == CorporateActionType.DIVIDEND
            and action.cash_amount is not None
        ):
            value -= action.cash_amount
            applied.append(action.record_id)
    return AdjustedPrice(
        value=value, policy=policy, action_ids=applied, snapshot_id=snapshot_id
    )
