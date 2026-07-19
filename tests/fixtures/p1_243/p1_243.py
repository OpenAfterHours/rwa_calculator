"""
P1.243 — IRB retail monetary cap is an SME-limb-only condition (Art. 147(5)(a)).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (engine/stages/classify/{attributes,subtypes,approach}.py)

Key responsibilities:
- Provide in-memory ``ResolvedHierarchyBundle`` builders that exercise the split
  of CRR / PS1/26 Art. 147(5)(a) into its two limbs for the IRB retail class:

    (A) natural person, aggregate owed > cap -> IRB retail (Art. 147(5)(a)(i):
        no amount cap on natural persons). SA regulatory-retail (Art. 123A) still
        expels them, so ``exposure_class`` (SA) stays CORPORATE while
        ``exposure_class_irb`` stays RETAIL_OTHER and the row routes to A-IRB.
    (B) SME, aggregate owed > cap -> stays CORPORATE_SME under IRB
        (Art. 147(5)(a)(ii): the monetary cap conditions the SME limb).
    (C) natural person, aggregate owed <= cap -> IRB retail (unchanged control;
        guards against an over-broad bypass).

- Provide a raw ``RawDataBundle`` builder (natural person over cap + SME over
  cap control) for the end-to-end acceptance twins under both regimes.

The monetary cap is EUR 1,000,000 (CRR, ~GBP 873k after the EUR/GBP seam) /
GBP 880,000 (PS1/26). ``OVER_CAP`` and ``UNDER_CAP`` straddle both native
thresholds so the fixtures are regime-invariant.

References:
- CRR Art. 147(5)(a)(i)/(ii): IRB retail class; monetary cap on the SME limb only.
- PRA PS1/26 Art. 147(5)(a)(i)/(ii): identical structure, GBP 880,000 SME cap.
- CRR Art. 123 / PS1/26 Art. 123A: the SA regulatory-retail cap (separate rule,
  applies to natural persons too — deliberately left binding here).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from tests.fixtures.raw_bundle import make_raw_bundle
from tests.fixtures.resolved_bundle import make_counterparty_lookup, make_resolved_bundle

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

    from rwa_calc.contracts.bundles import RawDataBundle, ResolvedHierarchyBundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

CP_NATURAL_PERSON: str = "CP_NAT_PERSON"
CP_SME: str = "CP_SME"

LOAN_NATURAL_PERSON: str = "LN_NAT_PERSON"
LOAN_SME: str = "LN_SME"

MODEL_ID: str = "M_RETAIL_CORP_IRB"

VALUE_DATE: date = date(2027, 1, 15)
MATURITY_DATE: date = date(2030, 1, 15)

EXPOSURE_PD: float = 0.02
OWN_LGD: float = 0.45

# Aggregate owed to the institution. OVER_CAP breaches both the CRR EUR 1,000,000
# (~GBP 873,200) and the PS1/26 GBP 880,000 thresholds; UNDER_CAP is below both.
OVER_CAP: float = 2_000_000.0
UNDER_CAP: float = 500_000.0

# SME revenue below the Art. 4(1)(128D) EUR 50m turnover threshold.
SME_REVENUE: float = 10_000_000.0


# ---------------------------------------------------------------------------
# Counterparty builder
# ---------------------------------------------------------------------------

_CP_SCHEMA: dict[str, PolarsDataType] = {
    "counterparty_reference": pl.String,
    "entity_type": pl.String,
    "country_code": pl.String,
    "annual_revenue": pl.Float64,
    "total_assets": pl.Float64,
    "default_status": pl.Boolean,
    "is_managed_as_retail": pl.Boolean,
    "is_natural_person": pl.Boolean,
}


def _make_cp(
    counterparty_reference: str,
    *,
    entity_type: str,
    annual_revenue: float | None,
    is_natural_person: bool,
) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "counterparty_reference": [counterparty_reference],
            "entity_type": [entity_type],
            "country_code": ["GB"],
            "annual_revenue": [annual_revenue],
            "total_assets": [None],
            "default_status": [False],
            # Managed as retail so the pool-management limb (PS1/26 Art. 123A(1)
            # (b)(iii) / IRB Art. 147(5)(c)) passes — isolating the monetary
            # threshold as the ONLY limb that can expel the row.
            "is_managed_as_retail": [True],
            "is_natural_person": [is_natural_person],
        },
        schema=_CP_SCHEMA,
    )


# ---------------------------------------------------------------------------
# Exposure / model_permissions / rating builders (resolved-bundle path)
# ---------------------------------------------------------------------------

_EXPOSURE_SCHEMA: dict[str, PolarsDataType] = {
    "exposure_reference": pl.String,
    "exposure_type": pl.String,
    "product_type": pl.String,
    "book_code": pl.String,
    "counterparty_reference": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "currency": pl.String,
    "drawn_amount": pl.Float64,
    "undrawn_amount": pl.Float64,
    "nominal_amount": pl.Float64,
    "lgd": pl.Float64,
    "internal_pd": pl.Float64,
    "seniority": pl.String,
    "exposure_has_parent": pl.Boolean,
    "root_facility_reference": pl.String,
    "facility_hierarchy_depth": pl.Int32,
    "counterparty_has_parent": pl.Boolean,
    "parent_counterparty_reference": pl.String,
    "ultimate_parent_reference": pl.String,
    "counterparty_hierarchy_depth": pl.Int32,
    "lending_group_reference": pl.String,
    "lending_group_total_exposure": pl.Float64,
    "residential_collateral_value": pl.Float64,
    "exposure_for_retail_threshold": pl.Float64,
    "lending_group_adjusted_exposure": pl.Float64,
    "model_id": pl.String,
}


def _make_exposure(
    exposure_reference: str,
    counterparty_reference: str,
    aggregate_owed: float,
) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "exposure_reference": [exposure_reference],
            "exposure_type": ["loan"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["RETAIL"],
            "counterparty_reference": [counterparty_reference],
            "value_date": [VALUE_DATE],
            "maturity_date": [MATURITY_DATE],
            "currency": ["GBP"],
            "drawn_amount": [aggregate_owed],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [OWN_LGD],
            "internal_pd": [EXPOSURE_PD],
            "seniority": ["senior"],
            "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [aggregate_owed],
            "residential_collateral_value": [0.0],
            "exposure_for_retail_threshold": [aggregate_owed],
            "lending_group_adjusted_exposure": [aggregate_owed],
            "model_id": [MODEL_ID],
        },
        schema=_EXPOSURE_SCHEMA,
    )


def _make_model_permissions() -> pl.LazyFrame:
    # Grant retail_other A-IRB (retail is own-estimate only) and corporate /
    # corporate_sme A-IRB so approach routing is driven by the IRB exposure
    # class, not by permission scarcity: the natural person routes to retail
    # A-IRB and the SME control to corporate A-IRB.
    classes = ["retail_other", "corporate", "corporate_sme"]
    return pl.LazyFrame(
        {
            "model_id": [MODEL_ID] * len(classes),
            "exposure_class": classes,
            "approach": ["advanced_irb"] * len(classes),
            "country_codes": [None] * len(classes),
            "excluded_book_codes": [None] * len(classes),
        },
        schema={
            "model_id": pl.String,
            "exposure_class": pl.String,
            "approach": pl.String,
            "country_codes": pl.String,
            "excluded_book_codes": pl.String,
        },
    )


def _make_rating_inheritance(counterparty_reference: str) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "counterparty_reference": [counterparty_reference],
            "internal_pd": [EXPOSURE_PD],
            "internal_model_id": [MODEL_ID],
            "external_cqs": [None],
            "cqs": [None],
            "pd": [EXPOSURE_PD],
        },
        schema={
            "counterparty_reference": pl.String,
            "internal_pd": pl.Float64,
            "internal_model_id": pl.String,
            "external_cqs": pl.Int8,
            "cqs": pl.Int8,
            "pd": pl.Float64,
        },
    )


def _empty_schema_lf(schema: dict[str, PolarsDataType]) -> pl.LazyFrame:
    return pl.LazyFrame(schema=schema)


def _make_bundle(
    counterparties: pl.LazyFrame,
    counterparty_reference: str,
    exposure_reference: str,
    aggregate_owed: float,
) -> ResolvedHierarchyBundle:
    return make_resolved_bundle(
        exposures=_make_exposure(exposure_reference, counterparty_reference, aggregate_owed),
        counterparty_lookup=make_counterparty_lookup(
            counterparties=counterparties,
            parent_mappings=_empty_schema_lf(
                {
                    "child_counterparty_reference": pl.String,
                    "parent_counterparty_reference": pl.String,
                }
            ),
            ultimate_parent_mappings=_empty_schema_lf(
                {
                    "counterparty_reference": pl.String,
                    "ultimate_parent_reference": pl.String,
                    "hierarchy_depth": pl.Int32,
                }
            ),
            rating_inheritance=_make_rating_inheritance(counterparty_reference),
        ),
        lending_group_totals=_empty_schema_lf(
            {
                "lending_group_reference": pl.String,
                "total_exposure": pl.Float64,
            }
        ),
        model_permissions=_make_model_permissions(),
        hierarchy_errors=[],
    )


# ---------------------------------------------------------------------------
# Named scenario bundles (classifier-level unit tests)
# ---------------------------------------------------------------------------


def make_natural_person_over_cap_bundle() -> ResolvedHierarchyBundle:
    """(A) natural person, aggregate 2,000,000 > cap -> IRB retail; SA corporate."""
    return _make_bundle(
        _make_cp(
            CP_NATURAL_PERSON,
            entity_type="individual",
            annual_revenue=None,
            is_natural_person=True,
        ),
        CP_NATURAL_PERSON,
        LOAN_NATURAL_PERSON,
        OVER_CAP,
    )


def make_sme_over_cap_bundle() -> ResolvedHierarchyBundle:
    """(B) SME, aggregate 2,000,000 > cap -> stays CORPORATE_SME under IRB."""
    return _make_bundle(
        _make_cp(
            CP_SME,
            entity_type="corporate",
            annual_revenue=SME_REVENUE,
            is_natural_person=False,
        ),
        CP_SME,
        LOAN_SME,
        OVER_CAP,
    )


def make_natural_person_under_cap_bundle() -> ResolvedHierarchyBundle:
    """(C) natural person, aggregate 500,000 <= cap -> IRB retail (control)."""
    return _make_bundle(
        _make_cp(
            CP_NATURAL_PERSON,
            entity_type="individual",
            annual_revenue=None,
            is_natural_person=True,
        ),
        CP_NATURAL_PERSON,
        LOAN_NATURAL_PERSON,
        UNDER_CAP,
    )


# ---------------------------------------------------------------------------
# Raw bundle (end-to-end acceptance twins)
# ---------------------------------------------------------------------------


def _raw_counterparties() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "counterparty_reference": [CP_NATURAL_PERSON, CP_SME],
            "entity_type": ["individual", "corporate"],
            "country_code": ["GB", "GB"],
            "annual_revenue": [None, SME_REVENUE],
            "total_assets": [None, None],
            "default_status": [False, False],
            "is_managed_as_retail": [True, True],
            "is_natural_person": [True, False],
        },
        schema={
            "counterparty_reference": pl.String,
            "entity_type": pl.String,
            "country_code": pl.String,
            "annual_revenue": pl.Float64,
            "total_assets": pl.Float64,
            "default_status": pl.Boolean,
            "is_managed_as_retail": pl.Boolean,
            "is_natural_person": pl.Boolean,
        },
    )


def _raw_loans() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "loan_reference": [LOAN_NATURAL_PERSON, LOAN_SME],
            "counterparty_reference": [CP_NATURAL_PERSON, CP_SME],
            "product_type": ["TERM_LOAN", "TERM_LOAN"],
            "book_code": ["RETAIL", "RETAIL"],
            "currency": ["GBP", "GBP"],
            "drawn_amount": [OVER_CAP, OVER_CAP],
            "lgd": [OWN_LGD, OWN_LGD],
            "seniority": ["senior", "senior"],
            "value_date": [VALUE_DATE, VALUE_DATE],
            "maturity_date": [MATURITY_DATE, MATURITY_DATE],
        },
        schema={
            "loan_reference": pl.String,
            "counterparty_reference": pl.String,
            "product_type": pl.String,
            "book_code": pl.String,
            "currency": pl.String,
            "drawn_amount": pl.Float64,
            "lgd": pl.Float64,
            "seniority": pl.String,
            "value_date": pl.Date,
            "maturity_date": pl.Date,
        },
    )


def _raw_ratings() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "rating_reference": ["RAT_NAT", "RAT_SME"],
            "counterparty_reference": [CP_NATURAL_PERSON, CP_SME],
            "rating_type": ["internal", "internal"],
            "pd": [EXPOSURE_PD, EXPOSURE_PD],
            "model_id": [MODEL_ID, MODEL_ID],
            "rating_date": [VALUE_DATE, VALUE_DATE],
        },
        schema={
            "rating_reference": pl.String,
            "counterparty_reference": pl.String,
            "rating_type": pl.String,
            "pd": pl.Float64,
            "model_id": pl.String,
            "rating_date": pl.Date,
        },
    )


def build_p1_243_raw_bundle() -> RawDataBundle:
    """RawDataBundle: natural person over cap + SME over cap, both IRB-permissioned."""
    empty_lending = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )
    empty_facility_mappings = pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        }
    )
    empty_facilities = pl.LazyFrame(
        schema={
            "facility_reference": pl.String,
            "counterparty_reference": pl.String,
        }
    )
    return make_raw_bundle(
        facilities=empty_facilities,
        loans=_raw_loans(),
        counterparties=_raw_counterparties(),
        facility_mappings=empty_facility_mappings,
        lending_mappings=empty_lending,
        ratings=_raw_ratings(),
        model_permissions=_make_model_permissions(),
    )
