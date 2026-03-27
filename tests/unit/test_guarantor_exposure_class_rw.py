"""
Unit tests for guarantor risk weight lookup using guarantor_exposure_class.

Verifies that all valid entity types (sovereign, central_bank, bank, company,
institution, corporate, mdb) correctly map to the right SA exposure class and
produce correct guarantor risk weights. Also tests UK domestic sovereign
treatment under Art. 114(3).

References:
- CRR Art. 114: CGCB risk weights
- CRR Art. 114(3): 0% RW for domestic sovereign in domestic currency
- CRR Art. 120-121: Institution risk weights
- CRR Art. 122: Corporate risk weights
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

import rwa_calc.engine.irb.namespace  # noqa: F401 - Register namespace
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa.calculator import SACalculator


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR configuration (GBP base currency)."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


def _make_sa_calculator() -> SACalculator:
    """Create a minimal SA calculator for testing guarantee substitution."""
    return SACalculator()


def _sa_guarantee_result(
    guarantor_entity_type: str,
    guarantor_cqs: int | None,
    config: CalculationConfig,
    *,
    guarantor_country_code: str | None = None,
    guarantor_is_ccp_client_cleared: bool | None = None,
    currency: str = "GBP",
) -> pl.DataFrame:
    """Run SA guarantee substitution and return the result."""
    data: dict[str, list] = {
        "exposure_reference": ["EXP001"],
        "ead": [1_000_000.0],
        "risk_weight": [1.0],
        "guaranteed_portion": [1_000_000.0],
        "unguaranteed_portion": [0.0],
        "guarantor_entity_type": [guarantor_entity_type],
        "guarantor_cqs": [guarantor_cqs],
        "currency": [currency],
    }
    if guarantor_country_code is not None:
        data["guarantor_country_code"] = [guarantor_country_code]
    if guarantor_is_ccp_client_cleared is not None:
        data["guarantor_is_ccp_client_cleared"] = [guarantor_is_ccp_client_cleared]

    lf = pl.LazyFrame(data)
    calc = _make_sa_calculator()
    # Call the private method directly for isolated testing
    result_lf = calc._apply_guarantee_substitution(lf, config)
    return result_lf.collect()


def _irb_guarantee_result(
    guarantor_entity_type: str,
    guarantor_cqs: int | None,
    config: CalculationConfig,
    *,
    guarantor_country_code: str | None = None,
    guarantor_is_ccp_client_cleared: bool | None = None,
    currency: str = "GBP",
) -> pl.DataFrame:
    """Run IRB guarantee substitution and return the result."""
    data: dict[str, list] = {
        "exposure_reference": ["EXP001"],
        "pd": [0.01],
        "lgd": [0.45],
        "ead_final": [1_000_000.0],
        "maturity": [2.5],
        "exposure_class": ["CORPORATE"],
        "rwa": [500_000.0],
        "risk_weight": [0.50],
        "guaranteed_portion": [1_000_000.0],
        "unguaranteed_portion": [0.0],
        "guarantor_entity_type": [guarantor_entity_type],
        "guarantor_cqs": [guarantor_cqs],
        "currency": [currency],
    }
    if guarantor_country_code is not None:
        data["guarantor_country_code"] = [guarantor_country_code]
    if guarantor_is_ccp_client_cleared is not None:
        data["guarantor_is_ccp_client_cleared"] = [guarantor_is_ccp_client_cleared]

    lf = pl.LazyFrame(data)
    return lf.irb.apply_guarantee_substitution(config).collect()


class TestSAGuarantorExposureClassMapping:
    """SA calculator correctly maps entity types to exposure classes for guarantor RW."""

    def test_sovereign_cqs1_zero_rw(self, crr_config: CalculationConfig) -> None:
        """Sovereign entity type → CGCB class → 0% RW for CQS 1."""
        result = _sa_guarantee_result("sovereign", 1, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_central_bank_cqs1_zero_rw(self, crr_config: CalculationConfig) -> None:
        """central_bank entity type → CGCB class → 0% RW for CQS 1."""
        result = _sa_guarantee_result("central_bank", 1, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_central_bank_cqs3(self, crr_config: CalculationConfig) -> None:
        """central_bank entity type → CGCB class → 50% RW for CQS 3."""
        result = _sa_guarantee_result("central_bank", 3, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.50)

    def test_institution_cqs1(self, crr_config: CalculationConfig) -> None:
        """institution entity type → INSTITUTION class → 20% RW for CQS 1."""
        result = _sa_guarantee_result("institution", 1, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.20)

    def test_bank_cqs1(self, crr_config: CalculationConfig) -> None:
        """bank entity type → INSTITUTION class → 20% RW for CQS 1."""
        result = _sa_guarantee_result("bank", 1, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.20)

    def test_bank_cqs2_uk_deviation(self, crr_config: CalculationConfig) -> None:
        """bank entity type → INSTITUTION class → 30% RW for CQS 2 (UK deviation)."""
        result = _sa_guarantee_result("bank", 2, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.30)

    def test_corporate_cqs1(self, crr_config: CalculationConfig) -> None:
        """corporate entity type → CORPORATE class → 20% RW for CQS 1."""
        result = _sa_guarantee_result("corporate", 1, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.20)

    def test_company_cqs1(self, crr_config: CalculationConfig) -> None:
        """company entity type → CORPORATE class → 20% RW for CQS 1."""
        result = _sa_guarantee_result("company", 1, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.20)

    def test_company_cqs2(self, crr_config: CalculationConfig) -> None:
        """company entity type → CORPORATE class → 50% RW for CQS 2."""
        result = _sa_guarantee_result("company", 2, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.50)

    def test_mdb_cqs1(self, crr_config: CalculationConfig) -> None:
        """mdb entity type → MDB class → 20% RW for CQS 1."""
        result = _sa_guarantee_result("mdb", 1, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.20)


class TestSADomesticSovereignTreatment:
    """Art. 114(3): UK sovereign guarantor in GBP → 0% RW regardless of CQS."""

    def test_uk_sovereign_cqs3_gbp_zero_rw(self, crr_config: CalculationConfig) -> None:
        """UK sovereign guarantor (CQS 3) in GBP should get 0% RW under Art. 114(3)."""
        result = _sa_guarantee_result(
            "sovereign", 3, crr_config, guarantor_country_code="GB", currency="GBP"
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_uk_central_bank_cqs3_gbp_zero_rw(self, crr_config: CalculationConfig) -> None:
        """UK central bank guarantor (CQS 3) in GBP should get 0% RW under Art. 114(3)."""
        result = _sa_guarantee_result(
            "central_bank", 3, crr_config, guarantor_country_code="GB", currency="GBP"
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_non_uk_sovereign_cqs3_standard_rw(self, crr_config: CalculationConfig) -> None:
        """Non-UK sovereign (CQS 3) should get standard 50% RW."""
        result = _sa_guarantee_result(
            "sovereign", 3, crr_config, guarantor_country_code="US", currency="GBP"
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.50)

    def test_uk_sovereign_non_gbp_standard_rw(self, crr_config: CalculationConfig) -> None:
        """UK sovereign in non-GBP currency should get standard CQS-based RW."""
        result = _sa_guarantee_result(
            "sovereign", 3, crr_config, guarantor_country_code="GB", currency="USD"
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.50)


class TestIRBGuarantorExposureClassMapping:
    """IRB namespace correctly maps entity types to exposure classes for guarantor RW."""

    def test_sovereign_cqs1_zero_rw(self, crr_config: CalculationConfig) -> None:
        """Sovereign entity type → CGCB class → 0% SA RW for CQS 1."""
        result = _irb_guarantee_result("sovereign", 1, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_central_bank_cqs1_zero_rw(self, crr_config: CalculationConfig) -> None:
        """central_bank entity type → CGCB class → 0% SA RW for CQS 1."""
        result = _irb_guarantee_result("central_bank", 1, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_bank_cqs1(self, crr_config: CalculationConfig) -> None:
        """bank entity type → INSTITUTION class → 20% SA RW for CQS 1."""
        result = _irb_guarantee_result("bank", 1, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.20)

    def test_company_cqs1(self, crr_config: CalculationConfig) -> None:
        """company entity type → CORPORATE class → 20% SA RW for CQS 1."""
        result = _irb_guarantee_result("company", 1, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.20)


class TestIRBDomesticSovereignTreatment:
    """Art. 114(3): UK sovereign guarantor in GBP → 0% RW in IRB namespace."""

    def test_uk_sovereign_cqs3_gbp_zero_rw(self, crr_config: CalculationConfig) -> None:
        """UK sovereign guarantor (CQS 3) in GBP should get 0% SA RW under Art. 114(3)."""
        result = _irb_guarantee_result(
            "sovereign", 3, crr_config, guarantor_country_code="GB", currency="GBP"
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_non_uk_sovereign_cqs3_standard_rw(self, crr_config: CalculationConfig) -> None:
        """Non-UK sovereign (CQS 3) should get standard 50% SA RW."""
        result = _irb_guarantee_result(
            "sovereign", 3, crr_config, guarantor_country_code="US", currency="GBP"
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.50)


class TestSAEUDomesticSovereignTreatment:
    """Art. 114(4): EU sovereign guarantor in domestic currency → 0% RW regardless of CQS."""

    def test_eu_sovereign_eur_cqs3_zero_rw(self, crr_config: CalculationConfig) -> None:
        """German sovereign guarantor (CQS 3) in EUR → 0% RW under Art. 114(4)."""
        result = _sa_guarantee_result(
            "sovereign", 3, crr_config, guarantor_country_code="DE", currency="EUR"
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_eu_central_bank_eur_cqs3_zero_rw(self, crr_config: CalculationConfig) -> None:
        """French central bank guarantor (CQS 3) in EUR → 0% RW under Art. 114(4)."""
        result = _sa_guarantee_result(
            "central_bank", 3, crr_config, guarantor_country_code="FR", currency="EUR"
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_eu_non_euro_sovereign_domestic_currency_zero_rw(
        self, crr_config: CalculationConfig
    ) -> None:
        """Polish sovereign guarantor (CQS 3) in PLN → 0% RW (non-euro EU domestic)."""
        result = _sa_guarantee_result(
            "sovereign", 3, crr_config, guarantor_country_code="PL", currency="PLN"
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_eu_sovereign_usd_standard_rw(self, crr_config: CalculationConfig) -> None:
        """EU sovereign guarantor in USD → standard CQS-based RW (foreign currency)."""
        result = _sa_guarantee_result(
            "sovereign", 3, crr_config, guarantor_country_code="DE", currency="USD"
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.50)

    def test_non_eu_sovereign_eur_standard_rw(self, crr_config: CalculationConfig) -> None:
        """Non-EU sovereign (US) in EUR → standard CQS-based RW."""
        result = _sa_guarantee_result(
            "sovereign", 3, crr_config, guarantor_country_code="US", currency="EUR"
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.50)


class TestIRBEUDomesticSovereignTreatment:
    """Art. 114(4): EU sovereign guarantor in domestic currency → 0% RW in IRB namespace."""

    def test_eu_sovereign_eur_cqs3_zero_rw(self, crr_config: CalculationConfig) -> None:
        """German sovereign guarantor (CQS 3) in EUR → 0% SA RW under Art. 114(4)."""
        result = _irb_guarantee_result(
            "sovereign", 3, crr_config, guarantor_country_code="DE", currency="EUR"
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_eu_non_euro_sovereign_domestic_zero_rw(
        self, crr_config: CalculationConfig
    ) -> None:
        """Swedish sovereign (CQS 3) in SEK → 0% SA RW under Art. 114(4)."""
        result = _irb_guarantee_result(
            "sovereign", 3, crr_config, guarantor_country_code="SE", currency="SEK"
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_eu_sovereign_usd_standard_rw(self, crr_config: CalculationConfig) -> None:
        """EU sovereign in USD → standard 50% SA RW (foreign currency)."""
        result = _irb_guarantee_result(
            "sovereign", 3, crr_config, guarantor_country_code="DE", currency="USD"
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.50)


class TestSACCPGuarantorRiskWeight:
    """CCP guarantor gets prescribed 2%/4% RW per CRR Art. 306 / CRE54.14-15."""

    def test_ccp_proprietary_2pct(self, crr_config: CalculationConfig) -> None:
        """CCP guarantor (proprietary) should get 2% RW."""
        result = _sa_guarantee_result(
            "ccp", None, crr_config, guarantor_is_ccp_client_cleared=False
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.02)

    def test_ccp_client_cleared_4pct(self, crr_config: CalculationConfig) -> None:
        """CCP guarantor (client-cleared) should get 4% RW."""
        result = _sa_guarantee_result(
            "ccp", None, crr_config, guarantor_is_ccp_client_cleared=True
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.04)

    def test_ccp_null_client_cleared_defaults_to_proprietary(
        self, crr_config: CalculationConfig
    ) -> None:
        """CCP guarantor with null is_ccp_client_cleared defaults to 2% (proprietary)."""
        result = _sa_guarantee_result("ccp", None, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.02)

    def test_ccp_with_cqs_still_uses_ccp_rw(self, crr_config: CalculationConfig) -> None:
        """CCP branch overrides CQS-based institution RW even if CQS exists."""
        result = _sa_guarantee_result(
            "ccp", 1, crr_config, guarantor_is_ccp_client_cleared=False
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.02)


class TestIRBCCPGuarantorRiskWeight:
    """IRB: CCP guarantor SA RW should be 2%/4% per CRR Art. 306 / CRE54.14-15."""

    def test_ccp_proprietary_2pct(self, crr_config: CalculationConfig) -> None:
        """CCP guarantor (proprietary) should get 2% SA RW in IRB path."""
        result = _irb_guarantee_result(
            "ccp", None, crr_config, guarantor_is_ccp_client_cleared=False
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.02)

    def test_ccp_client_cleared_4pct(self, crr_config: CalculationConfig) -> None:
        """CCP guarantor (client-cleared) should get 4% SA RW in IRB path."""
        result = _irb_guarantee_result(
            "ccp", None, crr_config, guarantor_is_ccp_client_cleared=True
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.04)

    def test_ccp_null_defaults_to_proprietary(self, crr_config: CalculationConfig) -> None:
        """CCP guarantor with null is_ccp_client_cleared defaults to 2% in IRB path."""
        result = _irb_guarantee_result("ccp", None, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.02)
