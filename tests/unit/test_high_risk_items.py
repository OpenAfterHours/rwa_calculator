"""
Unit tests for "High-Risk Items" (Art. 128) 150% risk weight.

Why these tests matter:
    CRR Art. 128 defines a separate SA exposure class for items associated with
    particularly high risk. Without explicit handling, these exposures fall through
    to the CQS join fallback (100%) or their base entity_type class, **understating
    capital** by up to 50 percentage points (100% vs 150%).

    Under CRR, high-risk items include:
    - Venture capital investments (Art. 128(1)(a))
    - Private equity (Art. 128(1)(a))
    - Speculative immovable property financing (Art. 128(2))
    - AIFs not treated under Art. 132 (Art. 128(1)(b))
    - Other PRA-designated high-risk items

    Under Basel 3.1, Art. 128 is retained for speculative RE and other designated
    high-risk items. PE/VC may be reclassified to equity under Art. 133(5) at 400%,
    but if classified as high_risk they still receive 150%.

    The 150% is unconditional — no CQS lookup, no LTV calculation. High-risk items
    also take classification priority over DEFAULTED (Art. 112 Table A2, priority 4
    vs priority 5), so a defaulted high-risk item retains 150% per Art. 128, not
    the provision-based 100%/150% of Art. 127.

References:
    - CRR Art. 112(1)(l): High-risk exposure class in SA classification
    - CRR Art. 128: Items associated with particularly high risk — 150% RW
    - PRA PS1/26 Art. 128: Retained under Basel 3.1
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.entity_class_mapping import (
    ENTITY_TYPE_TO_IRB_CLASS,
    ENTITY_TYPE_TO_SA_CLASS,
)
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.sa import SACalculator
from rwa_calc.rulebook.resolve import resolve
from tests.fixtures.single_exposure import calculate_single_sa_exposure

# High-risk-item RW (Art. 128, 150% flat) is identical under CRR and Basel 3.1,
# single-sourced into the common rulepack pack (was HIGH_RISK_RW + B31_HIGH_RISK_RW).
HIGH_RISK_RW = resolve("crr", date(2026, 1, 1)).scalar_param("high_risk_rw").value
B31_HIGH_RISK_RW = HIGH_RISK_RW

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


# =============================================================================
# DATA TABLE / CONSTANT TESTS
# =============================================================================


class TestHighRiskConstants:
    """Tests for Art. 128 risk weight constants."""

    def test_crr_high_risk_rw_150(self):
        """CRR Art. 128: High-risk items → 150%."""
        assert Decimal("1.50") == HIGH_RISK_RW

    def test_b31_high_risk_rw_150(self):
        """PRA PS1/26 Art. 128: High-risk items → 150% (unchanged from CRR)."""
        assert Decimal("1.50") == B31_HIGH_RISK_RW

    def test_crr_and_b31_high_risk_same(self):
        """Art. 128 is unchanged between CRR and Basel 3.1."""
        assert HIGH_RISK_RW == B31_HIGH_RISK_RW


# =============================================================================
# CLASSIFIER MAPPING TESTS
# =============================================================================


class TestHighRiskClassifierMappings:
    """Tests for entity_type → HIGH_RISK exposure class mapping."""

    @pytest.mark.parametrize(
        "entity_type",
        [
            "high_risk",
            "high_risk_venture_capital",
            "high_risk_private_equity",
            "high_risk_speculative_re",
        ],
        ids=[
            "generic_high_risk",
            "venture_capital",
            "private_equity",
            "speculative_re",
        ],
    )
    def test_sa_class_mapping(self, entity_type):
        """All high-risk entity_types map to HIGH_RISK SA class."""
        assert ENTITY_TYPE_TO_SA_CLASS[entity_type] == ExposureClass.HIGH_RISK.value

    @pytest.mark.parametrize(
        "entity_type",
        [
            "high_risk",
            "high_risk_venture_capital",
            "high_risk_private_equity",
            "high_risk_speculative_re",
        ],
    )
    def test_irb_class_mapping(self, entity_type):
        """All high-risk entity_types map to HIGH_RISK in IRB class dict."""
        assert ENTITY_TYPE_TO_IRB_CLASS[entity_type] == ExposureClass.HIGH_RISK.value

    def test_high_risk_enum_value(self):
        """ExposureClass.HIGH_RISK has correct string value."""
        assert ExposureClass.HIGH_RISK.value == "high_risk"


# =============================================================================
# CRR SA CALCULATOR TESTS
# =============================================================================


class TestCRRHighRiskItems:
    """Tests for Art. 128 high-risk items through the CRR SA calculator.

    SI 2021/1078 reg. 6(3)(a) omitted Art. 128 from the onshored UK CRR text
    with effect from 1 January 2022. Under UK CRR, the engine therefore does
    not apply a 150% high-risk weight: exposures fall through to the residual
    OTHER class at 100%. The 150% Art. 128 treatment is re-introduced under
    PRA PS1/26 Basel 3.1 — see TestB31HighRiskItems below.
    """

    def test_generic_high_risk_100_percent(self, sa_calculator, crr_config):
        """UK CRR (Art. 128 omitted by SI 2021/1078): generic high-risk → 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="high_risk",
            config=crr_config,
            entity_type="high_risk",
        )
        assert result["risk_weight"] == pytest.approx(1.00)
        assert result["rwa"] == pytest.approx(1_000_000.0)

    def test_venture_capital_100_percent(self, sa_calculator, crr_config):
        """UK CRR (Art. 128 omitted): venture capital → 100% RW (OTHER fallthrough)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="high_risk",
            config=crr_config,
            entity_type="high_risk_venture_capital",
        )
        assert result["risk_weight"] == pytest.approx(1.00)
        assert result["rwa"] == pytest.approx(500_000.0)

    def test_private_equity_100_percent(self, sa_calculator, crr_config):
        """UK CRR (Art. 128 omitted): private equity → 100% RW (OTHER fallthrough)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="high_risk",
            config=crr_config,
            entity_type="high_risk_private_equity",
        )
        assert result["risk_weight"] == pytest.approx(1.00)
        assert result["rwa"] == pytest.approx(2_000_000.0)

    def test_speculative_re_100_percent(self, sa_calculator, crr_config):
        """UK CRR (Art. 128 omitted): speculative RE → 100% RW (OTHER fallthrough)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("10000000"),
            exposure_class="high_risk",
            config=crr_config,
            entity_type="high_risk_speculative_re",
        )
        assert result["risk_weight"] == pytest.approx(1.00)
        assert result["rwa"] == pytest.approx(10_000_000.0)

    def test_high_risk_ignores_cqs(self, sa_calculator, crr_config):
        """UK CRR: 100% OTHER fallthrough is unconditional — CQS has no effect."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="high_risk",
            config=crr_config,
            entity_type="high_risk",
            cqs=1,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_high_risk_ignores_seniority(self, sa_calculator, crr_config):
        """UK CRR: 100% OTHER fallthrough is unconditional — seniority has no effect."""
        for seniority in ("senior", "subordinated"):
            result = calculate_single_sa_exposure(
                sa_calculator,
                ead=Decimal("1000000"),
                exposure_class="high_risk",
                config=crr_config,
                entity_type="high_risk",
                seniority=seniority,
            )
            assert result["risk_weight"] == pytest.approx(1.00)


# =============================================================================
# BASEL 3.1 SA CALCULATOR TESTS
# =============================================================================


class TestB31HighRiskItems:
    """Tests for Art. 128 high-risk items through the Basel 3.1 SA calculator."""

    def test_generic_high_risk_150_percent(self, sa_calculator, b31_config):
        """PRA PS1/26 Art. 128: Generic high-risk item → 150% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="high_risk",
            config=b31_config,
            entity_type="high_risk",
        )
        assert result["risk_weight"] == pytest.approx(1.50)
        assert result["rwa"] == pytest.approx(1_500_000.0)

    def test_speculative_re_150_percent(self, sa_calculator, b31_config):
        """PRA PS1/26 Art. 128: Speculative RE → 150% (unchanged from CRR)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="high_risk",
            config=b31_config,
            entity_type="high_risk_speculative_re",
        )
        assert result["risk_weight"] == pytest.approx(1.50)
        assert result["rwa"] == pytest.approx(7_500_000.0)

    def test_b31_high_risk_ignores_cqs(self, sa_calculator, b31_config):
        """PRA PS1/26 Art. 128: 150% is unconditional under B31."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="high_risk",
            config=b31_config,
            entity_type="high_risk",
            cqs=2,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_b31_diverges_from_crr_for_high_risk(self, sa_calculator, b31_config, crr_config):
        """Art. 128 was OMITTED from UK CRR (SI 2021/1078) and RE-INTRODUCED under B3.1.

        UK CRR: high-risk → OTHER fallthrough at 100%.
        PRA PS1/26 B3.1: high-risk Art. 128 → 150%.
        """
        crr_result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="high_risk",
            config=crr_config,
            entity_type="high_risk",
        )
        b31_result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="high_risk",
            config=b31_config,
            entity_type="high_risk",
        )
        assert crr_result["risk_weight"] == pytest.approx(1.00)
        assert b31_result["risk_weight"] == pytest.approx(1.50)
        # 0.50 × EAD = 500,000 uplift under B3.1.
        assert b31_result["rwa"] - crr_result["rwa"] == pytest.approx(500_000.0)


# =============================================================================
# CLASSIFIER INTEGRATION TESTS
# =============================================================================


class TestHighRiskDefaultedPriority:
    """Tests that HIGH_RISK takes priority over DEFAULTED classification.

    Art. 112 Table A2 places high-risk items at priority 4 and defaulted
    exposures at priority 5. A defaulted high-risk item retains its HIGH_RISK
    classification, ensuring the unconditional 150% Art. 128 weight rather
    than the provision-dependent 100%/150% of Art. 127.

    This is tested via the SA calculator: a defaulted high-risk item should
    still get 150% (not 100% which it would get if reclassified to DEFAULTED
    with adequate provisions).
    """

    def test_defaulted_high_risk_gets_100_under_crr(self, sa_calculator, crr_config):
        """UK CRR defaulted high-risk: 100% (OTHER fallthrough, Art. 128 omitted).

        Under SI 2021/1078 reg. 6(3)(a), Art. 128 is dead letter under UK CRR
        so the high-risk class falls through to OTHER (100%). The Art. 112
        Table A2 priority carve-out remains in place: ``_uc == "HIGH_RISK"``
        suppresses the Art. 127 defaulted-RW override (so we land on the 100%
        OTHER fallthrough rather than the Art. 127 100%/150% provision split).
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="high_risk",
            config=crr_config,
            entity_type="high_risk",
            is_defaulted=True,
            provision_allocated=Decimal("500000"),  # 50% provision > 20% threshold
        )
        # UK CRR: high-risk class is dead letter → OTHER fallthrough at 100%.
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_defaulted_high_risk_b31_gets_150(self, sa_calculator, b31_config):
        """Defaulted high-risk item under B31: still 150% (Art. 128)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="high_risk",
            config=b31_config,
            entity_type="high_risk",
            is_defaulted=True,
            provision_allocated=Decimal("500000"),
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_defaulted_corporate_still_gets_defaulted_treatment(self, sa_calculator, crr_config):
        """Non-high-risk defaulted exposures still use Art. 127 treatment."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="defaulted",
            config=crr_config,
            entity_type="corporate",
            is_defaulted=True,
            provision_allocated=Decimal("500000"),  # 50% > 20% threshold → 100%
        )
        assert result["risk_weight"] == pytest.approx(1.00)
