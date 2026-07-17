from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from hanalpha.domain.models import Bar


def closes(bars: Sequence[Bar]) -> np.ndarray:
    return np.asarray([bar.close for bar in bars], dtype=float)


def highs(bars: Sequence[Bar]) -> np.ndarray:
    return np.asarray([bar.high for bar in bars], dtype=float)


def lows(bars: Sequence[Bar]) -> np.ndarray:
    return np.asarray([bar.low for bar in bars], dtype=float)


def volumes(bars: Sequence[Bar]) -> np.ndarray:
    return np.asarray([bar.volume for bar in bars], dtype=float)


def sma(values: Sequence[float] | np.ndarray, window: int) -> float:
    array = np.asarray(values, dtype=float)
    if window <= 0 or len(array) < window:
        raise ValueError("insufficient values for SMA")
    return float(np.mean(array[-window:]))


def rolling_high(values: Sequence[float] | np.ndarray, window: int, *, exclude_last: bool = False) -> float:
    array = np.asarray(values, dtype=float)
    required = window + (1 if exclude_last else 0)
    if window <= 0 or len(array) < required:
        raise ValueError("insufficient values for rolling high")
    end = -1 if exclude_last else None
    return float(np.max(array[-required:end]))


def rolling_low(values: Sequence[float] | np.ndarray, window: int, *, exclude_last: bool = False) -> float:
    array = np.asarray(values, dtype=float)
    required = window + (1 if exclude_last else 0)
    if window <= 0 or len(array) < required:
        raise ValueError("insufficient values for rolling low")
    end = -1 if exclude_last else None
    return float(np.min(array[-required:end]))


def atr(bars: Sequence[Bar], window: int = 14) -> float:
    if len(bars) < window + 1:
        raise ValueError("insufficient bars for ATR")
    ranges: list[float] = []
    for previous, current in zip(bars[-window - 1 : -1], bars[-window:], strict=True):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    value = float(np.mean(ranges))
    if not math.isfinite(value) or value <= 0:
        raise ValueError("ATR must be positive and finite")
    return value


def rsi(bars: Sequence[Bar], window: int = 14) -> float:
    values = closes(bars)
    if len(values) < window + 1:
        raise ValueError("insufficient bars for RSI")
    changes = np.diff(values[-window - 1 :])
    gains = np.clip(changes, 0, None)
    losses = -np.clip(changes, None, 0)
    avg_gain = float(np.mean(gains))
    avg_loss = float(np.mean(losses))
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def relative_strength(symbol_bars: Sequence[Bar], benchmark_bars: Sequence[Bar], window: int = 20) -> float:
    if len(symbol_bars) < window + 1 or len(benchmark_bars) < window + 1:
        raise ValueError("insufficient bars for relative strength")
    symbol_return = symbol_bars[-1].close / symbol_bars[-window - 1].close - 1
    benchmark_return = benchmark_bars[-1].close / benchmark_bars[-window - 1].close - 1
    return float(symbol_return - benchmark_return)


def average_dollar_volume(bars: Sequence[Bar], window: int = 20) -> float:
    if len(bars) < window:
        raise ValueError("insufficient bars for average dollar volume")
    values = [bar.close * bar.volume for bar in bars[-window:]]
    return float(np.mean(values))


def zscore_last(values: Sequence[float], window: int) -> float:
    array = np.asarray(values, dtype=float)
    if len(array) < window:
        raise ValueError("insufficient values for z-score")
    sample = array[-window:]
    std = float(np.std(sample))
    if std == 0:
        return 0.0
    return float((sample[-1] - float(np.mean(sample))) / std)
