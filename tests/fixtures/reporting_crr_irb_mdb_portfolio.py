"""
CRR IRB multilateral-development-bank reporting portfolio — the Art. 147(4)(c) class axis.

Pipeline position:
    build_reporting_crr_irb_mdb_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Why this portfolio exists (P1.366): CRR Art. 147(4)(c) puts every multilateral
development bank "which [is] not assigned a 0 % risk weight under Article 117" in
the IRB INSTITUTIONS class, and the CRR IRB templates are laid out on the
Art. 147(2) classes (COREP Annex II §3.3.2; C 09.02 row 0020 "Institutions —
Point (b) of Article 147(2) CRR"; C 02.00 rows 0270 / 0330). The engine keeps such
an MDB's ``exposure_class`` at its Art. 112(1)(d) SA label ``mdb`` on the IRB leg,
and until P1.366 the reporting projection published that label, so the leg:

- opened a C 08.01-08.05 ``mdb`` sheet no published sheet code addresses;
- was counted in C 09.02 row 0150 but not row 0020 (``v6052_m``, ERROR, failed by
  exactly the MDB exposure);
- was in C 02.00 rows 0250 / 0310 but in neither institutions of-which row
  (0270 / 0330) — the ``_warn_if_a_breakdown_strands`` residual;
- vanished from Pillar 3 CR6 and missed CR7 row 3.

No registered portfolio held a CRR IRB MDB, so every gate was structurally blind
to it (LESSONS B5). This book is the smallest one that can tell the fix from its
absence, in CRR only — under PS1/26 Art. 147(3)(f) + 147A(1)(a) every MDB is
Standardised, so there is no Basel 3.1 case (the Basel 3.1 arm of the same bundle
is a negative control in the acceptance test, and is not registered).

Composition (every leg drawn, GBP, one country — GB — so C 09.02's TOTAL and GB
sheets partition the same legs):

    ref             | obligor              | approach | Art. 147 class | role
    ----------------|----------------------|----------|----------------|-----------------
    LN_MDB_FIRB     | non-named MDB        | F-IRB    | institution    | MOVES (r0270)
    LN_MDB_AIRB     | non-named MDB        | A-IRB    | institution    | MOVES (r0330)
    LN_INST         | institution          | F-IRB    | institution    | SURVIVES (control)
    LN_MDB_GTD      | non-named MDB, 40%   | F-IRB    | institution    | origin MOVES;
                    | covered by an IRB    |          |                | __G_ post basis
                    | corporate guarantor  |          |                | stays CORPORATE
    LN_MDB_SA       | non-named MDB (CQS2) | SA       | mdb (Art. 112) | SA control

Why each leg is load-bearing:

- ``LN_INST`` is the two-leg control (LESSONS B5): row 0020 / the institution
  sheet hold it before AND after the fix, so a fix that zeroed the row is
  distinguishable from one that moved the MDBs into it.
- ``LN_MDB_AIRB`` is mandatory, not optional: C 02.00 row 0330 (A-IRB
  institutions) is a named target and its stranding (row 0310 > breakdown) was
  measured. It carries an own-estimate LGD, which is what routes A-IRB — CRR
  full IRB grants institutions A-IRB.
- ``LN_MDB_GTD`` is the guard on the POST twin: its 600,000 slice is guaranteed by
  a corporate with an internal PD below the obligor's, so the guarantor is IRB
  (Art. 161 / 236 parameter substitution), the leg stays on F-IRB, and its
  ``reporting_class`` is the guarantor's ``corporate``. A relabel keyed on the
  approach alone would wrongly move that slice to ``institution``. Its ``__REM``
  leg stays the obligor's and must relabel.
- ``LN_MDB_SA`` (external CQS 2, no internal PD -> SA) pins the gate: on SA ``mdb``
  is the correct Art. 112(1)(d) class (C 07.00 sheet, C 09.01 row 0040) and must
  not move.

Deliberately OUT of scope: a NAMED (Art. 117(2)) MDB. Under full-IRB permissions it
routes SA (CLS006, no ``mdb``-class permission); reached IRB through an explicit
``mdb``-class permission it keeps ``exposure_class_irb`` ``mdb`` and would still
open a stray sheet — a separate engine gap (``sync_irb_exposure_class`` overwrites
its IRB class to ``mdb`` rather than the Art. 147(3)(b) central-government class),
pinned at the projection level in
``tests/unit/engine/aggregator/test_p1_366_mdb_reporting_class.py``.

References:
- CRR Art. 147(3)(b), 147(4)(c); CRR Art. 117(2)
- CRR Art. 161 / 236: IRB parameter substitution by an IRB guarantor
- COREP Annex II §3.3.2, C 09.02 row 0020, C 02.00 rows 0250-0330
- EBA v3.0: v6052_m, v0420_m / v0421_m / v0423_m, v4246_i, v4251_i
- PS1/26 Art. 147(3)(f), 147A(1)(a): no Basel 3.1 case
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: Must match ``create_full_irb_model_permissions`` (F-IRB + A-IRB for every IRB
#: class), or no row routes IRB at all.
_MODEL_ID: str = "TEST_FULL_IRB"

CP_MDB_FIRB: str = "MDB-CP-MDB-FIRB"
CP_MDB_AIRB: str = "MDB-CP-MDB-AIRB"
CP_INST: str = "MDB-CP-INST"
CP_MDB_GTD: str = "MDB-CP-MDB-GTD"
CP_GTOR: str = "MDB-CP-GTOR-CORP"
CP_MDB_SA: str = "MDB-CP-MDB-SA"

LN_MDB_FIRB: str = "MDB-LN-MDB-FIRB"
LN_MDB_AIRB: str = "MDB-LN-MDB-AIRB"
LN_INST: str = "MDB-LN-INST"
LN_MDB_GTD: str = "MDB-LN-MDB-GTD"
LN_MDB_SA: str = "MDB-LN-MDB-SA"

GUAR_MDB_GTD: str = "MDB-GUAR-MDB-GTD"

#: The two physical legs the CRM stage splits ``LN_MDB_GTD`` into.
LN_MDB_GTD_GUARANTEED: str = f"{LN_MDB_GTD}__G_{CP_GTOR}"
LN_MDB_GTD_RETAINED: str = f"{LN_MDB_GTD}__REM"

#: Drawn amounts, GBP. Distinct per leg so a mis-placed leg is identifiable from a
#: single cell value without a reverse lookup.
DRAWN_MDB_FIRB: float = 1_000_000.0
DRAWN_MDB_AIRB: float = 2_000_000.0
DRAWN_INST: float = 3_000_000.0
DRAWN_MDB_GTD: float = 1_500_000.0
DRAWN_MDB_SA: float = 700_000.0

#: The covered slice of ``LN_MDB_GTD`` (40%).
GUARANTEED_MDB_GTD: float = 600_000.0

#: Internal PDs. The guaranteed MDB's PD is well above the guarantor's, so the IRB
#: parameter substitution is beneficial and actually applied (a declined guarantee
#: moves neither class nor approach — ``aggregator._beneficial_gate``).
PD_MDB: float = 0.005
PD_INST: float = 0.005
PD_MDB_GTD: float = 0.02
PD_GTOR: float = 0.001

#: Own-estimate LGD of the A-IRB MDB leg — the input that routes it A-IRB.
LGD_MDB_AIRB: float = 0.30

#: External CQS of the SA MDB control (Art. 117(1) -> institution-like ladder).
CQS_MDB_SA: int = 2

#: Every IRB leg whose Art. 147 reporting class is INSTITUTIONS on the ORIGIN
#: basis, with its approach — the population C 08.01's institution sheet, C 09.02
#: row 0020 cols 0010-0070 and C 02.00 rows 0270 / 0330 must hold under CRR.
CRR_INSTITUTION_ORIGIN_LEGS: dict[str, str] = {
    LN_MDB_FIRB: "foundation_irb",
    LN_MDB_AIRB: "advanced_irb",
    LN_INST: "foundation_irb",
    LN_MDB_GTD_GUARANTEED: "foundation_irb",
    LN_MDB_GTD_RETAINED: "foundation_irb",
}

#: The MDB subset of the above — the legs the fix moves.
CRR_IRB_MDB_LEGS: frozenset[str] = frozenset(
    {LN_MDB_FIRB, LN_MDB_AIRB, LN_MDB_GTD_GUARANTEED, LN_MDB_GTD_RETAINED}
)

_VALUE_DATE: date = date(2020, 1, 1)
#: Beyond every reporting date the gate uses (CRR 2025-06-30 prior, 2025-12-31).
_MATURITY: date = date(2031, 12, 31)
#: Guarantee maturity matches the loan exactly — no Art. 239(3) mismatch haircut.
_GUARANTEE_MATURITY: date = _MATURITY
#: Comfortably >= 1y — Art. 237(2)(a) original-maturity eligibility satisfied.
_ORIGINAL_MATURITY_YEARS: float = 10.0


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_crr_irb_mdb_bundle() -> RawDataBundle:
    """Assemble the CRR IRB MDB portfolio as a sealed bundle.

    Sealed against the loader edge contracts by ``make_raw_bundle``, so it is
    shape-identical to a parquet-loaded production bundle. Run it through
    ``PipelineOrchestrator().run_with_data`` with ``PermissionMode.IRB``: every IRB
    obligor carries an internal PD and the matching full-IRB ``model_permissions``
    row; the SA control carries an external rating only.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        ratings=_ratings(),
        guarantees=_guarantees(),
        model_permissions=create_full_irb_model_permissions(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """Four non-named MDBs, one institution and one corporate guarantor, all GB.

    ``entity_type="mdb"`` is the generic, CQS-rated MDB — not one of the Art. 117(2)
    named MDBs (``mdb_named``) — which is what makes Art. 147(4)(c) apply. Separate
    legal entities because PD is an obligor attribute. The guarantor is above the
    SME ceiling so no supporting factor perturbs the substituted leg.
    """
    rows: list[dict] = [
        {"counterparty_reference": CP_MDB_FIRB, "entity_type": "mdb", "country_code": "GB"},
        {"counterparty_reference": CP_MDB_AIRB, "entity_type": "mdb", "country_code": "GB"},
        {"counterparty_reference": CP_INST, "entity_type": "institution", "country_code": "GB"},
        {"counterparty_reference": CP_MDB_GTD, "entity_type": "mdb", "country_code": "GB"},
        {
            "counterparty_reference": CP_GTOR,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 400_000_000.0,
        },
        {"counterparty_reference": CP_MDB_SA, "entity_type": "mdb", "country_code": "GB"},
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """Internal PDs for the IRB obligors and the guarantor; an external CQS for the
    SA control (no internal PD, so it cannot route IRB).

    The guarantor's internal PD is what makes it an IRB guarantor for an IRB
    beneficiary (Art. 201(2) internal-rating limb) — the post-twin guard.
    """
    rows: list[dict] = [
        _internal(CP_MDB_FIRB, pd=PD_MDB),
        _internal(CP_MDB_AIRB, pd=PD_MDB),
        _internal(CP_INST, pd=PD_INST),
        _internal(CP_MDB_GTD, pd=PD_MDB_GTD),
        _internal(CP_GTOR, pd=PD_GTOR),
        _external(CP_MDB_SA, cqs=CQS_MDB_SA),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans() -> pl.DataFrame:
    """One drawn senior term loan per obligor. EAD = drawn_amount.

    Only ``LN_MDB_AIRB`` carries an own-estimate LGD (with
    ``has_sufficient_collateral_data``), which is what routes it A-IRB; every other
    IRB leg resolves F-IRB on the Art. 161 supervisory LGD.
    """
    rows: list[dict] = [
        _loan(LN_MDB_FIRB, CP_MDB_FIRB, DRAWN_MDB_FIRB),
        _loan(
            LN_MDB_AIRB,
            CP_MDB_AIRB,
            DRAWN_MDB_AIRB,
            lgd=LGD_MDB_AIRB,
            has_sufficient_collateral_data=True,
        ),
        _loan(LN_INST, CP_INST, DRAWN_INST),
        _loan(LN_MDB_GTD, CP_MDB_GTD, DRAWN_MDB_GTD),
        _loan(LN_MDB_SA, CP_MDB_SA, DRAWN_MDB_SA),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _guarantees() -> pl.DataFrame:
    """The one partial guarantee: 40% of ``LN_MDB_GTD`` by the IRB corporate.

    Matched currency and maturity, restructuring included and neither unilateral
    flag set, so no eligibility gate or mismatch haircut zeroes the cover.
    """
    rows: list[dict] = [
        {
            "guarantee_reference": GUAR_MDB_GTD,
            "guarantor": CP_GTOR,
            "currency": "GBP",
            "maturity_date": _GUARANTEE_MATURITY,
            "amount_covered": GUARANTEED_MDB_GTD,
            "percentage_covered": GUARANTEED_MDB_GTD / DRAWN_MDB_GTD,
            "beneficiary_type": "loan",
            "beneficiary_reference": LN_MDB_GTD,
            "protection_type": "guarantee",
            "includes_restructuring": True,
            "original_maturity_years": _ORIGINAL_MATURITY_YEARS,
            "guarantor_seniority": "senior",
            "is_unilaterally_cancellable": False,
            "is_unilaterally_changeable": False,
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(GUARANTEE_SCHEMA))


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _loan(
    loan_reference: str,
    counterparty_reference: str,
    drawn_amount: float,
    *,
    lgd: float | None = None,
    has_sufficient_collateral_data: bool = False,
) -> dict:
    """Build one plain drawn senior term-loan row (unset columns take schema defaults)."""
    row: dict = {
        "loan_reference": loan_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "term_loan",
        "drawn_amount": drawn_amount,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
        "has_sufficient_collateral_data": has_sufficient_collateral_data,
    }
    if lgd is not None:
        row["lgd"] = lgd
    return row


def _internal(counterparty_reference: str, *, pd: float) -> dict:
    """Internal model rating row (PD + model_id — the IRB routing pair)."""
    return {
        "rating_reference": f"MDB-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "pd": pd,
        "model_id": _MODEL_ID,
        "rating_date": _VALUE_DATE,
    }


def _external(counterparty_reference: str, *, cqs: int) -> dict:
    """External ECAI rating row (CQS only, no model_id — never routes IRB)."""
    return {
        "rating_reference": f"MDB-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "external",
        "rating_agency": "S&P",
        "cqs": cqs,
        "rating_date": _VALUE_DATE,
        "is_solicited": True,
    }
