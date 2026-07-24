"""
Tests for the blended (LGD*) A-IRB LGD floor for exposures with collateral.

Both limbs of the Basel 3.1 A-IRB LGD input floor use the same Art. 230/231
LGD* shape — a weighted average of per-type LGDS floors and the unsecured LGDU,
using the proportion of the Art. 230(1) exposure basis E' = E × (1 + HE)
absorbed by each collateral type from the Art. 231 waterfall:

    LGD_floor = (E_unsecured / E') × LGDU + Σ_i (E_i / E') × LGDS_i

E is ``ead_for_crm``, the CCF=100% exposure value (Art. 223(4)), NOT the
post-CCF ``ead_gross`` — see ``TestArt2301ExposureBasisDenominator``.

Where:
    LGDU = 25% corporate / institution (Art. 161(5)(b)(iii)),
           30% retail_other, 50% retail_qrre (Art. 164(4)(b)(i)/(c))
    LGDS: financial=0%, receivables=10%, real_estate=10%, other_physical=15%

``retail_mortgage`` is the sole carve-out — Art. 164(4)(a) gives it a flat 5%
floor regardless of collateral composition.

References:
    PRA PS1/26 Art. 161(5)(b) — corporates and institutions (P1.248)
    PRA PS1/26 Art. 164(4)(c) — retail
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb.formulas import (
    _lgd_floor_blended_expression,
)
from rwa_calc.engine.irb.transforms import (
    apply_lgd_floor,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df(
    *,
    ead_gross: float = 100_000.0,
    ead_for_crm: float | None = None,
    exposure_volatility_haircut: float = 0.0,
    exposure_class: str = "retail_other",
    crm_alloc_financial: float = 0.0,
    crm_alloc_covered_bond: float = 0.0,
    crm_alloc_receivables: float = 0.0,
    crm_alloc_real_estate: float = 0.0,
    crm_alloc_other_physical: float = 0.0,
    crm_alloc_life_insurance: float = 0.0,
    total_collateral_for_lgd: float | None = None,
) -> pl.LazyFrame:
    """Build a minimal LazyFrame with allocation columns for testing.

    ``ead_for_crm`` defaults to ``ead_gross`` — the pure on-balance-sheet case
    where the Art. 223(4) CCF=100% basis and the post-CCF EAD coincide. Pass it
    explicitly (> ``ead_gross``) to model an off-balance-sheet row whose CCF is
    below 100%; the Art. 231 waterfall allocates against ``ead_for_crm``, so
    ``total_collateral_for_lgd`` is capped there and not at ``ead_gross``.
    """
    if ead_for_crm is None:
        ead_for_crm = ead_gross
    total = (
        crm_alloc_financial
        + crm_alloc_covered_bond
        + crm_alloc_receivables
        + crm_alloc_real_estate
        + crm_alloc_other_physical
        + crm_alloc_life_insurance
    )
    if total_collateral_for_lgd is None:
        total_collateral_for_lgd = min(total, ead_for_crm)
    return pl.LazyFrame(
        {
            "ead_gross": [ead_gross],
            "ead_for_crm": [ead_for_crm],
            "exposure_volatility_haircut": [exposure_volatility_haircut],
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
        assert result["floor"][0] == pytest.approx(0.0, abs=1e-10)

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

    @pytest.mark.parametrize("exposure_class", ["CORPORATE", "corporate_sme", "institution"])
    def test_corporate_and_institution_partially_secured_blend(self, exposure_class):
        """Art. 161(5)(b): 80% financial + 20% unsecured = 0.8*0% + 0.2*25% = 5%."""
        lf = _make_df(
            exposure_class=exposure_class,
            crm_alloc_financial=80_000.0,
        )
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.05)

    def test_corporate_lgdu_is_25pct_not_retail_30pct(self):
        """Corporate LGDU is 25% (Art. 161(5)(b)(iii)), not the retail 30%."""
        # 60% other_physical + 40% unsecured = 0.6*15% + 0.4*25% = 19%
        # (the retail_other answer for the same shape would be 21%)
        lf = _make_df(
            exposure_class="corporate",
            crm_alloc_other_physical=60_000.0,
        )
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.19)

    def test_corporate_fully_secured_equals_single_type_lgds(self):
        """Fully secured corporate: blend collapses onto the bare LGDS."""
        lf = _make_df(
            exposure_class="corporate",
            crm_alloc_real_estate=100_000.0,
        )
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.10)

    def test_corporate_no_collateral_returns_null(self):
        """Art. 161(5)(a): no recognised protection → null (flat 25% fallback)."""
        lf = _make_df(exposure_class="corporate")
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] is None

    def test_corporate_multi_type_blend(self):
        """Art. 231 multi-collateral: 30% fin + 30% RE + 20% phys + 20% unsecured."""
        lf = _make_df(
            exposure_class="corporate",
            crm_alloc_financial=30_000.0,
            crm_alloc_real_estate=30_000.0,
            crm_alloc_other_physical=20_000.0,
        )
        # 0.3*0% + 0.3*10% + 0.2*15% + 0.2*25% = 0% + 3% + 3% + 5% = 11%
        result = lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.11)

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
                "ead_for_crm": [0.0],
                "exposure_volatility_haircut": [0.0],
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
        # Waterfall caps allocations at EAD, so test with capped values.
        lf2 = _make_df(
            crm_alloc_other_physical=100_000.0,
            total_collateral_for_lgd=100_000.0,
        )
        result = lf2.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()
        assert result["floor"][0] == pytest.approx(0.15)


class TestArt2301ExposureBasisDenominator:
    """Art. 230(1): the LGD* weights are shares of E' = E × (1 + HE).

    E is ``ead_for_crm`` — the CCF=100% exposure value (Art. 223(4)) — so an
    off-balance-sheet row with CCF < 100% has ead_gross < ead_for_crm. Dividing
    by ``ead_gross`` was wrong in BOTH directions, the sign turning on whether
    the recognised collateral C fits inside ead_gross (G):

    - ``C <= G``: over-weights the secured share, and since every LGDS
      (0/10/10/15%) is below every LGDU (25/30/50%) the floor lands BELOW the
      mandated value (anti-conservative). The common case, and the reason for
      the fix — ``test_denominator_is_ead_for_crm_not_ead_gross``.
    - ``C > G``: the unsecured weight clipped to zero, leaving the floor ABOVE
      the mandated value and not a convex combination at all — see
      ``test_weights_stay_convex_when_fully_collateralised``, where the old
      denominator returned 0.375, above even the 25% LGDU ceiling.

    Reference case — undrawn committed facility, nominal 1,000,000, CCF 40%
    (ead_gross 400,000), 200,000 eligible cash recognised:
        Art. 230(1): (0 × 200,000 + 25% × 800,000) / 1,000,000 = 20.0%
        ead_gross:   (0 × 200,000 + 25% × 200,000) /   400,000 = 12.5%
    """

    _NOMINAL = 1_000_000.0
    _CCF = 0.40
    _EAD_GROSS = 400_000.0  # _NOMINAL × _CCF
    _CASH = 200_000.0
    _EXPECTED = 0.20  # (1,000,000 - 200,000) × 25% / 1,000,000
    _PRE_FIX = 0.125  # the ead_gross-denominator answer

    def _obs_row(self, **kwargs) -> pl.LazyFrame:
        """The reference off-balance-sheet corporate row."""
        return _make_df(
            ead_gross=self._EAD_GROSS,
            ead_for_crm=self._NOMINAL,
            exposure_class="corporate",
            crm_alloc_financial=self._CASH,
            total_collateral_for_lgd=self._CASH,
            **kwargs,
        )

    def _floor(self, lf: pl.LazyFrame) -> float:
        return lf.with_columns(_lgd_floor_blended_expression(B31).alias("floor")).collect()[
            "floor"
        ][0]

    def test_denominator_is_ead_for_crm_not_ead_gross(self) -> None:
        """
        Art. 230(1) / 223(4): E is the CCF=100% basis, not the post-CCF EAD.

        Arrange: corporate A-IRB commitment, nominal 1,000,000 at CCF 40%
                 (ead_gross 400,000), 200,000 cash recognised by the waterfall.
        Act:     evaluate the blended floor expression.
        Assert:  20.0% — 25% LGDU on the 800,000 unsecured share of the
                 1,000,000 basis. Fails at 12.5% against an ead_gross divisor.
        """
        actual = self._floor(self._obs_row())

        assert actual == pytest.approx(self._EXPECTED, rel=1e-12), (
            f"Art. 230(1) floor must divide by ead_for_crm × (1 + HE) = "
            f"{self._NOMINAL:,.0f}, giving {self._EXPECTED:.4f}; got {actual:.6f} "
            f"({'the ead_gross denominator' if actual == pytest.approx(self._PRE_FIX) else 'neither basis'})"
        )

    def test_floor_is_not_the_ead_gross_under_floor(self) -> None:
        """
        Anti-confound: the corrected floor is not the pre-fix under-floor.

        Arrange: the same commitment row.
        Act:     evaluate the blended floor.
        Assert:  strictly above the 12.5% that the ead_gross denominator gave,
                 and still at or below the 25% LGDU ceiling — so neither the
                 old divisor nor a "just use LGDU" shortcut passes.
        """
        actual = self._floor(self._obs_row())

        assert actual > self._PRE_FIX, (
            f"floor must exceed the anti-conservative ead_gross answer "
            f"{self._PRE_FIX:.3f}, got {actual:.6f}"
        )
        assert actual < 0.25, (
            f"floor must stay below the flat LGDU 25% — part of the exposure is "
            f"secured, got {actual:.6f}"
        )

    def test_volatility_haircut_grosses_up_the_basis(self) -> None:
        """
        Art. 230(1): HE is applied to the exposure basis, E' = E × (1 + HE).

        Arrange: same row with exposure_volatility_haircut = 25%, so
                 E' = 1,000,000 × 1.25 = 1,250,000.
        Act:     evaluate the blended floor.
        Assert:  (1,250,000 - 200,000) × 25% / 1,250,000 = 21.0% — strictly
                 above the HE = 0 answer, so the (1 + HE) factor is not a
                 silent no-op.
        """
        actual = self._floor(self._obs_row(exposure_volatility_haircut=0.25))

        assert actual == pytest.approx(0.21, rel=1e-12), (
            f"HE = 25% must gross the basis to 1,250,000, giving 21.0%; got {actual:.6f}"
        )
        assert actual > self._EXPECTED, (
            "grossing up the basis must raise the floor (the unsecured share grows)"
        )

    def test_zero_haircut_leaves_the_basis_unchanged(self) -> None:
        """
        HE = 0 is the identity: E' == E for every non-SFT row.

        Arrange: the reference row with HE = 0 and the same row with HE unset.
        Act:     evaluate both.
        Assert:  identical — the gross-up only bites where HE > 0.
        """
        assert self._floor(self._obs_row(exposure_volatility_haircut=0.0)) == pytest.approx(
            self._EXPECTED, rel=1e-12
        )

    def test_on_balance_sheet_row_is_unaffected(self) -> None:
        """
        Regression guard: ead_for_crm == ead_gross leaves the blend unchanged.

        Arrange: a fully drawn (on-balance-sheet) retail_other row, 60% other
                 physical, where the two EAD bases coincide by construction.
        Act:     evaluate the blended floor.
        Assert:  21% — the pre-existing answer. The denominator fix must move
                 only off-balance-sheet rows.
        """
        actual = self._floor(_make_df(crm_alloc_other_physical=60_000.0))

        assert actual == pytest.approx(0.21, rel=1e-12), (
            f"on-BS blend must stay at 0.6 × 15% + 0.4 × 30% = 21%, got {actual:.6f}"
        )

    def test_retail_other_off_balance_sheet_row_also_moves(self) -> None:
        """
        The same correction applies to the retail limb (Art. 164(4)(c)).

        Arrange: retail_other commitment, nominal 100,000 at CCF 40%
                 (ead_gross 40,000), 20,000 other physical recognised.
        Act:     evaluate the blended floor.
        Assert:  0.2 × 15% + 0.8 × 30% = 27% on the Art. 230(1) basis (the
                 ead_gross divisor gave 0.5 × 15% + 0.5 × 30% = 22.5%).
        """
        lf = _make_df(
            ead_gross=40_000.0,
            ead_for_crm=100_000.0,
            exposure_class="retail_other",
            crm_alloc_other_physical=20_000.0,
            total_collateral_for_lgd=20_000.0,
        )

        actual = self._floor(lf)

        assert actual == pytest.approx(0.27, rel=1e-12), (
            f"retail_other OBS blend must be 27% on the 100,000 basis, got {actual:.6f}"
        )
        assert actual != pytest.approx(0.225, rel=1e-9), (
            "22.5% is the ead_gross-denominator answer — the fix must move off it"
        )

    def test_weights_stay_convex_when_fully_collateralised(self) -> None:
        """
        Convexity: collateral capped at the basis gives weights summing to 1.

        Arrange: an OBS row whose recognised collateral equals ead_for_crm (the
                 Art. 231 waterfall cap), all other physical.
        Act:     evaluate the blended floor.
        Assert:  exactly the 15% LGDS — the unsecured weight clipped to zero and
                 the secured weight is 1.0, never above it.
        """
        lf = _make_df(
            ead_gross=400_000.0,
            ead_for_crm=1_000_000.0,
            exposure_class="corporate",
            crm_alloc_other_physical=1_000_000.0,
            total_collateral_for_lgd=1_000_000.0,
        )

        actual = self._floor(lf)

        assert actual == pytest.approx(0.15, rel=1e-12), (
            f"a fully collateralised row must collapse onto LGDS = 15%, got {actual:.6f}"
        )


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
        ead_for_crm: float | None = None,
        total_collateral_for_lgd: float | None = None,
        collateral_type: str | None = "other_physical",
    ) -> pl.LazyFrame:
        if ead_for_crm is None:
            ead_for_crm = ead_gross
        total = crm_alloc_financial + crm_alloc_other_physical
        if total_collateral_for_lgd is None:
            total_collateral_for_lgd = min(total, ead_for_crm)
        return pl.LazyFrame(
            {
                "lgd": [lgd],
                "lgd_input": [lgd],
                "exposure_class": [exposure_class],
                "is_airb": [is_airb],
                "ead_gross": [ead_gross],
                "ead_for_crm": [ead_for_crm],
                "exposure_volatility_haircut": [0.0],
                "total_collateral_for_lgd": [total_collateral_for_lgd],
                "crm_alloc_financial": [crm_alloc_financial],
                "crm_alloc_covered_bond": [0.0],
                "crm_alloc_receivables": [0.0],
                "crm_alloc_real_estate": [0.0],
                "crm_alloc_other_physical": [crm_alloc_other_physical],
                "crm_alloc_life_insurance": [0.0],
            }
        ).with_columns(pl.lit(collateral_type, dtype=pl.String).alias("collateral_type"))

    def test_airb_retail_other_blended_floor_applied(self):
        """A-IRB retail_other gets blended floor, not single-type."""
        # 60% physical + 40% unsecured → blended floor = 0.6*15% + 0.4*30% = 21%
        # Institution LGD estimate = 10% (below floor)
        lf = self._make_irb_df(
            lgd=0.10,
            crm_alloc_other_physical=60_000.0,
        )
        result = lf.pipe(apply_lgd_floor, B31).collect()
        # Without blended: single-type floor would be 15% (other_physical)
        # With blended: floor is 21%
        assert result["lgd_floored"][0] == pytest.approx(0.21)

    def test_airb_retail_other_lgd_above_blended_floor(self):
        """A-IRB retail_other with LGD above blended floor: no change."""
        lf = self._make_irb_df(
            lgd=0.35,
            crm_alloc_other_physical=60_000.0,
        )
        result = lf.pipe(apply_lgd_floor, B31).collect()
        # Blended floor = 21%, LGD = 35% > 21%, so lgd_floored = 35%
        assert result["lgd_floored"][0] == pytest.approx(0.35)

    def test_firb_not_floored(self):
        """F-IRB supervisory LGD is not subject to LGD floor."""
        lf = self._make_irb_df(
            lgd=0.10,
            is_airb=False,
            crm_alloc_other_physical=60_000.0,
        )
        result = lf.pipe(apply_lgd_floor, B31).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.10)

    def test_crr_no_floor(self):
        """CRR: No LGD floors at all."""
        lf = self._make_irb_df(
            lgd=0.10,
            crm_alloc_other_physical=60_000.0,
        )
        result = lf.pipe(apply_lgd_floor, CRR).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.10)

    def test_corporate_uses_blended_floor(self):
        """A-IRB corporate gets the Art. 161(5)(b) blend, not the single-type floor."""
        lf = self._make_irb_df(
            lgd=0.10,
            exposure_class="CORPORATE",
            crm_alloc_other_physical=60_000.0,
        )
        result = lf.pipe(apply_lgd_floor, B31).collect()
        # Blended: 0.6*15% + 0.4*25% = 19% (single-type would be 15%; the
        # collateral-free flat floor would be 25%)
        assert result["lgd_floored"][0] == pytest.approx(0.19)

    def test_corporate_without_collateral_keeps_flat_25pct(self):
        """Art. 161(5)(a): corporate with no recognised protection stays at 25%."""
        lf = self._make_irb_df(lgd=0.10, exposure_class="CORPORATE", collateral_type=None)
        result = lf.pipe(apply_lgd_floor, B31).collect()
        assert result["lgd_floored"][0] == pytest.approx(0.25)

    def test_retail_mortgage_uses_flat_floor(self):
        """retail_mortgage uses flat 5% floor (Art. 164(4)(a)), not blended."""
        lf = pl.LazyFrame(
            {
                "lgd": [0.02],
                "lgd_input": [0.02],
                "exposure_class": ["retail_mortgage"],
                "is_airb": [True],
                "ead_gross": [100_000.0],
                "ead_for_crm": [100_000.0],
                "exposure_volatility_haircut": [0.0],
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
        result = lf.pipe(apply_lgd_floor, B31).collect()
        # retail_mortgage → flat 5% floor for RRE collateral
        assert result["lgd_floored"][0] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Tests: CRM allocation columns preserved
# ---------------------------------------------------------------------------


class TestCRMAllocColumnsPreserved:
    """Verify that crm_alloc_* columns survive the CRM pipeline."""

    def test_allocation_column_names(self):
        """CRM_ALLOC_COLUMNS mapping covers all waterfall types."""
        from rwa_calc.engine.crm.expressions import CRM_ALLOC_COLUMNS, WATERFALL_ORDER

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
                "ead_for_crm": [100_000.0],
                "exposure_volatility_haircut": [0.0],
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
