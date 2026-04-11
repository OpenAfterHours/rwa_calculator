"""
Basel 3.1 Group L: Equity Exposure Acceptance Tests.

Tests validate the production calculator correctly handles equity exposures
under PRA PS1/26 Art. 133 (amended), with IRB equity approaches removed
(Art. 147A) and transitional phase-in schedule (PRA Rules 4.1-4.3).

SA equity weights (B31-L1 through B31-L9):
- Art. 133(1): Subordinated debt / non-equity own funds 150%
- Art. 133(3): Standard equity (listed, unlisted, exchange-traded) 250%
- Art. 133(5): Higher-risk equity (speculative, PE/VC, young unlisted <5yr) 400%
- Art. 133(6): Legislative (government-supported) equity 100%
- Central bank equity 0% (sovereign treatment)
- CIU fallback: listed 250% / unlisted 400% (aligns with Art. 133)

Art. 147A IRB removal (B31-L10):
- IRB config still routes equity to SA (Art. 147A removes equity IRB)

Transitional schedule (B31-L11 through B31-L16):
- PRA Rule 4.1: Standard equity floor 160%/190%/220%/250% (2027-2030)
- PRA Rule 4.2: Higher-risk floor 220%/280%/340%/400% (2027-2030)
- PRA Rule 4.3: Excluded from floor: central_bank, government_supported,
  subordinated_debt, CIU look-through/mandate-based

CIU treatment under B31 (B31-L17 through B31-L19):
- Art. 132(2): Fallback listed=250% / unlisted=400% (was flat 150% under CRR)
- Art. 132A: Mandate-based (user-supplied RW, 1.2x third-party multiplier)
- No ciu_approach → falls to 250% (B31 default)

Regulatory References:
- PRA PS1/26 Art. 133(1),(3),(5),(6): Basel 3.1 SA equity weights
- PRA PS1/26 Art. 147A: Removal of IRB equity approaches
- PRA PS1/26 Rules 4.1-4.3: Equity transitional schedule (2027-2030)
- PRA PS1/26 Art. 132(2), 132A: CIU treatment
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from tests.fixtures.single_exposure import calculate_single_equity_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.equity.calculator import EquityCalculator

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Basel 3.1 SA config — post-transitional (2031) for steady-state weights."""
    return CalculationConfig.basel_3_1(reporting_date=date(2031, 1, 1))


@pytest.fixture
def b31_irb_config() -> CalculationConfig:
    """Basel 3.1 IRB config — verifies Art. 147A routes equity to SA."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2031, 1, 1),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def b31_2027_config() -> CalculationConfig:
    """Basel 3.1 config for transitional Year 1 (2027)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def b31_2028_config() -> CalculationConfig:
    """Basel 3.1 config for transitional Year 2 (2028)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2028, 6, 30))


@pytest.fixture
def b31_2029_config() -> CalculationConfig:
    """Basel 3.1 config for transitional Year 3 (2029)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2029, 6, 30))


@pytest.fixture
def equity_calculator() -> EquityCalculator:
    """Equity calculator instance."""
    return EquityCalculator()


# =============================================================================
# Basel 3.1 SA Equity Weights — B31-L1 through B31-L9
# =============================================================================


class TestB31L1_ListedEquitySA:
    """
    B31-L1: Listed equity under Basel 3.1 SA.
    Input: equity_type=listed, EAD=£500,000
    Expected: Art. 133(3) 250% → RWA = £1,250,000
    """

    def test_b31_l1_risk_weight(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("500000"),
            equity_type="listed",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50, abs=1e-4)

    def test_b31_l1_rwa(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("500000"),
            equity_type="listed",
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(1_250_000.0, rel=1e-4)

    def test_b31_l1_approach_is_sa(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("500000"),
            equity_type="listed",
            config=b31_config,
        )
        assert result["approach"] == "sa"


class TestB31L2_ExchangeTradedEquitySA:
    """
    B31-L2: Exchange-traded equity under Basel 3.1 SA.
    Input: equity_type=exchange_traded, EAD=£300,000
    Expected: Art. 133(3) 250% → RWA = £750,000
    """

    def test_b31_l2_risk_weight(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("300000"),
            equity_type="exchange_traded",
            is_exchange_traded=True,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50, abs=1e-4)

    def test_b31_l2_rwa(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("300000"),
            equity_type="exchange_traded",
            is_exchange_traded=True,
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(750_000.0, rel=1e-4)


class TestB31L3_UnlistedEquitySA:
    """
    B31-L3: Unlisted equity under Basel 3.1 SA.
    Input: equity_type=unlisted, EAD=£200,000
    Expected: Art. 133(3) 250% (standard rate, not higher-risk unless speculative)
    """

    def test_b31_l3_risk_weight(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("200000"),
            equity_type="unlisted",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50, abs=1e-4)


class TestB31L4_SpeculativeHigherRiskEquitySA:
    """
    B31-L4: Higher-risk (speculative) equity under Basel 3.1 SA.
    Input: equity_type=speculative, is_speculative=True, EAD=£100,000
    Expected: Art. 133(5) 400% → RWA = £400,000
    """

    def test_b31_l4_risk_weight(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="speculative",
            is_speculative=True,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(4.00, abs=1e-4)

    def test_b31_l4_rwa(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="speculative",
            is_speculative=True,
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(400_000.0, rel=1e-4)


class TestB31L5_GovernmentSupportedEquitySA:
    """
    B31-L5: Government-supported (legislative programme) equity under Basel 3.1 SA.
    Input: equity_type=government_supported, is_government_supported=True, EAD=£400,000
    Expected: Art. 133(6) 100% → RWA = £400,000
    """

    def test_b31_l5_risk_weight(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("400000"),
            equity_type="government_supported",
            is_government_supported=True,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00, abs=1e-4)

    def test_b31_l5_rwa(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("400000"),
            equity_type="government_supported",
            is_government_supported=True,
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(400_000.0, rel=1e-4)


class TestB31L6_SubordinatedDebtSA:
    """
    B31-L6: Subordinated debt / non-equity own funds under Basel 3.1 SA.
    Input: equity_type=subordinated_debt, EAD=£250,000
    Expected: Art. 133(1) 150% → RWA = £375,000
    """

    def test_b31_l6_risk_weight(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("250000"),
            equity_type="subordinated_debt",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50, abs=1e-4)

    def test_b31_l6_rwa(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("250000"),
            equity_type="subordinated_debt",
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(375_000.0, rel=1e-4)


class TestB31L7_CentralBankEquitySA:
    """
    B31-L7: Central bank equity under Basel 3.1 SA.
    Input: equity_type=central_bank, EAD=£1,000,000
    Expected: 0% RW (sovereign treatment, unchanged) → RWA = £0
    """

    def test_b31_l7_risk_weight(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="central_bank",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(0.00, abs=1e-4)

    def test_b31_l7_rwa_zero(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="central_bank",
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(0.0, abs=1e-6)


class TestB31L8_PrivateEquitySA:
    """
    B31-L8: Private equity under Basel 3.1 SA.
    Input: equity_type=private_equity, EAD=£150,000
    Expected: Art. 133(5) 400% (PE/VC is always higher-risk equity)
    """

    def test_b31_l8_risk_weight(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("150000"),
            equity_type="private_equity",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(4.00, abs=1e-4)

    def test_b31_l8_rwa(self, equity_calculator, b31_config):
        """PE at 400% RW: RWA = 150k × 4.00 = 600k."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("150000"),
            equity_type="private_equity",
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(600_000.0, rel=1e-4)


class TestB31L9_IsSpeculativeFlagOverridesType:
    """
    B31-L9: is_speculative flag overrides equity_type to higher-risk 400%.
    Input: equity_type=listed, is_speculative=True, EAD=£100,000
    Expected: is_speculative flag → Art. 133(5) 400% overrides listed 250%
    """

    def test_b31_l9_risk_weight(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="listed",
            is_speculative=True,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(4.00, abs=1e-4)


# =============================================================================
# Art. 147A IRB Removal — B31-L10
# =============================================================================


class TestB31L10_IRBConfigRoutesToSA:
    """
    B31-L10: Under Basel 3.1, IRB config still routes equity to SA.
    Input: equity_type=listed, EAD=£200,000, permission_mode=IRB
    Expected: Art. 147A removes IRB equity → approach="sa", RW=250% (not 290%)
    """

    def test_b31_l10_approach_is_sa(self, equity_calculator, b31_irb_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("200000"),
            equity_type="listed",
            config=b31_irb_config,
        )
        assert result["approach"] == "sa"

    def test_b31_l10_risk_weight_is_sa(self, equity_calculator, b31_irb_config):
        """IRB config gives 250% (SA weight), NOT 290% (IRB Simple weight)."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("200000"),
            equity_type="listed",
            config=b31_irb_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50, abs=1e-4)

    def test_b31_l10_irb_weight_not_applied(self, equity_calculator, b31_irb_config):
        """Speculative equity gets 400% (SA), NOT 370% (IRB Simple other)."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("200000"),
            equity_type="speculative",
            is_speculative=True,
            config=b31_irb_config,
        )
        assert result["risk_weight"] == pytest.approx(4.00, abs=1e-4)


# =============================================================================
# Transitional Schedule — B31-L11 through B31-L16
# =============================================================================


class TestB31L11_TransitionalYear1ListedEquity:
    """
    B31-L11: Listed equity in transitional Year 1 (2027).
    Input: equity_type=listed, EAD=£500,000, reporting_date=2027-06-30
    Expected: PRA Rule 4.1 floor 160%, but Art. 133(3) base 250% > 160%
              → max(250%, 160%) = 250% → RWA = £1,250,000
    """

    def test_b31_l11_risk_weight(self, equity_calculator, b31_2027_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("500000"),
            equity_type="listed",
            config=b31_2027_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50, abs=1e-4)


class TestB31L12_TransitionalYear1SpeculativeEquity:
    """
    B31-L12: Speculative (higher-risk) equity in transitional Year 1 (2027).
    Input: equity_type=speculative, is_speculative=True, EAD=£100,000,
           reporting_date=2027-06-30
    Expected: PRA Rule 4.2 higher-risk floor 220%, Art. 133(5) base 400% > 220%
              → max(400%, 220%) = 400% → RWA = £400,000
    """

    def test_b31_l12_risk_weight(self, equity_calculator, b31_2027_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="speculative",
            is_speculative=True,
            config=b31_2027_config,
        )
        assert result["risk_weight"] == pytest.approx(4.00, abs=1e-4)


class TestB31L13_TransitionalExclusionSubordinatedDebt:
    """
    B31-L13: Subordinated debt excluded from transitional floor (PRA Rule 4.3).
    Input: equity_type=subordinated_debt, EAD=£250,000
    Tests across all transitional years: 150% never raised to 160%/190%/220%/250%.
    """

    def test_b31_l13_year1_not_floored(self, equity_calculator, b31_2027_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("250000"),
            equity_type="subordinated_debt",
            config=b31_2027_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50, abs=1e-4)

    def test_b31_l13_year2_not_floored(self, equity_calculator, b31_2028_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("250000"),
            equity_type="subordinated_debt",
            config=b31_2028_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50, abs=1e-4)

    def test_b31_l13_year3_not_floored(self, equity_calculator, b31_2029_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("250000"),
            equity_type="subordinated_debt",
            config=b31_2029_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50, abs=1e-4)

    def test_b31_l13_steady_state(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("250000"),
            equity_type="subordinated_debt",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50, abs=1e-4)


class TestB31L14_TransitionalExclusionGovernmentSupported:
    """
    B31-L14: Government-supported equity excluded from transitional floor.
    Input: equity_type=government_supported, is_government_supported=True, EAD=£300,000
    Expected: 100% across all years — never raised to standard floor (160%+).
    """

    def test_b31_l14_year1_not_floored(self, equity_calculator, b31_2027_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("300000"),
            equity_type="government_supported",
            is_government_supported=True,
            config=b31_2027_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00, abs=1e-4)

    def test_b31_l14_year3_not_floored(self, equity_calculator, b31_2029_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("300000"),
            equity_type="government_supported",
            is_government_supported=True,
            config=b31_2029_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00, abs=1e-4)


class TestB31L15_TransitionalExclusionCentralBank:
    """
    B31-L15: Central bank equity excluded from transitional floor.
    Input: equity_type=central_bank, EAD=£500,000, reporting_date=2027-06-30
    Expected: 0% — floor cannot raise a 0% sovereign treatment exposure.
    """

    def test_b31_l15_zero_preserved(self, equity_calculator, b31_2027_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("500000"),
            equity_type="central_bank",
            config=b31_2027_config,
        )
        assert result["risk_weight"] == pytest.approx(0.00, abs=1e-4)


class TestB31L16_TransitionalScheduleProgression:
    """
    B31-L16: Verify transitional floor progression across years.
    For listed equity (base 250%), floor never bites because 250% > all floors.
    But we verify the calculator doesn't accidentally apply a WRONG floor.
    """

    def test_b31_l16_year1_listed(self, equity_calculator, b31_2027_config):
        """Year 1: max(250%, 160%) = 250%."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="listed",
            config=b31_2027_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50, abs=1e-4)

    def test_b31_l16_year2_listed(self, equity_calculator, b31_2028_config):
        """Year 2: max(250%, 190%) = 250%."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="listed",
            config=b31_2028_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50, abs=1e-4)

    def test_b31_l16_year3_listed(self, equity_calculator, b31_2029_config):
        """Year 3: max(250%, 220%) = 250%."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="listed",
            config=b31_2029_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50, abs=1e-4)

    def test_b31_l16_steady_state_listed(self, equity_calculator, b31_config):
        """Steady state (2031): max(250%, 250%) = 250%."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="listed",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50, abs=1e-4)


# =============================================================================
# CIU Treatment Under Basel 3.1 — B31-L17 through B31-L19
# =============================================================================


class TestB31L17_CIUFallbackSA:
    """
    B31-L17: CIU with fallback approach under Basel 3.1.

    Art. 132(2) CIU fallback = 1,250% (same under both CRR and B31).
    The punitive weight incentivises firms to use look-through or mandate-based.
    """

    def test_b31_l17_unlisted_risk_weight(self, equity_calculator, b31_config):
        """CIU fallback = 1,250% (Art. 132(2))."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("400000"),
            equity_type="ciu",
            ciu_approach="fallback",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(12.50, abs=1e-4)

    def test_b31_l17_unlisted_rwa(self, equity_calculator, b31_config):
        """CIU fallback: RWA = 400k x 12.50 = 5,000k."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("400000"),
            equity_type="ciu",
            ciu_approach="fallback",
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(5_000_000.0, rel=1e-4)

    def test_b31_l17_listed_risk_weight(self, equity_calculator, b31_config):
        """Listed CIU fallback = 1,250% (Art. 132(2), same as unlisted)."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("400000"),
            equity_type="ciu",
            ciu_approach="fallback",
            is_exchange_traded=True,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(12.50, abs=1e-4)

    def test_b31_l17_listed_rwa(self, equity_calculator, b31_config):
        """Listed CIU fallback: RWA = 400k x 12.50 = 5,000k."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("400000"),
            equity_type="ciu",
            ciu_approach="fallback",
            is_exchange_traded=True,
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(5_000_000.0, rel=1e-4)

    def test_b31_l17_fallback_is_punitive(self, equity_calculator, b31_config):
        """CIU fallback (1,250%) far exceeds standard equity RW (250%)."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("400000"),
            equity_type="ciu",
            ciu_approach="fallback",
            config=b31_config,
        )
        assert result["risk_weight"] > 2.50, "CIU fallback must far exceed standard equity"


class TestB31L18_CIUMandateBasedSA:
    """
    B31-L18: CIU with mandate-based approach under Basel 3.1.
    Input: equity_type=ciu, ciu_approach=mandate_based, ciu_mandate_rw=1.20, EAD=£300,000
    Expected: Art. 132A mandate RW 120% → RWA = £360,000
    """

    def test_b31_l18_risk_weight(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("300000"),
            equity_type="ciu",
            ciu_approach="mandate_based",
            ciu_mandate_rw=1.20,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.20, abs=1e-4)

    def test_b31_l18_rwa(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("300000"),
            equity_type="ciu",
            ciu_approach="mandate_based",
            ciu_mandate_rw=1.20,
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(360_000.0, rel=1e-4)


class TestB31L19_CIUMandateThirdPartySA:
    """
    B31-L19: CIU mandate-based with third-party calculation under Basel 3.1.
    Input: equity_type=ciu, ciu_approach=mandate_based, ciu_mandate_rw=1.00,
           ciu_third_party_calc=True, EAD=£200,000
    Expected: Art. 132(4) 1.2× multiplier → 100% × 1.2 = 120% → RWA = £240,000
    """

    def test_b31_l19_risk_weight(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("200000"),
            equity_type="ciu",
            ciu_approach="mandate_based",
            ciu_mandate_rw=1.00,
            ciu_third_party_calc=True,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.20, abs=1e-4)

    def test_b31_l19_rwa(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("200000"),
            equity_type="ciu",
            ciu_approach="mandate_based",
            ciu_mandate_rw=1.00,
            ciu_third_party_calc=True,
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(240_000.0, rel=1e-4)


# =============================================================================
# RWA Arithmetic and Edge Cases — B31-L20 through B31-L23
# =============================================================================


class TestB31L20_RWAArithmeticStandard:
    """
    B31-L20: RWA = EAD × RW arithmetic for standard equity.
    Input: equity_type=listed, EAD=£1,234,567
    Expected: RWA = £1,234,567 × 2.50 = £3,086,417.50
    """

    def test_b31_l20_rwa_exact(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1234567"),
            equity_type="listed",
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(3_086_417.50, rel=1e-6)


class TestB31L21_RWAArithmeticHigherRisk:
    """
    B31-L21: RWA = EAD × RW arithmetic for higher-risk equity.
    Input: equity_type=speculative, is_speculative=True, EAD=£750,000
    Expected: RWA = £750,000 × 4.00 = £3,000,000
    """

    def test_b31_l21_rwa_exact(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("750000"),
            equity_type="speculative",
            is_speculative=True,
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(3_000_000.0, rel=1e-6)


class TestB31L22_ZeroEAD:
    """
    B31-L22: Zero EAD produces zero RWA regardless of risk weight.
    Input: equity_type=listed, EAD=0
    Expected: RWA = 0
    """

    def test_b31_l22_rwa_zero(self, equity_calculator, b31_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("0"),
            equity_type="listed",
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(0.0, abs=1e-6)


class TestB31L23_CRRVsB31RegressionContrast:
    """
    B31-L23: Verify B31 weights differ from CRR for key types.
    Confirms the framework switch produces correct weight changes.
    """

    def test_b31_l23_listed_crr_vs_b31(self, equity_calculator, b31_config):
        """CRR listed=100%, B31 listed=250% — verify B31 is higher."""
        crr_config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            permission_mode=PermissionMode.STANDARDISED,
        )
        crr_result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="listed",
            config=crr_config,
        )
        b31_result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="listed",
            config=b31_config,
        )
        assert crr_result["risk_weight"] == pytest.approx(1.00, abs=1e-4)
        assert b31_result["risk_weight"] == pytest.approx(2.50, abs=1e-4)

    def test_b31_l23_ciu_fallback_crr_vs_b31(self, equity_calculator, b31_config):
        """CIU fallback = 1,250% under both CRR and B31 (Art. 132(2))."""
        crr_config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            permission_mode=PermissionMode.STANDARDISED,
        )
        crr_result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="ciu",
            ciu_approach="fallback",
            config=crr_config,
        )
        b31_result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="ciu",
            ciu_approach="fallback",
            config=b31_config,
        )
        assert crr_result["risk_weight"] == pytest.approx(12.50, abs=1e-4)
        assert b31_result["risk_weight"] == pytest.approx(12.50, abs=1e-4)

    def test_b31_l23_subordinated_debt_crr_vs_b31(self, equity_calculator, b31_config):
        """CRR subordinated_debt=100%, B31 subordinated_debt=150%."""
        crr_config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            permission_mode=PermissionMode.STANDARDISED,
        )
        crr_result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="subordinated_debt",
            config=crr_config,
        )
        b31_result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="subordinated_debt",
            config=b31_config,
        )
        assert crr_result["risk_weight"] == pytest.approx(1.00, abs=1e-4)
        assert b31_result["risk_weight"] == pytest.approx(1.50, abs=1e-4)
