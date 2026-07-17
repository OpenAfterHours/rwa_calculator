"""
Unit tests for Art. 237(1)/(2)(b) maturity-mismatch ineligibility on GUARANTEES.

The guarantee maturity-mismatch step (`_apply_maturity_mismatch_to_guarantees`)
applies the Art. 239(3) scaling GA = G* x (t-0.25)/(T-0.25). P1.231 adds the two
eligibility gates the collateral sibling already enforces (haircuts.py), which
ZERO coverage rather than merely scaling it:

- Art. 237(1): credit protection with residual maturity < 3 months that is ALSO
  shorter than the exposure shall not be recognised. Tested on the RAW residuals
  (before the 0.25 floor) so a short exposure — whose T also floors to 0.25 and
  masks the mismatch under the scaling formula — no longer slips through.
- Art. 162(3)/237(2)(b): where the exposure is subject to the one-day IRB
  maturity floor (daily-margined repos/SFTs), ANY maturity mismatch makes the
  protection ineligible.

Both gates are regime-invariant (identical under CRR and PS1/26) and null-
PERMISSIVE (absent/null one-day-floor flag => False; null residuals => no gate).

References:
    CRR Art. 237(1): <3-month-and-shorter protection ineligibility.
    CRR Art. 162(3) / Art. 237(2)(b): one-day-floor exposures + any mismatch.
    CRR Art. 239(3): maturity-mismatch scaling (unchanged).
    tests/unit/crm/test_art237_ineligibility.py: the collateral sibling this
        mirrors.
    docs/plans/compliance-audit-crr-111-241-rectification.md §5 WS2, P1.231.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.crm.guarantees import _apply_maturity_mismatch_to_guarantees

# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------

_AMOUNT = 1000.0
_BENEFICIARY = "EXP001"


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))


def _guarantee(
    reporting_date: date,
    guar_maturity_days: int,
    *,
    original_maturity_years: float | None = None,
    include_original_column: bool = False,
) -> pl.LazyFrame:
    """One guarantee row covering _AMOUNT, maturing guar_maturity_days out.

    ``include_original_column`` adds the ``original_maturity_years`` column (Art.
    237(2)(a) original term); ``original_maturity_years`` sets its value (None =>
    null, permissive)."""
    data: dict = {
        "guarantee_reference": ["G1"],
        "beneficiary_reference": [_BENEFICIARY],
        "amount_covered": [_AMOUNT],
        "maturity_date": [reporting_date + timedelta(days=guar_maturity_days)],
    }
    schema: dict = {
        "guarantee_reference": pl.String,
        "beneficiary_reference": pl.String,
        "amount_covered": pl.Float64,
        "maturity_date": pl.Date,
    }
    if include_original_column or original_maturity_years is not None:
        data["original_maturity_years"] = [original_maturity_years]
        schema["original_maturity_years"] = pl.Float64
    return pl.LazyFrame(data, schema=schema)


def _exposure(
    reporting_date: date,
    exp_maturity_days: int | None,
    *,
    has_one_day_maturity_floor: bool | None = None,
    include_floor_column: bool = True,
) -> pl.LazyFrame:
    """One exposure row maturing exp_maturity_days out (None => null maturity_date),
    optional 1-day-floor flag."""
    maturity = reporting_date + timedelta(days=exp_maturity_days) if exp_maturity_days else None
    data: dict = {
        "exposure_reference": [_BENEFICIARY],
        "maturity_date": [maturity],
    }
    schema: dict = {"exposure_reference": pl.String, "maturity_date": pl.Date}
    if include_floor_column:
        data["has_one_day_maturity_floor"] = [has_one_day_maturity_floor]
        schema["has_one_day_maturity_floor"] = pl.Boolean
    return pl.LazyFrame(data, schema=schema)


def _covered(guar: pl.LazyFrame, exp: pl.LazyFrame, config: CalculationConfig) -> float:
    """Run the maturity-mismatch step and return the resulting amount_covered."""
    result = _apply_maturity_mismatch_to_guarantees(guar, exp, config).collect()
    return result["amount_covered"][0]


# ---------------------------------------------------------------------------
# Art. 162(3)/237(2)(b) — one-day maturity floor
# ---------------------------------------------------------------------------


class TestGuaranteeOneDayFloorIneligibility:
    """Art. 162(3)/237(2)(b): any mismatch on a one-day-floor exposure => zeroed."""

    def test_one_day_floor_with_mismatch_zeroed(self, crr_config: CalculationConfig) -> None:
        """DISCRIMINATING: 1-day-floor exposure (3y) + shorter guarantee (1y) => 0.

        Pre-fix the guarantee is merely scaled (~272); post-fix it is zeroed.
        """
        rd = crr_config.reporting_date
        covered = _covered(
            _guarantee(rd, 365),
            _exposure(rd, int(3 * 365.25), has_one_day_maturity_floor=True),
            crr_config,
        )
        assert covered == pytest.approx(0.0, abs=1e-9)

    def test_one_day_floor_false_allows_scaling(self, crr_config: CalculationConfig) -> None:
        """Control: floor=False + mismatch => normal 239(3) scaling (positive, reduced)."""
        rd = crr_config.reporting_date
        covered = _covered(
            _guarantee(rd, 365),
            _exposure(rd, int(3 * 365.25), has_one_day_maturity_floor=False),
            crr_config,
        )
        assert 0.0 < covered < _AMOUNT

    def test_one_day_floor_no_mismatch_not_checked(self, crr_config: CalculationConfig) -> None:
        """Control: floor=True but guarantee (5y) >= exposure (3y) => full coverage."""
        rd = crr_config.reporting_date
        covered = _covered(
            _guarantee(rd, int(5 * 365.25)),
            _exposure(rd, int(3 * 365.25), has_one_day_maturity_floor=True),
            crr_config,
        )
        assert covered == pytest.approx(_AMOUNT)

    def test_null_floor_defaults_false(self, crr_config: CalculationConfig) -> None:
        """Null 1-day-floor flag is permissive (=> False) => normal scaling."""
        rd = crr_config.reporting_date
        covered = _covered(
            _guarantee(rd, 365),
            _exposure(rd, int(3 * 365.25), has_one_day_maturity_floor=None),
            crr_config,
        )
        assert 0.0 < covered < _AMOUNT

    def test_missing_floor_column_defaults_permissive(self, crr_config: CalculationConfig) -> None:
        """Absent 1-day-floor column => no gate applied (backward compatible)."""
        rd = crr_config.reporting_date
        covered = _covered(
            _guarantee(rd, 365),
            _exposure(rd, int(3 * 365.25), include_floor_column=False),
            crr_config,
        )
        assert 0.0 < covered < _AMOUNT

    def test_b31_same_one_day_floor_check(self, b31_config: CalculationConfig) -> None:
        """Art. 162(3)/237(2)(b) applies identically under Basel 3.1."""
        rd = b31_config.reporting_date
        covered = _covered(
            _guarantee(rd, 365),
            _exposure(rd, int(3 * 365.25), has_one_day_maturity_floor=True),
            b31_config,
        )
        assert covered == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Art. 237(1) — <3-month-and-shorter protection (masked short-exposure case)
# ---------------------------------------------------------------------------


class TestGuaranteeShortProtectionIneligibility:
    """Art. 237(1): protection residual < 3 months AND shorter than exposure => zeroed."""

    def test_short_protection_masked_by_short_exposure_zeroed(
        self, crr_config: CalculationConfig
    ) -> None:
        """DISCRIMINATING: guarantee 40d (~0.107y), exposure 80d (~0.216y) => 0.

        Both raw residuals are < 0.25 so they floor to 0.25 and the scaling
        formula's mismatch test (0.25 < 0.25) is FALSE — pre-fix this returns
        full coverage (1000). The explicit raw-value 237(1) gate zeroes it.
        """
        rd = crr_config.reporting_date
        covered = _covered(_guarantee(rd, 40), _exposure(rd, 80), crr_config)
        assert covered == pytest.approx(0.0, abs=1e-9)

    def test_short_protection_long_exposure_still_zeroed(
        self, crr_config: CalculationConfig
    ) -> None:
        """Control: guarantee 40d, exposure 3y => 0 (already zeroed by the scale
        formula pre-fix; the explicit gate keeps it 0, i.e. no regression)."""
        rd = crr_config.reporting_date
        covered = _covered(_guarantee(rd, 40), _exposure(rd, int(3 * 365.25)), crr_config)
        assert covered == pytest.approx(0.0, abs=1e-9)

    def test_short_protection_not_shorter_than_exposure_full(
        self, crr_config: CalculationConfig
    ) -> None:
        """Control: guarantee 80d, exposure 40d — protection LONGER than the
        exposure (no mismatch) => full coverage, even though both are < 3 months."""
        rd = crr_config.reporting_date
        covered = _covered(_guarantee(rd, 80), _exposure(rd, 40), crr_config)
        assert covered == pytest.approx(_AMOUNT)

    def test_t_02_long_exposure_yields_zero(self, crr_config: CalculationConfig) -> None:
        """t ~= 0.2 (< 3 months), T = 5y => ZERO benefit.

        The 0.25 GA-floor already zeroes this pre-fix (scale = (0.25-0.25)/(5-0.25)
        = 0); the explicit Art. 237(1) gate keeps it 0. Confirms the headline
        "sub-3-month protection is not recognised" contract regardless of the
        floor interaction (t=74d ~= 0.2y, exposure 5y)."""
        rd = crr_config.reporting_date
        covered = _covered(_guarantee(rd, 74), _exposure(rd, int(5 * 365.25)), crr_config)
        assert covered == pytest.approx(0.0, abs=1e-9)

    def test_t_02_outlives_shorter_exposure_recognised(self, crr_config: CalculationConfig) -> None:
        """t ~= 0.2 protection OUTLIVES a shorter exposure (T ~= 0.15) => recognised.

        No maturity mismatch (t >= T), so neither the 237(1) gate nor the scaling
        fires — full coverage is retained even though the protection is itself
        < 3 months (t=74d ~= 0.2y, exposure 55d ~= 0.15y)."""
        rd = crr_config.reporting_date
        covered = _covered(_guarantee(rd, 74), _exposure(rd, 55), crr_config)
        assert covered == pytest.approx(_AMOUNT)

    def test_b31_same_short_protection_check(self, b31_config: CalculationConfig) -> None:
        """Art. 237(1) applies identically under Basel 3.1."""
        rd = b31_config.reporting_date
        covered = _covered(_guarantee(rd, 40), _exposure(rd, 80), b31_config)
        assert covered == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Regression — the Art. 239(3) scaling itself is unchanged
# ---------------------------------------------------------------------------


class TestGuaranteeScalingUnchanged:
    """The 239(3) formula must still produce its usual values when no gate fires."""

    def test_cvam_formula_unchanged(self, crr_config: CalculationConfig) -> None:
        """Guarantee 2y, exposure 3y, no floor => scaling ~0.636 (unchanged)."""
        rd = crr_config.reporting_date
        covered = _covered(
            _guarantee(rd, int(2 * 365.25)),
            _exposure(rd, int(3 * 365.25), has_one_day_maturity_floor=False),
            crr_config,
        )
        # (t - 0.25)/(T - 0.25) with t ~= 2.0, T ~= 3.0 => ~0.636.
        assert covered == pytest.approx(_AMOUNT * (2.0 - 0.25) / (3.0 - 0.25), rel=1e-2)

    def test_no_mismatch_full_coverage(self, crr_config: CalculationConfig) -> None:
        """Guarantee 3y >= exposure 3y => no mismatch => full coverage."""
        rd = crr_config.reporting_date
        covered = _covered(
            _guarantee(rd, int(3 * 365.25)),
            _exposure(rd, int(3 * 365.25), has_one_day_maturity_floor=False),
            crr_config,
        )
        assert covered == pytest.approx(_AMOUNT)


# ---------------------------------------------------------------------------
# Null / join-miss exposure maturity defaults to a 5y exposure (twin alignment)
# ---------------------------------------------------------------------------


class TestGuaranteeNullExposureMaturity:
    """A null exposure maturity_date is treated as a 5y exposure, so the gates
    and the 239(3) scaling still bind (aligns with the collateral twin's 5y
    default; without it both gates silently no-op on null-T)."""

    def test_one_day_floor_null_exposure_maturity_zeroed(
        self, crr_config: CalculationConfig
    ) -> None:
        """DISCRIMINATING: one-day-floor exposure with NULL maturity_date + a
        shorter (1y) guarantee => 0. Null T defaults to 5y, so t=1 < 5 is a
        mismatch and Art. 237(2)(b) zeroes it.

        Pre-fix (null T not defaulted): raw_mismatch is False => full coverage.
        """
        rd = crr_config.reporting_date
        covered = _covered(
            _guarantee(rd, 365),
            _exposure(rd, None, has_one_day_maturity_floor=True),
            crr_config,
        )
        assert covered == pytest.approx(0.0, abs=1e-9)

    def test_null_exposure_maturity_scales_against_5y(self, crr_config: CalculationConfig) -> None:
        """Control: non-floor exposure with NULL maturity_date + 2y guarantee =>
        scaled against T = 5y => 1000·(2-0.25)/(5-0.25) ~= 368.42."""
        rd = crr_config.reporting_date
        covered = _covered(
            _guarantee(rd, int(2 * 365.25)),
            _exposure(rd, None, has_one_day_maturity_floor=False),
            crr_config,
        )
        assert covered == pytest.approx(_AMOUNT * (2.0 - 0.25) / (5.0 - 0.25), rel=1e-2)

    def test_b31_one_day_floor_null_exposure_maturity_zeroed(
        self, b31_config: CalculationConfig
    ) -> None:
        """Basel 3.1: the null-T 5y default binds identically."""
        rd = b31_config.reporting_date
        covered = _covered(
            _guarantee(rd, 365),
            _exposure(rd, None, has_one_day_maturity_floor=True),
            b31_config,
        )
        assert covered == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Art. 237(2)(a) — original maturity < 1y, ONLY where a mismatch exists (P1.232)
# ---------------------------------------------------------------------------


class TestGuaranteeShortOriginalMaturity:
    """Art. 237(2)(a): a guarantee whose ORIGINAL maturity is < 1 year is
    ineligible ONLY where a maturity mismatch exists (Art. 237(2) chapeau).
    Matched / protection-outlives-exposure short-dated guarantees stay
    recognised. Null original maturity is PERMISSIVE (P1.10)."""

    def test_short_original_mismatch_zeroed(self, crr_config: CalculationConfig) -> None:
        """DISCRIMINATING: 1y guarantee, original 0.75y, exposure 3y (mismatch) => 0.

        Pre-fix the maturity-mismatch step only scales (~272); the relocated
        Art. 237(2)(a) gate zeroes it because a mismatch exists and original < 1y.
        """
        rd = crr_config.reporting_date
        covered = _covered(
            _guarantee(rd, 365, original_maturity_years=0.75),
            _exposure(rd, int(3 * 365.25)),
            crr_config,
        )
        assert covered == pytest.approx(0.0, abs=1e-9)

    def test_matched_short_original_recognised(self, crr_config: CalculationConfig) -> None:
        """Control: 1y guarantee == 1y exposure (NO mismatch), original 0.75y =>
        full coverage. The <1y-original test must NOT bind without a mismatch."""
        rd = crr_config.reporting_date
        covered = _covered(
            _guarantee(rd, 365, original_maturity_years=0.75),
            _exposure(rd, 365),
            crr_config,
        )
        assert covered == pytest.approx(_AMOUNT)

    def test_outlives_short_original_recognised(self, crr_config: CalculationConfig) -> None:
        """Control: 9m guarantee (original 0.75y) OUTLIVES a 6m exposure (t>=T, no
        mismatch) => full coverage, even though original maturity < 1y."""
        rd = crr_config.reporting_date
        covered = _covered(
            _guarantee(rd, 274, original_maturity_years=0.75),
            _exposure(rd, 183),
            crr_config,
        )
        assert covered == pytest.approx(_AMOUNT)

    def test_null_original_mismatch_permissive(self, crr_config: CalculationConfig) -> None:
        """Control: mismatch present but original maturity NULL => permissive (the
        2(a) gate does not fire); the guarantee is scaled by Art. 239(3), not
        zeroed (1y guarantee, 3y exposure => ~0.27)."""
        rd = crr_config.reporting_date
        covered = _covered(
            _guarantee(rd, 365, original_maturity_years=None, include_original_column=True),
            _exposure(rd, int(3 * 365.25)),
            crr_config,
        )
        assert 0.0 < covered < _AMOUNT

    def test_b31_short_original_mismatch_zeroed(self, b31_config: CalculationConfig) -> None:
        """Basel 3.1: the relocated Art. 237(2)(a) gate binds identically."""
        rd = b31_config.reporting_date
        covered = _covered(
            _guarantee(rd, 365, original_maturity_years=0.75),
            _exposure(rd, int(3 * 365.25)),
            b31_config,
        )
        assert covered == pytest.approx(0.0, abs=1e-9)
