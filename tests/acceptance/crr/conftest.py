"""
Shared fixtures for CRR acceptance tests.

Provides common test configuration and helper utilities for validating
RWA calculations against expected outputs.
"""

import pytest
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys
from typing import Any

import polars as pl

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.rwa_calc.config.fx_rates import (
    CRR_REGULATORY_THRESHOLDS_EUR,
    get_crr_threshold_gbp,
)


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
    return {
        row["scenario_id"]: row
        for row in expected_outputs_df.to_dicts()
    }


def get_scenarios_by_group(
    expected_outputs_df: pl.DataFrame,
    group: str,
) -> list[dict[str, Any]]:
    """Filter scenarios by group prefix."""
    return expected_outputs_df.filter(
        pl.col("scenario_group") == group
    ).to_dicts()


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
        # SME eligibility threshold (turnover)
        # EUR is regulatory source of truth; GBP derived from FX rate
        "sme_turnover_threshold_gbp": get_crr_threshold_gbp("sme_turnover"),
        "sme_turnover_threshold_eur": CRR_REGULATORY_THRESHOLDS_EUR["sme_turnover"],
        # SME supporting factor - tiered approach (CRR2 Art. 501)
        # EUR is regulatory source of truth; GBP derived from FX rate
        "sme_exposure_threshold_gbp": get_crr_threshold_gbp("sme_exposure"),
        "sme_exposure_threshold_eur": CRR_REGULATORY_THRESHOLDS_EUR["sme_exposure"],
        "sme_supporting_factor_tier1": Decimal("0.7619"),  # Up to threshold
        "sme_supporting_factor_tier2": Decimal("0.85"),    # Above threshold
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
        "institution_uk": {
            1: Decimal("0.20"),
            2: Decimal("0.30"),  # UK deviation
            3: Decimal("0.50"),
            4: Decimal("1.00"),
            5: Decimal("1.00"),
            6: Decimal("1.50"),
            None: Decimal("0.40"),
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
    """CRR slotting risk weights."""
    return {
        "strong": Decimal("0.70"),
        "good": Decimal("0.70"),
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
# Assertion Helpers
# =============================================================================


def assert_rwa_within_tolerance(
    actual: float,
    expected: float,
    tolerance: float = 0.01,
    scenario_id: str = "",
) -> None:
    """
    Assert RWA values are within acceptable tolerance.

    Args:
        actual: The calculated RWA value
        expected: The expected RWA value
        tolerance: Relative tolerance (default 1%)
        scenario_id: Scenario ID for error messages
    """
    if expected == 0:
        assert actual == 0, f"{scenario_id}: Expected 0, got {actual}"
    else:
        relative_diff = abs(actual - expected) / abs(expected)
        assert relative_diff <= tolerance, (
            f"{scenario_id}: RWA difference {relative_diff*100:.2f}% exceeds "
            f"tolerance {tolerance*100:.0f}%: actual={actual:,.2f}, expected={expected:,.2f}"
        )


def assert_risk_weight_match(
    actual: float,
    expected: float,
    tolerance: float = 0.0001,
    scenario_id: str = "",
) -> None:
    """
    Assert risk weight values match exactly (or within very small tolerance).

    Args:
        actual: The calculated risk weight
        expected: The expected risk weight
        tolerance: Absolute tolerance (default 0.01%)
        scenario_id: Scenario ID for error messages
    """
    diff = abs(actual - expected)
    assert diff <= tolerance, (
        f"{scenario_id}: Risk weight mismatch: actual={actual:.4f}, expected={expected:.4f}"
    )


def assert_ead_match(
    actual: float,
    expected: float,
    tolerance: float = 0.01,
    scenario_id: str = "",
) -> None:
    """
    Assert EAD values match within tolerance.

    Args:
        actual: The calculated EAD value
        expected: The expected EAD value
        tolerance: Relative tolerance (default 1%)
        scenario_id: Scenario ID for error messages
    """
    if expected == 0:
        assert actual == 0, f"{scenario_id}: Expected EAD 0, got {actual}"
    else:
        relative_diff = abs(actual - expected) / abs(expected)
        assert relative_diff <= tolerance, (
            f"{scenario_id}: EAD difference {relative_diff*100:.2f}% exceeds "
            f"tolerance {tolerance*100:.0f}%: actual={actual:,.2f}, expected={expected:,.2f}"
        )


def assert_supporting_factor_match(
    actual: float,
    expected: float,
    scenario_id: str = "",
) -> None:
    """
    Assert supporting factor matches exactly.

    Args:
        actual: The calculated supporting factor
        expected: The expected supporting factor
        scenario_id: Scenario ID for error messages
    """
    assert actual == pytest.approx(expected, rel=0.0001), (
        f"{scenario_id}: Supporting factor mismatch: actual={actual}, expected={expected}"
    )


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
    from rwa_calc.contracts.config import CalculationConfig, IRBPermissions

    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        irb_permissions=IRBPermissions.sa_only(),
    )


@pytest.fixture(scope="session")
def crr_irb_calculation_config():
    """
    Create CRR CalculationConfig with full IRB permissions.

    Used for IRB scenario tests (CRR-B, CRR-C).
    """
    from rwa_calc.contracts.config import CalculationConfig, IRBPermissions

    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        irb_permissions=IRBPermissions.full_irb(),
    )


@pytest.fixture(scope="session")
def raw_data_bundle(load_test_fixtures):
    """
    Convert test fixtures to RawDataBundle for pipeline processing.

    This assembles all fixture LazyFrames into the format expected
    by the production pipeline.
    """
    from rwa_calc.contracts.bundles import RawDataBundle

    fixtures = load_test_fixtures

    return RawDataBundle(
        facilities=fixtures.facilities,
        loans=fixtures.loans,
        contingents=fixtures.contingents,
        counterparties=fixtures.get_all_counterparties(),
        collateral=fixtures.collateral,
        guarantees=fixtures.guarantees,
        provisions=fixtures.provisions,
        ratings=fixtures.ratings,
        facility_mappings=fixtures.facility_mappings,
        org_mappings=fixtures.org_mappings,
        lending_mappings=fixtures.lending_mappings,
        specialised_lending=fixtures.specialised_lending,
    )


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
def slotting_results_df(pipeline_results) -> pl.DataFrame:
    """Get Slotting results as a collected DataFrame."""
    if pipeline_results.slotting_results is None:
        return pl.DataFrame()
    return pipeline_results.slotting_results.collect()


@pytest.fixture(scope="session")
def irb_pipeline_results(raw_data_bundle, crr_irb_calculation_config):
    """
    Run all fixtures through the pipeline with IRB permissions.

    Used for IRB scenario tests (CRR-B F-IRB, CRR-C A-IRB).
    Session-scoped to avoid re-running for each test.

    Returns:
        AggregatedResultBundle with IRB calculation results
    """
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    pipeline = PipelineOrchestrator()
    result = pipeline.run_with_data(raw_data_bundle, crr_irb_calculation_config)

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


def get_result_for_exposure(
    results_df: pl.DataFrame,
    exposure_reference: str,
) -> dict | None:
    """
    Look up calculation result for a specific exposure.

    Args:
        results_df: DataFrame of pipeline results
        exposure_reference: The exposure reference to find

    Returns:
        dict of result values, or None if not found
    """
    filtered = results_df.filter(
        pl.col("exposure_reference") == exposure_reference
    )

    if filtered.height == 0:
        return None
    return filtered.row(0, named=True)


def get_sa_result_for_exposure(
    sa_results_df: pl.DataFrame,
    exposure_reference: str,
) -> dict | None:
    """Look up SA result for a specific exposure."""
    return get_result_for_exposure(sa_results_df, exposure_reference)


def get_irb_result_for_exposure(
    irb_results_df: pl.DataFrame,
    exposure_reference: str,
) -> dict | None:
    """Look up IRB result for a specific exposure."""
    return get_result_for_exposure(irb_results_df, exposure_reference)


def get_slotting_result_for_exposure(
    slotting_results_df: pl.DataFrame,
    exposure_reference: str,
) -> dict | None:
    """Look up Slotting result for a specific exposure."""
    return get_result_for_exposure(slotting_results_df, exposure_reference)
