"""
Basel 3.1 Scenario P2.19 / B31-L24: Unlisted equity, young business — Art. 133(4) 400%.

Tests that an unlisted equity with business_age_years < 5.0 and is_speculative=False
receives the Art. 133(4) higher-risk weight of 400%, NOT the Art. 133(3) standard 250%.

The defect under test:
    In engine/equity/calculator.py _apply_b31_equity_weights_sa() (line ~548),
    the Art. 133(4) higher-risk condition is gated on:
        equity_type in {private_equity, private_equity_diversified}
    An equity_type="unlisted" row therefore falls through to the OTHERWISE branch
    and receives 250% (Art. 133(3)), even when business_age_years=2.0 < 5.0 and
    is_exchange_traded=False both satisfy Art. 133(4) conditions (a) and (b).

    Post-fix: the condition must be generalised to any non-listed, non-exchange-traded
    equity that meets both Art. 133(4) sub-conditions.

Hand-calculation (Basel 3.1, reporting_date=2030-01-01, steady-state):
    equity_type="unlisted", is_exchange_traded=False  → Art. 133(4)(a): not listed
    business_age_years=2.0 < 5.0                      → Art. 133(4)(b): young business
    is_speculative=False                               → 400% from dynamic condition only
    EAD = fair_value = 1_000_000.0
    RWA = 1_000_000.0 × 4.00 = 4_000_000.0
    rwa_final = 4_000_000.0  (2030 is steady-state; no transitional floor)

Regulatory references:
    - PRA PS1/26 Art. 133(3): Standard unlisted equity = 250%
    - PRA PS1/26 Art. 133(4): Higher-risk unlisted (not exchange-traded + business <5yr) = 400%
    - PRA PS1/26 Glossary p.5: "long-established" = business >= 5 years old
    - src/rwa_calc/engine/equity/calculator.py: _apply_b31_equity_weights_sa() line ~548
    - tests/fixtures/p2_19/p2_19.py: fixture constants (EXPECTED_RISK_WEIGHT etc.)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.equity.calculator import EquityCalculator
from tests.fixtures.p2_19.p2_19 import (
    EXPECTED_EAD,
    EXPECTED_RISK_WEIGHT,
    EXPECTED_RWA,
    EXPECTED_RWA_FINAL,
    EXPOSURE_REF,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2030, 1, 1)  # steady-state; transitional floors fully phased in


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_unlisted_young_equity_lf() -> pl.LazyFrame:
    """
    Build the P2.19 single-row equity LazyFrame for the B31-L24 scenario.

    equity_type="unlisted": base-table SA risk weight is 250% (Art. 133(3)).
    business_age_years=2.0: < 5.0 threshold — Art. 133(4)(b) satisfied.
    is_exchange_traded=False: Art. 133(4)(a) satisfied.
    is_speculative=False: crux — 400% must come from Art. 133(4), NOT speculative path.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [EXPOSURE_REF],
            "ead_final": [EXPECTED_EAD],
            "equity_type": ["unlisted"],
            "is_speculative": [False],
            "is_exchange_traded": [False],
            "is_government_supported": [False],
            "is_diversified_portfolio": [False],
            "ciu_approach": pl.Series([None], dtype=pl.String),
            "ciu_mandate_rw": pl.Series([None], dtype=pl.Float64),
            "ciu_third_party_calc": pl.Series([None], dtype=pl.Boolean),
            "business_age_years": pl.Series([2.0], dtype=pl.Float64),
        }
    )


def _run_calculate_branch(lf: pl.LazyFrame, config: CalculationConfig) -> dict:
    """Run EquityCalculator.calculate_branch and return first row as dict."""
    calculator = EquityCalculator()
    return calculator.calculate_branch(lf, config).collect().row(0, named=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def b31_2030_config() -> CalculationConfig:
    """Basel 3.1 SA config — steady-state 2030-01-01, no transitional floor."""
    return CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE)


# ---------------------------------------------------------------------------
# B31-L24 / P2.19: Unlisted young equity — PRIMARY ASSERTION (FAILS today)
# ---------------------------------------------------------------------------


class TestB31L24UnlistedYoungEquityHigherRisk:
    """
    B31-L24 (P2.19): Unlisted equity with business_age_years < 5 years must
    receive the Art. 133(4) higher-risk weight of 400%, not the Art. 133(3)
    standard weight of 250%.

    Pre-fix defect:
        _apply_b31_equity_weights_sa() gates the Art. 133(4) condition on
        equity_type in {private_equity, private_equity_diversified}.
        equity_type="unlisted" falls through to the OTHERWISE branch → 250%.

    Post-fix requirement:
        Any non-listed, non-exchange-traded equity that satisfies both
        Art. 133(4) sub-conditions receives 400%.
    """

    def test_unlisted_young_equity_gets_400pct_not_250pct(
        self,
        b31_2030_config: CalculationConfig,
    ) -> None:
        """
        B31-L24 primary: unlisted equity with business_age_years=2.0 → risk_weight=4.00.

        Arrange: equity_type="unlisted", business_age_years=2.0, is_speculative=False,
                 is_exchange_traded=False, EAD=£1,000,000.
        Act: calculate_branch with Basel 3.1 steady-state config (2030-01-01).
        Assert: risk_weight == 4.00 (Art. 133(4) 400%, not Art. 133(3) 250%).

        Failure mode before fix:
            risk_weight == 2.50  (engine gates Art. 133(4) on private_equity type only).
        Regulatory reference: PRA PS1/26 Art. 133(4) — higher-risk unlisted equity.
        """
        # Arrange
        lf = _build_unlisted_young_equity_lf()

        # Act
        result = _run_calculate_branch(lf, b31_2030_config)

        # Assert
        assert result["risk_weight"] == pytest.approx(EXPECTED_RISK_WEIGHT, abs=1e-4), (
            f"B31-L24 (P2.19): unlisted equity with business_age_years=2.0 "
            f"should receive Art. 133(4) 400% (risk_weight=4.00), "
            f"got risk_weight={result['risk_weight']:.4f}. "
            f"Engine gates Art. 133(4) on equity_type in {{private_equity, "
            f"private_equity_diversified}} — equity_type='unlisted' falls through "
            f"to 250% (Art. 133(3)) incorrectly."
        )

    def test_unlisted_young_equity_rwa_is_4_000_000(
        self,
        b31_2030_config: CalculationConfig,
    ) -> None:
        """
        B31-L24 primary: RWA = £1,000,000 × 400% = £4,000,000.

        Arrange: equity_type="unlisted", business_age_years=2.0, EAD=£1,000,000.
        Act: calculate_branch with Basel 3.1 steady-state config.
        Assert: rwa == 4_000_000.0.

        Failure mode before fix: rwa == 2_500_000.0 (250% applied instead of 400%).
        """
        # Arrange
        lf = _build_unlisted_young_equity_lf()

        # Act
        result = _run_calculate_branch(lf, b31_2030_config)

        # Assert
        assert result["rwa"] == pytest.approx(EXPECTED_RWA, rel=1e-4), (
            f"B31-L24 (P2.19): unlisted young equity RWA should be "
            f"{EXPECTED_RWA:,.0f} (£1m × 400%), got {result['rwa']:,.0f}. "
            f"Engine returns 2,500,000 (250%) because Art. 133(4) is not "
            f"applied to equity_type='unlisted'."
        )

    def test_unlisted_young_equity_rwa_final_is_4_000_000(
        self,
        b31_2030_config: CalculationConfig,
    ) -> None:
        """
        B31-L24 primary: rwa_final = rwa (no transitional floor in steady-state 2030).

        Arrange: equity_type="unlisted", business_age_years=2.0, EAD=£1,000,000,
                 reporting_date=2030-01-01 (steady-state).
        Act: calculate_branch.
        Assert: rwa_final == 4_000_000.0.
        """
        # Arrange
        lf = _build_unlisted_young_equity_lf()

        # Act
        result = _run_calculate_branch(lf, b31_2030_config)

        # Assert
        assert result["rwa_final"] == pytest.approx(EXPECTED_RWA_FINAL, rel=1e-4), (
            f"B31-L24 (P2.19): rwa_final should equal rwa={EXPECTED_RWA_FINAL:,.0f} "
            f"in steady-state 2030, got {result['rwa_final']:,.0f}."
        )

    def test_unlisted_young_equity_ead_final_is_1_000_000(
        self,
        b31_2030_config: CalculationConfig,
    ) -> None:
        """
        B31-L24: ead_final = fair_value = 1_000_000.0 (no carrying-value override).

        Arrange: equity_type="unlisted", ead_final=£1,000,000.
        Act: calculate_branch.
        Assert: ead_final == 1_000_000.0.
        """
        # Arrange
        lf = _build_unlisted_young_equity_lf()

        # Act
        result = _run_calculate_branch(lf, b31_2030_config)

        # Assert
        assert result["ead_final"] == pytest.approx(EXPECTED_EAD, rel=1e-4), (
            f"B31-L24 (P2.19): ead_final should be {EXPECTED_EAD:,.0f}, "
            f"got {result['ead_final']:,.0f}."
        )
