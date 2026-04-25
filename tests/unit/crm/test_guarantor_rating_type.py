"""
Unit tests for guarantor_rating_type audit field in CRM processor.

Verifies that the CRM audit trail includes `guarantor_rating_type` ("internal" or
"external") per the specification (CRR Art. 153(3) / Art. 233A output fields).
The rating type is derived from whether the guarantor has an internal PD
(internal model rating) or only an external CQS.

References:
    docs/specifications/crr/credit-risk-mitigation.md line 348
    docs/user-guide/methodology/crm.md line 366
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CounterpartyLookup,
)
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.crm.guarantees import apply_guarantees
from rwa_calc.engine.crm.processor import CRMProcessor

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def crr_irb_config() -> CalculationConfig:
    """CRR config with full IRB permissions — needed to exercise IRB guarantor routing."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31), permission_mode=PermissionMode.IRB
    )


@pytest.fixture
def b31_irb_config() -> CalculationConfig:
    """Basel 3.1 config with full IRB permissions."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30), permission_mode=PermissionMode.IRB
    )


@pytest.fixture
def crm_processor() -> CRMProcessor:
    return CRMProcessor()


def _base_exposure(
    *,
    approach: str = "SA",
    exposure_class: str = "corporate",
    ead: float = 1_000_000.0,
) -> pl.LazyFrame:
    """Minimal exposure with all columns required by apply_guarantees."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP001"],
            "counterparty_reference": ["CP001"],
            "exposure_class": [exposure_class],
            "approach": [approach],
            "ead_pre_crm": [ead],
            "lgd": [0.45],
            "cqs": [3],
            "product_type": ["LOAN"],
            "drawn_amount": [ead],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "risk_type": [None],
            "interest": [0.0],
            "maturity_date": [date(2029, 12, 31)],
            # Columns normally set by prior CRM steps (CCF, collateral)
            "ead_after_collateral": [ead],
            "ead_from_ccf": [0.0],
            "ccf": [1.0],
            "collateral_adjusted_value": [0.0],
            "lgd_pre_crm": [0.45],
            "lgd_post_crm": [0.45],
        }
    )


def _guarantee(
    *,
    guarantor: str = "GUAR001",
    amount: float = 500_000.0,
    beneficiary: str = "EXP001",
    protection_type: str = "guarantee",
    includes_restructuring: bool = True,
    currency: str = "GBP",
) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "guarantee_reference": ["G001"],
            "guarantee_type": ["unfunded"],
            "guarantor": [guarantor],
            "currency": [currency],
            "maturity_date": [date(2029, 12, 31)],
            "amount_covered": [amount],
            "percentage_covered": [None],
            "beneficiary_type": ["exposure"],
            "beneficiary_reference": [beneficiary],
            "protection_type": [protection_type],
            "includes_restructuring": [includes_restructuring],
        }
    )


def _counterparty_lookup(
    *,
    entity_type: str = "corporate",
) -> pl.LazyFrame:
    """Counterparty lookup for the guarantor."""
    return pl.LazyFrame(
        {
            "counterparty_reference": ["GUAR001"],
            "entity_type": [entity_type],
            "country_code": ["GB"],
        }
    )


def _rating_inheritance(
    *,
    cqs: int | None = 2,
    internal_pd: float | None = None,
    pd: float | None = None,
) -> pl.LazyFrame:
    """Rating inheritance for guarantor."""
    return pl.LazyFrame(
        {
            "counterparty_reference": ["GUAR001"],
            "cqs": [cqs],
            "pd": [pd or internal_pd],
            "internal_pd": [internal_pd],
        }
    )


# ---------------------------------------------------------------------------
# Direct guarantees.apply_guarantees tests
# ---------------------------------------------------------------------------


class TestGuarantorRatingTypeDerivation:
    """Tests that guarantor_rating_type is correctly derived from rating data."""

    def test_internal_rating_produces_internal_type(self, crr_config: CalculationConfig) -> None:
        """Guarantor with internal PD -> rating_type = "internal"."""
        result = apply_guarantees(
            _base_exposure(),
            _guarantee(),
            _counterparty_lookup(),
            crr_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.005),
        ).collect()

        assert "guarantor_rating_type" in result.columns
        assert result["guarantor_rating_type"][0] == "internal"

    def test_external_rating_produces_external_type(self, crr_config: CalculationConfig) -> None:
        """Guarantor with CQS but no internal PD -> rating_type = "external"."""
        result = apply_guarantees(
            _base_exposure(),
            _guarantee(),
            _counterparty_lookup(),
            crr_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=None),
        ).collect()

        assert result["guarantor_rating_type"][0] == "external"

    def test_no_rating_produces_null(self, crr_config: CalculationConfig) -> None:
        """Guarantor with neither internal PD nor CQS -> rating_type = null."""
        result = apply_guarantees(
            _base_exposure(),
            _guarantee(),
            _counterparty_lookup(),
            crr_config,
            rating_inheritance=_rating_inheritance(cqs=None, internal_pd=None, pd=None),
        ).collect()

        assert result["guarantor_rating_type"][0] is None

    def test_internal_takes_precedence_over_external(self, crr_config: CalculationConfig) -> None:
        """When both internal PD and external CQS present, internal wins."""
        result = apply_guarantees(
            _base_exposure(),
            _guarantee(),
            _counterparty_lookup(),
            crr_config,
            rating_inheritance=_rating_inheritance(cqs=1, internal_pd=0.002),
        ).collect()

        assert result["guarantor_rating_type"][0] == "internal"

    def test_rating_type_aligns_with_approach(self, crr_config: CalculationConfig) -> None:
        """When rating_type is "external", approach should be "sa"."""
        result = apply_guarantees(
            _base_exposure(),
            _guarantee(),
            _counterparty_lookup(),
            crr_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=None),
        ).collect()

        assert result["guarantor_rating_type"][0] == "external"
        assert result["guarantor_approach"][0] == "sa"

    def test_no_rating_inheritance_produces_null(self, crr_config: CalculationConfig) -> None:
        """When no rating_inheritance provided, rating_type should be null."""
        result = apply_guarantees(
            _base_exposure(),
            _guarantee(),
            _counterparty_lookup(),
            crr_config,
            rating_inheritance=None,
        ).collect()

        assert result["guarantor_rating_type"][0] is None


class TestGuarantorRatingTypeB31:
    """Basel 3.1 framework tests for guarantor_rating_type."""

    def test_b31_internal_rating_type(self, b31_config: CalculationConfig) -> None:
        """B31: internal PD -> rating_type = "internal"."""
        result = apply_guarantees(
            _base_exposure(),
            _guarantee(),
            _counterparty_lookup(),
            b31_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.005),
        ).collect()

        assert result["guarantor_rating_type"][0] == "internal"

    def test_b31_external_rating_type(self, b31_config: CalculationConfig) -> None:
        """B31: external CQS only -> rating_type = "external"."""
        result = apply_guarantees(
            _base_exposure(),
            _guarantee(),
            _counterparty_lookup(),
            b31_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=None),
        ).collect()

        assert result["guarantor_rating_type"][0] == "external"


class TestGuarantorRatingTypeInAudit:
    """Tests that guarantor_rating_type appears in the CRM audit trail."""

    def test_audit_contains_rating_type_column(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """CRM audit trail must include guarantor_rating_type."""
        data = ClassifiedExposuresBundle(
            all_exposures=_base_exposure(),
            sa_exposures=_base_exposure(),
            irb_exposures=pl.LazyFrame(),
            counterparty_lookup=CounterpartyLookup(
                counterparties=_counterparty_lookup(),
                parent_mappings=pl.LazyFrame({"child": [], "parent": []}),
                ultimate_parent_mappings=pl.LazyFrame({"ref": [], "ult": []}),
                rating_inheritance=_rating_inheritance(cqs=2, internal_pd=None),
            ),
            classification_errors=[],
            guarantees=_guarantee(),
            collateral=None,
            provisions=None,
        )

        bundle = crm_processor.get_crm_adjusted_bundle(data, crr_config)
        assert bundle.crm_audit is not None
        audit = bundle.crm_audit.collect()
        assert "guarantor_rating_type" in audit.columns

    def test_audit_rating_type_value_external(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Audit: external-only guarantor -> "external"."""
        data = ClassifiedExposuresBundle(
            all_exposures=_base_exposure(),
            sa_exposures=_base_exposure(),
            irb_exposures=pl.LazyFrame(),
            counterparty_lookup=CounterpartyLookup(
                counterparties=_counterparty_lookup(),
                parent_mappings=pl.LazyFrame({"child": [], "parent": []}),
                ultimate_parent_mappings=pl.LazyFrame({"ref": [], "ult": []}),
                rating_inheritance=_rating_inheritance(cqs=2, internal_pd=None),
            ),
            classification_errors=[],
            guarantees=_guarantee(),
            collateral=None,
            provisions=None,
        )

        bundle = crm_processor.get_crm_adjusted_bundle(data, crr_config)
        audit = bundle.crm_audit.collect()
        assert audit["guarantor_rating_type"][0] == "external"

    def test_audit_rating_type_null_no_guarantees(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Audit: no guarantee -> guarantor_rating_type is null."""
        data = ClassifiedExposuresBundle(
            all_exposures=_base_exposure(),
            sa_exposures=_base_exposure(),
            irb_exposures=pl.LazyFrame(),
            counterparty_lookup=None,
            classification_errors=[],
            guarantees=None,
            collateral=None,
            provisions=None,
        )

        bundle = crm_processor.get_crm_adjusted_bundle(data, crr_config)
        assert bundle.crm_audit is not None
        audit = bundle.crm_audit.collect()
        assert "guarantor_rating_type" in audit.columns
        assert audit["guarantor_rating_type"][0] is None


class TestGuarantorRatingTypeEdgeCases:
    """Edge case tests for guarantor_rating_type derivation."""

    def test_column_dtype_is_string(self, crr_config: CalculationConfig) -> None:
        """guarantor_rating_type should be String type."""
        result = apply_guarantees(
            _base_exposure(),
            _guarantee(),
            _counterparty_lookup(),
            crr_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.005),
        ).collect()

        assert result.schema["guarantor_rating_type"] == pl.String

    def test_unguaranteed_exposure_has_null_rating_type(
        self,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Exposure without any guarantee should have null rating_type."""
        data = ClassifiedExposuresBundle(
            all_exposures=_base_exposure(),
            sa_exposures=_base_exposure(),
            irb_exposures=pl.LazyFrame(),
            counterparty_lookup=None,
            classification_errors=[],
            guarantees=None,
            collateral=None,
            provisions=None,
        )

        bundle = crm_processor.get_crm_adjusted_bundle(data, crr_config)
        exposures = bundle.exposures.collect()
        assert "guarantor_rating_type" in exposures.columns
        assert exposures["guarantor_rating_type"][0] is None

    def test_rating_type_values_are_constrained(self, crr_config: CalculationConfig) -> None:
        """Only "internal", "external", or null are valid values."""
        result = apply_guarantees(
            _base_exposure(),
            _guarantee(),
            _counterparty_lookup(),
            crr_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.005),
        ).collect()

        valid_values = {"internal", "external", None}
        actual = result["guarantor_rating_type"][0]
        assert actual in valid_values

    def test_multiple_exposures_mixed_rating_types(self, crr_config: CalculationConfig) -> None:
        """Multiple exposures with different guarantors get correct rating types."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "counterparty_reference": ["CP001", "CP002"],
                "exposure_class": ["corporate", "corporate"],
                "approach": ["SA", "SA"],
                "ead_pre_crm": [1_000_000.0, 2_000_000.0],
                "lgd": [0.45, 0.45],
                "cqs": [3, 3],
                "product_type": ["LOAN", "LOAN"],
                "drawn_amount": [1_000_000.0, 2_000_000.0],
                "undrawn_amount": [0.0, 0.0],
                "nominal_amount": [0.0, 0.0],
                "risk_type": [None, None],
                "interest": [0.0, 0.0],
                "maturity_date": [date(2029, 12, 31), date(2029, 12, 31)],
                "ead_after_collateral": [1_000_000.0, 2_000_000.0],
                "ead_from_ccf": [0.0, 0.0],
                "ccf": [1.0, 1.0],
                "collateral_adjusted_value": [0.0, 0.0],
                "lgd_pre_crm": [0.45, 0.45],
                "lgd_post_crm": [0.45, 0.45],
            }
        )
        guarantees = pl.LazyFrame(
            {
                "guarantee_reference": ["G001", "G002"],
                "guarantee_type": ["unfunded", "unfunded"],
                "guarantor": ["GUAR_INT", "GUAR_EXT"],
                "currency": ["GBP", "GBP"],
                "maturity_date": [date(2029, 12, 31), date(2029, 12, 31)],
                "amount_covered": [500_000.0, 1_000_000.0],
                "percentage_covered": [None, None],
                "beneficiary_type": ["exposure", "exposure"],
                "beneficiary_reference": ["EXP001", "EXP002"],
                "protection_type": ["guarantee", "guarantee"],
                "includes_restructuring": [True, True],
            }
        )
        cp_lookup = pl.LazyFrame(
            {
                "counterparty_reference": ["GUAR_INT", "GUAR_EXT"],
                "entity_type": ["corporate", "institution"],
                "country_code": ["GB", "GB"],
            }
        )
        ri = pl.LazyFrame(
            {
                "counterparty_reference": ["GUAR_INT", "GUAR_EXT"],
                "cqs": [1, 2],
                "pd": [0.005, None],
                "internal_pd": [0.005, None],
            }
        )

        result = apply_guarantees(exposures, guarantees, cp_lookup, crr_config, ri).collect()

        # First exposure guaranteed by internal-rated guarantor
        row0 = result.filter(pl.col("parent_exposure_reference") == "EXP001")
        guar0 = row0.filter(pl.col("guaranteed_portion") > 0)
        assert guar0["guarantor_rating_type"][0] == "internal"

        # Second exposure guaranteed by external-only guarantor
        row1 = result.filter(pl.col("parent_exposure_reference") == "EXP002")
        guar1 = row1.filter(pl.col("guaranteed_portion") > 0)
        assert guar1["guarantor_rating_type"][0] == "external"


# ---------------------------------------------------------------------------
# Art. 114(4)/(7) priority over internal-rating routing
# ---------------------------------------------------------------------------


def _sovereign_exposure(currency: str, original_currency: str | None = None) -> pl.LazyFrame:
    """Exposure with currency columns so the EU/UK domestic check has data to read."""
    cols = {
        "exposure_reference": ["EXP001"],
        "counterparty_reference": ["CP001"],
        "exposure_class": ["corporate"],
        "approach": ["foundation_irb"],
        "ead_pre_crm": [1_000_000.0],
        "lgd": [0.45],
        "cqs": [3],
        "product_type": ["LOAN"],
        "drawn_amount": [1_000_000.0],
        "undrawn_amount": [0.0],
        "nominal_amount": [0.0],
        "risk_type": [None],
        "interest": [0.0],
        "maturity_date": [date(2029, 12, 31)],
        "ead_after_collateral": [1_000_000.0],
        "ead_from_ccf": [0.0],
        "ccf": [1.0],
        "collateral_adjusted_value": [0.0],
        "lgd_pre_crm": [0.45],
        "lgd_post_crm": [0.45],
        "currency": [currency],
    }
    if original_currency is not None:
        cols["original_currency"] = [original_currency]
    return pl.LazyFrame(cols)


def _sovereign_counterparty_lookup(country_code: str) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "counterparty_reference": ["GUAR001"],
            "entity_type": ["sovereign"],
            "country_code": [country_code],
        }
    )


class TestDomesticSovereignGuarantorForcedToSA:
    """Art. 114(4)/(7): EU/UK domestic-currency CGCB guarantor must be routed through
    SA so the 0% RW short-circuit applies — even when the guarantor has an internal
    PD that would otherwise route it to IRB parameter substitution.

    The domestic-currency test is evaluated against the **guarantee** currency (the
    currency of the substituted exposure to the sovereign), not the underlying
    exposure currency. Art. 233(3) FX haircut handles the mismatch separately.
    """

    def test_uk_sovereign_gbp_guarantee_with_internal_pd_forced_to_sa(
        self, crr_irb_config: CalculationConfig
    ) -> None:
        """UK sovereign guarantor + GBP guarantee + internal PD -> 'sa'.

        Without the Art. 114(4) override, the firm's CGCB IRB permission combined with
        the internal PD would route this to 'irb' and apply parametric IRB RW.
        """
        result = apply_guarantees(
            _sovereign_exposure(currency="GBP"),
            _guarantee(currency="GBP"),
            _sovereign_counterparty_lookup("GB"),
            crr_irb_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.001),
        ).collect()

        assert result["guarantor_approach"][0] == "sa"
        # Rating type still reports the underlying rating source
        assert result["guarantor_rating_type"][0] == "internal"

    def test_de_sovereign_eur_guarantee_with_internal_pd_forced_to_sa(
        self, crr_irb_config: CalculationConfig
    ) -> None:
        """DE sovereign + EUR guarantee + internal PD -> 'sa' via Art. 114(7)."""
        result = apply_guarantees(
            _sovereign_exposure(currency="GBP"),
            _guarantee(currency="EUR"),
            _sovereign_counterparty_lookup("DE"),
            crr_irb_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.001),
        ).collect()

        assert result["guarantor_approach"][0] == "sa"

    def test_pl_sovereign_pln_guarantee_with_internal_pd_forced_to_sa(
        self, crr_irb_config: CalculationConfig
    ) -> None:
        """PL sovereign + PLN guarantee + internal PD -> 'sa' (non-euro EU)."""
        result = apply_guarantees(
            _sovereign_exposure(currency="GBP"),
            _guarantee(currency="PLN"),
            _sovereign_counterparty_lookup("PL"),
            crr_irb_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.001),
        ).collect()

        assert result["guarantor_approach"][0] == "sa"

    def test_gbp_loan_eur_guarantee_de_sovereign_forced_to_sa(
        self, crr_irb_config: CalculationConfig
    ) -> None:
        """Cross-currency: GBP loan + EUR guarantee + DE sovereign -> 'sa'.

        Regression test for the reported bug: guarantee currency (EUR) matches
        DE's domestic currency so Art. 114(7) fires, even though the underlying
        loan is in GBP. Art. 233(3) 8% FX haircut handles the mismatch.
        """
        result = apply_guarantees(
            _sovereign_exposure(currency="GBP", original_currency="GBP"),
            _guarantee(currency="EUR"),
            _sovereign_counterparty_lookup("DE"),
            crr_irb_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.001),
        ).collect()

        assert result["guarantor_approach"][0] == "sa"

    def test_de_sovereign_usd_guarantee_stays_irb(self, crr_irb_config: CalculationConfig) -> None:
        """DE sovereign + USD guarantee (non-domestic) + internal PD -> 'irb'.

        USD is not DE's domestic currency, so Art. 114(7) cannot apply; the
        internal-PD branch wins and parametric IRB RW substitution is used.
        """
        result = apply_guarantees(
            _sovereign_exposure(currency="GBP"),
            _guarantee(currency="USD"),
            _sovereign_counterparty_lookup("DE"),
            crr_irb_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.001),
        ).collect()

        assert result["guarantor_approach"][0] == "irb"

    def test_exposure_ccy_matches_but_guarantee_ccy_does_not_stays_irb(
        self, crr_irb_config: CalculationConfig
    ) -> None:
        """EUR loan + GBP guarantee + DE sovereign -> 'irb'.

        Guards against regressing to the old behaviour that read exposure currency.
        The exposure is in DE's domestic (EUR) but the guarantee is in GBP, so
        the substituted exposure to the sovereign is not in DE's domestic currency.
        """
        result = apply_guarantees(
            _sovereign_exposure(currency="GBP", original_currency="EUR"),
            _guarantee(currency="GBP"),
            _sovereign_counterparty_lookup("DE"),
            crr_irb_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.001),
        ).collect()

        assert result["guarantor_approach"][0] == "irb"

    def test_b31_uk_sovereign_gbp_guarantee_with_internal_pd_forced_to_sa(
        self, b31_irb_config: CalculationConfig
    ) -> None:
        """Basel 3.1: UK sovereign + GBP guarantee + internal PD -> 'sa'."""
        result = apply_guarantees(
            _sovereign_exposure(currency="GBP"),
            _guarantee(currency="GBP"),
            _sovereign_counterparty_lookup("GB"),
            b31_irb_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.001),
        ).collect()

        assert result["guarantor_approach"][0] == "sa"

    def test_b31_de_sovereign_eur_guarantee_with_internal_pd_forced_to_sa(
        self, b31_irb_config: CalculationConfig
    ) -> None:
        """Basel 3.1: DE sovereign + EUR guarantee + internal PD -> 'sa'."""
        result = apply_guarantees(
            _sovereign_exposure(currency="GBP"),
            _guarantee(currency="EUR"),
            _sovereign_counterparty_lookup("DE"),
            b31_irb_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.001),
        ).collect()

        assert result["guarantor_approach"][0] == "sa"


# ---------------------------------------------------------------------------
# Beneficiary-aware routing: institution beneficiary + institution guarantor
# ---------------------------------------------------------------------------


def _institution_exposure(approach: str) -> pl.LazyFrame:
    """Institution-class exposure where `approach` is the BENEFICIARY's approach."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP001"],
            "counterparty_reference": ["CP001"],
            "exposure_class": ["institution"],
            "approach": [approach],
            "ead_pre_crm": [1_000_000.0],
            "lgd": [0.45],
            "cqs": [3],
            "product_type": ["LOAN"],
            "drawn_amount": [1_000_000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "risk_type": [None],
            "interest": [0.0],
            "maturity_date": [date(2029, 12, 31)],
            "ead_after_collateral": [1_000_000.0],
            "ead_from_ccf": [0.0],
            "ccf": [1.0],
            "collateral_adjusted_value": [0.0],
            "lgd_pre_crm": [0.45],
            "lgd_post_crm": [0.45],
        }
    )


def _institution_counterparty_lookup() -> pl.LazyFrame:
    """Counterparty lookup for an institution guarantor."""
    return pl.LazyFrame(
        {
            "counterparty_reference": ["GUAR001"],
            "entity_type": ["institution"],
            "country_code": ["GB"],
        }
    )


class TestInstitutionGuarantorBeneficiaryAware:
    """Beneficiary-aware guarantor routing for an institution-on-institution
    guarantee where both parties have internal AND external ratings.

    Expected (CRR Art. 161 / Basel 3.1 CRE22.70-85):
    - Beneficiary on IRB → guarantor_approach == "irb" (use internal PD)
    - Beneficiary on SA  → guarantor_approach == "sa"  (use external CQS)
    """

    def test_crr_irb_beneficiary_routes_guarantor_to_irb(
        self, crr_irb_config: CalculationConfig
    ) -> None:
        result = apply_guarantees(
            _institution_exposure(approach="foundation_irb"),
            _guarantee(),
            _institution_counterparty_lookup(),
            crr_irb_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.005),
        ).collect()

        assert result["guarantor_approach"][0] == "irb"

    def test_crr_sa_beneficiary_routes_guarantor_to_sa(
        self, crr_irb_config: CalculationConfig
    ) -> None:
        """SA beneficiary always uses guarantor's external CQS, even if guarantor
        has an internal PD that would otherwise route to IRB."""
        result = apply_guarantees(
            _institution_exposure(approach="standardised"),
            _guarantee(),
            _institution_counterparty_lookup(),
            crr_irb_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.005),
        ).collect()

        assert result["guarantor_approach"][0] == "sa"

    def test_b31_irb_beneficiary_routes_guarantor_to_irb(
        self, b31_irb_config: CalculationConfig
    ) -> None:
        result = apply_guarantees(
            _institution_exposure(approach="foundation_irb"),
            _guarantee(),
            _institution_counterparty_lookup(),
            b31_irb_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.005),
        ).collect()

        assert result["guarantor_approach"][0] == "irb"

    def test_b31_sa_beneficiary_routes_guarantor_to_sa(
        self, b31_irb_config: CalculationConfig
    ) -> None:
        result = apply_guarantees(
            _institution_exposure(approach="standardised"),
            _guarantee(),
            _institution_counterparty_lookup(),
            b31_irb_config,
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.005),
        ).collect()

        assert result["guarantor_approach"][0] == "sa"

    def test_irb_beneficiary_without_firm_irb_permission_falls_back_to_sa(
        self, crr_config: CalculationConfig
    ) -> None:
        """If the firm lacks IRB permission for the guarantor's exposure class,
        the guarantor is routed to SA even when the beneficiary is IRB."""
        result = apply_guarantees(
            _institution_exposure(approach="foundation_irb"),
            _guarantee(),
            _institution_counterparty_lookup(),
            crr_config,  # default permissions (SA-only)
            rating_inheritance=_rating_inheritance(cqs=2, internal_pd=0.005),
        ).collect()

        assert result["guarantor_approach"][0] == "sa"
