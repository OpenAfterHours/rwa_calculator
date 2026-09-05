"""
Unit tests for CRM maturity mismatch adjustment (Art. 238).

The vectorized apply_maturity_mismatch method must use actual exposure maturity
(derived from exposure_maturity Date column) rather than a hardcoded T=5 default.
The formula is CVAM = CVA × (t − 0.25) / (T − 0.25) where:
- t = collateral residual maturity in years
- T = min(exposure residual maturity, 5) in years (Art. 238(1) cap, no floor)

Whether a mismatch exists at all is decided on the RAW residuals (Art. 237(1):
"the residual maturity of the credit protection is less than that of the
protected exposure"). The 0.25 term lives only in the scaling formula, which
is reached only when t >= 0.25 < T, so it never divides by zero. Flooring T
before the comparison fabricated a mismatch for every matched pair maturing
within three months of the reporting date and zeroed its protection (escape
log 2026-09-05).

References:
    CRR Art. 238: Maturity mismatch adjustment
    PRA PS1/26 Art. 238: Same treatment under Basel 3.1
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.crm.haircuts import HaircutCalculator


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))


def _make_collateral(
    coll_maturity_years: float,
    exposure_maturity_date: date,
    value_after_haircut: float = 1000.0,
) -> pl.LazyFrame:
    """Build a minimal collateral LazyFrame for maturity mismatch testing."""
    return pl.LazyFrame(
        {
            "residual_maturity_years": [coll_maturity_years],
            "exposure_maturity": [exposure_maturity_date],
            "value_after_haircut": [value_after_haircut],
        },
        schema={
            "residual_maturity_years": pl.Float64,
            "exposure_maturity": pl.Date,
            "value_after_haircut": pl.Float64,
        },
    )


class TestMaturityMismatchVectorized:
    """Tests for HaircutCalculator.apply_maturity_mismatch with actual exposure maturity."""

    def test_no_mismatch_collateral_exceeds_exposure(self, crr_config: CalculationConfig) -> None:
        """No adjustment when collateral maturity >= exposure maturity."""
        reporting = crr_config.reporting_date
        # Exposure matures in 3 years, collateral in 5 years → no mismatch
        exposure_mat = reporting + timedelta(days=int(3 * 365.25))
        collateral = _make_collateral(5.0, exposure_mat)

        calc = HaircutCalculator()
        result = calc.apply_maturity_mismatch(collateral, crr_config).collect()

        assert result["maturity_adjustment_factor"][0] == pytest.approx(1.0)
        assert result["value_after_maturity_adj"][0] == pytest.approx(1000.0)

    def test_3yr_exposure_2yr_collateral(self, crr_config: CalculationConfig) -> None:
        """
        Correct adjustment for 3yr exposure with 2yr collateral.

        T = min(3, 5) = 3, t = 2
        Factor = (2 - 0.25) / (3 - 0.25) = 1.75 / 2.75 ≈ 0.6364

        Previously this would incorrectly use T=5:
        Factor = (2 - 0.25) / (5 - 0.25) = 1.75 / 4.75 ≈ 0.3684
        """
        reporting = crr_config.reporting_date
        exposure_mat = reporting + timedelta(days=int(3 * 365.25))
        collateral = _make_collateral(2.0, exposure_mat)

        calc = HaircutCalculator()
        result = calc.apply_maturity_mismatch(collateral, crr_config).collect()

        expected_factor = (2.0 - 0.25) / (3.0 - 0.25)  # 0.6364
        assert result["maturity_adjustment_factor"][0] == pytest.approx(expected_factor, rel=1e-2)
        assert result["value_after_maturity_adj"][0] == pytest.approx(
            1000.0 * expected_factor, rel=1e-2
        )

    def test_5yr_exposure_2yr_collateral(self, crr_config: CalculationConfig) -> None:
        """Standard case: 5yr exposure with 2yr collateral. T capped at 5."""
        reporting = crr_config.reporting_date
        exposure_mat = reporting + timedelta(days=int(5 * 365.25))
        collateral = _make_collateral(2.0, exposure_mat)

        calc = HaircutCalculator()
        result = calc.apply_maturity_mismatch(collateral, crr_config).collect()

        expected_factor = (2.0 - 0.25) / (5.0 - 0.25)  # 0.3684
        assert result["maturity_adjustment_factor"][0] == pytest.approx(expected_factor, rel=1e-2)

    def test_7yr_exposure_capped_at_5(self, crr_config: CalculationConfig) -> None:
        """Exposure maturity >5yr is capped at T=5 per Art. 238."""
        reporting = crr_config.reporting_date
        exposure_mat = reporting + timedelta(days=int(7 * 365.25))
        collateral = _make_collateral(2.0, exposure_mat)

        calc = HaircutCalculator()
        result = calc.apply_maturity_mismatch(collateral, crr_config).collect()

        expected_factor = (2.0 - 0.25) / (5.0 - 0.25)  # Capped at T=5
        assert result["maturity_adjustment_factor"][0] == pytest.approx(expected_factor, rel=1e-2)

    def test_collateral_under_3_months_zeroed(self, crr_config: CalculationConfig) -> None:
        """Collateral with <3 month maturity provides no protection."""
        reporting = crr_config.reporting_date
        exposure_mat = reporting + timedelta(days=int(3 * 365.25))
        collateral = _make_collateral(0.1, exposure_mat)

        calc = HaircutCalculator()
        result = calc.apply_maturity_mismatch(collateral, crr_config).collect()

        assert result["maturity_adjustment_factor"][0] == pytest.approx(0.0)
        assert result["value_after_maturity_adj"][0] == pytest.approx(0.0)

    def test_null_collateral_maturity_defaults_to_10yr(self, crr_config: CalculationConfig) -> None:
        """Null collateral maturity defaults to 10yr (no mismatch)."""
        reporting = crr_config.reporting_date
        exposure_mat = reporting + timedelta(days=int(3 * 365.25))
        collateral = pl.LazyFrame(
            {
                "residual_maturity_years": [None],
                "exposure_maturity": [exposure_mat],
                "value_after_haircut": [1000.0],
            },
            schema={
                "residual_maturity_years": pl.Float64,
                "exposure_maturity": pl.Date,
                "value_after_haircut": pl.Float64,
            },
        )

        calc = HaircutCalculator()
        result = calc.apply_maturity_mismatch(collateral, crr_config).collect()

        # 10yr collateral > 3yr exposure → no adjustment
        assert result["maturity_adjustment_factor"][0] == pytest.approx(1.0)

    def test_null_exposure_maturity_defaults_to_5yr(self, crr_config: CalculationConfig) -> None:
        """Null exposure maturity defaults to T=5 (conservative)."""
        collateral = pl.LazyFrame(
            {
                "residual_maturity_years": [2.0],
                "exposure_maturity": [None],
                "value_after_haircut": [1000.0],
            },
            schema={
                "residual_maturity_years": pl.Float64,
                "exposure_maturity": pl.Date,
                "value_after_haircut": pl.Float64,
            },
        )

        calc = HaircutCalculator()
        result = calc.apply_maturity_mismatch(collateral, crr_config).collect()

        expected_factor = (2.0 - 0.25) / (5.0 - 0.25)  # T defaults to 5
        assert result["maturity_adjustment_factor"][0] == pytest.approx(expected_factor, rel=1e-2)

    def test_1yr_exposure_short_maturity_amplifies_factor(
        self, crr_config: CalculationConfig
    ) -> None:
        """
        Short exposure maturity produces larger adjustment factor.

        T = max(min(1, 5), 0.25) = 1, t = 0.5
        Factor = (0.5 - 0.25) / (1 - 0.25) = 0.25 / 0.75 = 0.3333

        With the old hardcoded T=5:
        Factor = (0.5 - 0.25) / (5 - 0.25) = 0.25 / 4.75 = 0.0526

        The old code gave too much benefit reduction (0.053 factor vs correct 0.333).
        """
        reporting = crr_config.reporting_date
        exposure_mat = reporting + timedelta(days=int(1 * 365.25))
        collateral = _make_collateral(0.5, exposure_mat)

        calc = HaircutCalculator()
        result = calc.apply_maturity_mismatch(collateral, crr_config).collect()

        expected_factor = (0.5 - 0.25) / (1.0 - 0.25)  # 0.3333
        assert result["maturity_adjustment_factor"][0] == pytest.approx(expected_factor, rel=1e-2)

    def test_basel31_same_formula(self, b31_config: CalculationConfig) -> None:
        """Basel 3.1 uses the same maturity mismatch formula as CRR."""
        reporting = b31_config.reporting_date
        exposure_mat = reporting + timedelta(days=int(3 * 365.25))
        collateral = _make_collateral(2.0, exposure_mat)

        calc = HaircutCalculator()
        result = calc.apply_maturity_mismatch(collateral, b31_config).collect()

        expected_factor = (2.0 - 0.25) / (3.0 - 0.25)
        assert result["maturity_adjustment_factor"][0] == pytest.approx(expected_factor, rel=1e-2)

    def test_mixed_batch_varying_exposure_maturities(self, crr_config: CalculationConfig) -> None:
        """Multiple exposures with different maturities processed correctly."""
        reporting = crr_config.reporting_date
        collateral = pl.LazyFrame(
            {
                "residual_maturity_years": [2.0, 2.0, 2.0, 0.1],
                "exposure_maturity": [
                    reporting + timedelta(days=int(3 * 365.25)),  # T=3
                    reporting + timedelta(days=int(5 * 365.25)),  # T=5
                    reporting + timedelta(days=int(1 * 365.25)),  # T=1 → no mismatch (2>1)
                    reporting + timedelta(days=int(3 * 365.25)),  # coll < 3m → 0
                ],
                "value_after_haircut": [1000.0, 1000.0, 1000.0, 1000.0],
            },
            schema={
                "residual_maturity_years": pl.Float64,
                "exposure_maturity": pl.Date,
                "value_after_haircut": pl.Float64,
            },
        )

        calc = HaircutCalculator()
        result = calc.apply_maturity_mismatch(collateral, crr_config).collect()

        factors = result["maturity_adjustment_factor"].to_list()
        # T=3: (2-0.25)/(3-0.25) = 0.6364
        assert factors[0] == pytest.approx((2.0 - 0.25) / (3.0 - 0.25), rel=1e-2)
        # T=5: (2-0.25)/(5-0.25) = 0.3684
        assert factors[1] == pytest.approx((2.0 - 0.25) / (5.0 - 0.25), rel=1e-2)
        # Collateral 2yr >= exposure 1yr → no adjustment
        assert factors[2] == pytest.approx(1.0)
        # Collateral < 3 months → no protection
        assert factors[3] == pytest.approx(0.0)

    def test_collateral_outliving_a_one_month_exposure_keeps_full_value(
        self, crr_config: CalculationConfig
    ) -> None:
        """Collateral (0.5y) longer than a one-month exposure: no mismatch, factor 1.0.

        Only the protection-longer-than-exposure limb of the short-exposure case;
        the matched and protection-shorter limbs live in
        TestMatchedAndShortDatedProtection.
        """
        reporting = crr_config.reporting_date
        exposure_mat = reporting + timedelta(days=30)
        collateral = _make_collateral(0.5, exposure_mat)

        calc = HaircutCalculator()
        result = calc.apply_maturity_mismatch(collateral, crr_config).collect()

        assert result["maturity_adjustment_factor"][0] == pytest.approx(1.0)


class TestMatchedAndShortDatedProtection:
    """Art. 237(1): a mismatch exists only when protection is SHORTER than the exposure.

    Escape log 2026-09-05: the exposure residual was floored at 0.25y before the
    comparison while the collateral residual was not, so a matched pair maturing
    within three months of the reporting date (interbank loan against interbank
    deposit under one netting agreement) compared as "protection shorter than
    exposure", hit the three-month gate, and lost all protection. Equal residuals
    are not a mismatch, whatever their length, and Art. 238(1) caps T at five
    years without flooring it.
    """

    @pytest.mark.parametrize("days", [7, 30, 60, 89, 91])
    def test_matched_pair_within_three_months_keeps_full_value(
        self, crr_config: CalculationConfig, days: int
    ) -> None:
        # Arrange: exposure and collateral share one maturity date inside 3 months.
        reporting = crr_config.reporting_date
        exposure_mat = reporting + timedelta(days=days)
        collateral = _make_collateral(days / 365.25, exposure_mat)

        # Act
        result = HaircutCalculator().apply_maturity_mismatch(collateral, crr_config).collect()

        # Assert: no mismatch → no gate, no scaling.
        assert result["maturity_adjustment_factor"][0] == pytest.approx(1.0)
        assert result["value_after_maturity_adj"][0] == pytest.approx(1000.0)

    def test_matched_past_dated_pair_keeps_full_value(self, crr_config: CalculationConfig) -> None:
        # Arrange: both legs carry a maturity date ten days before the reporting date
        # (a rolled position whose contractual date has passed).
        reporting = crr_config.reporting_date
        exposure_mat = reporting - timedelta(days=10)
        collateral = _make_collateral(-10 / 365.25, exposure_mat)

        # Act
        result = HaircutCalculator().apply_maturity_mismatch(collateral, crr_config).collect()

        # Assert
        assert result["maturity_adjustment_factor"][0] == pytest.approx(1.0)

    def test_matched_pair_with_short_original_term_is_not_gated(
        self, crr_config: CalculationConfig
    ) -> None:
        # Arrange: a 60-day deposit opened 30 days ago (original term 90 days) against a
        # 60-day loan. Art. 237(2)(a) binds only where a mismatch exists.
        reporting = crr_config.reporting_date
        exposure_mat = reporting + timedelta(days=60)
        collateral = pl.LazyFrame(
            {
                "residual_maturity_years": [60 / 365.25],
                "exposure_maturity": [exposure_mat],
                "value_after_haircut": [1000.0],
                "original_maturity_years": [90 / 365.0],
            },
            schema={
                "residual_maturity_years": pl.Float64,
                "exposure_maturity": pl.Date,
                "value_after_haircut": pl.Float64,
                "original_maturity_years": pl.Float64,
            },
        )

        # Act
        result = HaircutCalculator().apply_maturity_mismatch(collateral, crr_config).collect()

        # Assert
        assert result["maturity_adjustment_factor"][0] == pytest.approx(1.0)

    def test_protection_shorter_than_a_short_exposure_is_still_zeroed(
        self, crr_config: CalculationConfig
    ) -> None:
        # Arrange: 60-day exposure, 18-day collateral — a real mismatch under 3 months.
        reporting = crr_config.reporting_date
        exposure_mat = reporting + timedelta(days=60)
        collateral = _make_collateral(18 / 365.25, exposure_mat)

        # Act
        result = HaircutCalculator().apply_maturity_mismatch(collateral, crr_config).collect()

        # Assert: Art. 237(1) — under three months AND shorter than the exposure.
        assert result["maturity_adjustment_factor"][0] == pytest.approx(0.0)

    def test_mismatch_just_over_three_months_scales_without_a_floor_on_t(
        self, crr_config: CalculationConfig
    ) -> None:
        # Arrange: 100-day exposure (T = 0.2738y), 95-day collateral (t = 0.2601y).
        # A real mismatch with t >= 0.25, so the Art. 238 formula applies and its
        # denominator T - 0.25 is positive without any floor on T.
        reporting = crr_config.reporting_date
        exposure_mat = reporting + timedelta(days=100)
        t = 95 / 365.25
        big_t = 100 / 365.25
        collateral = _make_collateral(t, exposure_mat)

        # Act
        result = HaircutCalculator().apply_maturity_mismatch(collateral, crr_config).collect()

        # Assert
        expected = (t - 0.25) / (big_t - 0.25)
        assert 0.0 < expected < 1.0
        assert result["maturity_adjustment_factor"][0] == pytest.approx(expected, rel=1e-6)

    def test_basel31_matched_short_pair_keeps_full_value(
        self, b31_config: CalculationConfig
    ) -> None:
        # Arrange: PS1/26 carries Art. 237-239 forward unchanged.
        reporting = b31_config.reporting_date
        exposure_mat = reporting + timedelta(days=45)
        collateral = _make_collateral(45 / 365.25, exposure_mat)

        # Act
        result = HaircutCalculator().apply_maturity_mismatch(collateral, b31_config).collect()

        # Assert
        assert result["maturity_adjustment_factor"][0] == pytest.approx(1.0)
