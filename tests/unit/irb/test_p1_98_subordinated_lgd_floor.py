"""
P1.98 — Subordinated Corporate A-IRB LGD floor must be 25% (not 50%).

Pipeline stage: IRB calculator — _lgd_floor_expression fallback path
    (has_exposure_class=False, has_seniority=True, seniority="subordinated")

Bug: _lgd_floor_expression() routes subordinated to floors.subordinated_unsecured
    (Decimal("0.50")) when exposure_class column is absent. Art. 161(5) mandates
    a SINGLE 25% floor for ALL unsecured corporate A-IRB exposures regardless of
    seniority. The 50% value is the F-IRB supervisory LGD (Art. 161(1)(b)), not
    an A-IRB floor.

Expected (post-fix): lgd_floor = 0.25 → lgd_floored = max(lgd_own=0.10, 0.25) = 0.25

References:
    - PRA PS1/26 Art. 161(5): A-IRB unsecured corporate LGD floor 25%.
    - PRA PS1/26 Art. 161(1)(b): F-IRB supervisory LGD 75% for subordinated.
    - Bug site: src/rwa_calc/engine/irb/formulas.py lines 157-166.
    - Config:   src/rwa_calc/contracts/config.py LGDFloors.subordinated_unsecured.
    - Spec:     docs/specifications/crr/airb-calculation.md lines 77-89.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.contract_columns import pad_crm_exit_defaults as _pad
from tests.fixtures.p1_98.p1_98 import (
    EFFECTIVE_MATURITY,
    EXPECTED_CORRELATION,
    EXPECTED_EL,
    EXPECTED_K,
    EXPECTED_LGD_FLOOR,
    EXPECTED_LGD_FLOORED,
    EXPECTED_MA,
    EXPECTED_PD_FLOORED,
    EXPECTED_RISK_WEIGHT,
    EXPECTED_RWA,
    LGD_OWN,
    PD_OWN,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb.formulas import _lgd_floor_expression

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture()
def b31_config() -> CalculationConfig:
    """Basel 3.1 config (reporting date 2026-01-01 aligns with scenario fixtures)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2026, 1, 1))


# =============================================================================
# P1.98 — PRIMARY ASSERTION: LGD floor on fallback path must be 25%
# =============================================================================


class TestP198SubordinatedLGDFloor:
    """P1.98: Subordinated corporate A-IRB — LGD floor fallback path.

    Regulatory basis: PRA PS1/26 Art. 161(5) — single 25% floor for all
    unsecured corporate A-IRB exposures regardless of seniority. The 50%
    subordinated supervisory LGD (Art. 161(1)(b)) is an F-IRB value only.
    """

    def test_p1_98_subordinated_fallback_floor_is_25pct_not_50pct(
        self, b31_config: CalculationConfig
    ) -> None:
        """Art. 161(5): subordinated corporate A-IRB LGD floor = 25%, not 50%.

        Exercises _lgd_floor_expression fallback path directly:
            has_exposure_class=False (exposure_class column absent from frame)
            has_seniority=True       (seniority column present)
            seniority="subordinated"

        The current implementation returns floors.subordinated_unsecured = 0.50.
        The correct value per Art. 161(5) is floors.unsecured = 0.25.

        Primary assertion: lgd_floored == EXPECTED_LGD_FLOOR (0.25).
        """
        # Arrange: synthetic frame with seniority only — no exposure_class column
        lf = pl.LazyFrame(
            {
                "lgd": [LGD_OWN],  # 0.10 — below 25% floor, floor binds
                "seniority": ["subordinated"],
            }
        )
        lgd_floor_expr = _lgd_floor_expression(
            b31_config, has_seniority=True, has_exposure_class=False
        )

        # Act: apply LGD floor expression
        result = lf.with_columns(
            lgd_floor_expr.alias("lgd_floor"),
            pl.max_horizontal(pl.col("lgd"), lgd_floor_expr).alias("lgd_floored"),
        ).collect()

        # Assert: floor value must be 25% per Art. 161(5), not 50%
        assert result["lgd_floor"][0] == pytest.approx(EXPECTED_LGD_FLOOR, abs=1e-9), (
            f"LGD floor for subordinated corporate (no exposure_class) must be "
            f"{EXPECTED_LGD_FLOOR} per Art. 161(5), got {result['lgd_floor'][0]}"
        )

    def test_p1_98_lgd_floored_value_25pct(self, b31_config: CalculationConfig) -> None:
        """max(lgd_own=0.10, floor=0.25) = 0.25 for subordinated corporate A-IRB.

        Confirms the floored LGD used in capital computation equals 0.25, not 0.50.
        """
        # Arrange
        lf = pl.LazyFrame(
            {
                "lgd": [LGD_OWN],  # 0.10 — below floor
                "seniority": ["subordinated"],
            }
        )
        lgd_floor_expr = _lgd_floor_expression(
            b31_config, has_seniority=True, has_exposure_class=False
        )

        # Act
        result = lf.with_columns(
            pl.max_horizontal(pl.col("lgd"), lgd_floor_expr).alias("lgd_floored"),
        ).collect()

        # Assert
        assert result["lgd_floored"][0] == pytest.approx(EXPECTED_LGD_FLOORED, abs=1e-9), (
            f"lgd_floored must be {EXPECTED_LGD_FLOORED} (floor binds), "
            f"got {result['lgd_floored'][0]}"
        )

    def test_p1_98_senior_unsecured_fallback_floor_unchanged_25pct(
        self, b31_config: CalculationConfig
    ) -> None:
        """Senior corporate fallback path still yields 25% (no regression).

        The fix must not break the senior unsecured case on the same fallback path.
        """
        # Arrange
        lf = pl.LazyFrame(
            {
                "lgd": [0.10],
                "seniority": ["senior"],
            }
        )
        lgd_floor_expr = _lgd_floor_expression(
            b31_config, has_seniority=True, has_exposure_class=False
        )

        # Act
        result = lf.with_columns(
            lgd_floor_expr.alias("lgd_floor"),
        ).collect()

        # Assert: senior floor remains 25%
        assert result["lgd_floor"][0] == pytest.approx(0.25, abs=1e-9)

    def test_p1_98_null_seniority_fallback_floor_25pct(self, b31_config: CalculationConfig) -> None:
        """Null seniority on fallback path defaults to senior → 25% floor.

        The fix must handle null seniority (fill_null("senior") path) correctly.
        """
        # Arrange
        lf = pl.LazyFrame(
            {
                "lgd": [0.10],
                "seniority": [None],
            }
        )
        lgd_floor_expr = _lgd_floor_expression(
            b31_config, has_seniority=True, has_exposure_class=False
        )

        # Act
        result = lf.with_columns(
            lgd_floor_expr.alias("lgd_floor"),
        ).collect()

        # Assert: null → senior → 25%
        assert result["lgd_floor"][0] == pytest.approx(0.25, abs=1e-9)


# =============================================================================
# P1.98 — FULL HAND-CALC CHAIN (all formula outputs for the scenario)
# =============================================================================


class TestP198FullHandCalc:
    """P1.98: End-to-end hand-calc chain using apply_irb_formulas with exposure_class.

    Uses apply_irb_formulas with exposure_class="corporate" (correct path) to
    verify the full formula chain produces the expected outputs from the scenario
    proposal when LGD is correctly floored at 25%.

    Note: These assertions will PASS once the fallback-path bug (lines 157-166) is
    fixed AND also confirm the with-exposure_class path was already correct.
    """

    @pytest.fixture()
    def b31_config(self) -> CalculationConfig:
        return CalculationConfig.basel_3_1(reporting_date=date(2026, 1, 1))

    def test_p1_98_pd_floored(self, b31_config: CalculationConfig) -> None:
        """PD floor (Art. 160(1) corporate = 0.0005): PD=0.005 > floor, no change."""
        from rwa_calc.engine.irb.formulas import apply_irb_formulas

        lf = pl.LazyFrame(
            {
                "pd": [PD_OWN],  # 0.005
                "lgd": [LGD_OWN],  # 0.10 — below floor
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "seniority": ["subordinated"],
                "is_airb": [True],
                "effective_maturity": [EFFECTIVE_MATURITY],  # 2.5
            }
        )
        result = apply_irb_formulas(_pad(lf), b31_config).collect()

        assert result["pd_floored"][0] == pytest.approx(EXPECTED_PD_FLOORED, rel=1e-9)

    def test_p1_98_lgd_floored_via_exposure_class(self, b31_config: CalculationConfig) -> None:
        """Via exposure_class='corporate': LGD floored to 25% (Art. 161(5))."""
        from rwa_calc.engine.irb.formulas import apply_irb_formulas

        lf = pl.LazyFrame(
            {
                "pd": [PD_OWN],
                "lgd": [LGD_OWN],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "seniority": ["subordinated"],
                "is_airb": [True],
                "effective_maturity": [EFFECTIVE_MATURITY],
            }
        )
        result = apply_irb_formulas(_pad(lf), b31_config).collect()

        assert result["lgd_floored"][0] == pytest.approx(EXPECTED_LGD_FLOORED, abs=1e-9)

    def test_p1_98_correlation(self, b31_config: CalculationConfig) -> None:
        """Correlation R ≈ 0.21346 for corporate PD=0.005 (Art. 153)."""
        from rwa_calc.engine.irb.formulas import apply_irb_formulas

        lf = pl.LazyFrame(
            {
                "pd": [PD_OWN],
                "lgd": [LGD_OWN],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "seniority": ["subordinated"],
                "is_airb": [True],
                "effective_maturity": [EFFECTIVE_MATURITY],
            }
        )
        result = apply_irb_formulas(_pad(lf), b31_config).collect()

        assert result["correlation"][0] == pytest.approx(EXPECTED_CORRELATION, rel=1e-6)

    def test_p1_98_capital_k(self, b31_config: CalculationConfig) -> None:
        """Capital K ≈ 0.023166 when LGD correctly floored at 0.25."""
        from rwa_calc.engine.irb.formulas import apply_irb_formulas

        lf = pl.LazyFrame(
            {
                "pd": [PD_OWN],
                "lgd": [LGD_OWN],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "seniority": ["subordinated"],
                "is_airb": [True],
                "effective_maturity": [EFFECTIVE_MATURITY],
            }
        )
        result = apply_irb_formulas(_pad(lf), b31_config).collect()

        assert result["k"][0] == pytest.approx(EXPECTED_K, rel=1e-3)

    def test_p1_98_maturity_adjustment(self, b31_config: CalculationConfig) -> None:
        """MA ≈ 1.33454 for M=2.5, PD=0.005 (M-2.5=0 simplifies formula)."""
        from rwa_calc.engine.irb.formulas import apply_irb_formulas

        lf = pl.LazyFrame(
            {
                "pd": [PD_OWN],
                "lgd": [LGD_OWN],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "seniority": ["subordinated"],
                "is_airb": [True],
                "effective_maturity": [EFFECTIVE_MATURITY],
            }
        )
        result = apply_irb_formulas(_pad(lf), b31_config).collect()

        assert result["maturity_adjustment"][0] == pytest.approx(EXPECTED_MA, rel=1e-4)

    def test_p1_98_risk_weight(self, b31_config: CalculationConfig) -> None:
        """RW ≈ 0.38646 (≈38.6%) when LGD correctly floored at 0.25."""
        from rwa_calc.engine.irb.formulas import apply_irb_formulas

        lf = pl.LazyFrame(
            {
                "pd": [PD_OWN],
                "lgd": [LGD_OWN],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "seniority": ["subordinated"],
                "is_airb": [True],
                "effective_maturity": [EFFECTIVE_MATURITY],
            }
        )
        result = apply_irb_formulas(_pad(lf), b31_config).collect()

        assert result["risk_weight"][0] == pytest.approx(EXPECTED_RISK_WEIGHT, rel=1e-3)

    def test_p1_98_rwa(self, b31_config: CalculationConfig) -> None:
        """RWA ≈ 386,459 GBP (EAD=1,000,000 × RW≈0.38646)."""
        from rwa_calc.engine.irb.formulas import apply_irb_formulas

        lf = pl.LazyFrame(
            {
                "pd": [PD_OWN],
                "lgd": [LGD_OWN],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "seniority": ["subordinated"],
                "is_airb": [True],
                "effective_maturity": [EFFECTIVE_MATURITY],
            }
        )
        result = apply_irb_formulas(_pad(lf), b31_config).collect()

        assert result["rwa"][0] == pytest.approx(EXPECTED_RWA, rel=1e-3)

    def test_p1_98_expected_loss(self, b31_config: CalculationConfig) -> None:
        """EL = PD × LGD_floored × EAD = 0.005 × 0.25 × 1,000,000 = 1,250."""
        from rwa_calc.engine.irb.formulas import apply_irb_formulas

        lf = pl.LazyFrame(
            {
                "pd": [PD_OWN],
                "lgd": [LGD_OWN],
                "ead_final": [1_000_000.0],
                "exposure_class": ["corporate"],
                "seniority": ["subordinated"],
                "is_airb": [True],
                "effective_maturity": [EFFECTIVE_MATURITY],
            }
        )
        result = apply_irb_formulas(_pad(lf), b31_config).collect()

        assert result["expected_loss"][0] == pytest.approx(EXPECTED_EL, abs=1.0)
