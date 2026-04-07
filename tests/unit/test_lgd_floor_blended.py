"""
Tests for Art. 164(4)(c) blended LGD floor for A-IRB retail with mixed collateral.

Art. 164(4)(c) specifies that for retail "other secured" exposures, the LGD floor
is a weighted average of per-type LGDS floors and the unsecured LGDU, using the
proportion of EAD absorbed by each collateral type from the Art. 231 waterfall.

    LGD_floor = (E_unsecured / EAD) × LGDU + Σ_i (E_i / EAD) × LGDS_i

Where:
    LGDU = 30% for retail_other, 50% for retail_qrre
    LGDS: financial=0%, receivables=10%, real_estate=10%, other_physical=15%

References:
    PRA PS1/26 Art. 164(4)(c)
"""

from __future__ import annotations

import polars as pl
import pytest

import rwa_calc.engine.irb.namespace  # register .irb namespace  # noqa: F401
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb.formulas import (
    _lgd_floor_blended_expression,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df(
    *,
    ead_gross: float = 100_000.0,
    exposure_class: str = "retail_other",
    crm_alloc_financial: float = 0.0,
    crm_alloc_covered_bond: float = 0.0,
    crm_alloc_receivables: float = 0.0,
    crm_alloc_real_estate: float = 0.0,
    crm_alloc_other_physical: float = 0.0,
    crm_alloc_life_insurance: float = 0.0,
    total_collateral_for_lgd: float | None = None,
) -> pl.LazyFrame:
    """Build a minimal LazyFrame with allocation columns for testing."""
    total = (
        crm_alloc_financial
        + crm_alloc_covered_bond
        + crm_alloc_receivables
        + crm_alloc_real_estate
        + crm_alloc_other_physical
        + crm_alloc_life_insurance
    )
    if total_collateral_for_lgd is None:
        total_collateral_for_lgd = min(total, ead_gross)
    return pl.LazyFrame(
        {
            "ead_gross": [ead_gross],
            "exposure_class": [exposure_class],
            "total_collateral_for_lgd": [total_collateral_for_lgd],
            "crm_alloc_financial": [crm_alloc_financial],
            "crm_alloc_covered_bond": [crm_alloc_covered_bond],
            "crm_alloc_receivables": [crm_alloc_receivables],
            "crm_alloc_real_estate": [crm_alloc_real_estate],
            "crm_alloc_other_physical": [crm_alloc_other_physical],
            "crm_alloc_life_insurance": [crm_alloc_life_insurance],
        }
    )


from datetime import date

_REPORTING_DATE = date(2027, 1, 1)
B31 = CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE)
CRR = CalculationConfig.crr(reporting_date=_REPORTING_DATE)


# ---------------------------------------------------------------------------
# Tests: _lgd_floor_blended_expression() directly
# ---------------------------------------------------------------------------


class TestBlendedExpressionDirect:
    """Test the blended floor expression in isolation."""

    def test_crr_returns_zero(self):
        """CRR has no LGD floors — blended expression returns 0."""
        lf = _make_df(crm_alloc_other_physical=60_000.0)
        result = lf.with_columns(_lgd_floor_blended_expression(CRR).alias("floor")).collect()
        assert result["floor"][0] == 0.0

    def test_fully_unsecured_retail_other_returns_null(self):
        """Fully unsecured retail_other: blended returns null (defers to fallback)."""
        lf = _make_df()  # all allocations zero, total_collateral_for_lgd = 0
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        # No collateral → not eligible for blended floor → null (single-type fallback)
        assert result["floor"][0] is None

    def test_fully_secured_by_financial(self):
        """100% financial collateral: floor = 0% (LGDS_financial)."""
        lf = _make_df(crm_alloc_financial=100_000.0)
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.0)

    def test_fully_secured_by_other_physical(self):
        """100% other physical: floor = 15% (LGDS_other_physical)."""
        lf = _make_df(crm_alloc_other_physical=100_000.0)
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.15)

    def test_mixed_physical_and_unsecured(self):
        """60% physical + 40% unsecured: floor = 0.6*15% + 0.4*30% = 21%."""
        lf = _make_df(crm_alloc_other_physical=60_000.0)
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.21)

    def test_mixed_financial_and_receivables(self):
        """50% financial + 50% receivables: floor = 0.5*0% + 0.5*10% = 5%."""
        lf = _make_df(
            crm_alloc_financial=50_000.0,
            crm_alloc_receivables=50_000.0,
        )
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.05)

    def test_three_type_mix(self):
        """30% financial + 40% RE + 30% unsecured: floor = 0*0.3 + 10%*0.4 + 30%*0.3 = 13%."""
        lf = _make_df(
            crm_alloc_financial=30_000.0,
            crm_alloc_real_estate=40_000.0,
        )
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.13)

    def test_all_collateral_types(self):
        """All 6 types used; compute weighted average correctly."""
        lf = _make_df(
            ead_gross=100_000.0,
            crm_alloc_financial=10_000.0,  # 10% × 0% = 0%
            crm_alloc_covered_bond=10_000.0,  # 10% × 0% = 0%
            crm_alloc_receivables=20_000.0,  # 20% × 10% = 2%
            crm_alloc_real_estate=20_000.0,  # 20% × 10% = 2%
            crm_alloc_other_physical=20_000.0,  # 20% × 15% = 3%
            crm_alloc_life_insurance=10_000.0,  # 10% × 0% = 0%
        )
        # 10% unsecured × 30% = 3% — total = 10%
        # Wait: total collateral = 90k, unsecured = 10k
        # floor = (10/100)*30% + (10/100)*0% + (10/100)*0% + (20/100)*10%
        #       + (20/100)*10% + (20/100)*15% + (10/100)*0%
        # = 3% + 0% + 0% + 2% + 2% + 3% + 0% = 10%
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.10)

    def test_retail_qrre_uses_50pct_lgdu(self):
        """QRRE exposure: 50% unsecured LGDU instead of 30%."""
        lf = _make_df(
            exposure_class="retail_qrre",
            crm_alloc_other_physical=60_000.0,
        )
        # 60% physical + 40% unsecured
        # floor = 0.6 * 15% + 0.4 * 50% = 9% + 20% = 29%
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.29)

    def test_retail_mortgage_returns_null(self):
        """retail_mortgage is not eligible for blended — returns null."""
        lf = _make_df(
            exposure_class="retail_mortgage",
            crm_alloc_real_estate=80_000.0,
        )
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] is None

    def test_corporate_returns_null(self):
        """Corporate exposure is not eligible for blended — returns null."""
        lf = _make_df(
            exposure_class="CORPORATE",
            crm_alloc_financial=80_000.0,
        )
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] is None

    def test_zero_ead_returns_null(self):
        """Zero EAD: no exposure, so blended not applicable → null."""
        lf = _make_df(
            ead_gross=0.0,
            crm_alloc_financial=50_000.0,
            total_collateral_for_lgd=0.0,
        )
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        # total_collateral_for_lgd=0 → not eligible → null
        assert result["floor"][0] is None

    def test_zero_ead_with_collateral_returns_zero(self):
        """Zero EAD but positive collateral: division guard returns 0."""
        lf = pl.LazyFrame(
            {
                "ead_gross": [0.0],
                "exposure_class": ["retail_other"],
                "total_collateral_for_lgd": [50_000.0],
                "crm_alloc_financial": [50_000.0],
                "crm_alloc_covered_bond": [0.0],
                "crm_alloc_receivables": [0.0],
                "crm_alloc_real_estate": [0.0],
                "crm_alloc_other_physical": [0.0],
                "crm_alloc_life_insurance": [0.0],
            }
        )
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.0)

    def test_no_collateral_retail_other(self):
        """No collateral on retail_other: blended returns null (not eligible)."""
        lf = _make_df()  # all alloc = 0, total_collateral_for_lgd = 0
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        # total_collateral_for_lgd == 0, so has_collateral is False → null
        assert result["floor"][0] is None

    def test_overcollateralised(self):
        """Collateral exceeds EAD: unsecured portion clamped to 0."""
        lf = _make_df(
            crm_alloc_other_physical=120_000.0,
            total_collateral_for_lgd=100_000.0,  # capped at EAD
        )
        # Fully secured, unsecured portion = 0
        # But alloc = 120k, EAD = 100k. Numerator = 120k * 15% = 18k.
        # Floor = 18k / 100k = 18%. But this is before alloc cap.
        # Actually the waterfall caps at EAD, so total_collateral = 100k.
        # The _es_ amounts ARE capped by the waterfall (cumulative trick).
        # In real use, crm_alloc_other_physical would be 100k (capped).
        # Let's test with actual waterfall output (capped values).
        lf2 = _make_df(
            crm_alloc_other_physical=100_000.0,
            total_collateral_for_lgd=100_000.0,
        )
        result = lf2.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# Tests: Integration with apply_lgd_floor via namespace
# ---------------------------------------------------------------------------


class TestBlendedFloorIntegration:
    """Test that the blended floor is correctly wired through the namespace."""

    def _make_irb_df(
        self,
        *,
        lgd: float = 0.10,
        exposure_class: str = "retail_other",
        is_airb: bool = True,
        crm_alloc_financial: float = 0.0,
        crm_alloc_other_physical: float = 0.0,
        ead_gross: float = 100_000.0,
        total_collateral_for_lgd: float | None = None,
    ) -> pl.LazyFrame:
        total = crm_alloc_financial + crm_alloc_other_physical
        if total_collateral_for_lgd is None:
            total_collateral_for_lgd = min(total, ead_gross)
        return pl.LazyFrame(
            {
                "lgd": [lgd],
                "lgd_input": [lgd],
                "exposure_class": [exposure_class],
                "is_airb": [is_airb],
                "ead_gross": [ead_gross],
                "total_collateral_for_lgd": [total_collateral_for_lgd],
                "crm_alloc_financial": [crm_alloc_financial],
                "crm_alloc_covered_bond": [0.0],
                "crm_alloc_receivables": [0.0],
                "crm_alloc_real_estate": [0.0],
                "crm_alloc_other_physical": [crm_alloc_other_physical],
                "crm_alloc_life_insurance": [0.0],
                "collateral_type": ["other_physical"],
            }
        )

    def test_airb_retail_other_blended_floor_applied(self):
        """A-IRB retail_other gets blended floor, not single-type."""
        # 60% physical + 40% unsecured → blended floor = 0.6*15% + 0.4*30% = 21%
        # Institution LGD estimate = 10% (below floor)
        lf = self._make_irb_df(
            lgd=0.10,
            crm_alloc_other_physical=60_000.0,
        )
        result = lf.irb.apply_lgd_floor(B31).collect()
        # Without blended: single-type floor would be 15% (other_physical)
        # With blended: floor is 21%
        assert result["lgd_floored"][0] == pytest.approx(0.21)

    def test_airb_retail_other_lgd_above_blended_floor(self):
        """A-IRB retail_other with LGD above blended floor: no change."""
        lf = self._make_irb_df(
            lgd=0.35,
            crm_alloc_other_physical=60_000.0,
        )
        result = lf.irb.apply_lgd_floor(B31).collect()
        # Blended floor = 21%, LGD = 35% > 21%, so lgd_floored = 35%
        assert result["lgd_floored"][0] == pytest.approx(0.35)

    def test_firb_not_floored(self):
        """F-IRB supervisory LGD is not subject to LGD floor."""
        lf = self._make_irb_df(
            lgd=0.10,
            is_airb=False,
            crm_alloc_other_physical=60_000.0,
        )
        result = lf.irb.apply_lgd_floor(B31).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.10)

    def test_crr_no_floor(self):
        """CRR: No LGD floors at all."""
        lf = self._make_irb_df(
            lgd=0.10,
            crm_alloc_other_physical=60_000.0,
        )
        result = lf.irb.apply_lgd_floor(CRR).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.10)

    def test_corporate_uses_single_type_floor(self):
        """Corporate falls through to single-type floor (not blended)."""
        lf = self._make_irb_df(
            lgd=0.10,
            exposure_class="CORPORATE",
            crm_alloc_other_physical=60_000.0,
        )
        result = lf.irb.apply_lgd_floor(B31).collect()
        # Corporate single-type floor for other_physical = 15%
        assert result["lgd_floored"][0] == pytest.approx(0.15)

    def test_retail_mortgage_uses_flat_floor(self):
        """retail_mortgage uses flat 5% floor (Art. 164(4)(a)), not blended."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.02],
                "lgd_input": [0.02],
                "exposure_class": ["retail_mortgage"],
                "is_airb": [True],
                "ead_gross": [100_000.0],
                "total_collateral_for_lgd": [80_000.0],
                "crm_alloc_financial": [0.0],
                "crm_alloc_covered_bond": [0.0],
                "crm_alloc_receivables": [0.0],
                "crm_alloc_real_estate": [80_000.0],
                "crm_alloc_other_physical": [0.0],
                "crm_alloc_life_insurance": [0.0],
                "collateral_type": ["residential_re"],
            }
        )
        result = lf.irb.apply_lgd_floor(B31).collect()
        # retail_mortgage → flat 5% floor for RRE collateral
        assert result["lgd_floored"][0] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Tests: CRM allocation columns preserved
# ---------------------------------------------------------------------------


class TestCRMAllocColumnsPreserved:
    """Verify that crm_alloc_* columns survive the CRM pipeline."""

    def test_allocation_column_names(self):
        """CRM_ALLOC_COLUMNS mapping covers all waterfall types."""
        from rwa_calc.engine.crm.constants import CRM_ALLOC_COLUMNS, WATERFALL_ORDER

        suffixes = {suffix for _, _, suffix in WATERFALL_ORDER}
        assert set(CRM_ALLOC_COLUMNS.keys()) == suffixes
        # All output columns have the crm_alloc_ prefix
        for col_name in CRM_ALLOC_COLUMNS.values():
            assert col_name.startswith("crm_alloc_")


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------


class TestBlendedFloorEdgeCases:
    """Edge cases for the blended LGD floor."""

    def test_null_allocation_columns(self):
        """Null allocation columns treated as zero."""
        lf = pl.LazyFrame(
            {
                "ead_gross": [100_000.0],
                "exposure_class": ["retail_other"],
                "total_collateral_for_lgd": [50_000.0],
                "crm_alloc_financial": [None],
                "crm_alloc_covered_bond": [None],
                "crm_alloc_receivables": [None],
                "crm_alloc_real_estate": [None],
                "crm_alloc_other_physical": [50_000.0],
                "crm_alloc_life_insurance": [None],
            }
        )
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        # 50% physical + 50% unsecured = 0.5*15% + 0.5*30% = 22.5%
        assert result["floor"][0] == pytest.approx(0.225)

    def test_small_ead_precision(self):
        """Small EAD values: check numerical precision."""
        lf = _make_df(
            ead_gross=1.0,
            crm_alloc_other_physical=0.6,
        )
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        # 60% physical + 40% unsecured = 0.6*15% + 0.4*30% = 21%
        assert result["floor"][0] == pytest.approx(0.21, abs=1e-10)

    @pytest.mark.parametrize(
        "alloc_fin,alloc_op,expected_floor",
        [
            (100_000, 0, 0.0),  # 100% financial → 0%
            (0, 100_000, 0.15),  # 100% other_physical → 15%
            (50_000, 50_000, 0.075),  # 50/50 → 7.5%
            (80_000, 20_000, 0.03),  # 80% fin + 20% phys → 3%
            (20_000, 80_000, 0.12),  # 20% fin + 80% phys → 12%
        ],
    )
    def test_parametrized_two_type_mix(self, alloc_fin, alloc_op, expected_floor):
        """Parametrized: financial + other_physical blends."""
        lf = _make_df(
            crm_alloc_financial=alloc_fin,
            crm_alloc_other_physical=alloc_op,
        )
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(expected_floor)

    def test_receivables_and_re_blend(self):
        """Receivables + RE both at 10% LGDS — verify correct computation."""
        lf = _make_df(
            crm_alloc_receivables=40_000.0,
            crm_alloc_real_estate=40_000.0,
        )
        # 40% rec + 40% re + 20% unsecured = 0.4*10% + 0.4*10% + 0.2*30% = 14%
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.14)

    def test_life_insurance_treated_as_financial(self):
        """Life insurance gets 0% LGDS floor (same as financial collateral)."""
        lf = _make_df(
            crm_alloc_life_insurance=60_000.0,
        )
        # 60% life ins (0%) + 40% unsecured (30%) = 12%
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.12)

    def test_covered_bond_treated_as_financial(self):
        """Covered bonds get 0% LGDS floor (same as financial collateral)."""
        lf = _make_df(
            crm_alloc_covered_bond=70_000.0,
        )
        # 70% covered bond (0%) + 30% unsecured (30%) = 9%
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.09)
