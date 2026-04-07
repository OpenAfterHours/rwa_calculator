"""
Tests for Art. 127 defaulted exposure secured/unsecured split.

CRR Art. 127(1)-(2) / CRE20.89-90 require that defaulted exposures be split
into secured (non-financial collateral) and unsecured portions:
- Secured portion: retains the base (non-defaulted) risk weight
- Unsecured portion: 100% if provisions >= 20% of unsecured value, else 150%

Financial collateral already reduces EAD before the SA calculator runs.
Non-financial collateral (RE, receivables, other physical) provides
additional secured coverage that reduces the portion subject to the
defaulted 100%/150% override.

Why this matters: without the split, well-collateralised defaulted exposures
are assigned 100%/150% on the entire EAD (including the portion backed by
collateral), systematically overstating capital requirements.

References:
- CRR Art. 127(1): unsecured part risk weight (100%/150%)
- CRR Art. 127(2): secured/unsecured determination via eligible CRM
- CRE20.88: B31 RESI RE non-income flat 100%
- CRE20.89-90: B31 defaulted provision test and CRM eligibility
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
# CRR: Backward compatibility — no non-financial collateral
# ---------------------------------------------------------------------------


class TestCRRDefaultedBackwardCompat:
    """Defaulted exposures without non-financial collateral behave as before."""

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
        """When CRM columns are absent, defaults to 0 → no collateral → standard behaviour."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("5000"),
            config=crr_config,
        )
        # No collateral_re_value passed → defaults to 0 → full 150%
        assert result["risk_weight"] == pytest.approx(1.50)


# ---------------------------------------------------------------------------
# CRR: Secured/unsecured split with non-financial collateral
# ---------------------------------------------------------------------------


class TestCRRDefaultedSecuredSplit:
    """Art. 127(2) secured/unsecured split with non-financial collateral."""

    def test_crr_defaulted_with_re_collateral_blended(self, sa_calculator, crr_config):
        """RE collateral 60k on 100k EAD → 60% secured at base RW, 40% unsecured at 150%.

        Base RW for corporate = 100% (from CQS join, unrated).
        Unsecured portion = 40k. Provisions 0 < 20% of 40k = 8k → 150%.
        Blended = 0.40 × 1.50 + 0.60 × 1.00 = 1.20.
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
        assert result["risk_weight"] == pytest.approx(1.20)

    def test_crr_defaulted_fully_secured_base_rw(self, sa_calculator, crr_config):
        """RE collateral >= EAD → fully secured → base RW only.

        Secured pct = 100%, so blended = 0×150% + 1.0×100% = 100%.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            collateral_re_value=Decimal("120000"),  # > EAD
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_crr_defaulted_provision_threshold_uses_unsecured(self, sa_calculator, crr_config):
        """Provisions 5k sufficient for unsecured 20k (25%) but not for total 100k (5%).

        EAD=100k, RE collateral=80k → unsecured=20k.
        CRR denominator = (unsecured_ead + provision_deducted) × unsecured_pct
          = (100k + 0) × 0.2 = 20k.
        Provision 5k >= 20% of 20k = 4k → 100% for unsecured.
        Blended = 0.2 × 1.0 + 0.8 × 1.0 = 1.0 (100%).
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("5000"),
            provision_deducted=Decimal("0"),
            collateral_re_value=Decimal("80000"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_crr_defaulted_mixed_collateral_types(self, sa_calculator, crr_config):
        """RE 30k + receivables 20k + other 10k = 60k total non-fin collateral.

        EAD=100k, total non-fin=60k → 60% secured, 40% unsecured.
        Provisions 0 → 150% for unsecured.
        Base RW = 100% (unrated corporate).
        Blended = 0.4 × 1.50 + 0.6 × 1.00 = 1.20.
        """
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
        assert result["risk_weight"] == pytest.approx(1.20)

    def test_crr_defaulted_provision_deducted_in_denominator(self, sa_calculator, crr_config):
        """CRR adds provision_deducted to denominator — test with deducted provisions.

        EAD=100k, provision_deducted=10k, RE collateral=50k.
        Pre-provision EAD = 100k + 10k = 110k.
        Unsecured pre-provision = 110k × (1 - 50k/100k) = 110k × 0.5 = 55k.
        Provision 12k >= 20% of 55k = 11k → 100% for unsecured.
        Blended = 0.5 × 1.0 + 0.5 × 1.0 = 1.0.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("12000"),
            provision_deducted=Decimal("10000"),
            collateral_re_value=Decimal("50000"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_crr_defaulted_rwa_correctness(self, sa_calculator, crr_config):
        """Verify RWA = EAD × blended_rw.

        EAD=200k, RE collateral=100k → 50% secured.
        Provisions 0 → 150% for unsecured.
        Base RW = 100% (unrated corporate).
        Blended = 0.5 × 1.50 + 0.5 × 1.00 = 1.25.
        RWA = 200k × 1.25 = 250k.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("200000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            collateral_re_value=Decimal("100000"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.25)
        assert result["rwa"] == pytest.approx(250000.0)


# ---------------------------------------------------------------------------
# B31: Backward compatibility — no non-financial collateral
# ---------------------------------------------------------------------------


class TestB31DefaultedBackwardCompat:
    """B31 defaulted exposures without non-financial collateral behave as before."""

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
# B31: Secured/unsecured split
# ---------------------------------------------------------------------------


class TestB31DefaultedSecuredSplit:
    """Basel 3.1 Art. 127 / CRE20.89-90 secured/unsecured split."""

    def test_b31_defaulted_with_re_collateral_blended(self, sa_calculator, b31_config):
        """RE collateral 60k on 100k EAD → 60% secured, 40% unsecured.

        B31 base RW for unrated corporate = 100%.
        Unsecured = 40k. Provisions 0 < 20% of 40k = 8k → 150%.
        Blended = 0.4 × 1.50 + 0.6 × 1.00 = 1.20.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            collateral_re_value=Decimal("60000"),
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.20)

    def test_b31_defaulted_provision_threshold_uses_unsecured(self, sa_calculator, b31_config):
        """Provisions 5k sufficient for unsecured 20k but not total 100k.

        EAD=100k, RE=80k → unsecured=20k.
        B31 denominator = unsecured_ead = 100k × 0.2 = 20k.
        5k >= 20% of 20k = 4k → 100%.
        Blended = 0.2 × 1.0 + 0.8 × 1.0 = 1.0.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("5000"),
            collateral_re_value=Decimal("80000"),
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00)


# ---------------------------------------------------------------------------
# B31: RESI RE exceptions
# ---------------------------------------------------------------------------


class TestB31DefaultedResiRE:
    """B31 RESI RE defaulted exceptions (CRE20.88)."""

    def test_b31_resi_re_non_income_flat_100pct_no_split(self, sa_calculator, b31_config):
        """Non-income RESI RE default = 100% flat for whole exposure (CRE20.88).

        The secured/unsecured split does NOT apply to RESI RE non-income.
        Even with RE collateral that would lower the blended RW, the
        regulatory 100% flat overrides.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="RETAIL_MORTGAGE",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            collateral_re_value=Decimal("80000"),
            config=b31_config,
        )
        # 100% flat — no blending with base RW
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_b31_resi_re_income_dependent_gets_split(self, sa_calculator, b31_config):
        """Income-dependent RESI RE default → provision-based with split.

        EAD=100k, has_income_cover=True, RE collateral=60k.
        Base RW for RESI RE = depends on LTV; with null LTV → falls through
        to loan-splitting default. We use a specific LTV to get a known base RW.
        """
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
        # Income-dependent → provision test applies with split
        # Base RW < 100% for well-secured mortgage, blended RW < 150%
        assert result["risk_weight"] < 1.50

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

    def test_high_risk_unaffected_by_split(self, sa_calculator, crr_config):
        """HIGH_RISK exposure → 150% regardless of collateral or provisions."""
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
        """Non-defaulted corporate → normal RW, collateral has no defaulted effect."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=False,
            collateral_re_value=Decimal("80000"),
            config=crr_config,
        )
        # Unrated corporate = 100% (not affected by defaulted logic)
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_crr_b31_same_behaviour_no_collateral(self, sa_calculator, crr_config, b31_config):
        """Both frameworks give same result without non-financial collateral."""
        crr_result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("5000"),
            config=crr_config,
        )
        b31_result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("5000"),
            config=b31_config,
        )
        assert crr_result["risk_weight"] == pytest.approx(b31_result["risk_weight"])

    def test_defaulted_mortgage_gets_split_crr(self, sa_calculator, crr_config):
        """CRR defaulted mortgage with RE collateral gets blended RW.

        CRR has no RESI RE flat-100% exception. All defaulted classes
        (except HIGH_RISK) get the provision-based split.
        EAD=100k, RE=60k. Base RW for mortgage LTV≤80% = 35%.
        Unsecured=40k. Provisions 0 < 20% of 40k → 150%.
        Blended = 0.4 × 1.50 + 0.6 × 0.35 = 0.60 + 0.21 = 0.81.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="RETAIL_MORTGAGE",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            ltv=Decimal("0.60"),
            collateral_re_value=Decimal("60000"),
            config=crr_config,
        )
        # Base RW for CRR mortgage LTV=60% (≤80% threshold) = 35%
        # Blended: 0.4 × 1.50 + 0.6 × 0.35 = 0.81
        assert result["risk_weight"] == pytest.approx(0.81, rel=0.01)

    def test_defaulted_zero_ead_unchanged(self, sa_calculator, crr_config):
        """Zero EAD → secured_pct = 0, RW doesn't matter but should not error."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("0"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            collateral_re_value=Decimal("50000"),
            config=crr_config,
        )
        # Zero EAD → rwa = 0 regardless of risk weight
        assert result["rwa"] == pytest.approx(0.0)

    def test_defaulted_retail_with_receivables_collateral(self, sa_calculator, crr_config):
        """Defaulted retail with receivables collateral.

        EAD=50k, receivables=20k → 40% secured, 60% unsecured.
        Base RW for retail = 75%.
        Provisions 0 → 150% for unsecured.
        Blended = 0.6 × 1.50 + 0.4 × 0.75 = 0.90 + 0.30 = 1.20.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("50000"),
            exposure_class="RETAIL_OTHER",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            collateral_receivables_value=Decimal("20000"),
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.20)
