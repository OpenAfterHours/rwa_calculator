"""
Unit tests for Art. 237(2) maturity mismatch ineligibility conditions.

Art. 237(2) adds two conditions beyond the existing 3-month residual maturity test:
- (a) Original maturity of protection < 1 year → ineligible when mismatch exists
- (b) Exposures with 1-day IRB maturity floor (Art. 162(3)) → any mismatch
      makes protection completely ineligible (repos/SFTs with daily margining)

These conditions prevent capital understatement from over-recognising
short-term or mismatched credit protection.

References:
    CRR Art. 237(2): Maturity mismatch ineligibility conditions
    CRR Art. 162(3): 1-day maturity floor for repos/SFTs
    PRA PS1/26 Art. 237(2): Same treatment under Basel 3.1
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.haircuts import calculate_maturity_mismatch_adjustment
from rwa_calc.engine.crm.haircuts import HaircutCalculator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    original_maturity_years: float | None = None,
    exposure_has_one_day_maturity_floor: bool | None = None,
) -> pl.LazyFrame:
    """Build a minimal collateral LazyFrame for Art. 237(2) testing."""
    data: dict = {
        "residual_maturity_years": [coll_maturity_years],
        "exposure_maturity": [exposure_maturity_date],
        "value_after_haircut": [value_after_haircut],
    }
    schema: dict = {
        "residual_maturity_years": pl.Float64,
        "exposure_maturity": pl.Date,
        "value_after_haircut": pl.Float64,
    }
    if original_maturity_years is not None:
        data["original_maturity_years"] = [original_maturity_years]
        schema["original_maturity_years"] = pl.Float64
    if exposure_has_one_day_maturity_floor is not None:
        data["exposure_has_one_day_maturity_floor"] = [exposure_has_one_day_maturity_floor]
        schema["exposure_has_one_day_maturity_floor"] = pl.Boolean

    return pl.LazyFrame(data, schema=schema)


# ---------------------------------------------------------------------------
# Art. 237(2) — Original maturity < 1 year (vectorized path)
# ---------------------------------------------------------------------------


class TestOriginalMaturityIneligibility:
    """Art. 237(2): protection with original maturity < 1 year is ineligible when mismatch exists."""

    def test_original_maturity_under_1yr_zeroed(self, crr_config: CalculationConfig) -> None:
        """Protection with 0.5yr original maturity → factor 0.0 (ineligible)."""
        # Collateral: 0.5yr residual, 0.5yr original, exposure: 3yr
        exposure_date = crr_config.reporting_date + timedelta(days=int(3 * 365.25))
        lf = _make_collateral(
            coll_maturity_years=0.5,
            exposure_maturity_date=exposure_date,
            original_maturity_years=0.5,
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_maturity_mismatch(lf, crr_config).collect()

        assert result["maturity_adjustment_factor"][0] == pytest.approx(0.0)
        assert result["value_after_maturity_adj"][0] == pytest.approx(0.0)

    def test_original_maturity_exactly_1yr_eligible(self, crr_config: CalculationConfig) -> None:
        """Original maturity = 1.0 year: NOT ineligible (condition is < 1yr)."""
        exposure_date = crr_config.reporting_date + timedelta(days=int(3 * 365.25))
        lf = _make_collateral(
            coll_maturity_years=0.5,
            exposure_maturity_date=exposure_date,
            original_maturity_years=1.0,
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_maturity_mismatch(lf, crr_config).collect()

        # Should get CVAM adjustment, not zero
        assert result["maturity_adjustment_factor"][0] > 0.0
        assert result["value_after_maturity_adj"][0] > 0.0

    def test_original_maturity_just_under_1yr_zeroed(self, crr_config: CalculationConfig) -> None:
        """Original maturity = 0.99 year: ineligible."""
        exposure_date = crr_config.reporting_date + timedelta(days=int(3 * 365.25))
        lf = _make_collateral(
            coll_maturity_years=0.5,
            exposure_maturity_date=exposure_date,
            original_maturity_years=0.99,
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_maturity_mismatch(lf, crr_config).collect()

        assert result["maturity_adjustment_factor"][0] == pytest.approx(0.0)
        assert result["value_after_maturity_adj"][0] == pytest.approx(0.0)

    def test_original_maturity_no_mismatch_not_checked(self, crr_config: CalculationConfig) -> None:
        """When collateral >= exposure maturity: original maturity check skipped."""
        exposure_date = crr_config.reporting_date + timedelta(days=int(1 * 365.25))
        lf = _make_collateral(
            coll_maturity_years=2.0,
            exposure_maturity_date=exposure_date,
            original_maturity_years=0.5,  # would fail if checked
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_maturity_mismatch(lf, crr_config).collect()

        # No mismatch → factor 1.0, original maturity irrelevant
        assert result["maturity_adjustment_factor"][0] == pytest.approx(1.0)

    def test_null_original_maturity_defaults_permissive(
        self, crr_config: CalculationConfig
    ) -> None:
        """Null original maturity defaults to >= 1yr (backward compatible)."""
        exposure_date = crr_config.reporting_date + timedelta(days=int(3 * 365.25))
        lf = _make_collateral(
            coll_maturity_years=1.0,
            exposure_maturity_date=exposure_date,
            original_maturity_years=None,  # Will use column with null
        )
        # Add the column but with null
        lf = lf.with_columns(pl.lit(None).cast(pl.Float64).alias("original_maturity_years"))
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_maturity_mismatch(lf, crr_config).collect()

        # Should get CVAM adjustment, not zero (null treated as >= 1yr)
        assert result["maturity_adjustment_factor"][0] > 0.0

    def test_missing_column_defaults_permissive(self, crr_config: CalculationConfig) -> None:
        """When original_maturity_years column is absent: no ineligibility check."""
        exposure_date = crr_config.reporting_date + timedelta(days=int(3 * 365.25))
        # No original_maturity_years in data at all
        lf = _make_collateral(
            coll_maturity_years=1.0,
            exposure_maturity_date=exposure_date,
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_maturity_mismatch(lf, crr_config).collect()

        # Should work normally — backward compatible
        assert result["maturity_adjustment_factor"][0] > 0.0

    def test_b31_same_original_maturity_check(self, b31_config: CalculationConfig) -> None:
        """Art. 237(2) original maturity check applies identically under Basel 3.1."""
        exposure_date = b31_config.reporting_date + timedelta(days=int(3 * 365.25))
        lf = _make_collateral(
            coll_maturity_years=0.5,
            exposure_maturity_date=exposure_date,
            original_maturity_years=0.5,
        )
        calc = HaircutCalculator(is_basel_3_1=True)
        result = calc.apply_maturity_mismatch(lf, b31_config).collect()

        assert result["maturity_adjustment_factor"][0] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Art. 162(3)/237(2) — 1-day maturity floor exposure (vectorized path)
# ---------------------------------------------------------------------------


class TestOneDayMaturityFloorIneligibility:
    """Art. 162(3)/237(2): any mismatch on 1-day M floor exposures → ineligible."""

    def test_one_day_floor_with_mismatch_zeroed(self, crr_config: CalculationConfig) -> None:
        """Repo/SFT exposure (1-day M floor) with mismatched collateral → zeroed."""
        exposure_date = crr_config.reporting_date + timedelta(days=int(3 * 365.25))
        lf = _make_collateral(
            coll_maturity_years=2.0,  # Would normally get CVAM
            exposure_maturity_date=exposure_date,
            exposure_has_one_day_maturity_floor=True,
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_maturity_mismatch(lf, crr_config).collect()

        assert result["maturity_adjustment_factor"][0] == pytest.approx(0.0)
        assert result["value_after_maturity_adj"][0] == pytest.approx(0.0)

    def test_one_day_floor_no_mismatch_not_checked(self, crr_config: CalculationConfig) -> None:
        """When collateral >= exposure maturity: 1-day floor doesn't trigger."""
        exposure_date = crr_config.reporting_date + timedelta(days=int(1 * 365.25))
        lf = _make_collateral(
            coll_maturity_years=2.0,
            exposure_maturity_date=exposure_date,
            exposure_has_one_day_maturity_floor=True,
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_maturity_mismatch(lf, crr_config).collect()

        # No mismatch → factor 1.0
        assert result["maturity_adjustment_factor"][0] == pytest.approx(1.0)

    def test_one_day_floor_false_allows_cvam(self, crr_config: CalculationConfig) -> None:
        """Non-repo exposure (floor=False) with mismatch → normal CVAM."""
        exposure_date = crr_config.reporting_date + timedelta(days=int(3 * 365.25))
        lf = _make_collateral(
            coll_maturity_years=2.0,
            exposure_maturity_date=exposure_date,
            exposure_has_one_day_maturity_floor=False,
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_maturity_mismatch(lf, crr_config).collect()

        # Should get positive CVAM factor
        assert result["maturity_adjustment_factor"][0] > 0.0
        assert result["value_after_maturity_adj"][0] > 0.0

    def test_null_floor_defaults_false(self, crr_config: CalculationConfig) -> None:
        """Null 1-day floor flag defaults to False (permissive/backward compat)."""
        exposure_date = crr_config.reporting_date + timedelta(days=int(3 * 365.25))
        lf = _make_collateral(
            coll_maturity_years=2.0,
            exposure_maturity_date=exposure_date,
        )
        lf = lf.with_columns(
            pl.lit(None).cast(pl.Boolean).alias("exposure_has_one_day_maturity_floor")
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_maturity_mismatch(lf, crr_config).collect()

        # Should get positive CVAM factor (null treated as False)
        assert result["maturity_adjustment_factor"][0] > 0.0

    def test_missing_floor_column_defaults_permissive(self, crr_config: CalculationConfig) -> None:
        """When exposure_has_one_day_maturity_floor column absent: no check applied."""
        exposure_date = crr_config.reporting_date + timedelta(days=int(3 * 365.25))
        lf = _make_collateral(
            coll_maturity_years=2.0,
            exposure_maturity_date=exposure_date,
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_maturity_mismatch(lf, crr_config).collect()

        assert result["maturity_adjustment_factor"][0] > 0.0

    def test_b31_same_one_day_floor_check(self, b31_config: CalculationConfig) -> None:
        """Art. 162(3)/237(2) 1-day floor check applies identically under Basel 3.1."""
        exposure_date = b31_config.reporting_date + timedelta(days=int(3 * 365.25))
        lf = _make_collateral(
            coll_maturity_years=2.0,
            exposure_maturity_date=exposure_date,
            exposure_has_one_day_maturity_floor=True,
        )
        calc = HaircutCalculator(is_basel_3_1=True)
        result = calc.apply_maturity_mismatch(lf, b31_config).collect()

        assert result["maturity_adjustment_factor"][0] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Combined conditions (vectorized path)
# ---------------------------------------------------------------------------


class TestCombinedIneligibilityConditions:
    """Test interaction between Art. 237(2) conditions."""

    def test_both_conditions_trigger(self, crr_config: CalculationConfig) -> None:
        """Both original_maturity <1yr AND 1-day floor → still zeroed."""
        exposure_date = crr_config.reporting_date + timedelta(days=int(3 * 365.25))
        lf = _make_collateral(
            coll_maturity_years=0.5,
            exposure_maturity_date=exposure_date,
            original_maturity_years=0.5,
            exposure_has_one_day_maturity_floor=True,
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_maturity_mismatch(lf, crr_config).collect()

        assert result["maturity_adjustment_factor"][0] == pytest.approx(0.0)

    def test_3month_check_still_applies(self, crr_config: CalculationConfig) -> None:
        """Art. 237(2)(a) <3 month check is unaffected by new conditions."""
        exposure_date = crr_config.reporting_date + timedelta(days=int(3 * 365.25))
        lf = _make_collateral(
            coll_maturity_years=0.1,
            exposure_maturity_date=exposure_date,
            original_maturity_years=5.0,  # would pass orig maturity check
            exposure_has_one_day_maturity_floor=False,  # would pass floor check
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_maturity_mismatch(lf, crr_config).collect()

        assert result["maturity_adjustment_factor"][0] == pytest.approx(0.0)

    def test_mixed_batch_all_conditions(self, crr_config: CalculationConfig) -> None:
        """Mixed batch: 4 exposures testing different Art. 237(2) conditions."""
        base = crr_config.reporting_date
        lf = pl.LazyFrame(
            {
                "residual_maturity_years": [2.0, 0.5, 2.0, 1.0],
                "exposure_maturity": [
                    base + timedelta(days=int(3 * 365.25)),  # 3yr: mismatch → CVAM
                    base + timedelta(days=int(3 * 365.25)),  # 3yr: orig <1yr → zeroed
                    base + timedelta(days=int(3 * 365.25)),  # 3yr: 1-day floor → zeroed
                    base + timedelta(days=int(3 * 365.25)),  # 3yr: normal CVAM
                ],
                "value_after_haircut": [1000.0, 1000.0, 1000.0, 1000.0],
                "original_maturity_years": [5.0, 0.5, 5.0, 3.0],
                "exposure_has_one_day_maturity_floor": [False, False, True, False],
            },
            schema={
                "residual_maturity_years": pl.Float64,
                "exposure_maturity": pl.Date,
                "value_after_haircut": pl.Float64,
                "original_maturity_years": pl.Float64,
                "exposure_has_one_day_maturity_floor": pl.Boolean,
            },
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_maturity_mismatch(lf, crr_config).collect()

        factors = result["maturity_adjustment_factor"].to_list()

        # Row 0: normal mismatch → positive CVAM factor
        assert factors[0] > 0.0
        # Row 1: orig maturity 0.5yr → zeroed
        assert factors[1] == pytest.approx(0.0)
        # Row 2: 1-day floor → zeroed
        assert factors[2] == pytest.approx(0.0)
        # Row 3: normal mismatch → positive CVAM factor
        assert factors[3] > 0.0

    def test_existing_cvam_formula_unchanged(self, crr_config: CalculationConfig) -> None:
        """Verify CVAM formula still produces correct values when conditions don't trigger."""
        # 3yr exposure, 2yr collateral, 5yr original maturity, no floor
        exposure_date = crr_config.reporting_date + timedelta(days=int(3 * 365.25))
        lf = _make_collateral(
            coll_maturity_years=2.0,
            exposure_maturity_date=exposure_date,
            original_maturity_years=5.0,
            exposure_has_one_day_maturity_floor=False,
        )
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.apply_maturity_mismatch(lf, crr_config).collect()

        # CVAM = (2.0 - 0.25) / (3.0 - 0.25) = 1.75 / 2.75 ≈ 0.6364
        assert result["maturity_adjustment_factor"][0] == pytest.approx(1.75 / 2.75, rel=1e-3)
        assert result["value_after_maturity_adj"][0] == pytest.approx(1000.0 * 1.75 / 2.75, rel=1)


# ---------------------------------------------------------------------------
# Scalar API — calculate_maturity_mismatch_adjustment
# ---------------------------------------------------------------------------


class TestScalarMaturityMismatchArt237:
    """Art. 237(2) conditions in the scalar calculate_maturity_mismatch_adjustment."""

    def test_original_maturity_under_1yr_zeroed(self) -> None:
        """Original maturity 0.5yr → value zeroed."""
        adjusted, desc = calculate_maturity_mismatch_adjustment(
            collateral_value=Decimal("1000"),
            collateral_maturity_years=0.5,
            exposure_maturity_years=3.0,
            original_maturity_years=0.5,
        )
        assert adjusted == Decimal("0")
        assert "Art. 237(2)" in desc

    def test_original_maturity_1yr_eligible(self) -> None:
        """Original maturity exactly 1.0yr → eligible (condition is < 1yr)."""
        adjusted, _ = calculate_maturity_mismatch_adjustment(
            collateral_value=Decimal("1000"),
            collateral_maturity_years=0.5,
            exposure_maturity_years=3.0,
            original_maturity_years=1.0,
        )
        # Gets CVAM formula, not zero
        assert adjusted > Decimal("0")

    def test_original_maturity_none_permissive(self) -> None:
        """original_maturity_years=None → no ineligibility check (backward compat)."""
        adjusted, _ = calculate_maturity_mismatch_adjustment(
            collateral_value=Decimal("1000"),
            collateral_maturity_years=0.5,
            exposure_maturity_years=3.0,
            original_maturity_years=None,
        )
        # Gets CVAM formula, not zero
        assert adjusted > Decimal("0")

    def test_one_day_floor_zeroed(self) -> None:
        """1-day M floor exposure with mismatch → zeroed."""
        adjusted, desc = calculate_maturity_mismatch_adjustment(
            collateral_value=Decimal("1000"),
            collateral_maturity_years=2.0,
            exposure_maturity_years=3.0,
            has_one_day_maturity_floor=True,
        )
        assert adjusted == Decimal("0")
        assert "Art. 237(2)" in desc or "162(3)" in desc

    def test_one_day_floor_false_allows_cvam(self) -> None:
        """1-day M floor = False → normal CVAM."""
        adjusted, _ = calculate_maturity_mismatch_adjustment(
            collateral_value=Decimal("1000"),
            collateral_maturity_years=2.0,
            exposure_maturity_years=3.0,
            has_one_day_maturity_floor=False,
        )
        assert adjusted > Decimal("0")

    def test_no_mismatch_skips_all_checks(self) -> None:
        """No mismatch → all Art. 237(2) checks skipped."""
        adjusted, desc = calculate_maturity_mismatch_adjustment(
            collateral_value=Decimal("1000"),
            collateral_maturity_years=5.0,
            exposure_maturity_years=3.0,
            original_maturity_years=0.5,  # Would fail
            has_one_day_maturity_floor=True,  # Would fail
        )
        assert adjusted == Decimal("1000")
        assert "No maturity mismatch" in desc

    def test_residual_under_3m_still_zeroed(self) -> None:
        """Residual maturity < 3 months is checked before original maturity."""
        adjusted, desc = calculate_maturity_mismatch_adjustment(
            collateral_value=Decimal("1000"),
            collateral_maturity_years=0.1,
            exposure_maturity_years=3.0,
            original_maturity_years=5.0,  # Would pass
            has_one_day_maturity_floor=False,  # Would pass
        )
        assert adjusted == Decimal("0")
        assert "3 months" in desc

    def test_cvam_formula_unchanged_when_eligible(self) -> None:
        """CVAM formula produces correct value when Art. 237(2) conditions pass."""
        adjusted, desc = calculate_maturity_mismatch_adjustment(
            collateral_value=Decimal("1000"),
            collateral_maturity_years=2.0,
            exposure_maturity_years=5.0,
            original_maturity_years=3.0,
            has_one_day_maturity_floor=False,
        )
        # CVAM = (2.0 - 0.25) / (5.0 - 0.25) = 1.75 / 4.75 ≈ 0.3684
        expected_factor = Decimal(str(1.75 / 4.75))
        expected_value = Decimal("1000") * expected_factor
        assert abs(adjusted - expected_value) < Decimal("0.01")
        assert "Maturity adj" in desc
