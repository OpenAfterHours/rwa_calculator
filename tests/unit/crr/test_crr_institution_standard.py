"""
Tests for institution risk weights -- CRR vs Basel 3.1 ECRA split.

Verifies P1.149: CRR Art. 120 Table 3 always uses 50% (CQS 2) and 100%
(unrated) regardless of base currency. The 30%/40% values previously labelled
as a "UK deviation" are actually the PRA PS1/26 Basel 3.1 ECRA values and only
apply when the framework is Basel 3.1.

References:
- CRR Art. 120(2), Table 3 (CQS 2 = 50%, unrated = 100%)
- PRA PS1/26 Art. 120 ECRA Table 3 (CQS 2 = 30%, unrated = 40%)
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.crr_risk_weights import (
    INSTITUTION_RISK_WEIGHTS_B31_ECRA,
    INSTITUTION_RISK_WEIGHTS_CRR,
    INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR,
    INSTITUTION_SHORT_TERM_UNRATED_RW_CRR,
    _create_institution_df,
    lookup_risk_weight,
)
from rwa_calc.domain.enums import CQS
from rwa_calc.engine.sa.calculator import SACalculator

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sa_calculator() -> SACalculator:
    """Return an SA Calculator instance."""
    return SACalculator()


@pytest.fixture
def crr_config_eur() -> CalculationConfig:
    """CRR config with EUR base currency."""
    crr = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    return replace(crr, base_currency="EUR")


@pytest.fixture
def crr_config_gbp() -> CalculationConfig:
    """CRR config with GBP base currency (still CRR Table 3, not B31 ECRA)."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Basel 3.1 (PRA PS1/26) config — uses ECRA Table 3."""
    return CalculationConfig.basel_3_1(reporting_date=date(2024, 12, 31))


# =============================================================================
# Data table constant tests
# =============================================================================


class TestInstitutionRiskWeightsCRR:
    """Tests for CRR Art. 120 Table 3 vs PRA PS1/26 ECRA Table 3."""

    def test_crr_unrated_hundred_percent(self) -> None:
        """CRR Art. 120(2): unrated institution = 100% RW."""
        assert INSTITUTION_RISK_WEIGHTS_CRR[CQS.UNRATED] == Decimal("1.00")

    def test_b31_ecra_unrated_forty_percent(self) -> None:
        """PRA PS1/26 ECRA: unrated institution = 40% RW (sovereign-derived)."""
        assert INSTITUTION_RISK_WEIGHTS_B31_ECRA[CQS.UNRATED] == Decimal("0.40")

    def test_crr_vs_b31_unrated_differ(self) -> None:
        """CRR (100%) and B31 ECRA (40%) must differ for unrated institutions."""
        assert (
            INSTITUTION_RISK_WEIGHTS_CRR[CQS.UNRATED]
            != INSTITUTION_RISK_WEIGHTS_B31_ECRA[CQS.UNRATED]
        )

    def test_crr_cqs2_fifty_percent(self) -> None:
        """CRR Art. 120 Table 3: CQS 2 institution = 50% RW."""
        assert INSTITUTION_RISK_WEIGHTS_CRR[CQS.CQS2] == Decimal("0.50")

    def test_b31_ecra_cqs2_thirty_percent(self) -> None:
        """PRA PS1/26 ECRA Table 3: CQS 2 institution = 30% RW."""
        assert INSTITUTION_RISK_WEIGHTS_B31_ECRA[CQS.CQS2] == Decimal("0.30")

    def test_other_rated_values_unchanged(self) -> None:
        """Rated institution weights unchanged between CRR and B31 except CQS 2."""
        for cqs in [CQS.CQS1, CQS.CQS3, CQS.CQS4, CQS.CQS5, CQS.CQS6]:
            assert INSTITUTION_RISK_WEIGHTS_CRR[cqs] == INSTITUTION_RISK_WEIGHTS_B31_ECRA[cqs], (
                f"CQS {cqs.value} should be the same in both tables"
            )


# =============================================================================
# DataFrame generator tests
# =============================================================================


class TestInstitutionDataFrame:
    """Tests for _create_institution_df keyed on framework."""

    def test_crr_df_unrated_row(self) -> None:
        """CRR DataFrame unrated row should have 1.00 risk weight."""
        df = _create_institution_df(is_basel_3_1=False)
        unrated = df.filter(df["cqs"].is_null())
        assert unrated.shape[0] == 1
        assert unrated["risk_weight"][0] == pytest.approx(1.00)

    def test_b31_df_unrated_row(self) -> None:
        """B31 DataFrame unrated row should have 0.40 risk weight."""
        df = _create_institution_df(is_basel_3_1=True)
        unrated = df.filter(df["cqs"].is_null())
        assert unrated.shape[0] == 1
        assert unrated["risk_weight"][0] == pytest.approx(0.40)

    def test_crr_vs_b31_df_cqs2(self) -> None:
        """CQS 2 differs: CRR=50%, B31 ECRA=30%."""
        crr_df = _create_institution_df(is_basel_3_1=False)
        b31_df = _create_institution_df(is_basel_3_1=True)
        crr_cqs2 = crr_df.filter(crr_df["cqs"] == 2)["risk_weight"][0]
        b31_cqs2 = b31_df.filter(b31_df["cqs"] == 2)["risk_weight"][0]
        assert crr_cqs2 == pytest.approx(0.50)
        assert b31_cqs2 == pytest.approx(0.30)


# =============================================================================
# Scalar lookup tests
# =============================================================================


class TestLookupInstitution:
    """Tests for lookup_risk_weight keyed on framework."""

    def test_lookup_unrated_crr_hundred_percent(self) -> None:
        """Unrated institution under CRR gets 100%."""
        assert lookup_risk_weight("INSTITUTION", None, is_basel_3_1=False) == Decimal("1.00")

    def test_lookup_unrated_b31_forty_percent(self) -> None:
        """Unrated institution under B31 ECRA gets 40%."""
        assert lookup_risk_weight("INSTITUTION", None, is_basel_3_1=True) == Decimal("0.40")

    def test_lookup_cqs_zero_treated_as_unrated_crr(self) -> None:
        """CQS 0 treated as unrated → 100% under CRR."""
        assert lookup_risk_weight("INSTITUTION", 0, is_basel_3_1=False) == Decimal("1.00")


# =============================================================================
# SA calculator integration tests
# =============================================================================


class TestSACalculatorInstitutionFramework:
    """Tests for SA calculator institution treatment per framework."""

    def test_unrated_institution_crr_eur_hundred_percent(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
    ) -> None:
        """Unrated institution under CRR (EUR base) gets 100% RW (Art. 120(2))."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=None,
            config=crr_config_eur,
        )
        assert result["risk_weight"] == pytest.approx(1.00)
        assert result["rwa"] == pytest.approx(1_000_000)

    def test_unrated_institution_crr_gbp_hundred_percent(
        self,
        sa_calculator: SACalculator,
        crr_config_gbp: CalculationConfig,
    ) -> None:
        """Unrated institution under CRR (GBP base) ALSO gets 100% — base ccy doesn't switch frameworks."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=None,
            config=crr_config_gbp,
        )
        assert result["risk_weight"] == pytest.approx(1.00)
        assert result["rwa"] == pytest.approx(1_000_000)

    def test_rated_institution_cqs2_crr_fifty_percent(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
    ) -> None:
        """CQS 2 institution under CRR gets 50%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=2,
            config=crr_config_eur,
        )
        assert result["risk_weight"] == pytest.approx(0.50)
        assert result["rwa"] == pytest.approx(500_000)

    def test_rated_institution_cqs2_b31_thirty_percent(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """CQS 2 institution under Basel 3.1 ECRA gets 30%."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=2,
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(0.30)
        assert result["rwa"] == pytest.approx(300_000)

    def test_rated_institution_cqs1_same_both_frameworks(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
        b31_config: CalculationConfig,
    ) -> None:
        """CQS 1 institution gets 20% under both CRR and B31."""
        crr = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=1,
            config=crr_config_eur,
        )
        b31 = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=1,
            config=b31_config,
        )
        assert crr["risk_weight"] == pytest.approx(0.20)
        assert b31["risk_weight"] == pytest.approx(0.20)


# =============================================================================
# Guarantor substitution tests
# =============================================================================


class TestGuarantorInstitutionFramework:
    """Tests for guarantor substitution by framework."""

    @staticmethod
    def _make_guaranteed_exposure(currency: str, country_code: str, guarantor_country: str) -> dict:
        """Build a corporate exposure fully guaranteed by an unrated institution."""
        return {
            "exposure_reference": ["EXP_001"],
            "ead_final": [1_000_000.0],
            "exposure_class": ["CORPORATE"],
            "cqs": [None],
            "is_sme": [False],
            "is_infrastructure": [False],
            "is_managed_as_retail": [False],
            "qualifies_as_retail": [True],
            "has_income_cover": [False],
            "seniority": ["senior"],
            "is_defaulted": [False],
            "currency": [currency],
            "cp_country_code": [country_code],
            "cp_entity_type": ["corporate"],
            "cp_is_natural_person": [False],
            "cp_is_social_housing": [False],
            "cp_is_investment_grade": [False],
            "is_payroll_loan": [False],
            "is_short_term_trade_lc": [False],
            "residual_maturity_years": [1.0],
            # Guarantee fields — fully guaranteed
            "guaranteed_portion": [1_000_000.0],
            "unguaranteed_portion": [0.0],
            "guarantor_exposure_class": ["institution"],
            "guarantor_cqs": [None],
            "guarantor_entity_type": ["institution"],
            "guarantor_country_code": [guarantor_country],
            "guarantor_is_ccp_client_cleared": [False],
            "guarantee_fx_haircut": [0.0],
            "guarantee_restructuring_haircut": [0.0],
        }

    def test_guarantor_unrated_institution_crr_hundred_percent(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
    ) -> None:
        """Unrated institution guarantor under CRR → 100% guarantor RW."""
        import polars as pl

        data = self._make_guaranteed_exposure("EUR", "DE", "DE")
        df = pl.DataFrame(data).lazy()
        result = sa_calculator.calculate_branch(df, crr_config_eur).collect()
        row = result.to_dicts()[0]

        assert row["guarantor_rw"] == pytest.approx(1.00)

    def test_guarantor_unrated_institution_b31_forty_percent(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Unrated institution guarantor under B31 ECRA → 40% guarantor RW."""
        import polars as pl

        data = self._make_guaranteed_exposure("GBP", "GB", "GB")
        df = pl.DataFrame(data).lazy()
        result = sa_calculator.calculate_branch(df, b31_config).collect()
        row = result.to_dicts()[0]

        assert row["guarantor_rw"] == pytest.approx(0.40)


# =============================================================================
# CRR short-term institution tests (P1.99 / P1.121)
# =============================================================================


class TestCRRShortTermInstitutionTables:
    """CRR Art. 120(2) Table 4 + Art. 121(3) regulatory values."""

    def test_crr_table_4_differs_from_long_term(self) -> None:
        """CQS 2/3 short-term diverges from Table 3 long-term (P1.99)."""
        assert (
            INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR[CQS.CQS2]
            < INSTITUTION_RISK_WEIGHTS_CRR[CQS.CQS2]
        )
        assert (
            INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR[CQS.CQS3]
            < INSTITUTION_RISK_WEIGHTS_CRR[CQS.CQS3]
        )

    def test_crr_unrated_short_term_is_twenty_percent(self) -> None:
        """CRR Art. 121(3): unrated institution short-term = 20%."""
        assert Decimal("0.20") == INSTITUTION_SHORT_TERM_UNRATED_RW_CRR


class TestCRRShortTermInstitutionSACalculator:
    """End-to-end SA calculator checks for CRR short-term institution RWs."""

    @pytest.mark.parametrize(
        ("cqs", "expected_rw"),
        [
            (1, 0.20),
            (2, 0.20),  # P1.99: was 0.50 long-term
            (3, 0.20),  # P1.99: was 0.50 long-term
            (4, 0.50),
            (5, 0.50),
            (6, 1.50),
        ],
    )
    def test_rated_institution_short_term(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
        cqs: int,
        expected_rw: float,
    ) -> None:
        """Rated institution with residual maturity <= 3m uses Art. 120(2) Table 4."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=cqs,
            residual_maturity_years=0.25,
            original_maturity_years=0.25,
            config=crr_config_eur,
        )
        assert result["risk_weight"] == pytest.approx(expected_rw)

    def test_rated_institution_just_over_three_months_uses_long_term(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
    ) -> None:
        """Rated institution CQS 2 with residual maturity > 3m falls back to Table 3 (50%)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=2,
            residual_maturity_years=0.26,
            original_maturity_years=0.26,
            config=crr_config_eur,
        )
        assert result["risk_weight"] == pytest.approx(0.50)

    def test_unrated_institution_short_term_twenty_percent(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
    ) -> None:
        """Unrated institution with original maturity <= 3m gets 20% per Art. 121(3)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=None,
            residual_maturity_years=0.25,
            original_maturity_years=0.25,
            config=crr_config_eur,
        )
        assert result["risk_weight"] == pytest.approx(0.20)
        assert result["rwa"] == pytest.approx(200_000)

    def test_unrated_institution_keys_on_original_maturity(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
    ) -> None:
        """Seasoned long-dated bond (original > 3m, residual <= 3m) does NOT qualify for Art. 121(3)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=None,
            residual_maturity_years=0.20,
            original_maturity_years=5.0,
            config=crr_config_eur,
        )
        # Falls through to Table 5 fallback (100%)
        assert result["risk_weight"] == pytest.approx(1.00)

    def test_rated_institution_keys_on_residual_maturity(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
    ) -> None:
        """Rated CQS 2 seasoned short-dated residual uses Art. 120(2) Table 4 (20%)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=2,
            residual_maturity_years=0.20,
            original_maturity_years=5.0,
            config=crr_config_eur,
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_unrated_short_term_sovereign_floor_still_applies_in_fx(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
    ) -> None:
        """Art. 121(6) sovereign floor lifts 20% to 150% when sovereign is CQS 6 in FX."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=None,
            residual_maturity_years=0.25,
            original_maturity_years=0.25,
            currency="USD",
            country_code="TR",
            local_currency="TRY",
            sovereign_cqs=6,
            config=crr_config_eur,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_b31_rated_short_term_unaffected_by_crr_change(
        self,
        sa_calculator: SACalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """B31 uses Table 4 with CQS 1-5 all 20% — unaffected by CRR-specific fix."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=4,
            residual_maturity_years=0.25,
            original_maturity_years=0.25,
            config=b31_config,
        )
        # B31 Table 4: CQS 4 short-term = 20% (vs CRR 50%)
        assert result["risk_weight"] == pytest.approx(0.20)
