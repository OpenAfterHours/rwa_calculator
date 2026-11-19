"""
Review CL-02: a collateral ``maturity_date`` sets its residual maturity.

Why this matters:
    The input contract documents collateral ``maturity_date`` ("Collateral
    maturity (if applicable)"), but before CL-02 nothing in the CRM stage read
    it. The Art. 237-239 maturity mismatch and the Art. 224 Table 1 band read
    ``residual_maturity_years`` alone, whose null took a 10-year default, so a
    one-year cash deposit supplied with only its maturity date protected a
    five-year loan in full: SA EAD 0 and F-IRB LGD 0 in both regimes, against
    84,208 / LGD 0.3789 for the same deposit supplied as a 1.0-year residual.
    Every repository fixture set both fields, so the path was never exercised.

Rule (quoted, verbatim):
    PS1/26 Art. 238(1): "the institution shall take the maturity of the credit
    protection to be the time to the earliest date at which the protection may
    terminate or be terminated". CRR Art. 238(1): "the maturity of the credit
    protection shall be the time to the earliest date at which the protection
    may terminate or be terminated". PS1/26 Art. 237(1): "a maturity mismatch
    occurs when the residual maturity of the credit protection is less than
    that of the protected exposure".

Hand calculation (cash 100,000 maturing one year after the reporting date,
loan 100,000 maturing five years after it, original protection term 2 years):
    t = days / 365.25 to the collateral date, T = min(days / 365.25, 5)
    CVAM = 100,000 x (t - 0.25) / (T - 0.25); SA E* = 100,000 - CVAM;
    F-IRB LGD* = LGDU x E* / E (financial LGDS 0%).
    CRR (2026-06-30): t = 365 / 365.25, T = 1826 / 365.25 -> E* = 84,222.66,
        LGD* = 0.45 x 0.8422266 = 0.379002.
    Basel 3.1 (2027-06-30): t = 366 / 365.25, T = min(1827 / 365.25, 5) = 5
        -> E* = 84,167.30, LGD* = 0.40 x 0.8416730 = 0.336669.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.unit.crm import _pipeline_harness as harness

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.crm.haircuts import HaircutCalculator, with_derived_residual_maturity


def _one_year_and_five_years(regime: str) -> tuple[date, date, date]:
    rd = harness.REPORTING_DATES[regime]
    return rd, date(rd.year + 1, rd.month, rd.day), date(rd.year + 5, rd.month, rd.day)


def _hand_calc(regime: str) -> tuple[float, float]:
    """(SA E*, F-IRB LGD*) for the docstring scenario, from its day counts."""
    rd, coll_mat, loan_mat = _one_year_and_five_years(regime)
    t = (coll_mat - rd).days / 365.25
    big_t = min((loan_mat - rd).days / 365.25, 5.0)
    e_star = 100_000.0 - 100_000.0 * (t - 0.25) / (big_t - 0.25)
    lgdu = 0.45 if regime == "crr" else 0.40
    return e_star, lgdu * e_star / 100_000.0


def _run(regime: str, *, firb: bool, residual: float | None) -> tuple[dict, set[str]]:
    _rd, coll_mat, loan_mat = _one_year_and_five_years(regime)
    pledge = {
        "collateral_reference": "C1",
        "collateral_type": "cash",
        "market_value": 100_000.0,
        "maturity_date": coll_mat,
        "beneficiary_type": "loan",
        "beneficiary_reference": "L1",
        "is_eligible_financial_collateral": True,
        "original_maturity_years": 2.0,
        "residual_maturity_years": residual,
    }
    results, errors = harness.run(
        regime,
        firb=firb,
        loans=harness.loans(
            [
                {
                    "loan_reference": "L1",
                    "counterparty_reference": "CP1",
                    "drawn_amount": 100_000.0,
                    "maturity_date": loan_mat,
                }
            ]
        ),
        collateral=harness.collateral([pledge]),
    )
    return harness.row(results, "L1"), harness.codes(errors)


class TestMaturityDateOnlyPledgeTakesTheMismatch:
    """End to end: a pledge stating only its maturity date is mismatch-adjusted."""

    @pytest.mark.parametrize(("regime", "expected_ead"), [("crr", 84_222.66), ("b31", 84_167.30)])
    def test_sa_exposure_value_reflects_the_one_year_protection(
        self, regime: str, expected_ead: float
    ) -> None:
        # Arrange
        hand_ead, _ = _hand_calc(regime)
        assert hand_ead == pytest.approx(expected_ead, abs=0.01)

        # Act
        result, error_codes = _run(regime, firb=False, residual=None)

        # Assert: pre-fix this was 0.0 (the deposit protected the loan in full).
        assert result["ead_final"] == pytest.approx(hand_ead, rel=1e-9)
        assert "CRM002" in error_codes

    @pytest.mark.parametrize(("regime", "expected_lgd"), [("crr", 0.379002), ("b31", 0.336669)])
    def test_firb_lgd_reflects_the_one_year_protection(
        self, regime: str, expected_lgd: float
    ) -> None:
        # Arrange
        _, hand_lgd = _hand_calc(regime)
        assert hand_lgd == pytest.approx(expected_lgd, abs=1e-6)

        # Act
        result, error_codes = _run(regime, firb=True, residual=None)

        # Assert: pre-fix this was 0.0 in both regimes.
        assert result["approach_applied"] == "foundation_irb"
        assert result["lgd_post_crm"] == pytest.approx(hand_lgd, rel=1e-9)
        assert "CRM002" in error_codes

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_a_supplied_residual_still_wins_over_the_date(self, regime: str) -> None:
        """A 10-year residual beside the one-year date: the residual is the input."""
        # Act
        result, error_codes = _run(regime, firb=False, residual=10.0)

        # Assert: no mismatch on the supplied residual -> full protection.
        assert result["ead_final"] == pytest.approx(0.0, abs=1e-9)
        assert "CRM002" not in error_codes


class TestWithDerivedResidualMaturity:
    """The derivation itself: coalesce, day count, null passthrough."""

    def test_null_residual_is_derived_on_the_365_25_basis(self) -> None:
        # Arrange
        frame = pl.LazyFrame(
            {
                "maturity_date": [date(2027, 6, 30), date(2030, 1, 1), None],
                "residual_maturity_years": [None, 0.75, None],
            },
            schema={"maturity_date": pl.Date, "residual_maturity_years": pl.Float64},
        )

        # Act
        out = with_derived_residual_maturity(frame, date(2026, 6, 30)).collect()

        # Assert: derived / supplied-wins / neither stays null.
        assert out["residual_maturity_years"].to_list() == [
            pytest.approx(365 / 365.25),
            pytest.approx(0.75),
            None,
        ]

    @pytest.mark.parametrize(
        ("regime_config", "expected_haircut"),
        [
            (CalculationConfig.crr(reporting_date=date(2026, 6, 30)), 0.005),
            (CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30)), 0.005),
        ],
    )
    def test_the_art_224_band_reads_the_derived_residual(
        self, regime_config: CalculationConfig, expected_haircut: float
    ) -> None:
        """A CQS 1 sovereign bond six months from maturity is in the <= 1y band.

        Art. 224(1) Table 1 keys the haircut on "Residual Maturity"; a null
        residual took the longest band (CRR 4% / Basel 3.1 4% at 10 days). The
        derived 0.5-year residual gives the 0.5% band in both regimes.
        """
        # Arrange
        rd = regime_config.reporting_date
        frame = pl.LazyFrame(
            {
                "collateral_reference": ["B1"],
                "collateral_type": ["bond"],
                "issuer_type": ["sovereign"],
                "issuer_cqs": [1],
                "currency": ["GBP"],
                "exposure_currency": ["GBP"],
                "market_value": [100_000.0],
                "maturity_date": [date(rd.year, 12, 31)],
                "residual_maturity_years": [None],
                "liquidation_period_days": [10],
                "is_eligible_financial_collateral": [True],
            },
            schema_overrides={
                "issuer_cqs": pl.Int8,
                "residual_maturity_years": pl.Float64,
                "liquidation_period_days": pl.Int32,
            },
        )

        # Act
        out = HaircutCalculator().apply_haircuts(frame, regime_config).collect()

        # Assert
        assert out["collateral_haircut"][0] == pytest.approx(expected_haircut)
