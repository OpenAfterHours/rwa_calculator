"""
Residential security the hierarchy's property VALUES cannot see — the P1.324 guards.

Pipeline position:
    build_residential_security_guard_bundle() -> RawDataBundle -> PipelineOrchestrator

Why it exists (P1.324 review F1). Basel 3.1 reads three floors off RESIDENTIAL
security — the PS1/26 Art. 154(4A)(b) 10% RWEA floor, the Art. 163(1)(b) 0.10% PD
floor and the Art. 164(4)(a) flat 5% LGD floor — so a ``retail_mortgage`` row
leaves them only when it is secured on commercial property and on nothing
residential. The CRM recognises a house on three routes that the hierarchy's
drawn-basis property values (``residential_collateral_value`` and its uncapped
twin) and its keep-first ``property_type`` do not follow. Each leg below is a real
house-secured exposure whose ``property_type`` reads ``commercial`` (a shop is the
first property the hierarchy sees) and whose residential values are 0; each must
keep the residential floors:

    ref         | the house reaches the loan through ...
    ------------|------------------------------------------------------------------
    GRD-LNK-L   | the M:N ``collateral_links`` table (the collateral row's own
                | beneficiary is the sibling loan GRD-LNK-L0)
    GRD-NEST-L  | a pledge at the ROOT facility of a facility -> sub-facility ->
                | loan chain (the CRM cascades facility collateral over every
                | ancestor; the hierarchy's values use the immediate parent only)
    GRD-SYN-L   | a ``collateral_type`` synonym (``residential_property``) the CRM
                | recognises as real estate (``REAL_ESTATE_COLLATERAL_TYPES``)

``GRD-CTL-L`` is the control that MUST move: a shop and nothing else, so it is
PS1/26 Art. 147(5C) other retail on all three floors. Without it every guard could
pass because the change was not active at all.

Every loan is A-IRB retail, GB natural person, 300,000 drawn, PD 0.04%, own LGD 3%
— own estimates below every Basel 3.1 floor, so each floor IS the result.

References:
- PS1/26 Art. 147(5B)/(5C), 154(4A)(b), 163(1)(b)/(c), 164(4)(a)/(c)
- CRR Art. 230-231 (collateral allocation the CRM performs on these routes)
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_LINK_SCHEMA,
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: Must match ``create_full_irb_model_permissions`` or no row routes IRB.
_MODEL_ID: str = "TEST_FULL_IRB"

LN_LINKS: str = "GRD-LNK-L"
LN_LINKS_SIBLING: str = "GRD-LNK-L0"
LN_NESTED: str = "GRD-NEST-L"
LN_SYNONYM: str = "GRD-SYN-L"
LN_CONTROL: str = "GRD-CTL-L"

#: The house-secured guards: each must keep the residential floors.
GUARD_LOANS: tuple[str, ...] = (LN_LINKS, LN_NESTED, LN_SYNONYM)

FAC_ROOT: str = "GRD-NEST-ROOT"
FAC_SUB: str = "GRD-NEST-SUB"

#: Drawn amount of every loan (no undrawn headroom on the loans themselves).
DRAWN: float = 300_000.0
#: A shop against a 300,000 loan: 200,000 less the 40% immovable-property haircut
#: is 120,000 recognised, i.e. 40% cover. The shop is every guard's FIRST property.
SHOP_VALUE: float = 200_000.0
#: Shop-only recognised cover under Basel 3.1 (the figure a guard's CRM credit
#: must EXCEED to show the house is credited too).
SHOP_RECOGNISED_B31: float = SHOP_VALUE * (1.0 - 0.40)
#: Every house. Large enough that its recognised value covers what it reaches.
HOUSE_VALUE: float = 1_000_000.0
#: Own-estimate PD: below both Basel 3.1 retail floors (0.05% / 0.10%).
PD_RETAIL: float = 0.0004
#: Own-estimate LGD below every Basel 3.1 retail LGD floor.
LGD_RETAIL: float = 0.03

_VALUE_DATE: date = date(2020, 1, 1)
_MATURITY: date = date(2031, 12, 31)


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_residential_security_guard_bundle() -> RawDataBundle:
    """Assemble the guard portfolio as a sealed bundle (loader-edge shaped).

    Run it through ``PipelineOrchestrator().run_with_data`` under Basel 3.1 with
    ``PermissionMode.IRB``.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        facilities=_facilities(),
        loans=_loans(),
        facility_mappings=_facility_mappings(),
        ratings=_ratings(),
        model_permissions=create_full_irb_model_permissions(),
        collateral=_collateral(),
        collateral_links=_collateral_links(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------

_COUNTERPARTY_OF: dict[str, str] = {
    LN_LINKS: "GRD-CP-LNK",
    LN_LINKS_SIBLING: "GRD-CP-LNK",
    LN_NESTED: "GRD-CP-NEST",
    LN_SYNONYM: "GRD-CP-SYN",
    LN_CONTROL: "GRD-CP-CTL",
}


def _counterparties() -> pl.DataFrame:
    """One GB natural person per scenario, none defaulted."""
    rows = [
        {
            "counterparty_reference": ref,
            "entity_type": "individual",
            "country_code": "GB",
            "is_natural_person": True,
            "is_managed_as_retail": True,
        }
        for ref in sorted(set(_COUNTERPARTY_OF.values()))
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """One internal PD per obligor — an internal PD plus a permission routes IRB."""
    rows = [
        {
            "rating_reference": f"GRD-RTG-{ref}",
            "counterparty_reference": ref,
            "rating_type": "internal",
            "pd": PD_RETAIL,
            "model_id": _MODEL_ID,
            "rating_date": _VALUE_DATE,
        }
        for ref in sorted(set(_COUNTERPARTY_OF.values()))
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _facilities() -> pl.DataFrame:
    """ROOT -> SUB for the nested scenario; limits equal drawn, so no headroom row moves."""
    rows = [
        _facility(FAC_ROOT, limit=DRAWN),
        _facility(FAC_SUB, limit=DRAWN),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_SCHEMA))


def _facility_mappings() -> pl.DataFrame:
    """ROOT -> SUB (facility) -> GRD-NEST-L (loan)."""
    rows = [
        {
            "parent_facility_reference": FAC_ROOT,
            "child_reference": FAC_SUB,
            "child_type": "facility",
        },
        {"parent_facility_reference": FAC_SUB, "child_reference": LN_NESTED, "child_type": "loan"},
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _loans() -> pl.DataFrame:
    """One drawn term loan per scenario, plus the links scenario's sibling."""
    rows = [_loan(ref) for ref in _COUNTERPARTY_OF]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _collateral() -> pl.DataFrame:
    """A shop FIRST on every guard and on the control; then each guard's house.

    The shop listed first is what makes each guard's keep-first ``property_type``
    read ``commercial``.
    """
    rows = [
        _property("GRD-SHOP-LNK", "loan", LN_LINKS, "real_estate", "commercial", SHOP_VALUE),
        _property("GRD-SHOP-NEST", "loan", LN_NESTED, "real_estate", "commercial", SHOP_VALUE),
        _property("GRD-SHOP-SYN", "loan", LN_SYNONYM, "real_estate", "commercial", SHOP_VALUE),
        _property("GRD-SHOP-CTL", "loan", LN_CONTROL, "real_estate", "commercial", SHOP_VALUE),
        # (a) The house's OWN beneficiary is the sibling; the link table adds LN_LINKS.
        _property(
            "GRD-HOUSE-LNK", "loan", LN_LINKS_SIBLING, "real_estate", "residential", HOUSE_VALUE
        ),
        # (b) Pledged at the ROOT facility, two levels above the loan.
        _property(
            "GRD-HOUSE-NEST", "facility", FAC_ROOT, "real_estate", "residential", HOUSE_VALUE
        ),
        # (c) A recognised real-estate synonym, not the canonical "real_estate".
        _property(
            "GRD-HOUSE-SYN",
            "loan",
            LN_SYNONYM,
            "residential_property",
            "residential",
            HOUSE_VALUE,
        ),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COLLATERAL_SCHEMA))


def _collateral_links() -> pl.DataFrame:
    """The links scenario's house, linked to BOTH loans of its obligor."""
    rows = [
        {
            "collateral_reference": "GRD-HOUSE-LNK",
            "beneficiary_type": "loan",
            "beneficiary_reference": LN_LINKS_SIBLING,
        },
        {
            "collateral_reference": "GRD-HOUSE-LNK",
            "beneficiary_type": "loan",
            "beneficiary_reference": LN_LINKS,
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COLLATERAL_LINK_SCHEMA))


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _facility(reference: str, *, limit: float) -> dict:
    return {
        "facility_reference": reference,
        "product_type": "mortgage",
        "counterparty_reference": _COUNTERPARTY_OF[LN_NESTED],
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "currency": "GBP",
        "limit": limit,
        "committed": True,
        "risk_type": "MR",
        "seniority": "senior",
        "lgd": LGD_RETAIL,
        "has_sufficient_collateral_data": True,
    }


def _loan(loan_reference: str) -> dict:
    """A drawn senior term loan carrying an own LGD estimate (routes A-IRB)."""
    return {
        "loan_reference": loan_reference,
        "counterparty_reference": _COUNTERPARTY_OF[loan_reference],
        "product_type": "term_loan",
        "drawn_amount": DRAWN,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
        "lgd": LGD_RETAIL,
        "has_sufficient_collateral_data": True,
    }


def _property(
    collateral_reference: str,
    beneficiary_type: str,
    beneficiary_reference: str,
    collateral_type: str,
    property_type: str,
    value: float,
) -> dict:
    """A recognised (Art. 199(2)-attested) real-estate pledge."""
    return {
        "collateral_reference": collateral_reference,
        "collateral_type": collateral_type,
        "currency": "GBP",
        "is_eligible_irb_collateral": True,
        "property_type": property_type,
        "market_value": value,
        "property_ltv": DRAWN / value,
        "beneficiary_type": beneficiary_type,
        "beneficiary_reference": beneficiary_reference,
    }
