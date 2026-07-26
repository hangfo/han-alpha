from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from hanalpha.execution.control_models import QuoteSnapshot


class QuoteAdmissionResult(BaseModel):
    """Deterministic quote evidence decision shared by Arm, Ops and future Permit gates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    eligible: bool
    reasons: tuple[str, ...]
    valid_until: datetime
    observed_age_seconds: float
    provider_age_seconds: float
    spread_bps: Decimal
    drift_bps: Decimal | None = None


def evaluate_quote_admission(
    quote: QuoteSnapshot,
    *,
    at: datetime,
    quote_max_age: timedelta = timedelta(seconds=5),
    provider_clock_skew: timedelta = timedelta(seconds=1),
    max_spread_bps: Decimal = Decimal("50"),
    expected_symbol: str | None = None,
    expected_currency: str | None = None,
    reference_limit_price: Decimal | None = None,
    side: str | None = None,
    max_drift_bps: Decimal | None = None,
) -> QuoteAdmissionResult:
    """Evaluate only source-backed quote facts and return their hard expiry.

    Optional intent bindings are omitted by the read-only Ops projection. Therefore
    an Ops PASS means that the latest quote is intrinsically eligible, not that a
    particular intent or Permit is executable.
    """

    reasons: list[str] = []
    observed_age = at - quote.observed_at
    provider_age = at - quote.provider_timestamp
    if observed_age < timedelta(0):
        reasons.append("OBSERVED_AT_IN_FUTURE")
    elif observed_age > quote_max_age:
        reasons.append("OBSERVED_QUOTE_STALE")
    if provider_age < -provider_clock_skew:
        reasons.append("PROVIDER_TIMESTAMP_IN_FUTURE")
    elif provider_age > quote_max_age:
        reasons.append("PROVIDER_QUOTE_STALE")
    if quote.provider_timestamp > quote.observed_at + provider_clock_skew:
        reasons.append("PROVIDER_AFTER_OBSERVATION_TOLERANCE")
    if quote.feed_mode != "REALTIME":
        reasons.append("FEED_NOT_REALTIME")
    if quote.market_phase not in {"REGULAR", "OPEN"}:
        reasons.append("MARKET_PHASE_INELIGIBLE")
    if quote.venue in {"", "UNKNOWN"}:
        reasons.append("VENUE_NOT_AUTHORITATIVE")
    if expected_symbol is not None and quote.symbol != expected_symbol:
        reasons.append("SYMBOL_MISMATCH")
    if expected_currency is not None and quote.currency != expected_currency:
        reasons.append("CURRENCY_MISMATCH")
    midpoint = (quote.bid + quote.ask) / Decimal("2")
    spread_bps = (quote.ask - quote.bid) / midpoint * Decimal("10000")
    if spread_bps > max_spread_bps:
        reasons.append("SPREAD_TOO_WIDE")
    drift_bps: Decimal | None = None
    if reference_limit_price is not None:
        if side not in {"BUY", "SELL"} or max_drift_bps is None:
            raise ValueError("intent-bound quote evaluation requires side and max_drift_bps")
        executable_price = quote.ask if side == "BUY" else quote.bid
        drift_bps = (
            abs(executable_price - reference_limit_price)
            / reference_limit_price
            * Decimal("10000")
        )
        if drift_bps > max_drift_bps:
            reasons.append("PRICE_DRIFT_TOO_LARGE")
    valid_until = min(
        quote.observed_at + quote_max_age,
        quote.provider_timestamp + quote_max_age,
    )
    return QuoteAdmissionResult(
        eligible=not reasons and valid_until > at,
        reasons=tuple(reasons),
        valid_until=valid_until,
        observed_age_seconds=observed_age.total_seconds(),
        provider_age_seconds=provider_age.total_seconds(),
        spread_bps=spread_bps,
        drift_bps=drift_bps,
    )
