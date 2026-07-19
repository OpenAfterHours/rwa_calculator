"""
P1.247 — CRR Art. 158(7): equity IRB-Simple must emit an expected-loss amount.

Under the Art. 155(2) simple risk-weight approach the risk-weighted exposure
amount is ``RW x exposure value`` (RW 190%/290%/370%). Separately, Art. 158(7)
requires an expected-loss amount to be computed as ``EL rate x exposure value``:

    - 0.8% for private equity in sufficiently diversified portfolios (190% RW)
    - 0.8% for exchange-traded equity exposures                       (290% RW)
    - 2.4% for all other equity exposures                            (370% RW)

The EL amount is a required Art. 158(7) computation used for disclosure (COREP
C08 / Pillar 3 IRB EL columns). It does NOT feed the Art. 159 EL-vs-provisions
comparison — Art. 159 subtracts only the Art. 158(5),(6),(10) EL amounts from
provisions, and Art. 155(2) does not gross the equity RWA up by EL. The pre-fix
engine emitted NO ``expected_loss`` on the simple path (only the PD/LGD path
did), so the Art. 158(7) amount was silently zero.

Regulatory Reference:
    CRR Art. 158(7): equity simple-approach EL rates (0.8% / 0.8% / 2.4%).
      Art. 158 was omitted from onshored UK CRR by SI 2021/1078; the live text
      is in the PRA Rulebook (CRR Firms) IRB Approach Part, mirroring EU CRR
      Art. 158(7) / Annex VII Part I point 32.
    CRR Art. 155(2): simple risk-weight buckets 190% / 290% / 370%.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from tests.fixtures.single_exposure import calculate_single_equity_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import EquityType, PermissionMode
from rwa_calc.engine.equity.calculator import EquityCalculator
from rwa_calc.rulebook.compile import lookup_float_map
from rwa_calc.rulebook.resolve import resolve

# ---------------------------------------------------------------------------
# Constants — Art. 158(7) EL rates
# ---------------------------------------------------------------------------

EL_RATE_DIVERSIFIED_PE = 0.008
EL_RATE_EXCHANGE_TRADED = 0.008
EL_RATE_OTHER = 0.024
EAD = Decimal("1000000")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def irb_config() -> CalculationConfig:
    """CRR IRB configuration that routes equity through Art. 155 IRB Simple."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def sa_config() -> CalculationConfig:
    """CRR SA-only configuration (Art. 133 SA path — no IRB equity EL)."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    )


@pytest.fixture
def b31_irb_config() -> CalculationConfig:
    """Basel 3.1 IRB configuration — equity IRB removed, all equity -> SA."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def equity_calculator() -> EquityCalculator:
    """Equity calculator instance."""
    return EquityCalculator()


# ---------------------------------------------------------------------------
# P1.247 — Art. 158(7) EL rate emission on the IRB-Simple path
# ---------------------------------------------------------------------------


class TestP1247IRBSimpleEquityExpectedLoss:
    """Art. 158(7) EL amount must be emitted on the Art. 155(2) simple path."""

    def test_diversified_pe_el_08_percent(
        self, equity_calculator: EquityCalculator, irb_config: CalculationConfig
    ) -> None:
        """Diversified PE (190% RW) carries the 0.8% Art. 158(7) EL rate."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=EAD,
            equity_type="private_equity",
            is_diversified=True,
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(1.90)
        assert result["expected_loss"] == pytest.approx(EL_RATE_DIVERSIFIED_PE * float(EAD))

    def test_private_equity_diversified_type_el_08_percent(
        self, equity_calculator: EquityCalculator, irb_config: CalculationConfig
    ) -> None:
        """equity_type=private_equity_diversified pairs 190% RW with 0.8% EL."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=EAD,
            equity_type="private_equity_diversified",
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(1.90)
        assert result["expected_loss"] == pytest.approx(EL_RATE_DIVERSIFIED_PE * float(EAD))

    def test_exchange_traded_flag_el_08_percent(
        self, equity_calculator: EquityCalculator, irb_config: CalculationConfig
    ) -> None:
        """Exchange-traded (290% RW) carries the 0.8% Art. 158(7) EL rate."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=EAD,
            equity_type="exchange_traded",
            is_exchange_traded=True,
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(2.90)
        assert result["expected_loss"] == pytest.approx(EL_RATE_EXCHANGE_TRADED * float(EAD))

    def test_listed_el_08_percent(
        self, equity_calculator: EquityCalculator, irb_config: CalculationConfig
    ) -> None:
        """Listed equity (290% RW, exchange-traded bucket) carries 0.8% EL."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=EAD,
            equity_type="listed",
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(2.90)
        assert result["expected_loss"] == pytest.approx(EL_RATE_EXCHANGE_TRADED * float(EAD))

    def test_other_equity_el_24_percent(
        self, equity_calculator: EquityCalculator, irb_config: CalculationConfig
    ) -> None:
        """Other equity (370% RW) carries the 2.4% Art. 158(7) EL rate."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=EAD,
            equity_type="other",
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(3.70)
        assert result["expected_loss"] == pytest.approx(EL_RATE_OTHER * float(EAD))

    def test_non_diversified_pe_el_24_percent(
        self, equity_calculator: EquityCalculator, irb_config: CalculationConfig
    ) -> None:
        """Non-diversified private equity (370% RW) is 'all other' at 2.4% EL."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=EAD,
            equity_type="private_equity",
            is_diversified=False,
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(3.70)
        assert result["expected_loss"] == pytest.approx(EL_RATE_OTHER * float(EAD))

    def test_government_supported_el_24_percent(
        self, equity_calculator: EquityCalculator, irb_config: CalculationConfig
    ) -> None:
        """Government-supported equity (370% 'all other') carries 2.4% EL."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=EAD,
            equity_type="government_supported",
            is_government_supported=True,
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(3.70)
        assert result["expected_loss"] == pytest.approx(EL_RATE_OTHER * float(EAD))

    def test_central_bank_el_zero(
        self, equity_calculator: EquityCalculator, irb_config: CalculationConfig
    ) -> None:
        """Central-bank equity (0% RW) carries a 0.0 EL amount (no loss)."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=EAD,
            equity_type="central_bank",
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(0.00)
        assert result["expected_loss"] == pytest.approx(0.0)

    @pytest.mark.parametrize(
        ("equity_type", "is_diversified", "is_exchange_traded", "expected_rw", "expected_el_rate"),
        [
            ("private_equity", True, False, 1.90, 0.008),
            ("exchange_traded", False, True, 2.90, 0.008),
            ("listed", False, False, 2.90, 0.008),
            ("other", False, False, 3.70, 0.024),
            ("unlisted", False, False, 3.70, 0.024),
        ],
    )
    def test_el_pairs_with_rw_bucket(
        self,
        equity_calculator: EquityCalculator,
        irb_config: CalculationConfig,
        equity_type: str,
        is_diversified: bool,
        is_exchange_traded: bool,
        expected_rw: float,
        expected_el_rate: float,
    ) -> None:
        """The EL rate pairs with the simple-RW bucket (0.8% <-> 190/290; 2.4% <-> 370)."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=EAD,
            equity_type=equity_type,
            is_diversified=is_diversified,
            is_exchange_traded=is_exchange_traded,
            config=irb_config,
        )
        assert result["risk_weight"] == pytest.approx(expected_rw)
        assert result["expected_loss"] == pytest.approx(expected_el_rate * float(EAD))

    def test_el_scales_linearly_with_ead(
        self, equity_calculator: EquityCalculator, irb_config: CalculationConfig
    ) -> None:
        """EL amount = rate x ead_final scales with EAD (2.4% x 250,000 = 6,000)."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("250000"),
            equity_type="other",
            config=irb_config,
        )
        assert result["expected_loss"] == pytest.approx(EL_RATE_OTHER * 250_000.0)


class TestP1247RegimeScoping:
    """The Art. 158(7) simple EL is confined to the CRR IRB-Simple path."""

    def test_sa_path_emits_no_simple_el(
        self, equity_calculator: EquityCalculator, sa_config: CalculationConfig
    ) -> None:
        """CRR SA-only equity (Art. 133) does not carry the simple-approach EL."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=EAD,
            equity_type="other",
            config=sa_config,
        )
        assert result["approach"] == "sa"
        assert result.get("expected_loss") is None

    def test_b31_irb_equity_emits_no_simple_el(
        self, equity_calculator: EquityCalculator, b31_irb_config: CalculationConfig
    ) -> None:
        """Under Basel 3.1 equity IRB is removed — all equity routes to SA and
        carries no Art. 158(7) simple EL (equity_irb_approaches_available=False)."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=EAD,
            equity_type="other",
            config=b31_irb_config,
        )
        assert result["approach"] == "sa"
        assert result.get("expected_loss") is None


class TestP1247PackEntry:
    """The EL rates live in a cited rulepack entry (CRR pack, Art. 158(7))."""

    def test_pack_carries_simple_el_rates(self) -> None:
        """equity_irb_simple_el resolves to the Art. 158(7) rates by EquityType."""
        el_map = lookup_float_map(resolve("crr", date(2026, 1, 1)).lookup("equity_irb_simple_el"))
        assert el_map[EquityType.PRIVATE_EQUITY_DIVERSIFIED] == pytest.approx(0.008)
        assert el_map[EquityType.EXCHANGE_TRADED] == pytest.approx(0.008)
        assert el_map[EquityType.LISTED] == pytest.approx(0.008)
        assert el_map[EquityType.OTHER] == pytest.approx(0.024)
        assert el_map[EquityType.PRIVATE_EQUITY] == pytest.approx(0.024)
        assert el_map[EquityType.CENTRAL_BANK] == pytest.approx(0.0)
