"""
Integration tests: EU/UK domestic sovereign guarantor 0% RW end-to-end.

Verifies the two-limb Art. 114(4)/(7) + Art. 235(3) condition under the
substitution approach (CRR Art. 215-217): the 0% domestic-CGCB extension applies
only when the substituted exposure is BOTH

  (a) denominated in the guarantor's domestic currency — evaluated against the
      **guarantee** currency, with the Art. 233(3) 8% FX haircut separately
      absorbing any guarantee-vs-underlying mismatch; AND
  (b) *funded* in that same currency — the Art. 235(3) funding limb, which reads
      the loan's funding currency (its ``funding_currency``, falling back to the
      denomination). See P1.229.

A loan funded in a non-domestic currency therefore does NOT receive the 0%
extension even when the guarantee is denominated in the domestic currency; it
follows normal guarantor routing instead (here: IRB parameter substitution,
because the sovereign guarantors carry an internal PD and the beneficiaries are
IRB). Only the same-currency case keeps the 0% short-circuit.

Pipeline wired: HierarchyResolver -> ExposureClassifier -> CRMProcessor
    -> SACalculator / IRBCalculator. No mocking.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.schemas import FX_RATES_SCHEMA, GUARANTEE_SCHEMA, RATINGS_SCHEMA
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.hierarchy import HierarchyResolver
from tests.fixtures.raw_bundle import make_raw_bundle

from .conftest import (
    _rows_to_lazyframe,
    make_counterparty,
    make_facility,
    make_loan,
    make_model_permission,
    make_raw_data_bundle,
)

# =============================================================================
# HELPERS
# =============================================================================

_RATING_DATE = date(2024, 6, 1)
_MODEL_ID = "MODEL_01"


def _full_irb_model_permissions() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ec in ["corporate", "central_govt_central_bank"]:
        for approach in ["advanced_irb", "foundation_irb"]:
            rows.append(
                make_model_permission(
                    model_id=_MODEL_ID,
                    exposure_class=ec,
                    approach=approach,
                )
            )
    return rows


def _internal_rating(
    *,
    counterparty_reference: str,
    pd: float,
    rating_reference: str | None = None,
) -> dict[str, Any]:
    return {
        "rating_reference": rating_reference or f"RAT_{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "rating_agency": "internal",
        "rating_value": "BB",
        "cqs": None,
        "pd": pd,
        "rating_date": _RATING_DATE,
        "is_solicited": True,
        "model_id": _MODEL_ID,
    }


def _guarantee_row(
    *,
    guarantee_reference: str,
    guarantor: str,
    currency: str,
    amount_covered: float,
    beneficiary_type: str,
    beneficiary_reference: str,
) -> dict[str, Any]:
    return {
        "guarantee_reference": guarantee_reference,
        "guarantee_type": "sovereign_guarantee",
        "guarantor": guarantor,
        "currency": currency,
        "maturity_date": date(2030, 12, 31),
        "amount_covered": amount_covered,
        "percentage_covered": None,
        "beneficiary_type": beneficiary_type,
        "beneficiary_reference": beneficiary_reference,
        "protection_type": "guarantee",
        "includes_restructuring": True,
    }


def _fx_rates() -> list[dict[str, Any]]:
    """FX rates to GBP base currency."""
    return [
        {"currency_from": "EUR", "currency_to": "GBP", "rate": 0.86},
        {"currency_from": "USD", "currency_to": "GBP", "rate": 0.78},
        {"currency_from": "GBP", "currency_to": "GBP", "rate": 1.0},
    ]


def _build_bundle(
    *,
    loan_currency: str,
    guarantee_currency: str,
    guarantor_country: str,
    beneficiary_type: str,
    borrower_internal_pd: float = 0.02,
    guarantor_internal_pd: float = 0.001,
) -> RawDataBundle:
    """Build a RawDataBundle with:

    - borrower corporate (GB, internal PD -> IRB)
    - sovereign guarantor (country=guarantor_country, internal PD)
    - loan from borrower in loan_currency
    - guarantee from sovereign in guarantee_currency, at beneficiary_type level
    """
    counterparties = [
        make_counterparty(
            counterparty_reference="BORROWER",
            counterparty_name="Borrower Corp",
            entity_type="corporate",
            country_code="GB",
        ),
        make_counterparty(
            counterparty_reference="SOV_GUAR",
            counterparty_name="Sovereign Guarantor",
            entity_type="sovereign",
            country_code=guarantor_country,
            annual_revenue=0.0,
            total_assets=0.0,
        ),
    ]
    loans = [
        make_loan(
            loan_reference="LN_BORROWER",
            counterparty_reference="BORROWER",
            currency=loan_currency,
            drawn_amount=1_000_000.0,
            interest=0.0,
        ),
    ]
    facilities = [
        make_facility(
            facility_reference="FAC_BORROWER",
            counterparty_reference="BORROWER",
            currency=loan_currency,
        ),
    ]
    ratings = [
        _internal_rating(counterparty_reference="BORROWER", pd=borrower_internal_pd),
        _internal_rating(counterparty_reference="SOV_GUAR", pd=guarantor_internal_pd),
    ]
    beneficiary_reference = {
        "loan": "LN_BORROWER",
        "facility": "FAC_BORROWER",
        "counterparty": "BORROWER",
    }[beneficiary_type]
    guarantees_rows = [
        _guarantee_row(
            guarantee_reference="GUAR_SOV_001",
            guarantor="SOV_GUAR",
            currency=guarantee_currency,
            amount_covered=1_000_000.0,
            beneficiary_type=beneficiary_type,
            beneficiary_reference=beneficiary_reference,
        ),
    ]
    bundle = make_raw_data_bundle(
        counterparties=counterparties,
        loans=loans,
        facilities=facilities,
        model_permissions=_full_irb_model_permissions(),
    )
    ratings_lf = _rows_to_lazyframe(ratings, RATINGS_SCHEMA)
    guarantees_lf = _rows_to_lazyframe(guarantees_rows, GUARANTEE_SCHEMA)
    fx_rates_lf = _rows_to_lazyframe(_fx_rates(), FX_RATES_SCHEMA)
    return make_raw_bundle(
        facilities=bundle.facilities,
        loans=bundle.loans,
        counterparties=bundle.counterparties,
        facility_mappings=bundle.facility_mappings,
        lending_mappings=bundle.lending_mappings,
        org_mappings=bundle.org_mappings,
        contingents=bundle.contingents,
        collateral=bundle.collateral,
        guarantees=guarantees_lf,
        provisions=bundle.provisions,
        ratings=ratings_lf,
        specialised_lending=bundle.specialised_lending,
        equity_exposures=bundle.equity_exposures,
        fx_rates=fx_rates_lf,
        model_permissions=bundle.model_permissions,
    )


def _run_to_crm(
    resolver: HierarchyResolver,
    classifier: ExposureClassifier,
    crm_processor: CRMProcessor,
    config: CalculationConfig,
    bundle: RawDataBundle,
) -> CRMAdjustedBundle:
    resolved = resolver.resolve(bundle, config)
    classified = classifier.classify(resolved, config)
    return crm_processor.get_crm_unified_bundle(classified, config)


def _guarantor_row(df: pl.DataFrame, loan_reference: str = "LN_BORROWER") -> dict[str, Any]:
    """Locate the guaranteed sub-row (or row with positive guaranteed_portion) for the loan."""
    matching = df.filter(
        pl.col("exposure_reference").str.contains(loan_reference, literal=True)
        & (pl.col("guaranteed_portion").fill_null(0) > 0)
    )
    assert matching.height >= 1, f"No guaranteed sub-row found for {loan_reference} in {df}"
    return matching.row(0, named=True)


# =============================================================================
# CASES
# =============================================================================


class TestDomesticSovereignGuarantorEndToEnd:
    """Final risk_weight and guarantor_approach for cross-currency sovereign guarantees."""

    def test_gbp_loan_eur_guarantee_de_sovereign_facility_level(
        self, hierarchy_resolver, classifier, crm_processor, irb_calculator, crr_firb_config
    ):
        """GBP-funded loan + EUR guarantee from DE sovereign at facility level.

        The guarantee currency (EUR) matches DE's domestic currency so the
        DENOMINATION limb of Art. 114(4)/(7) passes — but the loan is FUNDED in
        GBP, so the Art. 235(3) FUNDING limb fails and the 0% extension is denied
        (P1.229). Normal routing applies: the DE sovereign carries an internal PD
        and the beneficiary is IRB, so the guarantor routes to IRB parameter
        substitution with a positive risk weight — NOT the 0% short-circuit.

        (Pre-P1.229 this case wrongly returned guarantor_approach="sa" / 0% RW —
        the engine tested only the guarantee currency, ignoring the funding limb.)
        """
        bundle = _build_bundle(
            loan_currency="GBP",
            guarantee_currency="EUR",
            guarantor_country="DE",
            beneficiary_type="facility",
        )
        crm_bundle = _run_to_crm(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )
        irb_lf = irb_calculator.calculate_branch(
            crm_bundle.exposures.filter(
                pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value])
            ),
            crr_firb_config,
        )
        df = irb_lf.collect()

        row = _guarantor_row(df)
        assert row["guarantor_approach"] == "irb", (
            f"Expected irb (GBP-funded loan fails the Art. 235(3) funding limb "
            f"despite the EUR guarantee matching DE domestic), got "
            f"{row['guarantor_approach']!r}"
        )
        # 0% short-circuit must NOT fire — the sovereign's IRB parameter
        # substitution yields a positive risk weight.
        assert row["guarantor_rw"] > 0.0

    def test_gbp_loan_gbp_guarantee_uk_sovereign_counterparty_level(
        self, hierarchy_resolver, classifier, crm_processor, irb_calculator, crr_firb_config
    ):
        """No regression for the same-currency UK sovereign case."""
        bundle = _build_bundle(
            loan_currency="GBP",
            guarantee_currency="GBP",
            guarantor_country="GB",
            beneficiary_type="counterparty",
        )
        crm_bundle = _run_to_crm(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )
        irb_lf = irb_calculator.calculate_branch(
            crm_bundle.exposures.filter(
                pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value])
            ),
            crr_firb_config,
        )
        df = irb_lf.collect()

        row = _guarantor_row(df)
        assert row["guarantor_approach"] == "sa"
        assert row["guarantor_rw"] == pytest.approx(0.0, abs=1e-9)

    def test_eur_loan_gbp_guarantee_uk_sovereign(
        self, hierarchy_resolver, classifier, crm_processor, irb_calculator, crr_firb_config
    ):
        """Mirror case: EUR-funded loan + GBP guarantee from UK sovereign.

        The guarantee currency (GBP) matches the UK's domestic currency so the
        denomination limb passes — but the loan is FUNDED in EUR, so the
        Art. 235(3) funding limb fails and the 0% extension is denied (P1.229).
        The guarantor (internal PD, IRB beneficiary) routes to IRB parameter
        substitution with a positive risk weight.

        (Pre-P1.229 this case wrongly returned guarantor_approach="sa" / 0% RW.)
        """
        bundle = _build_bundle(
            loan_currency="EUR",
            guarantee_currency="GBP",
            guarantor_country="GB",
            beneficiary_type="loan",
        )
        crm_bundle = _run_to_crm(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )
        irb_lf = irb_calculator.calculate_branch(
            crm_bundle.exposures.filter(
                pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value])
            ),
            crr_firb_config,
        )
        df = irb_lf.collect()

        row = _guarantor_row(df)
        assert row["guarantor_approach"] == "irb"
        assert row["guarantor_rw"] > 0.0

    def test_gbp_loan_usd_guarantee_de_sovereign_stays_irb(
        self, hierarchy_resolver, classifier, crm_processor, irb_calculator, crr_firb_config
    ):
        """Negative control: guarantee currency (USD) is NOT DE's domestic (EUR).

        Art. 114(7) cannot apply, so internal-PD routing wins and the guarantor
        uses parametric IRB RW substitution (non-zero).
        """
        bundle = _build_bundle(
            loan_currency="GBP",
            guarantee_currency="USD",
            guarantor_country="DE",
            beneficiary_type="loan",
        )
        crm_bundle = _run_to_crm(
            hierarchy_resolver, classifier, crm_processor, crr_firb_config, bundle
        )
        irb_lf = irb_calculator.calculate_branch(
            crm_bundle.exposures.filter(
                pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value])
            ),
            crr_firb_config,
        )
        df = irb_lf.collect()

        row = _guarantor_row(df)
        assert row["guarantor_approach"] == "irb"
        # Positive guarantor RW — the 0% short-circuit must not fire here.
        assert row["guarantor_rw"] > 0.0
