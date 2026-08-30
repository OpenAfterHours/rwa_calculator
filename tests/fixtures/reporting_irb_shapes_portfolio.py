"""
IRB exposure-SHAPE reporting portfolio — the off-BS, LFSE, defaulted and
Art. 200(1) protection axes of the C 08.xx family.

Pipeline position:
    build_reporting_irb_shapes_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Why a NINTH portfolio (rather than extending ``reporting_irb_classes_portfolio``):
that portfolio owns the IRB *class and PD-band* axes and says so — "every row here
is drawn and unmitigated so a mis-banded exposure shows up in one cell". Adding an
off-balance-sheet leg or a collateral pledge to it would move every one of its
committed goldens and bury the shape question in band churn. This portfolio is the
complement: one obligor per SHAPE, with the class axis held as flat as the shape
allows.

Measured before it existed (``scripts/check_template_cell_coverage.py``, 28-run
matrix, 339 template-column pairs / 210 live): **26** dead columns are dead for
the single reason that no IRB obligor in the estate has the shape. They are not
spread thinly — they are four clusters, and one portfolio reaches all four.

Composition — one row per shape:

    ref              | shape                                   | approach | targets
    -----------------|-----------------------------------------|----------|------------------
    LN_CORP_ONB      | drawn corporate anchor (non-LFSE)       | F-IRB    | the residual control
    CT_CORP_GTEE     | ISSUED off-BS financial guarantee       | F-IRB    | C 08.01/02 0100,0120
    FAC_CORP_OC      | committed line with headroom -> undrawn | F-IRB    | C 08.03 0020,0030; CR6 c,d
    LN_LFSE          | corporate flagged apply_fi_scalar       | F-IRB    | C 08.01/02 0030,0140,0240,0270
    LN_RET_CTRL      | retail_other, NOT defaulted             | A-IRB    | the 0265 live control
    LN_RET_DEF       | retail_other, defaulted, BEEL < LGD     | A-IRB    | C 08.01/02 0265; C 09.02 0120
    LN_LIFE          | retail_other + life-policy pledge       | A-IRB    | C 08.01/02 0170,0172
    LN_FINCOLL       | corporate + cash AND equity pledged     | F-IRB    | CR7-A col b (diagnostic)
    LN_SL / CT_SL    | slotting SL obligor with an off-BS leg  | slotting | C 08.06 0030,0050; CR10 b

THE DEFAULTED CLUSTER'S PREMISE WAS WRONG, AND THE CORRECTION IS THE DESIGN.
The banked baseline records C 08.01/0265, C 08.02/0265 and C 09.02/0120 as
``NO_FIXTURE`` because "no portfolio in the estate defaults an IRB obligor". That
is false: ``reporting_irb_classes_portfolio`` defaults ``CP_RRE_DEF``, and the
sealed frame carries ``is_defaulted=True`` on ``IRC-LN-RRE-DEF``. Measured on that
row under Basel 3.1 IRB, the true reason is different and sharper — its
``rwa_final`` is **exactly 0.00**, because its BEEL equals its LGD so
PS1/26 Art. 154(1)(a) gives ``K = max(0, LGD - BEEL) = 0``, and Art. 154(4A)(b)
confines the mortgage floor add-on to NON-defaulted exposures. A defaulted subset
whose RWEA is structurally zero cannot light an RWEA sub-split however many
defaulted obligors it holds.

So ``LN_RET_DEF`` is deliberately **not** a second defaulted mortgage. It is
``retail_other`` (no property pledge, so Art. 154(4A) is out of scope entirely)
with ``beel`` set strictly BELOW ``lgd``, which leaves ``K > 0`` and a positive
RWEA for the sub-split to sum. ``LN_RET_CTRL`` carries the same obligor grade and
LGD and is NOT defaulted: it is the live control required by ``LESSONS.md`` B5's
2026-08-08 recurrence — one leg that must SURVIVE a narrowing of the defaulted
scope, one that must MOVE — because a single defaulted row leaves the cell at 0.00
afterwards and a test that cannot tell "the split works" from "the split was
zeroed" is not a test of the split.

DELIBERATELY OUT OF SCOPE, and each is a finding rather than an omission:

- **C 08.01/02 col 0171 (cash on deposit in LGD).** Not reachable by any fixture.
  ``engine/crm/third_party_deposit.py`` zeroes ``third_party_deposit_value`` for
  BOTH F-IRB and A-IRB and raises CRM017, so ``ofcp_lgd_cash_deposit`` reports 0.0
  on every IRB leg by construction. ``engine/crm/ofcp_routing.py`` records that
  narrowing that gate is "a SEPARATE, CAPITAL-AFFECTING decision" which feeds the
  Basel 3.1 output floor and "needs its own review and its own regression
  evidence". The baseline's ``NO_FIXTURE`` code is wrong for this column; it is
  ``ENGINE_CANNOT_PRODUCE`` until that review happens.
- **C 08.01/02 col 0173 (instruments held by a third party).** No engine carrier
  at all — already recorded ``ENGINE_CANNOT_PRODUCE``.
- **C 07.00 col 0070 (Financial Collateral Simple Method).** Needs a config
  electing Art. 222, which is ``reporting_funded_protection_portfolio``'s job and
  is blocked on the P1.347 arbitration, not on a fixture.
- **The SA risk-weight buckets (13 columns).** An SA axis; this portfolio is
  IRB-permissioned throughout.

``LN_FINCOLL`` is a DIAGNOSTIC, not a claim. The baseline says of CR7-A col b that
"a fixture pledging eligible financial collateral to an IRB obligor should light
it; if it cannot, the binding is the defect". This row is that experiment stated
as one.

It is F-IRB deliberately, and the first attempt got that wrong in a way worth
recording: pledged to an A-IRB *retail* obligor the cash left
``collateral_financial_value`` at **0.00**, which would have looked like the
engine defect the baseline predicts. It is not — an A-IRB leg's own-estimate LGD
does not read pledged collateral at all (the same reason
``reporting_irb_classes_portfolio`` records its property pledges as
number-neutral). Art. 228's LGD* is the calculation that consumes financial
collateral, and that is the Foundation limb. A diagnostic pointed at the wrong
approach limb answers a different question than the one asked.

The answer, once pointed correctly, is that CR7-A col b is NOT an engine defect —
it needs NON-CASH financial collateral. Cash is recognised (it drives this leg's
LGD* down from the 0.40 supervisory value) but lands in ``collateral_cash_value``,
a sibling carrier to the ``collateral_financial_value`` col b reads. Adding the
equity pledge populates it.

INPUT-DOMAIN FINDING, surfaced while doing so and worth its own bullet: the
loader's accepted ``collateral_type`` set and the CRM engine's recognition set
DISAGREE about debt securities, and no input string satisfies both.
``VALID_COLLATERAL_TYPES`` (``data/schemas.py``) accepts ``bond`` and rejects
``government_bond``; ``FINANCIAL_COLLATERAL_TYPES`` recognises ``government_bond``
and ``corporate_bond`` and has no entry for ``bond``. Measured: a ``bond`` row
passes validation, matches no category, and is silently degraded to unclassified
'other' at NO secured value with only a warning; a ``government_bond`` row is
recognised and populates ``collateral_financial_value`` but fails loader
validation. Note ``tests/fixtures/collateral/collateral.py`` pledges ``bond``
throughout, so the base fixture portfolio's debt-security collateral may be
getting no recognition at all. Not fixed here — this portfolio uses ``equity``,
which is in both sets — but it is exactly the class of gap
``docs/plans/test-space-correctness-proposal.md`` Phase 1 exists to catch.

References:
- CRR Art. 166(8)/(10), Art. 166C/166D: IRB conversion factors on off-BS items
- CRR Art. 153(2) / PS1/26 Art. 153(2): the 1.25x large-financial-sector multiplier
- CRR Art. 178: obligor-level default
- PS1/26 Art. 154(1)(a): defaulted A-IRB K = max(0, LGD - BEEL)
- CRR Art. 200(1)(b): life insurance policies as other funded credit protection
- CRR Art. 153(5): slotting where no internal PD is available
- COREP Annex II, C 08.01/02 cols 0030-0270; C 08.03 cols 0020-0030; C 08.06
- tests/fixtures/reporting_offbs_portfolio.py: the off-BS row idiom this reuses
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CONTINGENTS_SCHEMA,
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

#: Must match ``create_full_irb_model_permissions`` (F-IRB + A-IRB + slotting for
#: every class), or no row routes IRB at all.
_MODEL_ID: str = "TEST_FULL_IRB"

CP_CORP: str = "IRS-CP-CORP"
CP_LFSE: str = "IRS-CP-LFSE"
CP_RET_CTRL: str = "IRS-CP-RET-CTRL"
CP_RET_DEF: str = "IRS-CP-RET-DEF"
CP_LIFE: str = "IRS-CP-LIFE"
CP_FINCOLL: str = "IRS-CP-FINCOLL"
CP_SL: str = "IRS-CP-SL"

LN_CORP_ONB: str = "IRS-LN-CORP-ONB"
LN_LFSE: str = "IRS-LN-LFSE"
LN_RET_CTRL: str = "IRS-LN-RET-CTRL"
LN_RET_DEF: str = "IRS-LN-RET-DEF"
LN_LIFE: str = "IRS-LN-LIFE"
LN_FINCOLL: str = "IRS-LN-FINCOLL"
LN_SL: str = "IRS-LN-SL"

CT_CORP_GTEE: str = "IRS-CT-CORP-GTEE"
CT_SL: str = "IRS-CT-SL"

FAC_CORP_OC: str = "IRS-FAC-CORP-OC"
FAC_SL: str = "IRS-FAC-SL"

#: Internal PDs. Distinct per obligor so a mis-attributed cell is identifiable
#: from a single value without a reverse lookup. All sit comfortably above the
#: Art. 160(1) 0.03% corporate/institution floor so the floor never moves a row
#: between PD bands — this portfolio is about shape, not bands.
PD_CORP: float = 0.0150
PD_LFSE: float = 0.0180
PD_RETAIL: float = 0.0250

#: Own-estimate LGD shared by every A-IRB retail leg, so the RWEA differences
#: between them are attributable to the shape under test and not to LGD.
LGD_RETAIL: float = 0.45

#: Best-estimate expected loss for ``LN_RET_DEF``, set strictly BELOW
#: :data:`LGD_RETAIL` so PS1/26 Art. 154(1)(a) leaves ``K = LGD - BEEL = 0.25``
#: and the row carries a POSITIVE RWEA. This is the whole correction described in
#: the module docstring: the estate's existing defaulted IRB row has BEEL == LGD
#: and therefore exactly zero RWEA, which no RWEA sub-split can see.
BEEL_RET_DEF: float = 0.20

#: Drawn amounts, in GBP. Every one distinct, and none a multiple of another, so
#: a cell that sums the wrong subset is identifiable from its value alone.
DRAWN_CORP_ONB: float = 4_100_000.0
DRAWN_LFSE: float = 3_300_000.0
DRAWN_RET_CTRL: float = 210_000.0
DRAWN_RET_DEF: float = 170_000.0
DRAWN_LIFE: float = 130_000.0
DRAWN_FINCOLL: float = 90_000.0
DRAWN_SL: float = 12_700_000.0

#: Off-balance-sheet nominals. Both are ISSUED items (``is_obs_commitment``
#: defaults False) carrying ``risk_type="FR"`` — full risk, 100% CCF in both
#: regimes — so the pre-conversion and post-conversion cells differ only by the
#: IRB conversion factor and neither is zero.
NOMINAL_CORP_GTEE: float = 2_600_000.0
NOMINAL_SL: float = 5_400_000.0

#: The corporate commitment. Partially consumed by ``LN_CORP_ONB``, so its
#: synthetic undrawn leg is a genuine limit-minus-drawn number rather than the
#: whole limit — which is what makes the C 08.03 col 0030 exposure-weighted
#: average CCF a non-trivial weighted figure rather than a single CCF echoed back.
LIMIT_CORP_OC: float = 7_500_000.0

#: Life-policy surrender value pledged against ``LN_LIFE``. Below the drawn
#: amount so the Art. 200(1)(b) recognition is partial and col 0172 cannot be
#: confused with a full-cover degenerate case.
LIFE_SURRENDER_VALUE: float = 80_000.0

#: Eligible cash pledged against ``LN_FINCOLL``. Recognised — it drives the
#: Art. 228 LGD* down from the 0.40 supervisory value — but it lands in
#: ``collateral_cash_value``, NOT in the ``collateral_financial_value`` carrier
#: CR7-A col b reads. Kept because the LGD* movement is the proof the pledge is
#: live rather than merely present.
FINCOLL_VALUE: float = 55_000.0

#: Main-index equity pledged on the same leg — the actual CR7-A col b probe.
#: Sized differently from the cash so the two carriers can never be confused for
#: one another in a cell value.
EQUITY_VALUE: float = 35_000.0

_VALUE_DATE: date = date(2020, 1, 1)
_MATURITY: date = date(2031, 12, 31)  # > both reporting dates (CRR 2025, B31 2027)

#: The approach each row must resolve to, per regime. No divergence is expected
#: here — unlike the class portfolio, every obligor type in this book keeps its
#: approach across the regime change, so any movement is a regression.
IRB_SHAPES_EXPECTED_APPROACH: dict[str, tuple[str, str]] = {
    # exposure_reference: (CRR approach, Basel 3.1 approach)
    LN_CORP_ONB: ("foundation_irb", "foundation_irb"),
    LN_LFSE: ("foundation_irb", "foundation_irb"),
    LN_RET_CTRL: ("advanced_irb", "advanced_irb"),
    LN_RET_DEF: ("advanced_irb", "advanced_irb"),
    LN_LIFE: ("advanced_irb", "advanced_irb"),
    LN_FINCOLL: ("foundation_irb", "foundation_irb"),
    LN_SL: ("slotting", "slotting"),
}


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_irb_shapes_bundle() -> RawDataBundle:
    """Assemble the IRB exposure-shape portfolio as a sealed bundle.

    Sealed against the loader edge contracts by ``make_raw_bundle``, so it is
    shape-identical to a parquet-loaded production bundle. Run it through
    ``PipelineOrchestrator().run_with_data`` under either regime with
    ``PermissionMode.IRB``.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        facilities=_facilities(),
        facility_mappings=_facility_mappings(),
        contingents=_contingents(),
        ratings=_ratings(),
        model_permissions=create_full_irb_model_permissions(),
        collateral=_collateral(),
        specialised_lending=_specialised_lending(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """One obligor per shape.

    The two corporates sit above the SME ceiling so no supporting factor
    perturbs the cells under test. ``CP_LFSE`` differs from ``CP_CORP`` in
    exactly one attribute — ``apply_fi_scalar`` — so the four LFSE sub-split
    cells can be read as the difference between two otherwise identical obligors.

    The four retail obligors carry ``is_natural_person`` / ``is_managed_as_retail``
    so the Art. 123 retail limbs pass. None of them is pledged residential
    property, so they classify ``retail_other`` rather than ``retail_mortgage``
    and the PS1/26 Art. 154(4A) mortgage floor is out of scope for all of them —
    which is what keeps ``LN_RET_DEF``'s RWEA a pure Art. 154(1)(a) figure.

    ``CP_SL`` carries no ``apply_fi_scalar`` and no revenue: it is routed by the
    specialised-lending table plus the absence of an internal PD.
    """
    rows: list[dict] = [
        {
            "counterparty_reference": CP_CORP,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 400_000_000.0,
        },
        {
            "counterparty_reference": CP_LFSE,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 400_000_000.0,
            # CRR Art. 153(2): the large-financial-sector-entity 1.25x asset
            # correlation multiplier. This is the ONLY carrier the C 08.01/02
            # LFSE sub-split reads (``reporting/corep/c08.py`` gates the four
            # cells on ``cp_apply_fi_scalar == True``), and no other portfolio in
            # the estate sets it True.
            "apply_fi_scalar": True,
        },
        *(
            {
                "counterparty_reference": ref,
                "entity_type": "individual",
                "country_code": "GB",
                "is_natural_person": True,
                "is_managed_as_retail": True,
            }
            for ref in (CP_RET_CTRL, CP_LIFE)
        ),
        # F-IRB, not retail: the Art. 228 LGD* calculation is what consumes
        # eligible financial collateral, and an A-IRB leg's own-estimate LGD does
        # not read it. Measured — pledged to an A-IRB retail obligor the cash left
        # ``collateral_financial_value`` at 0.00, so the CR7-A col b diagnostic
        # would have been answered by the wrong approach limb.
        {
            "counterparty_reference": CP_FINCOLL,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 400_000_000.0,
        },
        {
            "counterparty_reference": CP_RET_DEF,
            "entity_type": "individual",
            "country_code": "GB",
            "is_natural_person": True,
            "is_managed_as_retail": True,
            # CRR Art. 178 obligor-level default. Paired with a BEEL strictly
            # below LGD on the loan, this is what gives the defaulted subset a
            # NON-ZERO RWEA — see the module docstring.
            "default_status": True,
        },
        {
            "counterparty_reference": CP_SL,
            "entity_type": "specialised_lending",
            "country_code": "GB",
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """Internal PD ratings — an internal PD plus a matching permission routes IRB.

    ``CP_SL`` gets ``model_id`` but NO PD, so the F-IRB / A-IRB specialised-lending
    branches are unavailable and the exposure falls to slotting (CRR Art. 153(5)).
    """
    rows: list[dict] = [
        _internal(CP_CORP, pd=PD_CORP),
        _internal(CP_LFSE, pd=PD_LFSE),
        # The control and the defaulted row share one obligor grade, so the RWEA
        # difference between them is attributable to the default treatment alone.
        _internal(CP_RET_CTRL, pd=PD_RETAIL),
        _internal(CP_RET_DEF, pd=PD_RETAIL),
        _internal(CP_LIFE, pd=PD_RETAIL),
        _internal(CP_FINCOLL, pd=PD_RETAIL),
        _internal_no_pd(CP_SL),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans() -> pl.DataFrame:
    """The drawn leg of each shape.

    The two corporates carry no firm LGD estimate, so the A-IRB branch is
    unavailable and they resolve F-IRB on the Art. 161 supervisory LGD. The four
    retail rows carry ``lgd`` + ``has_sufficient_collateral_data`` so they resolve
    A-IRB (retail is A-IRB-only in both regimes).
    """
    rows: list[dict] = [
        _loan(LN_CORP_ONB, CP_CORP, DRAWN_CORP_ONB),
        _loan(LN_LFSE, CP_LFSE, DRAWN_LFSE),
        # The 0265 live control: not defaulted, same grade and LGD as LN_RET_DEF.
        # Its RWEA must stay OUT of the defaulted sub-split and IN the sheet total.
        _loan(
            LN_RET_CTRL,
            CP_RET_CTRL,
            DRAWN_RET_CTRL,
            lgd=LGD_RETAIL,
            has_sufficient_collateral_data=True,
        ),
        # The 0265 demonstration: defaulted via the obligor, with BEEL strictly
        # below LGD so Art. 154(1)(a) leaves K = 0.25 and the RWEA is positive.
        _loan(
            LN_RET_DEF,
            CP_RET_DEF,
            DRAWN_RET_DEF,
            lgd=LGD_RETAIL,
            beel=BEEL_RET_DEF,
            has_sufficient_collateral_data=True,
        ),
        _loan(
            LN_LIFE,
            CP_LIFE,
            DRAWN_LIFE,
            lgd=LGD_RETAIL,
            has_sufficient_collateral_data=True,
        ),
        # No firm LGD estimate, so this resolves F-IRB and the Art. 228 LGD*
        # calculation consumes the pledged cash — the CR7-A col b diagnostic.
        _loan(LN_FINCOLL, CP_FINCOLL, DRAWN_FINCOLL),
        # Slotting: SL row + slotting permission + no internal PD.
        _loan(LN_SL, CP_SL, DRAWN_SL),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _contingents() -> pl.DataFrame:
    """Two ISSUED off-balance-sheet items — the IRB and slotting off-BS legs.

    ``is_obs_commitment`` defaults False (an issued item, not a commitment) and
    ``bs_type="OFB"`` keeps the nominal off balance sheet so it flows through the
    conversion-factor stage. Both carry ``risk_type="FR"`` so the CCF is 100% in
    both regimes and the regime pair cannot move them between buckets — this
    portfolio is about the off-BS *columns* existing at all, not about which
    bucket they land in (``reporting_offbs_portfolio`` owns the bucket axis).

    ``CT_SL`` is what lights the C 08.06 / CR10 slotting off-BS columns: those
    are a separate population from the IRB ones and no slotting obligor in the
    estate had an off-balance-sheet leg.
    """
    rows: list[dict] = [
        {
            "contingent_reference": CT_CORP_GTEE,
            "counterparty_reference": CP_CORP,
            "product_type": "financial_guarantee",
            "nominal_amount": NOMINAL_CORP_GTEE,
            "risk_type": "FR",
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "bs_type": "OFB",
        },
        {
            "contingent_reference": CT_SL,
            "counterparty_reference": CP_SL,
            "product_type": "financial_guarantee",
            "nominal_amount": NOMINAL_SL,
            "risk_type": "FR",
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "bs_type": "OFB",
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(CONTINGENTS_SCHEMA))


def _facilities() -> pl.DataFrame:
    """Two COMMITMENTS, each emitting one synthetic ``<facility>_UNDRAWN`` leg.

    Both are ``committed=True``: an uncommitted facility emits no undrawn
    exposure at all (``engine/hierarchy/facility_undrawn.py`` filters it
    out), so it could never reach a conversion-factor column.

    ``FAC_CORP_OC`` is the load-bearing one. ``LN_CORP_ONB`` maps to it, so its
    undrawn headroom is ``LIMIT_CORP_OC - DRAWN_CORP_ONB`` and the C 08.03 col
    0030 exposure-weighted average CCF has two differently-weighted contributors
    (the issued guarantee and this commitment) rather than one.
    """
    rows: list[dict] = [
        {
            "facility_reference": FAC_CORP_OC,
            "counterparty_reference": CP_CORP,
            "product_type": "revolving_credit_facility",
            "limit": LIMIT_CORP_OC,
            "risk_type": "OC",
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "committed": True,
            "is_revolving": True,
        },
        {
            "facility_reference": FAC_SL,
            "counterparty_reference": CP_SL,
            "product_type": "term_loan",
            "limit": DRAWN_SL,
            "risk_type": "OC",
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "committed": True,
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_SCHEMA))


def _facility_mappings() -> pl.DataFrame:
    """Link each drawn loan to its parent so the headroom nets the drawn balance.

    ``LN_SL`` is drawn to ``FAC_SL``'s full limit, so that facility contributes no
    undrawn leg — the slotting off-BS coverage comes from ``CT_SL`` instead, which
    keeps the slotting cells hand-checkable at exactly ``NOMINAL_SL``.
    """
    rows: list[dict] = [
        {
            "parent_facility_reference": FAC_CORP_OC,
            "child_reference": LN_CORP_ONB,
            "child_type": "loan",
        },
        {
            "parent_facility_reference": FAC_SL,
            "child_reference": LN_SL,
            "child_type": "loan",
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _collateral() -> pl.DataFrame:
    """The Art. 200(1)(b) life policy and the CR7-A financial-collateral probe.

    ``IRS-COLL-LIFE`` is the only life-insurance pledge in the estate. Its
    surrender value is below the drawn amount deliberately: partial cover keeps
    C 08.01 col 0172 distinguishable from a full-cover degenerate case, and the
    ``{c0170} = {c0171}+{c0172}+{c0173}`` identity non-trivial given col 0171 and
    col 0173 are structurally zero (module docstring).

    ``IRS-COLL-CASH`` is the CR7-A col b DIAGNOSTIC — eligible cash pledged to an
    A-IRB obligor. If col b stays dead with this row present, the column's binding
    is the defect rather than the estate's shape, and its reason code should move
    to ``ENGINE_CANNOT_PRODUCE``.
    """
    return pl.DataFrame(
        [
            {
                "collateral_reference": "IRS-COLL-LIFE",
                "collateral_type": "life_insurance",
                "is_eligible_irb_collateral": True,
                "market_value": LIFE_SURRENDER_VALUE,
                # GBP, matching the exposure. Without it the policy denomination
                # is unknown, ``engine/crm/life_insurance.py`` raises CRM020 and
                # applies the Art. 233(3) 8% FX volatility reduction
                # conservatively — which would leave col 0172 carrying a haircut
                # this portfolio is not trying to exercise. p1_275 owns that axis.
                "currency": "GBP",
                "beneficiary_type": "loan",
                "beneficiary_reference": LN_LIFE,
            },
            {
                "collateral_reference": "IRS-COLL-CASH",
                "collateral_type": "cash",
                "is_eligible_irb_collateral": True,
                "market_value": FINCOLL_VALUE,
                "currency": "GBP",
                "beneficiary_type": "loan",
                "beneficiary_reference": LN_FINCOLL,
            },
            # A sovereign debt security on the SAME leg. Cash alone cannot answer
            # the CR7-A col b question: measured, an eligible cash pledge lands in
            # ``collateral_cash_value`` and leaves ``collateral_financial_value``
            # — which is what col b binds through
            # ``cr7a_capped_collateral_financial_value`` — at 0.00. The two are
            # sibling carriers off ``_adj_cash`` / ``_adj_fin``
            # (``engine/crm/collateral.py``), so only a NON-cash financial
            # collateral reaches the one col b reads.
            {
                "collateral_reference": "IRS-COLL-EQUITY",
                # ``equity`` because it is the only NON-CASH string in BOTH
                # ``VALID_COLLATERAL_TYPES`` (what the loader accepts) and
                # ``FINANCIAL_COLLATERAL_TYPES`` (what the CRM engine recognises)
                # other than ``gold`` / ``credit_linked_note``. Measured, those
                # two sets DISAGREE about debt securities and there is no input
                # string that both validates and is recognised as one:
                #   - ``bond``            validates, matches NO engine category,
                #                         degraded to unclassified 'other' at no
                #                         secured value (warning only);
                #   - ``government_bond`` is recognised and populates
                #                         ``collateral_financial_value``, but
                #                         FAILS loader validation as an invalid
                #                         ``collateral_type``.
                # Recorded rather than worked around silently — see the module
                # docstring's finding note. Art. 197(1)(d)-(e) main-index equity
                # is genuine financial collateral, so this row is honest as well
                # as convenient.
                "collateral_type": "equity",
                "is_eligible_financial_collateral": True,
                "is_eligible_irb_collateral": True,
                "market_value": EQUITY_VALUE,
                "nominal_value": EQUITY_VALUE,
                "currency": "GBP",
                # Art. 197(1)(f) main-index membership and Art. 198(1)(a) listing.
                # Both are REQUIRED attestations, not decoration: without them the
                # CRM stage recognises the pledge at zero secured value and
                # ``collateral_financial_value`` stays 0.00 while
                # ``collateral_financial_market_value`` still shows 35,000 — an
                # eligibility gap that looks like a populated carrier if you read
                # only the market-value column.
                "is_main_index": True,
                "is_listed": True,
                "beneficiary_type": "loan",
                "beneficiary_reference": LN_FINCOLL,
            },
        ]
    )


def _specialised_lending() -> pl.DataFrame:
    """One project-finance slotting exposure (strong category).

    Mirrors the rich portfolio's row so the slotting *treatment* is unchanged and
    the only new thing this portfolio asks of the slotting path is an
    off-balance-sheet leg.
    """
    return pl.DataFrame(
        [
            {
                "counterparty_reference": CP_SL,
                "sl_type": "project_finance",
                "slotting_category": "strong",
                "is_hvcre": False,
            }
        ]
    )


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _loan(
    loan_reference: str,
    counterparty_reference: str,
    drawn_amount: float,
    *,
    lgd: float | None = None,
    beel: float | None = None,
    has_sufficient_collateral_data: bool = False,
    product_type: str = "term_loan",
) -> dict:
    """Build one loan row dict (unset optional columns take schema defaults)."""
    row: dict = {
        "loan_reference": loan_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": product_type,
        "drawn_amount": drawn_amount,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
        "has_sufficient_collateral_data": has_sufficient_collateral_data,
    }
    if lgd is not None:
        row["lgd"] = lgd
    # Best-estimate expected loss. Only meaningful on a defaulted exposure, where
    # PS1/26 Art. 154(1)(a) makes K = max(0, LGD - BEEL); left unset elsewhere so
    # the schema default applies and no non-defaulted row gains an EL shortfall.
    if beel is not None:
        row["beel"] = beel
    return row


def _internal(counterparty_reference: str, *, pd: float) -> dict:
    """Internal model rating row (PD + model_id — the IRB routing pair)."""
    return {
        "rating_reference": f"IRS-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "pd": pd,
        "model_id": _MODEL_ID,
        "rating_date": _VALUE_DATE,
    }


def _internal_no_pd(counterparty_reference: str) -> dict:
    """Internal rating carrying only ``model_id`` (no PD) — for slotting routing."""
    return {
        "rating_reference": f"IRS-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "model_id": _MODEL_ID,
        "rating_date": _VALUE_DATE,
    }
