from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hanalpha.experiments.models import ArtifactDigest, ExperimentManifest, TrialStatus, WindowRole
from hanalpha.experiments.registry import ExperimentRegistry, IllegalTrialTransition
from tests.experiments.helpers import authorized_manifest, protocol


def _manifest(
    registry: ExperimentRegistry, now: datetime, *, key: str = "trial", **updates: object
) -> ExperimentManifest:
    return authorized_manifest(registry, at=now, key=key, **updates)


def test_manifest_hash_is_canonical_and_sensitive(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    now = datetime(2024, 1, 1, tzinfo=UTC)
    try:
        first = _manifest(registry, now, parameters={"slow": 20, "fast": 5})
        second = _manifest(registry, now, parameters={"fast": 5, "slow": 20})
        assert first.experiment_id == second.experiment_id
        assert _manifest(registry, now, key="other", seed=8).experiment_id != first.experiment_id
    finally:
        registry.close()


def test_registry_treats_reordered_manifest_parameters_as_idempotent(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    now = datetime(2024, 1, 1, tzinfo=UTC)
    try:
        first = _manifest(registry, now, parameters={"slow": 20, "fast": 5})
        second = _manifest(registry, now, parameters={"fast": 5, "slow": 20})
        assert registry.register(first, at=now) == registry.register(second, at=now)
        assert len(registry.history(first.experiment_id)) == 1
    finally:
        registry.close()


def test_failed_trial_remains_in_strategy_cemetery_and_cannot_promote(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    now = datetime(2024, 1, 1, tzinfo=UTC)
    try:
        manifest = _manifest(registry, now)
        registry.register(manifest, at=now)
        registry.transition(
            manifest.experiment_id, TrialStatus.RUNNING, at=now + timedelta(seconds=1)
        )
        registry.transition(
            manifest.experiment_id,
            TrialStatus.FAILED,
            at=now + timedelta(seconds=2),
            failure_reason="accounting invariant",
        )
        cemetery = registry.strategy_cemetery()
        assert [item.experiment_id for item in cemetery] == [manifest.experiment_id]
        assert cemetery[0].failure_reason == "accounting invariant"
        with pytest.raises(IllegalTrialTransition):
            registry.transition(
                manifest.experiment_id,
                TrialStatus.PROMOTED,
                at=now + timedelta(seconds=3),
            )
        assert len(registry.history(manifest.experiment_id)) == 3
    finally:
        registry.close()


def test_counterfactual_requires_registered_parent(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    now = datetime(2024, 1, 1, tzinfo=UTC)
    try:
        child = _manifest(registry, now, counterfactual_of="f" * 64)
        with pytest.raises(KeyError, match="counterfactual"):
            registry.register(child, at=now)
    finally:
        registry.close()


def test_artifacts_are_hash_registered_and_conflicts_fail_closed(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    now = datetime(2024, 1, 1, tzinfo=UTC)
    artifact = ArtifactDigest(name="result.json", sha256="a" * 64, size=42)
    try:
        manifest = _manifest(registry, now)
        registry.register(manifest, at=now)
        registry.record_artifact(
            manifest.experiment_id,
            artifact,
            relative_path="runs/result.json",
            at=now + timedelta(seconds=2),
        )
        assert registry.artifacts(manifest.experiment_id)[0].digest == artifact
        registry.record_artifact(
            manifest.experiment_id,
            artifact,
            relative_path="runs/result.json",
            at=now + timedelta(seconds=1),
        )
        with pytest.raises(RuntimeError, match="conflict"):
            registry.record_artifact(
                manifest.experiment_id,
                artifact.model_copy(update={"sha256": "b" * 64}),
                relative_path="runs/result.json",
                at=now + timedelta(seconds=2),
            )
    finally:
        registry.close()


def test_completed_trial_rejects_self_reported_promotion(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    now = datetime(2024, 1, 1, tzinfo=UTC)
    try:
        manifest = _manifest(registry, now)
        registry.register(manifest, at=now)
        registry.transition(manifest.experiment_id, TrialStatus.RUNNING, at=now)
        registry.transition(
            manifest.experiment_id,
            TrialStatus.COMPLETED,
            at=now,
            result_hash="a" * 64,
        )
        with pytest.raises(IllegalTrialTransition):
            registry.transition(manifest.experiment_id, TrialStatus.PROMOTED, at=now)
        with pytest.raises(IllegalTrialTransition, match="self-reported"):
            registry.promote(manifest.experiment_id, at=now)
        assert registry.history(manifest.experiment_id)[-1].status == TrialStatus.COMPLETED
    finally:
        registry.close()


def test_trial_budget_is_persistent_atomic_and_idempotent(tmp_path) -> None:
    path = tmp_path / "experiments.sqlite3"
    first = ExperimentRegistry(path)
    second = ExperimentRegistry(path)
    now = datetime(2024, 1, 1, tzinfo=UTC)
    research_protocol = protocol(max_trials=1)
    try:
        first.register_protocol(research_protocol)
        allocation = first.allocate_trial(
            research_protocol.protocol_hash,
            parameters={"fast": 5},
            window_role=WindowRole.TEST,
            idempotency_key="logical-trial",
            at=now,
        )
        retry = second.allocate_trial(
            research_protocol.protocol_hash,
            parameters={"fast": 5},
            window_role=WindowRole.TEST,
            idempotency_key="logical-trial",
            at=now,
        )
        assert retry.allocation_id == allocation.allocation_id
        with pytest.raises(RuntimeError, match="budget"):
            second.allocate_trial(
                research_protocol.protocol_hash,
                parameters={"fast": 6},
                window_role=WindowRole.TEST,
                idempotency_key="another-trial",
                at=now,
            )
    finally:
        first.close()
        second.close()
