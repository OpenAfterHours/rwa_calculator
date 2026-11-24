"""
P1.204: the Basel 3.1 slotting short-maturity columns A/C are a firm election.

Pipeline position:
    CRMProcessor -> SlottingCalculator (prepare_columns -> apply_slotting_weights
        -> apply_el_rates) -> OutputAggregator

PRA PS1/26 Art. 153(5)(c): "subject to points (d) to (f) of this paragraph an
institution shall: (i) assign the relevant risk weight in column B of Table A to
exposures assigned to the 'Strong' rating grade; (ii) assign the relevant risk
weight in column D of Table A to exposures assigned to the 'Good' rating grade".
Art. 153(5)(d): "an institution may, for all categories of specialised lending
exposures, if less than 2.5 years remain until maturity of an exposure" assign
column A (Strong) / column C (Good) instead. Column B/D is the default; A/C only
on the firm's election. Art. 158(6): the EL rate is "the EL value in the cell of
Table B that is in the corresponding row and column to the risk weight value in
Table A that the institution has assigned", so EL follows the applied column.

Table A (ps126app1.pdf p.103), A / B / C / D:
    non-HVCRE  50% / 70% / 70% / 90%      HVCRE  70% / 95% / 95% / 120%
Table B (p.108), A / B / C / D:
    non-HVCRE  0% / 0.4% / 0.4% / 0.8%    HVCRE  0.4% flat

UK CRR Art. 153(5) is different: the institution "shall assign risk weights ...
in accordance with Table 1", whose "less than 2,5 years" row (50/70/115/250/0)
is mandatory — so the CRR split stays automatic whatever the election says.

The expected values below are typed from the two tables, not read from the
rulepack, so a wrong pack value cannot move the expectation with it.

References:
- PRA PS1/26 Art. 153(5)(c)-(d) Table A; Art. 158(6) Table B
- UK CRR Art. 153(5) Table 1
"""

from __future__ import annotations

import dataclasses
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.slotting.transforms import (
    apply_el_rates,
    apply_slotting_weights,
    prepare_columns,
)

_REPORTING_DATE = date(2027, 6, 30)
_SHORT = date(2029, 6, 30)  # 2.0 years remain -> is_short_maturity True
_LONG = date(2031, 6, 30)  # 4.0 years remain -> is_short_maturity False
_EAD = 10_000_000.0
_CARRIER = "slotting_short_maturity_rw_applied"


def _b31(*, elected: bool | None = None) -> CalculationConfig:
    if elected is None:
        return CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE)
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE, slotting_short_maturity_election=elected
    )


def _crr(*, elected: bool | None = None) -> CalculationConfig:
    config = CalculationConfig.crr(reporting_date=_REPORTING_DATE)
    if elected is None:
        return config
    return dataclasses.replace(config, slotting_short_maturity_election=elected)


def _run(
    config: CalculationConfig,
    *,
    category: str,
    maturity: date,
    hvcre: bool = False,
    pre_operational: bool | None = None,
) -> dict[str, object]:
    """One slotting row through the RW and EL transforms, as the calculator runs them."""
    data: dict[str, list[object]] = {
        "exposure_reference": ["SL1"],
        "ead_final": [_EAD],
        "slotting_category": [category],
        "is_hvcre": [hvcre],
        "sl_type": ["hvcre" if hvcre else "project_finance"],
        "maturity_date": [maturity],
    }
    if pre_operational is not None:
        data["is_pre_operational"] = [pre_operational]
    lf = pl.LazyFrame(data)
    out = (
        lf.pipe(prepare_columns, config)
        .pipe(apply_slotting_weights, config)
        .pipe(apply_el_rates, config)
        .collect()
    )
    return out.row(0, named=True)


# Adequacy for every short-dated case below: the date really is short-dated.
def test_the_short_fixture_date_is_inside_the_two_and_a_half_year_window() -> None:
    row = _run(_b31(), category="strong", maturity=_SHORT)
    assert row["is_short_maturity"] is True, "the short date is not < 2.5y - tests prove nothing"
    assert _run(_b31(), category="strong", maturity=_LONG)["is_short_maturity"] is False


class TestBasel31DefaultIsColumnBD:
    """Without the Art. 153(5)(d) election a short-dated Strong/Good leg takes B/D."""

    @pytest.mark.parametrize(
        ("category", "hvcre", "expected_rw", "expected_el_rate"),
        [
            pytest.param("strong", False, 0.70, 0.004, id="strong-col-B"),
            pytest.param("good", False, 0.90, 0.008, id="good-col-D"),
            pytest.param("strong", True, 0.95, 0.004, id="hvcre-strong-col-B"),
            pytest.param("good", True, 1.20, 0.004, id="hvcre-good-col-D"),
        ],
    )
    def test_short_dated_leg_takes_the_default_column(
        self, category: str, hvcre: bool, expected_rw: float, expected_el_rate: float
    ) -> None:
        # Arrange
        config = _b31()

        # Act
        row = _run(config, category=category, maturity=_SHORT, hvcre=hvcre)

        # Assert
        assert row["risk_weight"] == pytest.approx(expected_rw)
        assert row["slotting_el_rate"] == pytest.approx(expected_el_rate)
        assert row["expected_loss"] == pytest.approx(expected_el_rate * _EAD)
        assert row[_CARRIER] is False

    def test_the_factory_default_is_not_elected(self) -> None:
        # Arrange / Act
        config = _b31()

        # Assert
        assert config.slotting_short_maturity_election is False

    def test_an_explicit_false_election_matches_the_default(self) -> None:
        # Arrange
        config = _b31(elected=False)

        # Act
        row = _run(config, category="strong", maturity=_SHORT)

        # Assert
        assert (row["risk_weight"], row["slotting_el_rate"]) == pytest.approx((0.70, 0.004))


class TestBasel31ElectionAppliesColumnAC:
    """With the election a short-dated Strong/Good leg takes A/C, and EL follows it."""

    @pytest.mark.parametrize(
        ("category", "hvcre", "expected_rw", "expected_el_rate"),
        [
            pytest.param("strong", False, 0.50, 0.0, id="strong-col-A"),
            pytest.param("good", False, 0.70, 0.004, id="good-col-C"),
            pytest.param("strong", True, 0.70, 0.004, id="hvcre-strong-col-A"),
            pytest.param("good", True, 0.95, 0.004, id="hvcre-good-col-C"),
        ],
    )
    def test_short_dated_leg_takes_the_elected_column(
        self, category: str, hvcre: bool, expected_rw: float, expected_el_rate: float
    ) -> None:
        # Arrange
        config = _b31(elected=True)

        # Act
        row = _run(config, category=category, maturity=_SHORT, hvcre=hvcre)

        # Assert
        assert row["risk_weight"] == pytest.approx(expected_rw)
        assert row["slotting_el_rate"] == pytest.approx(expected_el_rate)
        assert row[_CARRIER] is True

    @pytest.mark.parametrize(
        ("category", "expected_rw", "expected_el_rate"),
        [
            pytest.param("strong", 0.70, 0.004, id="strong-col-B"),
            pytest.param("good", 0.90, 0.008, id="good-col-D"),
        ],
    )
    def test_the_election_does_not_reach_a_long_dated_leg(
        self, category: str, expected_rw: float, expected_el_rate: float
    ) -> None:
        # Arrange
        config = _b31(elected=True)

        # Act
        row = _run(config, category=category, maturity=_LONG)

        # Assert
        assert (row["risk_weight"], row["slotting_el_rate"]) == pytest.approx(
            (expected_rw, expected_el_rate)
        )
        assert row[_CARRIER] is False

    def test_the_election_covers_pre_operational_project_finance(self) -> None:
        """Art. 153(5)(d) is "for all categories of specialised lending exposures".

        Unit-level guard only: nothing in production sets ``is_pre_operational``
        True (it is defaulted False in ``prepare_columns`` and is not an input
        column), so this pins that the flag can never block the election again.
        """
        # Arrange
        config = _b31(elected=True)

        # Act
        row = _run(config, category="strong", maturity=_SHORT, pre_operational=True)

        # Assert
        assert (row["risk_weight"], row["slotting_el_rate"]) == pytest.approx((0.50, 0.0))


class TestBasel31GradesWithoutAColumnChoice:
    """Table A gives 'Satisfactory', 'Weak' and 'Default' ONE column each.

    Art. 153(5)(d) offers a column for 'Strong' (A for B) and 'Good' (C for D)
    only, so for the other three grades there is nothing to elect: the weight and
    the Table B EL rate are the grade's single cell whatever the election says,
    and a short-dated leg sits in the short-maturity band its remaining maturity
    names. The band is what C 08.06 / CR10 cut their rows on, so a carrier False
    here would move every short-dated Satisfactory/Weak/Default leg of a firm
    without the election onto a row labelled ">= 2.5 years".
    """

    @pytest.mark.parametrize("elected", [False, True], ids=["default", "elected"])
    @pytest.mark.parametrize(
        ("category", "hvcre", "expected_rw", "expected_el_rate"),
        [
            pytest.param("satisfactory", False, 1.15, 0.028, id="satisfactory"),
            pytest.param("weak", False, 2.50, 0.08, id="weak"),
            pytest.param("default", False, 0.0, 0.5, id="default"),
            pytest.param("satisfactory", True, 1.40, 0.028, id="hvcre-satisfactory"),
            pytest.param("weak", True, 2.50, 0.08, id="hvcre-weak"),
            pytest.param("default", True, 0.0, 0.5, id="hvcre-default"),
        ],
    )
    def test_short_dated_leg_keeps_its_single_column_and_the_short_band(
        self,
        category: str,
        hvcre: bool,
        expected_rw: float,
        expected_el_rate: float,
        elected: bool,
    ) -> None:
        # Arrange
        config = _b31(elected=elected)

        # Act
        row = _run(config, category=category, maturity=_SHORT, hvcre=hvcre)

        # Assert
        assert row["risk_weight"] == pytest.approx(expected_rw)
        assert row["slotting_el_rate"] == pytest.approx(expected_el_rate)
        assert row[_CARRIER] is True

    @pytest.mark.parametrize("category", ["satisfactory", "weak", "default"])
    def test_long_dated_leg_sits_in_the_long_band(self, category: str) -> None:
        # Arrange
        config = _b31()

        # Act
        row = _run(config, category=category, maturity=_LONG)

        # Assert
        assert row[_CARRIER] is False


class TestCrrMaturitySplitStaysMandatory:
    """CRR Art. 153(5) Table 1's '< 2.5 years' row is a 'shall' - no election reaches it."""

    @pytest.mark.parametrize("elected", [None, False, True], ids=["default", "false", "true"])
    def test_short_dated_strong_takes_the_table_1_short_row(self, elected: bool | None) -> None:
        # Arrange
        config = _crr(elected=elected)

        # Act
        row = _run(config, category="strong", maturity=_SHORT)

        # Assert
        assert (row["risk_weight"], row["slotting_el_rate"]) == pytest.approx((0.50, 0.0))
        assert row[_CARRIER] is True

    def test_long_dated_strong_takes_the_table_1_long_row(self) -> None:
        # Arrange
        config = _crr()

        # Act
        row = _run(config, category="strong", maturity=_LONG)

        # Assert
        assert (row["risk_weight"], row["slotting_el_rate"]) == pytest.approx((0.70, 0.004))
        assert row[_CARRIER] is False
