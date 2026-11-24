"""
QRRE per-individual aggregate reporting portfolio — the QRRE / retail-other sheet axis.

Pipeline position:
    build_reporting_qrre_headroom_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator (C 08.01 / OF 08.01 sheets)

Why this portfolio exists (P5.54, the deferred half of P1.320):
    CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c) cap the *aggregate* nominal
    exposure to one individual across the QRRE sub-portfolio, and P1.320 made
    ``engine/classify/subtypes.py::qrre_obligor_aggregate_limit_expr`` count each
    committed facility limit ONCE rather than once per hierarchy leg. Before this
    portfolio no registered reporting run could see that fix: the estate's only
    QRRE row (``reporting_irb_classes_portfolio.py``'s ``LN_QRRE``) is ONE leg
    drawn to its full limit, so it mints no ``_UNDRAWN`` headroom row, and every
    other revolving facility in ``RUNS`` belongs to a corporate. Reverting the
    dedupe moved no reporting output at all — ``tests/acceptance/reporting`` ran
    fully green — which is LESSONS B5 in its fourth form: a cap with no row past
    it and no row that reaches it through more than one leg.

Composition — five natural-person obligors, every leg A-IRB (internal PD on
the obligor, own-estimate LGD on every loan AND every facility, so each
synthetic headroom row inherits one), one shared obligor PD so that only the
classification differs between rows:

    obligor     facility (limit)             legs                     class, both regimes
    ----------  ---------------------------  -----------------------  -------------------
    MOVER       FAC_MOVER 60,000 LR          LN_MOVER drawn 20,000    retail_qrre
                                             FAC_MOVER_UNDRAWN        retail_qrre
    SURVIVOR    FAC_SURVIVOR 30,000 LR       LN_SURVIVOR fully drawn  retail_qrre
    PAST_CAP    FAC_PAST_CAP_A 50,000 LR     LN_PAST_CAP_A drawn      retail_other
                FAC_PAST_CAP_B 50,000 LR     LN_PAST_CAP_B drawn      retail_other
    MIXED       FAC_MIXED 120,000 MR         LN_MIXED drawn 40,000    retail_other
                                             FAC_MIXED_UNDRAWN        retail_other
    MOF         FAC_MOF 120,000 LR (root)    FAC_MOF_UNDRAWN_..._MR   retail_other
                  sub FAC_MOF_MR 50,000 MR   FAC_MOF_UNDRAWN_..._LR   retail_other
                  sub FAC_MOF_LR 70,000 LR   (no loans)

What each obligor guards, stated as the regression it turns red:

- ``MOVER`` (the moving row). One LR facility with headroom, so the hierarchy
  emits the drawn loan AND ``FAC_MOVER_UNDRAWN``; both inherit the full
  ``facility_limit``. Its limit sits in ``(ceiling / 2, ceiling]`` under BOTH
  ceilings, so counted once it qualifies and counted per leg (``2 x limit``) it
  does not. Summing every leg — the pre-P1.320 expression — moves both legs to
  retail-other.
- ``SURVIVOR`` (the live-cell control). One fully drawn leg well below the cap.
  It is QRRE under the fix and under every regression below, so the QRRE sheet
  stays populated whichever way the mover goes, and a test can tell "the mover
  moved" from "the QRRE sheet was zeroed" (LESSONS B5, the two-leg pattern).
- ``PAST_CAP`` (the row past the cap). Two DISTINCT qualifying facilities, each
  at or below the cap, whose limits sum past it. Art. 147(5A)(c) is an
  aggregate across facilities, so it must stay retail-other. Guards the
  over-deduplicating regression — one contribution per obligor (a ``max``) —
  which would admit it.
- ``MIXED`` (mixed candidacy within one facility, candidate leg FIRST). A
  revolving, unsecured facility whose undrawn part is NOT unconditionally
  cancellable (``MR``). The drawn leg carries no undrawn commitment and so
  passes the Art. 147(5A)(b) cancellability limb; the ``_UNDRAWN`` leg does
  not. Its limit sits in ``(ceiling, 2 x ceiling]``. The correct aggregate
  counts the limit once from the one candidate leg (past the cap:
  retail-other). Dividing the limit by the facility's LINE count — the shape of
  the sibling obligor dedupe in ``engine/classify/attributes.py`` that
  ``subtypes.py`` documents it must NOT copy — halves it and wrongly admits the
  drawn leg to QRRE.
- ``MOF`` (mixed candidacy within one facility, NON-candidate leg FIRST). A
  multi-option facility root with two committed sub-lines and no loans: an
  ``MR`` sub (not unconditionally cancellable, so not a candidate) and an
  ``LR`` sub (a candidate). The waterfall emits one headroom row per sub, each
  carrying the ROOT's ``facility_limit`` and the root as its
  ``parent_facility_reference`` — one dedupe group — and it emits them sorted
  by descending SA CCF (``engine/hierarchy/facility_undrawn.py::
  _expand_mof_facility_undrawn``), so the non-candidate ``MR`` row reaches the
  classifier BEFORE the candidate ``LR`` row. That order is what this obligor is
  for. ``subtypes.py``'s ⚠ note says the intra-facility ordinal is a
  ``cum_sum`` of the CANDIDATE MASK, not a row count; on ``MIXED`` a row-count
  ordinal ("the first leg of the facility carries the limit") happens to pick
  the candidate leg, because the drawn loan precedes the ``_UNDRAWN`` row in
  ``engine/hierarchy/unify.py``'s concat. Here the first row is the
  non-candidate, so a row-count ordinal gives the candidate leg zero, the
  individual's aggregate zero, and wrongly admits the ``LR`` row to QRRE. The
  line-count divide admits it too (``120,000 / 2``). With no loans there is no
  sub-grain leg, so the MOF root/sub over-count below does not arise here.

The reading ``MOF``'s class rests on — settled by the owner, NOT fixed by the
rule text. Art. 147(5A)(c) / 154(4)(c) do not say which nominal amount a
multi-option root contributes when only some of its sub-lines are
QRRE-eligible. Two readings fit the words:

- ROOT reading (the engine's, by the P1.320 design): the waterfall row carries
  the ROOT's ``facility_limit`` (``engine/hierarchy/facility_undrawn.py``), and
  the first candidate leg of the root's group carries it once — 120,000, past
  both ceilings, so the ``LR`` leg is retail-other.
- SUB-LINE reading: the QRRE-eligible ``LR`` sub-line's own 70,000 limit is the
  nominal basis — at or below both ceilings, so the ``LR`` leg would be QRRE.

The owner's P1.355 sign-off brief keeps "today's conservative treatment ...
when some sibling sub-lines are not QRRE-eligible", which is the root reading,
so ``QRRE_HEADROOM_EXPECTED_CLASS`` records retail-other. If P1.355 or a later
item adopts the sub-line reading, the class test and both sheet tests go red in
both regimes: that is the intended signal, and the answer is to re-point
``EXP_MOF_LR_UNDRAWN`` (and the two sheet totals) deliberately, with the reason
— not to treat retail-other as reading-independent. ``MIXED`` has no sub-line:
on the committed-limit basis its one 120,000 limit is past the cap however its
legs are deduplicated.

The ceiling is not typed anywhere in this file (LESSONS A4 / B3): it is
``regulatory_threshold(pack, "qrre_max_limit", config.eur_gbp_rate)`` — GBP
90,000 native under PS1/26, EUR 100,000 converted at ``eur_gbp_rate`` under CRR
(GBP 87,320 at the 0.8732 default). The bundle deliberately carries NO
``fx_rates`` table: with ``sync_eur_gbp_rate_from_fx_table`` on, one would move
the CRR ceiling. The limits below are fixture inputs chosen against both
ceilings, and ``tests/acceptance/reporting/test_qrre_headroom_reporting.py``
asserts their adequacy against the pack at test time rather than trusting this
docstring.

Registration: ``qrre-headroom`` in ``RUNS``
(``tests/acceptance/reporting/test_supervisory_validations.py``) under both
regimes, with a prior-period frame. Registering it is what puts it in the
supervisory register and the coverage, cell-census and filing-mapping ratchets,
and it owes a golden per run (``qrre_headroom_crr`` / ``qrre_headroom_b31``,
owned by ``test_reporting_registered_goldens.py``) the day it is registered.

Deliberately OUT of scope:
- The MOF root/sub grain over-count (P1.355; ``tests/fixtures/p1_320`` leg (v):
  a loan under a sub-line keys its leg on the SUB while the waterfall rows key
  on the ROOT, so a root of 70,000 and its sub of 25,000 count 95,000).
  Conservative, separately owed, and asserted at engine level there; ``MOF``
  above has no loans precisely so that it does not reach it.
- RWA signs. QRRE and retail-other correlations cross near PD 7.3% and the
  PS1/26 QRRE LGD / PD floors differ from retail-other's, so the direction of a
  reclassification depends on PD and LGD. The tests pin sheet PLACEMENT, never a
  sign (P5.62 owns the RWA direction on a facility share).

References:
- CRR Art. 154(4)(a)-(c) / PS1/26 Art. 147(5A)(a)-(c): the QRRE sub-class
- CRR Annex II item 5.3 / PS1/26 Annex II §3.3.2 item 4.5: the QRRE sheet
- tests/fixtures/p1_320/p1_320.py: the engine-level legs this mirrors (``MOF``
  is the shape of its leg (vi) — a loan-free root whose sub-lines differ in
  cancellability — at one root, with an ``MR`` sub-line where leg (vi) has ``FR``)
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.domain.enums import ExposureClass
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: Must match ``create_full_irb_model_permissions`` or no row routes IRB.
_MODEL_ID: str = "TEST_FULL_IRB"

CP_MOVER: str = "QHR-CP-MOVER"
CP_SURVIVOR: str = "QHR-CP-SURVIVOR"
CP_PAST_CAP: str = "QHR-CP-PAST-CAP"
CP_MIXED: str = "QHR-CP-MIXED"
CP_MOF: str = "QHR-CP-MOF"

FAC_MOVER: str = "QHR-FAC-MOVER"
FAC_SURVIVOR: str = "QHR-FAC-SURVIVOR"
FAC_PAST_CAP_A: str = "QHR-FAC-PAST-CAP-A"
FAC_PAST_CAP_B: str = "QHR-FAC-PAST-CAP-B"
FAC_MIXED: str = "QHR-FAC-MIXED"
#: A multi-option facility root and its two committed sub-lines.
FAC_MOF: str = "QHR-FAC-MOF"
FAC_MOF_LR: str = "QHR-FAC-MOF-LR"
FAC_MOF_MR: str = "QHR-FAC-MOF-MR"

LN_MOVER: str = "QHR-LN-MOVER"
LN_SURVIVOR: str = "QHR-LN-SURVIVOR"
LN_PAST_CAP_A: str = "QHR-LN-PAST-CAP-A"
LN_PAST_CAP_B: str = "QHR-LN-PAST-CAP-B"
LN_MIXED: str = "QHR-LN-MIXED"

#: The synthetic headroom rows the hierarchy stage mints for the two single-level
#: facilities drawn below their limit (``<facility_reference>_UNDRAWN``).
EXP_MOVER_UNDRAWN: str = FAC_MOVER + "_UNDRAWN"
EXP_MIXED_UNDRAWN: str = FAC_MIXED + "_UNDRAWN"
#: The MOF root's two waterfall headroom rows (``<root>_UNDRAWN_<sub>``), one per
#: committed sub-line. Both carry the ROOT's ``facility_limit`` and the root as
#: their ``parent_facility_reference``, so they share one dedupe group.
EXP_MOF_LR_UNDRAWN: str = FAC_MOF + "_UNDRAWN_" + FAC_MOF_LR
EXP_MOF_MR_UNDRAWN: str = FAC_MOF + "_UNDRAWN_" + FAC_MOF_MR

#: Facility limits (GBP) — fixture INPUTS chosen against the pack ceilings, not
#: regulatory values. The adequacy of each against
#: ``regulatory_threshold(pack, "qrre_max_limit", ...)`` is asserted at test time.
#:
#: ``MOVER_LIMIT`` must sit in ``(ceiling / 2, ceiling]`` under BOTH ceilings.
MOVER_LIMIT: float = 60_000.0
MOVER_DRAWN: float = 20_000.0
#: Well below the cap on one leg — QRRE under every reading.
SURVIVOR_LIMIT: float = 30_000.0
#: Each at or below the cap; together past it under BOTH ceilings.
PAST_CAP_LIMIT: float = 50_000.0
#: Must sit in ``(ceiling, 2 x ceiling]`` under BOTH ceilings.
MIXED_LIMIT: float = 120_000.0
MIXED_DRAWN: float = 40_000.0
#: The MOF root limit must sit in ``(ceiling, 2 x ceiling]`` under BOTH
#: ceilings; the two sub-line limits sum to it exactly, so the waterfall
#: allocates the whole root headroom to the two subs and emits no
#: ``_RESIDUAL`` row.
MOF_LIMIT: float = 120_000.0
MOF_LR_LIMIT: float = 70_000.0
MOF_MR_LIMIT: float = 50_000.0

#: The non-cancellable risk type on ``FAC_MIXED`` and the ``FAC_MOF_MR``
#: sub-line. ``MR`` (CRR Annex I medium risk) is a committed bucket that is NOT
#: the ``LR`` unconditional-cancellability signal ``qrre_undrawn_cancellable_expr``
#: reads, and its SA CCF is above ``LR``'s in both regimes, which is what puts the
#: ``MR`` sub-line's waterfall row first.
MIXED_RISK_TYPE: str = "MR"

#: One obligor PD for every row, so the classification is the only thing that
#: differs between legs. Above every retail PD floor in both regimes.
PD_RETAIL: float = 0.02
#: Own-estimate LGD on every leg — above the PS1/26 QRRE and retail-other
#: unsecured LGD input floors, so no floor binds in either class.
LGD_RETAIL: float = 0.55

_VALUE_DATE: date = date(2020, 1, 1)
_MATURITY: date = date(2031, 12, 31)  # > both reporting dates (CRR 2025, B31 2027)

_QRRE: str = ExposureClass.RETAIL_QRRE.value
_RETAIL_OTHER: str = ExposureClass.RETAIL_OTHER.value

#: Every obligor; each guard sits on its own because the (c) aggregate is
#: per-individual.
_OBLIGORS: tuple[str, ...] = (CP_MOVER, CP_SURVIVOR, CP_PAST_CAP, CP_MIXED, CP_MOF)

#: Every exposure leg and the Art. 147 IRB class it must resolve to — the same
#: in both regimes, because Art. 154(4)(a)-(c) and Art. 147(5A)(a)-(c) impose the
#: same conditions and differ only in the (c) ceiling, which every limit above
#: clears or fails on the same side under both. ``EXP_MOF_LR_UNDRAWN``'s entry
#: is the owner-settled ROOT reading (module docstring), not a fact of the text.
QRRE_HEADROOM_EXPECTED_CLASS: dict[str, str] = {
    LN_MOVER: _QRRE,
    EXP_MOVER_UNDRAWN: _QRRE,
    LN_SURVIVOR: _QRRE,
    LN_PAST_CAP_A: _RETAIL_OTHER,
    LN_PAST_CAP_B: _RETAIL_OTHER,
    LN_MIXED: _RETAIL_OTHER,
    EXP_MIXED_UNDRAWN: _RETAIL_OTHER,
    EXP_MOF_MR_UNDRAWN: _RETAIL_OTHER,
    EXP_MOF_LR_UNDRAWN: _RETAIL_OTHER,
}

#: The C 08.01 sheet each class reports on, per regime. CRR keys the sheet axis
#: by IRB class (Annex II items 5.3 / 5.4); the Basel 3.1 axis is class AND
#: approach (PRA001 v4.1.1 ``OF08.01.01.01``): sheet 0015 "Retail - Qualifying
#: revolving (AIRB approach)" and sheet 0017 "Retail - Other non-SME (AIRB
#: approach)" — every obligor here is a natural person, so non-SME.
QRRE_HEADROOM_SHEET: dict[str, dict[str, str]] = {
    "crr": {_QRRE: "retail_qrre", _RETAIL_OTHER: "retail_other"},
    "b31": {_QRRE: "retail_qrre_airb", _RETAIL_OTHER: "retail_other_non_sme_airb"},
}


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_qrre_headroom_bundle() -> RawDataBundle:
    """Assemble the QRRE per-individual aggregate portfolio as a sealed bundle.

    Sealed against the loader edge contracts by ``make_raw_bundle``, so it is
    shape-identical to a parquet-loaded production bundle. Run it through
    ``PipelineOrchestrator().run_with_data`` under either regime with
    ``PermissionMode.IRB``; under Basel 3.1 keep
    ``enforce_retail_granularity=False`` (the production default), or the
    optional 0.2% granularity test fails every row of a compact portfolio as
    regulatory retail and the QRRE sheet vanishes.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        facilities=_facilities(),
        facility_mappings=_facility_mappings(),
        ratings=_ratings(),
        model_permissions=create_full_irb_model_permissions(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """Five natural persons, pool-managed as retail.

    ``is_natural_person`` passes the Art. 147(5A)(a) limb and
    ``is_managed_as_retail`` the Art. 123A(1)(b)(iii) pool-management limb, so
    the QRRE outcome is decided only by the facility attributes and limits.
    Each guard sits on its own obligor because the (c) aggregate is
    per-individual: sharing one would make every guard read the same sum.
    """
    rows = [
        {
            "counterparty_reference": reference,
            "entity_type": "individual",
            "country_code": "GB",
            "is_natural_person": True,
            "is_managed_as_retail": True,
        }
        for reference in _OBLIGORS
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """Internal PD ratings — an internal PD plus a permission routes a row IRB.

    Ratings join on ``counterparty_reference``, so the synthetic ``_UNDRAWN``
    rows carry their obligor's PD like the drawn legs do.
    """
    rows = [
        {
            "rating_reference": f"QHR-RTG-{reference}",
            "counterparty_reference": reference,
            "rating_type": "internal",
            "pd": PD_RETAIL,
            "model_id": _MODEL_ID,
            "rating_date": _VALUE_DATE,
        }
        for reference in _OBLIGORS
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _facilities() -> pl.DataFrame:
    """The revolving, unsecured facilities — the Art. 147(5A)(b) attributes.

    Five parents plus the two committed sub-lines of the ``MOF`` root. Each
    sub-line's ``risk_type`` is what its waterfall headroom row carries, so the
    ``MR`` sub-line's row fails the cancellability limb and the ``LR`` one's
    passes; the root's ``limit`` is what both rows carry as ``facility_limit``.

    ``is_revolving`` / ``is_secured`` / ``limit`` live on the facility and are
    coalesced onto each leg by the hierarchy stage. ``lgd`` and
    ``has_sufficient_collateral_data`` are set here as well as on the loans
    because the synthetic ``_UNDRAWN`` row takes them from its facility: without
    them the headroom leg has no own-estimate LGD and cannot route A-IRB, the
    only IRB approach Art. 151(4) / PS1/26 Art. 147A permit for retail.
    """
    rows = [
        _facility(FAC_MOVER, CP_MOVER, MOVER_LIMIT),
        _facility(FAC_SURVIVOR, CP_SURVIVOR, SURVIVOR_LIMIT),
        _facility(FAC_PAST_CAP_A, CP_PAST_CAP, PAST_CAP_LIMIT),
        _facility(FAC_PAST_CAP_B, CP_PAST_CAP, PAST_CAP_LIMIT),
        _facility(FAC_MIXED, CP_MIXED, MIXED_LIMIT, risk_type=MIXED_RISK_TYPE),
        _facility(FAC_MOF, CP_MOF, MOF_LIMIT),
        _facility(FAC_MOF_LR, CP_MOF, MOF_LR_LIMIT),
        _facility(FAC_MOF_MR, CP_MOF, MOF_MR_LIMIT, risk_type=MIXED_RISK_TYPE),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_SCHEMA))


def _loans() -> pl.DataFrame:
    """One drawn revolving loan per facility. EAD of a drawn leg = drawn_amount."""
    rows = [
        _loan(LN_MOVER, CP_MOVER, MOVER_DRAWN),
        _loan(LN_SURVIVOR, CP_SURVIVOR, SURVIVOR_LIMIT),
        _loan(LN_PAST_CAP_A, CP_PAST_CAP, PAST_CAP_LIMIT),
        _loan(LN_PAST_CAP_B, CP_PAST_CAP, PAST_CAP_LIMIT),
        _loan(LN_MIXED, CP_MIXED, MIXED_DRAWN),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _facility_mappings() -> pl.DataFrame:
    """Link each loan to its parent, and the two ``MOF`` sub-lines to their root.

    A facility -> facility edge is what makes ``FAC_MOF`` a multi-option root:
    the hierarchy stage then emits one waterfall headroom row per committed
    sub-line instead of a single ``_UNDRAWN`` row, and the sub-lines emit none.
    """
    pairs = (
        (FAC_MOVER, LN_MOVER),
        (FAC_SURVIVOR, LN_SURVIVOR),
        (FAC_PAST_CAP_A, LN_PAST_CAP_A),
        (FAC_PAST_CAP_B, LN_PAST_CAP_B),
        (FAC_MIXED, LN_MIXED),
    )
    rows = [
        {"parent_facility_reference": parent, "child_reference": child, "child_type": "loan"}
        for parent, child in pairs
    ] + [
        {"parent_facility_reference": FAC_MOF, "child_reference": sub, "child_type": "facility"}
        for sub in (FAC_MOF_LR, FAC_MOF_MR)
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_MAPPING_SCHEMA))


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _facility(
    facility_reference: str,
    counterparty_reference: str,
    limit: float,
    *,
    risk_type: str = "LR",
) -> dict:
    """One committed, revolving, unsecured retail facility row.

    ``risk_type="LR"`` is the unconditional-cancellability signal (CRR Annex I
    para 4(a) / PS1/26 Table A1 row (7)) that the QRRE (b) limb reads on an
    undrawn leg. ``is_qrre_transactor=False`` keeps every admitted row on the
    revolver PD floor rather than the transactor path.
    """
    return {
        "facility_reference": facility_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "revolving_credit_facility",
        "limit": limit,
        "risk_type": risk_type,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "committed": True,
        "is_revolving": True,
        "is_secured": False,
        "is_qrre_transactor": False,
        "seniority": "senior",
        "lgd": LGD_RETAIL,
        "has_sufficient_collateral_data": True,
    }


def _loan(loan_reference: str, counterparty_reference: str, drawn_amount: float) -> dict:
    """One drawn revolving retail loan row with an own-estimate LGD."""
    return {
        "loan_reference": loan_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "revolving_credit_facility",
        "drawn_amount": drawn_amount,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
        "lgd": LGD_RETAIL,
        "has_sufficient_collateral_data": True,
    }
