"""
P1.320 — QRRE per-individual aggregate must count each facility limit ONCE,
not once per exposure leg (CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c)).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (RawDataBundle -> HierarchyResolver -> ExposureClassifier, exercising
    ``engine/classify/subtypes.py``'s obligor-aggregate expression)

Key responsibilities:
- Provide ONE ``build_p1_320_raw_bundle`` that carries every classification
  leg below on its own distinct counterparty, so the per-individual
  aggregate for each leg is isolated and none of the legs interact.
- Exercise the dedupe key decided in the design (Wave 1, ADDENDUM R1):
  ``(counterparty_reference, parent_facility_reference)`` — count each
  supplied facility limit once, not once per leg the hierarchy stage emits
  for that facility (drawn loan / synthetic ``_UNDRAWN`` headroom / MOF
  waterfall sub-row / MOF residual row).

Defect site: ``src/rwa_calc/engine/classify/subtypes.py:186-197``.
The aggregate today sums ``facility_limit`` over every QRRE-CANDIDATE LEG,
so a facility split into N legs is counted N times.

QRRE ceiling — read from the pack, not typed here (LESSONS A4 / addendum R9):
    ``regulatory_threshold(pack, "qrre_max_limit", config.eur_gbp_rate)``
    CRR:  EUR 100,000 x eur_gbp_rate -> GBP 87,320.00 at the default rate.
    B31:  GBP 90,000.00 (native, no FX).
``QRRE2_LIMIT`` (60,000.0) is chosen so ``45,000 < limit <= 87,320``: doubled
(2 legs, pre-fix) it clears BOTH ceilings; singled (post-fix) it clears
neither. See legs (i)/(ii) below.

Leg inventory (design doc ``.claude/state/outputs/P1.320-scenario.md``,
ADDENDUM "Final leg inventory" — (iii) is cut, see note):

    (i)   headroom mover        FAC_Q2 60,000 / LN_Q2 drawn 20,000
                                 -> loan + _UNDRAWN legs, SAME facility.
                                 pre-fix 120,000 -> retail_other (both regimes)
                                 post-fix 60,000 -> retail_qrre  (both regimes)

    (ii)  multi-loan mover,     FAC_Q3 60,000 / LN_Q3A 30,000 + LN_Q3B 30,000
          NO _UNDRAWN leg       fully drawn -> 2 loan legs, no headroom row.
                                 Proves the mechanism is LEGS, not headroom.
                                 pre-fix 120,000 -> retail_other (both regimes)
                                 post-fix 60,000 -> retail_qrre  (both regimes)

    (iv)  fully-drawn           FAC_Q1 40,000 drawn 40,000 -> 1 leg.
          live-cell control     retail_qrre BOTH before and after (LESSONS
                                 B5 two-leg pattern: this keeps the QRRE cell
                                 non-zero pre-fix so a reporting test can tell
                                 "the fix worked" from "the fix zeroed the
                                 cell" -- reporting portfolio itself is
                                 DEFERRED, addendum R8, but the fixture still
                                 carries the control for that future item).

    (v)   MOF key pin           FAC_MOF 70,000 root; FAC_MOF_SUB 25,000 sub;
          (leg-multiplication    LN_MOF 10,000 drawn under the sub.
          grain ONLY -- see       Emits: LN_MOF (limit=25,000, its OWN sub's
          addendum R5)            limit), FAC_MOF_UNDRAWN_FAC_MOF_SUB (waterfall
                                  row, limit=70,000 = ROOT's limit), and
                                  FAC_MOF_UNDRAWN_RESIDUAL (limit=70,000,
                                  since sub headroom 15,000 < parent headroom
                                  60,000 leaves a 45,000 residual candidate
                                  at the ROOT's own LR risk_type).
                                 today (no dedupe):        165,000 (25k+70k+70k)
                                 parent_facility_reference: 95,000 (25k + 70k,
                                     the waterfall + residual rows share ONE
                                     group keyed on the ROOT's own reference)
                                 root_facility_reference+max (REJECTED key):
                                     70,000
                                 retail_other UNDER EVERY KEY, BOTH REGIMES --
                                 green before and after. Its non-vacuity is a
                                 mutation-testing job for test-writer (switch
                                 the key to root_facility_reference and watch
                                 it flip), not a moving assertion here.
                                 CAVEAT (addendum R5): this leg pins the LEG-
                                 MULTIPLICATION grain only. The root/sub grain
                                 over-count (a drawn leg keys on its immediate
                                 SUB, a waterfall/residual leg keys on the
                                 ROOT, so one economic facility still spans
                                 two dedupe groups) SURVIVES this fix -- it is
                                 conservative (over-counting denies QRRE, the
                                 safe direction) so it does not block this
                                 item, but it is a DIFFERENT, separately-owed
                                 defect. Do not read this leg as proving the
                                 root/sub grain is fixed.

    (vi)  MIXED candidate /     Addendum R2 -- Attack 8, highest-value new
          non-candidate         leg. Two 50,000 MOF roots (FAC_MIX_ROOT1,
          facility group        FAC_MIX_ROOT2) under ONE individual, each with
                                 two committed subs of DIFFERING risk_type:
                                 one LR (unconditionally cancellable ->
                                 QRRE-candidate) at 30,000 and one FR (fails
                                 cancellability -> NOT a candidate) at 20,000.
                                 Sub headrooms sum EXACTLY to the root's own
                                 headroom (30,000 + 20,000 = 50,000), so both
                                 waterfall rows are emitted in full and no
                                 residual row appears -- the two rows per root
                                 are clean: candidate 50,000 (root's own
                                 limit, not the sub's -- see facility_undrawn
                                 .py:561) + non-candidate 0.
                                 current (today, no dedupe; ALREADY correct
                                     here since exactly one candidate leg
                                     exists per facility): 100,000
                                 proposed (parent_facility_reference dedupe):
                                     100,000 -- UNCHANGED, both regimes.
                                 sibling-``pl.len()`` divide (the WRONG fix a
                                     copy of ``attributes.py:707-716`` would
                                     produce -- it divides by the group's
                                     TOTAL row count, candidate or not):
                                     50,000 -- WRONGLY admits QRRE. This leg
                                     exists purely to catch that shape; every
                                     other leg here passes it too.

    (iii) two-facility survivor -- CUT. ``tests/unit/classifier/
          test_p1_191_qrre_aggregate_nominal.py`` already carries this exact
          control (two 50,000 facilities to one individual, plus a 50,000
          control obligor) and is verified passing under the patched
          expression (addendum, "Protective" list). Per addendum R2's
          explicit scope trade ("cut leg (iii), not leg (vi)"), it is not
          duplicated here.

Field mapping (design doc Sec. 2.4, both regimes):
- Counterparty: ``entity_type="individual"`` (a ``NATURAL_PERSON_ENTITY_TYPES``
  member), ``is_natural_person=True``, ``is_managed_as_retail=True`` (Art.
  123A(1)(b)(iii) pool-management attestation -- isolates the QRRE gates from
  the owed-amount retail-qualification test, matching ``p1_191``/``p1_244``),
  ``default_status=False``.
- Facility: ``is_revolving=True``, ``is_secured=False``, ``committed=True``,
  ``risk_type="LR"`` (unconditionally cancellable) unless a leg specifically
  needs a non-cancellable sub, ``is_qrre_transactor=False`` explicitly (so
  admitted rows take the higher, conservative ``pd_floors.retail_qrre_revolver``
  floor rather than silently exercising the transactor path).
- Loan: ``risk_type="LR"`` set explicitly ON THE LOAN ROW ITSELF, not only the
  facility -- ``risk_type`` is NOT in
  ``enrich.py::_join_facility_qrre_columns``'s coupled-column set, so the
  facility does not supply it to the loan leg (the
  ``reporting_irb_classes_portfolio.py:83`` docstring claim that it does is
  wrong). In practice ``unify.py`` nulls a drawn loan's ``risk_type`` and
  forces its ``undrawn_amount`` to 0.0 regardless (the cancellability limb is
  then trivially satisfied), so the input value is inert for THIS scenario's
  outcome -- it is set anyway to keep every fixture row schema-honest and to
  match the explicit brief.

References:
- CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c): QRRE per-individual aggregate.
- ``src/rwa_calc/engine/hierarchy/facility_undrawn.py``: MOF waterfall
  expansion -- ``facility_limit`` on every waterfall/residual row is the
  ROOT's own ``limit`` field, never the sub's (``:561``); ``risk_type`` is
  ``coalesce(mof_risk_type, risk_type)`` so a waterfall row takes its OWN
  sub's risk_type (``:512-515``); ``is_secured``/``is_revolving``/
  ``is_qrre_transactor`` are the PARENT's (ROOT's) own values, not per-sub
  (``:554-560``).
- ``src/rwa_calc/engine/hierarchy/unify.py``: ``parent_facility_reference
  = coalesce(mapped_parent_facility, source_facility_reference)``; a
  facility_undrawn row's ``source_facility_reference`` is the row's own
  ``facility_reference`` (the ROOT for MOF waterfall/residual rows).
- ``.claude/state/outputs/P1.320-scenario.md`` -- the full design, including
  the Wave 1 ADDENDUM this fixture implements.

Usage:
    from tests.fixtures.p1_320.p1_320 import build_p1_320_raw_bundle
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
# Scenario identity constants -- one counterparty per leg (isolated aggregates)
# ---------------------------------------------------------------------------

#: Leg (i) — headroom mover.
CP_Q2: str = "P1320_CP_Q2"
FAC_Q2: str = "P1320_FAC_Q2"
LN_Q2: str = "P1320_LN_Q2"
EXP_Q2_UNDRAWN: str = FAC_Q2 + "_UNDRAWN"

#: Leg (ii) — multi-loan mover, no ``_UNDRAWN`` leg.
CP_Q3: str = "P1320_CP_Q3"
FAC_Q3: str = "P1320_FAC_Q3"
LN_Q3A: str = "P1320_LN_Q3A"
LN_Q3B: str = "P1320_LN_Q3B"

#: Leg (iv) — fully-drawn live-cell control (unchanged before and after).
CP_Q1: str = "P1320_CP_Q1"
FAC_Q1: str = "P1320_FAC_Q1"
LN_Q1: str = "P1320_LN_Q1"

#: Leg (v) — MOF key pin (leg-multiplication grain only; see module docstring).
CP_MOF: str = "P1320_CP_MOF"
FAC_MOF: str = "P1320_FAC_MOF"
FAC_MOF_SUB: str = "P1320_FAC_MOF_SUB"
LN_MOF: str = "P1320_LN_MOF"
EXP_MOF_SUB_UNDRAWN: str = FAC_MOF + "_UNDRAWN_" + FAC_MOF_SUB
EXP_MOF_RESIDUAL: str = FAC_MOF + "_UNDRAWN_RESIDUAL"

#: Leg (vi) — MIXED candidate/non-candidate facility group (addendum R2).
CP_MIX: str = "P1320_CP_MIX"
FAC_MIX_ROOT1: str = "P1320_FAC_MIX_ROOT1"
FAC_MIX_R1_SUBA: str = "P1320_FAC_MIX_R1_SUBA"  # LR — QRRE candidate
FAC_MIX_R1_SUBB: str = "P1320_FAC_MIX_R1_SUBB"  # FR — NOT a candidate
FAC_MIX_ROOT2: str = "P1320_FAC_MIX_ROOT2"
FAC_MIX_R2_SUBA: str = "P1320_FAC_MIX_R2_SUBA"  # LR — QRRE candidate
FAC_MIX_R2_SUBB: str = "P1320_FAC_MIX_R2_SUBB"  # FR — NOT a candidate
EXP_MIX_R1_SUBA_UNDRAWN: str = FAC_MIX_ROOT1 + "_UNDRAWN_" + FAC_MIX_R1_SUBA
EXP_MIX_R1_SUBB_UNDRAWN: str = FAC_MIX_ROOT1 + "_UNDRAWN_" + FAC_MIX_R1_SUBB
EXP_MIX_R2_SUBA_UNDRAWN: str = FAC_MIX_ROOT2 + "_UNDRAWN_" + FAC_MIX_R2_SUBA
EXP_MIX_R2_SUBB_UNDRAWN: str = FAC_MIX_ROOT2 + "_UNDRAWN_" + FAC_MIX_R2_SUBB

# ---------------------------------------------------------------------------
# Scenario monetary constants (GBP) -- fixture INPUTS, not regulatory values.
# The QRRE ceiling itself is deliberately NOT typed here (LESSONS A4 /
# addendum R9) -- read it via
# ``regulatory_threshold(pack, "qrre_max_limit", config.eur_gbp_rate)``.
# ---------------------------------------------------------------------------

#: Leg (i)/(ii) facility limit. Chosen so 45,000 < limit <= 87,320: doubled
#: (pre-fix, 2 legs) it exceeds BOTH regime ceilings; singled (post-fix) it
#: clears BOTH. Deliberately NOT the pre-existing QRRE_LIMIT=45,000 constant
#: (``reporting_irb_classes_portfolio.py``), which sits exactly on the CRR/B31
#: split boundary (LESSONS C7).
QRRE2_LIMIT: float = 60_000.0
Q2_DRAWN: float = 20_000.0  # leg (i): headroom = 60,000 - 20,000 = 40,000
Q3A_DRAWN: float = 30_000.0  # leg (ii): two loans sum to the full limit
Q3B_DRAWN: float = 30_000.0

#: Leg (iv) — below both ceilings on a single leg either way.
Q1_LIMIT: float = 40_000.0
Q1_DRAWN: float = 40_000.0  # fully drawn -> no _UNDRAWN leg

#: Leg (v) — MOF root/sub/loan.
MOF_ROOT_LIMIT: float = 70_000.0
MOF_SUB_LIMIT: float = 25_000.0
MOF_LOAN_DRAWN: float = 10_000.0

#: Leg (vi) — MOF root/sub, no loans (fully undrawn). Sub headrooms sum
#: EXACTLY to the root's own headroom so both waterfall rows are emitted in
#: full and no residual row appears.
MIX_ROOT_LIMIT: float = 50_000.0
MIX_SUBA_LIMIT: float = 30_000.0  # LR, candidate
MIX_SUBB_LIMIT: float = 20_000.0  # FR, non-candidate

VALUE_DATE: date = date(2027, 1, 4)
MATURITY_DATE: date = date(2030, 1, 4)


# ---------------------------------------------------------------------------
# Schemas (mirrors ``tests/fixtures/p1_244/p1_244.py`` — the closest sibling)
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

_MAPPING_SCHEMA: dict[str, PolarsDataType] = {
    "parent_facility_reference": pl.String,
    "child_reference": pl.String,
    "child_type": pl.String,
}

_EMPTY_LENDING_MAPPINGS = pl.LazyFrame(
    schema={
        "parent_counterparty_reference": pl.String,
        "child_counterparty_reference": pl.String,
    }
)


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------


def _counterparty(counterparty_reference: str, name: str) -> dict[str, object]:
    """Return one natural-person, pool-managed retail counterparty row.

    ``is_managed_as_retail=True`` satisfies the Art. 123A(1)(b)(iii) pool-
    management limb so ``qualifies_as_retail`` does not depend on the owed
    amount, isolating the QRRE (c) aggregate-limit gate under test — the same
    isolation ``p1_191``/``p1_244`` use.
    """
    return {
        "counterparty_reference": counterparty_reference,
        "counterparty_name": name,
        "entity_type": "individual",
        "country_code": "GB",
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": True,
        "is_natural_person": True,
        "annual_revenue": 0.0,
        "total_assets": 0.0,
    }


def _facility(
    facility_reference: str,
    counterparty_reference: str,
    *,
    limit: float,
    risk_type: str = "LR",
    is_secured: bool = False,
    committed: bool = True,
    is_revolving: bool = True,
) -> dict[str, object]:
    """Return one revolving retail facility row.

    ``is_qrre_transactor=False`` explicitly, so a newly-admitted row takes
    the higher, conservative ``pd_floors.retail_qrre_revolver`` floor rather
    than silently exercising the transactor path (design doc Sec. 2.4).
    """
    return {
        "facility_reference": facility_reference,
        "counterparty_reference": counterparty_reference,
        "currency": "GBP",
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
        "limit": limit,
        "committed": committed,
        "is_revolving": is_revolving,
        "is_qrre_transactor": False,
        "is_secured": is_secured,
        "seniority": "senior",
        "risk_type": risk_type,
        "product_type": "revolving_credit_facility",
        "book_code": "BANKING",
    }


def _loan(
    loan_reference: str,
    counterparty_reference: str,
    *,
    drawn_amount: float,
) -> dict[str, object]:
    """Return one drawn revolving retail loan row.

    ``risk_type="LR"`` is set on the loan row itself per the design's field
    mapping (Sec. 2.4) — the facility does NOT supply ``risk_type`` to a loan
    leg (``enrich.py::_join_facility_qrre_columns`` couples only
    ``is_revolving`` / ``is_qrre_transactor`` / ``is_secured`` / ``limit`` /
    ``facility_termination_date``). ``unify.py`` nulls a drawn loan's own
    ``risk_type`` and forces ``undrawn_amount`` to 0.0 regardless, so this
    value does not change THIS scenario's classification outcome — it is set
    to keep the row schema-honest and match the brief exactly.
    """
    return {
        "loan_reference": loan_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "revolving_credit_facility",
        "book_code": "BANKING",
        "currency": "GBP",
        "drawn_amount": drawn_amount,
        "lgd": 0.5,
        "seniority": "senior",
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
        "risk_type": "LR",
    }


def _mapping(
    parent_facility_reference: str, child_reference: str, child_type: str
) -> dict[str, object]:
    return {
        "parent_facility_reference": parent_facility_reference,
        "child_reference": child_reference,
        "child_type": child_type,
    }


# ---------------------------------------------------------------------------
# Frame assembly
# ---------------------------------------------------------------------------


def _counterparties() -> pl.LazyFrame:
    rows = [
        _counterparty(CP_Q2, "P1.320 Headroom Mover"),
        _counterparty(CP_Q3, "P1.320 Multi-Loan Mover"),
        _counterparty(CP_Q1, "P1.320 Fully-Drawn Control"),
        _counterparty(CP_MOF, "P1.320 MOF Key Pin"),
        _counterparty(CP_MIX, "P1.320 Mixed Candidate Group"),
    ]
    return pl.LazyFrame(rows, schema=_CP_SCHEMA)


def _facilities() -> pl.LazyFrame:
    rows = [
        # --- (i) headroom mover: FAC_Q2 60,000, LN_Q2 drawn 20,000 -----------
        _facility(FAC_Q2, CP_Q2, limit=QRRE2_LIMIT),
        # --- (ii) multi-loan mover: FAC_Q3 60,000, 2 fully-drawn loans -------
        _facility(FAC_Q3, CP_Q3, limit=QRRE2_LIMIT),
        # --- (iv) fully-drawn live-cell control: FAC_Q1 40,000 --------------
        _facility(FAC_Q1, CP_Q1, limit=Q1_LIMIT),
        # --- (v) MOF key pin: root 70,000 / sub 25,000 -----------------------
        _facility(FAC_MOF, CP_MOF, limit=MOF_ROOT_LIMIT),
        _facility(FAC_MOF_SUB, CP_MOF, limit=MOF_SUB_LIMIT),
        # --- (vi) MIXED candidate/non-candidate group: 2 roots x 2 subs -----
        _facility(FAC_MIX_ROOT1, CP_MIX, limit=MIX_ROOT_LIMIT),
        _facility(FAC_MIX_R1_SUBA, CP_MIX, limit=MIX_SUBA_LIMIT, risk_type="LR"),
        _facility(FAC_MIX_R1_SUBB, CP_MIX, limit=MIX_SUBB_LIMIT, risk_type="FR"),
        _facility(FAC_MIX_ROOT2, CP_MIX, limit=MIX_ROOT_LIMIT),
        _facility(FAC_MIX_R2_SUBA, CP_MIX, limit=MIX_SUBA_LIMIT, risk_type="LR"),
        _facility(FAC_MIX_R2_SUBB, CP_MIX, limit=MIX_SUBB_LIMIT, risk_type="FR"),
    ]
    return pl.LazyFrame(rows, schema=_FAC_SCHEMA)


def _loans() -> pl.LazyFrame:
    rows = [
        _loan(LN_Q2, CP_Q2, drawn_amount=Q2_DRAWN),
        _loan(LN_Q3A, CP_Q3, drawn_amount=Q3A_DRAWN),
        _loan(LN_Q3B, CP_Q3, drawn_amount=Q3B_DRAWN),
        _loan(LN_Q1, CP_Q1, drawn_amount=Q1_DRAWN),
        _loan(LN_MOF, CP_MOF, drawn_amount=MOF_LOAN_DRAWN),
    ]
    return pl.LazyFrame(rows, schema=_LOAN_SCHEMA)


def _facility_mappings() -> pl.LazyFrame:
    rows = [
        # (i) headroom mover
        _mapping(FAC_Q2, LN_Q2, "loan"),
        # (ii) multi-loan mover
        _mapping(FAC_Q3, LN_Q3A, "loan"),
        _mapping(FAC_Q3, LN_Q3B, "loan"),
        # (iv) fully-drawn control
        _mapping(FAC_Q1, LN_Q1, "loan"),
        # (v) MOF key pin: root -> sub (facility), sub -> loan
        _mapping(FAC_MOF, FAC_MOF_SUB, "facility"),
        _mapping(FAC_MOF_SUB, LN_MOF, "loan"),
        # (vi) MIXED group: each root -> its two subs (facility), no loans
        _mapping(FAC_MIX_ROOT1, FAC_MIX_R1_SUBA, "facility"),
        _mapping(FAC_MIX_ROOT1, FAC_MIX_R1_SUBB, "facility"),
        _mapping(FAC_MIX_ROOT2, FAC_MIX_R2_SUBA, "facility"),
        _mapping(FAC_MIX_ROOT2, FAC_MIX_R2_SUBB, "facility"),
    ]
    return pl.LazyFrame(rows, schema=_MAPPING_SCHEMA)


def build_p1_320_raw_bundle() -> RawDataBundle:
    """Return the P1.320 RawDataBundle carrying every classification leg.

    Legs (i), (ii), (iv), (v), (vi) — see the module docstring for the full
    inventory and the arithmetic each leg is designed to exhibit. Each leg
    sits on its own distinct counterparty (or, for (v)/(vi), a counterparty
    used ONLY by that leg's own facilities), so the per-individual QRRE
    aggregates are isolated and no leg's outcome depends on another's.
    """
    return make_raw_bundle(
        facilities=_facilities(),
        loans=_loans(),
        counterparties=_counterparties(),
        facility_mappings=_facility_mappings(),
        lending_mappings=_EMPTY_LENDING_MAPPINGS,
    )
