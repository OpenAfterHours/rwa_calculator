"""
Tests for CRR institution risk weights -- EU standard (non-UK) treatment.

Verifies P1.16: Unrated institutions under the CRR standard treatment
(Art. 120(2) Table 3) should get 100% RW when the sovereign CQS is unknown,
not 40% (which is the UK sovereign-derived value).

The standard treatment applies when use_uk_deviation=False, i.e. when
base_currency != "GBP". This is relevant for non-UK institution counterparties
where the sovereign CQS is not available.

References:
- CRR Art. 120(2), Table 3
- CRR Art. 121(6) (sovereign floor for FX unrated institutions)
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.crr_risk_weights import (
    INSTITUTION_RISK_WEIGHTS_STANDARD,
    INSTITUTION_RISK_WEIGHTS_UK,
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
    """CRR config with EUR base currency (non-UK standard treatment)."""
    crr = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    return replace(crr, base_currency="EUR")


@pytest.fixture
def crr_config_gbp() -> CalculationConfig:
    """CRR config with GBP base currency (UK deviation treatment)."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


# =============================================================================
# Data table constant tests
# =============================================================================


class TestInstitutionRiskWeightsStandard:
    """Tests for INSTITUTION_RISK_WEIGHTS_STANDARD dict (Art. 120(2) Table 3)."""

    def test_standard_unrated_hundred_percent(self) -> None:
        """Art. 120(2): Unrated institution under standard treatment gets 100% RW."""
        assert INSTITUTION_RISK_WEIGHTS_STANDARD[CQS.UNRATED] == Decimal("1.00")

    def test_uk_unrated_forty_percent(self) -> None:
        """UK deviation: Unrated institution gets 40% RW (sovereign-derived)."""
        assert INSTITUTION_RISK_WEIGHTS_UK[CQS.UNRATED] == Decimal("0.40")

    def test_standard_vs_uk_unrated_differ(self) -> None:
        """Standard and UK tables must differ for unrated institutions."""
        assert (
            INSTITUTION_RISK_WEIGHTS_STANDARD[CQS.UNRATED]
            != INSTITUTION_RISK_WEIGHTS_UK[CQS.UNRATED]
        )

    def test_standard_rated_values_unchanged(self) -> None:
        """Rated institution weights unchanged between UK and standard (except CQS 2)."""
        for cqs in [CQS.CQS1, CQS.CQS3, CQS.CQS4, CQS.CQS5, CQS.CQS6]:
            assert INSTITUTION_RISK_WEIGHTS_STANDARD[cqs] == INSTITUTION_RISK_WEIGHTS_UK[cqs], (
                f"CQS {cqs.value} should be same in both tables"
            )


# =============================================================================
# DataFrame generator tests
# =============================================================================


class TestInstitutionDataFrame:
    """Tests for _create_institution_df with standard treatment."""

    def test_standard_df_unrated_row(self) -> None:
        """Standard DataFrame unrated row should have 1.00 risk weight."""
        df = _create_institution_df(use_uk_deviation=False)
        unrated = df.filter(df["cqs"].is_null())
        assert unrated.shape[0] == 1
        assert unrated["risk_weight"][0] == pytest.approx(1.00)

    def test_uk_df_unrated_row(self) -> None:
        """UK DataFrame unrated row should have 0.40 risk weight."""
        df = _create_institution_df(use_uk_deviation=True)
        unrated = df.filter(df["cqs"].is_null())
        assert unrated.shape[0] == 1
        assert unrated["risk_weight"][0] == pytest.approx(0.40)

    def test_standard_vs_uk_df_cqs2(self) -> None:
        """CQS 2 differs: UK=30%, standard=50%."""
        uk_df = _create_institution_df(use_uk_deviation=True)
        std_df = _create_institution_df(use_uk_deviation=False)
        uk_cqs2 = uk_df.filter(uk_df["cqs"] == 2)["risk_weight"][0]
        std_cqs2 = std_df.filter(std_df["cqs"] == 2)["risk_weight"][0]
        assert uk_cqs2 == pytest.approx(0.30)
        assert std_cqs2 == pytest.approx(0.50)


# =============================================================================
# Scalar lookup tests
# =============================================================================


class TestLookupInstitutionStandard:
    """Tests for lookup_risk_weight with standard (non-UK) treatment."""

    def test_lookup_unrated_standard_hundred_percent(self) -> None:
        """Unrated institution with standard treatment gets 100%."""
        assert lookup_risk_weight("INSTITUTION", None, use_uk_deviation=False) == Decimal("1.00")

    def test_lookup_unrated_uk_forty_percent(self) -> None:
        """Unrated institution with UK deviation gets 40%."""
        assert lookup_risk_weight("INSTITUTION", None, use_uk_deviation=True) == Decimal("0.40")

    def test_lookup_cqs_zero_treated_as_unrated(self) -> None:
        """CQS 0 treated as unrated → 100% under standard."""
        assert lookup_risk_weight("INSTITUTION", 0, use_uk_deviation=False) == Decimal("1.00")


# =============================================================================
# SA calculator integration tests
# =============================================================================


class TestSACalculatorInstitutionStandard:
    """Tests for SA calculator with non-UK (standard) institution treatment."""

    def test_unrated_institution_eur_hundred_percent(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
    ) -> None:
        """Unrated institution with EUR base currency gets 100% RW (Art. 120(2))."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=None,
            config=crr_config_eur,
        )
        assert result["risk_weight"] == pytest.approx(1.00)
        assert result["rwa"] == pytest.approx(1_000_000)

    def test_unrated_institution_gbp_forty_percent(
        self,
        sa_calculator: SACalculator,
        crr_config_gbp: CalculationConfig,
    ) -> None:
        """Unrated institution with GBP base currency gets 40% RW (UK deviation)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=None,
            config=crr_config_gbp,
        )
        assert result["risk_weight"] == pytest.approx(0.40)
        assert result["rwa"] == pytest.approx(400_000)

    def test_rated_institution_cqs2_eur_fifty_percent(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
    ) -> None:
        """CQS 2 institution with EUR base gets 50% (no UK deviation)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=2,
            config=crr_config_eur,
        )
        assert result["risk_weight"] == pytest.approx(0.50)
        assert result["rwa"] == pytest.approx(500_000)

    def test_rated_institution_cqs1_same_both_treatments(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
        crr_config_gbp: CalculationConfig,
    ) -> None:
        """CQS 1 institution gets 20% regardless of UK deviation."""
        eur = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=1,
            config=crr_config_eur,
        )
        gbp = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=1,
            config=crr_config_gbp,
        )
        assert eur["risk_weight"] == pytest.approx(0.20)
        assert gbp["risk_weight"] == pytest.approx(0.20)

    def test_rwa_correctness_unrated_standard(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
    ) -> None:
        """RWA = EAD × 100% for unrated institution under standard treatment."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="INSTITUTION",
            cqs=None,
            config=crr_config_eur,
        )
        assert result["rwa"] == pytest.approx(5_000_000)

    def test_capital_understatement_comparison(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
        crr_config_gbp: CalculationConfig,
    ) -> None:
        """Standard unrated RW (100%) must be higher than UK unrated RW (40%).

        This test documents the core P1.16 fix: non-UK unrated institutions were
        previously getting the same 40% as UK, understating capital by 60pp.
        """
        eur = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=None,
            config=crr_config_eur,
        )
        gbp = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="INSTITUTION",
            cqs=None,
            config=crr_config_gbp,
        )
        assert eur["risk_weight"] > gbp["risk_weight"]
        assert eur["rwa"] > gbp["rwa"]


# =============================================================================
# Guarantor substitution tests
# =============================================================================


class TestGuarantorInstitutionStandard:
    """Tests for guarantor substitution with non-UK institution guarantors."""

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

    def test_guarantor_unrated_institution_eur_hundred_percent(
        self,
        sa_calculator: SACalculator,
        crr_config_eur: CalculationConfig,
    ) -> None:
        """Unrated institution guarantor under EUR base gets 100% guarantor RW."""
        import polars as pl

        data = self._make_guaranteed_exposure("EUR", "DE", "DE")
        df = pl.DataFrame(data).lazy()
        result = sa_calculator.calculate_branch(df, crr_config_eur).collect()
        row = result.to_dicts()[0]

        # Unrated institution guarantor under standard → 100% guarantor RW
        assert row["guarantor_rw"] == pytest.approx(1.00)

    def test_guarantor_unrated_institution_gbp_forty_percent(
        self,
        sa_calculator: SACalculator,
        crr_config_gbp: CalculationConfig,
    ) -> None:
        """Unrated institution guarantor under GBP base gets 40% guarantor RW."""
        import polars as pl

        data = self._make_guaranteed_exposure("GBP", "GB", "GB")
        df = pl.DataFrame(data).lazy()
        result = sa_calculator.calculate_branch(df, crr_config_gbp).collect()
        row = result.to_dicts()[0]

        # Unrated institution guarantor under UK deviation → 40% guarantor RW
        assert row["guarantor_rw"] == pytest.approx(0.40)
