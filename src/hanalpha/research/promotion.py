from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hanalpha.experiments.models import ExperimentResult, TrialStatus
from hanalpha.experiments.registry import ExperimentRegistry, IllegalTrialTransition
from hanalpha.pit.models import HASH_PATTERN, require_aware
from hanalpha.simulation.events import canonical_hash


class PromotionThresholds(BaseModel):
    """Pre-registered, fail-closed research promotion thresholds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    minimum_observations: int = Field(default=252, ge=30)
    minimum_oos_return_after_costs: Decimal = Decimal("0")
    minimum_deflated_sharpe_probability: Decimal = Field(default=Decimal("0.95"), ge=0, le=1)
    maximum_pbo: Decimal = Field(default=Decimal("0.20"), ge=0, le=1)
    maximum_drawdown: Decimal = Field(default=Decimal("0.25"), ge=0, le=1)
    minimum_cost_stress_return: Decimal = Decimal("0")
    maximum_single_instrument_contribution: Decimal = Field(default=Decimal("0.35"), ge=0, le=1)


class PromotionEvidence(BaseModel):
    """Evidence packet; missing diagnostics are deliberately represented by None."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_hash: str
    expected_protocol_hash: str
    observations: int = Field(ge=0)
    oos_return_after_costs: Decimal
    deflated_sharpe_probability: Decimal | None = Field(default=None, ge=0, le=1)
    pbo: Decimal | None = Field(default=None, ge=0, le=1)
    max_drawdown: Decimal = Field(ge=0)
    cost_stress_return: Decimal
    largest_instrument_contribution: Decimal = Field(ge=0)
    parameter_stable: bool
    artifacts_verified: bool
    reproducible: bool
    independent_approved: bool
    budget_exhausted: bool = False


def promotion_failures(
    evidence: PromotionEvidence, thresholds: PromotionThresholds
) -> tuple[str, ...]:
    checks = (
        (evidence.protocol_hash == evidence.expected_protocol_hash, "protocol_hash_mismatch"),
        (not evidence.budget_exhausted, "research_budget_exhausted"),
        (evidence.observations >= thresholds.minimum_observations, "insufficient_observations"),
        (
            evidence.oos_return_after_costs >= thresholds.minimum_oos_return_after_costs,
            "oos_return_below_threshold",
        ),
        (
            evidence.deflated_sharpe_probability is not None
            and evidence.deflated_sharpe_probability
            >= thresholds.minimum_deflated_sharpe_probability,
            "deflated_sharpe_gate_failed_or_missing",
        ),
        (
            evidence.pbo is not None and evidence.pbo <= thresholds.maximum_pbo,
            "pbo_gate_failed_or_missing",
        ),
        (evidence.max_drawdown <= thresholds.maximum_drawdown, "drawdown_gate_failed"),
        (
            evidence.cost_stress_return >= thresholds.minimum_cost_stress_return,
            "cost_stress_gate_failed",
        ),
        (
            evidence.largest_instrument_contribution
            <= thresholds.maximum_single_instrument_contribution,
            "concentration_gate_failed",
        ),
        (evidence.parameter_stable, "parameter_instability"),
        (evidence.artifacts_verified, "artifact_verification_failed"),
        (evidence.reproducible, "reproducibility_failed"),
        (evidence.independent_approved, "independent_approval_missing"),
    )
    return tuple(reason for passed, reason in checks if not passed)


class ValidationAssessment(BaseModel):
    """Offline validator output signed by a configured validation authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: str = Field(pattern=HASH_PATTERN)
    protocol_hash: str = Field(pattern=HASH_PATTERN)
    result_hash: str = Field(pattern=HASH_PATTERN)
    validator_id: str = Field(min_length=1)
    observations: int = Field(ge=0)
    deflated_sharpe_probability: Decimal | None = Field(default=None, ge=0, le=1)
    pbo: Decimal | None = Field(default=None, ge=0, le=1)
    cost_stress_return: Decimal
    largest_instrument_contribution: Decimal = Field(ge=0)
    parameter_stable: bool
    reproduction_result_hash: str | None = Field(default=None, pattern=HASH_PATTERN)
    assessed_at: datetime
    signature: str = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_time(self) -> ValidationAssessment:
        require_aware(self.assessed_at, "assessed_at")
        return self

    def signing_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"signature"})


class IndependentApproval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: str = Field(pattern=HASH_PATTERN)
    reviewer_id: str = Field(min_length=1)
    reviewer_role: str = Field(pattern="^independent_reviewer$")
    approved: bool
    rationale: str = Field(min_length=1)
    approved_at: datetime
    signature: str = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_time(self) -> IndependentApproval:
        require_aware(self.approved_at, "approved_at")
        return self

    def signing_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"signature"})


def authority_signature(payload: dict[str, object], secret: bytes) -> str:
    message = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


class PromotionService:
    """Derive promotion from immutable artifacts and separated signed authorities."""

    def __init__(
        self,
        registry: ExperimentRegistry,
        artifact_root: Path,
        *,
        validator_keys: dict[str, bytes],
        reviewer_keys: dict[str, bytes],
    ) -> None:
        self.registry = registry
        self.artifact_root = Path(artifact_root).resolve()
        self.validator_keys = validator_keys
        self.reviewer_keys = reviewer_keys

    def promote(self, experiment_id: str, *, at: datetime) -> None:
        history = self.registry.history(experiment_id)
        if not history or history[-1].status != TrialStatus.COMPLETED:
            raise IllegalTrialTransition("only a completed trial can be promoted")
        manifest = self.registry.manifest(experiment_id)
        protocol = self.registry.protocol(manifest.protocol_hash)
        verified = self._verified_artifacts(experiment_id)
        required = {
            "manifest.json",
            "result.json",
            "validation-assessment.json",
            "independent-approval.json",
        }
        if not required.issubset(verified):
            raise IllegalTrialTransition("required promotion artifacts are missing")
        directory = self.artifact_root / experiment_id
        artifact_manifest = type(manifest).model_validate_json(
            (directory / "manifest.json").read_text()
        )
        result = ExperimentResult.model_validate_json((directory / "result.json").read_text())
        assessment = ValidationAssessment.model_validate_json(
            (directory / "validation-assessment.json").read_text()
        )
        approval = IndependentApproval.model_validate_json(
            (directory / "independent-approval.json").read_text()
        )
        self._verify_assessment(assessment)
        self._verify_approval(approval)
        if artifact_manifest != manifest:
            raise IllegalTrialTransition("manifest artifact differs from registry")
        if assessment.assessed_at > at or approval.approved_at > at:
            raise IllegalTrialTransition("promotion authority artifact is from the future")
        if approval.reviewer_id == protocol.researcher_id:
            raise IllegalTrialTransition("researcher cannot independently approve own program")
        if not approval.approved:
            raise IllegalTrialTransition("independent reviewer rejected promotion")
        if (
            assessment.experiment_id != experiment_id
            or assessment.protocol_hash != manifest.protocol_hash
            or assessment.result_hash != result.result_hash
            or result.result_hash != history[-1].result_hash
            or result.experiment_id != experiment_id
            or approval.experiment_id != experiment_id
        ):
            raise IllegalTrialTransition("signed promotion artifacts do not bind to trial")
        evidence = PromotionEvidence(
            protocol_hash=assessment.protocol_hash,
            expected_protocol_hash=manifest.protocol_hash,
            observations=assessment.observations,
            oos_return_after_costs=result.metrics.total_return,
            deflated_sharpe_probability=assessment.deflated_sharpe_probability,
            pbo=assessment.pbo,
            max_drawdown=result.metrics.max_drawdown,
            cost_stress_return=assessment.cost_stress_return,
            largest_instrument_contribution=assessment.largest_instrument_contribution,
            parameter_stable=assessment.parameter_stable,
            artifacts_verified=True,
            reproducible=assessment.reproduction_result_hash == result.result_hash,
            independent_approved=True,
            budget_exhausted=False,
        )
        thresholds = PromotionThresholds(
            minimum_observations=protocol.success.minimum_observations,
            minimum_oos_return_after_costs=protocol.success.minimum_oos_return,
            minimum_deflated_sharpe_probability=protocol.success.minimum_dsr_probability,
            maximum_pbo=protocol.success.maximum_pbo,
            maximum_drawdown=protocol.success.maximum_drawdown,
            minimum_cost_stress_return=protocol.success.minimum_cost_stress_return,
            maximum_single_instrument_contribution=(protocol.success.maximum_contribution_share),
        )
        failures = promotion_failures(evidence, thresholds)
        if failures:
            raise IllegalTrialTransition("promotion gates failed: " + ",".join(failures))
        self.registry._promote_verified(
            experiment_id,
            at=at,
            metadata={
                "assessment_hash": canonical_hash(assessment),
                "approval_hash": canonical_hash(approval),
                "validator_id": assessment.validator_id,
                "reviewer_id": approval.reviewer_id,
            },
        )

    def _verified_artifacts(self, experiment_id: str) -> set[str]:
        verified: set[str] = set()
        for record in self.registry.artifacts(experiment_id):
            path = (self.artifact_root / record.relative_path).resolve()
            if self.artifact_root not in path.parents or not path.is_file():
                raise IllegalTrialTransition("artifact path escaped root or is missing")
            content = path.read_bytes()
            if (
                len(content) != record.digest.size
                or hashlib.sha256(content).hexdigest() != record.digest.sha256
            ):
                raise IllegalTrialTransition("artifact digest mismatch")
            verified.add(record.digest.name)
        return verified

    def _verify_assessment(self, assessment: ValidationAssessment) -> None:
        key = self.validator_keys.get(assessment.validator_id)
        if key is None or not hmac.compare_digest(
            assessment.signature, authority_signature(assessment.signing_payload(), key)
        ):
            raise IllegalTrialTransition("validation authority signature is invalid")

    def _verify_approval(self, approval: IndependentApproval) -> None:
        key = self.reviewer_keys.get(approval.reviewer_id)
        if key is None or not hmac.compare_digest(
            approval.signature, authority_signature(approval.signing_payload(), key)
        ):
            raise IllegalTrialTransition("review authority signature is invalid")
