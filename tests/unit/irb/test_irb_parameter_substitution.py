"""
Unit tests for Basel 3.1 parameter substitution (CRE22.70-85).

Tests the IRB guarantee method where an IRB exposure guaranteed by an F-IRB
counterparty uses the guarantor's PD and F-IRB supervisory LGD instead of
SA risk weight substitution.

Under Basel 3.1:
- SA guarantor → SA risk weight substitution (existing CRR approach)
- IRB guarantor → PD parameter substitution (new Basel 3.1 approach)

The guaranteed portion RWA is recalculated using:
    K(guarantor_PD, F-IRB_LGD=0.40) × 12.5 × MA(guarantor_PD)

References:
- CRE22.70-85: Unfunded credit protection methods
- CRE32.9: F-IRB supervisory LGD (unsecured senior = 40% under Basel 3.1)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

import rwa_calc.engine.irb.namespace  # noqa: F401 - Register namespace
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb.formulas import _parametric_irb_risk_weight_expr


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR configuration (should use SA RW substitution, not parameter sub)."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Basel 3.1 configuration (enables parameter substitution)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _compute_expected_irb_rw(
    pd: float, lgd: float, maturity: float, exposure_class: str = "CORPORATE"
) -> float:
    """Compute expected IRB risk weight using the parametric formula helper.

    Uses a minimal LazyFrame to run the formula and extract the scalar result.
    """
    lf = pl.LazyFrame(
        {
            "exposure_class": [exposure_class],
            "turnover_m": [None],
            "maturity": [maturity],
            "requires_fi_scalar": [False],
        }
    )
    pd_expr = pl.lit(pd)
    rw_expr = _parametric_irb_risk_weight_expr(
        pd_expr=pd_expr, lgd=lgd, scaling_factor=1.0, eur_gbp_rate=0.8732
    )
    result = lf.with_columns(rw_expr.alias("rw")).collect()
    return result["rw"][0]


class TestParameterSubstitutionMethod:
    """Tests for Basel 3.1 PD parameter substitution."""

    def test_irb_guarantor_uses_parameter_substitution(
        self, b31_config: CalculationConfig
    ) -> None:
        """IRB guarantor under Basel 3.1 should use PD parameter substitution.

        The guaranteed portion RWA uses the guarantor's PD (0.005) and F-IRB
        supervisory LGD (0.40) through the IRB formula instead of SA RW lookup.
        """
        guarantor_pd = 0.005  # 0.5% PD — low default risk guarantor
        firb_lgd = 0.40  # F-IRB supervisory unsecured senior
        maturity = 2.5

        # Pre-compute expected IRB RW for guarantor parameters
        expected_guarantor_rw = _compute_expected_irb_rw(
            pd=guarantor_pd, lgd=firb_lgd, maturity=maturity
        )

        borrower_rw = 0.80  # Borrower's original IRB RW (higher than guarantor)
        ead = 1_000_000.0
        borrower_rwa = borrower_rw * ead  # 800k

        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.05],  # Borrower PD
                "lgd": [0.45],
                "ead_final": [ead],
                "maturity": [maturity],
                "exposure_class": ["CORPORATE"],
                "turnover_m": [None],
                "requires_fi_scalar": [False],
                "rwa": [borrower_rwa],
                "risk_weight": [borrower_rw],
                "guaranteed_portion": [ead],  # Fully guaranteed
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["corporate"],
                "guarantor_cqs": [2],
                "guarantor_approach": ["irb"],
                "guarantor_pd": [guarantor_pd],
            }
        )

        result = lf.irb.apply_guarantee_substitution(b31_config).collect()

        # Verify parameter substitution was used
        assert result["guarantee_method_used"][0] == "PD_PARAMETER_SUBSTITUTION"
        assert result["guarantee_status"][0] == "PD_PARAMETER_SUBSTITUTION"

        # RWA should be guaranteed_portion × IRB_RW(guarantor_PD, firb_LGD)
        expected_rwa = ead * expected_guarantor_rw
        assert result["rwa"][0] == pytest.approx(expected_rwa, rel=1e-4)

        # Guarantor RW should be the IRB-computed risk weight
        assert result["guarantor_rw"][0] == pytest.approx(expected_guarantor_rw, rel=1e-4)

    def test_sa_guarantor_uses_sa_rw_substitution_under_b31(
        self, b31_config: CalculationConfig
    ) -> None:
        """SA guarantor under Basel 3.1 should still use SA RW substitution."""
        ead = 1_000_000.0
        borrower_rw = 0.50
        borrower_rwa = borrower_rw * ead

        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [ead],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [borrower_rwa],
                "risk_weight": [borrower_rw],
                "guaranteed_portion": [ead],
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["sovereign"],
                "guarantor_cqs": [1],  # Sovereign CQS 1 = 0% RW
                "guarantor_approach": ["sa"],
                "guarantor_pd": [None],  # SA guarantor has no PD
            }
        )

        result = lf.irb.apply_guarantee_substitution(b31_config).collect()

        # Should use SA RW substitution
        assert result["guarantee_method_used"][0] == "SA_RW_SUBSTITUTION"
        assert result["guarantee_status"][0] == "SA_RW_SUBSTITUTION"

        # RWA = 0 for sovereign CQS 1 (0% RW)
        assert result["rwa"][0] == pytest.approx(0.0)
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_crr_always_uses_sa_rw_substitution(
        self, crr_config: CalculationConfig
    ) -> None:
        """CRR should always use SA RW substitution, even for IRB guarantors."""
        ead = 1_000_000.0
        borrower_rw = 0.80  # Higher than guarantor's SA RW (20%) → beneficial
        borrower_rwa = borrower_rw * ead

        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.05],
                "lgd": [0.45],
                "ead_final": [ead],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [borrower_rwa],
                "risk_weight": [borrower_rw],
                "guaranteed_portion": [ead],
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["corporate"],
                "guarantor_cqs": [1],  # Corporate CQS 1 = 20% RW under SA
                "guarantor_approach": ["irb"],
                "guarantor_pd": [0.005],  # IRB guarantor with PD
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        # CRR: always SA RW substitution regardless of guarantor approach
        assert result["guarantee_method_used"][0] == "SA_RW_SUBSTITUTION"
        assert result["guarantee_status"][0] == "SA_RW_SUBSTITUTION"

        # SA RW for corporate CQS 1 = 20%
        assert result["guarantor_rw"][0] == pytest.approx(0.20)

    def test_partial_guarantee_blends_irb_and_parameter_sub(
        self, b31_config: CalculationConfig
    ) -> None:
        """Partial guarantee should blend original IRB RWA with parameter-substituted RWA."""
        guarantor_pd = 0.005
        firb_lgd = 0.40
        maturity = 2.5
        ead = 1_000_000.0

        expected_guarantor_rw = _compute_expected_irb_rw(
            pd=guarantor_pd, lgd=firb_lgd, maturity=maturity
        )

        borrower_rw = 0.80
        borrower_rwa = borrower_rw * ead
        guaranteed = 600_000.0  # 60% guaranteed
        unguaranteed = 400_000.0  # 40% unguaranteed

        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.05],
                "lgd": [0.45],
                "ead_final": [ead],
                "maturity": [maturity],
                "exposure_class": ["CORPORATE"],
                "turnover_m": [None],
                "requires_fi_scalar": [False],
                "rwa": [borrower_rwa],
                "risk_weight": [borrower_rw],
                "guaranteed_portion": [guaranteed],
                "unguaranteed_portion": [unguaranteed],
                "guarantor_entity_type": ["corporate"],
                "guarantor_cqs": [2],
                "guarantor_approach": ["irb"],
                "guarantor_pd": [guarantor_pd],
            }
        )

        result = lf.irb.apply_guarantee_substitution(b31_config).collect()

        # Blended RWA = unguaranteed_fraction × original_rwa + guaranteed × guarantor_rw
        expected_rwa = (unguaranteed / ead) * borrower_rwa + guaranteed * expected_guarantor_rw
        assert result["rwa"][0] == pytest.approx(expected_rwa, rel=1e-4)

    def test_non_beneficial_parameter_sub_not_applied(
        self, b31_config: CalculationConfig
    ) -> None:
        """If guarantor's IRB RW >= borrower's RW, guarantee should not be applied."""
        # Set guarantor PD high enough that IRB RW exceeds borrower's
        guarantor_pd = 0.10  # High PD
        firb_lgd = 0.40
        maturity = 2.5

        guarantor_rw = _compute_expected_irb_rw(
            pd=guarantor_pd, lgd=firb_lgd, maturity=maturity
        )

        # Borrower has lower RW than guarantor would
        borrower_rw = max(0.01, guarantor_rw - 0.10)  # Ensure lower than guarantor
        ead = 1_000_000.0
        borrower_rwa = borrower_rw * ead

        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.001],
                "lgd": [0.45],
                "ead_final": [ead],
                "maturity": [maturity],
                "exposure_class": ["CORPORATE"],
                "turnover_m": [None],
                "requires_fi_scalar": [False],
                "rwa": [borrower_rwa],
                "risk_weight": [borrower_rw],
                "guaranteed_portion": [ead],
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["corporate"],
                "guarantor_cqs": [3],
                "guarantor_approach": ["irb"],
                "guarantor_pd": [guarantor_pd],
            }
        )

        result = lf.irb.apply_guarantee_substitution(b31_config).collect()

        # Non-beneficial: guarantee not applied, original RWA preserved
        assert result["guarantee_status"][0] == "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"
        assert result["rwa"][0] == pytest.approx(borrower_rwa)


class TestParameterSubstitutionExpectedLoss:
    """Tests for expected loss handling under parameter substitution."""

    def test_irb_guarantor_el_uses_substituted_pd(
        self, b31_config: CalculationConfig
    ) -> None:
        """IRB guarantor EL should use guarantor_pd × firb_lgd for guaranteed portion."""
        guarantor_pd = 0.005
        firb_lgd = 0.40
        ead = 1_000_000.0
        guaranteed = 600_000.0
        unguaranteed = 400_000.0
        original_el = 5_000.0  # Original EL for full exposure

        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [ead],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "turnover_m": [None],
                "requires_fi_scalar": [False],
                "rwa": [800_000.0],
                "risk_weight": [0.80],
                "expected_loss": [original_el],
                "guaranteed_portion": [guaranteed],
                "unguaranteed_portion": [unguaranteed],
                "guarantor_entity_type": ["corporate"],
                "guarantor_cqs": [2],
                "guarantor_approach": ["irb"],
                "guarantor_pd": [guarantor_pd],
            }
        )

        result = lf.irb.apply_guarantee_substitution(b31_config).collect()

        # EL = unguaranteed_fraction × original_EL + guarantor_pd_floored × firb_lgd × guaranteed
        # PD floor for corporate under B3.1 = 0.0005 (0.05%), guarantor PD 0.005 > floor
        unguaranteed_el = (unguaranteed / ead) * original_el
        guaranteed_el = guarantor_pd * firb_lgd * guaranteed  # 0.005 × 0.40 × 600k = 1200
        expected_el = unguaranteed_el + guaranteed_el
        assert result["expected_loss"][0] == pytest.approx(expected_el, rel=1e-4)

    def test_sa_guarantor_el_zeroes_guaranteed_portion(
        self, b31_config: CalculationConfig
    ) -> None:
        """SA guarantor under Basel 3.1: guaranteed portion has no EL (SA has no EL)."""
        ead = 1_000_000.0
        guaranteed = 600_000.0
        unguaranteed = 400_000.0
        original_el = 5_000.0

        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [ead],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [500_000.0],
                "risk_weight": [0.50],
                "expected_loss": [original_el],
                "guaranteed_portion": [guaranteed],
                "unguaranteed_portion": [unguaranteed],
                "guarantor_entity_type": ["sovereign"],
                "guarantor_cqs": [1],
                "guarantor_approach": ["sa"],
                "guarantor_pd": [None],
            }
        )

        result = lf.irb.apply_guarantee_substitution(b31_config).collect()

        # EL = unguaranteed_fraction × original_EL (SA portion has zero EL)
        expected_el = (unguaranteed / ead) * original_el
        assert result["expected_loss"][0] == pytest.approx(expected_el, rel=1e-4)


class TestParametricIRBRiskWeightExpr:
    """Tests for the _parametric_irb_risk_weight_expr helper function."""

    def test_higher_pd_gives_higher_risk_weight(self) -> None:
        """Higher PD should result in higher risk weight."""
        rw_low = _compute_expected_irb_rw(pd=0.003, lgd=0.40, maturity=2.5)
        rw_high = _compute_expected_irb_rw(pd=0.05, lgd=0.40, maturity=2.5)

        assert rw_high > rw_low

    def test_higher_lgd_gives_higher_risk_weight(self) -> None:
        """Higher LGD should result in higher risk weight."""
        rw_low = _compute_expected_irb_rw(pd=0.01, lgd=0.20, maturity=2.5)
        rw_high = _compute_expected_irb_rw(pd=0.01, lgd=0.40, maturity=2.5)

        assert rw_high > rw_low

    def test_longer_maturity_gives_higher_risk_weight(self) -> None:
        """Longer maturity should result in higher risk weight (for non-retail)."""
        rw_short = _compute_expected_irb_rw(pd=0.01, lgd=0.40, maturity=1.0)
        rw_long = _compute_expected_irb_rw(pd=0.01, lgd=0.40, maturity=5.0)

        assert rw_long > rw_short

    def test_risk_weight_is_positive(self) -> None:
        """Risk weight should always be positive for valid PD/LGD."""
        rw = _compute_expected_irb_rw(pd=0.003, lgd=0.40, maturity=2.5)
        assert rw > 0

    def test_zero_lgd_gives_zero_risk_weight(self) -> None:
        """Zero LGD (fully collateralised) should give zero risk weight."""
        rw = _compute_expected_irb_rw(pd=0.01, lgd=0.0, maturity=2.5)
        assert rw == pytest.approx(0.0, abs=1e-10)

    def test_retail_exposure_has_no_maturity_adjustment(self) -> None:
        """Retail exposures should have MA=1.0 (no maturity effect)."""
        rw_short = _compute_expected_irb_rw(
            pd=0.01, lgd=0.40, maturity=1.0, exposure_class="RETAIL_MORTGAGE"
        )
        rw_long = _compute_expected_irb_rw(
            pd=0.01, lgd=0.40, maturity=5.0, exposure_class="RETAIL_MORTGAGE"
        )

        # Retail: no maturity adjustment, so RW should be the same
        assert rw_short == pytest.approx(rw_long, rel=1e-6)


class TestMixedGuarantorApproaches:
    """Tests for mixed SA/IRB guarantor scenarios."""

    def test_no_guarantor_pd_falls_back_to_sa_rw(
        self, b31_config: CalculationConfig
    ) -> None:
        """IRB guarantor without PD data falls back to SA RW substitution."""
        ead = 1_000_000.0
        borrower_rwa = 500_000.0

        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [ead],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [borrower_rwa],
                "risk_weight": [0.50],
                "guaranteed_portion": [ead],
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["corporate"],
                "guarantor_cqs": [1],  # CQS 1 = 20% SA RW
                "guarantor_approach": ["irb"],
                "guarantor_pd": [None],  # No PD available
            }
        )

        result = lf.irb.apply_guarantee_substitution(b31_config).collect()

        # Falls back to SA RW substitution because guarantor_pd is null
        assert result["guarantee_method_used"][0] == "SA_RW_SUBSTITUTION"
        assert result["guarantor_rw"][0] == pytest.approx(0.20)
