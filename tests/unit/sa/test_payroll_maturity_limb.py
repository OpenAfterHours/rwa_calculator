"""
Unit tests for the payroll / pension loan maturity condition on the SA chain (P1.365).

Pipeline position:
    CRMProcessor -> SACalculator.calculate_branch -> Aggregation

Why these tests matter:
    Both regimes assign the 35% payroll / pension loan weight only "provided that
    all the following conditions are met", and the fourth reads "the maximum
    original maturity of the loan is equal to or less than 10 years" (PS1/26
    Art. 123(4)(d); CRR Art. 123 final subparagraph, point (d), "ten years").
    The engine granted the 35% on the caller-attested ``is_payroll_loan`` flag
    alone, so a 15-year payroll loan took 35% where the rule sends it to the
    Art. 123 retail ladder (75%, or 100% for Basel 3.1 retail that is not
    regulatory retail) -- an RWA understatement in both regimes.

    Conditions (a)-(c) stay the firm's attestation through the flag. Condition
    (d) is visible in the row's own maturity data, so the engine withholds the
    35% only where that data CONTRADICTS the attestation, and keeps it where the
    maturity is unknown.

    The boundary legs pin a CALENDAR comparison. 2027-01-15 -> 2037-01-15 is
    exactly 10 years and 2026-01-15 -> 2036-01-16 is 10 years and a day, and both
    span 3,653 days, so no day-count or year-fraction threshold can classify the
    pair correctly. The SA stage's own derived ``original_maturity_years``
    ((maturity - value) / 365) puts every exactly-10-year term above 10.0, so a
    naive ``<= 10`` test on it would deny the 35% the rule's "equal to or less
    than" grants.

References:
- PRA PS1/26 Art. 123(4)(d): maximum original maturity equal to or less than 10 years
- CRR Art. 123 final subparagraph point (d) (inserted by Reg. (EU) 2019/876)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.sa import SACalculator
from rwa_calc.rulebook.resolve import resolve

_EAD = 40_000.0
_PAYROLL_RW = 0.35  # PS1/26 Art. 123(4) / CRR Art. 123 final subparagraph
_REGULATORY_RETAIL_RW = 0.75  # PS1/26 Art. 123(3)(b) / CRR Art. 123 first subparagraph
_NON_REGULATORY_RETAIL_RW = 1.00  # PS1/26 Art. 123(3)(c) / CRR Art. 123 (fails criteria)
_TRANSACTOR_RW = 0.45  # PS1/26 Art. 123(3)(a)
_CAP_ENTRY = "retail_payroll_loan_max_original_maturity_years"

_REGIMES = pytest.mark.parametrize("regime", ["crr", "b31"])


def _config(regime: str) -> CalculationConfig:
    """The regime's calculation config, built through its factory."""
    if regime == "crr":
        return CalculationConfig.crr(reporting_date=date(2026, 6, 30))
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _payroll_row(
    *,
    value_date: date | None = None,
    maturity_date: date | None = None,
    original_maturity_years: float | None = None,
    qualifies_as_retail: bool = True,
    is_qrre_transactor: bool = False,
) -> pl.LazyFrame:
    """One natural-person retail row flagged ``is_payroll_loan``, maturity as given."""
    return pl.DataFrame(
        {
            "exposure_reference": ["PAY_LIMB_D"],
            "ead_final": [_EAD],
            "exposure_class": [ExposureClass.RETAIL_OTHER.value],
            "cqs": [None],
            "is_sme": [False],
            "is_infrastructure": [False],
            "is_payroll_loan": [True],
            "is_qrre_transactor": [is_qrre_transactor],
            "qualifies_as_retail": [qualifies_as_retail],
            "value_date": [value_date],
            "maturity_date": [maturity_date],
            "original_maturity_years": [original_maturity_years],
        },
        schema_overrides={
            "cqs": pl.Int8,
            "value_date": pl.Date,
            "maturity_date": pl.Date,
            "original_maturity_years": pl.Float64,
        },
    ).lazy()


def _run(regime: str, row: pl.LazyFrame) -> dict:
    """Run the SA branch on one row and return it as a dict."""
    return SACalculator().calculate_branch(row, _config(regime)).collect().to_dicts()[0]


# =============================================================================
# The cap itself -- a cited pack value, one per regime
# =============================================================================


class TestPayrollMaturityCapPackEntry:
    """The 10-year limit is a cited rulepack scalar in both regimes."""

    @pytest.mark.parametrize(
        ("regime", "as_of", "framework"),
        [("crr", date(2026, 1, 1), "CRR"), ("b31", date(2027, 1, 1), "PS1/26")],
    )
    def test_cap_is_ten_years_cited_to_article_123(
        self, regime: str, as_of: date, framework: str
    ) -> None:
        """Each regime's pack carries 10 years, cited to its own Art. 123 text."""
        # Arrange / Act
        entry = resolve(regime, as_of).scalar_param(_CAP_ENTRY)

        # Assert
        assert entry.value == Decimal(10)
        assert (entry.citation.framework, entry.citation.article) == (framework, "123")


# =============================================================================
# Condition (d) contradicted by the row's own data -> no 35%
# =============================================================================


class TestPayrollLoanOverTenYearsLosesThirtyFivePercent:
    """A flagged payroll loan whose own maturity data exceeds 10 years is not 35%."""

    @_REGIMES
    def test_fifteen_year_term_takes_regulatory_retail_weight(self, regime: str) -> None:
        """2026-01-15 -> 2041-01-15 (15 years): 75% regulatory retail, not 35%."""
        # Arrange
        row = _payroll_row(value_date=date(2026, 1, 15), maturity_date=date(2041, 1, 15))

        # Act
        result = _run(regime, row)

        # Assert
        assert result["original_maturity_years"] > 10.0, (
            "adequacy: the row's own term must exceed the cap, or this proves nothing"
        )
        assert result["risk_weight"] == pytest.approx(_REGULATORY_RETAIL_RW)
        assert result["rwa_pre_factor"] == pytest.approx(_EAD * _REGULATORY_RETAIL_RW)

    @_REGIMES
    def test_ten_years_and_one_day_takes_regulatory_retail_weight(self, regime: str) -> None:
        """2026-01-15 -> 2036-01-16: one calendar day over 10 years fails (d)."""
        # Arrange
        row = _payroll_row(value_date=date(2026, 1, 15), maturity_date=date(2036, 1, 16))

        # Act
        result = _run(regime, row)

        # Assert
        assert result["risk_weight"] == pytest.approx(_REGULATORY_RETAIL_RW)

    @_REGIMES
    def test_explicit_twelve_year_original_maturity_takes_regulatory_retail_weight(
        self, regime: str
    ) -> None:
        """No dates, explicit ``original_maturity_years`` 12.0: fails (d) -> 75%."""
        # Arrange
        row = _payroll_row(original_maturity_years=12.0)

        # Act
        result = _run(regime, row)

        # Assert
        assert result["risk_weight"] == pytest.approx(_REGULATORY_RETAIL_RW)

    @_REGIMES
    def test_non_regulatory_retail_over_ten_years_takes_hundred_percent(self, regime: str) -> None:
        """Fails (d) and fails the regulatory-retail criteria: 100% in both regimes.

        Basel 3.1 is the fail-first leg -- its payroll limb precedes the
        Art. 123(3)(c) 100% limb, so the 35% used to win. CRR prices the
        non-qualifying row at 100% before it reaches the payroll limb, so its
        leg pins the landing rather than the fix.
        """
        # Arrange
        row = _payroll_row(
            value_date=date(2026, 1, 15),
            maturity_date=date(2041, 1, 15),
            qualifies_as_retail=False,
        )

        # Act
        result = _run(regime, row)

        # Assert
        assert result["risk_weight"] == pytest.approx(_NON_REGULATORY_RETAIL_RW)

    @_REGIMES
    def test_explicit_maturity_contradicts_when_a_date_is_missing(self, regime: str) -> None:
        """Value date absent, explicit 12.0: the explicit figure alone fails (d)."""
        # Arrange
        row = _payroll_row(maturity_date=date(2041, 1, 15), original_maturity_years=12.0)

        # Act
        result = _run(regime, row)

        # Assert
        assert result["risk_weight"] == pytest.approx(_REGULATORY_RETAIL_RW)

    @_REGIMES
    @pytest.mark.parametrize(
        ("maturity_date", "original_maturity_years"),
        [
            (date(2031, 1, 15), 12.0),  # dates within the cap, explicit figure over it
            (date(2041, 1, 15), 8.0),  # explicit figure within the cap, dates over it
        ],
        ids=["explicit_over", "dates_over"],
    )
    def test_either_source_over_the_cap_contradicts(
        self, regime: str, maturity_date: date, original_maturity_years: float
    ) -> None:
        """Dates AND an explicit figure: (d) fails if EITHER shows more than 10 years.

        The flag attests (d); any of the row's own maturity data that exceeds the
        cap contradicts it, so neither source can rescue the 35% from the other.
        """
        # Arrange
        row = _payroll_row(
            value_date=date(2026, 1, 15),
            maturity_date=maturity_date,
            original_maturity_years=original_maturity_years,
        )

        # Act
        result = _run(regime, row)

        # Assert
        assert result["risk_weight"] == pytest.approx(_REGULATORY_RETAIL_RW)

    def test_b31_qualifying_transactor_over_ten_years_keeps_transactor_weight(self) -> None:
        """Basel 3.1: a qualifying transactor failing (d) lands on Art. 123(3)(a) 45%."""
        # Arrange
        row = _payroll_row(
            value_date=date(2026, 1, 15),
            maturity_date=date(2041, 1, 15),
            is_qrre_transactor=True,
        )

        # Act
        result = _run("b31", row)

        # Assert
        assert result["risk_weight"] == pytest.approx(_TRANSACTOR_RW)


# =============================================================================
# Condition (d) met, or not contradicted -> 35% stands
# =============================================================================


class TestPayrollLoanWithinTenYearsKeepsThirtyFivePercent:
    """ "Equal to or less than 10 years" is met on the calendar, and unknown is no contradiction."""

    @_REGIMES
    @pytest.mark.parametrize(
        ("value_date", "maturity_date"),
        [
            (date(2026, 1, 15), date(2036, 1, 15)),  # 3,652 days, two leap days
            (date(2027, 1, 15), date(2037, 1, 15)),  # 3,653 days, three leap days
        ],
        ids=["two_leap_days", "three_leap_days"],
    )
    def test_exactly_ten_calendar_years_keeps_payroll_weight(
        self, regime: str, value_date: date, maturity_date: date
    ) -> None:
        """An exactly-10-year term is "equal to" the maximum: 35%."""
        # Arrange
        row = _payroll_row(value_date=value_date, maturity_date=maturity_date)

        # Act
        result = _run(regime, row)

        # Assert
        assert result["original_maturity_years"] > 10.0, (
            "adequacy: the /365 derivation must overshoot 10.0 here, or this leg "
            "cannot tell a calendar comparison from a naive year-fraction one"
        )
        assert result["risk_weight"] == pytest.approx(_PAYROLL_RW)

    def test_boundary_pair_shares_a_day_count(self) -> None:
        """Adequacy: exactly-10y and 10y+1d legs span the same number of days.

        This is what makes the pair decisive -- any day-count or year-fraction
        threshold gives them the same answer, while the rule gives them opposite
        ones; only a calendar comparison passes both.
        """
        # Arrange / Act
        exactly_ten = (date(2037, 1, 15) - date(2027, 1, 15)).days
        ten_and_a_day = (date(2036, 1, 16) - date(2026, 1, 15)).days

        # Assert
        assert exactly_ten == ten_and_a_day == 3653

    @_REGIMES
    def test_explicit_ten_year_original_maturity_keeps_payroll_weight(self, regime: str) -> None:
        """No dates, explicit ``original_maturity_years`` 10.0: "equal to" -> 35%."""
        # Arrange
        row = _payroll_row(original_maturity_years=10.0)

        # Act
        result = _run(regime, row)

        # Assert
        assert result["risk_weight"] == pytest.approx(_PAYROLL_RW)

    @_REGIMES
    def test_unknown_maturity_keeps_attested_payroll_weight(self, regime: str) -> None:
        """Typed-null dates and maturity: nothing contradicts the attestation -> 35%."""
        # Arrange
        row = _payroll_row()

        # Act
        result = _run(regime, row)

        # Assert
        assert result["risk_weight"] == pytest.approx(_PAYROLL_RW)

    @_REGIMES
    def test_absent_maturity_columns_keep_attested_payroll_weight(self, regime: str) -> None:
        """No date or maturity COLUMN at all (not typed nulls): 35% stands."""
        # Arrange
        row = _payroll_row().drop("value_date", "maturity_date", "original_maturity_years")

        # Act
        result = _run(regime, row)

        # Assert
        assert result["risk_weight"] == pytest.approx(_PAYROLL_RW)

    @_REGIMES
    def test_exact_ten_year_dates_and_explicit_ten_keep_payroll_weight(self, regime: str) -> None:
        """Both sources present and both within the cap: nothing contradicts (d) -> 35%."""
        # Arrange
        row = _payroll_row(
            value_date=date(2027, 1, 15),
            maturity_date=date(2037, 1, 15),
            original_maturity_years=10.0,
        )

        # Act
        result = _run(regime, row)

        # Assert
        assert result["risk_weight"] == pytest.approx(_PAYROLL_RW)
