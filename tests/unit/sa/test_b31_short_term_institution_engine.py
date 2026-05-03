"""
Engine-level unit tests for Basel 3.1 ECRA short-term institution risk weights
(CQS 4 and CQS 5 = 50%).

Tests that the SA namespace expression correctly applies the three-way split
mandated by Art. 120(2) Table 4:
    CQS 1-3 → 20%
    CQS 4-5 → 50%   <- the bug: namespace collapses to 20% for CQS <= 5
    CQS 6   → 150%

Pipeline position:
    _b31_append_institution_branches (namespace.py) → SACalculator.calculate_branch

References:
    - PRA PS1/26 Art. 120(2), Table 4
    - BCBS CRE20.17: short-term rated institution weights
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa import SACalculator

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sa_calculator() -> SACalculator:
    """Return an SA Calculator instance."""
    return SACalculator()


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Return a Basel 3.1 configuration (post-2027)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))


# =============================================================================
# CQS 4 SHORT-TERM = 50%
# =============================================================================


class TestB31ECRAShortTermCQS4:
    """Basel 3.1 ECRA short-term CQS 4 institution risk weight = 50%.

    Art. 120(2) Table 4 places CQS 4 in the 50% band, NOT the 20% band
    that covers only CQS 1-3.  The namespace currently uses a single binary
    split (cqs <= 5 → 20%, else → 150%) which incorrectly assigns 20% to
    CQS 4 and 5.
    """

    def test_b31_ecra_cqs4_short_term_risk_weight_is_50pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Art. 120(2) Table 4: CQS 4 rated institution with ≤3m maturity → 50%.

        Arrange: EUR 1m institution, CQS 4, original maturity 0.247y (≈3m).
        Act:     run SA calculator under Basel 3.1 config.
        Assert:  risk_weight == 0.50.
        """
        # Arrange
        ead = Decimal("1_000_000")

        # Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=ead,
            exposure_class="institution",
            cqs=4,
            residual_maturity_years=0.247,
            config=b31_config,
        )

        # Assert
        assert float(result["risk_weight"]) == pytest.approx(0.50), (
            f"CQS 4 short-term institution RW: expected 0.50 (50%), got {result['risk_weight']}"
        )

    def test_b31_ecra_cqs4_short_term_rwa(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Art. 120(2) Table 4: CQS 4, EUR 1m, ≤3m → RWA = EUR 500k.

        Arrange: EUR 1m institution, CQS 4, original maturity 0.247y.
        Act:     run SA calculator.
        Assert:  rwa == 500_000.
        """
        # Arrange
        ead = Decimal("1_000_000")

        # Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=ead,
            exposure_class="institution",
            cqs=4,
            residual_maturity_years=0.247,
            config=b31_config,
        )

        # Assert
        assert float(result["rwa"]) == pytest.approx(500_000.0, rel=1e-4), (
            f"CQS 4 short-term RWA: expected 500_000, got {result['rwa']}"
        )

    def test_b31_ecra_cqs4_short_term_exactly_3m_boundary(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Exactly 3 months (0.25y) is still short-term → CQS 4 = 50%."""
        # Arrange
        ead = Decimal("1_000_000")

        # Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=ead,
            exposure_class="institution",
            cqs=4,
            residual_maturity_years=0.25,
            config=b31_config,
        )

        # Assert
        assert float(result["risk_weight"]) == pytest.approx(0.50), (
            f"CQS 4 at exactly 0.25y (3m boundary): expected 0.50, got {result['risk_weight']}"
        )

    def test_b31_ecra_cqs4_long_term_still_100pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CQS 4 with >3m maturity uses long-term ECRA weight (100%) — regression pin."""
        # Arrange
        ead = Decimal("1_000_000")

        # Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=ead,
            exposure_class="institution",
            cqs=4,
            residual_maturity_years=1.0,
            config=b31_config,
        )

        # Assert — this already passes; pin it so the fix does not regress it
        assert float(result["risk_weight"]) == pytest.approx(1.00), (
            f"CQS 4 long-term: expected 1.00 (100%), got {result['risk_weight']}"
        )


# =============================================================================
# CQS 5 SHORT-TERM = 50%
# =============================================================================


class TestB31ECRAShortTermCQS5:
    """Basel 3.1 ECRA short-term CQS 5 institution risk weight = 50%.

    Mirrors TestB31ECRAShortTermCQS4 for the CQS 5 band, which is also
    in the 50% group per Art. 120(2) Table 4.
    """

    def test_b31_ecra_cqs5_short_term_risk_weight_is_50pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Art. 120(2) Table 4: CQS 5 rated institution with ≤3m maturity → 50%.

        Arrange: EUR 1m institution, CQS 5, original maturity 0.247y.
        Act:     run SA calculator under Basel 3.1 config.
        Assert:  risk_weight == 0.50.
        """
        # Arrange
        ead = Decimal("1_000_000")

        # Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=ead,
            exposure_class="institution",
            cqs=5,
            residual_maturity_years=0.247,
            config=b31_config,
        )

        # Assert
        assert float(result["risk_weight"]) == pytest.approx(0.50), (
            f"CQS 5 short-term institution RW: expected 0.50 (50%), got {result['risk_weight']}"
        )

    def test_b31_ecra_cqs5_short_term_rwa(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Art. 120(2) Table 4: CQS 5, EUR 1m, ≤3m → RWA = EUR 500k."""
        # Arrange
        ead = Decimal("1_000_000")

        # Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=ead,
            exposure_class="institution",
            cqs=5,
            residual_maturity_years=0.247,
            config=b31_config,
        )

        # Assert
        assert float(result["rwa"]) == pytest.approx(500_000.0, rel=1e-4), (
            f"CQS 5 short-term RWA: expected 500_000, got {result['rwa']}"
        )

    def test_b31_ecra_cqs5_long_term_still_100pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CQS 5 with >3m maturity uses long-term ECRA weight (100%) — regression pin."""
        # Arrange
        ead = Decimal("1_000_000")

        # Act
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=ead,
            exposure_class="institution",
            cqs=5,
            residual_maturity_years=1.0,
            config=b31_config,
        )

        # Assert — already passes; pin it
        assert float(result["risk_weight"]) == pytest.approx(1.00), (
            f"CQS 5 long-term: expected 1.00 (100%), got {result['risk_weight']}"
        )


# =============================================================================
# CQS 1-3 REGRESSION — must stay at 20% after the fix
# =============================================================================


@pytest.mark.parametrize(
    "cqs",
    [1, 2, 3],
    ids=["CQS1", "CQS2", "CQS3"],
)
def test_b31_ecra_cqs1_3_short_term_unchanged_at_20pct(
    sa_calculator: SACalculator,
    b31_config: CalculationConfig,
    cqs: int,
) -> None:
    """Art. 120(2) Table 4: CQS 1-3 short-term institution RW must remain 20%.

    Regression guard — the fix to CQS 4/5 must not disturb the CQS 1-3 band.
    """
    # Arrange
    ead = Decimal("1_000_000")

    # Act
    result = calculate_single_sa_exposure(
        sa_calculator,
        ead=ead,
        exposure_class="institution",
        cqs=cqs,
        residual_maturity_years=0.247,
        config=b31_config,
    )

    # Assert
    assert float(result["risk_weight"]) == pytest.approx(0.20), (
        f"CQS {cqs} short-term RW: expected 0.20 (20%), got {result['risk_weight']}"
    )
