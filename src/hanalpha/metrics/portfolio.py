from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from hanalpha.simulation.events import EquityPoint

__all__ = ["EquityPoint", "PortfolioMetrics", "compute_portfolio_metrics"]


class PortfolioMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total_return: Decimal
    max_drawdown: Decimal
    turnover: Decimal
    average_gross_exposure: Decimal
    ending_equity: Decimal
    observations: int


def compute_portfolio_metrics(
    points: list[EquityPoint], *, total_traded_notional: Decimal
) -> PortfolioMetrics:
    if not points:
        raise ValueError("metrics require equity points")
    if [item.as_of for item in points] != sorted(item.as_of for item in points):
        raise ValueError("equity points must be monotonic")
    starting = points[0].net_liquidation
    if starting <= 0:
        raise ValueError("starting equity must be positive")
    peak = starting
    max_drawdown = Decimal("0")
    for item in points:
        peak = max(peak, item.net_liquidation)
        drawdown = (peak - item.net_liquidation) / peak if peak > 0 else Decimal("0")
        max_drawdown = max(max_drawdown, drawdown)
    average_gross = sum((item.gross_exposure for item in points), Decimal("0")) / Decimal(
        len(points)
    )
    return PortfolioMetrics(
        total_return=points[-1].net_liquidation / starting - Decimal("1"),
        max_drawdown=max_drawdown,
        turnover=total_traded_notional / starting,
        average_gross_exposure=average_gross,
        ending_equity=points[-1].net_liquidation,
        observations=len(points),
    )
