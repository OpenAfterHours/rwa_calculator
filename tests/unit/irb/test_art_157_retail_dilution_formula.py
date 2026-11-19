"""TR-03: retail dilution risk is priced on the Art. 153(1) formula, not the retail one.

Pipeline position:
    CRMProcessor -> IRBCalculator (``transforms.apply_all_formulas`` — production;
    ``formulas.apply_irb_formulas`` and the stepwise ``calculate_correlation`` /
    ``calculate_maturity_adjustment`` — its twins)

Defect pinned (review TR-03, both regimes, RWA understated): the correlation and the
maturity adjustment were chosen by ``exposure_class`` alone, so a RETAIL purchased-
receivables row with ``purchased_receivables_subtype == "dilution_risk"`` took the
other-retail correlation (0.03-0.16, decay 35) and no maturity adjustment. At PD 2%
the engine's R was 0.094556 against the Art. 153(1) corporate 0.164146 — RWA 39.5%
low.

Rule text (verbatim):
    CRR Art. 157(1): "Institutions shall calculate the risk-weighted exposure amounts
    for dilution risk of purchased corporate and retail receivables in accordance
    with the formula set out in Article 153(1)."
    PS1/26 Art. 157(1): "An institution shall calculate the risk-weighted exposure
    amounts for dilution risk of purchased corporate and retail receivables in
    accordance with the formula set out in Article 153(1)."

Scope (verifier rescope): RETAIL dilution rows move to the Art. 153(1) corporate
curve with no SME (Art. 153(4)) and no large-FSE (Art. 153(2)) adjustment — neither
is an exposure to an SME corporate or an FSE. CORPORATE dilution rows are left
exactly as they are: whether Art. 153(2)/(4) reach a 157(1) dilution row is an
unsigned-off reading, and removing the 1.25 FSE multiplier would reduce RWA. The
exposure class is unchanged for reporting.

Hand calculation (PD 2%, M 1.0 so MA = 1, EAD 100,000; re-derived with
``tests/oracle/derivations/formulas.py``):
    R (Art. 153(1))  = 0.12*A + 0.24*(1-A), A = (1-e^-1)/(1-e^-50) -> 0.164146
    CRR, LGD 75%, x1.06:  RWA 169,194.90   (retail formula, pre-fix: 102,442.72)
    B31, LGD 100%:        RWA 212,823.78   (retail formula, pre-fix: 128,858.76)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.contract_columns import pad_crm_exit_defaults as _pad
from tests.oracle.derivations import formulas as oracle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb.formulas import apply_irb_formulas
from rwa_calc.engine.irb.transforms import (
    apply_all_formulas,
    calculate_correlation,
    calculate_maturity_adjustment,
)

_PD = 0.02
_EAD = 100_000.0
_R_CORPORATE = oracle.correlation_corporate(_PD)  # 0.164146
_R_RETAIL = oracle.correlation_retail(_PD)  # 0.094556

_CRR = CalculationConfig.crr(reporting_date=date(2026, 12, 31))
_B31 = CalculationConfig.basel_3_1(reporting_date=date(2027, 12, 31))


def _frame(lgd: float) -> pl.LazyFrame:
    """Four rows at the same PD/LGD/M: only class and subtype differ.

    - RET_DIL: retail_other + dilution_risk  -> MOVES to the Art. 153(1) curve
    - RET_SEN: retail_other + senior          -> unchanged (retail formula)
    - CORP_DIL: corporate + dilution_risk    -> unchanged (already Art. 153(1))
    - CORP_DIL_FSE: corporate + dilution_risk + requires_fi_scalar
                                               -> unchanged, keeps the 1.25 multiplier
    """
    return _pad(
        pl.LazyFrame(
            {
                "exposure_reference": ["RET_DIL", "RET_SEN", "CORP_DIL", "CORP_DIL_FSE"],
                "pd": [_PD] * 4,
                "lgd": [lgd] * 4,
                "lgd_input": [lgd] * 4,
                "ead_final": [_EAD] * 4,
                "exposure_class": ["retail_other", "retail_other", "corporate", "corporate"],
                "purchased_receivables_subtype": [
                    "dilution_risk",
                    "senior",
                    "dilution_risk",
                    "dilution_risk",
                ],
                "requires_fi_scalar": [False, False, False, True],
                "maturity": [1.0] * 4,
                "has_one_day_maturity_floor": [False] * 4,
            }
        )
    )


def _rows(df: pl.DataFrame) -> dict[str, dict]:
    return {r["exposure_reference"]: r for r in df.to_dicts()}


@pytest.mark.parametrize(
    ("config", "lgd", "scaling", "expected_rwa"),
    [
        (_CRR, 0.75, oracle.CRR_IRB_SCALING_FACTOR, 169_194.90),
        (_B31, 1.00, oracle.B31_IRB_SCALING_FACTOR, 212_823.78),
    ],
    ids=["crr", "b31"],
)
class TestRetailDilutionTakesTheArt1531Formula:
    """Production path: ``transforms.apply_all_formulas``."""

    def test_retail_dilution_row_uses_the_corporate_correlation(
        self, config: CalculationConfig, lgd: float, scaling: float, expected_rwa: float
    ) -> None:
        rows = _rows(apply_all_formulas(_frame(lgd), config).collect())

        assert rows["RET_DIL"]["correlation"] == pytest.approx(_R_CORPORATE, abs=1e-12)

    def test_retail_dilution_row_rwa_matches_the_hand_calculation(
        self, config: CalculationConfig, lgd: float, scaling: float, expected_rwa: float
    ) -> None:
        rows = _rows(apply_all_formulas(_frame(lgd), config).collect())
        expected_rw = oracle.irb_risk_weight_corporate(
            pd_value=_PD, lgd=lgd, maturity=1.0, correlation=_R_CORPORATE, scaling_factor=scaling
        )

        assert rows["RET_DIL"]["risk_weight"] == pytest.approx(expected_rw, rel=1e-9)
        assert rows["RET_DIL"]["rwa"] == pytest.approx(expected_rwa, abs=0.01)

    def test_retail_senior_row_keeps_the_retail_formula(
        self, config: CalculationConfig, lgd: float, scaling: float, expected_rwa: float
    ) -> None:
        """Anti-over-reach: only the dilution subtype moves."""
        rows = _rows(apply_all_formulas(_frame(lgd), config).collect())
        expected_rw = oracle.irb_risk_weight_retail(
            pd_value=_PD, lgd=lgd, correlation=_R_RETAIL, scaling_factor=scaling
        )

        assert rows["RET_SEN"]["correlation"] == pytest.approx(_R_RETAIL, abs=1e-12)
        assert rows["RET_SEN"]["maturity_adjustment"] == pytest.approx(1.0, abs=1e-15)
        assert rows["RET_SEN"]["risk_weight"] == pytest.approx(expected_rw, rel=1e-9)

    def test_corporate_dilution_rows_are_unchanged(
        self, config: CalculationConfig, lgd: float, scaling: float, expected_rwa: float
    ) -> None:
        """Corporate dilution keeps its class formula, FSE multiplier included."""
        rows = _rows(apply_all_formulas(_frame(lgd), config).collect())

        assert rows["CORP_DIL"]["correlation"] == pytest.approx(_R_CORPORATE, abs=1e-12)
        assert rows["CORP_DIL_FSE"]["correlation"] == pytest.approx(
            _R_CORPORATE * oracle.FINANCIAL_SECTOR_CORRELATION_MULTIPLIER, abs=1e-12
        )


class TestRetailDilutionTakesTheCorporateMaturityAdjustment:
    """Art. 153(1) carries the maturity adjustment; a retail class does not remove it."""

    def test_retail_dilution_row_at_two_and_a_half_years_is_maturity_adjusted(self) -> None:
        # Arrange — M = 2.5 makes MA visibly > 1 (at M = 1 it is exactly 1)
        lf = _frame(0.75).with_columns(pl.lit(2.5).alias("maturity"))

        # Act
        rows = _rows(apply_all_formulas(lf, _CRR).collect())

        # Assert
        assert rows["RET_DIL"]["maturity_adjustment"] == pytest.approx(
            oracle.maturity_adjustment(_PD, 2.5), abs=1e-12
        )
        assert rows["RET_SEN"]["maturity_adjustment"] == pytest.approx(1.0, abs=1e-15)


class TestTwinsAgreeWithTheProductionPath:
    """``formulas.apply_irb_formulas`` and the stepwise transforms route identically."""

    def test_apply_irb_formulas_twin(self) -> None:
        rows = _rows(apply_irb_formulas(_frame(0.75), _CRR).collect())

        assert rows["RET_DIL"]["correlation"] == pytest.approx(_R_CORPORATE, abs=1e-12)
        assert rows["RET_DIL"]["rwa"] == pytest.approx(169_194.90, abs=0.01)
        assert rows["RET_SEN"]["correlation"] == pytest.approx(_R_RETAIL, abs=1e-12)

    def test_stepwise_correlation_and_maturity_adjustment(self) -> None:
        lf = _frame(0.75).with_columns(
            pl.lit(_PD).alias("pd_floored"), pl.lit(2.5).alias("maturity")
        )

        rows = _rows(
            lf.pipe(calculate_correlation, _CRR).pipe(calculate_maturity_adjustment, _CRR).collect()
        )

        assert rows["RET_DIL"]["correlation"] == pytest.approx(_R_CORPORATE, abs=1e-12)
        assert rows["RET_DIL"]["maturity_adjustment"] == pytest.approx(
            oracle.maturity_adjustment(_PD, 2.5), abs=1e-12
        )
        assert rows["RET_SEN"]["maturity_adjustment"] == pytest.approx(1.0, abs=1e-15)

    def test_frame_without_the_subtype_column_still_prices(self) -> None:
        """A hand frame lacking the column (absent, not null) prices by class as before."""
        lf = pl.LazyFrame(
            {
                "pd_floored": [_PD],
                "exposure_class": ["retail_other"],
                "maturity": [1.0],
                "turnover_m": pl.Series([None], dtype=pl.Float64),
                "requires_fi_scalar": [False],
                "has_one_day_maturity_floor": [False],
            }
        )

        out = (
            lf.pipe(calculate_correlation, _CRR).pipe(calculate_maturity_adjustment, _CRR).collect()
        )

        assert out["correlation"][0] == pytest.approx(_R_RETAIL, abs=1e-12)
        assert out["maturity_adjustment"][0] == pytest.approx(1.0, abs=1e-15)
