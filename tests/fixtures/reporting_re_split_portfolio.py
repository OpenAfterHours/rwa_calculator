"""
Real-estate loan-split reporting portfolio — the oracle for the SPLIT-LEG axis.

Pipeline position:
    build_reporting_re_split_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Why a SEVENTH portfolio (rather than extending ``reporting_portfolio.py``):
across all twelve registered golden runs — six portfolios x two regimes — the
measured count of rows carrying a non-null ``split_parent_id`` is **zero**. The
real-estate loan-splitter fans one exposure into a secured leg plus a residual
leg, and no committed reporting fixture has ever produced one of those legs, so
no COREP or Pillar 3 cell has ever been observed carrying split output. That is
the negative space ``.claude/LESSONS.md`` B5 describes: the absence of a defect
report on the split legs is *caused by* the absence of coverage.

``reporting_portfolio.py``'s docstring claims its RRE/CRE collateral drives the
loan-split. It does not, and the mechanism is worth writing down because it is
silent: the splitter's candidate gate is set by
``engine/re_split/flagging.py``, which reads
``residential_collateral_value_uncapped`` / ``commercial_collateral_value_uncapped``
— derived in ``engine/hierarchy/enrich.py::enrich_with_property_coverage``
from collateral rows whose ``collateral_type`` is literally ``"real_estate"``
AND whose ``property_type`` says which limb they are. Without the property
attestation columns the classifier leaves ``re_split_mode`` NULL, the splitter
passes the row straight through, and a test written against that portfolio
passes while proving nothing. **Every collateral row here therefore attests
``collateral_type="real_estate"`` plus ``property_type`` / ``is_qualifying_re``
/ ``property_ltv``.**

Composition — every row exists to reach one named split shape, in BOTH regimes.
The regime pair is the point: CRR Art. 125/126 caps the secured leg at an LTV of
``re_split_rre_secured_ltv_cap`` / ``re_split_cre_secured_ltv_cap`` with no
prior-charge deduction, and PS1/26 Art. 124F/124H replaces both caps with a
single ratio applied to raw property value, *less* prior charges (Art. 124F(2)).
So the same row can and does split at a different point between the two.

    ref                 | obligor | property        | CRR legs       | B3.1 legs
    --------------------|---------|-----------------|----------------|----------------
    LN_ANCHOR           | CORP    | none            | 1 (no split)   | 1 (no split)
    LN_RRE_EXACT        | CORP    | RRE = exposure  | secured+resid  | secured+resid
    LN_RRE_UNDER        | CORP    | RRE < exposure  | secured+resid  | secured+resid
    LN_RRE_OVER         | CORP    | RRE > exposure  | secured+0 res  | secured+0 res
    LN_RRE_PRIOR        | CORP    | RRE, prior chg  | secured+resid  | secured+resid
    LN_CRE_SME          | SME     | CRE             | 1 (see below)  | secured+resid
    LN_CRE_CORP         | CORP    | CRE             | 1 (see below)  | whole
    LN_MIXED            | CORP    | RRE + CRE       | secured+resid  | rre+cre+resid

    -> re_split_role   CRR : secured, residual
                       B3.1: secured, residual, secured_rre, secured_cre, whole

``LN_RRE_PRIOR`` is the load-bearing row: it is the ONLY place the two regimes
disagree about *where* an otherwise identical exposure splits. CRR Art. 125
recognises no prior charge at all, so its secured leg is identical to
``LN_RRE_EXACT``'s; PS1/26 Art. 124F(2) subtracts the prior-charge ratio from the
secured cap, so under Basel 3.1 the secured leg shrinks and the residual grows by
the same amount. A splitter that dropped the prior-charge reduction would move
this row alone, and no other fixture in the estate would notice.

``LN_ANCHOR`` is the other half of the LESSONS B5 two-leg pattern. It is an
ordinary drawn corporate loan with no property at all, and it lands on the SAME
C 07.00 ``corporate`` sheet and the SAME Pillar 3 CR4 row 7 as every residual
leg. A change to how split legs carry their gross-exposure columns moves the
split component of those cells while ``LN_ANCHOR``'s component stays put — so a
test over them can tell "the fix worked" from "the fix zeroed the cell", which a
portfolio of nothing but split rows cannot.

``LN_MIXED`` is the only row that reaches ``secured_rre`` / ``secured_cre``: the
splitter emits the paired roles only when BOTH components allocate a non-zero
secured EAD, which needs one exposure carrying two property pledges of different
types. It also exercises the two regimes' different mixed-RE allocation rules —
PS1/26 Art. 124(4) pro-rata by collateral value against CRR Art. 124(1)'s
"any part of an exposure" RRE-first sequence.

``LN_CRE_SME`` carries an SME revenue figure deliberately, and it is the only
route to a Basel 3.1 CRE *split*: PS1/26 Art. 124H(1)-(2) loan-splits commercial
real estate for natural persons and SMEs, while Art. 124H(3) sends every other
counterparty down the whole-loan ``max(floor, min(cp_rw, income-producing RW))``
path instead. ``LN_CRE_CORP`` is the same exposure on a non-SME obligor and is
the only route to ``re_split_role == "whole"``. A natural person cannot stand in
for the SME here: an individual with property collateral is classified
RETAIL_MORTGAGE upstream, and the splitter's candidate gate excludes rows that
are already in a real-estate class.

**MEASURED ENGINE GAP — the CRR commercial limb does not split end to end.**
Both CRE rows attest ``rental_to_interest_ratio``, because CRR Art. 126(2)(d)
makes the preferential commercial treatment conditional on rental income
covering interest costs, and a fixture that omitted it would be describing an
ineligible exposure. Attesting it is nevertheless not enough today:
``rental_to_interest_ratio`` is declared on ``COLLATERAL_SCHEMA`` but on no edge
contract, so ``HIERARCHY_EXIT_EDGE.conform`` strips it before the classifier
runs, ``flagging.py``'s presence guard falls to its conservative
``pl.lit(False)`` branch, and ``cre_eligible`` is False for every CRR row in
every portfolio. The consequence is measured, not inferred: under CRR neither
CRE row fans out (the pipeline raises ``RE004`` for both), and ``LN_MIXED``
degenerates to an RRE-only split. The two unsplit CRE loans still REPORT on the
``commercial_mortgage`` sheet — Art. 112(1)(i) keys the reporting class on the
security, so ``reporting_class_origin`` diverges from ``exposure_class`` there,
which is why the expected-leg tables below carry both. The rows are kept, and
the test file marks the CRR CRE split ``xfail(strict=True)``, so the day the
carrier survives the seal the fixture already describes the right exposure and
the xfail flips rather than the coverage having to be invented then.

Deliberately OUT of scope (each would add a row without adding a split shape):
- Income-producing / buy-to-let real estate (PS1/26 Art. 124G / 124I whole-loan
  LTV bands). ``is_income_producing`` excludes a row from split candidacy
  altogether, so such a row could not reach a split leg — it belongs with the
  RE risk-weight fixtures, not here.
- ADC (PS1/26 Art. 124K). Also excluded from candidacy by design, so that the
  ADC weight applies to the whole exposure.
- Non-qualifying RE and the PS1/26 Art. 124(4) all-or-nothing gate
  (``re_split_force_other_re``). It is a mixed-RE variant of ``LN_MIXED`` whose
  distinguishing output is the Art. 124J risk weight rather than a new split
  shape, and it has unit coverage already.
- Defaulted split candidates. Art. 127 takes priority in the class waterfall and
  the candidate gate excludes ``is_defaulted``, so there is no split to report.
- IRB. Loan-splitting is a Standardised Approach mechanism (CRR Art. 125/126 and
  PS1/26 Art. 124F/124H all sit in the SA Part), and the splitter passes non-SA
  rows through untouched. The portfolio therefore runs
  ``PermissionMode.STANDARDISED``.

References:
- CRR Art. 124(1): "any part of an exposure" framing for partial security
- CRR Art. 125: residential mortgage preferential RW up to the secured LTV cap
- CRR Art. 126(2)(d): commercial RE — rental income must cover interest costs
- PRA PS1/26 Art. 124(4): mixed RRE+CRE pro-rata allocation by collateral value
- PRA PS1/26 Art. 124F / 124F(2): B3.1 RRE loan-split and its prior-charge deduction
- PRA PS1/26 Art. 124H(1)-(2) / 124H(3): B3.1 CRE loan-split vs whole-loan path
- PRA PS1/26 Art. 124L: residual leg risk weight by counterparty type
- COREP Annex II, C 07.00: SA exposure classes — one sheet per class, so the
  secured legs open ``residential_mortgage`` / ``commercial_mortgage`` sheets
- Pillar 3 CR4 rows 7 / 9 / 17 and CR5 rows 9f / 9g (Basel 3.1 only)
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    LOAN_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: Large corporate: above the SME revenue ceiling, so no supporting factor
#: perturbs the residual leg and PS1/26 Art. 124H(3) (not 124H(1)-(2)) governs
#: its commercial real estate.
CP_CORP: str = "RESP-CP-CORP"

#: SME corporate: below the SME revenue ceiling, so ``is_sme`` is True and
#: PS1/26 Art. 124H(1)-(2) loan-splits its commercial real estate.
CP_SME: str = "RESP-CP-SME"

LN_ANCHOR: str = "RESP-LN-ANCHOR"  # no property — the unsplit survivor
LN_RRE_EXACT: str = "RESP-LN-RRE-EXACT"  # property value == exposure
LN_RRE_UNDER: str = "RESP-LN-RRE-UNDER"  # property value < exposure
LN_RRE_OVER: str = "RESP-LN-RRE-OVER"  # property value > exposure
LN_RRE_PRIOR: str = "RESP-LN-RRE-PRIOR"  # prior charge ranking ahead of us
LN_CRE_SME: str = "RESP-LN-CRE-SME"  # B3.1 Art. 124H(1)-(2) split
LN_CRE_CORP: str = "RESP-LN-CRE-CORP"  # B3.1 Art. 124H(3) whole loan
LN_MIXED: str = "RESP-LN-MIXED"  # RRE + CRE on one exposure

#: Suffixes the splitter appends to ``exposure_reference`` per leg
#: (``engine/re_split/splitter.py::_secured_columns`` / ``_residual_columns``).
SECURED_SUFFIX: str = "_sec"
RESIDUAL_SUFFIX: str = "_res"
MIXED_RRE_SUFFIX: str = "_rre"
MIXED_CRE_SUFFIX: str = "_cre"

#: Drawn balances, in GBP. Distinct per row so a mis-allocated leg is
#: identifiable from a single template cell value.
DRAWN_ANCHOR: float = 1_000_000.0
DRAWN_RRE_EXACT: float = 1_000_000.0
DRAWN_RRE_UNDER: float = 2_000_000.0
DRAWN_RRE_OVER: float = 500_000.0
DRAWN_RRE_PRIOR: float = 1_000_000.0
DRAWN_CRE_SME: float = 1_000_000.0
DRAWN_CRE_CORP: float = 1_000_000.0
DRAWN_MIXED: float = 2_000_000.0

#: Property market values, in GBP.
VALUE_RRE_EXACT: float = 1_000_000.0
VALUE_RRE_UNDER: float = 1_000_000.0
VALUE_RRE_OVER: float = 1_000_000.0
VALUE_RRE_PRIOR: float = 1_000_000.0
VALUE_CRE_SME: float = 1_500_000.0
VALUE_CRE_CORP: float = 1_500_000.0
VALUE_MIXED_RRE: float = 1_000_000.0
VALUE_MIXED_CRE: float = 1_000_000.0

#: PS1/26 Art. 124F(2): the ratio of a charge ranking ahead of ours, deducted
#: from the Basel 3.1 secured cap. CRR Art. 125 has no equivalent deduction.
PRIOR_CHARGE_LTV: float = 0.20

#: CRR Art. 126(2)(d) attestation: rental income as a multiple of interest
#: costs. Set comfortably above the engine's threshold so the row is about the
#: split, not about a boundary.
RENTAL_TO_INTEREST_RATIO: float = 2.0

#: Below the SME revenue ceiling, so the classifier sets ``is_sme``.
SME_REVENUE: float = 20_000_000.0
#: Above it, so ``CP_CORP`` is a plain corporate.
LARGE_REVENUE: float = 250_000_000.0

#: Total drawn balance the portfolio puts into the pipeline. The split
#: conserves EAD, never the gross carriers, so this is the figure every
#: ``sum(ead_final)`` assertion ties back to.
TOTAL_DRAWN: float = (
    DRAWN_ANCHOR
    + DRAWN_RRE_EXACT
    + DRAWN_RRE_UNDER
    + DRAWN_RRE_OVER
    + DRAWN_RRE_PRIOR
    + DRAWN_CRE_SME
    + DRAWN_CRE_CORP
    + DRAWN_MIXED
)

#: Parent exposure_reference -> (drawn, residential property value,
#: commercial property value, prior-charge ratio). The design table the tests
#: derive their expected split allocations from, so an added row is covered
#: without editing an assertion.
SPLIT_DESIGN: dict[str, tuple[float, float, float, float]] = {
    LN_ANCHOR: (DRAWN_ANCHOR, 0.0, 0.0, 0.0),
    LN_RRE_EXACT: (DRAWN_RRE_EXACT, VALUE_RRE_EXACT, 0.0, 0.0),
    LN_RRE_UNDER: (DRAWN_RRE_UNDER, VALUE_RRE_UNDER, 0.0, 0.0),
    LN_RRE_OVER: (DRAWN_RRE_OVER, VALUE_RRE_OVER, 0.0, 0.0),
    LN_RRE_PRIOR: (DRAWN_RRE_PRIOR, VALUE_RRE_PRIOR, 0.0, PRIOR_CHARGE_LTV),
    LN_CRE_SME: (DRAWN_CRE_SME, 0.0, VALUE_CRE_SME, 0.0),
    LN_CRE_CORP: (DRAWN_CRE_CORP, 0.0, VALUE_CRE_CORP, 0.0),
    LN_MIXED: (DRAWN_MIXED, VALUE_MIXED_RRE, VALUE_MIXED_CRE, 0.0),
}

#: The parents that must physically fan out into more than one row, per regime.
#: ``LN_ANCHOR`` never splits (no property). The two CRE rows never split under
#: CRR — see the module docstring's MEASURED ENGINE GAP note — and ``LN_CRE_CORP``
#: takes the Art. 124H(3) whole-loan path under Basel 3.1, which reclassifies the
#: single row rather than fanning it out.
SPLIT_PARENTS_CRR: frozenset[str] = frozenset(
    {LN_RRE_EXACT, LN_RRE_UNDER, LN_RRE_OVER, LN_RRE_PRIOR, LN_MIXED}
)
SPLIT_PARENTS_B31: frozenset[str] = SPLIT_PARENTS_CRR | {LN_CRE_SME}

#: ``re_split_role`` values the portfolio must produce, per regime. Asserted as
#: an exact set so a splitter that quietly stopped emitting one of the five is a
#: failure rather than a silently narrower test.
EXPECTED_ROLES_CRR: frozenset[str] = frozenset({"secured", "residual"})
EXPECTED_ROLES_B31: frozenset[str] = frozenset(
    {"secured", "residual", "secured_rre", "secured_cre", "whole"}
)


class ExpectedLeg(NamedTuple):
    """One row the pipeline must emit, and where it must be reported.

    ``exposure_class`` is the risk-weighting class the splitter assigned;
    ``reporting_class`` is the ``reporting_class_origin`` the COREP / Pillar 3
    class axes key on. They differ for the two unsplit CRR commercial loans —
    see the module docstring's MEASURED ENGINE GAP note — and carrying both
    makes that divergence a stated expectation rather than a surprise.
    """

    role: str | None
    exposure_class: str
    reporting_class: str
    ead: float


#: CRR Art. 125 / Art. 126 — every emitted row, hand-derived from
#: ``re_split_rre_secured_ltv_cap`` (secured = min(EAD, cap x property value),
#: with NO prior-charge deduction) and confirmed against a pipeline run.
EXPECTED_LEGS_CRR: dict[str, ExpectedLeg] = {
    LN_ANCHOR: ExpectedLeg(None, "corporate", "corporate", DRAWN_ANCHOR),
    # Art. 126(2)(d) unreachable end-to-end: no split, but the security still
    # keys the reporting class (Art. 112(1)(i)).
    LN_CRE_CORP: ExpectedLeg(None, "corporate", "commercial_mortgage", DRAWN_CRE_CORP),
    LN_CRE_SME: ExpectedLeg(None, "corporate_sme", "commercial_mortgage", DRAWN_CRE_SME),
    LN_RRE_EXACT + SECURED_SUFFIX: ExpectedLeg(
        "secured", "residential_mortgage", "residential_mortgage", 800_000.0
    ),
    LN_RRE_EXACT + RESIDUAL_SUFFIX: ExpectedLeg("residual", "corporate", "corporate", 200_000.0),
    LN_RRE_UNDER + SECURED_SUFFIX: ExpectedLeg(
        "secured", "residential_mortgage", "residential_mortgage", 800_000.0
    ),
    LN_RRE_UNDER + RESIDUAL_SUFFIX: ExpectedLeg("residual", "corporate", "corporate", 1_200_000.0),
    # Cap slack: EAD binds below it, so the residual leg is emitted at zero.
    LN_RRE_OVER + SECURED_SUFFIX: ExpectedLeg(
        "secured", "residential_mortgage", "residential_mortgage", 500_000.0
    ),
    LN_RRE_OVER + RESIDUAL_SUFFIX: ExpectedLeg("residual", "corporate", "corporate", 0.0),
    # Art. 125 recognises no prior charge, so this is LN_RRE_EXACT's split.
    LN_RRE_PRIOR + SECURED_SUFFIX: ExpectedLeg(
        "secured", "residential_mortgage", "residential_mortgage", 800_000.0
    ),
    LN_RRE_PRIOR + RESIDUAL_SUFFIX: ExpectedLeg("residual", "corporate", "corporate", 200_000.0),
    # Art. 124(1) RRE-first sequential; the CRE component contributes nothing
    # because Art. 126(2)(d) cannot be attested, so the pair degenerates to
    # the single-component "secured" role rather than secured_rre/secured_cre.
    LN_MIXED + SECURED_SUFFIX: ExpectedLeg(
        "secured", "residential_mortgage", "residential_mortgage", 800_000.0
    ),
    LN_MIXED + RESIDUAL_SUFFIX: ExpectedLeg("residual", "corporate", "corporate", 1_200_000.0),
}

#: PS1/26 Art. 124F / 124H — every emitted row, hand-derived from
#: ``re_split_rre_secured_ltv_cap`` / ``re_split_cre_secured_ltv_cap`` applied
#: to raw property value LESS ``prior_charge_ltv`` (Art. 124F(2)), pro-rata by
#: collateral value on the mixed row (Art. 124(4)).
EXPECTED_LEGS_B31: dict[str, ExpectedLeg] = {
    LN_ANCHOR: ExpectedLeg(None, "corporate", "corporate", DRAWN_ANCHOR),
    # Art. 124H(3): non-NP/SME pure CRE is reclassified whole, not fanned out.
    LN_CRE_CORP: ExpectedLeg("whole", "commercial_mortgage", "commercial_mortgage", DRAWN_CRE_CORP),
    # Art. 124H(1)-(2): SME CRE splits at 0.55 x 1,500,000 = 825,000.
    LN_CRE_SME + SECURED_SUFFIX: ExpectedLeg(
        "secured", "commercial_mortgage", "commercial_mortgage", 825_000.0
    ),
    LN_CRE_SME + RESIDUAL_SUFFIX: ExpectedLeg(
        "residual", "corporate_sme", "corporate_sme", 175_000.0
    ),
    LN_RRE_EXACT + SECURED_SUFFIX: ExpectedLeg(
        "secured", "residential_mortgage", "residential_mortgage", 550_000.0
    ),
    LN_RRE_EXACT + RESIDUAL_SUFFIX: ExpectedLeg("residual", "corporate", "corporate", 450_000.0),
    LN_RRE_UNDER + SECURED_SUFFIX: ExpectedLeg(
        "secured", "residential_mortgage", "residential_mortgage", 550_000.0
    ),
    LN_RRE_UNDER + RESIDUAL_SUFFIX: ExpectedLeg("residual", "corporate", "corporate", 1_450_000.0),
    LN_RRE_OVER + SECURED_SUFFIX: ExpectedLeg(
        "secured", "residential_mortgage", "residential_mortgage", 500_000.0
    ),
    LN_RRE_OVER + RESIDUAL_SUFFIX: ExpectedLeg("residual", "corporate", "corporate", 0.0),
    # Art. 124F(2): (0.55 - 0.20) x 1,000,000 = 350,000. THE regime divergence.
    LN_RRE_PRIOR + SECURED_SUFFIX: ExpectedLeg(
        "secured", "residential_mortgage", "residential_mortgage", 350_000.0
    ),
    LN_RRE_PRIOR + RESIDUAL_SUFFIX: ExpectedLeg("residual", "corporate", "corporate", 650_000.0),
    # Art. 124(4) pro-rata: each component takes half the EAD, each capped at
    # 0.55 x its own 1,000,000 of property value.
    LN_MIXED + MIXED_RRE_SUFFIX: ExpectedLeg(
        "secured_rre", "residential_mortgage", "residential_mortgage", 550_000.0
    ),
    LN_MIXED + MIXED_CRE_SUFFIX: ExpectedLeg(
        "secured_cre", "commercial_mortgage", "commercial_mortgage", 550_000.0
    ),
    LN_MIXED + RESIDUAL_SUFFIX: ExpectedLeg("residual", "corporate", "corporate", 900_000.0),
}

_VALUE_DATE: date = date(2015, 1, 1)
_MATURITY: date = date(2035, 12, 31)  # beyond both reporting dates (CRR 2025, B31 2027)


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_re_split_bundle() -> RawDataBundle:
    """Assemble the real-estate loan-split reporting portfolio as a sealed bundle.

    Sealed against the loader edge contracts by ``make_raw_bundle``, so it is
    shape-identical to a parquet-loaded production bundle. Run it through
    ``PipelineOrchestrator().run_with_data`` under either regime with
    ``PermissionMode.STANDARDISED`` — loan-splitting is a Standardised Approach
    mechanism and the splitter passes IRB rows through untouched.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        collateral=_collateral(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """One large corporate and one SME corporate.

    Two obligors, not one, because the Basel 3.1 commercial limb branches on
    exactly this distinction: PS1/26 Art. 124H(1)-(2) loan-splits CRE for
    natural persons and SMEs, Art. 124H(3) sends everyone else down the
    whole-loan path. One obligor could reach only one of those.

    Both are UNRATED — no ratings table is supplied at all. That is deliberate:
    the residual leg then takes the unrated counterparty weight, so a moved
    number in a template cell is the split allocation and never a CQS lookup.
    """
    rows: list[dict] = [
        {
            "counterparty_reference": CP_CORP,
            "counterparty_name": CP_CORP,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": LARGE_REVENUE,
            "default_status": False,
        },
        {
            "counterparty_reference": CP_SME,
            "counterparty_name": CP_SME,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": SME_REVENUE,
            "default_status": False,
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _loans() -> pl.DataFrame:
    """Eight drawn term loans — one per split shape, plus the unsplit anchor.

    All on balance sheet and fully drawn: the split allocates ``ead_final``, and
    an off-balance-sheet leg would put a conversion factor between the drawn
    amount and the number being allocated. The conversion-factor axis has its
    own portfolio (``reporting_offbs_portfolio.py``).
    """
    rows: list[dict] = [
        _loan(LN_ANCHOR, CP_CORP, DRAWN_ANCHOR),
        _loan(LN_RRE_EXACT, CP_CORP, DRAWN_RRE_EXACT),
        _loan(LN_RRE_UNDER, CP_CORP, DRAWN_RRE_UNDER),
        _loan(LN_RRE_OVER, CP_CORP, DRAWN_RRE_OVER),
        _loan(LN_RRE_PRIOR, CP_CORP, DRAWN_RRE_PRIOR),
        _loan(LN_CRE_SME, CP_SME, DRAWN_CRE_SME),
        _loan(LN_CRE_CORP, CP_CORP, DRAWN_CRE_CORP),
        _loan(LN_MIXED, CP_CORP, DRAWN_MIXED),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _loan(ref: str, cp_ref: str, drawn: float) -> dict:
    return {
        "loan_reference": ref,
        "counterparty_reference": cp_ref,
        "product_type": "term_loan",
        "drawn_amount": drawn,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
        "is_defaulted": False,
    }


def _collateral() -> pl.DataFrame:
    """Nine property pledges — one per collateralised loan, two for ``LN_MIXED``.

    Every row is pledged DIRECTLY to its loan (``beneficiary_type="loan"``), so
    the ``direct`` limb of the hierarchy resolver's three-level collateral
    lookup is the one under test and no allocation weight sits between the
    pledge and the split.
    """
    rows: list[dict] = [
        _property(LN_RRE_EXACT, "residential", VALUE_RRE_EXACT, DRAWN_RRE_EXACT),
        _property(LN_RRE_UNDER, "residential", VALUE_RRE_UNDER, DRAWN_RRE_UNDER),
        _property(LN_RRE_OVER, "residential", VALUE_RRE_OVER, DRAWN_RRE_OVER),
        _property(
            LN_RRE_PRIOR,
            "residential",
            VALUE_RRE_PRIOR,
            DRAWN_RRE_PRIOR,
            prior_charge_ltv=PRIOR_CHARGE_LTV,
        ),
        _property(
            LN_CRE_SME,
            "commercial",
            VALUE_CRE_SME,
            DRAWN_CRE_SME,
            rental_to_interest_ratio=RENTAL_TO_INTEREST_RATIO,
        ),
        _property(
            LN_CRE_CORP,
            "commercial",
            VALUE_CRE_CORP,
            DRAWN_CRE_CORP,
            rental_to_interest_ratio=RENTAL_TO_INTEREST_RATIO,
        ),
        _property(
            LN_MIXED,
            "residential",
            VALUE_MIXED_RRE,
            DRAWN_MIXED,
            suffix="-RRE",
        ),
        _property(
            LN_MIXED,
            "commercial",
            VALUE_MIXED_CRE,
            DRAWN_MIXED,
            suffix="-CRE",
            rental_to_interest_ratio=RENTAL_TO_INTEREST_RATIO,
        ),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COLLATERAL_SCHEMA))


def _property(
    loan_ref: str,
    property_type: str,
    market_value: float,
    exposure: float,
    *,
    prior_charge_ltv: float = 0.0,
    rental_to_interest_ratio: float | None = None,
    suffix: str = "",
) -> dict:
    """One qualifying immovable-property pledge on one loan.

    ``collateral_type`` is the literal ``"real_estate"`` the hierarchy
    resolver's property-coverage filter matches on, and ``property_type``
    is what routes the value to the residential or the commercial component.
    Both are load-bearing: with either missing the exposure carries zero
    eligible property value, ``re_split_mode`` stays NULL, and the row is never
    a split candidate (see the module docstring).

    ``is_eligible_financial_collateral`` is False on purpose. CRR Art. 197 is
    the financial-collateral list and immovable property is not on it: under the
    Standardised Approach property is recognised through the Art. 124-126 /
    Art. 124F-124L risk weight, not through the CRM chain. Attesting both would
    route one pledge down two mitigation paths and double-count the benefit —
    the same double-count ``reporting/corep/c07.py`` records for col 0080.

    ``is_income_producing`` and ``is_adc`` are False on purpose too: either flag
    removes the row from split candidacy entirely (PS1/26 Art. 124G / 124I
    whole-loan bands, Art. 124K ADC), so a portfolio that set them would report
    no split legs at all.
    """
    return {
        "collateral_reference": f"{loan_ref}-COL{suffix}",
        "collateral_type": "real_estate",
        "currency": "GBP",
        "market_value": market_value,
        "nominal_value": market_value,
        "beneficiary_type": "loan",
        "beneficiary_reference": loan_ref,
        "residual_maturity_years": 10.0,
        "original_maturity_years": 20.0,
        "is_eligible_financial_collateral": False,
        "is_eligible_irb_collateral": True,
        "valuation_date": _VALUE_DATE,
        "valuation_type": "market",
        "property_type": property_type,
        "property_ltv": exposure / market_value,
        "is_income_producing": False,
        "is_adc": False,
        "is_presold": False,
        "is_qualifying_re": True,
        "prior_charge_ltv": prior_charge_ltv,
        "rental_to_interest_ratio": rental_to_interest_ratio,
    }
