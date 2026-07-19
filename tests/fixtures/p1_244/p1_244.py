"""
P1.244 — QRRE assignment gates (CRR Art. 154(4)(a)-(b) / PS1/26 Art. 147(5A)(a)-(b)).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (engine/stages/classify/subtypes.py + engine/stages/hierarchy plumbing)

Key responsibilities:
- Provide in-memory ``RawDataBundle`` builders (HierarchyResolver ->
  ExposureClassifier) that exercise the three Art. 147(5A) QRRE gates beyond
  the pre-existing revolving + aggregate-limit checks:

    (a) individuals — a natural-person control that becomes QRRE.
    (b) unsecured — a facility flagged ``is_secured=True`` is demoted from QRRE
        to RETAIL_OTHER (its unsecured control stays QRRE). Exercises the
        end-to-end ``is_secured`` facility->exposure coupling added in hierarchy.
    (b) unconditionally cancellable "to the extent undrawn" — an undrawn
        revolving line whose ``risk_type`` is NOT the low-risk / unconditionally-
        cancellable (LR) bucket is demoted; its LR control stays QRRE.

  Every ``build_p1_244_raw_bundle`` facility is fully undrawn (no mapped loans),
  so the demoted / control rows are all synthetic ``facility_undrawn`` rows
  (coupling Site A, ``facility_undrawn.py``) and the drawn-based "total amount
  owed" is 0 — mirroring the P1.191 pattern.

- Provide ``build_p1_244_drawn_leg_raw_bundle``: the ``is_secured`` attestation
  is coupled onto BOTH legs, so it also pins Site B — the parent facility's
  ``is_secured`` coalesced onto a DRAWN loan row (``enrich._join_facility_qrre_columns``).
  Each line is fully drawn (drawn == limit), so no synthetic undrawn row is
  emitted and the drawn loan is the sole QRRE candidate.

- Provide a direct ``classify_exposure_subtypes`` input frame for the
  individuals gate, whose demotion is only reachable when a RETAIL_OTHER row is
  NOT a natural person — a state the entity-type map cannot produce end-to-end
  (all three RETAIL_OTHER entity aliases ARE natural persons), so it is asserted
  at the transform boundary.

References:
- CRR Art. 154(4)(a)-(c) / PRA PS1/26 Art. 147(5A)(a)-(c): QRRE assignment.
- CRR Art. 111(1) / PS1/26 Table A1 Row 7: LR = unconditionally cancellable CCF.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

    from rwa_calc.contracts.bundles import RawDataBundle

# ---------------------------------------------------------------------------
# Scenario identity constants
# ---------------------------------------------------------------------------

CP_INDIVIDUAL: str = "P1244_CP_IND"

#: The QRRE-eligible control facility (individual, unsecured, LR-cancellable).
FAC_CONTROL: str = "P1244_FAC_CONTROL"
#: Secured revolving retail facility — demoted by the unsecured gate.
FAC_SECURED: str = "P1244_FAC_SECURED"
#: Undrawn revolving line with a non-LR (MR) risk_type — demoted by the
#: unconditionally-cancellable gate.
FAC_NOT_CANCELLABLE: str = "P1244_FAC_MR"

#: Facility_undrawn exposure references carry the "_UNDRAWN" suffix.
EXP_CONTROL: str = FAC_CONTROL + "_UNDRAWN"
EXP_SECURED: str = FAC_SECURED + "_UNDRAWN"
EXP_NOT_CANCELLABLE: str = FAC_NOT_CANCELLABLE + "_UNDRAWN"

#: Drawn-leg (Site B) facilities: each carries one fully-drawn revolving loan.
FAC_DRAWN_SECURED: str = "P1244_FAC_DRAWN_SECURED"
FAC_DRAWN_CONTROL: str = "P1244_FAC_DRAWN_CONTROL"

#: Drawn-leg loan references — a loan's exposure_reference == its loan_reference.
LOAN_DRAWN_SECURED: str = "P1244_LOAN_DRAWN_SECURED"
LOAN_DRAWN_CONTROL: str = "P1244_LOAN_DRAWN_CONTROL"

#: Facility limit — below both the CRR (GBP 87,320) and B31 (GBP 90,000) QRRE
#: per-individual aggregate limits so only the (a)/(b) gates discriminate. Kept
#: on distinct obligors so the aggregate per individual is a single limit.
FACILITY_LIMIT: float = 50_000.0

VALUE_DATE: date = date(2027, 1, 4)
MATURITY_DATE: date = date(2030, 1, 4)


# ---------------------------------------------------------------------------
# Raw-bundle builders (HierarchyResolver -> ExposureClassifier end-to-end)
# ---------------------------------------------------------------------------

_CP_SCHEMA: dict[str, PolarsDataType] = {
    "counterparty_reference": pl.String,
    "counterparty_name": pl.String,
    "entity_type": pl.String,
    "country_code": pl.String,
    "default_status": pl.Boolean,
    "apply_fi_scalar": pl.Boolean,
    "is_managed_as_retail": pl.Boolean,
    "is_natural_person": pl.Boolean,
    "annual_revenue": pl.Float64,
    "total_assets": pl.Float64,
}

_FAC_SCHEMA: dict[str, PolarsDataType] = {
    "facility_reference": pl.String,
    "counterparty_reference": pl.String,
    "currency": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
    "limit": pl.Float64,
    "committed": pl.Boolean,
    "is_revolving": pl.Boolean,
    "is_qrre_transactor": pl.Boolean,
    "is_secured": pl.Boolean,
    "seniority": pl.String,
    "risk_type": pl.String,
    "product_type": pl.String,
    "book_code": pl.String,
}


def _individual_cp() -> pl.LazyFrame:
    """One natural-person retail obligor per facility (distinct obligors keep the
    Art. 147(5A)(c) per-individual aggregate to a single 50,000 limit)."""
    refs = [f"{CP_INDIVIDUAL}_{n}" for n in range(3)]
    return pl.LazyFrame(
        {
            "counterparty_reference": refs,
            "counterparty_name": [f"P1.244 Individual {n}" for n in range(3)],
            "entity_type": ["individual"] * 3,
            "country_code": ["GB"] * 3,
            "default_status": [False] * 3,
            "apply_fi_scalar": [False] * 3,
            # Managed as retail so the Art. 123A(1)(b)(iii) pool-management limb
            # passes and qualifies_as_retail is driven only by the (zero) owed
            # amount — isolating the QRRE (a)/(b) gates under test.
            "is_managed_as_retail": [True] * 3,
            "is_natural_person": [True] * 3,
            "annual_revenue": [0.0] * 3,
            "total_assets": [0.0] * 3,
        },
        schema=_CP_SCHEMA,
    )


def _facility(
    facility_reference: str,
    counterparty_reference: str,
    *,
    is_secured: bool,
    risk_type: str,
) -> dict[str, object]:
    return {
        "facility_reference": facility_reference,
        "counterparty_reference": counterparty_reference,
        "currency": "GBP",
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
        "limit": FACILITY_LIMIT,
        "committed": True,
        "is_revolving": True,
        "is_qrre_transactor": False,
        "is_secured": is_secured,
        "seniority": "senior",
        "risk_type": risk_type,
        "product_type": "revolving_credit_facility",
        "book_code": "BANKING",
    }


def _facilities() -> pl.LazyFrame:
    refs = [f"{CP_INDIVIDUAL}_{n}" for n in range(3)]
    rows = [
        # Control — unsecured, LR (unconditionally cancellable) -> RETAIL_QRRE.
        _facility(FAC_CONTROL, refs[0], is_secured=False, risk_type="LR"),
        # Secured — LR so ONLY the unsecured gate discriminates -> RETAIL_OTHER.
        _facility(FAC_SECURED, refs[1], is_secured=True, risk_type="LR"),
        # Not unconditionally cancellable — unsecured but MR (committed medium
        # risk) on an undrawn line -> RETAIL_OTHER.
        _facility(FAC_NOT_CANCELLABLE, refs[2], is_secured=False, risk_type="MR"),
    ]
    return pl.LazyFrame(rows, schema=_FAC_SCHEMA)


_EMPTY_LOANS = pl.LazyFrame(
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
        "risk_type": pl.String,
    }
)

_EMPTY_LENDING_MAPPINGS = pl.LazyFrame(
    schema={
        "parent_counterparty_reference": pl.String,
        "child_counterparty_reference": pl.String,
    }
)

_EMPTY_FACILITY_MAPPINGS = pl.LazyFrame(
    schema={
        "parent_facility_reference": pl.String,
        "child_reference": pl.String,
        "child_type": pl.String,
    }
)


def build_p1_244_raw_bundle() -> RawDataBundle:
    """Return the P1.244 RawDataBundle: control + secured + non-cancellable lines."""
    return make_raw_bundle(
        facilities=_facilities(),
        loans=_EMPTY_LOANS,
        counterparties=_individual_cp(),
        facility_mappings=_EMPTY_FACILITY_MAPPINGS,
        lending_mappings=_EMPTY_LENDING_MAPPINGS,
    )


def build_p1_244_control_only_raw_bundle() -> RawDataBundle:
    """Return a RawDataBundle with ONLY the QRRE-eligible control facility.

    Every (a)/(b) gate passes, so no row is gate-demoted and the CLS010 warning
    must NOT fire — the negative control for ``collect_qrre_gate_demotion_warnings``.
    """
    refs = [f"{CP_INDIVIDUAL}_{n}" for n in range(3)]
    control_only = pl.LazyFrame(
        [_facility(FAC_CONTROL, refs[0], is_secured=False, risk_type="LR")],
        schema=_FAC_SCHEMA,
    )
    return make_raw_bundle(
        facilities=control_only,
        loans=_EMPTY_LOANS,
        counterparties=_individual_cp(),
        facility_mappings=_EMPTY_FACILITY_MAPPINGS,
        lending_mappings=_EMPTY_LENDING_MAPPINGS,
    )


# ---------------------------------------------------------------------------
# Drawn-leg builder (Site B: enrich.py facility->loan is_secured inheritance)
# ---------------------------------------------------------------------------

_LOAN_SCHEMA: dict[str, PolarsDataType] = {
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
    "risk_type": pl.String,
}


def _drawn_loan(loan_reference: str, counterparty_reference: str) -> dict[str, object]:
    """One fully-drawn revolving retail loan (drawn == facility limit).

    The drawn balance equals the facility limit so the parent facility has zero
    undrawn headroom and emits NO synthetic facility_undrawn row — the loan is
    then the sole QRRE candidate, keeping the Art. 147(5A)(c) per-individual
    aggregate at a single 50,000 limit (below both regime caps). ``risk_type``
    is nulled for drawn loans by ``unify._coerce_loans_to_unified``; with
    ``undrawn_amount`` forced to 0, the cancellability limb is trivially
    satisfied, isolating the ``is_secured`` gate on the DRAWN leg.
    """
    return {
        "loan_reference": loan_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "revolving_credit_facility",
        "book_code": "BANKING",
        "currency": "GBP",
        "drawn_amount": FACILITY_LIMIT,
        "lgd": 0.5,
        "seniority": "senior",
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
        "risk_type": "LR",
    }


def _drawn_facility_mappings() -> pl.LazyFrame:
    """Map each drawn loan to its parent facility (child_type='loan')."""
    return pl.LazyFrame(
        {
            "parent_facility_reference": [FAC_DRAWN_SECURED, FAC_DRAWN_CONTROL],
            "child_reference": [LOAN_DRAWN_SECURED, LOAN_DRAWN_CONTROL],
            "child_type": ["loan", "loan"],
        },
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        },
    )


def build_p1_244_drawn_leg_raw_bundle() -> RawDataBundle:
    """Return the P1.244 drawn-leg RawDataBundle exercising coupling Site B.

    The facility ``is_secured`` attestation is coalesced onto the DRAWN loan
    row by ``enrich._join_facility_qrre_columns`` (Site B), not only onto the
    synthetic facility_undrawn row (Site A). Each individual revolving line is
    fully drawn (drawn == limit), so:

    - FAC_DRAWN_SECURED (is_secured=True)  -> LOAN_DRAWN_SECURED demotes to RETAIL_OTHER.
    - FAC_DRAWN_CONTROL (is_secured=False) -> LOAN_DRAWN_CONTROL stays RETAIL_QRRE.
    """
    refs = [f"{CP_INDIVIDUAL}_{n}" for n in range(3)]
    facilities = pl.LazyFrame(
        [
            _facility(FAC_DRAWN_SECURED, refs[0], is_secured=True, risk_type="LR"),
            _facility(FAC_DRAWN_CONTROL, refs[1], is_secured=False, risk_type="LR"),
        ],
        schema=_FAC_SCHEMA,
    )
    loans = pl.LazyFrame(
        [
            _drawn_loan(LOAN_DRAWN_SECURED, refs[0]),
            _drawn_loan(LOAN_DRAWN_CONTROL, refs[1]),
        ],
        schema=_LOAN_SCHEMA,
    )
    return make_raw_bundle(
        facilities=facilities,
        loans=loans,
        counterparties=_individual_cp(),
        facility_mappings=_drawn_facility_mappings(),
        lending_mappings=_EMPTY_LENDING_MAPPINGS,
    )


# ---------------------------------------------------------------------------
# Direct classify_exposure_subtypes input frame (individuals gate)
# ---------------------------------------------------------------------------

_SUBTYPES_SCHEMA: dict[str, PolarsDataType] = {
    "exposure_reference": pl.String,
    "counterparty_reference": pl.String,
    "exposure_class": pl.String,
    "exposure_class_irb": pl.String,
    "qualifies_as_retail": pl.Boolean,
    "is_revolving": pl.Boolean,
    "is_secured": pl.Boolean,
    "risk_type": pl.String,
    "undrawn_amount": pl.Float64,
    "facility_limit": pl.Float64,
    "is_mortgage": pl.Boolean,
    "is_adc": pl.Boolean,
    "is_hvcre": pl.Boolean,
    "cp_entity_type": pl.String,
    "cp_is_natural_person": pl.Boolean,
    "cp_is_financial_sector_entity": pl.Boolean,
    "cp_total_assets": pl.Float64,
    "cp_apply_fi_scalar": pl.Boolean,
    "sme_size_metric_gbp": pl.Float64,
    "sme_size_source": pl.String,
}


def make_subtypes_frame(
    *,
    cp_entity_type: str,
    cp_is_natural_person: bool,
) -> pl.LazyFrame:
    """Return a one-row classify_exposure_subtypes input frame.

    The row is a qualifying, revolving, fully-drawn (no undrawn commitment),
    unsecured RETAIL_OTHER exposure — a QRRE candidate on every axis except the
    individuals gate, which is driven by the two counterparty arguments. A
    fully-drawn row (undrawn_amount=0) satisfies the cancellability limb
    trivially, isolating the individuals gate.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["P1244_SUBTYPES"],
            "counterparty_reference": ["P1244_SUBTYPES_CP"],
            "exposure_class": ["retail_other"],
            "exposure_class_irb": ["retail_other"],
            "qualifies_as_retail": [True],
            "is_revolving": [True],
            "is_secured": [False],
            "risk_type": ["FR"],
            "undrawn_amount": [0.0],
            "facility_limit": [FACILITY_LIMIT],
            "is_mortgage": [False],
            "is_adc": [False],
            "is_hvcre": [False],
            "cp_entity_type": [cp_entity_type],
            "cp_is_natural_person": [cp_is_natural_person],
            "cp_is_financial_sector_entity": [False],
            "cp_total_assets": [None],
            "cp_apply_fi_scalar": [False],
            "sme_size_metric_gbp": [None],
            "sme_size_source": [None],
        },
        schema=_SUBTYPES_SCHEMA,
    )
