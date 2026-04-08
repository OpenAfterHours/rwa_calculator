"""
Basel 3.1 Group K: Defaulted Exposure Acceptance Tests.

Tests validate the production calculator correctly handles defaulted
exposures under Basel 3.1 PRA PS1/26 Art. 127 and IRB Art. 153/154.

SA defaulted treatment (B31-K1 through B31-K8):
- Provision threshold at 20% of unsecured EAD (B31 denominator, not CRR's EAD + provision_deducted)
- 100% RW when provisions meet threshold, 150% when below
- RESI RE non-income-dependent: 100% flat regardless of provisions (CRE20.88)
- Secured/unsecured split with non-financial collateral (Art. 127(2))

IRB defaulted treatment (B31-K9 through B31-K12):
- F-IRB: K=0, RWA=0 (capital addressed via provisions)
- A-IRB: K = max(0, LGD_in_default - BEEL)
- No 1.06 scaling factor (Basel 3.1 removes CRR Art. 153(1) scaling)
- No Vasicek correlation or maturity adjustment for defaulted exposures

Regulatory References:
- PRA PS1/26 Art. 127: Defaulted SA risk weights and provision thresholds
- CRE20.88: RESI RE non-income defaulted flat 100% (Basel 3.1 only)
- CRE20.89-90: Defaulted provision test and secured/unsecured split
- PRA PS1/26 Art. 153/154: IRB defaulted treatment (no 1.06 scaling)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.irb import IRBLazyFrame  # noqa: F401 - registers namespace
from rwa_calc.engine.sa.calculator import SACalculator
from tests.fixtures.single_exposure import calculate_single_sa_exposure

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Basel 3.1 SA config for defaulted exposure tests."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def b31_irb_config() -> CalculationConfig:
    """Basel 3.1 IRB config for defaulted exposure tests."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def sa_calculator() -> SACalculator:
    """SA calculator instance."""
    return SACalculator()


# =============================================================================
# IRB Helper
# =============================================================================


def _build_b31_defaulted_exposure(
    *,
    exposure_ref: str,
    exposure_class: str,
    approach: str,
    is_airb: bool,
    lgd: float,
    beel: float,
    ead_final: float,
    maturity: float = 2.5,
) -> pl.LazyFrame:
    """Build a single defaulted exposure for B31 IRB acceptance testing."""
    return pl.LazyFrame(
        {
            "exposure_reference": [exposure_ref],
            "counterparty_reference": [f"CP_{exposure_ref}"],
            "pd": [1.0],  # Defaulted = PD 100%
            "lgd": [lgd],
            "beel": [beel],
            "ead_final": [ead_final],
            "exposure_class": [exposure_class],
            "maturity": [maturity],
            "approach": [approach],
            "is_airb": [is_airb],
            "is_defaulted": [True],
        }
    )


# =============================================================================
# B31-K1: Corporate Defaulted, High Provision → 100% RW
# =============================================================================


class TestB31K1_CorporateDefaultedHighProvision:
    """
    B31-K1: SA corporate defaulted with provision >= 20% threshold.

    Input: Corporate, EAD=100,000, provision_allocated=25,000 (25% of EAD)
    Expected: provision_allocated (25k) >= 20% × unsecured_ead (100k) → 100%
              RWA = 100,000 × 1.0 = 100,000
    """

    def test_b31_k1_risk_weight_100pct(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """High provision defaulted corporate gets 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("25000"),
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00, abs=1e-4)

    def test_b31_k1_rwa(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """High provision defaulted corporate: RWA = EAD × 100%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("25000"),
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(100_000.0, rel=1e-4)


# =============================================================================
# B31-K2: Corporate Defaulted, Low Provision → 150% RW
# =============================================================================


class TestB31K2_CorporateDefaultedLowProvision:
    """
    B31-K2: SA corporate defaulted with provision < 20% threshold.

    Input: Corporate, EAD=100,000, provision_allocated=15,000 (15% of EAD)
    Expected: provision_allocated (15k) < 20% × unsecured_ead (100k) → 150%
              RWA = 100,000 × 1.5 = 150,000
    """

    def test_b31_k2_risk_weight_150pct(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Low provision defaulted corporate gets 150% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("15000"),
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50, abs=1e-4)

    def test_b31_k2_rwa(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Low provision defaulted corporate: RWA = EAD × 150%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("15000"),
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(150_000.0, rel=1e-4)


# =============================================================================
# B31-K3: Corporate Defaulted, Zero Provision → 150% RW
# =============================================================================


class TestB31K3_CorporateDefaultedZeroProvision:
    """
    B31-K3: SA corporate defaulted with zero provisions.

    Input: Corporate, EAD=500,000, provision_allocated=0
    Expected: 0 < 20% × 500,000 = 100,000 → 150%
              RWA = 500,000 × 1.5 = 750,000
    """

    def test_b31_k3_risk_weight_150pct(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Zero provision defaulted corporate gets 150% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50, abs=1e-4)

    def test_b31_k3_rwa(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Zero provision defaulted corporate: RWA = EAD × 150%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("0"),
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(750_000.0, rel=1e-4)


# =============================================================================
# B31-K4: RESI RE Non-Income Defaulted → 100% Flat (CRE20.88 Exception)
# =============================================================================


class TestB31K4_ResiREnonIncomeDefaulted:
    """
    B31-K4: Basel 3.1 RESI RE non-income-dependent defaulted → 100% flat.

    Art. 127 / CRE20.88 exception: general residential RE (owner-occupied,
    non-income-dependent) defaulted exposures always get 100% flat regardless
    of provision level. This is a Basel 3.1-only simplification.

    Input: RETAIL_MORTGAGE, EAD=200,000, has_income_cover=False, provision=0
    Expected: 100% flat (exception overrides provision test)
              RWA = 200,000
    """

    def test_b31_k4_risk_weight_100pct_flat(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """B31 RESI RE non-income defaulted: 100% flat regardless of provisions."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("200000"),
            exposure_class="RETAIL_MORTGAGE",
            is_defaulted=True,
            has_income_cover=False,
            provision_allocated=Decimal("0"),
            property_type="residential",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00, abs=1e-4)

    def test_b31_k4_rwa(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """B31 RESI RE non-income defaulted: RWA = EAD × 100%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("200000"),
            exposure_class="RETAIL_MORTGAGE",
            is_defaulted=True,
            has_income_cover=False,
            provision_allocated=Decimal("0"),
            property_type="residential",
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(200_000.0, rel=1e-4)

    def test_b31_k4_exception_overrides_low_provision(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Zero provision would normally give 150%, but RESI RE exception gives 100%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("200000"),
            exposure_class="RETAIL_MORTGAGE",
            is_defaulted=True,
            has_income_cover=False,
            provision_allocated=Decimal("0"),
            property_type="residential",
            config=b31_config,
        )
        # Without exception, zero provision → 150%. Exception overrides to 100%.
        assert result["risk_weight"] < 1.50


# =============================================================================
# B31-K5: RESI RE Non-Income Defaulted with Collateral → Still 100% Flat
# =============================================================================


class TestB31K5_ResiREnonIncomeWithCollateral:
    """
    B31-K5: RESI RE non-income defaulted with RE collateral → still 100% flat.

    The CRE20.88 exception applies to the WHOLE exposure. Even with non-financial
    collateral that would normally create a secured/unsecured split, the 100%
    flat override prevails.

    Input: RETAIL_MORTGAGE, EAD=200,000, has_income_cover=False, provision=0,
           collateral_re_value=120,000
    Expected: 100% flat (exception overrides collateral split)
              RWA = 200,000
    """

    def test_b31_k5_risk_weight_100pct_flat(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Collateral does not override RESI RE exception — still 100% flat."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("200000"),
            exposure_class="RETAIL_MORTGAGE",
            is_defaulted=True,
            has_income_cover=False,
            provision_allocated=Decimal("0"),
            collateral_re_value=Decimal("120000"),
            property_type="residential",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.00, abs=1e-4)

    def test_b31_k5_rwa(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """RESI RE exception with collateral: RWA = EAD × 100%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("200000"),
            exposure_class="RETAIL_MORTGAGE",
            is_defaulted=True,
            has_income_cover=False,
            provision_allocated=Decimal("0"),
            collateral_re_value=Decimal("120000"),
            property_type="residential",
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(200_000.0, rel=1e-4)


# =============================================================================
# B31-K6: RESI RE Income-Dependent Defaulted → Provision Test (No Exception)
# =============================================================================


class TestB31K6_ResiREIncomeDefaulted:
    """
    B31-K6: Income-dependent RESI RE is NOT eligible for the CRE20.88 exception.

    When has_income_cover=True (IPRRE), the standard provision-based test applies.
    Without collateral, the full EAD is unsecured.

    Input: RETAIL_MORTGAGE, EAD=200,000, has_income_cover=True, provision=5,000
    Expected: 5,000 < 20% × 200,000 = 40,000 → 150%
              RWA = 200,000 × 1.5 = 300,000
    """

    def test_b31_k6_risk_weight_150pct(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Income-dependent RESI RE defaulted: no exception, uses provision test."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("200000"),
            exposure_class="RETAIL_MORTGAGE",
            is_defaulted=True,
            has_income_cover=True,
            provision_allocated=Decimal("5000"),
            property_type="residential",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50, abs=1e-4)

    def test_b31_k6_rwa(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Income-dependent RESI RE defaulted: RWA = EAD × 150%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("200000"),
            exposure_class="RETAIL_MORTGAGE",
            is_defaulted=True,
            has_income_cover=True,
            provision_allocated=Decimal("5000"),
            property_type="residential",
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(300_000.0, rel=1e-4)


# =============================================================================
# B31-K7: Corporate with RE Collateral → Blended Secured/Unsecured RW
# =============================================================================


class TestB31K7_CorporateDefaultedWithCollateral:
    """
    B31-K7: Defaulted corporate with non-financial collateral → blended RW.

    Art. 127(2) secured/unsecured split: secured portion retains base RW,
    unsecured portion gets 100%/150% based on provision threshold.

    Input: Corporate CQS=2 (base RW=50%), EAD=100,000, collateral_re_value=60,000,
           provision_allocated=2,000
    Expected: secured_pct = 60k/100k = 0.6, unsecured_pct = 0.4
              unsecured_ead = 40,000
              2,000 < 20% × 40,000 = 8,000 → provision_rw = 150%
              blended_rw = 0.4 × 1.50 + 0.6 × 0.50 = 0.60 + 0.30 = 0.90
              RWA = 100,000 × 0.90 = 90,000
    """

    def test_b31_k7_blended_risk_weight(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Collateral split blends 150% unsecured with 50% base secured."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            cqs=2,
            is_defaulted=True,
            provision_allocated=Decimal("2000"),
            collateral_re_value=Decimal("60000"),
            config=b31_config,
        )
        # blended = 0.4 × 1.50 + 0.6 × 0.50 = 0.90
        assert result["risk_weight"] == pytest.approx(0.90, abs=1e-2)

    def test_b31_k7_rwa(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Collateral split: RWA = EAD × blended_rw."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("100000"),
            exposure_class="CORPORATE",
            cqs=2,
            is_defaulted=True,
            provision_allocated=Decimal("2000"),
            collateral_re_value=Decimal("60000"),
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(90_000.0, rel=1e-2)


# =============================================================================
# B31-K8: B31 Provision Denominator Uses Unsecured EAD (Not Pre-Provision)
# =============================================================================


class TestB31K8_ProvisionDenominatorDifference:
    """
    B31-K8: B31 provision denominator = unsecured EAD, NOT EAD + provision_deducted.

    This tests the B31-specific denominator. Under CRR, provision_deducted inflates
    the denominator, making the 20% threshold harder to meet. Under B31, only the
    current unsecured EAD matters.

    Input: Corporate, EAD=80,000 (post-deduction), provision_deducted=20,000,
           provision_allocated=16,500
    Expected (B31): 16,500 >= 20% × 80,000 = 16,000 → 100% ✓
    Contrast (CRR): 16,500 < 20% × (80,000 + 20,000) = 20,000 → 150%
    RWA = 80,000 × 1.0 = 80,000
    """

    def test_b31_k8_risk_weight_100pct(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """B31 denominator: provision meets threshold using unsecured EAD only."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("80000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("16500"),
            provision_deducted=Decimal("20000"),
            config=b31_config,
        )
        # B31: 16,500 >= 0.2 × 80,000 = 16,000 → 100%
        assert result["risk_weight"] == pytest.approx(1.00, abs=1e-4)

    def test_b31_k8_rwa(
        self, sa_calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """B31 denominator: RWA = EAD × 100%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("80000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("16500"),
            provision_deducted=Decimal("20000"),
            config=b31_config,
        )
        assert result["rwa"] == pytest.approx(80_000.0, rel=1e-4)

    def test_b31_k8_crr_contrast_would_give_150pct(
        self, sa_calculator: SACalculator
    ) -> None:
        """Under CRR, same inputs give 150% due to larger denominator."""
        crr_config = CalculationConfig.crr(reporting_date=date(2025, 12, 31))
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("80000"),
            exposure_class="CORPORATE",
            is_defaulted=True,
            provision_allocated=Decimal("16500"),
            provision_deducted=Decimal("20000"),
            config=crr_config,
        )
        # CRR: 16,500 < 0.2 × (80,000 + 20,000) = 20,000 → 150%
        assert result["risk_weight"] == pytest.approx(1.50, abs=1e-4)


# =============================================================================
# B31-K9: F-IRB Corporate Defaulted → K=0, RWA=0
# =============================================================================


class TestB31K9_FIRBCorporateDefaulted:
    """
    B31-K9: F-IRB corporate defaulted under Basel 3.1.

    F-IRB defaulted always gives K=0, RWA=0 — capital is addressed via
    provisions. Same result as CRR (CRR-I1) since F-IRB K=0 regardless
    of scaling factor.

    Input: Corporate, PD=100%, supervisory LGD=45%, EAD=500,000
    Expected: K=0, RW=0%, RWA=0, EL=LGD×EAD=225,000
    """

    def test_b31_k9_k_is_zero(self, b31_irb_config: CalculationConfig) -> None:
        """B31 F-IRB defaulted corporate: K=0."""
        lf = _build_b31_defaulted_exposure(
            exposure_ref="B31_K9_CORP",
            exposure_class="CORPORATE",
            approach="foundation_irb",
            is_airb=False,
            lgd=0.45,
            beel=0.0,
            ead_final=500_000.0,
        )
        result = (
            lf.irb.prepare_columns(b31_irb_config)
            .irb.apply_all_formulas(b31_irb_config)
            .collect()
        )
        assert result["k"][0] == pytest.approx(0.0, abs=1e-10)

    def test_b31_k9_rwa_is_zero(self, b31_irb_config: CalculationConfig) -> None:
        """B31 F-IRB defaulted corporate: RWA=0 and RW=0."""
        lf = _build_b31_defaulted_exposure(
            exposure_ref="B31_K9_CORP",
            exposure_class="CORPORATE",
            approach="foundation_irb",
            is_airb=False,
            lgd=0.45,
            beel=0.0,
            ead_final=500_000.0,
        )
        result = (
            lf.irb.prepare_columns(b31_irb_config)
            .irb.apply_all_formulas(b31_irb_config)
            .collect()
        )
        assert result["rwa"][0] == pytest.approx(0.0, abs=1e-6)
        assert result["risk_weight"][0] == pytest.approx(0.0, abs=1e-6)

    def test_b31_k9_expected_loss(self, b31_irb_config: CalculationConfig) -> None:
        """B31 F-IRB defaulted corporate: EL = LGD × EAD = 225,000."""
        lf = _build_b31_defaulted_exposure(
            exposure_ref="B31_K9_CORP",
            exposure_class="CORPORATE",
            approach="foundation_irb",
            is_airb=False,
            lgd=0.45,
            beel=0.0,
            ead_final=500_000.0,
        )
        result = (
            lf.irb.prepare_columns(b31_irb_config)
            .irb.apply_all_formulas(b31_irb_config)
            .collect()
        )
        assert result["expected_loss"][0] == pytest.approx(225_000.0, rel=1e-6)


# =============================================================================
# B31-K10: A-IRB Retail Defaulted → No Scaling
# =============================================================================


class TestB31K10_AIRBRetailDefaulted:
    """
    B31-K10: A-IRB retail defaulted under Basel 3.1.

    Retail exposures use scaling=1.0 under both CRR and B31, so the result
    is identical to CRR-I2. Included to confirm B31 pathway works correctly.

    Input: Retail Other, PD=100%, LGD_in_default=65%, BEEL=50%, EAD=25,000
    Expected: K=max(0, 0.65-0.50)=0.15, RWA=0.15×12.5×1.0×25,000=46,875
              EL = BEEL × EAD = 12,500
    """

    def test_b31_k10_k_value(self, b31_irb_config: CalculationConfig) -> None:
        """B31 A-IRB retail defaulted: K = max(0, 0.65 - 0.50) = 0.15."""
        lf = _build_b31_defaulted_exposure(
            exposure_ref="B31_K10_RTL",
            exposure_class="RETAIL_OTHER",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.65,
            beel=0.50,
            ead_final=25_000.0,
        )
        result = (
            lf.irb.prepare_columns(b31_irb_config)
            .irb.apply_all_formulas(b31_irb_config)
            .collect()
        )
        assert result["k"][0] == pytest.approx(0.15, abs=1e-10)

    def test_b31_k10_rwa(self, b31_irb_config: CalculationConfig) -> None:
        """B31 A-IRB retail defaulted: RWA = K × 12.5 × 1.0 × EAD = 46,875."""
        lf = _build_b31_defaulted_exposure(
            exposure_ref="B31_K10_RTL",
            exposure_class="RETAIL_OTHER",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.65,
            beel=0.50,
            ead_final=25_000.0,
        )
        result = (
            lf.irb.prepare_columns(b31_irb_config)
            .irb.apply_all_formulas(b31_irb_config)
            .collect()
        )
        expected_rwa = 0.15 * 12.5 * 1.0 * 25_000.0  # 46,875
        assert result["rwa"][0] == pytest.approx(expected_rwa, rel=1e-6)

    def test_b31_k10_expected_loss(self, b31_irb_config: CalculationConfig) -> None:
        """B31 A-IRB retail defaulted: EL = BEEL × EAD = 12,500."""
        lf = _build_b31_defaulted_exposure(
            exposure_ref="B31_K10_RTL",
            exposure_class="RETAIL_OTHER",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.65,
            beel=0.50,
            ead_final=25_000.0,
        )
        result = (
            lf.irb.prepare_columns(b31_irb_config)
            .irb.apply_all_formulas(b31_irb_config)
            .collect()
        )
        assert result["expected_loss"][0] == pytest.approx(12_500.0, rel=1e-6)


# =============================================================================
# B31-K11: A-IRB Corporate Defaulted → NO 1.06 Scaling (Key B31 Difference)
# =============================================================================


class TestB31K11_AIRBCorporateDefaultedNoScaling:
    """
    B31-K11: A-IRB corporate defaulted under Basel 3.1 — no 1.06 scaling.

    This is the KEY B31 vs CRR difference for IRB defaulted exposures. Under CRR,
    non-retail A-IRB defaulted exposures receive 1.06 scaling (CRR-I3: RWA=993,750).
    Under B31, scaling is always 1.0 (RWA=937,500), a 6% reduction.

    Input: Corporate, PD=100%, LGD_in_default=60%, BEEL=45%, EAD=500,000
    Expected: K=max(0, 0.60-0.45)=0.15
              RWA = 0.15 × 12.5 × 1.0 × 500,000 = 937,500 (CRR: 993,750)
              EL = BEEL × EAD = 225,000
    """

    def test_b31_k11_k_value(self, b31_irb_config: CalculationConfig) -> None:
        """B31 A-IRB corporate defaulted: K = 0.15."""
        lf = _build_b31_defaulted_exposure(
            exposure_ref="B31_K11_CORP",
            exposure_class="CORPORATE",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.60,
            beel=0.45,
            ead_final=500_000.0,
        )
        result = (
            lf.irb.prepare_columns(b31_irb_config)
            .irb.apply_all_formulas(b31_irb_config)
            .collect()
        )
        assert result["k"][0] == pytest.approx(0.15, abs=1e-10)

    def test_b31_k11_rwa_no_scaling(self, b31_irb_config: CalculationConfig) -> None:
        """B31 A-IRB corporate defaulted: RWA = K × 12.5 × 1.0 × EAD = 937,500."""
        lf = _build_b31_defaulted_exposure(
            exposure_ref="B31_K11_CORP",
            exposure_class="CORPORATE",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.60,
            beel=0.45,
            ead_final=500_000.0,
        )
        result = (
            lf.irb.prepare_columns(b31_irb_config)
            .irb.apply_all_formulas(b31_irb_config)
            .collect()
        )
        expected_rwa = 0.15 * 12.5 * 1.0 * 500_000.0  # 937,500
        assert result["rwa"][0] == pytest.approx(expected_rwa, rel=1e-6)

    def test_b31_k11_rwa_less_than_crr(self, b31_irb_config: CalculationConfig) -> None:
        """B31 RWA is exactly 1/1.06 of CRR RWA for the same inputs."""
        lf = _build_b31_defaulted_exposure(
            exposure_ref="B31_K11_CORP",
            exposure_class="CORPORATE",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.60,
            beel=0.45,
            ead_final=500_000.0,
        )
        result = (
            lf.irb.prepare_columns(b31_irb_config)
            .irb.apply_all_formulas(b31_irb_config)
            .collect()
        )
        crr_rwa = 0.15 * 12.5 * 1.06 * 500_000.0  # 993,750 (CRR-I3)
        b31_rwa = result["rwa"][0]
        assert b31_rwa < crr_rwa
        assert b31_rwa == pytest.approx(crr_rwa / 1.06, rel=1e-6)

    def test_b31_k11_expected_loss(self, b31_irb_config: CalculationConfig) -> None:
        """B31 A-IRB corporate defaulted: EL = BEEL × EAD = 225,000."""
        lf = _build_b31_defaulted_exposure(
            exposure_ref="B31_K11_CORP",
            exposure_class="CORPORATE",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.60,
            beel=0.45,
            ead_final=500_000.0,
        )
        result = (
            lf.irb.prepare_columns(b31_irb_config)
            .irb.apply_all_formulas(b31_irb_config)
            .collect()
        )
        assert result["expected_loss"][0] == pytest.approx(225_000.0, rel=1e-6)


# =============================================================================
# B31-K12: A-IRB Corporate Defaulted, BEEL > LGD → K=0
# =============================================================================


class TestB31K12_AIRBCorporateDefaultedBEELExceedsLGD:
    """
    B31-K12: A-IRB corporate defaulted where BEEL exceeds LGD.

    When BEEL >= LGD, K = max(0, LGD - BEEL) = 0, so RWA = 0.
    The expected loss is still BEEL × EAD (bank's estimate, not supervisory).

    Input: Corporate, PD=100%, LGD_in_default=40%, BEEL=50%, EAD=300,000
    Expected: K=max(0, 0.40-0.50)=0, RWA=0, EL=BEEL×EAD=150,000
    """

    def test_b31_k12_k_is_zero(self, b31_irb_config: CalculationConfig) -> None:
        """B31 A-IRB defaulted: BEEL > LGD → K=0."""
        lf = _build_b31_defaulted_exposure(
            exposure_ref="B31_K12_CORP",
            exposure_class="CORPORATE",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.40,
            beel=0.50,
            ead_final=300_000.0,
        )
        result = (
            lf.irb.prepare_columns(b31_irb_config)
            .irb.apply_all_formulas(b31_irb_config)
            .collect()
        )
        assert result["k"][0] == pytest.approx(0.0, abs=1e-10)

    def test_b31_k12_rwa_is_zero(self, b31_irb_config: CalculationConfig) -> None:
        """B31 A-IRB defaulted: BEEL > LGD → RWA=0."""
        lf = _build_b31_defaulted_exposure(
            exposure_ref="B31_K12_CORP",
            exposure_class="CORPORATE",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.40,
            beel=0.50,
            ead_final=300_000.0,
        )
        result = (
            lf.irb.prepare_columns(b31_irb_config)
            .irb.apply_all_formulas(b31_irb_config)
            .collect()
        )
        assert result["rwa"][0] == pytest.approx(0.0, abs=1e-6)

    def test_b31_k12_expected_loss(self, b31_irb_config: CalculationConfig) -> None:
        """B31 A-IRB defaulted: EL = BEEL × EAD = 150,000 (uses BEEL, not LGD)."""
        lf = _build_b31_defaulted_exposure(
            exposure_ref="B31_K12_CORP",
            exposure_class="CORPORATE",
            approach="advanced_irb",
            is_airb=True,
            lgd=0.40,
            beel=0.50,
            ead_final=300_000.0,
        )
        result = (
            lf.irb.prepare_columns(b31_irb_config)
            .irb.apply_all_formulas(b31_irb_config)
            .collect()
        )
        assert result["expected_loss"][0] == pytest.approx(150_000.0, rel=1e-6)
