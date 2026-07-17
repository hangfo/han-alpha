from __future__ import annotations

import platform
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from hanalpha.experiments.artifacts import ResultBundleWriter
from hanalpha.experiments.models import (
    ExperimentManifest,
    ExperimentResult,
    TrialStatus,
)
from hanalpha.experiments.registry import ExperimentRegistry
from hanalpha.metrics.portfolio import compute_portfolio_metrics
from hanalpha.simulation.engine import (
    CandidatePolicy,
    PortfolioReplayEngine,
)
from hanalpha.simulation.events import ReplayFrame


class ExperimentContractError(RuntimeError):
    pass


class ExperimentRunner:
    """Close one deterministic local experiment lifecycle without external calls."""

    def __init__(self, registry: ExperimentRegistry, artifact_root: Path) -> None:
        self.registry = registry
        self.artifact_root = Path(artifact_root)

    def run(
        self,
        *,
        manifest: ExperimentManifest,
        engine: PortfolioReplayEngine,
        frames: list[ReplayFrame],
        policy: CandidatePolicy,
        at: datetime,
    ) -> ExperimentResult:
        self._validate_contract(manifest, engine, frames, policy)
        experiment_id = self.registry.register(manifest, at=at)
        self.registry.transition(
            experiment_id,
            TrialStatus.RUNNING,
            at=at,
            metadata={
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
        )
        try:
            replay = engine.run(frames, policy)
            traded_notional = sum(
                (Decimal(str(fill.price)) * Decimal(fill.quantity) for fill in replay.fills),
                Decimal("0"),
            )
            result = ExperimentResult(
                experiment_id=experiment_id,
                event_hash=replay.event_hash,
                equity_hash=replay.equity_hash,
                metrics=compute_portfolio_metrics(
                    replay.equity_points,
                    total_traded_notional=traded_notional,
                ),
                equity_points=replay.equity_points,
                fill_count=len(replay.fills),
            )
            directory = self.artifact_root / experiment_id
            digests = ResultBundleWriter().write(manifest, result, directory)
            for digest in digests:
                self.registry.record_artifact(
                    experiment_id,
                    digest,
                    relative_path=f"{experiment_id}/{digest.name}",
                    at=at,
                )
            self.registry.transition(
                experiment_id,
                TrialStatus.COMPLETED,
                at=at,
                result_hash=result.result_hash,
            )
            return result
        except Exception as exc:
            self.registry.transition(
                experiment_id,
                TrialStatus.FAILED,
                at=at,
                failure_reason=f"{type(exc).__name__}: {exc}",
            )
            raise

    @staticmethod
    def _validate_contract(
        manifest: ExperimentManifest,
        engine: PortfolioReplayEngine,
        frames: list[ReplayFrame],
        policy: CandidatePolicy,
    ) -> None:
        if manifest.config_hash != engine.config_hash:
            raise ExperimentContractError("manifest and engine config hashes differ")
        if manifest.cost_policy_hash != engine.exchange.policy.policy_hash:
            raise ExperimentContractError("manifest and exchange cost-policy hashes differ")
        if manifest.strategy_id != policy.name or manifest.strategy_version != policy.version:
            raise ExperimentContractError("manifest and candidate policy identity differ")
        if any(frame.snapshot_id != manifest.snapshot_id for frame in frames):
            raise ExperimentContractError("manifest and replay snapshot IDs differ")
