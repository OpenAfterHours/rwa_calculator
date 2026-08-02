"""
CRM guarantee-substitution reporting portfolio — the C 07.00 / C 08.01 / C 08.02
outflow/inflow axis.

Pipeline position:
    build_reporting_crm_substitution_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Why this portfolio: every substitution cell (C 07.00 cols 0050/0060/0090/0100,
C 08.01 cols 0040/0050/0070/0080, C 08.02 col 0080) is exactly 0.0 in every one of
the 70+ frozen golden ndjson files under ``tests/expected_outputs/reporting/`` —
no golden portfolio contains a guaranteed exposure that migrates exposure class.
This portfolio closes that blind spot with five guarantee legs, each on a
distinct obligor/guarantor pair with a distinct round guaranteed amount so a
mis-posted cell is identifiable on sight.

CRM substitution physically splits a guaranteed loan into a ``__G_<guarantor>``
guaranteed leg and a ``__REM`` retained leg (``engine/crm/guarantees.py``). The
sealed reporting projection (``engine/aggregator/aggregator.py``) then carries,
per leg:
    reporting_class_origin / reporting_approach_origin  = the OBLIGOR's applied
        class / approach (``exposure_class_applied`` / ``approach_applied``) —
        UNIFORM across a loan's legs, including the ``__G_`` leg. This is the
        key BOTH templates sheet on: C 07.00's module docstring says "Sheets
        key the OBLIGOR applied class"; C 08.01/02's says the five dicts "key
        the sealed ``reporting_class_origin`` ... the obligor basis" — same
        rule, each template's own column name for it. A guaranteed leg
        therefore never appears as a ROW on the guarantor's own class sheet —
        it stays on the obligor's ORIGIN sheet, contributing to that sheet's
        outflow column (C 07.00 col 0090 / C 08.01 col 0070).
    reporting_class / reporting_approach = the POST-substitution twin
        (``exposure_class_post_crm`` / ``approach_post_crm``) — the guarantor's
        class on the ``__G_`` leg. This is NOT a sheet key; it feeds the
        cross-template INFLOW, a per-destination-class SCALAR computed by
        ``reporting/corep/crm_substitution.py::substitution_inflows`` — ONE
        function, run once over the WHOLE sealed population (not a
        per-template slice) — that lands on the destination class's Total row
        (C 07.00 col 0100, C 08.01 col 0080). The destination class need NOT
        already have a native origin-basis row on that template — the sheet
        axis is the UNION of "classes with native rows" and "classes
        receiving an inflow", so a class with zero native rows still gets an
        INFLOW-ONLY sheet (Total row 0010/0020 = 0, the inflow column
        populated). Routing to a TEMPLATE reads ``reporting_approach`` (==
        ``approach_post_crm``): the IRB approaches (``foundation_irb`` /
        ``advanced_irb`` / ``slotting``) route to C 08.01, everything else
        (including the output floor's ``standardised_ccr`` relabel) is the SA
        complement and routes to C 07.00 — independent of which population
        the OUTFLOW leg itself sits in, so an IRB-origin obligor with an
        SA-treated guarantor puts the outflow on C 08.01 and the inflow on
        C 07.00 (see S3 below). Every leg with a positive
        ``guaranteed_portion`` is counted, including one whose guarantor sits
        in the obligor's own class (see S5 below).

``substitution_inflows`` retired the two former per-template helpers
(``c07.py``'s and ``c08.py``'s own class-inequality-gated inflow builders,
each keyed to its OWN approach-filtered population) precisely because that
split could report an outflow on one template and land its inflow on
NEITHER — the defect S3 isolates — and its class-inequality gate excluded a
same-class migration from both sides at once — the defect S5 isolates. This
is what makes the five scenarios below orthogonal rather than redundant:

    ref    | obligor        | guarantor              | outflow | inflow  | what it exercises
    -------|----------------|-------------------------|---------|---------|------------------------------
    S1     | IRB corporate  | IRB institution,        | C 08.01 | C 08.01 | within-template inflow,
           |                | OWN IRB exposure         |         |         | destination class HAS a
           |                |                          |         |         | native row already
    S2     | IRB corporate  | IRB retail_other,        | C 08.01 | C 08.01 | within-template inflow,
           |                | NO own exposure          |         |         | destination class has NO
           |                |                          |         |         | native row — an inflow-only
           |                |                          |         |         | sheet
    S3     | IRB corporate  | SA sovereign (domestic   | C 08.01 | C 07.00 | CROSS-TEMPLATE: the outflow
           |                | CGCB, 0% RW), NO own     |         |         | leg is only ever visible to
           |                | exposure                 |         |         | C 08.01's origin-IRB
           |                |                          |         |         | population, but the SA
           |                |                          |         |         | guarantor's inflow belongs
           |                |                          |         |         | on C 07.00 — crossing the
           |                |                          |         |         | SA/IRB template boundary,
           |                |                          |         |         | landing on an inflow-only
           |                |                          |         |         | C 07.00 sheet
    S4     | SA corporate   | SA institution, OWN SA   | C 07.00 | C 07.00 | within-template inflow,
           |                | exposure                 |         |         | destination class HAS a
           |                |                          |         |         | native row already
    S5     | IRB corporate  | IRB corporate (DIFFERENT | C 08.01 | C 08.01 | SAME-CLASS outflow/inflow:
           |                | counterparty, SAME class)|         |         | Annex II requires an outflow
           |                |                          |         |         | AND an equal inflow on the
           |                |                          |         |         | SAME sheet, netting to no
           |                |                          |         |         | change in col 0090 — the
           |                |                          |         |         | sharpest case, since the
           |                |                          |         |         | destination sheet IS the
           |                |                          |         |         | origin sheet, not merely a
           |                |                          |         |         | sheet that happens to exist

S1/S4 are the happy-path pair (one IRB, one SA) proving the mechanism works
when the destination class already has a native row. S2 isolates the
"destination class has no native population, same template" case. S3 isolates
the cross-template case: the leg is only ever visible to C 08.01's population
(its origin approach is IRB), so its OUTFLOW cannot be anywhere but C 08.01,
while its guarantor is SA-treated, so its INFLOW belongs on C 07.00 — the two
sides of one migration legitimately live on different templates. S5 isolates
the THIRD, orthogonal case COREP Annex II (both regimes, both templates)
calls out by name — "Inflows and outflows within the same exposure classes
and, where relevant, obligor grades or pools, shall also be considered" —
where ``pre_crm_exposure_class == post_crm_exposure_class_guaranteed`` and a
correct implementation must still recognise BOTH an outflow (col 0070 /
C 07.00 col 0090) and an equal inflow (col 0080 / C 07.00 col 0100) on that
one sheet, netting to no change in the post-substitution total (col 0090 /
col 0110) despite nothing leaving the class. This is the fixture-level
reproduction backing the CRM substitution investigation tracked against
C 07.00/C 08.01/C 08.02; see the module-level ``NOTE`` below for the specific
behaviour observed when this fixture was built and verified.

NOTE (as observed 2026-08-02, CRR, on ``fix/corep-crm-substitution-waterfall``
— re-verify against a live run before relying on this as a current-state
claim, since it was recorded mid-investigation): all five scenarios land
correctly, and portfolio-wide gross (40,500,000) reconciles exactly to net
across every sheet with zero leakage. Per sheet, Total row:

    c08_01 corporate    : 0020=27,000,000  0040=-12,300,000  0050=-3,300,000  0070=-15,600,000  0080=+5,400,000  0090=16,800,000
    c08_01 institution   : 0020= 4,000,000                                                        0080=+2,000,000  0090= 6,000,000
    c08_01 retail_other  : 0020=         0                                                          0080=+3,300,000  0090= 3,300,000   <- S2, inflow-only sheet
    c07_00 corporate     : 0010= 8,000,000                                    0060=-2,800,000  0090=-2,800,000                    0110= 5,200,000
    c07_00 institution   : 0010= 1,500,000                                                                          0100=+2,800,000  0110= 4,300,000
    c07_00 cgcb          : 0010=         0                                                                          0100=+4,900,000  0110= 4,900,000   <- S3, inflow-only sheet

S5's isolated ``corporate`` sheet Total row (S5 alone, no other scenario on
the sheet) reports ``0020=9,000,000 / 0040=-5,400,000 / 0070=-5,400,000 /
0080=5,400,000 / 0090=9,000,000`` (== 0020, i.e. no change, exactly as
Annex II requires), matching ``v1663_m`` ({c0070} = {c0040}+{c0050}+{c0060})
and the corrected col 0090 waterfall.

Every guarantee is PARTIAL cover (never 100%), so a retained ``__REM`` leg
genuinely coexists with the ``__G_`` leg on all five scenarios, and every
guaranteed amount is a distinct round GBP figure so any template cell is
traceable to exactly one leg. ``protection_type`` covers both values Annex II
splits (C 08.01 cols 0040/0050): S1/S3/S5 are ``"guarantee"``, S2/S4 are
``"credit_derivative"``.

No CRR/Basel 3.1 regime divergence is exercised here (deliberately, unlike
``reporting_irb_classes_portfolio.py``'s sovereign-class carve-out) — every
obligor keeps the same approach under both regimes, so the sheet-routing
answer is identical for both; the CRR/B31 expected-sheet dicts below are
provided as a matched pair purely for parity with the sibling fixture's
convention and because a future regime-conditioned defect fix could make them
diverge.

References:
- CRR Art. 235 / PS1/26 Art. 235: SA risk-weight substitution (RWSM).
- CRR Art. 161 / CRE22.70-85: IRB parameter substitution (PSM).
- CRR Art. 114(4)/(7) / Art. 235(3): the domestic-currency CGCB 0% RW
  extension to a centrally-guaranteed exposure (S3's guarantor).
- CRR Art. 201: eligible-guarantor eligibility gate.
- COREP Annex II, C 07.00 / C 08.01 / C 08.02: the outflow/inflow columns,
  including the same-exposure-class inflow/outflow requirement (S5).
- engine/crm/guarantees.py: the ``__G_`` / ``__REM`` physical split.
- engine/aggregator/aggregator.py: ``_add_reporting_projection`` (the sealed
  ``reporting_class`` / ``reporting_class_origin`` twins).
- reporting/corep/c07.py, reporting/corep/c08.py: module docstrings on sheet
  keying (each reads its per-class rows off ``reporting_class_origin``, the
  obligor basis).
- reporting/corep/crm_substitution.py: ``substitution_inflows`` — the single
  cross-template inflow router keyed on ``reporting_approach`` (S3), which
  counts every leg with a positive ``guaranteed_portion`` including same-class
  ones (S5); ``crm_waterfall`` / ``waterfall_refs`` — the C 08.01/02 col 0090
  identity this fixture also exercises (0090 = 0020 - 0070 + 0080 over
  positive magnitudes, col 0070 as the single whole-outflow subtotal).
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, GUARANTEE_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: Must match ``create_full_irb_model_permissions`` (F-IRB + A-IRB + slotting
#: for every class), or no row routes IRB at all.
_MODEL_ID: str = "TEST_FULL_IRB"

# -- S1: IRB obligor, IRB guarantor WITH its own IRB exposure ---------------
OB_S1: str = "CSUB-CP-OB-S1"
GTOR_S1: str = "CSUB-CP-GTOR-S1"
LN_S1: str = "CSUB-LN-S1"
LN_S1_GTOR_OWN: str = "CSUB-LN-S1-GTOR-OWN"
GUAR_S1: str = "CSUB-GUAR-S1"

# -- S2: IRB obligor, IRB guarantor with NO other IRB exposure in this book -
OB_S2: str = "CSUB-CP-OB-S2"
GTOR_S2: str = "CSUB-CP-GTOR-S2"
LN_S2: str = "CSUB-LN-S2"
GUAR_S2: str = "CSUB-GUAR-S2"

# -- S3: IRB obligor, SA (domestic CGCB) guarantor, no own exposure ---------
OB_S3: str = "CSUB-CP-OB-S3"
GTOR_S3: str = "CSUB-CP-GTOR-S3"
LN_S3: str = "CSUB-LN-S3"
GUAR_S3: str = "CSUB-GUAR-S3"

# -- S4: SA obligor, SA guarantor WITH its own SA exposure -------------------
OB_S4: str = "CSUB-CP-OB-S4"
GTOR_S4: str = "CSUB-CP-GTOR-S4"
LN_S4: str = "CSUB-LN-S4"
LN_S4_GTOR_OWN: str = "CSUB-LN-S4-GTOR-OWN"
GUAR_S4: str = "CSUB-GUAR-S4"

# -- S5: IRB obligor, IRB guarantor in the SAME exposure class (corporate) --
OB_S5: str = "CSUB-CP-OB-S5"
GTOR_S5: str = "CSUB-CP-GTOR-S5"
LN_S5: str = "CSUB-LN-S5"
GUAR_S5: str = "CSUB-GUAR-S5"

#: Drawn amounts (GBP), each a distinct round figure. EAD = drawn_amount (no
#: facility / CCF machinery involved — every row is a plain drawn term loan).
DRAWN_S1: float = 5_000_000.0
DRAWN_S1_GTOR_OWN: float = 4_000_000.0
DRAWN_S2: float = 6_000_000.0
DRAWN_S3: float = 7_000_000.0
DRAWN_S4: float = 8_000_000.0
DRAWN_S4_GTOR_OWN: float = 1_500_000.0
DRAWN_S5: float = 9_000_000.0

#: Guarantee coverage — always PARTIAL, so a retained ``__REM`` leg coexists
#: with the ``__G_`` leg on every scenario. Distinct percentages per scenario.
PCT_COVERED_S1: float = 0.40
PCT_COVERED_S2: float = 0.55
PCT_COVERED_S3: float = 0.70
PCT_COVERED_S4: float = 0.35
PCT_COVERED_S5: float = 0.60

#: amount_covered = drawn_amount * pct_covered, rounded to a clean GBP figure.
AMOUNT_COVERED_S1: float = DRAWN_S1 * PCT_COVERED_S1  # 2,000,000
AMOUNT_COVERED_S2: float = DRAWN_S2 * PCT_COVERED_S2  # 3,300,000
AMOUNT_COVERED_S3: float = DRAWN_S3 * PCT_COVERED_S3  # 4,900,000
AMOUNT_COVERED_S4: float = DRAWN_S4 * PCT_COVERED_S4  # 2,800,000
AMOUNT_COVERED_S5: float = DRAWN_S5 * PCT_COVERED_S5  # 5,400,000

#: Internal PDs (IRB legs only). Each guarantor with an internal PD is a
#: deliberately IRB-routing signal — see ``_assign_guarantor_approach``
#: (guarantor treated IRB iff the beneficiary is IRB, the guarantor's class
#: has IRB model permission, AND the guarantor carries an internal PD).
PD_OB_S1: float = 0.0050
PD_GTOR_S1: float = 0.0030
PD_OB_S2: float = 0.0060
PD_GTOR_S2: float = 0.0200
PD_OB_S3: float = 0.0080
PD_OB_S5: float = 0.0090
#: GTOR_S5 is a DIFFERENT corporate counterparty from OB_S5, not the same one
#: — the SAME-CLASS defect requires two distinct obligors of one class, not a
#: self-guarantee.
PD_GTOR_S5: float = 0.0045

#: External CQS assignments (SA / non-IRB-rated legs).
#: CQS 1 sovereign -> 0% RW under both regimes; also triggers the Art.
#: 114(4)/(7) domestic-CGCB 0% short-circuit for GTOR_S3 (GB / GBP), which
#: forces ``guarantor_approach="sa"`` unconditionally (CRR Art. 235(3)).
CQS_GTOR_S3: int = 1
#: CQS 2 institution -> a defined, non-zero SA risk weight.
CQS_GTOR_S4: int = 2

_VALUE_DATE: date = date(2020, 1, 1)
#: Beyond both reporting dates under test (CRR 2025-06-30, B31 2027-06-30).
_MATURITY: date = date(2033, 12, 31)
#: Guarantee maturity matches the loan exactly — no Art. 239(3) mismatch haircut.
_GUARANTEE_MATURITY: date = _MATURITY
#: Comfortably >= 1y — Art. 237(2)(a) original-maturity eligibility satisfied.
_ORIGINAL_MATURITY_YEARS: float = 10.0

#: Above the SME revenue ceiling for every corporate counterparty (obligors),
#: so the SME supporting factor never perturbs a substitution cell under test.
_LARGE_CORPORATE_REVENUE: float = 400_000_000.0

#: Per-loan (BASE reference) expected ORIGIN sheet — (template, class) — under
#: EACH regime. This is where EVERY leg of that loan (whole / ``__G_`` /
#: ``__REM``) physically sits: ``reporting_class_origin`` /
#: ``reporting_approach_origin`` are uniform across a loan's legs and never
#: reflect the guarantor. Consumed by the fixture-integrity test: a
#: mis-classified obligor silently moves a leg off its expected sheet without
#: any gate turning red. "c08_01" / "c07" name the template; the class is the
#: sheet key within it.
LOAN_EXPECTED_ORIGIN_SHEET_CRR: dict[str, tuple[str, str]] = {
    LN_S1: ("c08_01", "corporate"),
    LN_S1_GTOR_OWN: ("c08_01", "institution"),
    LN_S2: ("c08_01", "corporate"),
    LN_S3: ("c08_01", "corporate"),
    LN_S4: ("c07", "corporate"),
    LN_S4_GTOR_OWN: ("c07", "institution"),
    LN_S5: ("c08_01", "corporate"),
}
#: No regime divergence is exercised in this portfolio (see module docstring)
#: — identical to the CRR map.
LOAN_EXPECTED_ORIGIN_SHEET_B31: dict[str, tuple[str, str]] = dict(LOAN_EXPECTED_ORIGIN_SHEET_CRR)

#: Per-scenario substitution-inflow expectations, keyed by the guarantee
#: reference. ``destination_class`` is ``post_crm_exposure_class_guaranteed``
#: — the class the guaranteed portion is regulatory-attributed to
#: (CRR Art. 235). ``destination_template`` is which TEMPLATE the inflow
#: scalar (``reporting/corep/crm_substitution.py::substitution_inflows``,
#: grouped by ``post_crm_exposure_class_guaranteed`` and routed by
#: ``reporting_approach``) lands on — S3's guarantor is SA, so its inflow
#: belongs on C 07.00 even though the OUTFLOW leg itself is only ever visible
#: to C 08.01's origin-IRB population (its origin approach is IRB) — the two
#: sides of one migration can sit on different templates.
#: ``destination_has_native_population`` records whether the destination
#: class ALREADY has an origin-basis row on that template independent of any
#: inflow — S1/S4/S5 True, S2/S3 False. This is NOT the same question as
#: "does a sheet get emitted for it": the sheet axis is the UNION of "classes
#: with native rows" and "classes receiving an inflow", so S2's
#: ``retail_other`` C 08.01 sheet and S3's ``central_govt_central_bank``
#: C 07.00 sheet are both emitted as INFLOW-ONLY sheets (row 0010 total = 0,
#: nothing native, the inflow scalar populated) — see the dated NOTE in the
#: module docstring. ``same_class`` is True only for S5, where
#: ``destination_class`` equals the ORIGIN class (``LOAN_EXPECTED_ORIGIN_
#: SHEET_CRR[LN_S5][1]``) — i.e. the "destination sheet" is not a different
#: sheet at all, it is the SAME sheet the outflow leg already sits on, so a
#: correct implementation nets col 0090 back to the un-guaranteed total.
#: fixture-builder does not assert the engine's CURRENT behaviour here (that
#: is test-writer's job over a live pipeline run) — this dict only records
#: the fixture's DESIGN intent (confirmed to match observed behaviour in the
#: fixture-builder verification run — see the dated NOTE above).
SUBSTITUTION_INFLOW_DESIGN: dict[str, dict[str, object]] = {
    GUAR_S1: {
        "loan_reference": LN_S1,
        "guarantor_reference": GTOR_S1,
        "guaranteed_amount": AMOUNT_COVERED_S1,
        "destination_class": "institution",
        "destination_template": "c08_01",
        "destination_has_native_population": True,
        "same_class": False,
    },
    GUAR_S2: {
        "loan_reference": LN_S2,
        "guarantor_reference": GTOR_S2,
        "guaranteed_amount": AMOUNT_COVERED_S2,
        "destination_class": "retail_other",
        "destination_template": "c08_01",
        "destination_has_native_population": False,
        "same_class": False,
    },
    GUAR_S3: {
        "loan_reference": LN_S3,
        "guarantor_reference": GTOR_S3,
        "guaranteed_amount": AMOUNT_COVERED_S3,
        "destination_class": "central_govt_central_bank",
        # The OUTFLOW leg is only ever visible to C 08.01's population (its
        # origin approach is IRB) — but the guarantor is SA-treated, so the
        # INFLOW scalar belongs on C 07.00 (confirmed: it lands there as an
        # inflow-only sheet — see the module docstring NOTE). The two sides
        # of this one migration cross the SA/IRB template boundary.
        "destination_template": "c07",
        "destination_has_native_population": False,
        "same_class": False,
    },
    GUAR_S4: {
        "loan_reference": LN_S4,
        "guarantor_reference": GTOR_S4,
        "guaranteed_amount": AMOUNT_COVERED_S4,
        "destination_class": "institution",
        "destination_template": "c07",
        "destination_has_native_population": True,
        "same_class": False,
    },
    GUAR_S5: {
        "loan_reference": LN_S5,
        "guarantor_reference": GTOR_S5,
        "guaranteed_amount": AMOUNT_COVERED_S5,
        # Same class as the origin ("corporate") — see the module docstring
        # and ``same_class`` above.
        "destination_class": "corporate",
        "destination_template": "c08_01",
        "destination_has_native_population": True,
        "same_class": True,
    },
}


def guaranteed_leg_ref(loan_reference: str, guarantor_reference: str) -> str:
    """The physical ``__G_`` guaranteed-leg exposure reference the CRM splitter
    emits (``engine/crm/guarantees.py::_build_guarantor_sub_rows``)."""
    return f"{loan_reference}__G_{guarantor_reference}"


def remainder_leg_ref(loan_reference: str) -> str:
    """The physical ``__REM`` retained-leg exposure reference the CRM splitter
    emits (``engine/crm/guarantees.py::_retained_tranche_rows``)."""
    return f"{loan_reference}__REM"


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_crm_substitution_bundle() -> RawDataBundle:
    """Assemble the CRM guarantee-substitution portfolio as a sealed bundle.

    Sealed against the loader edge contracts by ``make_raw_bundle``, so it is
    shape-identical to a parquet-loaded production bundle. Run it through
    ``PipelineOrchestrator().run_with_data`` under either regime with
    ``PermissionMode.IRB`` — every IRB-routed obligor/guarantor carries an
    internal PD and the matching ``model_permissions`` row.
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
    """Five obligor/guarantor pairs, one per scenario.

    Obligors are all ``corporate`` (S1-S3/S5 above the SME revenue ceiling so
    the supporting factor never perturbs a substitution cell; S4 unrated so
    its own-basis SA risk weight is unambiguous). Guarantors span the four SA
    classes ``ENTITY_TYPE_TO_SA_CLASS`` can reach from a counterparty
    (``institution`` x2, ``individual`` -> retail_other, ``sovereign`` ->
    central_govt_central_bank), PLUS a fifth guarantor deliberately in the
    SAME class as its obligor (``corporate`` — S5) — see the module docstring
    table.
    """
    rows: list[dict] = [
        {
            "counterparty_reference": OB_S1,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        },
        {
            "counterparty_reference": GTOR_S1,
            "entity_type": "institution",
            "country_code": "GB",
        },
        {
            "counterparty_reference": OB_S2,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        },
        {
            "counterparty_reference": GTOR_S2,
            "entity_type": "individual",
            "country_code": "GB",
            "is_natural_person": True,
        },
        {
            "counterparty_reference": OB_S3,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        },
        {
            "counterparty_reference": GTOR_S3,
            "entity_type": "sovereign",
            "country_code": "GB",
        },
        {
            # Unrated: S4's obligor is a plain Standardised loan with no
            # internal PD and no ECAI rating (100% unrated corporate RW).
            "counterparty_reference": OB_S4,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        },
        {
            "counterparty_reference": GTOR_S4,
            "entity_type": "institution",
            "country_code": "GB",
        },
        {
            "counterparty_reference": OB_S5,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        },
        {
            # Same class as OB_S5 (corporate) but a DIFFERENT counterparty —
            # the SAME-CLASS defect (S5) needs two distinct obligors sharing
            # one class, not a self-guarantee.
            "counterparty_reference": GTOR_S5,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """Internal PD ratings for IRB legs, external CQS ratings for SA legs.

    OB_S4 is deliberately unrated (no row at all) — a plain Standardised loan.
    """
    rows: list[dict] = [
        _internal(OB_S1, pd=PD_OB_S1),
        _internal(GTOR_S1, pd=PD_GTOR_S1),
        _internal(OB_S2, pd=PD_OB_S2),
        _internal(GTOR_S2, pd=PD_GTOR_S2),
        _internal(OB_S3, pd=PD_OB_S3),
        _external(GTOR_S3, cqs=CQS_GTOR_S3),
        _external(GTOR_S4, cqs=CQS_GTOR_S4),
        _internal(OB_S5, pd=PD_OB_S5),
        _internal(GTOR_S5, pd=PD_GTOR_S5),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans() -> pl.DataFrame:
    """The five obligor loans plus the two guarantors' own exposures.

    GTOR_S5 gets NO own loan — S5's whole point is that its class already has
    an origin sheet (``corporate``, from OB_S1/OB_S2/OB_S3/OB_S5 alike), so no
    separate own-exposure is needed to pre-establish it.

    No ``lgd`` is supplied on any row, so every IRB leg resolves F-IRB
    (supervisory LGD) — consistent with ``reporting_irb_classes_portfolio.py``.
    """
    rows: list[dict] = [
        _loan(LN_S1, OB_S1, DRAWN_S1),
        _loan(LN_S1_GTOR_OWN, GTOR_S1, DRAWN_S1_GTOR_OWN),
        _loan(LN_S2, OB_S2, DRAWN_S2),
        _loan(LN_S3, OB_S3, DRAWN_S3),
        _loan(LN_S4, OB_S4, DRAWN_S4),
        _loan(LN_S4_GTOR_OWN, GTOR_S4, DRAWN_S4_GTOR_OWN),
        _loan(LN_S5, OB_S5, DRAWN_S5),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _guarantees() -> pl.DataFrame:
    """The five guarantee rows — one per scenario, each partial cover.

    ``protection_type`` alternates ``"guarantee"`` / ``"credit_derivative"``
    so both C 08.01 cols 0040/0050 are exercised. ``includes_restructuring``,
    matched maturity/currency, and both unilateral flags False on every row —
    no eligibility gate or maturity-mismatch haircut should zero any leg (see
    the module docstring; confirmed empirically, not merely asserted, in the
    fixture-builder verification run).
    """
    rows: list[dict] = [
        _guarantee(GUAR_S1, GTOR_S1, LN_S1, AMOUNT_COVERED_S1, PCT_COVERED_S1, "guarantee"),
        _guarantee(GUAR_S2, GTOR_S2, LN_S2, AMOUNT_COVERED_S2, PCT_COVERED_S2, "credit_derivative"),
        _guarantee(GUAR_S3, GTOR_S3, LN_S3, AMOUNT_COVERED_S3, PCT_COVERED_S3, "guarantee"),
        _guarantee(GUAR_S4, GTOR_S4, LN_S4, AMOUNT_COVERED_S4, PCT_COVERED_S4, "credit_derivative"),
        _guarantee(GUAR_S5, GTOR_S5, LN_S5, AMOUNT_COVERED_S5, PCT_COVERED_S5, "guarantee"),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(GUARANTEE_SCHEMA))


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _loan(loan_reference: str, counterparty_reference: str, drawn_amount: float) -> dict:
    """Build one plain drawn term-loan row (unset optional columns take
    schema defaults). EAD = drawn_amount (no CCF / facility involved)."""
    return {
        "loan_reference": loan_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "term_loan",
        "drawn_amount": drawn_amount,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
        "has_sufficient_collateral_data": False,
    }


def _guarantee(
    guarantee_reference: str,
    guarantor_reference: str,
    beneficiary_loan_reference: str,
    amount_covered: float,
    percentage_covered: float,
    protection_type: str,
) -> dict:
    """Build one guarantee row — always partial, always fully eligible."""
    return {
        "guarantee_reference": guarantee_reference,
        "guarantor": guarantor_reference,
        "currency": "GBP",
        "maturity_date": _GUARANTEE_MATURITY,
        "amount_covered": amount_covered,
        "percentage_covered": percentage_covered,
        "beneficiary_type": "loan",
        "beneficiary_reference": beneficiary_loan_reference,
        "protection_type": protection_type,
        "includes_restructuring": True,
        "original_maturity_years": _ORIGINAL_MATURITY_YEARS,
        "guarantor_seniority": "senior",
        "is_unilaterally_cancellable": False,
        "is_unilaterally_changeable": False,
    }


def _internal(counterparty_reference: str, *, pd: float) -> dict:
    """Internal model rating row (PD + model_id — the IRB routing pair)."""
    return {
        "rating_reference": f"CSUB-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "pd": pd,
        "model_id": _MODEL_ID,
        "rating_date": _VALUE_DATE,
    }


def _external(counterparty_reference: str, *, cqs: int) -> dict:
    """External ECAI rating row (CQS only, no model_id — never routes IRB)."""
    return {
        "rating_reference": f"CSUB-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "external",
        "rating_agency": "S&P",
        "cqs": cqs,
        "rating_date": _VALUE_DATE,
        "is_solicited": True,
    }
