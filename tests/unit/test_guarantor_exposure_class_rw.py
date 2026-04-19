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
import rwa_calc.engine.sa.namespace  # noqa: F401 - Register namespace
from rwa_calc.contracts.config import CalculationConfig


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR configuration (GBP base currency)."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


def _sa_guarantee_result(
    guarantor_entity_type: str,
    guarantor_cqs: int | None,
    config: CalculationConfig,
    *,
    guarantor_country_code: str | None = None,
    guarantor_is_ccp_client_cleared: bool | None = None,
    currency: str = "GBP",
    original_currency: str | None = None,
    guarantee_currency: str | None = None,
) -> pl.DataFrame:
    """Run SA guarantee substitution and return the result.

    When ``original_currency`` is provided, both ``currency`` (reporting) and
    ``original_currency`` (pre-FX-conversion denomination) columns are added,
    simulating the post-FX-conversion pipeline state. When ``guarantee_currency``
    is provided, it is added to the exposure row (populated by the CRM split).
    """
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
    if original_currency is not None:
        data["original_currency"] = [original_currency]
    if guarantor_country_code is not None:
        data["guarantor_country_code"] = [guarantor_country_code]
    if guarantor_is_ccp_client_cleared is not None:
        data["guarantor_is_ccp_client_cleared"] = [guarantor_is_ccp_client_cleared]
    if guarantee_currency is not None:
        data["guarantee_currency"] = [guarantee_currency]

    lf = pl.LazyFrame(data)
    # Call the namespace API directly for isolated testing
    result_lf = lf.sa.apply_guarantee_substitution(config)
    result: pl.DataFrame = result_lf.collect()
    return result


def _irb_guarantee_result(
    guarantor_entity_type: str,
    guarantor_cqs: int | None,
    config: CalculationConfig,
    *,
    guarantor_country_code: str | None = None,
    guarantor_is_ccp_client_cleared: bool | None = None,
    currency: str = "GBP",
    original_currency: str | None = None,
    guarantee_currency: str | None = None,
) -> pl.DataFrame:
    """Run IRB guarantee substitution and return the result.

    When ``original_currency`` is provided, both ``currency`` (reporting) and
    ``original_currency`` (pre-FX-conversion denomination) columns are added,
    simulating the post-FX-conversion pipeline state. When ``guarantee_currency``
    is provided, it is added to the exposure row (populated by the CRM split).
    """
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
    if original_currency is not None:
        data["original_currency"] = [original_currency]
    if guarantor_country_code is not None:
        data["guarantor_country_code"] = [guarantor_country_code]
    if guarantor_is_ccp_client_cleared is not None:
        data["guarantor_is_ccp_client_cleared"] = [guarantor_is_ccp_client_cleared]
    if guarantee_currency is not None:
        data["guarantee_currency"] = [guarantee_currency]

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

    def test_bank_cqs2_crr(self, crr_config: CalculationConfig) -> None:
        """bank entity type → INSTITUTION class → 50% RW for CQS 2 (CRR Art. 120 Table 3)."""
        result = _sa_guarantee_result("bank", 2, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.50)

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

    def test_eu_non_euro_sovereign_domestic_zero_rw(self, crr_config: CalculationConfig) -> None:
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


class TestSAEUDomesticSovereignPostFX:
    """Art. 114(4) 0% RW must hold after FX conversion.

    The ``FXConverter`` overwrites ``currency`` with the reporting currency and
    stores the pre-conversion denomination in ``original_currency``. The
    domestic-currency check must honour the denomination, not the reporting
    currency — otherwise every non-base-currency EU sovereign guarantee would
    fall through to the CQS ladder and (for unrated sovereigns) land on 100%.
    """

    def test_de_sovereign_eur_exposure_post_fx_to_gbp_zero_rw(
        self, crr_config: CalculationConfig
    ) -> None:
        """DE sovereign guarantor, EUR exposure converted to GBP reporting → 0%."""
        result = _sa_guarantee_result(
            "sovereign",
            None,  # unrated: without the fix this falls to `.otherwise(1.0)`
            crr_config,
            guarantor_country_code="DE",
            currency="GBP",  # reporting currency after FX conversion
            original_currency="EUR",  # pre-conversion denomination
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_pl_sovereign_pln_exposure_post_fx_to_gbp_zero_rw(
        self, crr_config: CalculationConfig
    ) -> None:
        """Polish sovereign guarantor, PLN exposure converted to GBP → 0% (non-euro EU)."""
        result = _sa_guarantee_result(
            "sovereign",
            None,
            crr_config,
            guarantor_country_code="PL",
            currency="GBP",
            original_currency="PLN",
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_de_sovereign_usd_exposure_post_fx_does_not_get_zero(
        self, crr_config: CalculationConfig
    ) -> None:
        """DE sovereign guarantor but USD exposure (non-domestic) → Art. 114(4) does NOT apply."""
        result = _sa_guarantee_result(
            "sovereign",
            None,  # unrated
            crr_config,
            guarantor_country_code="DE",
            currency="GBP",
            original_currency="USD",  # USD, not EUR → foreign currency
        )
        # Unrated CGCB foreign-currency → 100% per CQS ladder otherwise branch
        assert result["guarantor_rw"][0] == pytest.approx(1.0)


class TestIRBEUDomesticSovereignPostFX:
    """IRB path: same Art. 114(4) preservation across FX conversion."""

    def test_de_sovereign_eur_exposure_post_fx_to_gbp_zero_rw(
        self, crr_config: CalculationConfig
    ) -> None:
        """IRB: DE sovereign guarantor, EUR exposure post-FX → 0% SA RW substitution."""
        result = _irb_guarantee_result(
            "sovereign",
            None,
            crr_config,
            guarantor_country_code="DE",
            currency="GBP",
            original_currency="EUR",
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_se_sovereign_sek_exposure_post_fx_to_gbp_zero_rw(
        self, crr_config: CalculationConfig
    ) -> None:
        """IRB: Swedish sovereign, SEK exposure post-FX → 0% SA RW substitution."""
        result = _irb_guarantee_result(
            "sovereign",
            None,
            crr_config,
            guarantor_country_code="SE",
            currency="GBP",
            original_currency="SEK",
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.0)


class TestGuarantorSubstitutionReadsGuaranteeCurrency:
    """Art. 114(4)/(7): the domestic-currency test reads the GUARANTEE currency.

    Under the substitution approach (Art. 215-217) the guaranteed portion is
    treated as an exposure to the sovereign. Whether it qualifies for 0% RW
    under Art. 114(4)/(7) depends on whether the guarantee itself (the
    substituted exposure) is denominated in the sovereign's domestic currency —
    not whether the underlying loan is. The Art. 233(3) 8% FX haircut handles
    any mismatch between guarantee and underlying separately.
    """

    def test_sa_gbp_exposure_eur_guarantee_de_sovereign_zero_rw(
        self, crr_config: CalculationConfig
    ) -> None:
        """SA: GBP exposure + EUR guarantee + DE sovereign -> 0% RW."""
        result = _sa_guarantee_result(
            "sovereign",
            3,
            crr_config,
            guarantor_country_code="DE",
            currency="GBP",
            guarantee_currency="EUR",
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_sa_eur_exposure_gbp_guarantee_uk_sovereign_zero_rw(
        self, crr_config: CalculationConfig
    ) -> None:
        """SA: EUR exposure + GBP guarantee + UK sovereign -> 0% RW (mirror case)."""
        result = _sa_guarantee_result(
            "sovereign",
            3,
            crr_config,
            guarantor_country_code="GB",
            currency="EUR",
            guarantee_currency="GBP",
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_sa_eur_exposure_gbp_guarantee_de_sovereign_non_zero_rw(
        self, crr_config: CalculationConfig
    ) -> None:
        """SA: EUR exposure + GBP guarantee + DE sovereign -> NOT 0% RW.

        Guards against regressing to the old behaviour of reading exposure currency:
        the exposure happens to be in DE's domestic (EUR), but the guarantee is
        in GBP, so the substituted exposure to the sovereign is not domestic.
        """
        result = _sa_guarantee_result(
            "sovereign",
            3,
            crr_config,
            guarantor_country_code="DE",
            currency="EUR",
            guarantee_currency="GBP",
        )
        # CQS 3 CGCB = 50% RW (standard, not the 0% short-circuit)
        assert result["guarantor_rw"][0] == pytest.approx(0.50)

    def test_irb_gbp_exposure_eur_guarantee_de_sovereign_zero_rw(
        self, crr_config: CalculationConfig
    ) -> None:
        """IRB: GBP exposure + EUR guarantee + DE sovereign -> 0% guarantor_rw."""
        result = _irb_guarantee_result(
            "sovereign",
            3,
            crr_config,
            guarantor_country_code="DE",
            currency="GBP",
            guarantee_currency="EUR",
        )
        assert result["guarantor_rw"][0] == pytest.approx(0.0)

    def test_irb_eur_exposure_gbp_guarantee_de_sovereign_non_zero(
        self, crr_config: CalculationConfig
    ) -> None:
        """IRB: EUR exposure + GBP guarantee + DE sovereign -> NOT 0% guarantor_rw."""
        result = _irb_guarantee_result(
            "sovereign",
            3,
            crr_config,
            guarantor_country_code="DE",
            currency="EUR",
            guarantee_currency="GBP",
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
        result = _sa_guarantee_result("ccp", None, crr_config, guarantor_is_ccp_client_cleared=True)
        assert result["guarantor_rw"][0] == pytest.approx(0.04)

    def test_ccp_null_client_cleared_defaults_to_proprietary(
        self, crr_config: CalculationConfig
    ) -> None:
        """CCP guarantor with null is_ccp_client_cleared defaults to 2% (proprietary)."""
        result = _sa_guarantee_result("ccp", None, crr_config)
        assert result["guarantor_rw"][0] == pytest.approx(0.02)

    def test_ccp_with_cqs_still_uses_ccp_rw(self, crr_config: CalculationConfig) -> None:
        """CCP branch overrides CQS-based institution RW even if CQS exists."""
        result = _sa_guarantee_result("ccp", 1, crr_config, guarantor_is_ccp_client_cleared=False)
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
