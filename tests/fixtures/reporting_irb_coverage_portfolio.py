"""
IRB template-coverage portfolio — the Basel 3.1 OF 08.01 class sheets, the
conversion-factor rows and the inflow-only sheet no other registered run reaches.

Pipeline position:
    build_reporting_irb_coverage_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / filing.build_canonical_return

Why it exists (P5.81, LESSONS B5). Measured on the 39 runs registered before it
(2026-11-24), Basel 3.1 OF 08.01 lit only the class sheets 0006, 0010, 0012, 0015,
0017, 0021 and 0023, and sheet 0011 only beside 0012 (``declined-guarantee``,
P1.398 — the PI-02 pairing). No registered corporate had revenue above the PS1/26 Art. 147(4C)(b)(ii) large
-corporate threshold or was a financial sector entity, so OF 09.02 r0048 and
sheet 0022 were dead; no SME was managed as retail, so sheet 0016 and OF 09.02
r0120 were dead; no retail leg was secured by commercial property or owed by an
SME, so sheets 0018-0020 were dead; and no IRB off-balance-sheet item sat in the
10% or 20% Table A1 rows. Every published rule over those cells sat
NOT_EVALUATED, which reads exactly like a clean estate.

Composition — one obligor per target, every amount distinct:

    ref               | obligor                                  | approach | B31 sheet
    ------------------|------------------------------------------|----------|----------
    LN_CORP_AIRB      | corporate, revenue 120m, own LGD         | A-IRB    | 0011
    LN_LARGE          | corporate, revenue 600m (> 440m)         | F-IRB    | 0022
    FAC_LARGE_UCC     | its unconditionally cancellable line     | F-IRB    | 0022 r0031
    LN_FSE            | financial sector entity, revenue 80m     | F-IRB    | 0022
    LN_SME_FIRB       | corporate SME, revenue 20m               | F-IRB    | 0024
    CT_SME_TRADE      | its 20% trade item, part-guaranteed      | F-IRB    | 0024 r0032
      __G_ leg        | -> internally rated institution guarantor| F-IRB    | 0006 r0032
    LN_RET_SME        | SME managed as retail                    | A-IRB    | 0016
    LN_RET_NP         | natural person (the non-SME control)     | A-IRB    | 0017
    LN_RET_SME_CRE    | SME managed as retail, commercial pledge | A-IRB    | 0018
    LN_RET_NP_CRE     | natural person, commercial pledge        | A-IRB    | 0019
    LN_RET_SME_RRE    | SME managed as retail, residential pledge| A-IRB    | 0020

Three placement rules the design keeps, each a measured trap:

- **At most one non-retail A-IRB sheet.** Two A-IRB sheets that both report a
  maturity (c0250) make the Bank's ``boe_b0748`` fail on a correct return
  (publisher issue PI-31); A-IRB non-SME corporate beside F-IRB non-SME corporate
  makes ``boe_b1053``-``b1055`` fail (PI-02). This book holds sheet 0011 ALONE —
  no 0012, no 0009, no 0023 — so it lights 0011 with neither the PI-02 nor the PI-31 break. The
  pairings live in ``reporting_irb_pairings_portfolio``, which is the
  separately-removable half of P5.81.
- **New obligors, never a flipped flag.** ``CP_FSE`` is a new obligor, not
  ``is_financial_sector_entity`` set on the irb-shapes LFSE leg (that would move
  P1.400 capital).
- **The SME retail legs come from the classifier, not from a flag.** Each is a
  corporate below the SME ceiling, managed as retail, with an own-estimate LGD:
  ``classify_exposure_subtypes`` seals ``is_sme`` and
  ``reclassify_corporate_to_retail`` then moves it to retail_other (or
  retail_mortgage where property is pledged), so the SME split the sheets read is
  the one the sealed ledger really carries (LESSONS C11(c)).

The inflow-only sheet. ``GTOR_INST`` is an Art. 201(1)(f) institution with an
internal PD and NO exposure of its own. Its guarantee of the 20% trade item is
beneficial, so the guaranteed leg is substituted onto the institution class:
under Basel 3.1 sheet 0006 and under CRR the C 08.01 institution sheet exist only
because of that inflow — the shape ``d588294`` removed when it correctly declined
the natural-person guarantor. Under Basel 3.1 no other registered run has such a
sheet; under CRR ``irb-mdb`` (P1.366) has had one since, its corporate sheet, fed
by a drawn leg. This one is fed by an OFF-balance-sheet leg — the estate's first
off-balance-sheet leg substituted onto an IRB guarantor's class
(``declined-guarantee``'s recognised guarantee moves its covered part to the SA)
— which is what makes the substitution columns' conversion-factor basis visible
(R0 / R1 in ``tests/acceptance/reporting/test_irb_coverage_legs.py``). The
crossing amount is the guarantor's IRB RWEA, which is non-zero (LESSONS C2).

References:
- PRA PS1/26 Art. 147(4C): financial corporates and large corporates
- PRA PS1/26 Art. 147A(1)(e)/(f); CRR Art. 147(5): retail and SME managed as retail
- PRA PS1/26 Art. 166C(1) with Art. 111(1) Table A1: F-IRB conversion factors
- CRR Art. 201(1)(f), Art. 236: an institution guarantor under the IRB approach
- PRA PS1/26 Annex II: OF 08.01 rows 0031 / 0032 (p.116); OF 09.02 r0048, r0120
- Bank of England publisher issues PI-02 and PI-31
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CONTINGENTS_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: Must match ``create_full_irb_model_permissions``, or no row routes IRB at all.
_MODEL_ID: str = "TEST_FULL_IRB"

CP_CORP_AIRB: str = "IRV-CP-CORP-AIRB"
CP_LARGE: str = "IRV-CP-LARGE"
CP_FSE: str = "IRV-CP-FSE"
CP_SME_FIRB: str = "IRV-CP-SME-FIRB"
GTOR_INST: str = "IRV-CP-GTOR-INST"
CP_RET_SME: str = "IRV-CP-RET-SME"
CP_RET_NP: str = "IRV-CP-RET-NP"
CP_RET_SME_CRE: str = "IRV-CP-RET-SME-CRE"
CP_RET_NP_CRE: str = "IRV-CP-RET-NP-CRE"
CP_RET_SME_RRE: str = "IRV-CP-RET-SME-RRE"

LN_CORP_AIRB: str = "IRV-LN-CORP-AIRB"
LN_LARGE: str = "IRV-LN-LARGE"
LN_FSE: str = "IRV-LN-FSE"
LN_SME_FIRB: str = "IRV-LN-SME-FIRB"
LN_RET_SME: str = "IRV-LN-RET-SME"
LN_RET_NP: str = "IRV-LN-RET-NP"
LN_RET_SME_CRE: str = "IRV-LN-RET-SME-CRE"
LN_RET_NP_CRE: str = "IRV-LN-RET-NP-CRE"
LN_RET_SME_RRE: str = "IRV-LN-RET-SME-RRE"

FAC_LARGE_UCC: str = "IRV-FAC-LARGE-UCC"
CT_SME_TRADE: str = "IRV-CT-SME-TRADE"
GUAR_SME_TRADE: str = "IRV-GUAR-SME-TRADE"

#: Revenues, in GBP. ``REVENUE_LARGE`` is above the PS1/26 Art. 147(4C)(b)(ii)
#: GBP 440m threshold (``large_corporate_revenue_threshold`` in the b31 pack);
#: ``REVENUE_CORP_AIRB`` and ``REVENUE_FSE`` sit between that and the SME ceiling;
#: the SME revenues sit below the SME ceiling in both regimes.
REVENUE_CORP_AIRB: float = 120_000_000.0
REVENUE_LARGE: float = 600_000_000.0
REVENUE_FSE: float = 80_000_000.0
REVENUE_SME_FIRB: float = 20_000_000.0
REVENUE_RET_SME: float = 2_000_000.0

#: The FSE's total assets: far below the large-FSE threshold, so the Art. 153(2)
#: 1.25x correlation multiplier does NOT apply and the leg differs from a plain
#: corporate only in its Art. 147(4C)(b)(i) sub-class.
TOTAL_ASSETS_FSE: float = 2_000_000_000.0

#: Internal PDs. Distinct per obligor; all above the Art. 160(1) floor.
PD_CORP_AIRB: float = 0.0120
PD_LARGE: float = 0.0080
PD_FSE: float = 0.0090
PD_SME_FIRB: float = 0.0200
PD_GTOR_INST: float = 0.0010
PD_RETAIL: float = 0.0300

#: Own-estimate LGDs on the A-IRB legs.
LGD_CORP_AIRB: float = 0.35
LGD_RETAIL_UNSECURED: float = 0.40
LGD_RETAIL_SECURED: float = 0.20

#: Drawn amounts, in GBP — every one distinct, none a multiple of another.
DRAWN_CORP_AIRB: float = 2_300_000.0
DRAWN_LARGE: float = 3_700_000.0
DRAWN_FSE: float = 1_450_000.0
DRAWN_SME_FIRB: float = 1_100_000.0
DRAWN_RET_SME: float = 160_000.0
DRAWN_RET_NP: float = 140_000.0
DRAWN_RET_SME_CRE: float = 270_000.0
DRAWN_RET_NP_CRE: float = 230_000.0
DRAWN_RET_SME_RRE: float = 190_000.0

#: The large corporate's unconditionally cancellable commitment, wholly undrawn:
#: Table A1 row 7, 10% under Basel 3.1 (OF 08.01 row 0031); 0% under CRR
#: Art. 166(8)(a).
LIMIT_LARGE_UCC: float = 1_900_000.0

#: The SME's trade-related issued item (Table A1 20%, OF 08.01 row 0032; the CRR
#: Art. 166(10) medium/low-risk 20%), and the share of it the institution covers.
NOMINAL_SME_TRADE: float = 800_000.0
PCT_COVERED_SME_TRADE: float = 0.60

#: Property pledged behind the three secured retail legs, each at a 60% LTV.
PROPERTY_LTV: float = 0.60

_VALUE_DATE: date = date(2020, 1, 1)
_MATURITY: date = date(2031, 12, 31)  # > both reporting dates (CRR 2025, B31 2027)
_GUARANTEE_MATURITY: date = date(2032, 12, 31)  # outlasts the item: no mismatch haircut

#: The approach each drawn leg must resolve to: (CRR, Basel 3.1). None diverges.
IRB_COVERAGE_EXPECTED_APPROACH: dict[str, tuple[str, str]] = {
    LN_CORP_AIRB: ("advanced_irb", "advanced_irb"),
    LN_LARGE: ("foundation_irb", "foundation_irb"),
    LN_FSE: ("foundation_irb", "foundation_irb"),
    LN_SME_FIRB: ("foundation_irb", "foundation_irb"),
    LN_RET_SME: ("advanced_irb", "advanced_irb"),
    LN_RET_NP: ("advanced_irb", "advanced_irb"),
    LN_RET_SME_CRE: ("advanced_irb", "advanced_irb"),
    LN_RET_NP_CRE: ("advanced_irb", "advanced_irb"),
    LN_RET_SME_RRE: ("advanced_irb", "advanced_irb"),
}


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_irb_coverage_bundle() -> RawDataBundle:
    """Assemble the IRB template-coverage portfolio as a sealed bundle.

    Sealed against the loader edge contracts by ``make_raw_bundle``. Run it
    through ``PipelineOrchestrator().run_with_data`` under either regime with
    ``PermissionMode.IRB``.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        facilities=_facilities(),
        contingents=_contingents(),
        ratings=_ratings(),
        model_permissions=create_full_irb_model_permissions(),
        collateral=_collateral(),
        guarantees=_guarantees(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """One obligor per target sheet, plus the guarantor with no exposure of its own."""
    rows: list[dict] = [
        _corporate(CP_CORP_AIRB, REVENUE_CORP_AIRB),
        _corporate(CP_LARGE, REVENUE_LARGE),
        {
            **_corporate(CP_FSE, REVENUE_FSE),
            # PS1/26 Art. 147(4C)(b)(i): the financial-sector limb of the
            # sub-class, on its own (revenue is below the large threshold).
            "is_financial_sector_entity": True,
            "total_assets": TOTAL_ASSETS_FSE,
        },
        _corporate(CP_SME_FIRB, REVENUE_SME_FIRB),
        {
            "counterparty_reference": GTOR_INST,
            "entity_type": "institution",
            "country_code": "GB",
        },
        # Managed-as-retail SMEs: the classifier moves each to the retail class
        # with ``is_sme`` sealed True (module docstring).
        *(
            {**_corporate(ref, REVENUE_RET_SME), "is_managed_as_retail": True}
            for ref in (CP_RET_SME, CP_RET_SME_CRE, CP_RET_SME_RRE)
        ),
        *(
            {
                "counterparty_reference": ref,
                "entity_type": "individual",
                "country_code": "GB",
                "is_natural_person": True,
                "is_managed_as_retail": True,
            }
            for ref in (CP_RET_NP, CP_RET_NP_CRE)
        ),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """Internal PD ratings — an internal PD plus a matching permission routes IRB."""
    rows: list[dict] = [
        _internal(CP_CORP_AIRB, pd=PD_CORP_AIRB),
        _internal(CP_LARGE, pd=PD_LARGE),
        _internal(CP_FSE, pd=PD_FSE),
        _internal(CP_SME_FIRB, pd=PD_SME_FIRB),
        _internal(GTOR_INST, pd=PD_GTOR_INST),
        *(
            _internal(ref, pd=PD_RETAIL)
            for ref in (CP_RET_SME, CP_RET_NP, CP_RET_SME_CRE, CP_RET_NP_CRE, CP_RET_SME_RRE)
        ),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans() -> pl.DataFrame:
    """The drawn legs. An own-estimate LGD is what makes a leg A-IRB."""
    rows: list[dict] = [
        _loan(LN_CORP_AIRB, CP_CORP_AIRB, DRAWN_CORP_AIRB, lgd=LGD_CORP_AIRB),
        _loan(LN_LARGE, CP_LARGE, DRAWN_LARGE),
        _loan(LN_FSE, CP_FSE, DRAWN_FSE),
        _loan(LN_SME_FIRB, CP_SME_FIRB, DRAWN_SME_FIRB),
        _loan(LN_RET_SME, CP_RET_SME, DRAWN_RET_SME, lgd=LGD_RETAIL_UNSECURED),
        _loan(LN_RET_NP, CP_RET_NP, DRAWN_RET_NP, lgd=LGD_RETAIL_UNSECURED),
        _loan(LN_RET_SME_CRE, CP_RET_SME_CRE, DRAWN_RET_SME_CRE, lgd=LGD_RETAIL_SECURED),
        _loan(LN_RET_NP_CRE, CP_RET_NP_CRE, DRAWN_RET_NP_CRE, lgd=LGD_RETAIL_SECURED),
        _loan(LN_RET_SME_RRE, CP_RET_SME_RRE, DRAWN_RET_SME_RRE, lgd=LGD_RETAIL_SECURED),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _facilities() -> pl.DataFrame:
    """The large corporate's unconditionally cancellable commitment, wholly undrawn."""
    rows: list[dict] = [
        {
            "facility_reference": FAC_LARGE_UCC,
            "counterparty_reference": CP_LARGE,
            "product_type": "revolving_credit_facility",
            "limit": LIMIT_LARGE_UCC,
            "risk_type": "LR",
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "committed": True,
            "is_revolving": True,
        }
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_SCHEMA))


def _contingents() -> pl.DataFrame:
    """The SME's trade-related issued item — the 20% row, and the guaranteed leg."""
    rows: list[dict] = [
        {
            "contingent_reference": CT_SME_TRADE,
            "counterparty_reference": CP_SME_FIRB,
            "product_type": "trade_lc",
            "nominal_amount": NOMINAL_SME_TRADE,
            "risk_type": "MLR",
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "bs_type": "OFB",
        }
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(CONTINGENTS_SCHEMA))


def _guarantees() -> pl.DataFrame:
    """The institution's partial guarantee of the SME's trade item."""
    rows: list[dict] = [
        {
            "guarantee_reference": GUAR_SME_TRADE,
            "guarantor": GTOR_INST,
            "currency": "GBP",
            "maturity_date": _GUARANTEE_MATURITY,
            "amount_covered": NOMINAL_SME_TRADE * PCT_COVERED_SME_TRADE,
            "percentage_covered": PCT_COVERED_SME_TRADE,
            "beneficiary_type": "contingent",
            "beneficiary_reference": CT_SME_TRADE,
            "protection_type": "guarantee",
            "includes_restructuring": True,
            "guarantor_seniority": "senior",
            "is_unilaterally_cancellable": False,
            "is_unilaterally_changeable": False,
        }
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(GUARANTEE_SCHEMA))


def _collateral() -> pl.DataFrame:
    """The properties behind the three secured retail legs, each at a 60% LTV.

    A linked property row is what sets ``is_mortgage`` (and, for the managed-as
    -retail SMEs, the retail_mortgage reclassification); its ``property_type`` is
    what puts a leg on a commercial or a residential sheet.
    """
    return pl.DataFrame(
        [
            _property("IRV-COLL-SME-CRE", LN_RET_SME_CRE, DRAWN_RET_SME_CRE, "commercial"),
            _property("IRV-COLL-NP-CRE", LN_RET_NP_CRE, DRAWN_RET_NP_CRE, "commercial"),
            _property("IRV-COLL-SME-RRE", LN_RET_SME_RRE, DRAWN_RET_SME_RRE, "residential"),
        ]
    )


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _corporate(counterparty_reference: str, revenue: float) -> dict:
    """A GB corporate counterparty row of the given annual revenue."""
    return {
        "counterparty_reference": counterparty_reference,
        "entity_type": "corporate",
        "country_code": "GB",
        "annual_revenue": revenue,
    }


def _loan(
    loan_reference: str,
    counterparty_reference: str,
    drawn_amount: float,
    *,
    lgd: float | None = None,
) -> dict:
    """One drawn term loan. ``lgd`` set means an own estimate, so A-IRB."""
    row: dict = {
        "loan_reference": loan_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "term_loan",
        "drawn_amount": drawn_amount,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
        "has_sufficient_collateral_data": lgd is not None,
    }
    if lgd is not None:
        row["lgd"] = lgd
    return row


def _property(reference: str, loan_reference: str, drawn: float, property_type: str) -> dict:
    """An eligible GBP property pledged to one loan at :data:`PROPERTY_LTV`."""
    return {
        "collateral_reference": reference,
        "collateral_type": "real_estate",
        "currency": "GBP",
        "is_eligible_irb_collateral": True,
        "property_type": property_type,
        "market_value": round(drawn / PROPERTY_LTV, 2),
        "property_ltv": PROPERTY_LTV,
        "beneficiary_type": "loan",
        "beneficiary_reference": loan_reference,
    }


def _internal(counterparty_reference: str, *, pd: float) -> dict:
    """Internal model rating row (PD + model_id — the IRB routing pair)."""
    return {
        "rating_reference": f"IRV-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "pd": pd,
        "model_id": _MODEL_ID,
        "rating_date": _VALUE_DATE,
    }
