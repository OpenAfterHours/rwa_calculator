"""
Shared fixtures for CRR acceptance tests.

Provides common test configuration and helper utilities for validating
RWA calculations against expected outputs.
"""

import sys
from datetime import date
from decimal import Decimal
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
# (``from tests.acceptance.crr.conftest import ...``) keep resolving unchanged.
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
# Expected Outputs Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def expected_outputs_path() -> Path:
    """Path to CRR expected outputs directory."""
    return project_root / "tests" / "expected_outputs" / "crr"


@pytest.fixture(scope="session")
def expected_outputs_df(expected_outputs_path: Path) -> pl.DataFrame:
    """Load all CRR expected outputs as a Polars DataFrame."""
    parquet_path = expected_outputs_path / "expected_rwa_crr.parquet"
    if parquet_path.exists():
        return pl.read_parquet(parquet_path)
    # Fall back to CSV if parquet doesn't exist
    csv_path = expected_outputs_path / "expected_rwa_crr.csv"
    return pl.read_csv(csv_path)


@pytest.fixture(scope="session")
def expected_outputs_dict(expected_outputs_df: pl.DataFrame) -> dict[str, dict[str, Any]]:
    """Convert expected outputs to dictionary keyed by scenario_id."""
    return {row["scenario_id"]: row for row in expected_outputs_df.to_dicts()}


@pytest.fixture(scope="session")
def crr_a_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get CRR-A (SA) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "CRR-A")


@pytest.fixture(scope="session")
def crr_b_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get CRR-B (F-IRB) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "CRR-B")


@pytest.fixture(scope="session")
def crr_c_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get CRR-C (A-IRB) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "CRR-C")


@pytest.fixture(scope="session")
def crr_d_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get CRR-D (CRM) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "CRR-D")


@pytest.fixture(scope="session")
def crr_e_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get CRR-E (Slotting) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "CRR-E")


@pytest.fixture(scope="session")
def crr_f_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get CRR-F (Supporting Factors) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "CRR-F")


@pytest.fixture(scope="session")
def crr_g_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get CRR-G (Provisions) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "CRR-G")


@pytest.fixture(scope="session")
def crr_h_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get CRR-H (Complex) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "CRR-H")


# =============================================================================
# Configuration Fixtures
# =============================================================================


@pytest.fixture
def crr_config() -> dict[str, Any]:
    """
    Standard CRR configuration for all tests.

    Note: GBP thresholds are derived from EUR regulatory values using
    the configurable FX rate in src/rwa_calc/config/fx_rates.py
    """
    return {
        "regulatory_framework": "CRR",
        "basel_version": "3.0",
        "reporting_date": "2025-12-31",
        "apply_sme_supporting_factor": True,
        "apply_infrastructure_factor": True,
        # SME eligibility threshold (turnover). CRR Art. 501: EUR is the regulatory
        # source of truth (now the rulepack regulatory_thresholds bundle); GBP is
        # EUR × the default 0.8732 FX rate. Mirrored here for the fixture config.
        "sme_turnover_threshold_gbp": Decimal("50000000") * Decimal("0.8732"),
        "sme_turnover_threshold_eur": Decimal("50000000"),
        # SME supporting factor - tiered approach (CRR2 Art. 501)
        "sme_exposure_threshold_gbp": Decimal("2500000") * Decimal("0.8732"),
        "sme_exposure_threshold_eur": Decimal("2500000"),
        "sme_supporting_factor_tier1": Decimal("0.7619"),  # Up to threshold
        "sme_supporting_factor_tier2": Decimal("0.85"),  # Above threshold
        # Infrastructure factor (not tiered)
        "infrastructure_factor": Decimal("0.75"),
        # IRB parameters
        "pd_floor": Decimal("0.0003"),  # 0.03% single floor
        "maturity_floor": Decimal("1.0"),
        "maturity_cap": Decimal("5.0"),
    }


@pytest.fixture
def crr_risk_weights() -> dict[str, Any]:
    """CRR SA risk weight lookup tables."""
    return {
        "sovereign": {
            1: Decimal("0.00"),
            2: Decimal("0.20"),
            3: Decimal("0.50"),
            4: Decimal("1.00"),
            5: Decimal("1.00"),
            6: Decimal("1.50"),
            None: Decimal("1.00"),
        },
        "institution": {
            1: Decimal("0.20"),
            2: Decimal("0.50"),  # CRR Art. 120 Table 3
            3: Decimal("0.50"),
            4: Decimal("1.00"),
            5: Decimal("1.00"),
            6: Decimal("1.50"),
            None: Decimal("1.00"),  # CRR Art. 120(2) unrated
        },
        "corporate": {
            1: Decimal("0.20"),
            2: Decimal("0.50"),
            3: Decimal("1.00"),
            4: Decimal("1.00"),
            5: Decimal("1.50"),
            6: Decimal("1.50"),
            None: Decimal("1.00"),
        },
        "retail": Decimal("0.75"),
        "residential_mortgage": {
            "low_ltv": Decimal("0.35"),  # LTV <= 80%
            "high_ltv": Decimal("0.75"),  # Portion above 80%
            "threshold": Decimal("0.80"),
        },
        "commercial_re": {
            "low_ltv": Decimal("0.50"),  # LTV <= 50% with income cover
            "standard": Decimal("1.00"),
            "threshold": Decimal("0.50"),
        },
    }


@pytest.fixture
def crr_firb_lgd() -> dict[str, Decimal]:
    """CRR F-IRB supervisory LGD values."""
    return {
        "unsecured_senior": Decimal("0.45"),
        "subordinated": Decimal("0.75"),
        "financial_collateral": Decimal("0.00"),
        "receivables": Decimal("0.35"),
        "residential_re": Decimal("0.35"),
        "commercial_re": Decimal("0.35"),
        "other_physical": Decimal("0.40"),
    }


@pytest.fixture
def crr_haircuts() -> dict[str, Decimal]:
    """CRR supervisory haircuts."""
    return {
        "cash": Decimal("0.00"),
        "gold": Decimal("0.15"),
        "govt_bond_cqs1_0_1y": Decimal("0.005"),
        "govt_bond_cqs1_1_5y": Decimal("0.02"),
        "govt_bond_cqs1_5y_plus": Decimal("0.04"),
        "equity_main_index": Decimal("0.15"),
        "equity_other": Decimal("0.25"),
        "fx_mismatch": Decimal("0.08"),
    }


@pytest.fixture
def crr_ccf() -> dict[str, Decimal]:
    """CRR credit conversion factors."""
    return {
        "full_risk": Decimal("1.00"),
        "medium_risk": Decimal("0.50"),
        "medium_low_risk": Decimal("0.20"),
        "low_risk": Decimal("0.00"),
    }


@pytest.fixture
def crr_slotting_rw() -> dict[str, Decimal]:
    """CRR slotting risk weights (non-HVCRE, >=2.5yr maturity)."""
    return {
        "strong": Decimal("0.70"),
        "good": Decimal("0.90"),
        "satisfactory": Decimal("1.15"),
        "weak": Decimal("2.50"),
        "default": Decimal("0.00"),
    }


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
def crr_calculation_config():
    """
    Create CRR CalculationConfig for pipeline execution.

    Uses SA-only permissions for acceptance tests to ensure
    SA scenarios are processed using the Standardised Approach.
    IRB tests use a separate config with IRB permissions.
    """
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode

    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    )


@pytest.fixture(scope="session")
def crr_irb_calculation_config():
    """
    Create CRR CalculationConfig with full IRB permissions.

    Used for IRB scenario tests (CRR-B, CRR-C).
    """
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode

    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture(scope="session")
def crr_slotting_calculation_config():
    """
    Create CRR CalculationConfig with slotting permissions for specialised lending.

    For slotting tests, we permit SLOTTING but not A-IRB for SPECIALISED_LENDING
    to ensure exposures use the slotting approach instead of A-IRB.
    """
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode

    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture(scope="session")
def raw_data_bundle(load_test_fixtures):
    """
    Convert test fixtures to RawDataBundle for pipeline processing.

    This assembles all fixture LazyFrames into the format expected
    by the production pipeline.
    """
    return build_raw_bundle(load_test_fixtures)


@pytest.fixture(scope="session")
def irb_raw_data_bundle(load_test_fixtures):
    """
    Convert test fixtures to RawDataBundle with model permissions for IRB testing.
    """

    from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions

    return make_irb_bundle(load_test_fixtures, create_full_irb_model_permissions())


@pytest.fixture(scope="session")
def slotting_raw_data_bundle(load_test_fixtures):
    """RawDataBundle with slotting-only model permissions."""
    from tests.fixtures.irb_test_helpers import create_slotting_only_model_permissions

    return make_irb_bundle(load_test_fixtures, create_slotting_only_model_permissions())


@pytest.fixture(scope="session")
def pipeline_results(raw_data_bundle, crr_calculation_config):
    """
    Run all fixtures through the pipeline and return results.

    This is session-scoped to avoid re-running the pipeline for each test.
    The results are cached and shared across all acceptance tests.

    Returns:
        AggregatedResultBundle with all calculation results
    """
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    pipeline = PipelineOrchestrator()
    result = pipeline.run_with_data(raw_data_bundle, crr_calculation_config)

    return result


@pytest.fixture(scope="session")
def pipeline_results_df(pipeline_results) -> pl.DataFrame:
    """
    Get pipeline results as a collected DataFrame.

    Provides easy access to results for individual scenario lookups.
    """
    return pipeline_results.results.collect()


@pytest.fixture(scope="session")
def sa_results_df(pipeline_results) -> pl.DataFrame:
    """Get SA results as a collected DataFrame."""
    if pipeline_results.sa_results is None:
        return pl.DataFrame()
    return pipeline_results.sa_results.collect()


@pytest.fixture(scope="session")
def irb_results_df(pipeline_results) -> pl.DataFrame:
    """Get IRB results as a collected DataFrame."""
    if pipeline_results.irb_results is None:
        return pl.DataFrame()
    return pipeline_results.irb_results.collect()


@pytest.fixture(scope="session")
def slotting_pipeline_results(slotting_raw_data_bundle, crr_slotting_calculation_config):
    """
    Run all fixtures through the pipeline with slotting permissions.

    Used for slotting scenario tests (CRR-E).
    This config permits SLOTTING but NOT A-IRB for SPECIALISED_LENDING,
    ensuring exposures are routed to the slotting approach.

    Returns:
        AggregatedResultBundle with slotting calculation results
    """
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    pipeline = PipelineOrchestrator()
    result = pipeline.run_with_data(slotting_raw_data_bundle, crr_slotting_calculation_config)

    return result


@pytest.fixture(scope="session")
def slotting_results_df(slotting_pipeline_results) -> pl.DataFrame:
    """
    Get Slotting results as a collected DataFrame.

    Uses slotting_pipeline_results which permits SLOTTING but not A-IRB
    for SPECIALISED_LENDING exposures.
    """
    if slotting_pipeline_results.slotting_results is None:
        return pl.DataFrame()
    return slotting_pipeline_results.slotting_results.collect()


@pytest.fixture(scope="session")
def irb_pipeline_results(irb_raw_data_bundle, crr_irb_calculation_config):
    """
    Run all fixtures through the pipeline with IRB permissions.

    Used for IRB scenario tests (CRR-B F-IRB, CRR-C A-IRB).
    Session-scoped to avoid re-running for each test.

    Returns:
        AggregatedResultBundle with IRB calculation results
    """
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    pipeline = PipelineOrchestrator()
    result = pipeline.run_with_data(irb_raw_data_bundle, crr_irb_calculation_config)

    return result


@pytest.fixture(scope="session")
def irb_pipeline_results_df(irb_pipeline_results) -> pl.DataFrame:
    """Get IRB pipeline results as a collected DataFrame."""
    return irb_pipeline_results.results.collect()


@pytest.fixture(scope="session")
def irb_only_results_df(irb_pipeline_results) -> pl.DataFrame:
    """Get IRB-only results from the IRB pipeline."""
    if irb_pipeline_results.irb_results is None:
        return pl.DataFrame()
    return irb_pipeline_results.irb_results.collect()


def get_slotting_result_for_exposure(
    slotting_results_df: pl.DataFrame,
    exposure_reference: str,
) -> dict | None:
    """Look up Slotting result for a specific exposure."""
    return get_result_for_exposure(slotting_results_df, exposure_reference)


# =============================================================================
# Single-Guarantee SA Pipeline Helpers (shared by P1.109 / P1.124)
# =============================================================================


def run_single_guarantee_sa_pipeline(
    fixtures_dir: Path,
    reporting_date: date,
    guarantee_ref: str,
) -> pl.DataFrame:
    """
    Run the full CRR SA pipeline for a single-guarantee scenario.

    Builds a RawDataBundle with empty facilities/facility_mappings/lending_mappings
    schemas, scans the loan/counterparty/rating parquet files under ``fixtures_dir``,
    and filters the guarantee parquet to exactly the ``guarantee_ref`` row. Runs an
    SA-only ``CalculationConfig.crr`` through the pipeline orchestrator.

    Args:
        fixtures_dir: Directory holding loan/counterparty/rating/guarantee parquet files.
        reporting_date: Reporting date passed to ``CalculationConfig.crr``.
        guarantee_ref: The single ``guarantee_reference`` value to retain.

    Returns:
        The SA results DataFrame (all rows, including guarantee sub-rows).
    """
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    single_guar = pl.scan_parquet(fixtures_dir / "guarantee.parquet").filter(
        pl.col("guarantee_reference") == guarantee_ref
    )
    bundle = make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={
                "facility_reference": pl.String,
                "counterparty_reference": pl.String,
            }
        ),
        loans=pl.scan_parquet(fixtures_dir / "loan.parquet"),
        counterparties=pl.scan_parquet(fixtures_dir / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
        ratings=pl.scan_parquet(fixtures_dir / "rating.parquet"),
        guarantees=single_guar,
    )
    config = CalculationConfig.crr(
        reporting_date=reporting_date,
        permission_mode=PermissionMode.STANDARDISED,
    )
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None, "SA results must not be None for SA-only config"
    return results.sa_results.collect()


def aggregate_sa_rows_by_parent(df: pl.DataFrame, parent_ref: str) -> dict:
    """
    Aggregate all sub-rows (guarantee split rows + remainder) for a parent exposure.

    Additive fields (rwa_final, guaranteed_portion, unguaranteed_portion, ead_final)
    are summed. The first value is used for non-additive fields.

    Args:
        df: SA results DataFrame.
        parent_ref: The ``parent_exposure_reference`` whose sub-rows are aggregated.

    Returns:
        dict of aggregated result values.
    """
    sub_rows = df.filter(pl.col("parent_exposure_reference") == parent_ref)
    assert sub_rows.height > 0, (
        f"No SA result rows found with parent_exposure_reference='{parent_ref}'"
    )
    _additive = {"rwa_final", "guaranteed_portion", "unguaranteed_portion", "ead_final"}
    result: dict = {}
    for col_name in sub_rows.columns:
        if col_name in _additive:
            result[col_name] = sub_rows[col_name].sum()
        else:
            result[col_name] = sub_rows[col_name][0]
    return result
