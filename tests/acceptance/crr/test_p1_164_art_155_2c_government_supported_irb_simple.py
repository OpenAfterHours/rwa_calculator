"""
P1.164 — CRR Art. 155(2)(c): GOVERNMENT_SUPPORTED equity must use 370% RW.

Under CRR Art. 155(2) the IRB Simple risk weight approach assigns:
    (a) 290% to exchange-traded equity
    (b) 190% to diversified private equity portfolios
    (c) 370% to all other equity

"Government-supported" equity falls under none of the named sub-categories
(a) or (b) and must therefore be assigned the residual "all other equity" weight
of 370% per Art. 155(2)(c).

The pre-fix engine incorrectly treated government_supported as equivalent to
diversified private equity (190%), yielding an RWA of 570,000 instead of the
correct 1,110,000 for a 300,000 EAD.

Hand calculation:
    EAD     = 300,000
    RW      = 3.70  (Art. 155(2)(c) "all other equity")
    RWA     = 300,000 × 3.70 = 1,110,000

Regulatory Reference:
    CRR Art. 155(2)(c): Simple risk weight method — all other equity 370%
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from tests.fixtures.single_exposure import calculate_single_equity_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.equity.calculator import EquityCalculator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCENARIO_ID = "P1.164"
EAD = Decimal("300000")
EXPECTED_RISK_WEIGHT = 3.70
EXPECTED_RWA = 1_110_000.0
EXPECTED_EAD_FINAL = 300_000.0
EXPECTED_EQUITY_TYPE = "government_supported"

# Pre-fix (buggy) value — regression sentinel
BUGGY_RISK_WEIGHT = 1.90
BUGGY_RWA = 570_000.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def crr_irb_config() -> CalculationConfig:
    """CRR IRB configuration that routes equity through Art. 155 IRB Simple."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def equity_calculator() -> EquityCalculator:
    """Equity calculator instance."""
    return EquityCalculator()


@pytest.fixture
def government_supported_result(
    equity_calculator: EquityCalculator,
    crr_irb_config: CalculationConfig,
) -> dict:
    """Single government_supported equity exposure at EAD=300,000 via CRR IRB."""
    # Arrange
    return calculate_single_equity_exposure(
        equity_calculator,
        ead=EAD,
        equity_type=EXPECTED_EQUITY_TYPE,
        is_government_supported=True,
        config=crr_irb_config,
    )


# ---------------------------------------------------------------------------
# P1.164 — CRR Art. 155(2)(c) Government-Supported Equity IRB Simple Tests
# ---------------------------------------------------------------------------


class TestP1164_GovernmentSupportedIRBSimpleArt155_2c:
    """
    P1.164: government_supported equity under CRR IRB Simple must receive
    370% RW (Art. 155(2)(c) "all other equity"), not 190% diversified-PE rate.

    Pre-fix engine: 190% → RWA = 570,000.
    Post-fix engine: 370% → RWA = 1,110,000.
    """

    def test_p1_164_art_155_2c_government_supported_risk_weight(
        self,
        government_supported_result: dict,
    ) -> None:
        """
        P1.164: government_supported equity RW must be 3.70 (Art. 155(2)(c)).

        Arrange: equity_type=government_supported, is_government_supported=True,
                 EAD=300_000, CRR IRB permission mode.
        Act: calculate_single_equity_exposure via EquityCalculator.calculate_branch.
        Assert: risk_weight == 3.70.
        """
        # Act — result provided by fixture
        actual_rw = government_supported_result["risk_weight"]

        # Assert
        assert actual_rw == pytest.approx(EXPECTED_RISK_WEIGHT, abs=1e-4), (
            f"{SCENARIO_ID}: government_supported equity must use Art. 155(2)(c) "
            f"'all other equity' 370% RW. "
            f"Got {actual_rw:.4f} (pre-fix engine returns {BUGGY_RISK_WEIGHT} as diversified PE)."
        )

    def test_p1_164_art_155_2c_government_supported_rwa(
        self,
        government_supported_result: dict,
    ) -> None:
        """
        P1.164: government_supported equity RWA must be 1,110,000.

        Arrange: EAD=300_000, RW=3.70 (Art. 155(2)(c)).
        Act: calculate_single_equity_exposure.
        Assert: rwa == 1_110_000.0.
        """
        # Act — result provided by fixture
        actual_rwa = government_supported_result["rwa"]

        # Assert
        assert actual_rwa == pytest.approx(EXPECTED_RWA, rel=1e-4), (
            f"{SCENARIO_ID}: RWA = EAD × RW = 300,000 × 3.70 = 1,110,000. "
            f"Got {actual_rwa:,.0f} "
            f"(pre-fix engine returns {BUGGY_RWA:,.0f} using 190% diversified-PE rate)."
        )

    def test_p1_164_art_155_2c_government_supported_ead_final(
        self,
        government_supported_result: dict,
    ) -> None:
        """
        P1.164: ead_final must be 300,000 (no CRM adjustment on equity exposures).

        Arrange: EAD=300_000.
        Act: calculate_single_equity_exposure.
        Assert: ead_final == 300_000.0.
        """
        # Act — result provided by fixture
        actual_ead = government_supported_result["ead_final"]

        # Assert
        assert actual_ead == pytest.approx(EXPECTED_EAD_FINAL), (
            f"{SCENARIO_ID}: ead_final should equal EAD input 300,000. Got {actual_ead:,.0f}."
        )

    def test_p1_164_art_155_2c_government_supported_equity_type(
        self,
        government_supported_result: dict,
    ) -> None:
        """
        P1.164: equity_type must be preserved as 'government_supported'.

        Arrange: equity_type=government_supported.
        Act: calculate_single_equity_exposure.
        Assert: equity_type == 'government_supported' (or equivalent enum value).
        """
        # Act — result provided by fixture
        actual_equity_type = government_supported_result.get("equity_type")

        # Assert
        # Accept either the string value or an enum whose value/name matches
        equity_type_str = (
            actual_equity_type.value
            if hasattr(actual_equity_type, "value")
            else str(actual_equity_type)
        )
        assert equity_type_str == EXPECTED_EQUITY_TYPE, (
            f"{SCENARIO_ID}: equity_type should be '{EXPECTED_EQUITY_TYPE}'. "
            f"Got '{equity_type_str}'."
        )

    def test_p1_164_regression_not_190_percent(
        self,
        government_supported_result: dict,
    ) -> None:
        """
        P1.164 regression sentinel: risk_weight must NOT be 1.90 (diversified PE).

        Confirms the engine no longer misroutes government_supported through
        Art. 155(2)(b) diversified-PE path.

        Assert: risk_weight != 1.90.
        """
        # Act — result provided by fixture
        actual_rw = government_supported_result["risk_weight"]

        # Assert — regression sentinel
        assert actual_rw != pytest.approx(BUGGY_RISK_WEIGHT, abs=1e-4), (
            f"{SCENARIO_ID} regression: risk_weight is still {BUGGY_RISK_WEIGHT} "
            f"(diversified-PE rate Art. 155(2)(b)). "
            f"government_supported must use Art. 155(2)(c) 370% = {EXPECTED_RISK_WEIGHT}."
        )
