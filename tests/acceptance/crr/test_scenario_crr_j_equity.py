"""
CRR Group J: Equity Exposure Acceptance Tests.

Tests validate the production calculator correctly handles equity exposures
under CRR Art. 133 (SA) and Art. 155 (IRB Simple Risk Weight Method).

SA equity treatment (CRR-J1 through CRR-J9):
- Art. 133(2): Flat 100% for all standard equity types (listed, unlisted, PE, etc.)
- Art. 132(2): CIU fallback 150%
- Sovereign treatment: Central bank equity 0%
- No differentiated weights by listing status under CRR SA

IRB Simple equity treatment (CRR-J10 through CRR-J14):
- Art. 155(2)(a): Exchange-traded 290%
- Art. 155(2)(b): Diversified PE 190%
- Art. 155(2)(c): All other equity 370%
- Central bank 0% (sovereign treatment)
- Government-supported treated as diversified (190%)

CIU treatment (CRR-J15 through CRR-J17):
- Art. 132(2): Fallback 150%
- Art. 132A: Mandate-based (user-supplied RW, 1.2x third-party multiplier)

RWA verification (CRR-J18 through CRR-J20):
- RWA = EAD × risk_weight for representative exposures

Regulatory References:
- CRR Art. 133(2): SA equity flat 100%
- CRR Art. 132(2): CIU fallback 150%
- CRR Art. 132A: CIU mandate-based approach
- CRR Art. 155(2)(a-c): IRB Simple equity weights (290%/190%/370%)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.equity.calculator import EquityCalculator
from tests.fixtures.single_exposure import calculate_single_equity_exposure

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crr_sa_config() -> CalculationConfig:
    """CRR SA config for equity tests."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    )


@pytest.fixture
def crr_irb_config() -> CalculationConfig:
    """CRR IRB config for equity tests (enables IRB Simple method)."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def equity_calculator() -> EquityCalculator:
    """Equity calculator instance."""
    return EquityCalculator()


# =============================================================================
# CRR SA Equity Tests (Art. 133) — CRR-J1 through CRR-J9
# =============================================================================


class TestCRRJ1_ListedEquitySA:
    """
    CRR-J1: Listed equity under SA.
    Input: equity_type=listed, EAD=£500,000
    Expected: Art. 133(2) flat 100% → RWA = £500,000
    """

    def test_crr_j1_risk_weight(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("500000"),
            equity_type="listed",
            config=crr_sa_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00, abs=1e-4)

    def test_crr_j1_rwa(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("500000"),
            equity_type="listed",
            config=crr_sa_config,
        )
        assert result["rwa"] == pytest.approx(500_000.0, rel=1e-4)

    def test_crr_j1_approach(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("500000"),
            equity_type="listed",
            config=crr_sa_config,
        )
        assert result["approach"] == "sa"


class TestCRRJ2_UnlistedEquitySA:
    """
    CRR-J2: Unlisted equity under SA.
    Input: equity_type=unlisted, EAD=£300,000
    Expected: Art. 133(2) flat 100% — NOT differentiated (no 150% under CRR SA)
    """

    def test_crr_j2_risk_weight(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("300000"),
            equity_type="unlisted",
            config=crr_sa_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00, abs=1e-4)

    def test_crr_j2_rwa(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("300000"),
            equity_type="unlisted",
            config=crr_sa_config,
        )
        assert result["rwa"] == pytest.approx(300_000.0, rel=1e-4)


class TestCRRJ3_ExchangeTradedEquitySA:
    """
    CRR-J3: Exchange-traded equity under SA.
    Input: equity_type=exchange_traded, EAD=£200,000
    Expected: Art. 133(2) flat 100%
    """

    def test_crr_j3_risk_weight(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("200000"),
            equity_type="exchange_traded",
            config=crr_sa_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00, abs=1e-4)


class TestCRRJ4_PrivateEquitySA:
    """
    CRR-J4: Private equity under SA.
    Input: equity_type=private_equity, EAD=£100,000
    Expected: Art. 133(2) flat 100% (PE classified as high-risk goes to
    ExposureClass.HIGH_RISK 150% outside the equity calculator)
    """

    def test_crr_j4_risk_weight(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="private_equity",
            config=crr_sa_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00, abs=1e-4)


class TestCRRJ5_GovernmentSupportedEquitySA:
    """
    CRR-J5: Government-supported equity under SA.
    Input: equity_type=government_supported, EAD=£400,000
    Expected: Art. 133(2) flat 100% (same as all other equity under CRR SA)
    """

    def test_crr_j5_risk_weight(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("400000"),
            equity_type="government_supported",
            is_government_supported=True,
            config=crr_sa_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00, abs=1e-4)


class TestCRRJ6_SpeculativeEquitySA:
    """
    CRR-J6: Speculative equity under SA.
    Input: equity_type=speculative, is_speculative=True, EAD=£150,000
    Expected: Art. 133(2) flat 100% — no differentiation under CRR SA
    (speculative PE qualifying as high-risk is routed to ExposureClass.HIGH_RISK
    at classification, not to the equity calculator)
    """

    def test_crr_j6_risk_weight(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("150000"),
            equity_type="speculative",
            is_speculative=True,
            config=crr_sa_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00, abs=1e-4)


class TestCRRJ7_CentralBankEquitySA:
    """
    CRR-J7: Central bank equity under SA.
    Input: equity_type=central_bank, EAD=£1,000,000
    Expected: 0% RW (sovereign treatment) → RWA = £0
    """

    def test_crr_j7_risk_weight(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="central_bank",
            config=crr_sa_config,
        )
        assert result["risk_weight"] == pytest.approx(0.00, abs=1e-4)

    def test_crr_j7_rwa_zero(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="central_bank",
            config=crr_sa_config,
        )
        assert result["rwa"] == pytest.approx(0.0, abs=1e-6)


class TestCRRJ8_SubordinatedDebtSA:
    """
    CRR-J8: Subordinated debt under SA.
    Input: equity_type=subordinated_debt, EAD=£250,000
    Expected: Art. 133(2) flat 100% (CRR does not differentiate subordinated debt)
    """

    def test_crr_j8_risk_weight(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("250000"),
            equity_type="subordinated_debt",
            config=crr_sa_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00, abs=1e-4)


class TestCRRJ9_CIUFallbackSA:
    """
    CRR-J9: CIU equity with fallback approach under SA.
    Input: equity_type=ciu, ciu_approach=fallback, EAD=£600,000
    Expected: Art. 132(2) fallback 150% → RWA = £900,000
    """

    def test_crr_j9_risk_weight(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("600000"),
            equity_type="ciu",
            ciu_approach="fallback",
            config=crr_sa_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50, abs=1e-4)

    def test_crr_j9_rwa(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("600000"),
            equity_type="ciu",
            ciu_approach="fallback",
            config=crr_sa_config,
        )
        assert result["rwa"] == pytest.approx(900_000.0, rel=1e-4)


# =============================================================================
# CRR IRB Simple Equity Tests (Art. 155) — CRR-J10 through CRR-J14
# =============================================================================


class TestCRRJ10_ExchangeTradedEquityIRBSimple:
    """
    CRR-J10: Exchange-traded equity under IRB Simple.
    Input: equity_type=exchange_traded, is_exchange_traded=True, EAD=£200,000
    Expected: Art. 155(2)(a) 290% → RWA = £580,000
    """

    def test_crr_j10_risk_weight(self, equity_calculator, crr_irb_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("200000"),
            equity_type="exchange_traded",
            is_exchange_traded=True,
            config=crr_irb_config,
        )
        assert result["risk_weight"] == pytest.approx(2.90, abs=1e-4)

    def test_crr_j10_rwa(self, equity_calculator, crr_irb_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("200000"),
            equity_type="exchange_traded",
            is_exchange_traded=True,
            config=crr_irb_config,
        )
        assert result["rwa"] == pytest.approx(580_000.0, rel=1e-4)

    def test_crr_j10_approach(self, equity_calculator, crr_irb_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("200000"),
            equity_type="exchange_traded",
            is_exchange_traded=True,
            config=crr_irb_config,
        )
        assert result["approach"] == "irb_simple"


class TestCRRJ11_DiversifiedPEEquityIRBSimple:
    """
    CRR-J11: Diversified private equity portfolio under IRB Simple.
    Input: equity_type=private_equity, is_diversified=True, EAD=£100,000
    Expected: Art. 155(2)(b) 190% → RWA = £190,000
    """

    def test_crr_j11_risk_weight(self, equity_calculator, crr_irb_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="private_equity",
            is_diversified=True,
            config=crr_irb_config,
        )
        assert result["risk_weight"] == pytest.approx(1.90, abs=1e-4)

    def test_crr_j11_rwa(self, equity_calculator, crr_irb_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="private_equity",
            is_diversified=True,
            config=crr_irb_config,
        )
        assert result["rwa"] == pytest.approx(190_000.0, rel=1e-4)


class TestCRRJ12_OtherEquityIRBSimple:
    """
    CRR-J12: Other (non-exchange-traded, non-diversified-PE) under IRB Simple.
    Input: equity_type=unlisted, EAD=£100,000
    Expected: Art. 155(2)(c) 370% → RWA = £370,000
    """

    def test_crr_j12_risk_weight(self, equity_calculator, crr_irb_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="unlisted",
            config=crr_irb_config,
        )
        assert result["risk_weight"] == pytest.approx(3.70, abs=1e-4)

    def test_crr_j12_rwa(self, equity_calculator, crr_irb_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="unlisted",
            config=crr_irb_config,
        )
        assert result["rwa"] == pytest.approx(370_000.0, rel=1e-4)


class TestCRRJ13_CentralBankEquityIRBSimple:
    """
    CRR-J13: Central bank equity under IRB Simple.
    Input: equity_type=central_bank, EAD=£500,000
    Expected: 0% RW (sovereign treatment preserved under IRB) → RWA = £0
    """

    def test_crr_j13_risk_weight(self, equity_calculator, crr_irb_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("500000"),
            equity_type="central_bank",
            config=crr_irb_config,
        )
        assert result["risk_weight"] == pytest.approx(0.00, abs=1e-4)


class TestCRRJ14_GovernmentSupportedEquityIRBSimple:
    """
    CRR-J14: Government-supported equity under IRB Simple.
    Input: equity_type=government_supported, is_government_supported=True, EAD=£300,000
    Expected: Art. 155 — treated as diversified PE 190% → RWA = £570,000
    """

    def test_crr_j14_risk_weight(self, equity_calculator, crr_irb_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("300000"),
            equity_type="government_supported",
            is_government_supported=True,
            config=crr_irb_config,
        )
        assert result["risk_weight"] == pytest.approx(1.90, abs=1e-4)

    def test_crr_j14_rwa(self, equity_calculator, crr_irb_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("300000"),
            equity_type="government_supported",
            is_government_supported=True,
            config=crr_irb_config,
        )
        assert result["rwa"] == pytest.approx(570_000.0, rel=1e-4)


# =============================================================================
# CIU Specific Tests — CRR-J15 through CRR-J17
# =============================================================================


class TestCRRJ15_CIUMandateBasedSA:
    """
    CRR-J15: CIU equity with mandate-based approach under SA.
    Input: equity_type=ciu, ciu_approach=mandate_based, ciu_mandate_rw=0.80, EAD=£200,000
    Expected: Art. 132A mandate RW 80% → RWA = £160,000
    """

    def test_crr_j15_risk_weight(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("200000"),
            equity_type="ciu",
            ciu_approach="mandate_based",
            ciu_mandate_rw=0.80,
            config=crr_sa_config,
        )
        assert result["risk_weight"] == pytest.approx(0.80, abs=1e-4)

    def test_crr_j15_rwa(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("200000"),
            equity_type="ciu",
            ciu_approach="mandate_based",
            ciu_mandate_rw=0.80,
            config=crr_sa_config,
        )
        assert result["rwa"] == pytest.approx(160_000.0, rel=1e-4)


class TestCRRJ16_CIUMandateThirdPartySA:
    """
    CRR-J16: CIU equity with mandate-based + third-party calculation.
    Input: equity_type=ciu, ciu_approach=mandate_based, ciu_mandate_rw=0.80,
           ciu_third_party_calc=True, EAD=£200,000
    Expected: Art. 132(4) 1.2× multiplier → 80% × 1.2 = 96% → RWA = £192,000
    """

    def test_crr_j16_risk_weight(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("200000"),
            equity_type="ciu",
            ciu_approach="mandate_based",
            ciu_mandate_rw=0.80,
            ciu_third_party_calc=True,
            config=crr_sa_config,
        )
        assert result["risk_weight"] == pytest.approx(0.96, abs=1e-4)

    def test_crr_j16_rwa(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("200000"),
            equity_type="ciu",
            ciu_approach="mandate_based",
            ciu_mandate_rw=0.80,
            ciu_third_party_calc=True,
            config=crr_sa_config,
        )
        assert result["rwa"] == pytest.approx(192_000.0, rel=1e-4)


class TestCRRJ17_CIUNoApproachFallback:
    """
    CRR-J17: CIU equity with no ciu_approach set (fallback default).
    Input: equity_type=ciu, ciu_approach=None, EAD=£100,000
    Expected: Falls through to CIU fallback 150% → RWA = £150,000
    """

    def test_crr_j17_risk_weight(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("100000"),
            equity_type="ciu",
            config=crr_sa_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50, abs=1e-4)


# =============================================================================
# RWA Arithmetic Verification — CRR-J18 through CRR-J20
# =============================================================================


class TestCRRJ18_SARWAArithmetic:
    """
    CRR-J18: SA RWA = EAD × RW arithmetic verification.
    Input: equity_type=listed, EAD=£1,234,567
    Expected: RWA = £1,234,567 × 1.00 = £1,234,567
    """

    def test_crr_j18_rwa_exact(self, equity_calculator, crr_sa_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1234567"),
            equity_type="listed",
            config=crr_sa_config,
        )
        assert result["rwa"] == pytest.approx(1_234_567.0, rel=1e-6)


class TestCRRJ19_IRBSimpleRWAArithmetic:
    """
    CRR-J19: IRB Simple RWA = EAD × RW arithmetic verification.
    Input: equity_type=other, EAD=£750,000
    Expected: RWA = £750,000 × 3.70 = £2,775,000
    """

    def test_crr_j19_rwa_exact(self, equity_calculator, crr_irb_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("750000"),
            equity_type="other",
            config=crr_irb_config,
        )
        assert result["rwa"] == pytest.approx(2_775_000.0, rel=1e-6)


class TestCRRJ20_ZeroEAD:
    """
    CRR-J20: Zero EAD produces zero RWA regardless of risk weight.
    Input: equity_type=unlisted, EAD=0
    Expected: RWA = 0
    """

    def test_crr_j20_rwa_zero(self, equity_calculator, crr_irb_config):
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("0"),
            equity_type="unlisted",
            config=crr_irb_config,
        )
        assert result["rwa"] == pytest.approx(0.0, abs=1e-6)
