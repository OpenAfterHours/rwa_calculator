"""
P1.106 — B31 FCSM Institution-Bond CQS 2 = 30% Under ECRA (Art. 120 Table 3).

Acceptance scenario: a £1M corporate exposure (CQS 4, 100% unsecured RW) is
50%-collateralised by an institution bond with CQS 2.  Under Basel 3.1 ECRA
the collateral risk weight for CQS 2 institutions is 30% (not 50% as under CRR).

Pipeline position:
    CRMProcessor._compute_fcsm_columns → SACalculator.apply_fcsm_rw_substitution

Key assertion:
    B31 ECRA: fcsm_collateral_rw = 0.30 (bug: currently returns 0.50)
    CRR:      fcsm_collateral_rw = 0.50 (regression pin — must stay 0.50)

Hand calculation:
    EAD_gross = 1,000,000
    fcsm_collateral_value = min(500,000, 1,000,000) = 500,000
    secured_pct = 0.50, unsecured_pct = 0.50
    B31:  blended_rw = 0.30 * 0.50 + 1.00 * 0.50 = 0.65  → RWA = 650,000
    CRR:  blended_rw = 0.50 * 0.50 + 1.00 * 0.50 = 0.75  → RWA = 750,000

References:
    PRA PS1/26 Art. 120 Table 3 ECRA (ps126app1.pdf)
    CRR Art. 120 Table 3
    CRR Art. 222(1) — FCSM substitution + 20% floor
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import CRMCollateralMethod
from rwa_calc.engine.crm.simple_method import (
    _derive_collateral_rw_expr,
    compute_fcsm_columns,
)
from rwa_calc.engine.sa.rw_adjustments import apply_fcsm_rw_substitution

# =============================================================================
# Shared test data builders
# =============================================================================

_EAD = 1_000_000.0
_COLLATERAL_VALUE = 500_000.0


def _make_corporate_exposure(currency: str = "GBP") -> pl.LazyFrame:
    """GBP corporate exposure, EAD = £1M, unsecured RW = 100% (CQS 4 borrower)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["LOAN_FCSM_INST_CQS2"],
            "ead_gross": [_EAD],
            "ead_pre_crm": [_EAD],
            "ead": [_EAD],
            "ead_final": [_EAD],
            "currency": [currency],
            "approach": ["standardised"],
            "exposure_class": ["CORPORATE"],
            "cqs": [4],
            "risk_weight": [1.0],
        }
    )


def _make_institution_bond_cqs2(
    collateral_currency: str = "EUR",
    beneficiary_ref: str = "LOAN_FCSM_INST_CQS2",
) -> pl.LazyFrame:
    """EUR-denominated institution bond, CQS 2, market value = €500k."""
    return pl.LazyFrame(
        {
            "collateral_reference": ["COLL_INST_BOND_CQS2"],
            "collateral_type": ["bond"],
            "market_value": [_COLLATERAL_VALUE],
            "currency": [collateral_currency],
            "beneficiary_reference": [beneficiary_ref],
            "beneficiary_type": ["loan"],
            "issuer_cqs": [2],
            "issuer_type": ["institution"],
            "is_eligible_financial_collateral": [True],
        }
    )


@pytest.fixture
def b31_simple_config() -> CalculationConfig:
    """Basel 3.1 config with Simple Method elected."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2028, 1, 1),
        crm_collateral_method=CRMCollateralMethod.SIMPLE,
    )


@pytest.fixture
def crr_simple_config() -> CalculationConfig:
    """CRR config with Simple Method elected (contrastive/regression pin)."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        crm_collateral_method=CRMCollateralMethod.SIMPLE,
    )


# =============================================================================
# B31-FCSM-INST-CQS2  — primary assertion (currently failing — bug)
# =============================================================================


class TestB31FCSMInstCQS2:
    """
    B31-FCSM-INST-CQS2: Institution bond CQS 2 collateral RW = 30% under B31 ECRA.

    This class validates all three tiers of the FCSM calculation:
    1. Collateral RW derivation (the bug site: should be 30%, currently 50%)
    2. compute_fcsm_columns aggregation (fcsm_collateral_rw)
    3. SA RW substitution resulting in blended 65% and RWA 650,000
    """

    def test_b31_fcsm_institution_cqs2_collateral_rw_thirty_pct(self) -> None:
        """
        Art. 120 Table 3 ECRA: institution bond CQS 2 = 30% under Basel 3.1.

        Arrange: institution bond, CQS 2, Basel 3.1 framework.
        Act:     _derive_collateral_rw_expr(is_basel_3_1=True).
        Assert:  collateral RW = 0.30.

        Bug site: simple_method.py `institution_rw` branch ignores framework flag
        and returns 0.50 for CQS 2 under both CRR and B31.
        """
        # Arrange
        df = pl.DataFrame(
            {
                "collateral_type": ["bond"],
                "issuer_type": ["institution"],
                "issuer_cqs": [2],
            }
        )

        # Act
        result = df.with_columns(
            _derive_collateral_rw_expr(is_basel_3_1=True).alias("collateral_rw")
        )

        # Assert
        assert result["collateral_rw"][0] == pytest.approx(0.30, abs=1e-10), (
            "B31 ECRA: institution CQS 2 collateral RW should be 0.30 "
            f"(PRA PS1/26 Art. 120 Table 3), got {result['collateral_rw'][0]}"
        )

    def test_b31_fcsm_institution_cqs2_fcsm_columns(
        self, b31_simple_config: CalculationConfig
    ) -> None:
        """
        compute_fcsm_columns propagates B31 CQS 2 = 30% into fcsm_collateral_rw.

        Arrange: £1M corporate exposure, €500k institution bond CQS 2.
        Act:     compute_fcsm_columns under Basel 3.1.
        Assert:
            fcsm_collateral_value = 500,000
            fcsm_collateral_rw    = 0.30   (bug: currently returns 0.50)
        """
        # Arrange
        exposures = _make_corporate_exposure(currency="GBP")
        collateral = _make_institution_bond_cqs2(collateral_currency="EUR")

        # Act
        result = compute_fcsm_columns(exposures, collateral, b31_simple_config).collect()

        # Assert — collateral value
        assert result["fcsm_collateral_value"][0] == pytest.approx(500_000.0, rel=0.001), (
            f"fcsm_collateral_value should be 500,000, got {result['fcsm_collateral_value'][0]:,.0f}"
        )

        # Assert — collateral RW: 30% under B31 (bug yields 50%)
        assert result["fcsm_collateral_rw"][0] == pytest.approx(0.30, abs=1e-10), (
            "B31 ECRA: fcsm_collateral_rw for institution CQS 2 should be 0.30 "
            f"(PRA PS1/26 Art. 120 Table 3), got {result['fcsm_collateral_rw'][0]}"
        )

    def test_b31_fcsm_institution_cqs2_blended_risk_weight(
        self, b31_simple_config: CalculationConfig
    ) -> None:
        """
        Blended RW = 0.30 * 0.50 + 1.00 * 0.50 = 0.65 under Basel 3.1.

        Arrange: exposure with fcsm_collateral_rw = 0.30 (B31 ECRA target).
        Act:     apply_fcsm_rw_substitution.
        Assert:  risk_weight = 0.65.

        Note: the pre-condition (fcsm_collateral_rw=0.30) is hard-coded here to
        isolate the blending arithmetic from the derivation bug.  The derivation
        test above verifies the upstream step.
        """
        # Arrange — pre-compute expected fcsm_collateral_rw (post-fix value)
        exposures_with_fcsm = pl.LazyFrame(
            {
                "exposure_reference": ["LOAN_FCSM_INST_CQS2"],
                "ead_final": [_EAD],
                "risk_weight": [1.0],
                "fcsm_collateral_value": [_COLLATERAL_VALUE],
                "fcsm_collateral_rw": [0.30],  # B31 ECRA target
                "approach": ["standardised"],
                "exposure_class": ["CORPORATE"],
            }
        )

        # Act
        result = exposures_with_fcsm.pipe(apply_fcsm_rw_substitution, b31_simple_config).collect()

        # Assert
        assert result["risk_weight"][0] == pytest.approx(0.65, abs=1e-6), (
            f"B31 blended RW should be 0.65 (0.30×0.50 + 1.00×0.50), got {result['risk_weight'][0]}"
        )

    def test_b31_fcsm_institution_cqs2_rwa(self, b31_simple_config: CalculationConfig) -> None:
        """
        RWA = EAD × blended_rw = 1,000,000 × 0.65 = 650,000 under Basel 3.1.

        Primary E2E assertion for P1.106. Combines derivation + blending.
        The test fails at the derivation step (fcsm_collateral_rw = 0.50 → bug),
        so the blended RW arrives as 0.75 and RWA = 750,000 (100k too high).
        """
        # Arrange
        exposures = _make_corporate_exposure(currency="GBP")
        collateral = _make_institution_bond_cqs2(collateral_currency="EUR")

        # Act — derive FCSM columns then apply SA substitution
        with_fcsm = compute_fcsm_columns(exposures, collateral, b31_simple_config)
        result = with_fcsm.pipe(apply_fcsm_rw_substitution, b31_simple_config)
        result = result.with_columns(
            (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa")
        ).collect()

        # Assert: fcsm_collateral_rw drives the blended RW
        assert result["fcsm_collateral_rw"][0] == pytest.approx(0.30, abs=1e-10), (
            "fcsm_collateral_rw must be 0.30 before blending (B31 ECRA CQS 2)"
        )
        assert result["risk_weight"][0] == pytest.approx(0.65, abs=1e-6), (
            f"Blended RW should be 0.65, got {result['risk_weight'][0]:.4f}"
        )
        assert result["rwa"][0] == pytest.approx(650_000.0, rel=0.001), (
            f"RWA should be 650,000 under B31 ECRA, got {result['rwa'][0]:,.0f} "
            f"(delta from bug: {result['rwa'][0] - 650_000:,.0f})"
        )


# =============================================================================
# CRR-FCSM-INST-CQS2  — contrastive regression pin (must pass already)
# =============================================================================


class TestCRRFCSMInstCQS2Regression:
    """
    CRR-FCSM-INST-CQS2: Institution bond CQS 2 collateral RW = 50% under CRR.

    Regression pin: this test MUST PASS both before and after the fix.  It
    ensures the engine-implementer does not accidentally change CRR behaviour
    when fixing the B31 branch.
    """

    def test_crr_fcsm_institution_cqs2_collateral_rw_fifty_pct(self) -> None:
        """
        CRR Art. 120 Table 3: institution bond CQS 2 = 50% under CRR.

        Arrange: institution bond, CQS 2, CRR framework.
        Act:     _derive_collateral_rw_expr(is_basel_3_1=False).
        Assert:  collateral RW = 0.50.
        """
        # Arrange
        df = pl.DataFrame(
            {
                "collateral_type": ["bond"],
                "issuer_type": ["institution"],
                "issuer_cqs": [2],
            }
        )

        # Act
        result = df.with_columns(
            _derive_collateral_rw_expr(is_basel_3_1=False).alias("collateral_rw")
        )

        # Assert
        assert result["collateral_rw"][0] == pytest.approx(0.50, abs=1e-10), (
            f"CRR: institution CQS 2 collateral RW should be 0.50, got {result['collateral_rw'][0]}"
        )

    def test_crr_fcsm_institution_cqs2_fcsm_columns(
        self, crr_simple_config: CalculationConfig
    ) -> None:
        """
        fcsm_collateral_rw = 0.50 under CRR for institution CQS 2.

        Regression: must not change after the B31 fix.
        """
        # Arrange
        exposures = _make_corporate_exposure(currency="GBP")
        collateral = _make_institution_bond_cqs2(collateral_currency="EUR")

        # Act
        result = compute_fcsm_columns(exposures, collateral, crr_simple_config).collect()

        # Assert
        assert result["fcsm_collateral_rw"][0] == pytest.approx(0.50, abs=1e-10), (
            f"CRR fcsm_collateral_rw should be 0.50, got {result['fcsm_collateral_rw'][0]}"
        )

    def test_crr_fcsm_institution_cqs2_rwa(self, crr_simple_config: CalculationConfig) -> None:
        """
        CRR RWA = 1,000,000 × 0.75 = 750,000.

        blended_rw = 0.50 × 0.50 + 1.00 × 0.50 = 0.75.
        """
        # Arrange
        exposures = _make_corporate_exposure(currency="GBP")
        collateral = _make_institution_bond_cqs2(collateral_currency="EUR")

        # Act
        with_fcsm = compute_fcsm_columns(exposures, collateral, crr_simple_config)
        result = with_fcsm.pipe(apply_fcsm_rw_substitution, crr_simple_config)
        result = result.with_columns(
            (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa")
        ).collect()

        # Assert
        assert result["risk_weight"][0] == pytest.approx(0.75, abs=1e-6), (
            f"CRR blended RW should be 0.75, got {result['risk_weight'][0]:.4f}"
        )
        assert result["rwa"][0] == pytest.approx(750_000.0, rel=0.001), (
            f"CRR RWA should be 750,000, got {result['rwa'][0]:,.0f}"
        )


# =============================================================================
# Framework divergence assertion (combined)
# =============================================================================


class TestB31CRRFrameworkDivergence:
    """
    Structural validation: B31 ECRA institution CQS 2 produces lower capital.

    The delta is exactly -100,000 RWA (-10pp of EAD) — a consequence of the
    10pp reduction in institution CQS 2 risk weight (30% vs 50%) applied to
    the 50% secured share.
    """

    def test_b31_rwa_lower_than_crr_by_one_hundred_k(
        self,
        b31_simple_config: CalculationConfig,
        crr_simple_config: CalculationConfig,
    ) -> None:
        """
        B31 ECRA RWA (650k) should be 100k less than CRR RWA (750k).

        The 100k delta = EAD × (CRR_collateral_rw − B31_collateral_rw) × secured_pct
                        = 1,000,000 × (0.50 − 0.30) × 0.50
                        = 100,000.
        """
        # Arrange
        exposures = _make_corporate_exposure(currency="GBP")
        collateral = _make_institution_bond_cqs2(collateral_currency="EUR")

        def _compute_rwa(cfg: CalculationConfig) -> float:
            with_fcsm = compute_fcsm_columns(exposures, collateral, cfg)
            result = (
                with_fcsm.pipe(apply_fcsm_rw_substitution, cfg)
                .with_columns((pl.col("ead_final") * pl.col("risk_weight")).alias("rwa"))
                .collect()
            )
            return result["rwa"][0]

        # Act
        b31_rwa = _compute_rwa(b31_simple_config)
        crr_rwa = _compute_rwa(crr_simple_config)

        # Assert
        assert crr_rwa - b31_rwa == pytest.approx(100_000.0, abs=1.0), (
            f"Delta should be 100,000: CRR={crr_rwa:,.0f}, B31={b31_rwa:,.0f}, "
            f"delta={crr_rwa - b31_rwa:,.0f}"
        )
