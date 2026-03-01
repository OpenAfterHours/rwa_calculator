"""
Shared fixtures for Basel 3.1 acceptance tests.

Provides common test configuration and helper utilities for validating
Basel 3.1 RWA calculations against expected outputs.

Why these tests matter:
    Basel 3.1 (PRA PS9/24, effective 1 Jan 2027) introduces material changes
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


def get_scenarios_by_group(
    expected_outputs_df: pl.DataFrame,
    group: str,
) -> list[dict[str, Any]]:
    """Filter scenarios by group prefix."""
    return expected_outputs_df.filter(pl.col("scenario_group") == group).to_dicts()


@pytest.fixture(scope="session")
def b31_a_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get B31-A (SA revised) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "B31-A")


@pytest.fixture(scope="session")
def b31_f_scenarios(expected_outputs_df: pl.DataFrame) -> list[dict[str, Any]]:
    """Get B31-F (Output Floor) scenarios."""
    return get_scenarios_by_group(expected_outputs_df, "B31-F")


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
    from rwa_calc.contracts.config import CalculationConfig, IRBPermissions

    return CalculationConfig.basel_3_1(
        reporting_date=date(2030, 6, 30),
        irb_permissions=IRBPermissions.sa_only(),
    )


@pytest.fixture(scope="session")
def b31_irb_calculation_config():
    """
    Create Basel 3.1 CalculationConfig with full IRB permissions.

    Used for output floor tests (B31-F) with fully-phased 72.5% floor.
    Reporting date set to 2032 to ensure full phase-in.
    """
    from rwa_calc.contracts.config import CalculationConfig, IRBPermissions

    return CalculationConfig.basel_3_1(
        reporting_date=date(2032, 6, 30),
        irb_permissions=IRBPermissions.full_irb(),
    )


@pytest.fixture(scope="session")
def b31_irb_transitional_config():
    """
    Create Basel 3.1 CalculationConfig with 2027 reporting date.

    Used for transitional output floor tests (50% floor in 2027).
    """
    from rwa_calc.contracts.config import CalculationConfig, IRBPermissions

    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        irb_permissions=IRBPermissions.full_irb(),
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
            f"{scenario_id}: RWA difference {relative_diff * 100:.2f}% exceeds "
            f"tolerance {tolerance * 100:.0f}%: actual={actual:,.2f}, expected={expected:,.2f}"
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
            f"{scenario_id}: EAD difference {relative_diff * 100:.2f}% exceeds "
            f"tolerance {tolerance * 100:.0f}%: actual={actual:,.2f}, expected={expected:,.2f}"
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
def raw_data_bundle(load_test_fixtures):
    """
    Convert test fixtures to RawDataBundle for pipeline processing.

    Uses the same fixtures as CRR tests — the difference is the framework config.
    This validates that the same portfolio produces different (correct) results
    under each framework.
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
def irb_pipeline_results(raw_data_bundle, b31_irb_calculation_config):
    """
    Run all fixtures through the Basel 3.1 pipeline with full IRB permissions.

    Used for output floor tests (B31-F). Session-scoped.
    """
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    pipeline = PipelineOrchestrator()
    return pipeline.run_with_data(raw_data_bundle, b31_irb_calculation_config)


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
def transitional_pipeline_results(raw_data_bundle, b31_irb_transitional_config):
    """
    Run all fixtures through the Basel 3.1 pipeline with 2027 transitional floor.

    Used for transitional output floor test (B31-F3). Session-scoped.
    """
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    pipeline = PipelineOrchestrator()
    return pipeline.run_with_data(raw_data_bundle, b31_irb_transitional_config)


@pytest.fixture(scope="session")
def transitional_results_df(transitional_pipeline_results) -> pl.DataFrame:
    """Get transitional pipeline results as a collected DataFrame."""
    return transitional_pipeline_results.results.collect()


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
    filtered = results_df.filter(pl.col("exposure_reference") == exposure_reference)

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
