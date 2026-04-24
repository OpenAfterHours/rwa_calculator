"""
Tests for Art. 127 defaulted exposure risk weight treatment.

PS1/26 Art. 127(1)-(2) assign 100%/150% to the part of a defaulted exposure
not secured by recognised collateral or covered by recognised unfunded credit
protection. The unsecured part is determined by the CRM method the
institution applies (Art. 191A(2)).

Under the Financial Collateral Comprehensive Method (the default for SA),
eligible financial collateral has already reduced EAD in the CRM stage and
eligible real estate has been routed via class reclassification. So
``ead_final`` entering the SA risk-weight stage already represents the
unsecured value — Art. 127(1) applies to it flat. Non-financial collateral
columns (collateral_re_value, collateral_receivables_value,
collateral_other_physical_value) do NOT produce a secondary secured/unsecured
split inside the defaulted override — that would double-count the CRM
reduction and, for low-RW classes like retail (75%), drag the defaulted RW
below the 100% floor required by Art. 127(1)(b).

References:
- PS1/26 Art. 127(1): unsecured part 100%/150% by provision coverage
- PS1/26 Art. 127(2): unsecured part determined by the CRM method
- PS1/26 Art. 127(3) / CRE20.88: RESI RE non-income flat 100%
- CRR Art. 127(1)-(2): predecessor with pre-provision denominator
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa.calculator import SACalculator


@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


# ---------------------------------------------------------------------------
# CRR: no non-financial collateral
# ---------------------------------------------------------------------------


class TestCRRDefaultedBackwardCompat:
    """Defaulted exposures without non-financial collateral."""

    def test_crr_defaulted_low_provision_150pct(self, sa_calculator, crr_config):
        """No non-fin collateral, provisions < 20% → 150%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("5000"),  # 5% of 100k
            provision_deducted=Decimal("0"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_crr_defaulted_high_provision_100pct(self, sa_calculator, crr_config):
        """No non-fin collateral, provisions >= 20% → 100%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("25000"),  # 25% of 100k
            provision_deducted=Decimal("0"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_crr_defaulted_zero_provision_150pct(self, sa_calculator, crr_config):
        """Zero provisions → 150%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_crr_defaulted_missing_crm_columns(self, sa_calculator, crr_config):
        """When CRM columns are absent, no effect — standard behaviour."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("5000"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)


# ---------------------------------------------------------------------------
# CRR: non-financial collateral columns are ignored by the defaulted override
# ---------------------------------------------------------------------------


class TestCRRDefaultedNonFinCollateralIgnored:
    """Art. 127(2): CRM stage has already netted eligible collateral from EAD.

    The defaulted override does not apply a secondary secured/unsecured split
    on non-financial collateral columns — that would double-count. The full
    post-CRM ``ead_final`` is subject to the 100%/150% provision test.
    """

    def test_crr_defaulted_corporate_with_re_collateral_gets_150pct(
        self, sa_calculator, crr_config
    ):
        """Corporate defaulted, collateral_re_value populated, provisions 0 → 150%.

        Old behaviour blended to 1.20; under Art. 127(2) the full ead_final
        is unsecured (CRM already netted eligible collateral), so 150% flat.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            collateral_re_value=Decimal("60000"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_crr_defaulted_corporate_full_re_coverage_still_150pct(self, sa_calculator, crr_config):
        """RE collateral > EAD does NOT reduce the defaulted RW.

        Regression guard: previously secured_pct clipped to 1.0 drove the
        blended RW to the exposure's class base (100% corporate, 75% retail),
        undermining Art. 127(1)'s 100% floor.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            collateral_re_value=Decimal("120000"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_crr_defaulted_retail_full_re_coverage_still_150pct(self, sa_calculator, crr_config):
        """User-reported scenario: defaulted retail with non-fin collateral must
        not return the retail 75% base.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="RETAIL_OTHER",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            collateral_re_value=Decimal("120000"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_crr_defaulted_mixed_collateral_types_gets_150pct(self, sa_calculator, crr_config):
        """RE + receivables + other physical populated → still 150% (CRM already
        netted eligible collateral)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            collateral_re_value=Decimal("30000"),
            collateral_receivables_value=Decimal("20000"),
            collateral_other_physical_value=Decimal("10000"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_crr_defaulted_provision_threshold_on_full_ead(self, sa_calculator, crr_config):
        """CRR denominator = ead_final + provision_deducted (pre-provision value).

        EAD=100k, provision_deducted=10k → denominator = 110k.
        Provisions 25k >= 20% × 110k = 22k → 100%.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("25000"),
            provision_deducted=Decimal("10000"),
            collateral_re_value=Decimal("50000"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_crr_defaulted_rwa_correctness(self, sa_calculator, crr_config):
        """RWA = EAD × defaulted_rw regardless of non-fin collateral."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("200000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            collateral_re_value=Decimal("100000"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)
        assert result["rwa"] == pytest.approx(300000.0)


# ---------------------------------------------------------------------------
# B31: no non-financial collateral
# ---------------------------------------------------------------------------


class TestB31DefaultedBackwardCompat:
    """B31 defaulted exposures without non-financial collateral."""

    def test_b31_defaulted_low_provision_150pct(self, sa_calculator, b31_config):
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("5000"),
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_b31_defaulted_high_provision_100pct(self, sa_calculator, b31_config):
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("25000"),
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)


# ---------------------------------------------------------------------------
# B31: non-financial collateral columns ignored
# ---------------------------------------------------------------------------


class TestB31DefaultedNonFinCollateralIgnored:
    """B31 Art. 127(2) / CRE20.90 — CRM method determines unsecured portion;
    no secondary split inside the defaulted override."""

    def test_b31_defaulted_corporate_with_re_collateral_gets_150pct(
        self, sa_calculator, b31_config
    ):
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            collateral_re_value=Decimal("60000"),
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_b31_defaulted_provision_threshold_on_full_ead(self, sa_calculator, b31_config):
        """B31 denominator is ead_final (outstanding amount per Art. 127(1)).

        EAD=100k, provisions 20k = 20% × 100k → 100%.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("20000"),
            collateral_re_value=Decimal("80000"),
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)


# ---------------------------------------------------------------------------
# B31: RESI RE exceptions (Art. 127(3) / CRE20.88)
# ---------------------------------------------------------------------------


class TestB31DefaultedResiRE:
    """B31 RESI RE defaulted exceptions (CRE20.88)."""

    def test_b31_resi_re_non_income_flat_100pct(self, sa_calculator, b31_config):
        """Non-income RESI RE default = 100% flat for whole exposure."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="RETAIL_MORTGAGE",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            collateral_re_value=Decimal("80000"),
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_b31_resi_re_income_dependent_gets_provision_test(self, sa_calculator, b31_config):
        """Income-dependent RESI RE default → provision-based on full EAD."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="RETAIL_MORTGAGE",
            is_defaulted=True,
            has_income_cover=True,
            provision_allocated=Decimal("0"),
            collateral_re_value=Decimal("60000"),
            ltv=Decimal("0.50"),
            config=b31_config,
        )
        # Income-dependent + low provisions → 150% flat (Art. 127(3) doesn't
        # apply; full ead_final is unsecured per Art. 127(2)).
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_b31_resi_re_non_income_no_collateral_still_100pct(self, sa_calculator, b31_config):
        """Non-income RESI RE without collateral → still 100% flat."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="RETAIL_MORTGAGE",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)


# ---------------------------------------------------------------------------
# Cross-cutting: High-risk, non-defaulted, edge cases
# ---------------------------------------------------------------------------


class TestDefaultedEdgeCases:
    """Edge cases and cross-cutting concerns."""

    def test_high_risk_unaffected(self, sa_calculator, crr_config):
        """HIGH_RISK exposure → 150% via Art. 128, defaulted override skipped."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="HIGH_RISK",
            is_defaulted=True,
            provision_allocated=Decimal("50000"),
            collateral_re_value=Decimal("80000"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_non_defaulted_unaffected(self, sa_calculator, crr_config):
        """Non-defaulted corporate → normal RW, defaulted override does not fire."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=False,
            collateral_re_value=Decimal("80000"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_defaulted_retail_no_collateral_150pct(self, sa_calculator, crr_config):
        """User-reported scenario: defaulted retail with zero provisions → 150%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("50000"),
            exposure_class="RETAIL_OTHER",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_defaulted_retail_with_receivables_collateral_still_150pct(
        self, sa_calculator, crr_config
    ):
        """Non-financial collateral on retail does not lower the defaulted RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("50000"),
            exposure_class="RETAIL_OTHER",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            collateral_receivables_value=Decimal("20000"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_defaulted_zero_ead_unchanged(self, sa_calculator, crr_config):
        """Zero EAD → rwa = 0 regardless of risk weight, no error."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("0"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            collateral_re_value=Decimal("50000"),
            config=crr_config,
        )
        assert result["rwa"] == pytest.approx(0.0)
