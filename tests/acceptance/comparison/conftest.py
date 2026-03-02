"""
Shared fixtures for dual-framework comparison acceptance tests.

Provides session-scoped pipeline execution for both CRR and Basel 3.1
frameworks on the same fixture data, plus the DualFrameworkRunner
comparison results.

Why these tests matter:
    During the Basel 3.1 transition (PRA PS9/24, 1 Jan 2027), firms must
    quantify the capital impact of moving from CRR to Basel 3.1. These
    acceptance tests validate that the DualFrameworkRunner correctly
    identifies and quantifies the differences between frameworks.
"""

import sys
from datetime import date
from pathlib import Path

import polars as pl
import pytest

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


# =============================================================================
# Configuration Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def crr_sa_config():
    """CRR config with SA-only permissions for comparison."""
    from rwa_calc.contracts.config import CalculationConfig, IRBPermissions

    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        irb_permissions=IRBPermissions.sa_only(),
    )


@pytest.fixture(scope="session")
def b31_sa_config():
    """Basel 3.1 config with SA-only permissions for comparison."""
    from rwa_calc.contracts.config import CalculationConfig, IRBPermissions

    return CalculationConfig.basel_3_1(
        reporting_date=date(2030, 6, 30),
        irb_permissions=IRBPermissions.sa_only(),
    )


@pytest.fixture(scope="session")
def crr_firb_config():
    """CRR config with F-IRB permissions for comparison."""
    from rwa_calc.contracts.config import CalculationConfig, IRBPermissions

    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        irb_permissions=IRBPermissions.firb_only(),
    )


@pytest.fixture(scope="session")
def b31_firb_config():
    """Basel 3.1 config with F-IRB permissions for comparison.

    Uses 2027-06-30 reporting date for meaningful maturities
    from fixture loans (maturity dates 2028-2033).
    """
    from rwa_calc.contracts.config import CalculationConfig, IRBPermissions

    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        irb_permissions=IRBPermissions.firb_only(),
    )


# =============================================================================
# Data Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def load_test_fixtures():
    """Load test fixtures from tests/fixtures directory."""
    from workbooks.shared.fixture_loader import load_fixtures

    return load_fixtures()


@pytest.fixture(scope="session")
def raw_data_bundle(load_test_fixtures):
    """Convert test fixtures to RawDataBundle for pipeline processing."""
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


# =============================================================================
# Comparison Results Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def sa_comparison(raw_data_bundle, crr_sa_config, b31_sa_config):
    """Run DualFrameworkRunner with SA-only permissions.

    Session-scoped: runs both CRR and B31 pipelines once,
    joins results, computes deltas. Shared across all SA comparison tests.
    """
    from rwa_calc.engine.comparison import DualFrameworkRunner

    runner = DualFrameworkRunner()
    return runner.compare(raw_data_bundle, crr_sa_config, b31_sa_config)


@pytest.fixture(scope="session")
def sa_comparison_deltas_df(sa_comparison) -> pl.DataFrame:
    """Collected exposure-level deltas for SA comparison."""
    return sa_comparison.exposure_deltas.collect()


@pytest.fixture(scope="session")
def sa_comparison_class_summary_df(sa_comparison) -> pl.DataFrame:
    """Collected summary by exposure class for SA comparison."""
    return sa_comparison.summary_by_class.collect()


@pytest.fixture(scope="session")
def sa_comparison_approach_summary_df(sa_comparison) -> pl.DataFrame:
    """Collected summary by approach for SA comparison."""
    return sa_comparison.summary_by_approach.collect()


@pytest.fixture(scope="session")
def firb_comparison(raw_data_bundle, crr_firb_config, b31_firb_config):
    """Run DualFrameworkRunner with F-IRB permissions.

    Session-scoped: compares CRR F-IRB vs Basel 3.1 F-IRB.
    Key differences: LGD 45% vs 40%, PD floor 0.03% vs 0.05%,
    scaling factor 1.06 vs 1.0, supporting factors on vs off.
    """
    from rwa_calc.engine.comparison import DualFrameworkRunner

    runner = DualFrameworkRunner()
    return runner.compare(raw_data_bundle, crr_firb_config, b31_firb_config)


@pytest.fixture(scope="session")
def firb_comparison_deltas_df(firb_comparison) -> pl.DataFrame:
    """Collected exposure-level deltas for F-IRB comparison."""
    return firb_comparison.exposure_deltas.collect()


# =============================================================================
# Capital Impact Analysis Fixtures (M3.2)
# =============================================================================


@pytest.fixture(scope="session")
def sa_capital_impact(sa_comparison):
    """Capital impact analysis for SA-only comparison.

    Session-scoped: decomposes the SA comparison deltas into
    driver attribution (supporting factor removal, methodology changes).
    """
    from rwa_calc.engine.comparison import CapitalImpactAnalyzer

    return CapitalImpactAnalyzer().analyze(sa_comparison)


@pytest.fixture(scope="session")
def sa_impact_attribution_df(sa_capital_impact) -> pl.DataFrame:
    """Collected per-exposure attribution for SA comparison."""
    return sa_capital_impact.exposure_attribution.collect()


@pytest.fixture(scope="session")
def sa_impact_waterfall_df(sa_capital_impact) -> pl.DataFrame:
    """Collected portfolio waterfall for SA comparison."""
    return sa_capital_impact.portfolio_waterfall.collect()


@pytest.fixture(scope="session")
def sa_impact_class_summary_df(sa_capital_impact) -> pl.DataFrame:
    """Collected attribution summary by class for SA comparison."""
    return sa_capital_impact.summary_by_class.collect()


@pytest.fixture(scope="session")
def firb_capital_impact(firb_comparison):
    """Capital impact analysis for F-IRB comparison.

    Session-scoped: decomposes the F-IRB comparison deltas into
    driver attribution (scaling factor, supporting factor, methodology, floor).
    """
    from rwa_calc.engine.comparison import CapitalImpactAnalyzer

    return CapitalImpactAnalyzer().analyze(firb_comparison)


@pytest.fixture(scope="session")
def firb_impact_attribution_df(firb_capital_impact) -> pl.DataFrame:
    """Collected per-exposure attribution for F-IRB comparison."""
    return firb_capital_impact.exposure_attribution.collect()


@pytest.fixture(scope="session")
def firb_impact_waterfall_df(firb_capital_impact) -> pl.DataFrame:
    """Collected portfolio waterfall for F-IRB comparison."""
    return firb_capital_impact.portfolio_waterfall.collect()


@pytest.fixture(scope="session")
def firb_impact_class_summary_df(firb_capital_impact) -> pl.DataFrame:
    """Collected attribution summary by class for F-IRB comparison."""
    return firb_capital_impact.summary_by_class.collect()


# =============================================================================
# Assertion Helpers
# =============================================================================


def get_delta_for_exposure(
    deltas_df: pl.DataFrame,
    exposure_reference: str,
) -> dict | None:
    """Look up comparison delta for a specific exposure."""
    filtered = deltas_df.filter(pl.col("exposure_reference") == exposure_reference)
    if filtered.height == 0:
        return None
    return filtered.row(0, named=True)
