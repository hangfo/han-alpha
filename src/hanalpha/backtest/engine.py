from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from hanalpha.domain.enums import SignalAction
from hanalpha.domain.models import BacktestMetrics, Bar, Catalyst
from hanalpha.strategies.base import Strategy


@dataclass
class BacktestTrade:
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    reason: str


@dataclass
class _ActivePosition:
    entry_time: datetime
    entry_price: float
    quantity: int
    stop: float
    target: float
    entry_index: int


class BacktestEngine:
    """Long-only, one-position event-driven verifier with explicit costs and no look-ahead."""

    def __init__(
        self,
        *,
        starting_cash: float = 100_000,
        risk_per_trade_pct: float = 0.005,
        slippage_bps: float = 5,
        commission_per_share: float = 0.005,
    ) -> None:
        self.starting_cash = starting_cash
        self.risk_per_trade_pct = risk_per_trade_pct
        self.slippage_bps = slippage_bps
        self.commission_per_share = commission_per_share

    def run(
        self,
        *,
        symbol: str,
        bars: list[Bar],
        benchmark_bars: list[Bar],
        strategy: Strategy,
        catalysts: list[Catalyst] | None = None,
        warmup: int = 60,
    ) -> tuple[BacktestMetrics, list[BacktestTrade]]:
        if len(bars) != len(benchmark_bars):
            raise ValueError("symbol and benchmark bars must be aligned")
        if len(bars) <= warmup:
            raise ValueError("insufficient bars")
        catalysts = catalysts or []
        cash = self.starting_cash
        equity_curve: list[float] = [cash]
        trades: list[BacktestTrade] = []
        position: _ActivePosition | None = None
        for index in range(warmup, len(bars)):
            history = bars[: index + 1]
            benchmark_history = benchmark_bars[: index + 1]
            current = bars[index]
            available_catalysts = [item for item in catalysts if item.available_at <= current.timestamp]
            if position:
                exit_price: float | None = None
                reason = ""
                if current.low <= position.stop:
                    exit_price = position.stop * (1 - self.slippage_bps / 10_000)
                    reason = "stop"
                elif current.high >= position.target:
                    exit_price = position.target * (1 - self.slippage_bps / 10_000)
                    reason = "target"
                elif index - position.entry_index >= 78:
                    exit_price = current.close * (1 - self.slippage_bps / 10_000)
                    reason = "time"
                if exit_price is not None:
                    quantity = position.quantity
                    commission = max(1.0, quantity * self.commission_per_share)
                    cash += exit_price * quantity - commission
                    pnl = (exit_price - position.entry_price) * quantity - 2 * commission
                    trades.append(
                        BacktestTrade(
                            entry_time=position.entry_time,
                            exit_time=current.timestamp,
                            entry_price=position.entry_price,
                            exit_price=exit_price,
                            quantity=quantity,
                            pnl=pnl,
                            reason=reason,
                        )
                    )
                    position = None
            if position is None:
                signal = strategy.generate(
                    symbol=symbol,
                    bars=history,
                    benchmark_bars=benchmark_history,
                    catalysts=available_catalysts,
                    now=current.timestamp,
                )
                if signal and signal.action == SignalAction.BUY:
                    next_index = index + 1
                    if next_index >= len(bars):
                        break
                    next_bar = bars[next_index]
                    entry = next_bar.open * (1 + self.slippage_bps / 10_000)
                    per_share_risk = max(0.01, entry - signal.stop_price)
                    quantity = math.floor((cash * self.risk_per_trade_pct) / per_share_risk)
                    quantity = min(quantity, math.floor(cash / entry))
                    if quantity > 0:
                        commission = max(1.0, quantity * self.commission_per_share)
                        cash -= entry * quantity + commission
                        position = _ActivePosition(
                            entry_time=next_bar.timestamp,
                            entry_price=entry,
                            quantity=quantity,
                            stop=signal.stop_price,
                            target=signal.target_price,
                            entry_index=next_index,
                        )
            mark = cash
            if position:
                mark += current.close * position.quantity
            equity_curve.append(mark)
        ending_equity = equity_curve[-1]
        returns = np.diff(np.asarray(equity_curve)) / np.maximum(np.asarray(equity_curve[:-1]), 1e-9)
        sharpe = 0.0
        if len(returns) > 1 and float(np.std(returns)) > 0:
            sharpe = float(np.mean(returns) / np.std(returns) * math.sqrt(252 * 78))
        peaks = np.maximum.accumulate(np.asarray(equity_curve))
        drawdowns = 1 - np.asarray(equity_curve) / np.maximum(peaks, 1e-9)
        max_drawdown = float(np.max(drawdowns))
        winners = [trade.pnl for trade in trades if trade.pnl > 0]
        losers = [-trade.pnl for trade in trades if trade.pnl < 0]
        profit_factor = sum(winners) / sum(losers) if losers else (float("inf") if winners else 0.0)
        total_return = ending_equity / self.starting_cash - 1
        periods = max(1, len(equity_curve) - 1)
        annualized_return = (1 + total_return) ** ((252 * 78) / periods) - 1 if total_return > -1 else -1
        metrics = BacktestMetrics(
            total_return=total_return,
            annualized_return=annualized_return,
            sharpe=sharpe,
            max_drawdown=max_drawdown,
            profit_factor=profit_factor,
            win_rate=len(winners) / len(trades) if trades else 0.0,
            trades=len(trades),
            ending_equity=ending_equity,
        )
        return metrics, trades
