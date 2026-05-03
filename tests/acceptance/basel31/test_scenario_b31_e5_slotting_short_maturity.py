"""
Basel 3.1 Scenario B31-E5: Non-HVCRE Slotting Short-Maturity Column A/C.

Tests PRA PS1/26 Appendix 1, Art. 153(5)(d) — the column-A/C concession that
applies reduced risk weights when residual maturity is < 2.5 years for non-HVCRE
specialised lending under the Basel 3.1 supervisory slotting approach.

Key assertion:
    Strong, short maturity (<2.5yr) → RW = 50% (Table A col A)
    Strong, long maturity (>=2.5yr) → RW = 70% (Table A col B)
    Good,   short maturity (<2.5yr) → RW = 70% (Table A col C)
    Good,   long maturity (>=2.5yr) → RW = 90% (Table A col D)
    Satisfactory, any maturity      → RW = 115% (no col split)
    Weak,         any maturity      → RW = 250% (no col split)
    Default,      any maturity      → RW = 0%   (no col split)

Current engine behaviour (before fix):
    B31 lookup_rw ignores is_short for non-HVCRE — always returns base table.
    Strong short → 70% (WRONG — should be 50%).

Regulatory references:
    - PRA PS1/26 Appendix 1, Art. 153(5)(d), Table A (p. 103)
    - PRA PS1/26 Appendix 1, Art. 158(6), Table B (p. 108)
    - docs/specifications/basel31/slotting-approach.md §5 (lines 191-200)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from tests.acceptance.basel31.conftest import (
    assert_risk_weight_match,
    assert_rwa_within_tolerance,
    get_result_for_exposure,
)

# ---------------------------------------------------------------------------
# Exposure references — these are loan_references from the fixture builder,
# which the pipeline renames to exposure_reference via hierarchy.py line 1729.
# Reporting date: 2027-06-30  (CalculationConfig.basel_3_1 in conftest)
# Short maturity_date: 2029-06-30 → residual ≈ 2.0yr → is_short_maturity=True
# Long  maturity_date: 2031-06-30 → residual ≈ 4.0yr → is_short_maturity=False
# ---------------------------------------------------------------------------

_STRONG_SHORT = "LOAN-B31-SL-PF-STRONG-SHORT"
_STRONG_LONG = "LOAN-B31-SL-PF-STRONG-LONG"
_GOOD_SHORT = "LOAN-B31-SL-PF-GOOD-SHORT"
_GOOD_LONG = "LOAN-B31-SL-PF-GOOD-LONG"
_SAT_SHORT = "LOAN-B31-SL-PF-SAT-SHORT"
_WEAK_SHORT = "LOAN-B31-SL-PF-WEAK-SHORT"
_DEFAULT_SHORT = "LOAN-B31-SL-PF-DEFAULT-SHORT"

# EAD for all B31-E5 fixtures (£1,000,000 each)
_EAD = 1_000_000.0

# Model ID used for B31-E5 slotting permissions
_B31E5_MODEL_ID = "B31_E5_SLOTTING_MODEL"

# Reporting date (post-Basel 3.1 effective date)
_REPORTING_DATE = date(2027, 6, 30)


# ---------------------------------------------------------------------------
# Session-scoped fixture: build B31-E5-specific slotting results.
#
# Unlike the shared slotting_results_df (which uses existing SL fixtures that
# already have internal ratings), the B31-E5 loans need inline ratings to get
# model_slotting_permitted=True through the classifier. The shared conftest
# fixture does not cover these new counterparties, so we build the pipeline
# independently here.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def b31_e5_slotting_results_df() -> pl.DataFrame:
    """
    Run the B31-E5 fixture loans through the Basel 3.1 slotting pipeline.

    Builds a RawDataBundle that:
    - Loads ALL fixtures (for correct hierarchy/mapping support)
    - Augments the ratings LazyFrame with inline internal ratings for the 7 B31-E5
      counterparties (they have no entries in ratings.parquet, so we add them here
      to satisfy model_permissions-based slotting routing in the classifier)
    - Adds a model_permissions row granting slotting for SPECIALISED_LENDING

    The inline ratings give each B31-E5 counterparty model_id=_B31E5_MODEL_ID,
    matching the model_permissions entry.  Slotting ignores PD — the PD value
    in the rating is irrelevant and set to 0.005 for completeness only.

    Returns the collected slotting_results LazyFrame (filtered to B31-E5 loans).
    """
    from workbooks.shared.fixture_loader import load_fixtures

    from rwa_calc.contracts.bundles import RawDataBundle
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    b31_cp_refs = [
        "CP-SLOT-B31-PROJFIN-STRONG-SHORT",
        "CP-SLOT-B31-PROJFIN-STRONG-LONG",
        "CP-SLOT-B31-PROJFIN-GOOD-SHORT",
        "CP-SLOT-B31-PROJFIN-GOOD-LONG",
        "CP-SLOT-B31-PROJFIN-SAT-SHORT",
        "CP-SLOT-B31-PROJFIN-WEAK-SHORT",
        "CP-SLOT-B31-PROJFIN-DEFAULT-SHORT",
    ]

    fixtures = load_fixtures()

    # --- Inline ratings for B31-E5 counterparties ---
    # These counterparties are not in ratings.parquet, so we append inline rows
    # that carry the B31E5 model_id. Slotting does not use PD; we set 0.005 for
    # completeness.
    inline_ratings = pl.LazyFrame(
        {
            "rating_reference": [f"RTG_B31E5_{cp}" for cp in b31_cp_refs],
            "counterparty_reference": b31_cp_refs,
            "rating_type": ["internal"] * len(b31_cp_refs),
            "rating_agency": [None] * len(b31_cp_refs),
            "rating_value": [None] * len(b31_cp_refs),
            "cqs": pl.Series([None] * len(b31_cp_refs), dtype=pl.Int8),
            "pd": [0.005] * len(b31_cp_refs),
            "rating_date": [date(2027, 1, 1)] * len(b31_cp_refs),
            "is_solicited": [False] * len(b31_cp_refs),
            "model_id": [_B31E5_MODEL_ID] * len(b31_cp_refs),
        }
    )

    augmented_ratings = pl.concat(
        [fixtures.ratings, inline_ratings], how="diagonal_relaxed"
    )

    # --- Model permissions: grant slotting for SPECIALISED_LENDING ---
    model_permissions = pl.LazyFrame(
        {
            "model_id": [_B31E5_MODEL_ID],
            "exposure_class": [ExposureClass.SPECIALISED_LENDING.value],
            "approach": [ApproachType.SLOTTING.value],
        }
    )

    bundle = RawDataBundle(
        facilities=fixtures.facilities,
        loans=fixtures.loans,
        contingents=fixtures.contingents,
        counterparties=fixtures.counterparties,
        collateral=fixtures.collateral,
        guarantees=fixtures.guarantees,
        provisions=fixtures.provisions,
        ratings=augmented_ratings,
        facility_mappings=fixtures.facility_mappings,
        org_mappings=fixtures.org_mappings,
        lending_mappings=fixtures.lending_mappings,
        specialised_lending=fixtures.specialised_lending,
        model_permissions=model_permissions,
    )

    config = CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )

    pipeline = PipelineOrchestrator()
    results = pipeline.run_with_data(bundle, config)

    if results.slotting_results is None:
        return pl.DataFrame()
    return results.slotting_results.collect()


class TestB31E5SlottingShortMaturityColumnA:
    """
    B31-E5 primary scenario: non-HVCRE Strong, short maturity → column A = 50% RW.

    Central assertion: the engine must select RW = 0.50 (Table A col A) not
    RW = 0.70 (Table A col B) when is_short_maturity=True for a Strong exposure
    under Basel 3.1.

    Art. 153(5)(d) PRA PS1/26: firms may apply the column-A/C weights when
    residual maturity < 2.5 years.  The scenario assumes the firm has elected to
    apply column A, represented by is_short_maturity=True.
    """

    def test_b31_e5_strong_short_risk_weight_is_50_pct(
        self,
        b31_e5_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-E5 primary: PF Strong, <2.5yr residual → RW = 50% (col A).

        Arrange: £1m project finance, Strong, short maturity (2029-06-30), non-HVCRE.
        Act: run through Basel 3.1 pipeline with slotting permissions.
        Assert: risk_weight == 0.50.

        Failure mode before fix: risk_weight == 0.70 (base table used instead of short).
        Art. 153(5)(d) PRA PS1/26: column A = 50% for Strong when maturity < 2.5yr.
        """
        # Arrange
        exposure_ref = _STRONG_SHORT

        # Act
        result = get_result_for_exposure(b31_e5_slotting_results_df, exposure_ref)

        # Assert
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_risk_weight_match(
            result["risk_weight"],
            0.50,
            scenario_id="B31-E5",
        )

    def test_b31_e5_strong_short_rwa_is_500k(
        self,
        b31_e5_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-E5 primary: RWA = EAD × 50% = £500,000.

        Arrange: EAD = £1,000,000, RW = 0.50.
        Act: run through Basel 3.1 pipeline.
        Assert: rwa == 500,000.

        Failure mode before fix: rwa == 700,000 (base table RW = 70% applied).
        """
        # Arrange
        exposure_ref = _STRONG_SHORT

        # Act
        result = get_result_for_exposure(b31_e5_slotting_results_df, exposure_ref)

        # Assert
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa"],
            500_000.0,
            scenario_id="B31-E5",
        )

    def test_b31_e5_strong_short_el_rate_is_zero(
        self,
        b31_e5_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-E5: Strong, short maturity EL rate = 0.000 (Table B col A = 0%).

        Art. 158(6) Table B non-HVCRE <2.5yr: Strong = 0%.
        This is already implemented in B31_SLOTTING_EL_RATES_SHORT.
        """
        # Arrange
        exposure_ref = _STRONG_SHORT

        # Act
        result = get_result_for_exposure(b31_e5_slotting_results_df, exposure_ref)

        # Assert
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert result["slotting_el_rate"] == pytest.approx(0.0, abs=1e-6), (
            f"B31-E5: Strong short EL rate should be 0.000, got {result['slotting_el_rate']}"
        )

    def test_b31_e5_strong_short_expected_loss_is_zero(
        self,
        b31_e5_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-E5: Strong, short maturity EL = EAD × 0% = £0.

        Art. 158(6) Table B: Strong col A EL rate = 0% → EL = 0.
        """
        # Arrange
        exposure_ref = _STRONG_SHORT

        # Act
        result = get_result_for_exposure(b31_e5_slotting_results_df, exposure_ref)

        # Assert
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert result["expected_loss"] == pytest.approx(0.0, abs=0.01), (
            f"B31-E5: Strong short EL should be 0, got {result['expected_loss']}"
        )


class TestB31E5SlottingFullTableAMatrix:
    """
    B31-E5 companion parameterisations: pin the full non-HVCRE Table A matrix.

    Verifies the complete Strong/Good column-A/B/C/D split, plus the
    categories that have no maturity differentiation (Satisfactory, Weak, Default).
    """

    def test_b31_e5_strong_long_risk_weight_is_70_pct(
        self,
        b31_e5_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-E5b: PF Strong, >=2.5yr residual → RW = 70% (Table A col B).

        Arrange: £1m project finance, Strong, long maturity (2031-06-30), non-HVCRE.
        Act: run through Basel 3.1 pipeline.
        Assert: risk_weight == 0.70.
        """
        # Arrange
        exposure_ref = _STRONG_LONG

        # Act
        result = get_result_for_exposure(b31_e5_slotting_results_df, exposure_ref)

        # Assert
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_risk_weight_match(
            result["risk_weight"],
            0.70,
            scenario_id="B31-E5b",
        )

    def test_b31_e5_good_short_risk_weight_is_70_pct(
        self,
        b31_e5_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-E5c: PF Good, <2.5yr residual → RW = 70% (Table A col C).

        Arrange: £1m project finance, Good, short maturity (2029-06-30), non-HVCRE.
        Act: run through Basel 3.1 pipeline.
        Assert: risk_weight == 0.70.
        """
        # Arrange
        exposure_ref = _GOOD_SHORT

        # Act
        result = get_result_for_exposure(b31_e5_slotting_results_df, exposure_ref)

        # Assert
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_risk_weight_match(
            result["risk_weight"],
            0.70,
            scenario_id="B31-E5c",
        )

    def test_b31_e5_good_long_risk_weight_is_90_pct(
        self,
        b31_e5_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-E5d: PF Good, >=2.5yr residual → RW = 90% (Table A col D).

        Arrange: £1m project finance, Good, long maturity (2031-06-30), non-HVCRE.
        Act: run through Basel 3.1 pipeline.
        Assert: risk_weight == 0.90.
        """
        # Arrange
        exposure_ref = _GOOD_LONG

        # Act
        result = get_result_for_exposure(b31_e5_slotting_results_df, exposure_ref)

        # Assert
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_risk_weight_match(
            result["risk_weight"],
            0.90,
            scenario_id="B31-E5d",
        )

    def test_b31_e5_satisfactory_short_risk_weight_is_115_pct(
        self,
        b31_e5_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-E5e: PF Satisfactory, <2.5yr residual → RW = 115% (no col split).

        Satisfactory has no maturity differentiation — same weight regardless of
        is_short_maturity.
        """
        # Arrange
        exposure_ref = _SAT_SHORT

        # Act
        result = get_result_for_exposure(b31_e5_slotting_results_df, exposure_ref)

        # Assert
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_risk_weight_match(
            result["risk_weight"],
            1.15,
            scenario_id="B31-E5e",
        )

    def test_b31_e5_weak_short_risk_weight_is_250_pct(
        self,
        b31_e5_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-E5f: PF Weak, <2.5yr residual → RW = 250% (no col split).

        Weak has no maturity differentiation.
        """
        # Arrange
        exposure_ref = _WEAK_SHORT

        # Act
        result = get_result_for_exposure(b31_e5_slotting_results_df, exposure_ref)

        # Assert
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_risk_weight_match(
            result["risk_weight"],
            2.50,
            scenario_id="B31-E5f",
        )

    def test_b31_e5_default_short_risk_weight_is_zero(
        self,
        b31_e5_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-E5g: PF Default, <2.5yr residual → RW = 0% (no col split).

        Default has no maturity differentiation.
        """
        # Arrange
        exposure_ref = _DEFAULT_SHORT

        # Act
        result = get_result_for_exposure(b31_e5_slotting_results_df, exposure_ref)

        # Assert
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_risk_weight_match(
            result["risk_weight"],
            0.00,
            scenario_id="B31-E5g",
        )


class TestB31E5SlottingMaturityDifferentiation:
    """
    Structural invariant tests: short-maturity rows must differ from long-maturity rows.

    These tests verify the column-A vs column-B split is active — not that any
    specific absolute value is correct, but that the maturity dimension is honoured.
    """

    def test_b31_e5_strong_short_lower_rw_than_strong_long(
        self,
        b31_e5_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        Verify Strong short (col A, 50%) < Strong long (col B, 70%).

        If the engine ignores is_short for B31, both rows return the base table (70%)
        and this invariant fails.
        """
        # Arrange
        short_ref = _STRONG_SHORT
        long_ref = _STRONG_LONG

        # Act
        short_result = get_result_for_exposure(b31_e5_slotting_results_df, short_ref)
        long_result = get_result_for_exposure(b31_e5_slotting_results_df, long_ref)

        # Assert
        if short_result is None or long_result is None:
            pytest.skip("Missing slotting results for maturity comparison")

        assert short_result["risk_weight"] < long_result["risk_weight"], (
            f"B31-E5: Strong short ({short_result['risk_weight']}) should be "
            f"< Strong long ({long_result['risk_weight']}), "
            f"but the engine is ignoring is_short_maturity for Basel 3.1 "
            f"(Art. 153(5)(d) Table A col-A vs col-B split)"
        )

    def test_b31_e5_good_short_lower_rw_than_good_long(
        self,
        b31_e5_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        Verify Good short (col C, 70%) < Good long (col D, 90%).

        If the engine ignores is_short for B31, both rows return the base table (90%)
        and this invariant fails.
        """
        # Arrange
        short_ref = _GOOD_SHORT
        long_ref = _GOOD_LONG

        # Act
        short_result = get_result_for_exposure(b31_e5_slotting_results_df, short_ref)
        long_result = get_result_for_exposure(b31_e5_slotting_results_df, long_ref)

        # Assert
        if short_result is None or long_result is None:
            pytest.skip("Missing slotting results for maturity comparison")

        assert short_result["risk_weight"] < long_result["risk_weight"], (
            f"B31-E5: Good short ({short_result['risk_weight']}) should be "
            f"< Good long ({long_result['risk_weight']}), "
            f"but the engine is ignoring is_short_maturity for Basel 3.1 "
            f"(Art. 153(5)(d) Table A col-C vs col-D split)"
        )

    def test_b31_e5_strong_short_rwa_equals_500k(
        self,
        b31_e5_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        B31-E5: Strong short RWA = £1m × 50% = £500,000.

        Companion to the risk weight test. Failure mode: £700,000 (if 70% used).
        """
        # Arrange
        exposure_ref = _STRONG_SHORT

        # Act
        result = get_result_for_exposure(b31_e5_slotting_results_df, exposure_ref)

        # Assert
        if result is None:
            pytest.skip(f"Fixture data not available for {exposure_ref}")

        assert_rwa_within_tolerance(
            result["rwa"],
            500_000.0,
            scenario_id="B31-E5-RWA",
        )
