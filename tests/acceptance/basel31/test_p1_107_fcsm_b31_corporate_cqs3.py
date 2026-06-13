"""
P1.107 — B31 FCSM Corporate-Bond CQS 3 = 75% Under Art. 122(2) Table 6.

Acceptance scenario: a £1M corporate exposure (CQS 4, 100% unsecured RW) is
fully collateralised by a corporate bond with CQS 3. Under Basel 3.1 Art. 122(2)
Table 6 the SA risk weight for CQS 3 corporates is 75% (not 100% as under CRR).

Pipeline position:
    CRMProcessor._compute_fcsm_columns → SACalculator.apply_fcsm_rw_substitution

Key assertion:
    B31 Art. 122(2): fcsm_collateral_rw = 0.75 (bug: currently returns 1.00)
    CRR Art. 122:    fcsm_collateral_rw = 1.00 (regression pin — must stay 1.00)

Hand calculation:
    EAD_gross = 1,000,000
    fcsm_collateral_value = min(1,000,000, 1,000,000) = 1,000,000
    secured_pct = 1.00, unsecured_pct = 0.00
    B31:  blended_rw = 0.75 × 1.00 + 1.00 × 0.00 = 0.75  → RWA = 750,000
    CRR:  blended_rw = 1.00 × 1.00 + 1.00 × 0.00 = 1.00  → RWA = 1,000,000

References:
    PRA PS1/26 Art. 122(2) Table 6 (ps126app1.pdf): corporate CQS 3 = 75%
    CRR Art. 122 Table 5: corporate CQS 3 = 100%
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
_COLLATERAL_VALUE = 1_000_000.0  # fully secured — secured_pct = 1.0


def _make_corporate_exposure(currency: str = "GBP") -> pl.LazyFrame:
    """GBP corporate exposure, EAD = £1M, unsecured RW = 100% (CQS 4 borrower)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["LN_P1107"],
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


def _make_corporate_bond_cqs3(
    collateral_currency: str = "EUR",
    beneficiary_ref: str = "LN_P1107",
) -> pl.LazyFrame:
    """EUR-denominated corporate bond, CQS 3, market value = £1m."""
    return pl.LazyFrame(
        {
            "collateral_reference": ["COLL_P1107"],
            "collateral_type": ["bond"],
            "market_value": [_COLLATERAL_VALUE],
            "currency": [collateral_currency],
            "beneficiary_reference": [beneficiary_ref],
            "beneficiary_type": ["loan"],
            "issuer_cqs": [3],
            "issuer_type": ["corporate"],
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
# B31-FCSM-CORP-CQS3  — primary assertion (currently failing — bug)
# =============================================================================


class TestB31FCSMCorpCQS3:
    """
    B31-FCSM-CORP-CQS3: Corporate bond CQS 3 collateral RW = 75% under B31.

    This class validates all three tiers of the FCSM calculation:
    1. Collateral RW derivation (the bug site: should be 75%, currently 100%)
    2. compute_fcsm_columns aggregation (fcsm_collateral_rw)
    3. SA RW substitution resulting in fully-secured 75% RW and RWA 750,000
    """

    def test_b31_fcsm_corporate_cqs3_collateral_rw_seventy_five_pct(self) -> None:
        """
        Art. 122(2) Table 6: corporate bond CQS 3 = 75% under Basel 3.1.

        Arrange: corporate bond, CQS 3, Basel 3.1 framework.
        Act:     _derive_collateral_rw_expr(is_basel_3_1=True).
        Assert:  collateral RW = 0.75.

        Bug site: simple_method.py `corporate_rw` branch hardcodes CQS 3 → 1.00
        for both CRR and B31.  Under B31 Art. 122(2) Table 6 the correct value
        is 0.75.
        """
        # Arrange
        df = pl.DataFrame(
            {
                "collateral_type": ["bond"],
                "issuer_type": ["corporate"],
                "issuer_cqs": [3],
            }
        )

        # Act
        result = df.with_columns(
            _derive_collateral_rw_expr(is_basel_3_1=True).alias("collateral_rw")
        )

        # Assert
        assert result["collateral_rw"][0] == pytest.approx(0.75, abs=1e-10), (
            "B31 Art. 122(2) Table 6: corporate CQS 3 collateral RW should be 0.75 "
            f"(PRA PS1/26 Art. 122(2)), got {result['collateral_rw'][0]}"
        )

    def test_b31_fcsm_corporate_cqs3_fcsm_columns(
        self, b31_simple_config: CalculationConfig
    ) -> None:
        """
        compute_fcsm_columns propagates B31 CQS 3 = 75% into fcsm_collateral_rw.

        Arrange: £1M corporate exposure, €1M corporate bond CQS 3.
        Act:     compute_fcsm_columns under Basel 3.1.
        Assert:
            fcsm_collateral_value = 1,000,000
            fcsm_collateral_rw    = 0.75   (bug: currently returns 1.00)
        """
        # Arrange
        exposures = _make_corporate_exposure(currency="GBP")
        collateral = _make_corporate_bond_cqs3(collateral_currency="EUR")

        # Act
        result = compute_fcsm_columns(exposures, collateral, b31_simple_config).collect()

        # Assert — collateral value capped at EAD
        assert result["fcsm_collateral_value"][0] == pytest.approx(1_000_000.0, rel=0.001), (
            f"fcsm_collateral_value should be 1,000,000, "
            f"got {result['fcsm_collateral_value'][0]:,.0f}"
        )

        # Assert — collateral RW: 75% under B31 (bug yields 100%)
        assert result["fcsm_collateral_rw"][0] == pytest.approx(0.75, abs=1e-10), (
            "B31 Art. 122(2): fcsm_collateral_rw for corporate CQS 3 should be 0.75 "
            f"(PRA PS1/26 Art. 122(2) Table 6), got {result['fcsm_collateral_rw'][0]}"
        )

    def test_b31_fcsm_corporate_cqs3_blended_risk_weight(
        self, b31_simple_config: CalculationConfig
    ) -> None:
        """
        Blended RW = 0.75 × 1.00 + 1.00 × 0.00 = 0.75 under Basel 3.1 (fully secured).

        Arrange: exposure with fcsm_collateral_rw = 0.75 (B31 Art. 122(2) target).
        Act:     apply_fcsm_rw_substitution.
        Assert:  risk_weight = 0.75.

        Note: the pre-condition (fcsm_collateral_rw=0.75) is hard-coded here to
        isolate the blending arithmetic from the derivation bug.
        """
        # Arrange — pre-set fcsm_collateral_rw to the post-fix target value
        exposures_with_fcsm = pl.LazyFrame(
            {
                "exposure_reference": ["LN_P1107"],
                "ead_final": [_EAD],
                "risk_weight": [1.0],
                "fcsm_collateral_value": [_COLLATERAL_VALUE],
                "fcsm_collateral_rw": [0.75],  # B31 Art. 122(2) target
                "approach": ["standardised"],
                "exposure_class": ["CORPORATE"],
            }
        )

        # Act
        result = exposures_with_fcsm.pipe(apply_fcsm_rw_substitution, b31_simple_config).collect()

        # Assert
        assert result["risk_weight"][0] == pytest.approx(0.75, abs=1e-6), (
            f"B31 blended RW should be 0.75 (0.75 × 1.00 fully secured), "
            f"got {result['risk_weight'][0]}"
        )

    def test_b31_fcsm_corporate_cqs3_rwa(self, b31_simple_config: CalculationConfig) -> None:
        """
        RWA = EAD × blended_rw = 1,000,000 × 0.75 = 750,000 under Basel 3.1.

        Primary E2E assertion for P1.107. Combines derivation + blending.
        The test fails at the derivation step (fcsm_collateral_rw = 1.00 → bug),
        so the blended RW arrives as 1.00 and RWA = 1,000,000 (250k too high).
        """
        # Arrange
        exposures = _make_corporate_exposure(currency="GBP")
        collateral = _make_corporate_bond_cqs3(collateral_currency="EUR")

        # Act — derive FCSM columns then apply SA substitution
        with_fcsm = compute_fcsm_columns(exposures, collateral, b31_simple_config)
        result = with_fcsm.pipe(apply_fcsm_rw_substitution, b31_simple_config)
        result = result.with_columns(
            (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa")
        ).collect()

        # Assert: fcsm_collateral_rw = 0.75 (bug: 1.00)
        assert result["fcsm_collateral_rw"][0] == pytest.approx(0.75, abs=1e-10), (
            "fcsm_collateral_rw must be 0.75 before blending (B31 Art. 122(2) CQS 3)"
        )
        assert result["risk_weight"][0] == pytest.approx(0.75, abs=1e-6), (
            f"Blended RW should be 0.75 (fully secured by CQS 3 corporate bond), "
            f"got {result['risk_weight'][0]:.4f}"
        )
        assert result["rwa"][0] == pytest.approx(750_000.0, rel=0.001), (
            f"RWA should be 750,000 under B31 Art. 122(2), got {result['rwa'][0]:,.0f} "
            f"(delta from bug: {result['rwa'][0] - 750_000:,.0f})"
        )


# =============================================================================
# CRR-FCSM-CORP-CQS3  — contrastive regression pin (must pass already)
# =============================================================================


class TestCRRFCSMCorpCQS3Regression:
    """
    CRR-FCSM-CORP-CQS3: Corporate bond CQS 3 collateral RW = 100% under CRR.

    Regression pin: this test MUST PASS both before and after the fix.  It
    ensures the engine-implementer does not accidentally change CRR behaviour
    when fixing the B31 branch.
    """

    def test_crr_fcsm_corporate_cqs3_collateral_rw_one_hundred_pct(self) -> None:
        """
        CRR Art. 122 Table 5: corporate bond CQS 3 = 100% under CRR.

        Arrange: corporate bond, CQS 3, CRR framework.
        Act:     _derive_collateral_rw_expr(is_basel_3_1=False).
        Assert:  collateral RW = 1.00.
        """
        # Arrange
        df = pl.DataFrame(
            {
                "collateral_type": ["bond"],
                "issuer_type": ["corporate"],
                "issuer_cqs": [3],
            }
        )

        # Act
        result = df.with_columns(
            _derive_collateral_rw_expr(is_basel_3_1=False).alias("collateral_rw")
        )

        # Assert
        assert result["collateral_rw"][0] == pytest.approx(1.00, abs=1e-10), (
            f"CRR: corporate CQS 3 collateral RW should be 1.00, got {result['collateral_rw'][0]}"
        )

    def test_crr_fcsm_corporate_cqs3_fcsm_columns(
        self, crr_simple_config: CalculationConfig
    ) -> None:
        """
        fcsm_collateral_rw = 1.00 under CRR for corporate CQS 3.

        Regression: must not change after the B31 fix.
        """
        # Arrange
        exposures = _make_corporate_exposure(currency="GBP")
        collateral = _make_corporate_bond_cqs3(collateral_currency="EUR")

        # Act
        result = compute_fcsm_columns(exposures, collateral, crr_simple_config).collect()

        # Assert
        assert result["fcsm_collateral_rw"][0] == pytest.approx(1.00, abs=1e-10), (
            f"CRR fcsm_collateral_rw should be 1.00, got {result['fcsm_collateral_rw'][0]}"
        )

    def test_crr_fcsm_corporate_cqs3_rwa(self, crr_simple_config: CalculationConfig) -> None:
        """
        CRR RWA = 1,000,000 × 1.00 = 1,000,000 (fully secured by 100%-RW collateral).

        blended_rw = 1.00 × 1.00 + 1.00 × 0.00 = 1.00 (fully secured).
        """
        # Arrange
        exposures = _make_corporate_exposure(currency="GBP")
        collateral = _make_corporate_bond_cqs3(collateral_currency="EUR")

        # Act
        with_fcsm = compute_fcsm_columns(exposures, collateral, crr_simple_config)
        result = with_fcsm.pipe(apply_fcsm_rw_substitution, crr_simple_config)
        result = result.with_columns(
            (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa")
        ).collect()

        # Assert
        assert result["risk_weight"][0] == pytest.approx(1.00, abs=1e-6), (
            f"CRR blended RW should be 1.00, got {result['risk_weight'][0]:.4f}"
        )
        assert result["rwa"][0] == pytest.approx(1_000_000.0, rel=0.001), (
            f"CRR RWA should be 1,000,000, got {result['rwa'][0]:,.0f}"
        )


# =============================================================================
# Framework divergence assertion (combined)
# =============================================================================


class TestB31CRRFrameworkDivergence:
    """
    Structural validation: B31 corporate CQS 3 produces lower capital.

    The delta is exactly -250,000 RWA (-25pp of EAD) — a consequence of the
    25pp reduction in corporate CQS 3 risk weight (75% vs 100%) applied to
    the 100% secured share.
    """

    def test_b31_rwa_lower_than_crr_by_two_hundred_fifty_k(
        self,
        b31_simple_config: CalculationConfig,
        crr_simple_config: CalculationConfig,
    ) -> None:
        """
        B31 RWA (750k) should be 250k less than CRR RWA (1,000k).

        The 250k delta = EAD × (CRR_collateral_rw − B31_collateral_rw) × secured_pct
                        = 1,000,000 × (1.00 − 0.75) × 1.00
                        = 250,000.
        """
        # Arrange
        exposures = _make_corporate_exposure(currency="GBP")
        collateral = _make_corporate_bond_cqs3(collateral_currency="EUR")

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
        assert crr_rwa - b31_rwa == pytest.approx(250_000.0, abs=1.0), (
            f"Delta should be 250,000: CRR={crr_rwa:,.0f}, B31={b31_rwa:,.0f}, "
            f"delta={crr_rwa - b31_rwa:,.0f}"
        )
