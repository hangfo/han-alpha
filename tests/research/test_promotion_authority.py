from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from hanalpha.domain.enums import Side
from hanalpha.experiments.models import ArtifactDigest, TrialStatus
from hanalpha.experiments.registry import ExperimentRegistry, IllegalTrialTransition
from hanalpha.experiments.runner import ExperimentRunner
from hanalpha.research.promotion import (
    IndependentApproval,
    PromotionService,
    ValidationAssessment,
    authority_signature,
)
from hanalpha.simulation.engine import OrderProposal, PortfolioReplayEngine
from hanalpha.simulation.events import ReplayFrame, SimulationBar
from hanalpha.simulation.fills import FillPolicy, HistoricalExchange
from hanalpha.simulation.orders import OrderKind
from hanalpha.simulation.portfolio import PortfolioPolicy
from tests.experiments.helpers import authorized_manifest, protocol


class NoCandidates:
    name = "no-candidates"
    version = "1"

    def propose(self, frame, portfolio):
        return []


class OneRoundTrip:
    name = "one-round-trip"
    version = "1"

    def __init__(self) -> None:
        self.proposed = False

    def propose(self, frame, portfolio):
        if self.proposed:
            return []
        self.proposed = True
        return [
            OrderProposal(
                instrument_id="inst-alpha",
                strategy_id=self.name,
                strategy_version=self.version,
                side=Side.BUY,
                kind=OrderKind.LIMIT,
                quantity=10,
                planned_price=100,
                limit_price=100,
                protective_stop=90,
                protective_target=120,
                input_hash="7" * 64,
                signal_hash="8" * 64,
            )
        ]


def _write_authority_artifact(
    registry: ExperimentRegistry,
    root,
    experiment_id: str,
    name: str,
    model,
    now: datetime,
) -> None:
    content = (model.model_dump_json() + "\n").encode()
    target = root / experiment_id / name
    target.write_bytes(content)
    registry.record_artifact(
        experiment_id,
        ArtifactDigest(
            name=name,
            sha256=hashlib.sha256(content).hexdigest(),
            size=len(content),
        ),
        relative_path=f"{experiment_id}/{name}",
        at=now,
    )


def _signed_assessment(
    experiment_id, protocol_hash, result_hash, now, secret, *, benchmark_return="0"
):
    unsigned = ValidationAssessment(
        experiment_id=experiment_id,
        protocol_hash=protocol_hash,
        result_hash=result_hash,
        validator_id="offline-validator",
        observations=30,
        deflated_sharpe_probability="0.99",
        pbo="0.10",
        cost_stress_return="0",
        largest_instrument_contribution="0",
        parameter_stable=True,
        benchmark_return=benchmark_return,
        reproduction_result_hash=result_hash,
        assessed_at=now,
        signature="0" * 64,
    )
    return unsigned.model_copy(
        update={"signature": authority_signature(unsigned.signing_payload(), secret)}
    )


def _signed_approval(experiment_id, reviewer_id, now, secret):
    unsigned = IndependentApproval(
        experiment_id=experiment_id,
        reviewer_id=reviewer_id,
        reviewer_role="independent_reviewer",
        approved=True,
        rationale="all pre-registered gates independently reviewed",
        approved_at=now,
        signature="0" * 64,
    )
    return unsigned.model_copy(
        update={"signature": authority_signature(unsigned.signing_payload(), secret)}
    )


def test_promotion_is_derived_from_hashed_signed_artifacts(tmp_path) -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    artifact_root = tmp_path / "artifacts"
    registry = ExperimentRegistry(tmp_path / "registry.sqlite3")
    validator_secret = b"validator-test-secret"
    reviewer_secret = b"reviewer-test-secret"
    base_protocol = protocol()
    research_protocol = base_protocol.model_copy(
        update={
            "cost_policy_hash": FillPolicy().policy_hash,
            "success": base_protocol.success.model_copy(
                update={"minimum_oos_return": Decimal("-1")}
            ),
        }
    )
    try:
        manifest = authorized_manifest(
            registry,
            at=now,
            protocol_override=research_protocol,
            parameters={},
            strategy_id=OneRoundTrip.name,
            cost_policy_hash=FillPolicy().policy_hash,
        )
        frames = []
        for index in range(30):
            frame_time = now + timedelta(days=index)
            low = 89 if index == 2 else 99
            close = 90 if index == 2 else 100
            frames.append(
                ReplayFrame(
                    snapshot_id=manifest.snapshot_id,
                    as_of=frame_time,
                    bars=[
                        SimulationBar(
                            snapshot_id=manifest.snapshot_id,
                            instrument_id="inst-alpha",
                            source_record_id=f"bar-{index}",
                            source_revision=1,
                            event_time=frame_time,
                            available_at=frame_time,
                            open=100,
                            high=101,
                            low=low,
                            close=close,
                            volume=1_000_000,
                        )
                    ],
                )
            )
        result = ExperimentRunner(registry, artifact_root).run(
            manifest=manifest,
            engine=PortfolioReplayEngine(
                starting_cash=10000,
                portfolio_policy=PortfolioPolicy(),
                exchange=HistoricalExchange(FillPolicy()),
                config_hash=manifest.config_hash,
            ),
            frames=frames,
            policy=OneRoundTrip(),
            at=now,
        )
        assessment = _signed_assessment(
            manifest.experiment_id,
            manifest.protocol_hash,
            result.result_hash,
            now,
            validator_secret,
            benchmark_return=result.metrics.total_return,
        )
        approval = _signed_approval(manifest.experiment_id, "reviewer-2", now, reviewer_secret)
        _write_authority_artifact(
            registry,
            artifact_root,
            manifest.experiment_id,
            "validation-assessment.json",
            assessment,
            now,
        )
        _write_authority_artifact(
            registry,
            artifact_root,
            manifest.experiment_id,
            "independent-approval.json",
            approval,
            now,
        )
        PromotionService(
            registry,
            artifact_root,
            validator_keys={"offline-validator": validator_secret},
            reviewer_keys={"reviewer-2": reviewer_secret},
        ).promote(manifest.experiment_id, at=now + timedelta(seconds=1))
        assert registry.history(manifest.experiment_id)[-1].status == TrialStatus.PROMOTED
    finally:
        registry.close()


def test_researcher_cannot_self_approve_even_with_valid_signature(tmp_path) -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    artifact_root = tmp_path / "artifacts"
    registry = ExperimentRegistry(tmp_path / "registry.sqlite3")
    research_protocol = protocol().model_copy(update={"cost_policy_hash": FillPolicy().policy_hash})
    try:
        manifest = authorized_manifest(
            registry,
            at=now,
            protocol_override=research_protocol,
            parameters={},
            strategy_id=NoCandidates.name,
            cost_policy_hash=FillPolicy().policy_hash,
        )
        result = ExperimentRunner(registry, artifact_root).run(
            manifest=manifest,
            engine=PortfolioReplayEngine(
                starting_cash=10000,
                portfolio_policy=PortfolioPolicy(),
                exchange=HistoricalExchange(FillPolicy()),
                config_hash=manifest.config_hash,
            ),
            frames=[ReplayFrame(snapshot_id=manifest.snapshot_id, as_of=now, bars=[])],
            policy=NoCandidates(),
            at=now,
        )
        validator_secret = b"validator"
        researcher_secret = b"researcher"
        _write_authority_artifact(
            registry,
            artifact_root,
            manifest.experiment_id,
            "validation-assessment.json",
            _signed_assessment(
                manifest.experiment_id,
                manifest.protocol_hash,
                result.result_hash,
                now,
                validator_secret,
            ),
            now,
        )
        _write_authority_artifact(
            registry,
            artifact_root,
            manifest.experiment_id,
            "independent-approval.json",
            _signed_approval(
                manifest.experiment_id,
                research_protocol.researcher_id,
                now,
                researcher_secret,
            ),
            now,
        )
        service = PromotionService(
            registry,
            artifact_root,
            validator_keys={"offline-validator": validator_secret},
            reviewer_keys={research_protocol.researcher_id: researcher_secret},
        )
        with pytest.raises(IllegalTrialTransition, match="own program"):
            service.promote(manifest.experiment_id, at=now)
    finally:
        registry.close()
