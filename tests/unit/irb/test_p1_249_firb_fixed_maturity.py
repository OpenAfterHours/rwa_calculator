"""
P1.249 — CRR Art. 162(1) fixed F-IRB supervisory maturity for NON-repo-style exposures.

CRR Art. 162(1) first sentence: an institution that has **not** received permission to
use own LGDs and own conversion factors for exposures to corporates, institutions or
central governments and central banks "shall assign to exposures arising from
repurchase transactions or securities or commodities lending or borrowing transactions
a maturity value (M) of 0,5 years and to all other exposures M of 2,5 years".

Art. 162(1) second sentence: "Alternatively, as part of the permission referred to in
Article 143, the competent authorities shall decide on whether the institution shall
use maturity (M) for each exposure as set out under paragraph 2" — i.e. the
date-derived Art. 162(2) M is available only where the firm's Art. 143 permission says
so. The engine's historic behaviour is that second-sentence alternative for every
F-IRB row; the fixed 2.5y first-sentence treatment had no route at all (only its 0.5y
repo-style limb was implemented).

The election is therefore a firm-permission fact, not a regime fact: it lives on
``CalculationConfig.firb_fixed_maturity`` (default False, so today's date-derived M is
unmoved), gated by the CRR-only pack Feature ``firb_fixed_supervisory_maturity``
(Basel 3.1 left Art. 162(1) blank — verified ps126app1.pdf Art. 162(1)
"[Note: Provision left blank]" — so the election is inert under B31).

References:
- CRR Art. 162(1): fixed supervisory M — 0.5y repo-style, 2.5y all other exposures
- CRR Art. 162(2): per-exposure date-derived M (own-LGD/CF permission)
- CRR Art. 162(3): one-day M floor — outranks the fixed values in the engine chain
- PS1/26 Art. 162(1): provision left blank (Basel 3.1 deleted it)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.contract_columns import pad_crm_exit_defaults as _pad

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb.transforms import classify_approach, prepare_columns

_ONE_DAY = 1.0 / 365.0

# reporting_date 2025-12-31 → maturity_date 2027-12-31 is exactly 2.0y under the
# engine's /365 ordinal-day year fraction, safely clear of both 0.5y and 2.5y.
_CRR_REPORTING_DATE = date(2025, 12, 31)
_CRR_MATURITY_DATE = date(2027, 12, 31)
_DATE_DERIVED_M = 2.0

# Same 2.0y separation under a post-2027 B31 reporting date.
_B31_REPORTING_DATE = date(2027, 12, 31)
_B31_MATURITY_DATE = date(2029, 12, 31)


def _crr_config(*, firb_fixed_maturity: bool = False) -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=_CRR_REPORTING_DATE,
        firb_fixed_maturity=firb_fixed_maturity,
    )


def _b31_config(*, firb_fixed_maturity: bool = False) -> CalculationConfig:
    from dataclasses import replace

    # basel_3_1() deliberately has no election kwarg (the Feature is off under B31);
    # replace() proves the field cannot leak into the B31 chain either way.
    return replace(
        CalculationConfig.basel_3_1(reporting_date=_B31_REPORTING_DATE),
        firb_fixed_maturity=firb_fixed_maturity,
    )


def _irb_frame(
    *,
    approach: str = "foundation_irb",
    maturity_date: date | None = _CRR_MATURITY_DATE,
    is_sft: bool = False,
    risk_type: str | None = None,
    effective_maturity: float | None = None,
    has_one_day_maturity_floor: bool = False,
) -> pl.LazyFrame:
    """Minimal IRB exposure frame for maturity-only assertions."""
    lf = pl.LazyFrame(
        {
            "exposure_reference": ["EXP_P1249"],
            "pd": [0.01],
            "lgd": [0.45],
            "ead_final": [1_000_000.0],
            "exposure_class": ["CORPORATE"],
            "approach": [approach],
            "is_sft": [is_sft],
            "has_one_day_maturity_floor": [has_one_day_maturity_floor],
        }
    )
    lf = lf.with_columns(pl.Series("maturity_date", [maturity_date], dtype=pl.Date))
    if risk_type is not None:
        lf = lf.with_columns(pl.lit(risk_type).alias("risk_type"))
    if effective_maturity is not None:
        lf = lf.with_columns(pl.lit(effective_maturity).alias("effective_maturity"))
    return _pad(lf)


def _maturity(lf: pl.LazyFrame, config: CalculationConfig) -> float:
    result = lf.pipe(classify_approach, config).pipe(prepare_columns, config).collect()
    return result["maturity"][0]


class TestFIRBFixedMaturityElectionOn:
    """CRR Art. 162(1) first sentence, under the Art. 143 permission election."""

    def test_firb_non_sft_pinned_to_two_and_a_half_years(self) -> None:
        # Arrange — F-IRB corporate whose date-derived M would be 2.0y
        lf = _irb_frame()

        # Act
        m = _maturity(lf, _crr_config(firb_fixed_maturity=True))

        # Assert — Art. 162(1) "all other exposures M of 2,5 years"
        assert m == pytest.approx(2.5)

    def test_firb_derivative_is_an_other_exposure_at_two_and_a_half_years(self) -> None:
        # Arrange — Art. 162(1) carves out repo-style ONLY; derivatives are "other"
        lf = _irb_frame(risk_type="CCR_DERIVATIVE")

        # Act
        m = _maturity(lf, _crr_config(firb_fixed_maturity=True))

        # Assert
        assert m == pytest.approx(2.5)

    def test_firb_repo_style_sft_keeps_half_a_year(self) -> None:
        # Arrange — repo-style limb of the same sentence
        lf = _irb_frame(is_sft=True)

        # Act
        m = _maturity(lf, _crr_config(firb_fixed_maturity=True))

        # Assert — 0.5y, NOT the 2.5y "all other exposures" value
        assert m == pytest.approx(0.5)

    def test_firb_synthetic_ccr_sft_keeps_half_a_year(self) -> None:
        # Arrange — synthetic FCCM SFT rows never carry is_sft
        lf = _irb_frame(risk_type="CCR_SFT")

        # Act
        m = _maturity(lf, _crr_config(firb_fixed_maturity=True))

        # Assert
        assert m == pytest.approx(0.5)

    def test_airb_unaffected_by_the_election(self) -> None:
        # Arrange — Art. 162(1) binds only firms without own-LGD/CF permission
        lf = _irb_frame(approach="advanced_irb")

        # Act
        m = _maturity(lf, _crr_config(firb_fixed_maturity=True))

        # Assert — date-derived Art. 162(2) M survives
        assert m == pytest.approx(_DATE_DERIVED_M)

    def test_firm_supplied_effective_maturity_still_outranks_the_fixed_value(self) -> None:
        # Arrange — highest rung of the documented maturity priority chain
        lf = _irb_frame(effective_maturity=4.0)

        # Act
        m = _maturity(lf, _crr_config(firb_fixed_maturity=True))

        # Assert
        assert m == pytest.approx(4.0)

    def test_one_day_floor_still_outranks_the_fixed_value(self) -> None:
        # Arrange — Art. 162(3) carve-out sits above the fixed values in the chain
        lf = _irb_frame(has_one_day_maturity_floor=True)

        # Act
        m = _maturity(lf, _crr_config(firb_fixed_maturity=True))

        # Assert
        assert m == pytest.approx(_ONE_DAY)


class TestFIRBFixedMaturityElectionOff:
    """Default (no election): the Art. 162(2) date-derived M is unmoved."""

    def test_firb_non_sft_keeps_date_derived_maturity_by_default(self) -> None:
        # Arrange
        lf = _irb_frame()

        # Act
        m = _maturity(lf, _crr_config())

        # Assert — today's behaviour: residual 2.0y clipped into [1, 5]
        assert m == pytest.approx(_DATE_DERIVED_M)

    def test_firb_long_dated_still_clips_at_five_years_by_default(self) -> None:
        # Arrange — residual ≈ 9y
        lf = _irb_frame(maturity_date=date(2034, 12, 31))

        # Act
        m = _maturity(lf, _crr_config())

        # Assert — Art. 162(2) five-year cap, not the fixed 2.5y
        assert m == pytest.approx(5.0)

    def test_null_maturity_date_uses_the_fallback_default_not_the_election(self) -> None:
        """Null ``maturity_date``, election OFF → the 2.5y *fallback* default still applies.

        The fallback default (last rung of the maturity chain) and the elected Art. 162(1)
        value are the same number, so on exactly these rows a regression that made the
        election fire unconditionally would be invisible — the election-OFF rows able to
        detect that are the date-derived ones above (2.0y). This test pins the other half:
        that the 2.5 on a null-date row is produced by the **fallback**, so the fallback rung
        cannot be deleted or re-pointed at ``firb_fixed_maturity`` and still look correct.
        """
        # Arrange — nothing to derive M from, election off
        lf = _irb_frame(maturity_date=None)

        # Act
        m = _maturity(lf, _crr_config())

        # Assert — fallback default, reached without the Art. 162(1) election
        assert m == pytest.approx(2.5)


class TestFIRBFixedMaturityRegimeGate:
    """PS1/26 Art. 162(1) is "[Note: Provision left blank]" — the election is inert."""

    def test_election_has_no_effect_under_basel_3_1(self) -> None:
        # Arrange
        lf = _irb_frame(maturity_date=_B31_MATURITY_DATE)

        # Act
        m = _maturity(lf, _b31_config(firb_fixed_maturity=True))

        # Assert — Art. 162(2A) date-derived M, NOT 2.5y
        assert m == pytest.approx(_DATE_DERIVED_M)
