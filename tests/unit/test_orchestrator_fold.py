"""
Unit tests for the fold orchestrator and the literal stage registry.

Pins the Phase 4 orchestration shape:
- registry: the exact ordered stage-name list (one screen, no
  conditionals) and the per-stage failure policies
- run_stages: stage order, context threading, halt-on-exception with the
  declared policy, PIPELINE_ERRORS accumulation
- create_error_result: sealed empty aggregator frame + converted errors
- RulepackV0: regime facade properties

References:
- docs/plans/target-architecture-migration.md (Phase 4 — uniform stage model)
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.context import ArtifactKey
from rwa_calc.contracts.edges import sealed_edge_of
from rwa_calc.domain.enums import RegulatoryFramework
from rwa_calc.engine.orchestrator import (
    HALTED,
    PIPELINE_ERRORS,
    PipelineError,
    StageSpec,
    create_error_result,
    run_stages,
)
from rwa_calc.engine.registry import PIPELINE_STAGES
from rwa_calc.rulebook import RulepackV0
from tests.fixtures.context import make_context

TRACE: ArtifactKey[tuple[str, ...]] = ArtifactKey("test_trace")


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


class TestRegistry:
    """The literal stage list is the single source of pipeline order."""

    def test_stage_order_is_pinned(self):
        assert [s.name for s in PIPELINE_STAGES] == [
            "securitisation_allocator",
            "hierarchy_resolver",
            "ccr_sa_ccr",
            "classifier",
            "crm_processor",
            "re_splitter",
            "calculators",
            "equity_calculator",
            "aggregator",
        ]

    def test_failure_policies_are_pinned(self):
        """Calculator/aggregator crashes still flow through the error merge;
        everything else halts with the bare error result (verbatim pre-fold
        behaviour, rationalised by the error-channel slice)."""
        policies = {s.name: s.halt for s in PIPELINE_STAGES}
        assert policies["calculators"] == "merged"
        assert policies["aggregator"] == "merged"
        immediate = {n for n, h in policies.items() if h == "immediate"}
        assert immediate == {
            "securitisation_allocator",
            "hierarchy_resolver",
            "ccr_sa_ccr",
            "classifier",
            "crm_processor",
            "re_splitter",
            "equity_calculator",
        }


class TestRunStages:
    """Fold semantics over synthetic stages."""

    def test_stages_run_in_order_and_thread_context(self, crr_config):
        def make_stage(tag: str):
            def stage(ctx, rulepack, run_config):
                return ctx.put(TRACE, (*ctx.get_or(TRACE, ()), tag))

            return stage

        stages = (
            StageSpec("first", make_stage("first"), error_type="x"),
            StageSpec("second", make_stage("second"), error_type="x"),
        )
        ctx = make_context()

        out = run_stages(ctx, RulepackV0.from_config(crr_config), crr_config, stages)

        assert out.get(TRACE) == ("first", "second")
        assert not out.has(HALTED)

    def test_raising_stage_halts_fold_with_policy(self, crr_config):
        def boom(ctx, rulepack, run_config):
            raise RuntimeError("stage exploded")

        def never_runs(ctx, rulepack, run_config):  # pragma: no cover - must not run
            return ctx.put(TRACE, ("ran",))

        stages = (
            StageSpec("exploding", boom, error_type="explosion", halt="merged"),
            StageSpec("downstream", never_runs, error_type="x"),
        )
        ctx = make_context()

        out = run_stages(ctx, RulepackV0.from_config(crr_config), crr_config, stages)

        assert out.get(HALTED) == "merged"
        assert not out.has(TRACE)
        errors = out.get(PIPELINE_ERRORS)
        assert len(errors) == 1
        assert errors[0].stage == "exploding"
        assert errors[0].error_type == "explosion"
        assert "stage exploded" in errors[0].message


class TestCreateErrorResult:
    """The error result satisfies the sealed aggregator-exit registration."""

    def test_error_result_is_sealed_and_converted(self):
        errors = [PipelineError(stage="classifier", error_type="boom", message="m")]

        result = create_error_result(errors)

        assert sealed_edge_of(result.results) == "aggregator_exit"
        assert result.results.collect().height == 0
        assert [e.code for e in result.errors] == ["PIPELINE_CLASSIFIER"]


class TestRulepackV0:
    """The v0 regime facade delegates to the effective config."""

    def test_crr_facade(self):
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        rulepack = RulepackV0.from_config(config)

        assert rulepack.regime is RegulatoryFramework.CRR
        assert rulepack.is_crr is True
        assert rulepack.is_basel_3_1 is False
        assert rulepack.scaling_factor == 1.06

    def test_b31_facade(self):
        config = CalculationConfig.basel_3_1(reporting_date=date(2028, 1, 15))
        rulepack = RulepackV0.from_config(config)

        assert rulepack.regime is RegulatoryFramework.BASEL_3_1
        assert rulepack.is_basel_3_1 is True
        assert rulepack.scaling_factor == 1.0
