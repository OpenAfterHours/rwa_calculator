"""
P1.104 — CRR Art. 239(1) FCSM Maturity-Mismatch Eligibility Check.

Acceptance scenario: two GBP 1M corporate exposures (CQS 4, 100% unsecured RW)
are each fully collateralised by a corporate bond (CQS 2, 50% RW).

Case A (LN_P1104_COMPLIANT): collateral residual maturity 6.0y >= exposure 5.0y
    → CRR Art. 239(1) satisfied → FCSM collateral recognised
    → blended RW = 0.50  → RWA = 500,000

Case B (LN_P1104_MISMATCH): collateral residual maturity 3.0y < exposure 5.0y
    → CRR Art. 239(1) violated → collateral REJECTED (binary, no partial adjustment)
    → falls back to unsecured corporate CQS 4 RW = 1.00  → RWA = 1,000,000

Bug site (pre-fix):
    compute_fcsm_columns() does not check residual_maturity_years against the
    exposure's residual maturity. It therefore treats COLL_P1104_SHORT as fully
    eligible and returns fcsm_collateral_value = 1,000,000 / fcsm_collateral_rw = 0.50
    for LN_P1104_MISMATCH, producing an incorrect blended RW of 0.50 (RWA = 500,000).

Hand calculations:
    Both exposures: EAD = 1,000,000, corporate CQS 4 unsecured RW = 1.00
    Collateral: corporate bond CQS 2, FCSM item RW = max(0.20 floor, 0.50) = 0.50

    Case A (compliant — 6.0y >= 5.0y):
        maturity_eligibility = True
        fcsm_collateral_value = min(1,000,000, 1,000,000) = 1,000,000
        secured_pct = 1.00, unsecured_pct = 0.00
        blended_rw = 1.00 * 0.50 + 0.00 * 1.00 = 0.50
        RWA = 1,000,000 * 0.50 = 500,000

    Case B (mismatch — 3.0y < 5.0y):
        maturity_eligibility = False  (Art. 239(1))
        fcsm_collateral_value = 0   (collateral excluded)
        secured_pct = 0.00, unsecured_pct = 1.00
        blended_rw = 0.00 + 1.00 * 1.00 = 1.00
        RWA = 1,000,000 * 1.00 = 1,000,000

    Note: Art. 239(2) maturity-mismatch partial adjustment does NOT apply to FCSM
    (it is specific to FCCM/IRB). FCSM eligibility is strictly binary (Art. 239(1)).

References:
    CRR Art. 239(1): collateral ineligible when residual maturity < exposure maturity
    CRR Art. 222(3): FCSM 20% floor (FCSM_RW_FLOOR = 0.20)
    CRR Art. 122 Table 5: corporate CQS 2 = 50%, CQS 4 = 100%
    docs/specifications/crr/credit-risk-mitigation.md lines 827-838
    tests/fixtures/p1_104_art_239_1_fcsm_maturity/p1_104.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p1_104_art_239_1_fcsm_maturity.p1_104 import (
    COLL_SHORT_RESIDUAL_MATURITY_YEARS,
    CORPORATE_CQS4_RW,
    DRAWN_AMOUNT,
    EXPECTED_FCSM_COLLATERAL_RW_A,
    EXPECTED_FCSM_COLLATERAL_VALUE_A,
    EXPECTED_FCSM_COLLATERAL_VALUE_B,
    EXPECTED_RISK_WEIGHT_A,
    EXPECTED_RISK_WEIGHT_B,
    EXPECTED_RWA_A,
    EXPECTED_RWA_B,
    EXPOSURE_RESIDUAL_MATURITY_YEARS,
    LOAN_REF_COMPLIANT,
    LOAN_REF_MISMATCH,
)

import rwa_calc.engine.sa.namespace  # noqa: F401 — register sa namespace
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import CRMCollateralMethod
from rwa_calc.engine.crm.simple_method import compute_fcsm_columns

# =============================================================================
# Fixture paths and shared constants
# =============================================================================

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_104_art_239_1_fcsm_maturity"

_EAD = DRAWN_AMOUNT  # 1,000,000.0
_REPORTING_DATE = date(2026, 6, 1)


# =============================================================================
# Shared data builders
# =============================================================================


def _make_corporate_exposures() -> pl.LazyFrame:
    """Two GBP corporate exposures, EAD = £1M each, unsecured RW = 100% (CQS 4).

    Both share counterparty CP_P1104. residual_maturity_years ≈ 5.0y
    (value_date 2026-01-01 to maturity_date 2031-01-01).
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [LOAN_REF_COMPLIANT, LOAN_REF_MISMATCH],
            "ead_gross": [_EAD, _EAD],
            "ead_pre_crm": [_EAD, _EAD],
            "ead": [_EAD, _EAD],
            "ead_final": [_EAD, _EAD],
            "currency": ["GBP", "GBP"],
            "approach": ["standardised", "standardised"],
            "exposure_class": ["CORPORATE", "CORPORATE"],
            "cqs": [4, 4],
            "risk_weight": [CORPORATE_CQS4_RW, CORPORATE_CQS4_RW],
            "counterparty_reference": ["CP_P1104", "CP_P1104"],
            "parent_facility_reference": [None, None],
            "residual_maturity_years": [
                EXPOSURE_RESIDUAL_MATURITY_YEARS,
                EXPOSURE_RESIDUAL_MATURITY_YEARS,
            ],
        }
    ).with_columns(pl.col("parent_facility_reference").cast(pl.String))


# =============================================================================
# Config fixture
# =============================================================================


@pytest.fixture
def crr_simple_config() -> CalculationConfig:
    """CRR config with Financial Collateral Simple Method (Art. 222) elected."""
    return CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        crm_collateral_method=CRMCollateralMethod.SIMPLE,
    )


# =============================================================================
# P1.104-ART-239-1-COMPLIANT — Case A: collateral 6.0y >= exposure 5.0y
# =============================================================================


class TestP1104FCSMCompliantMaturity:
    """
    P1.104-A: Collateral with residual_maturity_years=6.0 is eligible under Art. 239(1).

    COLL_P1104_OK has maturity 6.0y which meets the "not less than" threshold
    for the 5.0y exposure → FCSM benefit is fully recognised.
    """

    def test_p1_104_art_239_1_compliant_fcsm_collateral_value(
        self, crr_simple_config: CalculationConfig
    ) -> None:
        """
        Art. 239(1) satisfied: FCSM collateral value = EAD (fully secured).

        Arrange: £1M corporate exposure (CQS 4), £1M corporate bond CQS 2,
                 collateral residual maturity 6.0y >= exposure 5.0y.
        Act:     compute_fcsm_columns (CRR SIMPLE method).
        Assert:  fcsm_collateral_value = 1,000,000 (collateral recognised).

        Pre-fix:  collateral recognised (already passes — confirms baseline).
        Post-fix: unchanged.
        """
        # Arrange
        exposures = _make_corporate_exposures()
        collateral = pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet")

        # Act
        result = compute_fcsm_columns(exposures, collateral, crr_simple_config).collect()
        compliant_row = result.filter(pl.col("exposure_reference") == LOAN_REF_COMPLIANT)

        # Assert
        assert compliant_row["fcsm_collateral_value"][0] == pytest.approx(
            EXPECTED_FCSM_COLLATERAL_VALUE_A, abs=1e-6
        ), (
            f"P1.104-A: fcsm_collateral_value should be {EXPECTED_FCSM_COLLATERAL_VALUE_A:,.0f} "
            f"(CQS 2 corporate bond, 6.0y >= 5.0y exposure — Art. 239(1) met), "
            f"got {compliant_row['fcsm_collateral_value'][0]:,.2f}"
        )

    def test_p1_104_art_239_1_compliant_fcsm_collateral_rw(
        self, crr_simple_config: CalculationConfig
    ) -> None:
        """
        Art. 239(1) satisfied: FCSM collateral RW = 0.50 (CQS 2 corporate bond).

        Arrange: £1M corporate bond CQS 2, collateral maturity 6.0y >= exposure 5.0y.
        Act:     compute_fcsm_columns (CRR SIMPLE method).
        Assert:  fcsm_collateral_rw = 0.50 = max(FCSM_RW_FLOOR=0.20, CQS2_RW=0.50).
        """
        # Arrange
        exposures = _make_corporate_exposures()
        collateral = pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet")

        # Act
        result = compute_fcsm_columns(exposures, collateral, crr_simple_config).collect()
        compliant_row = result.filter(pl.col("exposure_reference") == LOAN_REF_COMPLIANT)

        # Assert
        assert compliant_row["fcsm_collateral_rw"][0] == pytest.approx(
            EXPECTED_FCSM_COLLATERAL_RW_A, abs=1e-10
        ), (
            f"P1.104-A: fcsm_collateral_rw should be {EXPECTED_FCSM_COLLATERAL_RW_A:.2f} "
            f"(CRR Art. 122 Table 5: corporate CQS 2 = 50%), "
            f"got {compliant_row['fcsm_collateral_rw'][0]:.4f}"
        )

    def test_p1_104_art_239_1_compliant_risk_weight(
        self, crr_simple_config: CalculationConfig
    ) -> None:
        """
        Art. 239(1) satisfied: blended risk weight = 0.50 (fully secured, 50% collateral RW).

        Arrange: exposure as above, pre-set risk_weight=1.00 (unsecured CQS 4).
        Act:     compute_fcsm_columns then apply_fcsm_rw_substitution.
        Assert:  risk_weight = 0.50.

        blended_rw = secured_pct * fcsm_rw + unsecured_pct * base_rw
                   = 1.00 * 0.50 + 0.00 * 1.00 = 0.50
        """
        # Arrange
        exposures = _make_corporate_exposures()
        collateral = pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet")

        # Act
        with_fcsm = compute_fcsm_columns(exposures, collateral, crr_simple_config)
        result = with_fcsm.sa.apply_fcsm_rw_substitution(crr_simple_config).collect()
        compliant_row = result.filter(pl.col("exposure_reference") == LOAN_REF_COMPLIANT)

        # Assert
        assert compliant_row["risk_weight"][0] == pytest.approx(EXPECTED_RISK_WEIGHT_A, abs=1e-6), (
            f"P1.104-A: blended risk_weight should be {EXPECTED_RISK_WEIGHT_A:.2f} "
            f"(fully secured by 50%-RW corporate bond, Art. 239(1) met), "
            f"got {compliant_row['risk_weight'][0]:.4f}"
        )

    def test_p1_104_art_239_1_compliant_rwa(self, crr_simple_config: CalculationConfig) -> None:
        """
        Art. 239(1) satisfied: RWA = EAD × blended_rw = 1,000,000 × 0.50 = 500,000.

        Arrange: £1M corporate (CQS 4), £1M corporate bond CQS 2, maturity 6.0y >= 5.0y.
        Act:     FCSM columns + SA substitution + RWA calculation.
        Assert:  rwa = 500,000.
        """
        # Arrange
        exposures = _make_corporate_exposures()
        collateral = pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet")

        # Act
        with_fcsm = compute_fcsm_columns(exposures, collateral, crr_simple_config)
        result = (
            with_fcsm.sa.apply_fcsm_rw_substitution(crr_simple_config)
            .with_columns((pl.col("ead_final") * pl.col("risk_weight")).alias("rwa"))
            .collect()
        )
        compliant_row = result.filter(pl.col("exposure_reference") == LOAN_REF_COMPLIANT)

        # Assert
        assert compliant_row["rwa"][0] == pytest.approx(EXPECTED_RWA_A, rel=0.001), (
            f"P1.104-A: RWA should be {EXPECTED_RWA_A:,.0f} "
            f"(£1M × 0.50 blended RW, collateral 6.0y >= 5.0y — Art. 239(1) met), "
            f"got {compliant_row['rwa'][0]:,.0f}"
        )


# =============================================================================
# P1.104-ART-239-1-MISMATCH — Case B: collateral 3.0y < exposure 5.0y  [FAILS PRE-FIX]
# =============================================================================


class TestP1104FCSMMaturityMismatch:
    """
    P1.104-B: Collateral with residual_maturity_years=3.0 is INELIGIBLE under Art. 239(1).

    COLL_P1104_SHORT has maturity 3.0y which is LESS THAN the 5.0y exposure
    → Art. 239(1): collateral does not qualify as eligible funded credit protection.
    → FCSM benefit must be ZERO → exposure treated as fully unsecured.

    Pre-fix behaviour (incorrect):
        compute_fcsm_columns ignores residual_maturity_years and returns
        fcsm_collateral_value = 1,000,000 / fcsm_collateral_rw = 0.50
        → blended RW = 0.50 → RWA = 500,000 (too low by 500,000)

    Post-fix behaviour (correct):
        Art. 239(1) gate excludes COLL_P1104_SHORT
        → fcsm_collateral_value = 0.0 / fcsm_collateral_rw = 0.0
        → blended RW = 1.00 (fully unsecured) → RWA = 1,000,000
    """

    def test_p1_104_art_239_1_mismatch_fcsm_collateral_value_is_zero(
        self, crr_simple_config: CalculationConfig
    ) -> None:
        """
        Art. 239(1) violated: collateral 3.0y < exposure 5.0y → collateral excluded.

        Arrange: £1M corporate exposure (CQS 4, residual 5.0y), £1M corporate bond
                 CQS 2, collateral residual_maturity_years=3.0 (< 5.0y exposure).
        Act:     compute_fcsm_columns (CRR SIMPLE method).
        Assert:  fcsm_collateral_value = 0.0  (FCSM benefit is zero — collateral REJECTED).

        This test FAILS today because the engine does not check Art. 239(1) maturity
        eligibility and returns fcsm_collateral_value = 1,000,000 for this row.
        """
        # Arrange
        exposures = _make_corporate_exposures()
        collateral = pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet")

        # Act
        result = compute_fcsm_columns(exposures, collateral, crr_simple_config).collect()
        mismatch_row = result.filter(pl.col("exposure_reference") == LOAN_REF_MISMATCH)

        # Assert — collateral must be fully excluded (binary FCSM gate)
        assert mismatch_row["fcsm_collateral_value"][0] == pytest.approx(
            EXPECTED_FCSM_COLLATERAL_VALUE_B, abs=1e-6
        ), (
            f"P1.104-B: fcsm_collateral_value should be {EXPECTED_FCSM_COLLATERAL_VALUE_B:.0f} "
            f"(Art. 239(1): collateral {COLL_SHORT_RESIDUAL_MATURITY_YEARS}y < "
            f"exposure {EXPOSURE_RESIDUAL_MATURITY_YEARS:.2f}y → collateral INELIGIBLE), "
            f"got {mismatch_row['fcsm_collateral_value'][0]:,.2f}. "
            f"Pre-fix: engine ignores maturity check, returns 1,000,000."
        )

    def test_p1_104_art_239_1_mismatch_risk_weight_is_unsecured(
        self, crr_simple_config: CalculationConfig
    ) -> None:
        """
        Art. 239(1) violated: risk_weight must remain 1.00 (unsecured corporate CQS 4).

        Arrange: as above — COLL_P1104_SHORT has residual_maturity_years=3.0 < 5.0y.
        Act:     compute_fcsm_columns then apply_fcsm_rw_substitution.
        Assert:  risk_weight = 1.00 (no FCSM substitution — collateral excluded).

        This test FAILS today because the engine returns risk_weight = 0.50
        (blended as if collateral were fully recognised).
        """
        # Arrange
        exposures = _make_corporate_exposures()
        collateral = pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet")

        # Act
        with_fcsm = compute_fcsm_columns(exposures, collateral, crr_simple_config)
        result = with_fcsm.sa.apply_fcsm_rw_substitution(crr_simple_config).collect()
        mismatch_row = result.filter(pl.col("exposure_reference") == LOAN_REF_MISMATCH)

        # Assert — risk_weight must equal the unsecured borrower RW
        assert mismatch_row["risk_weight"][0] == pytest.approx(EXPECTED_RISK_WEIGHT_B, abs=1e-6), (
            f"P1.104-B: risk_weight should be {EXPECTED_RISK_WEIGHT_B:.2f} "
            f"(Art. 239(1): collateral {COLL_SHORT_RESIDUAL_MATURITY_YEARS}y maturity "
            f"< exposure {EXPOSURE_RESIDUAL_MATURITY_YEARS:.2f}y → no CRM benefit), "
            f"got {mismatch_row['risk_weight'][0]:.4f}. "
            f"Pre-fix: engine applies FCSM substitution → returns 0.50."
        )

    def test_p1_104_art_239_1_mismatch_rwa_equals_full_unsecured_rwa(
        self, crr_simple_config: CalculationConfig
    ) -> None:
        """
        Art. 239(1) violated: RWA = EAD × 1.00 = 1,000,000 (fully unsecured).

        Primary E2E assertion for P1.104-B. Art. 239(1) is binary — collateral
        is either fully eligible or fully excluded. Art. 239(2) partial adjustment
        does NOT apply to FCSM.

        Arrange: £1M corporate (CQS 4), £1M corporate bond CQS 2,
                 collateral residual_maturity_years=3.0 < exposure 5.0y.
        Act:     FCSM columns + SA substitution + RWA calculation.
        Assert:  rwa = 1,000,000.

        This test FAILS today because the engine returns rwa = 500,000
        (collateral incorrectly recognised despite Art. 239(1) violation).
        """
        # Arrange
        exposures = _make_corporate_exposures()
        collateral = pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet")

        # Act
        with_fcsm = compute_fcsm_columns(exposures, collateral, crr_simple_config)
        result = (
            with_fcsm.sa.apply_fcsm_rw_substitution(crr_simple_config)
            .with_columns((pl.col("ead_final") * pl.col("risk_weight")).alias("rwa"))
            .collect()
        )
        mismatch_row = result.filter(pl.col("exposure_reference") == LOAN_REF_MISMATCH)

        # Assert — no FCSM benefit → full unsecured RWA
        assert mismatch_row["rwa"][0] == pytest.approx(EXPECTED_RWA_B, rel=0.001), (
            f"P1.104-B: RWA should be {EXPECTED_RWA_B:,.0f} "
            f"(£1M × 1.00, Art. 239(1): collateral 3.0y < 5.0y → REJECTED), "
            f"got {mismatch_row['rwa'][0]:,.0f}. "
            f"Pre-fix: engine incorrectly returns {EXPECTED_RWA_A:,.0f} "
            f"(collateral recognised despite maturity mismatch)."
        )


# =============================================================================
# Differential assertion: correct direction of FCSM benefit
# =============================================================================


class TestP1104MismatchVsCompliantDivergence:
    """
    Structural validation: compliant RWA (500k) < mismatch RWA (1,000k).

    The delta = EAD × secured_pct × (borrower_rw - collateral_rw)
              = 1,000,000 × 1.00 × (1.00 - 0.50) = 500,000.

    This test confirms the Art. 239(1) gate produces a measurable capital impact.
    It FAILS today because both rows incorrectly return RWA = 500,000.
    """

    def test_p1_104_mismatch_rwa_greater_than_compliant_rwa_by_five_hundred_k(
        self, crr_simple_config: CalculationConfig
    ) -> None:
        """
        Mismatch RWA (1,000,000) must exceed compliant RWA (500,000) by exactly 500,000.

        Arrange: both exposures computed in one pass.
        Act:     FCSM columns + SA substitution + RWA calculation.
        Assert:  rwa_mismatch - rwa_compliant == 500,000.

        This test FAILS today because both rows return rwa = 500,000
        (delta = 0 instead of 500,000) when Art. 239(1) is not enforced.
        """
        # Arrange
        exposures = _make_corporate_exposures()
        collateral = pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet")

        # Act — single pass, two rows
        result = (
            compute_fcsm_columns(exposures, collateral, crr_simple_config)
            .sa.apply_fcsm_rw_substitution(crr_simple_config)
            .with_columns((pl.col("ead_final") * pl.col("risk_weight")).alias("rwa"))
            .collect()
        )

        compliant = result.filter(pl.col("exposure_reference") == LOAN_REF_COMPLIANT)
        mismatch = result.filter(pl.col("exposure_reference") == LOAN_REF_MISMATCH)

        rwa_compliant = compliant["rwa"][0]
        rwa_mismatch = mismatch["rwa"][0]

        # Assert
        assert rwa_mismatch - rwa_compliant == pytest.approx(500_000.0, abs=1.0), (
            f"P1.104: mismatch RWA - compliant RWA should equal 500,000 "
            f"(Art. 239(1) penalty = EAD × secured_pct × ΔRW = 1M × 1 × 0.50), "
            f"compliant={rwa_compliant:,.0f}, mismatch={rwa_mismatch:,.0f}, "
            f"delta={rwa_mismatch - rwa_compliant:,.0f}. "
            f"Pre-fix: both return 500,000, delta=0."
        )
