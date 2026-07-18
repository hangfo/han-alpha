from __future__ import annotations

import math
from decimal import Decimal
from itertools import pairwise

import numpy as np
from pydantic import BaseModel, ConfigDict

from hanalpha.simulation.events import EquityPoint

__all__ = ["EquityPoint", "PortfolioMetrics", "compute_portfolio_metrics"]


class PortfolioMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total_return: Decimal
    max_drawdown: Decimal
    turnover: Decimal
    average_gross_exposure: Decimal
    time_weighted_exposure_ratio: Decimal
    time_in_market: Decimal
    ending_equity: Decimal
    observations: int
    annualized_return: Decimal | None = None
    annualized_volatility: Decimal | None = None
    sharpe_ratio: Decimal | None = None
    sortino_ratio: Decimal | None = None
    calmar_ratio: Decimal | None = None
    expected_shortfall_95: Decimal | None = None
    time_under_water: Decimal


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
    underwater_intervals = Decimal("0")
    total_intervals = Decimal("0")
    for item in points:
        peak = max(peak, item.net_liquidation)
        drawdown = (peak - item.net_liquidation) / peak if peak > 0 else Decimal("0")
        max_drawdown = max(max_drawdown, drawdown)
    if len(points) == 1:
        average_gross = points[0].gross_exposure
        exposure_ratio = points[0].gross_exposure
        time_in_market = Decimal("1") if points[0].gross_exposure > 0 else Decimal("0")
    else:
        weights = [
            Decimal(str((right.as_of - left.as_of).total_seconds()))
            for left, right in pairwise(points)
        ]
        if any(weight <= 0 for weight in weights):
            raise ValueError("equity point times must be strictly increasing")
        duration = sum(weights, Decimal("0"))
        average_gross = sum((point.gross_exposure for point in points), Decimal("0")) / Decimal(
            len(points)
        )
        weighted_exposure = sum(
            (
                point.gross_exposure * weight
                for point, weight in zip(points[:-1], weights, strict=True)
            ),
            Decimal("0"),
        )
        exposure_ratio = weighted_exposure / duration
        time_in_market = (
            sum(
                (
                    weight
                    for point, weight in zip(points[:-1], weights, strict=True)
                    if point.gross_exposure > 0
                ),
                Decimal("0"),
            )
            / duration
        )
        running_peak = points[0].net_liquidation
        for point, weight in zip(points[:-1], weights, strict=True):
            running_peak = max(running_peak, point.net_liquidation)
            total_intervals += weight
            if point.net_liquidation < running_peak:
                underwater_intervals += weight
    annual_return, annual_vol, sharpe, sortino, expected_shortfall = _risk_metrics(points)
    calmar = (
        annual_return / max_drawdown if annual_return is not None and max_drawdown > 0 else None
    )
    return PortfolioMetrics(
        total_return=points[-1].net_liquidation / starting - Decimal("1"),
        max_drawdown=max_drawdown,
        turnover=total_traded_notional / starting,
        average_gross_exposure=average_gross,
        time_weighted_exposure_ratio=exposure_ratio,
        time_in_market=time_in_market,
        ending_equity=points[-1].net_liquidation,
        observations=len(points),
        annualized_return=annual_return,
        annualized_volatility=annual_vol,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        expected_shortfall_95=expected_shortfall,
        time_under_water=(
            underwater_intervals / total_intervals if total_intervals else Decimal("0")
        ),
    )


def _risk_metrics(
    points: list[EquityPoint],
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
    if len(points) < 3:
        return None, None, None, None, None
    elapsed_years = (points[-1].as_of - points[0].as_of).total_seconds() / (365.25 * 86400)
    if elapsed_years <= 0:
        return None, None, None, None, None
    equities = np.asarray([float(point.net_liquidation) for point in points], dtype=float)
    returns = equities[1:] / equities[:-1] - 1
    periods_per_year = len(returns) / elapsed_years
    total_return = equities[-1] / equities[0]
    annual_return = total_return ** (1 / elapsed_years) - 1 if total_return > 0 else -1.0
    annual_vol = float(np.std(returns, ddof=1) * math.sqrt(periods_per_year))
    mean = float(np.mean(returns))
    sharpe = (
        mean / float(np.std(returns, ddof=1)) * math.sqrt(periods_per_year) if annual_vol else None
    )
    downside = returns[returns < 0]
    downside_deviation = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0
    sortino = (
        mean / downside_deviation * math.sqrt(periods_per_year) if downside_deviation else None
    )
    tail_count = max(1, math.ceil(len(returns) * 0.05))
    expected_shortfall = float(np.mean(np.sort(returns)[:tail_count]))
    return (
        Decimal(str(annual_return)),
        Decimal(str(annual_vol)),
        Decimal(str(sharpe)) if sharpe is not None else None,
        Decimal(str(sortino)) if sortino is not None else None,
        Decimal(str(expected_shortfall)),
    )
