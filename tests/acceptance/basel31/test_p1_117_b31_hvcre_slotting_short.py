"""
Basel 3.1 Scenario P1.117: HVCRE Slotting Short-Maturity Subgrades.

Tests PRA PS1/26 Appendix 1, Art. 153(5)(d) — the column-A/C concession that
applies reduced risk weights when residual maturity is < 2.5 years for HVCRE
specialised lending under the Basel 3.1 supervisory slotting approach.

Key assertions:
    HVCRE Strong, short (<2.5yr) → RW = 70%  (Table A col A)
    HVCRE Good,   short (<2.5yr) → RW = 95%  (Table A col C)
    HVCRE Strong, long  (>=2.5yr) → RW = 95% (Table A col B)  — regression guard
    HVCRE Good,   long  (>=2.5yr) → RW = 120% (Table A col D) — regression guard

Bug under test (pre-fix):
    In engine/slotting/namespace.py lookup_rw() B31 branch, the is_hvcre check
    fires first and always returns weights["hvcre"] (the long-maturity table,
    Strong=0.95 / Good=1.20) — is_short is never consulted for HVCRE.
    Annotated in namespace.py at the comment:
        "HVCRE column A/C is tracked separately (see P1.117) and not applied here."

    Failure mode:
        HVCRE Strong short → risk_weight=0.95 / rwa=9_500_000  (wrong, should be 0.70/7m)
        HVCRE Good  short → risk_weight=1.20 / rwa=1_200_000  (wrong, should be 0.95/950k)

EL rate assertion:
    HVCRE EL rates are flat (no maturity split): Strong=0.4%, Good=0.4%
    slotting_el_rate=0.004 for all four rows.

Regulatory references:
    - PRA PS1/26 Appendix 1, Art. 153(5)(d), Table A (HVCRE block, col A/C)
    - PRA PS1/26 Appendix 1, Art. 158(6), Table B (HVCRE row — flat 0.4% for Strong/Good)
    - BCBS CRE33.5: supervisory slotting categories
    - docs/specifications/basel31/slotting-approach.md §5
    - src/rwa_calc/engine/slotting/namespace.py:415 (bug annotation)
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
# Exposure references — these are loan_references from the P1.117 fixture,
# which the pipeline renames to exposure_reference via hierarchy resolution.
# Reporting date: 2027-06-30
# Short maturity_date: 2029-06-30 → residual = 2.0yr → is_short_maturity=True
# Long  maturity_date: 2030-06-30 → residual = 3.0yr → is_short_maturity=False
# ---------------------------------------------------------------------------

_HVCRE_STRONG_SHORT = "EXP_B31_HVCRE_SHORT_001"      # primary — £10m
_HVCRE_GOOD_SHORT = "EXP_B31_HVCRE_GOOD_SHORT_001"   # regression — £1m
_HVCRE_STRONG_LONG = "EXP_B31_HVCRE_STRONG_LONG_001"  # regression guard — £1m
_HVCRE_GOOD_LONG = "EXP_B31_HVCRE_GOOD_LONG_001"     # regression guard — £1m

# EAD from fixtures
_EAD_PRIMARY = 10_000_000.0
_EAD_REGRESSION = 1_000_000.0

# Art. 153(5) Table A HVCRE risk weights — from b31_slotting.py
_RW_HVCRE_STRONG_SHORT = 0.70   # col A — PRIMARY assertion (bug returns 0.95)
_RW_HVCRE_GOOD_SHORT = 0.95     # col C  — WILL FAIL today (bug returns 1.20)
_RW_HVCRE_STRONG_LONG = 0.95    # col B  — regression guard (already correct)
_RW_HVCRE_GOOD_LONG = 1.20      # col D  — regression guard (already correct)

# HVCRE EL rate — flat 0.4% for Strong and Good (Art. 158(6) Table B)
_EL_RATE_HVCRE = 0.004

# Model ID for this scenario's slotting permissions
_P1117_MODEL_ID = "P1_117_HVCRE_SLOTTING_MODEL"

# Reporting date
_REPORTING_DATE = date(2027, 6, 30)

# Counterparty references (from fixture)
_CP_REFS = [
    "CP_HVCRE_DEV_01",
    "CP_HVCRE_DEV_02",
    "CP_HVCRE_DEV_03",
    "CP_HVCRE_DEV_04",
]


# ---------------------------------------------------------------------------
# Session-scoped fixture: run the P1.117 fixtures through the B31 slotting
# pipeline.
#
# Strategy mirrors B31-E5: we load the shared fixtures for scaffolding, then
# concatenate P1.117's counterparties, loans, and sl_metadata.  Inline
# ratings give each CP a model_id matching a bespoke model_permissions row
# that grants slotting for SPECIALISED_LENDING.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def p1117_hvcre_slotting_results_df() -> pl.DataFrame:
    """
    Run the P1.117 HVCRE fixture loans through the Basel 3.1 slotting pipeline.

    Builds a RawDataBundle that:
    - Loads ALL shared fixtures (for correct hierarchy/mapping support)
    - Appends P1.117 counterparties, loans, and specialised_lending metadata
    - Augments the ratings LazyFrame with inline internal ratings for the four
      P1.117 counterparties so the classifier sees model_slotting_permitted=True
    - Adds a model_permissions row granting slotting for SPECIALISED_LENDING

    Returns the collected slotting_results LazyFrame (all rows including P1.117).
    """
    from pathlib import Path

    from workbooks.shared.fixture_loader import load_fixtures

    from rwa_calc.contracts.bundles import RawDataBundle
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    # --- Load shared fixtures (provides scaffolding tables) ---
    fixtures = load_fixtures()

    # --- Load P1.117-specific fixture parquets ---
    p1117_dir = (
        Path(__file__).parent.parent.parent  # tests/
        / "fixtures"
        / "p1_117"
    )
    p1117_counterparties = pl.scan_parquet(p1117_dir / "counterparty.parquet")
    p1117_loans = pl.scan_parquet(p1117_dir / "loan.parquet")
    p1117_sl_metadata = pl.scan_parquet(p1117_dir / "sl_metadata.parquet")

    # --- Merge counterparties ---
    merged_counterparties = pl.concat(
        [fixtures.counterparties, p1117_counterparties],
        how="diagonal_relaxed",
    )

    # --- Merge loans ---
    merged_loans = pl.concat(
        [fixtures.loans, p1117_loans],
        how="diagonal_relaxed",
    )

    # --- Merge specialised_lending metadata ---
    if fixtures.specialised_lending is not None:
        merged_sl = pl.concat(
            [fixtures.specialised_lending, p1117_sl_metadata],
            how="diagonal_relaxed",
        )
    else:
        merged_sl = p1117_sl_metadata

    # --- Inline ratings for P1.117 counterparties ---
    # Slotting does not use PD; pd=0.005 is set for completeness only.
    inline_ratings = pl.LazyFrame(
        {
            "rating_reference": [f"RTG_P1117_{cp}" for cp in _CP_REFS],
            "counterparty_reference": _CP_REFS,
            "rating_type": ["internal"] * 4,
            "rating_agency": [None] * 4,
            "rating_value": [None] * 4,
            "cqs": pl.Series([None] * 4, dtype=pl.Int8),
            "pd": [0.005] * 4,
            "rating_date": [date(2027, 1, 1)] * 4,
            "is_solicited": [False] * 4,
            "model_id": [_P1117_MODEL_ID] * 4,
        }
    )
    augmented_ratings = pl.concat(
        [fixtures.ratings, inline_ratings],
        how="diagonal_relaxed",
    )

    # --- Model permissions: grant slotting for SPECIALISED_LENDING ---
    model_permissions = pl.LazyFrame(
        {
            "model_id": [_P1117_MODEL_ID],
            "exposure_class": [ExposureClass.SPECIALISED_LENDING.value],
            "approach": [ApproachType.SLOTTING.value],
        }
    )

    bundle = RawDataBundle(
        facilities=fixtures.facilities,
        loans=merged_loans,
        contingents=fixtures.contingents,
        counterparties=merged_counterparties,
        collateral=fixtures.collateral,
        guarantees=fixtures.guarantees,
        provisions=fixtures.provisions,
        ratings=augmented_ratings,
        facility_mappings=fixtures.facility_mappings,
        org_mappings=fixtures.org_mappings,
        lending_mappings=fixtures.lending_mappings,
        specialised_lending=merged_sl,
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


# ---------------------------------------------------------------------------
# PRIMARY SCENARIO: HVCRE Strong, short maturity — Table A col A = 70% RW
# ---------------------------------------------------------------------------


class TestP1117HvcreStrongShort:
    """
    P1.117 primary scenario: HVCRE Strong, residual maturity 2.0yr < 2.5yr.

    Central assertion: the engine must select RW = 0.70 (Table A col A for
    HVCRE) not RW = 0.95 (HVCRE long-maturity table) when is_short_maturity=True.

    Art. 153(5)(d) PRA PS1/26 Table A: HVCRE Strong short → 70%.
    Pre-fix failure mode: risk_weight=0.95, rwa=9_500_000.
    """

    def test_p1_117_hvcre_strong_short_risk_weight_is_70_pct(
        self,
        p1117_hvcre_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        P1.117 primary: HVCRE IPRE Strong, <2.5yr residual → RW = 70% (col A).

        Arrange: £10m HVCRE IPRE, Strong, maturity 2029-06-30 (~2.0yr), is_hvcre=True.
        Act: run through Basel 3.1 pipeline with slotting permissions.
        Assert: risk_weight == 0.70.

        Failure mode before fix: risk_weight == 0.95 (long-maturity HVCRE table used).
        Art. 153(5)(d) PRA PS1/26: HVCRE Strong col A = 70% when maturity < 2.5yr.
        """
        # Arrange
        exposure_ref = _HVCRE_STRONG_SHORT

        # Act
        result = get_result_for_exposure(p1117_hvcre_slotting_results_df, exposure_ref)

        # Assert
        assert result is not None, (
            f"P1.117 fixture row missing from slotting results: {exposure_ref}"
        )
        assert_risk_weight_match(
            result["risk_weight"],
            _RW_HVCRE_STRONG_SHORT,
            scenario_id="P1.117",
        )

    def test_p1_117_hvcre_strong_short_rwa_is_7m(
        self,
        p1117_hvcre_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        P1.117 primary: RWA = £10m × 70% = £7,000,000.

        Arrange: EAD = £10,000,000, RW = 0.70 (post-fix).
        Act: run through Basel 3.1 pipeline.
        Assert: rwa == 7_000_000.

        Failure mode before fix: rwa == 9_500_000 (0.95 × £10m).
        """
        # Arrange
        exposure_ref = _HVCRE_STRONG_SHORT

        # Act
        result = get_result_for_exposure(p1117_hvcre_slotting_results_df, exposure_ref)

        # Assert
        assert result is not None, (
            f"P1.117 fixture row missing from slotting results: {exposure_ref}"
        )
        assert_rwa_within_tolerance(
            result["rwa"],
            _EAD_PRIMARY * _RW_HVCRE_STRONG_SHORT,
            scenario_id="P1.117",
        )

    def test_p1_117_hvcre_strong_short_el_rate_is_0_4_pct(
        self,
        p1117_hvcre_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        P1.117: HVCRE Strong short EL rate = 0.004 (Art. 158(6) Table B, flat).

        HVCRE EL rates are flat regardless of maturity (unlike non-HVCRE).
        Strong=0.4%, Good=0.4% for HVCRE in both short and long columns.
        """
        # Arrange
        exposure_ref = _HVCRE_STRONG_SHORT

        # Act
        result = get_result_for_exposure(p1117_hvcre_slotting_results_df, exposure_ref)

        # Assert
        assert result is not None, (
            f"P1.117 fixture row missing from slotting results: {exposure_ref}"
        )
        assert result["slotting_el_rate"] == pytest.approx(_EL_RATE_HVCRE, abs=1e-6), (
            f"P1.117: HVCRE Strong short EL rate should be {_EL_RATE_HVCRE}, "
            f"got {result['slotting_el_rate']}"
        )


# ---------------------------------------------------------------------------
# SECOND FAILING SCENARIO: HVCRE Good, short maturity — Table A col C = 95% RW
# ---------------------------------------------------------------------------


class TestP1117HvcreGoodShort:
    """
    P1.117 regression: HVCRE Good, residual maturity 2.0yr < 2.5yr.

    Pre-fix failure mode: risk_weight=1.20, rwa=1_200_000.
    Post-fix expected:    risk_weight=0.95, rwa=950_000.

    Art. 153(5)(d) PRA PS1/26 Table A: HVCRE Good short → 95% (col C).
    """

    def test_p1_117_hvcre_good_short_risk_weight_is_95_pct(
        self,
        p1117_hvcre_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        P1.117b: HVCRE IPRE Good, <2.5yr residual → RW = 95% (col C).

        Arrange: £1m HVCRE IPRE, Good, maturity 2029-06-30 (~2.0yr), is_hvcre=True.
        Act: run through Basel 3.1 pipeline.
        Assert: risk_weight == 0.95.

        Failure mode before fix: risk_weight == 1.20 (long-maturity Good HVCRE used).
        """
        # Arrange
        exposure_ref = _HVCRE_GOOD_SHORT

        # Act
        result = get_result_for_exposure(p1117_hvcre_slotting_results_df, exposure_ref)

        # Assert
        assert result is not None, (
            f"P1.117 fixture row missing from slotting results: {exposure_ref}"
        )
        assert_risk_weight_match(
            result["risk_weight"],
            _RW_HVCRE_GOOD_SHORT,
            scenario_id="P1.117b",
        )

    def test_p1_117_hvcre_good_short_rwa_is_950k(
        self,
        p1117_hvcre_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        P1.117b: RWA = £1m × 95% = £950,000.

        Arrange: EAD = £1,000,000, RW = 0.95 (post-fix).
        Act: run through Basel 3.1 pipeline.
        Assert: rwa == 950_000.

        Failure mode before fix: rwa == 1_200_000 (1.20 × £1m).
        """
        # Arrange
        exposure_ref = _HVCRE_GOOD_SHORT

        # Act
        result = get_result_for_exposure(p1117_hvcre_slotting_results_df, exposure_ref)

        # Assert
        assert result is not None, (
            f"P1.117 fixture row missing from slotting results: {exposure_ref}"
        )
        assert_rwa_within_tolerance(
            result["rwa"],
            _EAD_REGRESSION * _RW_HVCRE_GOOD_SHORT,
            scenario_id="P1.117b",
        )

    def test_p1_117_hvcre_good_short_el_rate_is_0_4_pct(
        self,
        p1117_hvcre_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        P1.117b: HVCRE Good short EL rate = 0.004 (flat, no maturity split).

        Art. 158(6) Table B HVCRE: both Strong and Good use 0.4% regardless of maturity.
        """
        # Arrange
        exposure_ref = _HVCRE_GOOD_SHORT

        # Act
        result = get_result_for_exposure(p1117_hvcre_slotting_results_df, exposure_ref)

        # Assert
        assert result is not None, (
            f"P1.117 fixture row missing from slotting results: {exposure_ref}"
        )
        assert result["slotting_el_rate"] == pytest.approx(_EL_RATE_HVCRE, abs=1e-6), (
            f"P1.117b: HVCRE Good short EL rate should be {_EL_RATE_HVCRE}, "
            f"got {result['slotting_el_rate']}"
        )


# ---------------------------------------------------------------------------
# REGRESSION GUARDS: HVCRE long-maturity rows must remain unchanged
# ---------------------------------------------------------------------------


class TestP1117HvcreLongMaturityRegressionGuards:
    """
    Regression guards: long-maturity HVCRE rows must not be affected by the fix.

    Pre-fix: these already produce the correct output (0.95 Strong / 1.20 Good).
    Post-fix: must remain the same.

    These tests ensure the is_short_maturity dispatch is correct on both sides
    of the 2.5-year boundary.
    """

    def test_p1_117_hvcre_strong_long_risk_weight_is_95_pct(
        self,
        p1117_hvcre_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        P1.117c regression guard: HVCRE Strong, >=2.5yr residual → RW = 95% (col B).

        Arrange: £1m HVCRE IPRE, Strong, maturity 2030-06-30 (~3.0yr), is_hvcre=True.
        Act: run through Basel 3.1 pipeline.
        Assert: risk_weight == 0.95.
        """
        # Arrange
        exposure_ref = _HVCRE_STRONG_LONG

        # Act
        result = get_result_for_exposure(p1117_hvcre_slotting_results_df, exposure_ref)

        # Assert
        assert result is not None, (
            f"P1.117 fixture row missing from slotting results: {exposure_ref}"
        )
        assert_risk_weight_match(
            result["risk_weight"],
            _RW_HVCRE_STRONG_LONG,
            scenario_id="P1.117c",
        )

    def test_p1_117_hvcre_strong_long_rwa_is_950k(
        self,
        p1117_hvcre_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        P1.117c regression guard: RWA = £1m × 95% = £950,000.
        """
        # Arrange
        exposure_ref = _HVCRE_STRONG_LONG

        # Act
        result = get_result_for_exposure(p1117_hvcre_slotting_results_df, exposure_ref)

        # Assert
        assert result is not None, (
            f"P1.117 fixture row missing from slotting results: {exposure_ref}"
        )
        assert_rwa_within_tolerance(
            result["rwa"],
            _EAD_REGRESSION * _RW_HVCRE_STRONG_LONG,
            scenario_id="P1.117c",
        )

    def test_p1_117_hvcre_good_long_risk_weight_is_120_pct(
        self,
        p1117_hvcre_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        P1.117d regression guard: HVCRE Good, >=2.5yr residual → RW = 120% (col D).

        Arrange: £1m HVCRE IPRE, Good, maturity 2030-06-30 (~3.0yr), is_hvcre=True.
        Act: run through Basel 3.1 pipeline.
        Assert: risk_weight == 1.20.
        """
        # Arrange
        exposure_ref = _HVCRE_GOOD_LONG

        # Act
        result = get_result_for_exposure(p1117_hvcre_slotting_results_df, exposure_ref)

        # Assert
        assert result is not None, (
            f"P1.117 fixture row missing from slotting results: {exposure_ref}"
        )
        assert_risk_weight_match(
            result["risk_weight"],
            _RW_HVCRE_GOOD_LONG,
            scenario_id="P1.117d",
        )

    def test_p1_117_hvcre_good_long_rwa_is_1_2m(
        self,
        p1117_hvcre_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        P1.117d regression guard: RWA = £1m × 120% = £1,200,000.
        """
        # Arrange
        exposure_ref = _HVCRE_GOOD_LONG

        # Act
        result = get_result_for_exposure(p1117_hvcre_slotting_results_df, exposure_ref)

        # Assert
        assert result is not None, (
            f"P1.117 fixture row missing from slotting results: {exposure_ref}"
        )
        assert_rwa_within_tolerance(
            result["rwa"],
            _EAD_REGRESSION * _RW_HVCRE_GOOD_LONG,
            scenario_id="P1.117d",
        )

    def test_p1_117_hvcre_el_rates_flat_for_long_maturity_rows(
        self,
        p1117_hvcre_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        P1.117 regression guard: HVCRE long-maturity EL rate = 0.004 (flat).

        Art. 158(6) Table B: HVCRE EL rates do not split by maturity.
        Both Strong and Good long-maturity HVCRE rows must return 0.4%.
        """
        # Arrange
        for exposure_ref in (_HVCRE_STRONG_LONG, _HVCRE_GOOD_LONG):
            # Act
            result = get_result_for_exposure(p1117_hvcre_slotting_results_df, exposure_ref)

            # Assert
            assert result is not None, (
                f"P1.117 regression: fixture row missing from slotting results: {exposure_ref}"
            )
            assert result["slotting_el_rate"] == pytest.approx(_EL_RATE_HVCRE, abs=1e-6), (
                f"P1.117 regression: {exposure_ref} EL rate should be {_EL_RATE_HVCRE}, "
                f"got {result['slotting_el_rate']}"
            )


# ---------------------------------------------------------------------------
# STRUCTURAL INVARIANT: short < long for HVCRE
# ---------------------------------------------------------------------------


class TestP1117HvcreMaturityDifferentiation:
    """
    Structural invariant: after the fix, short-maturity HVCRE weights must be
    strictly lower than their long-maturity counterparts.

    If is_short_maturity is still ignored for HVCRE, both rows return the
    long table and this invariant fails.
    """

    def test_p1_117_hvcre_strong_short_lower_rw_than_strong_long(
        self,
        p1117_hvcre_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        HVCRE Strong short (col A, 70%) < HVCRE Strong long (col B, 95%).

        Pre-fix: both rows return 0.95 and the invariant fails.
        Post-fix: 0.70 < 0.95 holds.
        """
        # Arrange
        short_ref = _HVCRE_STRONG_SHORT
        long_ref = _HVCRE_STRONG_LONG

        # Act
        short_result = get_result_for_exposure(p1117_hvcre_slotting_results_df, short_ref)
        long_result = get_result_for_exposure(p1117_hvcre_slotting_results_df, long_ref)

        # Assert
        assert short_result is not None, (
            f"P1.117 fixture row missing from slotting results: {short_ref}"
        )
        assert long_result is not None, (
            f"P1.117 fixture row missing from slotting results: {long_ref}"
        )
        assert short_result["risk_weight"] < long_result["risk_weight"], (
            f"P1.117: HVCRE Strong short ({short_result['risk_weight']:.4f}) should be "
            f"< HVCRE Strong long ({long_result['risk_weight']:.4f}). "
            f"Engine is not applying is_short_maturity to HVCRE exposures "
            f"(Art. 153(5)(d) Table A col-A vs col-B split for HVCRE)."
        )

    def test_p1_117_hvcre_good_short_lower_rw_than_good_long(
        self,
        p1117_hvcre_slotting_results_df: pl.DataFrame,
    ) -> None:
        """
        HVCRE Good short (col C, 95%) < HVCRE Good long (col D, 120%).

        Pre-fix: both rows return 1.20 and the invariant fails.
        Post-fix: 0.95 < 1.20 holds.
        """
        # Arrange
        short_ref = _HVCRE_GOOD_SHORT
        long_ref = _HVCRE_GOOD_LONG

        # Act
        short_result = get_result_for_exposure(p1117_hvcre_slotting_results_df, short_ref)
        long_result = get_result_for_exposure(p1117_hvcre_slotting_results_df, long_ref)

        # Assert
        assert short_result is not None, (
            f"P1.117 fixture row missing from slotting results: {short_ref}"
        )
        assert long_result is not None, (
            f"P1.117 fixture row missing from slotting results: {long_ref}"
        )
        assert short_result["risk_weight"] < long_result["risk_weight"], (
            f"P1.117: HVCRE Good short ({short_result['risk_weight']:.4f}) should be "
            f"< HVCRE Good long ({long_result['risk_weight']:.4f}). "
            f"Engine is not applying is_short_maturity to HVCRE exposures "
            f"(Art. 153(5)(d) Table A col-C vs col-D split for HVCRE)."
        )
