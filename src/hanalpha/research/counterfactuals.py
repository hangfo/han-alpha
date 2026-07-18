from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from hanalpha.experiments.models import ExperimentManifest
from hanalpha.research.protocol import ResearchBudget


class CounterfactualSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    parameter_overrides: dict[str, int | float | str] = Field(default_factory=dict)
    cost_multiplier: Decimal = Field(default=Decimal("1"), gt=0)
    delay_bars: int = Field(default=0, ge=0)


def standard_counterfactual_suite(
    *, parameter: str, base_value: int
) -> tuple[CounterfactualSpec, ...]:
    if base_value < 2:
        raise ValueError("counterfactual parameter base must be at least two")
    delta = max(1, round(base_value * 0.1))
    return (
        CounterfactualSpec(name="double-cost", cost_multiplier=Decimal("2")),
        CounterfactualSpec(name="one-bar-delay", delay_bars=1),
        CounterfactualSpec(
            name=f"{parameter}-lower",
            parameter_overrides={parameter: base_value - delta},
        ),
        CounterfactualSpec(
            name=f"{parameter}-higher",
            parameter_overrides={parameter: base_value + delta},
        ),
    )


def counterfactual_manifests(
    base: ExperimentManifest,
    specs: tuple[CounterfactualSpec, ...],
    budget: ResearchBudget,
) -> tuple[tuple[ExperimentManifest, ...], ResearchBudget]:
    if len(specs) > budget.remaining_trials:
        raise RuntimeError("counterfactual suite exceeds research budget")
    manifests = tuple(
        base.model_copy(
            update={
                "hypothesis": f"{base.hypothesis}; counterfactual={spec.name}",
                "parameters": {
                    **base.parameters,
                    **spec.parameter_overrides,
                    "__cost_multiplier": str(spec.cost_multiplier),
                    "__delay_bars": spec.delay_bars,
                },
                "counterfactual_of": base.experiment_id,
            }
        )
        for spec in specs
    )
    consumed = ResearchBudget(
        max_trials=budget.max_trials,
        used_trials=budget.used_trials + len(specs),
    )
    return manifests, consumed
