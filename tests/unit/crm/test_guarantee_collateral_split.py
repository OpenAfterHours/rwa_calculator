"""
Direct unit tests for the D3 guarantee leg-split collateral conservation defect.

``_stock_split_cols()`` (``engine/crm/guarantees.py:61-76``) enumerates the
stock columns that must be pro-rated across guarantor/remainder legs when a
guaranteed exposure is physically split into ``__G_<guarantor>`` and
``__REM`` / ``__REM_FL`` / ``__REM_SEN`` sub-rows. It omits every
``collateral_*`` / ``crm_alloc_*`` column, so both ``_build_guarantor_sub_rows``
(``:886-911``) and ``_retained_tranche_rows`` (``:978-1015``) leave those
columns untouched — each leg inherits the FULL, unsplit collateral value and a
downstream ``Sum()`` counts it once per leg (COREP C 08.01/02 cols
0180/0190/0200/0210, C 07.00 col 0130, Pillar 3 CR7-A cols b/d/e/f).

References:
    CRR Art. 213-217: Unfunded credit protection (guarantee substitution)
    CRR Art. 230-231: Financial collateral comprehensive method / waterfall
    CRR Art. 234: Tranching of credit protection (attachment/detachment)
    PS1/26 Annex II cols 0150-0210: CRM techniques in LGD estimates reporting
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.crm.guarantees import _apply_guarantee_splits

# =============================================================================
# Stock-vs-ratio classification
# =============================================================================
#
# Verified against each column's producer in engine/crm/collateral.py:
#   - collateral_adjusted_value / collateral_market_value / collateral_financial_value /
#     collateral_cash_value / collateral_re_value / collateral_receivables_value /
#     collateral_other_physical_value: `_sum6(...)` currency sums (:1250-1257) --
#     STOCKS, same shape as `drawn_amount`.
# EXCLUDED although they ARE currency stocks -- the Art. 231 waterfall allocations
# `crm_alloc_*` (:1310-1316, :1374) and `total_collateral_for_lgd`
# (`min(cum, ead_for_crm)`, :1317, :1347). Their only post-split consumer is the
# Art. 161(5)(b) / 164(4)(c) blended LGD input floor (irb/formulas.py:454-461),
# which divides them by `lgd_star_exposure_basis_expr()` = ead_for_crm x (1 + HE).
# `ead_for_crm` is NOT split by _stock_split_cols() and is never recomputed after
# _initialize_ead, so it stays whole-exposure on every leg. That blend is a RATE,
# homogeneous of degree 0: splitting BOTH sides is number-neutral, splitting
# NEITHER is number-neutral, and splitting only the numerator is the one wrong
# option -- it would silently raise the floor on every guaranteed leg. Nothing
# under reporting/ reads either family, so splitting them buys no disclosure
# benefit to offset that risk.
# EXCLUDED as a ratio, NOT a stock:
#   - collateral_coverage_pct (:1500-1509): `total_collateral_for_lgd / ead_for_crm
#     * 100` -- a C/E percentage. Pro-rating it would be wrong; it is deliberately
#     absent from this list and from _stock_split_cols().
#   - collateral_lgd / lgd_secured / lgd_unsecured / lgd_post_crm: LGD rates, not
#     stocks -- also deliberately absent.
STOCK_COLLATERAL_COLUMNS: tuple[str, ...] = (
    "collateral_adjusted_value",
    "collateral_market_value",
    "collateral_financial_value",
    "collateral_cash_value",
    "collateral_re_value",
    "collateral_receivables_value",
    "collateral_other_physical_value",
)

# Distinct nonzero values per column so a conservation assertion can't pass by
# coincidence (e.g. every carrier defaulting to the same figure).
_COLLATERAL_VALUES: dict[str, float] = {
    "collateral_adjusted_value": 480_000.0,
    "collateral_market_value": 500_000.0,
    "collateral_financial_value": 50_000.0,
    "collateral_cash_value": 20_000.0,
    "collateral_re_value": 500_000.0,
    "collateral_receivables_value": 30_000.0,
    "collateral_other_physical_value": 40_000.0,
    "crm_alloc_financial": 50_000.0,
    "crm_alloc_covered_bond": 10_000.0,
    "crm_alloc_receivables": 30_000.0,
    "crm_alloc_real_estate": 300_000.0,
    "crm_alloc_other_physical": 40_000.0,
    "crm_alloc_life_insurance": 5_000.0,
    "total_collateral_for_lgd": 425_000.0,
}


def _exposure_with_collateral(ead: float = 1_000_000.0) -> pl.LazyFrame:
    """One real-estate-collateralised exposure, pre-guarantee-split."""
    data: dict = {
        "exposure_reference": ["EXP001"],
        "parent_exposure_reference": ["EXP001"],
        "ead_after_collateral": [ead],
        "ead_pre_crm": [ead],
        "drawn_amount": [ead],
        "nominal_amount": [0.0],
        "counterparty_reference": ["CP001"],
    }
    for col, value in _COLLATERAL_VALUES.items():
        data[col] = [value]
    return pl.LazyFrame(data)


# =============================================================================
# Conservation across guarantor / remainder legs (default first-loss split)
# =============================================================================


class TestGuaranteeSplitConservesCollateralValue:
    """D3: collateral_*/crm_alloc_* carriers must split like the other stock cols."""

    def test_partially_guaranteed_re_collateral_conserves_across_legs(self) -> None:
        """40% partial guarantee: Sum(collateral_re_value) across legs == pre-split value."""
        # Arrange
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001"],
                "amount_covered": [400_000.0],
                "guarantor": ["GUAR001"],
            }
        )
        exposures = _exposure_with_collateral(ead=1_000_000.0)

        # Act
        result = _apply_guarantee_splits(guarantees, exposures).collect()

        # Assert
        assert len(result) == 2
        total_re_value = result["collateral_re_value"].sum()
        assert total_re_value == pytest.approx(500_000.0, rel=1e-6)

    @pytest.mark.parametrize("column", STOCK_COLLATERAL_COLUMNS)
    def test_all_stock_collateral_columns_conserve_across_legs(self, column: str) -> None:
        """Every collateral_*/crm_alloc_* stock carrier conserves across the split.

        Today ``_stock_split_cols()`` omits these columns entirely, so each leg
        inherits the FULL pre-split value: the two-leg sum today is 2x the
        original figure -- a double count once these carriers reach a COREP
        Sum() (C 08.01/02 cols 0180-0210, C 07.00 col 0130, CR7-A cols b/d/e/f).
        """
        # Arrange
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001"],
                "amount_covered": [400_000.0],
                "guarantor": ["GUAR001"],
            }
        )
        exposures = _exposure_with_collateral(ead=1_000_000.0)
        original_value = _COLLATERAL_VALUES[column]

        # Act
        result = _apply_guarantee_splits(guarantees, exposures).collect()

        # Assert
        assert len(result) == 2
        total = result[column].sum()
        assert total == pytest.approx(original_value, rel=1e-6)

    def test_guaranteed_leg_collateral_share_matches_stock_split_basis(self) -> None:
        """The guaranteed/remainder legs' collateral share must use the SAME
        per-leg scale factor already applied to drawn_amount/ead_pre_crm by
        ``_stock_split_cols()`` -- the fix must reuse that convention, not
        invent a new one.
        """
        # Arrange: pre-split ratio collateral_re_value / drawn_amount = 0.5
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001"],
                "amount_covered": [400_000.0],
                "guarantor": ["GUAR001"],
            }
        )
        exposures = _exposure_with_collateral(ead=1_000_000.0)

        # Act
        result = _apply_guarantee_splits(guarantees, exposures).collect()
        guar = result.filter(pl.col("exposure_reference") == "EXP001__G_GUAR001")
        rem = result.filter(pl.col("exposure_reference") == "EXP001__REM")

        # Assert: the ratio is invariant across legs once collateral is split
        # by the same factor as drawn_amount (already in _stock_split_cols()).
        pre_split_ratio = 500_000.0 / 1_000_000.0
        guar_ratio = guar["collateral_re_value"][0] / guar["drawn_amount"][0]
        rem_ratio = rem["collateral_re_value"][0] / rem["drawn_amount"][0]
        assert guar_ratio == pytest.approx(pre_split_ratio, rel=1e-6)
        assert rem_ratio == pytest.approx(pre_split_ratio, rel=1e-6)

    def test_unguaranteed_exposure_collateral_unchanged(self) -> None:
        """Regression guard: an exposure with no guarantee is untouched."""
        # Arrange
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["OTHER"],
                "amount_covered": [100_000.0],
                "guarantor": ["GUAR001"],
            }
        )
        exposures = _exposure_with_collateral(ead=1_000_000.0)

        # Act
        result = _apply_guarantee_splits(guarantees, exposures).collect()

        # Assert
        assert len(result) == 1
        assert result["collateral_re_value"][0] == pytest.approx(500_000.0, rel=1e-6)
        assert result["total_collateral_for_lgd"][0] == pytest.approx(425_000.0, rel=1e-6)


# =============================================================================
# Conservation across Art. 234 tranched legs (first-loss / mezzanine / senior)
# =============================================================================


class TestArt234TranchedSplitConservesCollateralValue:
    """D3 on the mezzanine tranching path (``__REM_FL`` / ``__REM_SEN``)."""

    def test_tranched_split_conserves_collateral(self) -> None:
        """Art. 234 mezzanine tranching: Sum(collateral) across FL/mezz/SEN legs conserves.

        Mirrors tests/fixtures/p1_30e/p1_30e.py: EAD=1,000,000, a=200,000,
        d=600,000, guarantee amount_covered=400,000 (protected width exactly
        fills [a, d)) -- the three tranche ratios (0.2 + 0.4 + 0.4) sum to 1.0,
        so collateral conservation is exact once the fix applies the same
        ratio already used for drawn_amount/ead_pre_crm to these columns.
        """
        # Arrange
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001"],
                "amount_covered": [400_000.0],
                "guarantor": ["GUAR001"],
                "attachment_amount": [200_000.0],
                "detachment_amount": [600_000.0],
            }
        )
        exposures = _exposure_with_collateral(ead=1_000_000.0)

        # Act
        result = _apply_guarantee_splits(guarantees, exposures).collect()

        # Assert: three-row split (first-loss, mezzanine guaranteed, senior)
        assert len(result) == 3
        total_re_value = result["collateral_re_value"].sum()
        assert total_re_value == pytest.approx(500_000.0, rel=1e-6)

    @pytest.mark.parametrize("column", STOCK_COLLATERAL_COLUMNS)
    def test_tranched_split_conserves_all_stock_collateral_columns(self, column: str) -> None:
        """Every collateral_*/crm_alloc_* carrier conserves across the 3-leg tranche split."""
        # Arrange
        guarantees = pl.LazyFrame(
            {
                "beneficiary_reference": ["EXP001"],
                "amount_covered": [400_000.0],
                "guarantor": ["GUAR001"],
                "attachment_amount": [200_000.0],
                "detachment_amount": [600_000.0],
            }
        )
        exposures = _exposure_with_collateral(ead=1_000_000.0)
        original_value = _COLLATERAL_VALUES[column]

        # Act
        result = _apply_guarantee_splits(guarantees, exposures).collect()

        # Assert
        assert len(result) == 3
        total = result[column].sum()
        assert total == pytest.approx(original_value, rel=1e-6)
