"""Integration contract: the reconciliation registry must resolve against the
REAL per-exposure output.

``CreditRiskCalc.reconcile()`` reconciles a legacy file against our results read
via ``scan_results()`` — the raw aggregator ``results`` frame, written verbatim
to parquet (no projection onto the documentary ``CALCULATION_OUTPUT_SCHEMA``).
Every reconcilable component therefore must have at least one ``our_columns``
candidate that the engine ACTUALLY emits, or the runner skips it with a REC001
"no column for component" warning and the analyst silently loses that comparison.

This is the guard that the pure-unit tests cannot give: they feed hand-built
frames, so a registry that names columns the engine never produces (the original
``irb_pd_floored`` / ``irb_lgd_floored`` bug) passes unit tests yet breaks every
real IRB reconciliation. Here we run the real IRB pipeline once and assert each
key component resolves, so any future engine column rename is caught.

References:
- src/rwa_calc/analysis/recon_registry.py — RECONCILABLE_COMPONENTS.our_columns
- src/rwa_calc/analysis/reconciliation.py — _resolve_active_components (REC001)
"""

from __future__ import annotations

from datetime import date

import pytest
from workbooks.shared.fixture_loader import load_fixtures

from rwa_calc.analysis.recon_registry import RECONCILABLE_COMPONENTS_BY_NAME
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.acceptance_helpers import make_irb_bundle
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions


@pytest.fixture(scope="module")
def irb_output_columns() -> set[str]:
    """Column names on the real per-exposure output of a full IRB pipeline run.

    Module-scoped: the pipeline runs once and every parametrised case reads the
    same resolved schema.
    """
    bundle = make_irb_bundle(load_fixtures(), create_full_irb_model_permissions())
    config = CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        permission_mode=PermissionMode.IRB,
    )
    result = PipelineOrchestrator().run_with_data(bundle, config)
    return set(result.results.collect_schema().names())


# The IRB-driver and CRM components whose our_columns were authored against the
# fictional CALCULATION_OUTPUT_SCHEMA names (pd/lgd/guarantee), plus the headline
# numeric components, all of which must resolve on the real output.
@pytest.mark.parametrize(
    "component",
    ["pd", "lgd", "guarantee", "maturity", "ead", "rwa", "risk_weight", "expected_loss"],
)
def test_component_resolves_against_real_irb_output(
    component: str, irb_output_columns: set[str]
) -> None:
    spec = RECONCILABLE_COMPONENTS_BY_NAME[component]
    resolved = [c for c in spec.our_columns if c in irb_output_columns]
    assert resolved, (
        f"reconciliation component {component!r} our_columns={spec.our_columns} "
        f"resolves to nothing on the real IRB output — REC001 would fire and the "
        f"component would be silently skipped. Update recon_registry.our_columns to "
        f"the engine's actual output name."
    )
