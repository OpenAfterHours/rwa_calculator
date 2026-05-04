"""
Basel 3.1 Scenario P1.182: PE/VC Long-Established Carve-Out (B31-L24).

Tests PRA PS1/26 Art. 133(4) / Glossary — the business-age threshold that
distinguishes standard 250% equity (long-established PE, >= 5 years) from
higher-risk 400% equity (young PE, < 5 years or null).

Key assertions:
    EQ_PE_LEGACY_001: private_equity, business_age_years=12.0 → RW=250%, RWA=2,500,000
    EQ_PE_BUG_001:    private_equity, business_age_years=2.0  → RW=400%, RWA=4,000,000
    EQ_PE_DIVERSIFIED_001: private_equity_diversified, business_age_years=null → RW=400%, RWA=4,000,000

Bug under test (pre-fix):
    In engine/equity/calculator.py _apply_b31_equity_weights_sa(), the
    private_equity branch unconditionally assigns 400% regardless of business_age_years:
        .when(pl.col("equity_type") == "private_equity")
        .then(pl.lit(_B31_SA_RW[EquityType.PRIVATE_EQUITY]))   # always 400%
    This ignores the business_age_years >= 5.0 long-established carve-out entirely.

    Failure mode (primary):
        EQ_PE_LEGACY_001 → risk_weight=4.00, rwa=4_000_000  (wrong, should be 2.50/2.5m)

Regression guards (already correct pre-fix):
    EQ_PE_BUG_001       → risk_weight=4.00, rwa=4_000_000  (correct, young PE)
    EQ_PE_DIVERSIFIED_001 → risk_weight=4.00, rwa=4_000_000  (correct, null=conservative)

Config: CalculationConfig.basel_3_1(reporting_date=date(2030, 1, 1))
    2030-01-01 is steady-state — all transitional floors have completed
    their phase-in (PRA Rules 4.1/4.2 converge to full weight in 2030).
    Transitional max for higher-risk: 400% (same as Art. 133(4)), so the
    floor never bites even if enabled.

Regulatory references:
    - PRA PS1/26 Art. 133(3): Standard equity = 250%
    - PRA PS1/26 Art. 133(4): Higher-risk (unlisted + business < 5yr) = 400%
    - PRA PS1/26 Glossary p.5: definition of "long-established" (<5 years old)
    - src/rwa_calc/engine/equity/calculator.py: _apply_b31_equity_weights_sa()
    - tests/fixtures/p1_182/p1_182.py: fixture constants
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.equity.calculator import EquityCalculator

# ---------------------------------------------------------------------------
# Scenario constants (mirror tests/fixtures/p1_182/p1_182.py)
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2030, 1, 1)  # steady-state, no transitional floor

_EAD = 1_000_000.0  # fair_value = 1,000,000 GBP for all three rows

# B31-L24 primary: long-established PE (12 yr >= 5 yr threshold) → 250%
_EXPOSURE_LEGACY = "EQ_PE_LEGACY_001"
_BUSINESS_AGE_LEGACY = 12.0
_EXPECTED_RW_LEGACY = 2.50   # Art. 133(3) standard equity
_EXPECTED_RWA_LEGACY = 2_500_000.0

# Regression 1: young PE (2 yr < 5 yr threshold) → 400%
_EXPOSURE_BUG = "EQ_PE_BUG_001"
_BUSINESS_AGE_YOUNG = 2.0
_EXPECTED_RW_YOUNG = 4.00   # Art. 133(4) higher-risk
_EXPECTED_RWA_YOUNG = 4_000_000.0

# Regression 2: diversified PE, null age → conservative 400%
_EXPOSURE_DIVERSIFIED = "EQ_PE_DIVERSIFIED_001"
_EXPECTED_RW_DIVERSIFIED = 4.00   # null treated as <5y → Art. 133(4)
_EXPECTED_RWA_DIVERSIFIED = 4_000_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_equity_lf(
    exposure_reference: str,
    equity_type: str,
    business_age_years: float | None,
    ead: float = _EAD,
) -> pl.LazyFrame:
    """
    Build a single-row equity LazyFrame with business_age_years for calculate_branch.

    Includes the business_age_years column that the engine-implementer must
    read to resolve the long-established (>= 5y) carve-out per Art. 133(4).
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [exposure_reference],
            "ead_final": [ead],
            "equity_type": [equity_type],
            "is_speculative": [False],
            "is_exchange_traded": [False],
            "is_government_supported": [False],
            "is_diversified_portfolio": [False],
            "ciu_approach": pl.Series([None], dtype=pl.String),
            "ciu_mandate_rw": pl.Series([None], dtype=pl.Float64),
            "ciu_third_party_calc": pl.Series([None], dtype=pl.Boolean),
            "business_age_years": pl.Series([business_age_years], dtype=pl.Float64),
        }
    )


def _run(lf: pl.LazyFrame, config: CalculationConfig) -> dict:
    """Run calculate_branch and return the first row as a dict."""
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
# B31-L24: Long-established PE — PRIMARY ASSERTION (WILL FAIL today)
# ---------------------------------------------------------------------------


class TestB31L24LongEstablishedPE:
    """
    B31-L24: Private equity with business_age_years >= 5 years is standard
    equity under Art. 133(3) and must receive 250%, not 400%.

    Input:
        equity_type=private_equity, business_age_years=12.0, EAD=£1,000,000
        is_speculative=False, is_exchange_traded=False
    Expected:
        risk_weight=2.50 (Art. 133(3) standard equity)
        rwa=2,500,000

    Pre-fix failure mode:
        Engine returns risk_weight=4.00 / rwa=4,000,000 because
        _apply_b31_equity_weights_sa() ignores business_age_years.
    """

    def test_b31_l24_long_established_pe_risk_weight_is_250_pct(
        self,
        b31_2030_config: CalculationConfig,
    ) -> None:
        """
        B31-L24 primary: long-established PE (12yr) risk weight == 2.50.

        Arrange: private_equity, business_age_years=12.0 >= 5.0, EAD=£1m.
        Act: calculate_branch with Basel 3.1 steady-state config.
        Assert: risk_weight == 2.50 (Art. 133(3), not Art. 133(4)).

        Failure mode before fix: risk_weight == 4.00 (engine ignores age).
        PRA PS1/26 Art. 133(3): long-established unlisted equity → 250%.
        """
        # Arrange
        lf = _build_equity_lf(
            exposure_reference=_EXPOSURE_LEGACY,
            equity_type="private_equity",
            business_age_years=_BUSINESS_AGE_LEGACY,
        )

        # Act
        result = _run(lf, b31_2030_config)

        # Assert
        assert result["risk_weight"] == pytest.approx(_EXPECTED_RW_LEGACY, abs=1e-4), (
            f"B31-L24: long-established PE (business_age_years={_BUSINESS_AGE_LEGACY}) "
            f"should receive 250% (Art. 133(3)), got {result['risk_weight']:.4f}. "
            f"Engine does not yet apply the business_age_years >= 5.0 carve-out "
            f"in _apply_b31_equity_weights_sa()."
        )

    def test_b31_l24_long_established_pe_rwa_is_2_5m(
        self,
        b31_2030_config: CalculationConfig,
    ) -> None:
        """
        B31-L24 primary: RWA = £1,000,000 × 250% = £2,500,000.

        Arrange: private_equity, business_age_years=12.0, EAD=£1m.
        Act: calculate_branch with Basel 3.1 steady-state config.
        Assert: rwa == 2_500_000.

        Failure mode before fix: rwa == 4_000_000 (400% incorrectly applied).
        """
        # Arrange
        lf = _build_equity_lf(
            exposure_reference=_EXPOSURE_LEGACY,
            equity_type="private_equity",
            business_age_years=_BUSINESS_AGE_LEGACY,
        )

        # Act
        result = _run(lf, b31_2030_config)

        # Assert
        assert result["rwa"] == pytest.approx(_EXPECTED_RWA_LEGACY, rel=1e-4), (
            f"B31-L24: long-established PE RWA should be {_EXPECTED_RWA_LEGACY:,.0f} "
            f"(£1m × 250%), got {result['rwa']:,.0f}. "
            f"Engine still applies 400% to all private_equity regardless of age."
        )


# ---------------------------------------------------------------------------
# EQ_PE_BUG_001: Young PE — REGRESSION GUARD (must stay 400%)
# ---------------------------------------------------------------------------


class TestB31L24YoungPERegressionGuard:
    """
    Regression guard: young private equity (business_age_years=2.0 < 5.0) must
    remain at 400% (Art. 133(4) higher-risk) after the fix.

    The fix for long-established PE must not accidentally lower the weight
    for PE that genuinely qualifies as higher-risk.

    Input:
        equity_type=private_equity, business_age_years=2.0, EAD=£1,000,000
    Expected:
        risk_weight=4.00, rwa=4,000,000  (unchanged by fix)
    """

    def test_b31_young_pe_risk_weight_is_400_pct(
        self,
        b31_2030_config: CalculationConfig,
    ) -> None:
        """
        Regression: young PE (2yr) must remain at 400%.

        Arrange: private_equity, business_age_years=2.0 < 5.0, EAD=£1m.
        Act: calculate_branch with Basel 3.1 steady-state config.
        Assert: risk_weight == 4.00 (Art. 133(4)).
        """
        # Arrange
        lf = _build_equity_lf(
            exposure_reference=_EXPOSURE_BUG,
            equity_type="private_equity",
            business_age_years=_BUSINESS_AGE_YOUNG,
        )

        # Act
        result = _run(lf, b31_2030_config)

        # Assert
        assert result["risk_weight"] == pytest.approx(_EXPECTED_RW_YOUNG, abs=1e-4), (
            f"Regression: young PE (business_age_years={_BUSINESS_AGE_YOUNG}) "
            f"should remain at 400% (Art. 133(4)), got {result['risk_weight']:.4f}."
        )

    def test_b31_young_pe_rwa_is_4m(
        self,
        b31_2030_config: CalculationConfig,
    ) -> None:
        """
        Regression: young PE RWA = £1,000,000 × 400% = £4,000,000.

        Arrange: private_equity, business_age_years=2.0, EAD=£1m.
        Act: calculate_branch.
        Assert: rwa == 4_000_000.
        """
        # Arrange
        lf = _build_equity_lf(
            exposure_reference=_EXPOSURE_BUG,
            equity_type="private_equity",
            business_age_years=_BUSINESS_AGE_YOUNG,
        )

        # Act
        result = _run(lf, b31_2030_config)

        # Assert
        assert result["rwa"] == pytest.approx(_EXPECTED_RWA_YOUNG, rel=1e-4), (
            f"Regression: young PE RWA should be {_EXPECTED_RWA_YOUNG:,.0f}, "
            f"got {result['rwa']:,.0f}."
        )


# ---------------------------------------------------------------------------
# EQ_PE_DIVERSIFIED_001: Null age — REGRESSION GUARD (null → conservative 400%)
# ---------------------------------------------------------------------------


class TestB31L24NullAgeConservative:
    """
    Regression guard: private_equity_diversified with null business_age_years
    must be treated conservatively as < 5 years (400%) per Art. 133(4).

    When business_age_years is unknown, the engine must default to the
    higher-risk (400%) weight — the firm cannot claim the long-established
    carve-out without evidence of business age >= 5 years.

    Input:
        equity_type=private_equity_diversified, business_age_years=null, EAD=£1,000,000
    Expected:
        risk_weight=4.00, rwa=4,000,000
    """

    def test_b31_null_age_pe_risk_weight_is_400_pct(
        self,
        b31_2030_config: CalculationConfig,
    ) -> None:
        """
        Regression: null business_age_years on PE/VC → conservative 400%.

        Arrange: private_equity_diversified, business_age_years=null, EAD=£1m.
        Act: calculate_branch with Basel 3.1 steady-state config.
        Assert: risk_weight == 4.00 (null treated conservatively as <5y).
        """
        # Arrange
        lf = _build_equity_lf(
            exposure_reference=_EXPOSURE_DIVERSIFIED,
            equity_type="private_equity_diversified",
            business_age_years=None,  # null → conservative → 400%
        )

        # Act
        result = _run(lf, b31_2030_config)

        # Assert
        assert result["risk_weight"] == pytest.approx(_EXPECTED_RW_DIVERSIFIED, abs=1e-4), (
            f"Regression: null business_age_years on PE should be treated "
            f"conservatively as <5yr → 400%, got {result['risk_weight']:.4f}."
        )

    def test_b31_null_age_pe_rwa_is_4m(
        self,
        b31_2030_config: CalculationConfig,
    ) -> None:
        """
        Regression: null age PE/VC RWA = £1,000,000 × 400% = £4,000,000.

        Arrange: private_equity_diversified, business_age_years=null, EAD=£1m.
        Act: calculate_branch.
        Assert: rwa == 4_000_000.
        """
        # Arrange
        lf = _build_equity_lf(
            exposure_reference=_EXPOSURE_DIVERSIFIED,
            equity_type="private_equity_diversified",
            business_age_years=None,
        )

        # Act
        result = _run(lf, b31_2030_config)

        # Assert
        assert result["rwa"] == pytest.approx(_EXPECTED_RWA_DIVERSIFIED, rel=1e-4), (
            f"Regression: null-age PE RWA should be {_EXPECTED_RWA_DIVERSIFIED:,.0f}, "
            f"got {result['rwa']:,.0f}."
        )
