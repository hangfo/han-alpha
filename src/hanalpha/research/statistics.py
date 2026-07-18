from __future__ import annotations

import itertools
import math

import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class StatisticalDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sufficient: bool
    probability: float | None = Field(default=None, ge=0, le=1)
    reason: str
    observations: int = Field(ge=0)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1 + math.erf(value / math.sqrt(2)))


def _normal_ppf(probability: float) -> float:
    if not 0 < probability < 1:
        raise ValueError("probability must be between zero and one")
    coefficients_a = (
        -39.6968302866538,
        220.946098424521,
        -275.928510446969,
        138.357751867269,
        -30.6647980661472,
        2.50662827745924,
    )
    coefficients_b = (
        -54.4760987982241,
        161.585836858041,
        -155.698979859887,
        66.8013118877197,
        -13.2806815528857,
    )
    coefficients_c = (
        -0.00778489400243029,
        -0.322396458041136,
        -2.40075827716184,
        -2.54973253934373,
        4.37466414146497,
        2.93816398269878,
    )
    coefficients_d = (
        0.00778469570904146,
        0.32246712907004,
        2.445134137143,
        3.75440866190742,
    )
    lower = 0.02425
    upper = 1 - lower
    if probability < lower:
        q = math.sqrt(-2 * math.log(probability))
        return (
            (
                (
                    ((coefficients_c[0] * q + coefficients_c[1]) * q + coefficients_c[2]) * q
                    + coefficients_c[3]
                )
                * q
                + coefficients_c[4]
            )
            * q
            + coefficients_c[5]
        ) / (
            (
                ((coefficients_d[0] * q + coefficients_d[1]) * q + coefficients_d[2]) * q
                + coefficients_d[3]
            )
            * q
            + 1
        )
    if probability > upper:
        q = math.sqrt(-2 * math.log(1 - probability))
        return -(
            (
                (
                    (
                        ((coefficients_c[0] * q + coefficients_c[1]) * q + coefficients_c[2]) * q
                        + coefficients_c[3]
                    )
                    * q
                    + coefficients_c[4]
                )
                * q
                + coefficients_c[5]
            )
            / (
                (
                    ((coefficients_d[0] * q + coefficients_d[1]) * q + coefficients_d[2]) * q
                    + coefficients_d[3]
                )
                * q
                + 1
            )
        )
    q = probability - 0.5
    r = q * q
    return (
        (
            (
                (
                    ((coefficients_a[0] * r + coefficients_a[1]) * r + coefficients_a[2]) * r
                    + coefficients_a[3]
                )
                * r
                + coefficients_a[4]
            )
            * r
            + coefficients_a[5]
        )
        * q
        / (
            (
                (
                    ((coefficients_b[0] * r + coefficients_b[1]) * r + coefficients_b[2]) * r
                    + coefficients_b[3]
                )
                * r
                + coefficients_b[4]
            )
            * r
            + 1
        )
    )


def _sample_sharpe(values: np.ndarray) -> float:
    deviation = float(np.std(values, ddof=1))
    return float(np.mean(values) / deviation) if deviation > 0 else 0.0


def deflated_sharpe_ratio(
    returns: list[float], *, trial_sharpes: list[float]
) -> StatisticalDiagnostic:
    values = np.asarray(returns, dtype=float)
    if len(values) < 30:
        return StatisticalDiagnostic(
            sufficient=False,
            reason="at least 30 return observations are required",
            observations=len(values),
        )
    if len(trial_sharpes) < 2:
        return StatisticalDiagnostic(
            sufficient=False,
            reason="at least two registered trials are required",
            observations=len(values),
        )
    if not np.isfinite(values).all():
        raise ValueError("returns must be finite")
    sharpe = _sample_sharpe(values)
    trial_sigma = float(np.std(np.asarray(trial_sharpes, dtype=float), ddof=1))
    trials = len(trial_sharpes)
    euler_gamma = 0.5772156649015329
    expected_max = trial_sigma * (
        (1 - euler_gamma) * _normal_ppf(1 - 1 / trials)
        + euler_gamma * _normal_ppf(1 - 1 / (trials * math.e))
    )
    centered = values - float(np.mean(values))
    deviation = float(np.std(values, ddof=1))
    skew = float(np.mean(centered**3) / deviation**3) if deviation > 0 else 0
    kurtosis = float(np.mean(centered**4) / deviation**4) if deviation > 0 else 3
    denominator = math.sqrt(max(1e-12, 1 - skew * sharpe + ((kurtosis - 1) / 4) * sharpe**2))
    statistic = (sharpe - expected_max) * math.sqrt(len(values) - 1) / denominator
    return StatisticalDiagnostic(
        sufficient=True,
        probability=_normal_cdf(statistic),
        reason="probability Sharpe exceeds the multiple-testing benchmark",
        observations=len(values),
    )


def probability_of_backtest_overfitting(
    performance: np.ndarray, *, partitions: int = 8
) -> StatisticalDiagnostic:
    matrix = np.asarray(performance, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] < 2:
        return StatisticalDiagnostic(
            sufficient=False,
            reason="PBO requires at least two strategy trials",
            observations=matrix.shape[0] if matrix.ndim else 0,
        )
    if partitions < 4 or partitions % 2 or matrix.shape[0] < partitions * 2:
        return StatisticalDiagnostic(
            sufficient=False,
            reason="PBO requires an even partition count and two observations per partition",
            observations=matrix.shape[0],
        )
    if not np.isfinite(matrix).all():
        raise ValueError("performance matrix must be finite")
    blocks = np.array_split(np.arange(matrix.shape[0]), partitions)
    logits: list[float] = []
    for selected in itertools.combinations(range(partitions), partitions // 2):
        selected_set = set(selected)
        in_sample = np.concatenate([blocks[index] for index in selected])
        out_sample = np.concatenate(
            [blocks[index] for index in range(partitions) if index not in selected_set]
        )
        best = int(np.argmax(matrix[in_sample].mean(axis=0)))
        out_scores = matrix[out_sample].mean(axis=0)
        rank = int(np.argsort(np.argsort(out_scores))[best]) + 1
        percentile = rank / (matrix.shape[1] + 1)
        logits.append(math.log(percentile / (1 - percentile)))
    probability = sum(value <= 0 for value in logits) / len(logits)
    return StatisticalDiagnostic(
        sufficient=True,
        probability=probability,
        reason="fraction of CSCV selections with below-median OOS rank",
        observations=matrix.shape[0],
    )


def bootstrap_mean_interval(
    returns: list[float], *, seed: int, samples: int = 2000, confidence: float = 0.95
) -> tuple[float, float]:
    values = np.asarray(returns, dtype=float)
    if len(values) < 2 or samples < 100 or not 0 < confidence < 1:
        raise ValueError("invalid bootstrap configuration")
    if not np.isfinite(values).all():
        raise ValueError("returns must be finite")
    rng = np.random.default_rng(seed)
    means = rng.choice(values, size=(samples, len(values)), replace=True).mean(axis=1)
    tail = (1 - confidence) / 2
    return float(np.quantile(means, tail)), float(np.quantile(means, 1 - tail))


def moving_block_bootstrap_interval(
    returns: list[float],
    *,
    block_length: int,
    seed: int,
    samples: int = 2000,
    confidence: float = 0.95,
) -> tuple[float, float]:
    values = np.asarray(returns, dtype=float)
    if (
        len(values) < 4
        or block_length < 2
        or block_length > len(values)
        or samples < 100
        or not 0 < confidence < 1
    ):
        raise ValueError("invalid moving-block bootstrap configuration")
    if not np.isfinite(values).all():
        raise ValueError("returns must be finite")
    blocks = np.asarray([np.roll(values, -start)[:block_length] for start in range(len(values))])
    block_count = math.ceil(len(values) / block_length)
    rng = np.random.default_rng(seed)
    means = np.empty(samples)
    for index in range(samples):
        selected = rng.integers(0, len(blocks), size=block_count)
        sample = blocks[selected].reshape(-1)[: len(values)]
        means[index] = float(np.mean(sample))
    tail = (1 - confidence) / 2
    return float(np.quantile(means, tail)), float(np.quantile(means, 1 - tail))


def holm_adjust(p_values: list[float]) -> list[float]:
    if any(not 0 <= value <= 1 for value in p_values):
        raise ValueError("p-values must be between zero and one")
    ordered = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [0.0] * len(p_values)
    running = 0.0
    total = len(p_values)
    for rank, (index, value) in enumerate(ordered):
        running = max(running, min(1.0, (total - rank) * value))
        adjusted[index] = running
    return adjusted
