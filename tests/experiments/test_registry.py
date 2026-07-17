from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hanalpha.experiments.models import ArtifactDigest, ExperimentManifest, TrialStatus
from hanalpha.experiments.registry import ExperimentRegistry, IllegalTrialTransition


def _manifest(**updates) -> ExperimentManifest:
    payload = {
        "snapshot_id": "1" * 64,
        "code_hash": "2" * 64,
        "config_hash": "3" * 64,
        "cost_policy_hash": "4" * 64,
        "universe_hash": "5" * 64,
        "metric_schema_version": "1",
        "seed": 7,
        "strategy_id": "baseline",
        "strategy_version": "1",
        "hypothesis": "mechanical fixture hypothesis, not alpha",
        "parameters": {"slow": 20, "fast": 5},
    }
    payload.update(updates)
    return ExperimentManifest.model_validate(payload)


def test_manifest_hash_is_canonical_and_sensitive() -> None:
    first = _manifest(parameters={"slow": 20, "fast": 5})
    second = _manifest(parameters={"fast": 5, "slow": 20})
    assert first.experiment_id == second.experiment_id
    assert _manifest(seed=8).experiment_id != first.experiment_id


def test_registry_treats_reordered_manifest_parameters_as_idempotent(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    now = datetime(2024, 1, 1, tzinfo=UTC)
    first = _manifest(parameters={"slow": 20, "fast": 5})
    second = _manifest(parameters={"fast": 5, "slow": 20})
    try:
        assert registry.register(first, at=now) == registry.register(second, at=now)
        assert len(registry.history(first.experiment_id)) == 1
    finally:
        registry.close()


def test_failed_trial_remains_in_strategy_cemetery_and_cannot_promote(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    now = datetime(2024, 1, 1, tzinfo=UTC)
    manifest = _manifest()
    try:
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
    try:
        child = _manifest(counterfactual_of="f" * 64)
        with pytest.raises(KeyError, match="counterfactual"):
            registry.register(child, at=datetime(2024, 1, 1, tzinfo=UTC))
    finally:
        registry.close()


def test_artifacts_are_hash_registered_and_conflicts_fail_closed(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    manifest = _manifest()
    now = datetime(2024, 1, 1, tzinfo=UTC)
    artifact = ArtifactDigest(name="result.json", sha256="a" * 64, size=42)
    try:
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
