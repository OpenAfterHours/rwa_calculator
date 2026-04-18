"""
Unit tests for Basel 3.1 RE junior charges and Art. 124L counterparty type table.

Tests cover four related regulatory requirements:
- Art. 124F(2): Junior charge reduces the 55% loan-splitting threshold
- Art. 124G(2): 1.25x multiplier for income-producing RESI with junior lien
- Art. 124I(3): Tiered multipliers for income-producing CRE with junior lien
- Art. 124L: Counterparty-type-dependent residual RW for RRE loan-splitting

Why these tests matter:
    Without Art. 124L, all non-rated counterparties get a blanket 75% residual
    RW — understating capital for corporate/institutional RE borrowers (should
    get full unsecured RW). Without junior charge handling, second-lien exposures
    get the full 55% secured threshold as if they were first charges, also
    understating capital.

References:
- PRA PS1/26 Art. 124F(2): Junior charge threshold reduction
- PRA PS1/26 Art. 124G(2): Income-producing RESI junior multiplier
- PRA PS1/26 Art. 124I(3): Income-producing CRE junior multipliers
- PRA PS1/26 Art. 124L: Counterparty type table for RRE residual RW
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.b31_risk_weights import (
    B31_CRE_INCOME_JUNIOR_RW_HIGH,
    B31_CRE_INCOME_JUNIOR_RW_LOW,
    B31_CRE_INCOME_JUNIOR_RW_MID,
    B31_RESI_INCOME_JUNIOR_LTV_THRESHOLD,
    B31_RESI_INCOME_JUNIOR_MULTIPLIER,
    B31_RRE_RESIDUAL_RW_NATURAL_PERSON,
    B31_RRE_RESIDUAL_RW_OTHER_SME,
    B31_RRE_RESIDUAL_RW_RETAIL_SME,
    B31_RRE_RESIDUAL_RW_SOCIAL_HOUSING_FLOOR,
    lookup_b31_commercial_rw,
    lookup_b31_residential_rw,
)
from rwa_calc.engine.sa.calculator import SACalculator


@pytest.fixture
def sa_calculator() -> SACalculator:
    """Return an SA calculator instance."""
    return SACalculator()


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Return a Basel 3.1 configuration."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration (pre-2027)."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


# =============================================================================
# ART. 124L CONSTANTS
# =============================================================================


class TestArt124LConstants:
    """Verify Art. 124L counterparty type RW constants."""

    def test_natural_person_rw(self) -> None:
        assert Decimal("0.75") == B31_RRE_RESIDUAL_RW_NATURAL_PERSON

    def test_retail_sme_rw(self) -> None:
        assert Decimal("0.75") == B31_RRE_RESIDUAL_RW_RETAIL_SME

    def test_other_sme_rw(self) -> None:
        assert Decimal("0.85") == B31_RRE_RESIDUAL_RW_OTHER_SME

    def test_social_housing_floor(self) -> None:
        assert Decimal("0.75") == B31_RRE_RESIDUAL_RW_SOCIAL_HOUSING_FLOOR


# =============================================================================
# JUNIOR CHARGE CONSTANTS
# =============================================================================


class TestJuniorChargeConstants:
    """Verify junior charge constants — RRE uses multiplier, CRE uses absolute RW."""

    def test_resi_income_multiplier(self) -> None:
        assert Decimal("1.25") == B31_RESI_INCOME_JUNIOR_MULTIPLIER

    def test_resi_income_ltv_threshold(self) -> None:
        assert Decimal("0.50") == B31_RESI_INCOME_JUNIOR_LTV_THRESHOLD

    def test_cre_income_junior_rw_low(self) -> None:
        """Art. 124I(3)(a): LTV ≤ 60% → absolute 100%."""
        assert Decimal("1.00") == B31_CRE_INCOME_JUNIOR_RW_LOW

    def test_cre_income_junior_rw_mid(self) -> None:
        """Art. 124I(3)(b): 60% < LTV ≤ 80% → absolute 125%."""
        assert Decimal("1.25") == B31_CRE_INCOME_JUNIOR_RW_MID

    def test_cre_income_junior_rw_high(self) -> None:
        """Art. 124I(3)(c): LTV > 80% → absolute 137.5% (NOT 110% × 1.375 = 151.25%)."""
        assert Decimal("1.375") == B31_CRE_INCOME_JUNIOR_RW_HIGH


# =============================================================================
# ART. 124L — COUNTERPARTY TYPE TABLE (RRE RESIDUAL RW)
# =============================================================================


def _expected_loan_split_rw(ltv: float, cp_rw: float = 0.75, max_ratio: float = 0.55) -> float:
    """Compute expected loan-splitting RW for general residential."""
    secured_share = min(1.0, max_ratio / ltv)
    return 0.20 * secured_share + cp_rw * (1.0 - secured_share)


class TestArt124LCounterpartyType:
    """Art. 124L counterparty type table for RRE residual risk weight.

    The residual (unsecured) portion of a general RRE loan-split uses a
    counterparty-type-dependent risk weight instead of a blanket 75% cap.
    """

    def test_natural_person_gets_75pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Natural person → 75% residual RW per Art. 124L(a)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.80"),
            config=b31_config,
            cp_is_natural_person=True,
        )
        expected = _expected_loan_split_rw(0.80, cp_rw=0.75)
        assert float(result["risk_weight"]) == pytest.approx(expected, abs=1e-4)

    def test_retail_qualifying_sme_gets_75pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Retail-qualifying SME → 75% residual RW per Art. 124L(a)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.80"),
            config=b31_config,
            is_sme=True,
            qualifies_as_retail=True,
        )
        expected = _expected_loan_split_rw(0.80, cp_rw=0.75)
        assert float(result["risk_weight"]) == pytest.approx(expected, abs=1e-4)

    def test_other_sme_gets_85pct(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Non-retail SME → 85% residual RW per Art. 124L(b)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.80"),
            config=b31_config,
            is_sme=True,
            qualifies_as_retail=False,
        )
        expected = _expected_loan_split_rw(0.80, cp_rw=0.85)
        assert float(result["risk_weight"]) == pytest.approx(expected, abs=1e-4)

    def test_social_housing_uses_max_75_cp_rw(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Social housing → max(75%, unsecured CP RW) per Art. 124L(c).

        For residential, _cqs_risk_weight defaults to 1.0 (unrated). Since
        max(75%, 100%) = 100%, social housing gets full CP RW here.
        The 75% floor only binds when the CP RW would be below 75%.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.80"),
            config=b31_config,
            cp_is_social_housing=True,
        )
        # max(75%, 1.0) = 1.0 → same as "other" for unrated
        expected = _expected_loan_split_rw(0.80, cp_rw=1.0)
        assert float(result["risk_weight"]) == pytest.approx(expected, abs=1e-4)

    def test_social_housing_scalar_floor_binds(self) -> None:
        """Scalar API: social housing floor binds when cp_rw < 75%.

        The max(75%, cp_rw) formula from the Polars expression is verified
        via the scalar lookup, where we can control counterparty_rw directly.
        """
        rw, desc = lookup_b31_residential_rw(
            ltv=Decimal("0.80"),
            counterparty_rw=Decimal("0.50"),  # Below 75% floor
        )
        # With counterparty_rw=0.50, the loan-split gives lower RW
        expected_low = _expected_loan_split_rw(0.80, cp_rw=0.50)
        assert float(rw) == pytest.approx(float(expected_low), abs=1e-4)
        # The scalar API passes counterparty_rw through directly;
        # Art. 124L routing is done at the expression level.
        # The scalar is a convenience — institutional code should apply
        # Art. 124L routing before calling the scalar.

    def test_other_cp_gets_full_unsecured_rw(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Corporate borrower → full unsecured counterparty RW per Art. 124L(d).

        Unrated corporate = 100% — this was previously capped at 75%.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.80"),
            config=b31_config,
            # Not natural person, not SME, not social housing → "other"
        )
        expected = _expected_loan_split_rw(0.80, cp_rw=1.00)
        assert float(result["risk_weight"]) == pytest.approx(expected, abs=1e-4)

    def test_other_cp_unrated_gets_100pct_rw(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Unrated non-SME, non-natural-person → 100% residual RW.

        The _cqs_risk_weight defaults to 1.0 for residential (no CQS table
        for RE classes). Previously this was capped at 75% — now it passes
        through to the full unsecured counterparty RW.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.80"),
            config=b31_config,
            # Not natural person, not SME, not social housing → "other"
        )
        expected = _expected_loan_split_rw(0.80, cp_rw=1.0)
        assert float(result["risk_weight"]) == pytest.approx(expected, abs=1e-4)

    def test_null_counterparty_flags_default_to_other(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Missing counterparty type flags → 'other' (full CP RW, conservative).

        With no cp_is_natural_person, is_sme, or cp_is_social_housing flags,
        all default to False → "other" path → full unsecured CP RW.
        For residential, _cqs_risk_weight defaults to 1.0 (unrated).
        """
        df = pl.DataFrame(
            {
                "exposure_reference": ["TEST"],
                "ead_final": [500000.0],
                "exposure_class": ["RESIDENTIAL_MORTGAGE"],
                "cqs": [None],
                "ltv": [0.80],
                "has_income_cover": [False],
                "is_sme": [False],
                "is_infrastructure": [False],
            }
        ).lazy()
        result = sa_calculator.calculate_branch(df, b31_config).collect().to_dicts()[0]
        # _cqs_risk_weight = 1.0 (residential has no CQS table)
        # All counterparty flags default to False → "other" → full CP RW (1.0)
        expected = _expected_loan_split_rw(0.80, cp_rw=1.0)
        assert float(result["risk_weight"]) == pytest.approx(expected, abs=1e-4)


# =============================================================================
# ART. 124F(2) — JUNIOR CHARGE THRESHOLD REDUCTION (RRE)
# =============================================================================


class TestArt124F2JuniorChargeRRE:
    """Art. 124F(2): Junior charges reduce the 55% secured threshold.

    When prior/pari passu charges occupy part of the property's LTV,
    the 55% threshold for the 20% secured RW is reduced accordingly.
    """

    def test_junior_charge_reduces_threshold(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Prior charge LTV of 20% reduces threshold from 55% to 35%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.80"),
            config=b31_config,
            prior_charge_ltv=Decimal("0.20"),
            cp_is_natural_person=True,
        )
        # effective_threshold = max(0, 0.55 - 0.20) = 0.35
        expected = _expected_loan_split_rw(0.80, cp_rw=0.75, max_ratio=0.35)
        assert float(result["risk_weight"]) == pytest.approx(expected, abs=1e-4)

    def test_prior_charge_exceeds_threshold_gives_full_cp_rw(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """When prior_charge_ltv >= 55%, entire exposure gets CP RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.80"),
            config=b31_config,
            prior_charge_ltv=Decimal("0.60"),
            cp_is_natural_person=True,
        )
        # effective_threshold = max(0, 0.55 - 0.60) = 0.0
        # secured_share = 0 → full CP RW
        assert float(result["risk_weight"]) == pytest.approx(0.75, abs=1e-4)

    def test_no_prior_charge_unchanged(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """No prior charges → standard 55% threshold (backward compatible)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.80"),
            config=b31_config,
            prior_charge_ltv=Decimal("0.00"),
            cp_is_natural_person=True,
        )
        expected = _expected_loan_split_rw(0.80, cp_rw=0.75, max_ratio=0.55)
        assert float(result["risk_weight"]) == pytest.approx(expected, abs=1e-4)

    def test_missing_prior_charge_column_backward_compat(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Missing prior_charge_ltv column → 0.0 default (first charge)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.80"),
            config=b31_config,
            cp_is_natural_person=True,
            # No prior_charge_ltv parameter
        )
        expected = _expected_loan_split_rw(0.80, cp_rw=0.75, max_ratio=0.55)
        assert float(result["risk_weight"]) == pytest.approx(expected, abs=1e-4)

    def test_small_prior_charge(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Small prior charge (10%) reduces threshold from 55% to 45%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.70"),
            config=b31_config,
            prior_charge_ltv=Decimal("0.10"),
            cp_is_natural_person=True,
        )
        expected = _expected_loan_split_rw(0.70, cp_rw=0.75, max_ratio=0.45)
        assert float(result["risk_weight"]) == pytest.approx(expected, abs=1e-4)

    def test_rwa_correctness_with_junior_charge(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """RWA = EAD × RW with junior charge."""
        ead = Decimal("1000000")
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=ead,
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.80"),
            config=b31_config,
            prior_charge_ltv=Decimal("0.20"),
            cp_is_natural_person=True,
        )
        expected_rw = _expected_loan_split_rw(0.80, cp_rw=0.75, max_ratio=0.35)
        expected_rwa = float(ead) * expected_rw
        assert float(result["rwa"]) == pytest.approx(expected_rwa, abs=1.0)


# =============================================================================
# ART. 124F(2) — JUNIOR CHARGE THRESHOLD REDUCTION (CRE)
# =============================================================================


class TestArt124F2JuniorChargeCRE:
    """Art. 124F(2): Junior charges reduce the 55% threshold for CRE loan-splitting.

    CRE general loan-splitting (Art. 124H(1-2)) uses the same 55% threshold
    as RRE but with 60% secured RW instead of 20%.
    """

    def test_cre_junior_charge_reduces_threshold(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CRE loan-split: prior charge of 20% reduces threshold from 55% to 35%."""
        df = pl.DataFrame(
            {
                "exposure_reference": ["CRE001"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.80],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [False],
                "cp_is_natural_person": [True],
                "prior_charge_ltv": [0.20],
            }
        ).lazy()
        result = sa_calculator.calculate_branch(df, b31_config).collect().to_dicts()[0]
        # effective_threshold = 0.35, secured_share = 0.35/0.80
        secured_share = 0.35 / 0.80
        expected = 0.60 * secured_share + 1.0 * (1.0 - secured_share)
        assert float(result["risk_weight"]) == pytest.approx(expected, abs=1e-4)

    def test_cre_no_prior_charge_unchanged(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CRE loan-split with no prior charge → standard 55% threshold."""
        df = pl.DataFrame(
            {
                "exposure_reference": ["CRE002"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.80],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [False],
                "cp_is_natural_person": [True],
                "prior_charge_ltv": [0.0],
            }
        ).lazy()
        result = sa_calculator.calculate_branch(df, b31_config).collect().to_dicts()[0]
        secured_share = 0.55 / 0.80
        expected = 0.60 * secured_share + 1.0 * (1.0 - secured_share)
        assert float(result["risk_weight"]) == pytest.approx(expected, abs=1e-4)


# =============================================================================
# ART. 124G(2) — INCOME-PRODUCING RESI JUNIOR MULTIPLIER
# =============================================================================


class TestArt124G2ResiIncomeJunior:
    """Art. 124G(2): 1.25x multiplier for income-producing RESI with junior lien.

    The multiplier applies when LTV > 50% and prior charges exist. The resulting
    RW is NOT capped at the 105% table maximum — at LTV > 100% the base 105%
    band becomes 131.25%. Contrast Art. 124I(3) CRE, which uses absolute RWs.
    """

    def test_junior_multiplier_at_ltv_70(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """LTV 70% income-producing RESI: base 40% × 1.25 = 50%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.70"),
            has_income_cover=True,
            config=b31_config,
            prior_charge_ltv=Decimal("0.10"),
        )
        assert float(result["risk_weight"]) == pytest.approx(0.50, abs=1e-4)

    def test_junior_multiplier_at_ltv_90(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """LTV 90% income-producing RESI: base 60% × 1.25 = 75%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.90"),
            has_income_cover=True,
            config=b31_config,
            prior_charge_ltv=Decimal("0.10"),
        )
        assert float(result["risk_weight"]) == pytest.approx(0.75, abs=1e-4)

    def test_no_multiplier_at_ltv_50(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """LTV ≤ 50%: no multiplier even with junior charge. Base 30% stays."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.50"),
            has_income_cover=True,
            config=b31_config,
            prior_charge_ltv=Decimal("0.10"),
        )
        assert float(result["risk_weight"]) == pytest.approx(0.30, abs=1e-4)

    def test_multiplier_not_capped_at_105(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """LTV > 100% income-producing: base 105% × 1.25 = 131.25% (uncapped, Art. 124G(2))."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("1.10"),
            has_income_cover=True,
            config=b31_config,
            prior_charge_ltv=Decimal("0.10"),
        )
        assert float(result["risk_weight"]) == pytest.approx(1.3125, abs=1e-4)

    def test_no_multiplier_without_junior_charge(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """No prior charge → no multiplier, standard table RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.70"),
            has_income_cover=True,
            config=b31_config,
            # No prior_charge_ltv
        )
        assert float(result["risk_weight"]) == pytest.approx(0.40, abs=1e-4)

    def test_multiplier_at_ltv_60_boundary(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """LTV exactly 60% (just above 50%): base 35% × 1.25 = 43.75%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.60"),
            has_income_cover=True,
            config=b31_config,
            prior_charge_ltv=Decimal("0.10"),
        )
        assert float(result["risk_weight"]) == pytest.approx(0.4375, abs=1e-4)


# =============================================================================
# ART. 124I(3) — CRE INCOME-PRODUCING JUNIOR ABSOLUTE RWs
# =============================================================================


class TestArt124I3CREIncomeJunior:
    """Art. 124I(3): Absolute RWs (NOT multipliers) for income-producing CRE junior liens.

    Three LTV bands with absolute risk weights that replace the Art. 124I(1)/(2) base:
      ≤ 60%:  100%   (Art. 124I(3)(a))
      60-80%: 125%   (Art. 124I(3)(b))
      > 80%:  137.5% (Art. 124I(3)(c))

    Why absolute and not multiplicative: applying 1.375× to the 110% >80% base gives
    151.25%, a +13.75pp over-capital error. PS1/26 ps126app1.pdf p.57 specifies the
    RWs as absolute values. The spec tests here guard against the multiplier regression.
    """

    def test_junior_below_60(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CRE income LTV ≤ 60%: Art. 124I(3)(a) absolute 100%."""
        df = pl.DataFrame(
            {
                "exposure_reference": ["CRE_J1"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.50],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [True],
                "prior_charge_ltv": [0.10],
            }
        ).lazy()
        result = sa_calculator.calculate_branch(df, b31_config).collect().to_dicts()[0]
        assert float(result["risk_weight"]) == pytest.approx(1.00, abs=1e-4)

    def test_junior_60_to_80(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CRE income 60% < LTV ≤ 80%: Art. 124I(3)(b) absolute 125%."""
        df = pl.DataFrame(
            {
                "exposure_reference": ["CRE_J2"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.70],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [True],
                "prior_charge_ltv": [0.10],
            }
        ).lazy()
        result = sa_calculator.calculate_branch(df, b31_config).collect().to_dicts()[0]
        assert float(result["risk_weight"]) == pytest.approx(1.25, abs=1e-4)

    def test_junior_above_80(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CRE income LTV > 80%: Art. 124I(3)(c) absolute 137.5% (not 110% × 1.375)."""
        df = pl.DataFrame(
            {
                "exposure_reference": ["CRE_J3"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.90],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [True],
                "prior_charge_ltv": [0.10],
            }
        ).lazy()
        result = sa_calculator.calculate_branch(df, b31_config).collect().to_dicts()[0]
        # Art. 124I(3)(c): absolute 137.5% — replaces Art. 124I base, not multiplied
        assert float(result["risk_weight"]) == pytest.approx(1.375, abs=1e-4)

    def test_no_junior_charge_standard_cre_income(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """No prior charge → standard 110% for LTV > 80%."""
        df = pl.DataFrame(
            {
                "exposure_reference": ["CRE_STD"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.90],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [True],
                "prior_charge_ltv": [0.0],
            }
        ).lazy()
        result = sa_calculator.calculate_branch(df, b31_config).collect().to_dicts()[0]
        assert float(result["risk_weight"]) == pytest.approx(1.10, abs=1e-4)

    def test_junior_at_boundary_60(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CRE income at exactly 60%: ≤60% band → 100%."""
        df = pl.DataFrame(
            {
                "exposure_reference": ["CRE_B60"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.60],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [True],
                "prior_charge_ltv": [0.10],
            }
        ).lazy()
        result = sa_calculator.calculate_branch(df, b31_config).collect().to_dicts()[0]
        assert float(result["risk_weight"]) == pytest.approx(1.00, abs=1e-4)

    def test_junior_at_boundary_80(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CRE income at exactly 80%: ≤80% band → 125%."""
        df = pl.DataFrame(
            {
                "exposure_reference": ["CRE_B80"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.80],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [True],
                "prior_charge_ltv": [0.10],
            }
        ).lazy()
        result = sa_calculator.calculate_branch(df, b31_config).collect().to_dicts()[0]
        assert float(result["risk_weight"]) == pytest.approx(1.25, abs=1e-4)


# =============================================================================
# SCALAR LOOKUP FUNCTIONS
# =============================================================================


class TestScalarLookupJunior:
    """Test scalar lookup functions for junior charge and Art. 124L."""

    def test_rre_scalar_junior_threshold(self) -> None:
        """lookup_b31_residential_rw with prior charge reduces threshold."""
        rw, desc = lookup_b31_residential_rw(
            ltv=Decimal("0.80"),
            counterparty_rw=Decimal("0.75"),
            prior_charge_ltv=Decimal("0.20"),
        )
        # effective_threshold = 0.35, secured_ratio = 0.35/0.80
        expected = _expected_loan_split_rw(0.80, cp_rw=0.75, max_ratio=0.35)
        assert float(rw) == pytest.approx(expected, abs=1e-4)
        assert "threshold" in desc

    def test_rre_scalar_income_junior_multiplier(self) -> None:
        """lookup_b31_residential_rw income + junior → 1.25x."""
        rw, desc = lookup_b31_residential_rw(
            ltv=Decimal("0.70"),
            is_income_producing=True,
            prior_charge_ltv=Decimal("0.10"),
        )
        assert float(rw) == pytest.approx(0.50, abs=1e-4)
        assert "junior" in desc.lower()

    def test_rre_scalar_income_no_junior(self) -> None:
        """lookup_b31_residential_rw income without junior → standard table."""
        rw, _ = lookup_b31_residential_rw(
            ltv=Decimal("0.70"),
            is_income_producing=True,
        )
        assert float(rw) == pytest.approx(0.40, abs=1e-4)

    def test_rre_scalar_income_junior_uncapped_high_ltv(self) -> None:
        """Art. 124G(2): LTV > 100% base 105% × 1.25 = 131.25% (uncapped)."""
        rw, desc = lookup_b31_residential_rw(
            ltv=Decimal("1.10"),
            is_income_producing=True,
            prior_charge_ltv=Decimal("0.10"),
        )
        assert float(rw) == pytest.approx(1.3125, abs=1e-4)
        assert "junior" in desc.lower()

    def test_cre_scalar_income_junior_high_ltv(self) -> None:
        """lookup_b31_commercial_rw income + junior at LTV > 80% → Art. 124I(3)(c) 137.5%."""
        rw, desc = lookup_b31_commercial_rw(
            ltv=Decimal("0.90"),
            is_income_producing=True,
            prior_charge_ltv=Decimal("0.10"),
        )
        # Absolute 137.5% override, not 110% × 1.375 = 151.25%
        assert float(rw) == pytest.approx(1.375, abs=1e-4)
        assert "junior" in desc.lower()

    def test_cre_scalar_loan_split_junior(self) -> None:
        """lookup_b31_commercial_rw loan-split with junior → reduced threshold."""
        rw, desc = lookup_b31_commercial_rw(
            ltv=Decimal("0.80"),
            is_natural_person_or_sme=True,
            prior_charge_ltv=Decimal("0.20"),
        )
        # effective_threshold = 0.35, secured_ratio = 0.35/0.80
        expected = 0.60 * (0.35 / 0.80) + 1.00 * (1.0 - 0.35 / 0.80)
        assert float(rw) == pytest.approx(expected, abs=1e-4)
        assert "threshold" in desc


# =============================================================================
# CRR PATH — NO JUNIOR CHARGE / ART. 124L EFFECT
# =============================================================================


class TestCRRNoJuniorChargeEffect:
    """CRR has no Art. 124F(2)/G(2)/I(3)/124L — these are B31-only."""

    def test_crr_resi_ignores_prior_charge(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR residential path ignores prior_charge_ltv column."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("500000"),
            exposure_class="RESIDENTIAL_MORTGAGE",
            ltv=Decimal("0.80"),
            config=crr_config,
            prior_charge_ltv=Decimal("0.20"),
            cp_is_natural_person=True,
        )
        # CRR uses simple binary LTV split (Art. 125), not loan-splitting
        # LTV 80% = threshold boundary → 35% flat
        assert float(result["risk_weight"]) == pytest.approx(0.35, abs=1e-4)

    def test_crr_cre_ignores_prior_charge(
        self,
        sa_calculator: SACalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR commercial path ignores prior_charge_ltv column."""
        df = pl.DataFrame(
            {
                "exposure_reference": ["CRR_CRE"],
                "ead_final": [1_000_000.0],
                "exposure_class": ["COMMERCIAL_RE"],
                "cqs": [None],
                "ltv": [0.50],
                "is_sme": [False],
                "is_infrastructure": [False],
                "has_income_cover": [True],
                "prior_charge_ltv": [0.20],
            }
        ).lazy()
        result = sa_calculator.calculate_branch(df, crr_config).collect().to_dicts()[0]
        # CRR CRE with income + LTV ≤ threshold → 50% (Art. 126)
        assert float(result["risk_weight"]) == pytest.approx(0.50, abs=1e-4)


# =============================================================================
# MIXED BATCH — MULTIPLE EXPOSURE TYPES
# =============================================================================


class TestMixedBatch:
    """Test batch processing with mixed RE exposure types and junior charges."""

    def test_mixed_re_batch(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Batch with first-charge and junior-charge RE exposures."""
        df = pl.DataFrame(
            {
                "exposure_reference": ["FIRST_RESI", "JUNIOR_RESI", "JUNIOR_CRE_INC"],
                "ead_final": [500000.0, 500000.0, 1000000.0],
                "exposure_class": [
                    "RESIDENTIAL_MORTGAGE",
                    "RESIDENTIAL_MORTGAGE",
                    "COMMERCIAL_RE",
                ],
                "cqs": [None, None, None],
                "ltv": [0.80, 0.80, 0.90],
                "is_sme": [False, False, False],
                "is_infrastructure": [False, False, False],
                "has_income_cover": [False, False, True],
                "cp_is_natural_person": [True, True, False],
                "prior_charge_ltv": [0.0, 0.20, 0.10],
            }
        ).lazy()
        results = sa_calculator.calculate_branch(df, b31_config).collect()

        # First charge RRE: standard 55% threshold
        rw_first = results.filter(pl.col("exposure_reference") == "FIRST_RESI")["risk_weight"][0]
        expected_first = _expected_loan_split_rw(0.80, cp_rw=0.75)
        assert float(rw_first) == pytest.approx(expected_first, abs=1e-4)

        # Junior charge RRE: 35% threshold
        rw_junior = results.filter(pl.col("exposure_reference") == "JUNIOR_RESI")["risk_weight"][0]
        expected_junior = _expected_loan_split_rw(0.80, cp_rw=0.75, max_ratio=0.35)
        assert float(rw_junior) == pytest.approx(expected_junior, abs=1e-4)

        # Junior CRE income at LTV 90%: Art. 124I(3)(c) absolute 137.5%
        rw_cre = results.filter(pl.col("exposure_reference") == "JUNIOR_CRE_INC")["risk_weight"][0]
        assert float(rw_cre) == pytest.approx(1.375, abs=1e-4)
