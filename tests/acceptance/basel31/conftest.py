"""
Shared fixtures for Basel 3.1 acceptance tests.

Provides common test configuration and helper utilities for validating
Basel 3.1 RWA calculations against expected outputs.

Why these tests matter:
    Basel 3.1 (PRA PS1/26, effective 1 Jan 2027) introduces material changes
    to credit risk capital requirements. These acceptance tests verify that the
    calculator correctly implements the revised framework, catching regressions
    and ensuring regulatory compliance across SA risk weights, IRB parameters,
    and the output floor.
"""

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tests.acceptance.acceptance_helpers import (  # noqa: E402
    assert_ead_match,
    assert_risk_weight_match,
    assert_rwa_within_tolerance,
    assert_supporting_factor_match,
    build_raw_bundle,
    get_irb_result_for_exposure,
    get_result_for_exposure,
    get_sa_result_for_exposure,
    get_scenarios_by_group,
    make_irb_bundle,
)
from tests.fixtures.raw_bundle import make_raw_bundle  # noqa: E402

# Re-exported so explicit-path imports
# (``from tests.acceptance.basel31.conftest import ...``) keep resolving unchanged.
__all__ = [
    "assert_ead_match",
    "assert_risk_weight_match",
    "assert_rwa_within_tolerance",
    "assert_supporting_factor_match",
    "get_irb_result_for_exposure",
    "get_result_for_exposure",
    "get_sa_result_for_exposure",
    "get_scenarios_by_group",
]

# =============================================================================
# Shared PSM guarantee-substitution input schema
# =============================================================================

# Identical input schema for the IRB guarantee-substitution
# LazyFrames built by the P1.157 and P1.159 PSM acceptance tests
# (_build_p1157_lf / _build_p1159_lf). The data payloads differ per scenario
# (exposure_class, requires_fi_scalar, PD/LGD/guarantor values) and stay inline
# in each test module; only this byte-identical column->dtype contract is shared.
PSM_GUARANTEE_INPUT_SCHEMA: dict[str, pl.DataType] = {
    "exposure_reference": pl.String,
    "exposure_class": pl.String,
    "pd": pl.Float64,
    "lgd": pl.Float64,
    "maturity": pl.Float64,
    "ead_final": pl.Float64,
    "turnover_m": pl.Float64,
    "requires_fi_scalar": pl.Boolean,
    "has_one_day_maturity_floor": pl.Boolean,
    "is_qrre_transactor": pl.Boolean,
    "rwa": pl.Float64,
    "risk_weight": pl.Float64,
    "expected_loss": pl.Float64,
    "guaranteed_portion": pl.Float64,
    "unguaranteed_portion": pl.Float64,
    "guarantor_entity_type": pl.String,
    "guarantor_cqs": pl.Int8,
    "guarantor_approach": pl.String,
    "guarantor_pd": pl.Float64,
    "guarantor_reference": pl.String,
    "guarantor_seniority": pl.String,
    "guarantor_is_financial_sector_entity": pl.Boolean,
    "original_maturity_years": pl.Float64,
}

# =============================================================================
# Expected Outputs Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def expected_outputs_path() -> Path:
    """Path to Basel 3.1 expected outputs directory."""
    return project_root / "tests" / "expected_outputs" / "basel31"


@pytest.fixture(scope="session")
def expected_outputs_df(expected_outputs_path: Path) -> pl.DataFrame:
    """Load all Basel 3.1 expected outputs as a Polars DataFrame.

    Supports parquet (fastest), CSV, and JSON (source of truth) formats.
    The JSON file contains a nested structure with metadata and a 'scenarios' array.
    """
    parquet_path = expected_outputs_path / "expected_rwa_b31.parquet"
    if parquet_path.exists():
        return pl.read_parquet(parquet_path)

    csv_path = expected_outputs_path / "expected_rwa_b31.csv"
    if csv_path.exists():
        return pl.read_csv(csv_path, null_values=[""])

    json_path = expected_outputs_path / "expected_rwa_b31.json"
    if json_path.exists():
        with open(json_path) as f:
            data = json.load(f)
        scenarios = data.get("scenarios", data)
        return pl.DataFrame(scenarios)

    msg = f"No expected outputs file found in {expected_outputs_path}"
    raise FileNotFoundError(msg)


@pytest.fixture(scope="session")
def expected_outputs_dict(expected_outputs_df: pl.DataFrame) -> dict[str, dict[str, Any]]:
    """Convert expected outputs to dictionary keyed by scenario_id."""
    return {row["scenario_id"]: row for row in expected_outputs_df.to_dicts()}


@pytest.fixture(scope="session")
def b31_a_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get B31-A (SA revised) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "B31-A")


@pytest.fixture(scope="session")
def b31_b_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get B31-B (Foundation IRB Revised) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "B31-B")


@pytest.fixture(scope="session")
def b31_c_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get B31-C (Advanced IRB Revised) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "B31-C")


@pytest.fixture(scope="session")
def b31_d_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get B31-D (Credit Risk Mitigation Revised) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "B31-D")


@pytest.fixture(scope="session")
def b31_e_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get B31-E (Specialised Lending Slotting) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "B31-E")


@pytest.fixture(scope="session")
def b31_f_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get B31-F (Output Floor) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "B31-F")


@pytest.fixture(scope="session")
def b31_g_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get B31-G (Provisions & Impairments) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "B31-G")


@pytest.fixture(scope="session")
def b31_h_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get B31-H (Complex/Combined) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "B31-H")


# =============================================================================
# Configuration Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def b31_calculation_config():
    """
    Create Basel 3.1 CalculationConfig for SA pipeline execution.

    Uses SA-only permissions for B31-A acceptance tests.
    Reporting date set to mid-2030 for fully-phased output floor (72.5%).
    """
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode

    return CalculationConfig.basel_3_1(
        reporting_date=date(2030, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )


@pytest.fixture(scope="session")
def b31_irb_calculation_config():
    """
    Create Basel 3.1 CalculationConfig with full IRB permissions.

    Used for output floor tests (B31-F) with fully-phased 72.5% floor.
    Reporting date set to 2032 to ensure full phase-in.
    """
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode

    return CalculationConfig.basel_3_1(
        reporting_date=date(2032, 6, 30),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture(scope="session")
def b31_firb_calculation_config():
    """
    Create Basel 3.1 CalculationConfig with F-IRB only permissions.

    Used for B31-B F-IRB acceptance tests. Reporting date 2027-06-30 gives
    meaningful maturities (1-5y) while being post Basel 3.1 effective date.

    Key differences from CRR F-IRB config:
    - Senior unsecured LGD: 40% (was 45%)
    - PD floor: 0.05% corporate (was 0.03%)
    - Scaling factor: 1.0 (was 1.06)
    - Supporting factor: disabled
    """
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode

    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture(scope="session")
def b31_slotting_calculation_config():
    """
    Create Basel 3.1 CalculationConfig with Slotting permissions.

    Permits Slotting (but not A-IRB) for SPECIALISED_LENDING.
    This ensures SL exposures route to slotting, not A-IRB.

    Key Basel 3.1 slotting differences from CRR:
    - Maturity split removed; all SL uses single Table A (PRA PS1/26 Art. 153(5))
    - PRA has NO separate pre-operational PF weights (unlike BCBS CRE33)
    - HVCRE weights unchanged
    """
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode

    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture(scope="session")
def b31_irb_transitional_config():
    """
    Create Basel 3.1 CalculationConfig with 2027 reporting date.

    Used for transitional output floor tests (60% floor in 2027).
    """
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode

    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.IRB,
    )


# =============================================================================
# Test Fixtures Loader
# =============================================================================


@pytest.fixture(scope="session")
def load_test_fixtures():
    """Load test fixtures from tests/fixtures directory."""
    from workbooks.shared.fixture_loader import load_fixtures

    return load_fixtures()


# =============================================================================
# Pipeline-Based Testing Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def raw_data_bundle(load_test_fixtures):
    """
    Convert test fixtures to RawDataBundle for SA pipeline processing.

    Uses the same fixtures as CRR tests — the difference is the framework config.
    No model_permissions needed for SA-only tests.
    """
    return build_raw_bundle(load_test_fixtures)


@pytest.fixture(scope="session")
def irb_raw_data_bundle(load_test_fixtures):
    """
    Convert test fixtures to RawDataBundle with model permissions for IRB testing.

    Enriches internal ratings with model_id and creates full-coverage
    model_permissions so the pipeline routes exposures to IRB approaches.
    """

    from tests.fixtures.irb_test_helpers import (
        create_full_irb_model_permissions,
    )

    return make_irb_bundle(load_test_fixtures, create_full_irb_model_permissions())


@pytest.fixture(scope="session")
def firb_raw_data_bundle(load_test_fixtures):
    """RawDataBundle with FIRB-only model permissions (no AIRB)."""
    from tests.fixtures.irb_test_helpers import (
        create_firb_only_model_permissions,
    )

    return make_irb_bundle(load_test_fixtures, create_firb_only_model_permissions())


@pytest.fixture(scope="session")
def slotting_raw_data_bundle(load_test_fixtures):
    """RawDataBundle with slotting-only model permissions."""
    from tests.fixtures.irb_test_helpers import (
        create_slotting_only_model_permissions,
    )

    return make_irb_bundle(load_test_fixtures, create_slotting_only_model_permissions())


@pytest.fixture(scope="session")
def pipeline_results(raw_data_bundle, b31_calculation_config):
    """
    Run all fixtures through the Basel 3.1 pipeline (SA-only) and return results.

    Session-scoped to avoid re-running the pipeline for each test.
    """
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    pipeline = PipelineOrchestrator()
    return pipeline.run_with_data(raw_data_bundle, b31_calculation_config)


@pytest.fixture(scope="session")
def pipeline_results_df(pipeline_results) -> pl.DataFrame:
    """Get Basel 3.1 pipeline results as a collected DataFrame."""
    return pipeline_results.results.collect()


@pytest.fixture(scope="session")
def sa_results_df(pipeline_results) -> pl.DataFrame:
    """Get Basel 3.1 SA results as a collected DataFrame."""
    if pipeline_results.sa_results is None:
        return pl.DataFrame()
    return pipeline_results.sa_results.collect()


@pytest.fixture(scope="session")
def irb_pipeline_results(irb_raw_data_bundle, b31_irb_calculation_config):
    """
    Run all fixtures through the Basel 3.1 pipeline with full IRB permissions.

    Used for output floor tests (B31-F). Session-scoped.
    """
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    pipeline = PipelineOrchestrator()
    return pipeline.run_with_data(irb_raw_data_bundle, b31_irb_calculation_config)


@pytest.fixture(scope="session")
def irb_pipeline_results_df(irb_pipeline_results) -> pl.DataFrame:
    """Get Basel 3.1 IRB pipeline results as a collected DataFrame."""
    return irb_pipeline_results.results.collect()


@pytest.fixture(scope="session")
def irb_only_results_df(irb_pipeline_results) -> pl.DataFrame:
    """Get IRB-only results from the Basel 3.1 pipeline."""
    if irb_pipeline_results.irb_results is None:
        return pl.DataFrame()
    return irb_pipeline_results.irb_results.collect()


@pytest.fixture(scope="session")
def firb_pipeline_results(firb_raw_data_bundle, b31_firb_calculation_config):
    """
    Run all fixtures through the Basel 3.1 pipeline with F-IRB only permissions.

    Used for B31-B F-IRB acceptance tests. Session-scoped.
    """
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    pipeline = PipelineOrchestrator()
    return pipeline.run_with_data(firb_raw_data_bundle, b31_firb_calculation_config)


@pytest.fixture(scope="session")
def firb_results_df(firb_pipeline_results) -> pl.DataFrame:
    """Get F-IRB results from the Basel 3.1 pipeline."""
    if firb_pipeline_results.irb_results is None:
        return pl.DataFrame()
    return firb_pipeline_results.irb_results.collect()


@pytest.fixture(scope="session")
def transitional_pipeline_results(irb_raw_data_bundle, b31_irb_transitional_config):
    """
    Run all fixtures through the Basel 3.1 pipeline with 2027 transitional floor.

    Used for transitional output floor test (B31-F3). Session-scoped.
    """
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    pipeline = PipelineOrchestrator()
    return pipeline.run_with_data(irb_raw_data_bundle, b31_irb_transitional_config)


@pytest.fixture(scope="session")
def transitional_results_df(transitional_pipeline_results) -> pl.DataFrame:
    """Get transitional pipeline results as a collected DataFrame."""
    return transitional_pipeline_results.results.collect()


@pytest.fixture(scope="session")
def airb_results_df(transitional_pipeline_results) -> pl.DataFrame:
    """Get A-IRB results from the Basel 3.1 pipeline.

    Reuses transitional pipeline (2027-06-30, full_irb) which provides
    meaningful maturities for A-IRB exposures. Session-scoped.
    """
    if transitional_pipeline_results.irb_results is None:
        return pl.DataFrame()
    return transitional_pipeline_results.irb_results.collect()


@pytest.fixture(scope="session")
def slotting_pipeline_results(slotting_raw_data_bundle, b31_slotting_calculation_config):
    """
    Run all fixtures through the Basel 3.1 pipeline with Slotting permissions.

    Used for B31-E slotting acceptance tests. Session-scoped.
    """
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    pipeline = PipelineOrchestrator()
    return pipeline.run_with_data(slotting_raw_data_bundle, b31_slotting_calculation_config)


@pytest.fixture(scope="session")
def slotting_results_df(slotting_pipeline_results) -> pl.DataFrame:
    """Get slotting results from the Basel 3.1 pipeline."""
    if slotting_pipeline_results.slotting_results is None:
        return pl.DataFrame()
    return slotting_pipeline_results.slotting_results.collect()


def run_sa_single_loan_result(
    fixtures_dir: Path,
    loan_ref: str,
    *,
    facility_link_ref: str | None = None,
    reporting_date: date = date(2027, 6, 30),
) -> dict:
    """
    Run a single-loan scenario fixture through the Basel 3.1 SA pipeline.

    Shared plumbing for scenario-local SA acceptance fixtures (P1.103 / P1.105 /
    P1.128).  Scans the counterparty / facility / loan / rating parquets from
    ``fixtures_dir`` and assembles a RawDataBundle with empty-schema auxiliary
    tables.

    When ``facility_link_ref`` is provided, ``facility_mappings`` carries one row
    linking ``loan_ref`` to that facility (so a facility-scoped rating override
    propagates onto the loan); when it is None, ``facility_mappings`` is built
    empty with the correct schema (the SCRA / unrated path).

    Args:
        fixtures_dir: Directory holding the scenario-local parquets.
        loan_ref: The loan/exposure reference to filter the SA results to.
        facility_link_ref: Parent facility reference to link to ``loan_ref``,
            or None for no facility mapping.
        reporting_date: Reporting date for the Basel 3.1 config.

    Returns:
        The single SA result row for ``loan_ref`` as a dict.
    """
    from rwa_calc.contracts.config import CalculationConfig, PermissionMode
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    # Arrange — load scenario-local parquets
    counterparties = pl.scan_parquet(fixtures_dir / "counterparty.parquet")
    facilities = pl.scan_parquet(fixtures_dir / "facility.parquet")
    loans = pl.scan_parquet(fixtures_dir / "loan.parquet")
    ratings = pl.scan_parquet(fixtures_dir / "rating.parquet")

    facility_mapping_schema = {
        "parent_facility_reference": pl.String,
        "child_reference": pl.String,
        "child_type": pl.String,
    }
    if facility_link_ref is None:
        facility_mappings = pl.LazyFrame(schema=facility_mapping_schema)
    else:
        facility_mappings = pl.LazyFrame(
            [
                {
                    "parent_facility_reference": facility_link_ref,
                    "child_reference": loan_ref,
                    "child_type": "loan",
                }
            ],
            schema=facility_mapping_schema,
        )
    lending_mappings = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )

    bundle = make_raw_bundle(
        facilities=facilities,
        loans=loans,
        counterparties=counterparties,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        ratings=ratings,
    )

    config = CalculationConfig.basel_3_1(
        reporting_date=reporting_date,
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act — run full Basel 3.1 SA pipeline
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, "SA results must not be None for SA-only config"

    df = results.sa_results.collect()
    rows = df.filter(pl.col("exposure_reference") == loan_ref).to_dicts()
    assert len(rows) == 1, (
        f"Expected exactly 1 row for {loan_ref!r}, got {len(rows)}. "
        f"All exposure_references: {df['exposure_reference'].to_list()}"
    )
    return rows[0]
