"""
IRB class-and-PD-band reporting portfolio — the C 08.xx sheet and row axes.

Pipeline position:
    build_reporting_irb_classes_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Why a FIFTH portfolio (rather than extending ``reporting_portfolio.py``):
the rich portfolio's IRB book is three exposures — F-IRB corporate, A-IRB
corporate, A-IRB retail — so the C 08.xx family emits only the ``corporate`` and
``retail_other`` sheets, and C 08.03 / C 08.05 (the PD-range breakdowns) emit a
single band each. Every published rule scoped to the IRB central-government,
institution, retail-mortgage or QRRE sheet, and every sum-check written over the
low PD bands, was NOT_EVALUATED: **15 CRR and 10 Basel 3.1 rules on the sheet
axis, plus 8 CRR and 14 Basel 3.1 on the PD-band rows**. Adding these rows to the
rich portfolio would move all 26 of its committed goldens, so this portfolio is
separate with its own golden directory — the pattern
``reporting_offbs_portfolio.py`` established.

Composition — the sheet axis (Art. 147 IRB exposure classes):

    ref              | IRB class                 | approach | basis
    -----------------|---------------------------|----------|---------------------
    LN_SOV_A/B/C     | central_govt_central_bank | F-IRB    | Art. 147(2)(a)
    LN_INST          | institution               | F-IRB    | Art. 147(2)(b)
    LN_RRE           | retail_mortgage           | A-IRB    | Art. 154(3)
    LN_QRRE          | retail_qrre               | A-IRB    | Art. 154(4)
    LN_CORP_*        | corporate                 | F-IRB    | Art. 147(2)(c)

and the row axis (the fixed C 08.03 / C 08.05 PD scale), which is why there is a
fourteen-grade corporate masterscale rather than one exposure per decade of PD:

    ref              | PD      | leaf band        | CRR  | B3.1
    -----------------|---------|------------------|------|------
    LN_SOV_A         | 0.020%  | 0.00 to <0.10    | 0020 |  --
    LN_SOV_B         | 0.040%  | 0.00 to <0.10    | 0020 |  --
    LN_SOV_C         | 0.070%  | 0.00 to <0.10    | 0020 |  --
    corporate G01    | 0.020%  | see below        | 0020 | 0015
    corporate G02    | 0.070%  | see below        | 0020 | 0025
    corporate G03-14 | 0.12-70%| 0.10% .. < 100%  | 0030 | 0030
                     |         |            ..0160| 0160 | 0160

The corporate grades are a 14-point internal MASTERSCALE because the published
PD-range rules are PARENT/CHILD sums within a single sheet: ``v09754_m`` is
``{r0070} = {r0080} + {r0090}`` and ``v09756_m`` is
``{r0130} = {r0140} + {r0150} + {r0160}``. A coordinate is only evaluated when
the parent band AND every child band it references are populated on the SAME
class sheet, so a sparse ladder leaves every one of those rules NOT_EVALUATED.
The masterscale puts one obligor in each of the thirteen LEAF bands, which
populates all four parent bands and makes every published group evaluable on the
corporate sheet under both regimes. See ``CORP_MASTERSCALE`` for the mapping.

Note the scale is hierarchical: parent rows 0010/0070/0100/0130 repeat the span
of the sub-bands beneath them, so they are populated implicitly and summing every
emitted row double-counts.

The three sovereigns exercise the CRR-only sovereign IRB sheet and the Art.
160(1) no-floor treatment (the 0.03% PD floor binds corporates and institutions,
not central governments and central banks). All three land in the SAME leaf band,
``0.00 to <0.10`` (CRR row 0020) — the published scale has no sub-0.03% band for
a floored corporate to be excluded from, so unlike an earlier revision of this
fixture they are not the only route into a low band. They are kept because the
sovereign sheet itself is CRR-only and worth emitting.

``LN_CORP_FLOOR`` (grade G01) carries the SAME 0.02% PD as ``LN_SOV_A`` and is
still load-bearing, because it pins the ALLOCATION BASIS:
``c08.py::_pd_alloc_col`` allocates C 08.03 / C 08.05 on ``pd_floored`` under CRR
and on the unfloored ``pd`` under Basel 3.1. Under Basel 3.1 the 0.05% corporate
PD input floor falls exactly on the 0015 / 0025 boundary, so G01 lands in 0015
(``0.00 to <0.05``) on the pre-floor basis and would land in 0025 on the
post-floor one — the sharpest available discriminator between the two bases.
Under CRR the 0.03% floor sits INSIDE the first leaf band (``0.00 to <0.10``), so
there the floor cannot move a corporate across a band boundary at all.

``LN_QRRE`` is drawn to exactly its parent facility's limit. That is deliberate:
a facility with headroom emits a synthetic ``_UNDRAWN`` exposure which inherits
no internal rating and routes standardised, so the QRRE row would never reach a
C 08.xx sheet at all. Drawn == limit leaves the loan as the sole QRRE candidate
and keeps the Art. 154(4)(c) per-individual aggregate at one facility limit,
below both the EUR 100k (CRR) and GBP 90k (PS1/26) caps. The facility supplies
``is_revolving`` / ``is_secured=False`` / ``risk_type="LR"`` / ``limit``; the
classifier reads all four off the drawn leg after the hierarchy stage coalesces
them (the pattern ``tests/fixtures/p1_244`` pins).

Regime divergence is expected and is not a defect: PS1/26 Art. 147A(1)(a) read
with Art. 147(3) makes the sovereign class Standardised-only, so under Basel 3.1
the three sovereign rows route SA and the ``central_govt_central_bank`` IRB sheet
is legitimately absent. The Basel 3.1 arm of this portfolio therefore covers the
institution / retail-mortgage / QRRE sheets and the PD-band rows; the CRR arm
covers those plus the sovereign sheet.

Deliberately OUT of scope:
- A-IRB specialised lending. The rich portfolio owns the slotting sheet, and
  C 08.06 row 0095 — the row the blocked OF 08.06 rules address — does not exist
  in this estate's template at all (``templates.py::B31_C08_06_ROWS`` runs
  0010-0120), so no fixture row can emit it.
- C 02.00 F-IRB / A-IRB class rows 0270-0360. This estate's CRR C 02.00 uses the
  PS1/26 row numbering, so those refs are absent from the template rather than
  unpopulated. A template gap, not a data one.
- Off-balance-sheet items and CRM: ``reporting_offbs_portfolio.py`` and the rich
  portfolio own those axes. Every row here is drawn and unmitigated so a
  mis-banded exposure shows up in one cell.

References:
- CRR Art. 147(2)-(5) / PS1/26 Art. 147: IRB exposure classes
- CRR Art. 160(1): the 0.03% PD floor, scoped to corporates and institutions
- CRR Art. 154(3)-(4) / PS1/26 Art. 147(5A): retail mortgage and QRRE sub-classes
- PS1/26 Art. 147A(1)(a): the Basel 3.1 SA-only sovereign class
- COREP Annex II, C 08.03 / C 08.05: the PD-range row breakdowns
- tests/fixtures/p1_244/p1_244.py: the QRRE drawn-leg wiring this mirrors
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
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: Must match ``create_full_irb_model_permissions`` (F-IRB + A-IRB + slotting
#: for every class), or no row routes IRB at all.
_MODEL_ID: str = "TEST_FULL_IRB"

CP_SOV_A: str = "IRC-CP-SOV-A"
CP_SOV_B: str = "IRC-CP-SOV-B"
CP_SOV_C: str = "IRC-CP-SOV-C"
CP_INST: str = "IRC-CP-INST"
CP_RRE: str = "IRC-CP-RRE"
CP_QRRE: str = "IRC-CP-QRRE"
LN_SOV_A: str = "IRC-LN-SOV-A"
LN_SOV_B: str = "IRC-LN-SOV-B"
LN_SOV_C: str = "IRC-LN-SOV-C"
LN_INST: str = "IRC-LN-INST"
LN_RRE: str = "IRC-LN-RRE"
LN_QRRE: str = "IRC-LN-QRRE"

FAC_QRRE: str = "IRC-FAC-QRRE"

#: The corporate internal masterscale: one obligor per grade, ``(grade, PD)``.
#:
#: Fourteen grades rather than a handful because the published PD-range checks
#: are PARENT/CHILD sums within one sheet — ``v09754_m`` is
#: ``{r0070} = {r0080} + {r0090}``, ``v09756_m`` is
#: ``{r0130} = {r0140} + {r0150} + {r0160}`` — so a rule executes only when the
#: parent band AND every child band are populated on the SAME class sheet. A
#: portfolio with one exposure per decade of PD leaves all of them
#: NOT_EVALUATED. Grades G02-G14 fill exactly the bands those sums reference,
#: which is also what makes C 08.02 (the obligor-grade breakdown) non-trivial
#: for the first time.
#:
#: ``G01`` is the floored grade: 0.02% as booked, which CRR Art. 160(1) lifts to
#: the 0.03% minimum for corporates — see the module docstring.
#:
#: Every grade below names the LEAF band it occupies. The parent bands (0010,
#: 0070, 0100, 0130) are populated implicitly, because a parent spans its
#: children: no grade is booked "into" a parent.
CORP_MASTERSCALE: tuple[tuple[str, float], ...] = (
    ("G01", 0.0002),  # -> CRR 0020 (0.00 to <0.10) / B3.1 0015 (0.00 to <0.05)
    ("G02", 0.0007),  # -> CRR 0020 (0.00 to <0.10) / B3.1 0025 (0.05 to <0.10)
    ("G03", 0.0012),  # -> 0030   0.10 to <0.15
    ("G04", 0.0020),  # -> 0040   0.15 to <0.25
    ("G05", 0.0035),  # -> 0050   0.25 to <0.50
    ("G06", 0.0060),  # -> 0060   0.50 to <0.75
    ("G07", 0.0120),  # -> 0080   0.75 to <1.75   (child of 0070)
    ("G08", 0.0200),  # -> 0090   1.75 to <2.5    (child of 0070)
    ("G09", 0.0350),  # -> 0110   2.5 to <5       (child of 0100)
    ("G10", 0.0700),  # -> 0120   5 to <10        (child of 0100)
    ("G11", 0.1200),  # -> 0140  10 to <20        (child of 0130)
    ("G12", 0.2500),  # -> 0150  20 to <30        (child of 0130)
    ("G13", 0.4000),  # -> 0160  30 to <100       (child of 0130)
    ("G14", 0.7000),  # -> 0160  30 to <100       (second obligor in the band)
)


def corp_cp(grade: str) -> str:
    """Counterparty reference for one masterscale grade."""
    return f"IRC-CP-CORP-{grade}"


def corp_ln(grade: str) -> str:
    """Loan reference for one masterscale grade."""
    return f"IRC-LN-CORP-{grade}"


#: The QRRE facility limit. Below both Art. 154(4)(c) caps (EUR 100k / GBP 90k),
#: and equal to the drawn balance so no synthetic undrawn exposure is minted.
QRRE_LIMIT: float = 45_000.0

#: Internal PDs, chosen so each occupies a distinct C 08.03 band. The three
#: sovereign values sit BELOW the Art. 160(1) 0.03% floor band boundary or just
#: above it; the floor does not bind the sovereign class, so they survive to the
#: template as booked.
PD_SOV_A: float = 0.0002
PD_SOV_B: float = 0.0004
PD_SOV_C: float = 0.0007
PD_INST: float = 0.0040
PD_RRE: float = 0.0060
PD_QRRE: float = 0.0200

#: Drawn amounts, in GBP. Distinct per row so a mis-classified or mis-banded
#: exposure is identifiable from a single cell value.
DRAWN_SOV_A: float = 8_000_000.0
DRAWN_SOV_B: float = 7_000_000.0
DRAWN_SOV_C: float = 6_000_000.0
DRAWN_INST: float = 5_500_000.0
DRAWN_RRE: float = 300_000.0
DRAWN_QRRE: float = QRRE_LIMIT
#: Masterscale drawn amounts step by 100k from G01, so a mis-banded grade is
#: identifiable from a single C 08.03 cell value without a reverse lookup.
DRAWN_CORP_BASE: float = 3_000_000.0
DRAWN_CORP_STEP: float = 100_000.0

_VALUE_DATE: date = date(2020, 1, 1)
_MATURITY: date = date(2031, 12, 31)  # > both reporting dates (CRR 2025, B31 2027)

#: Every exposure and the C 08.xx sheet it must land on UNDER CRR. Consumed by
#: the fixture-integrity test: if a row stops reaching its sheet the goldens
#: quietly stop covering that class and the published rules written over it fall
#: back to NOT_EVALUATED without any gate turning red.
IRB_CLASS_EXPECTED_SHEET_CRR: dict[str, str] = {
    LN_SOV_A: "central_govt_central_bank",
    LN_SOV_B: "central_govt_central_bank",
    LN_SOV_C: "central_govt_central_bank",
    LN_INST: "institution",
    LN_RRE: "retail_mortgage",
    LN_QRRE: "retail_qrre",
    **{corp_ln(grade): "corporate" for grade, _pd in CORP_MASTERSCALE},
}

#: PS1/26 Art. 147A(1)(a): the sovereign class is Standardised-only under Basel
#: 3.1, so the three sovereign rows leave the IRB book entirely. Everything else
#: keeps its CRR sheet.
IRB_CLASS_EXPECTED_SHEET_B31: dict[str, str] = {
    ref: sheet
    for ref, sheet in IRB_CLASS_EXPECTED_SHEET_CRR.items()
    if ref not in (LN_SOV_A, LN_SOV_B, LN_SOV_C)
}

#: The approach each row must resolve to, per regime. The sovereign trio is the
#: only divergence and it is the regime change itself, not a tolerance.
IRB_CLASS_EXPECTED_APPROACH: dict[str, tuple[str, str]] = {
    # exposure_reference: (CRR approach, Basel 3.1 approach)
    LN_SOV_A: ("foundation_irb", "standardised"),
    LN_SOV_B: ("foundation_irb", "standardised"),
    LN_SOV_C: ("foundation_irb", "standardised"),
    LN_INST: ("foundation_irb", "foundation_irb"),
    LN_RRE: ("advanced_irb", "advanced_irb"),
    LN_QRRE: ("advanced_irb", "advanced_irb"),
    **{corp_ln(grade): ("foundation_irb", "foundation_irb") for grade, _pd in CORP_MASTERSCALE},
}


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_irb_classes_bundle() -> RawDataBundle:
    """Assemble the IRB class-and-PD-band portfolio as a sealed bundle.

    Sealed against the loader edge contracts by ``make_raw_bundle``, so it is
    shape-identical to a parquet-loaded production bundle. Run it through
    ``PipelineOrchestrator().run_with_data`` under either regime with
    ``PermissionMode.IRB`` — every obligor carries an internal PD and the
    matching ``model_permissions`` row, which is what routes a row IRB.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        facilities=_facilities(),
        facility_mappings=_facility_mappings(),
        ratings=_ratings(),
        model_permissions=create_full_irb_model_permissions(),
        collateral=_collateral(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """One obligor per IRB sheet, plus the sovereign and corporate PD ladders.

    The three sovereigns are separate legal entities in different jurisdictions
    rather than one obligor with three facilities: PD is assigned per obligor
    (Art. 160(1) reads the obligor grade), so three bands need three obligors.
    The non-GB codes also give the C 09.02 geographic breakdown more than one
    country sheet to partition.

    The two retail obligors carry ``is_natural_person`` and
    ``is_managed_as_retail`` so the Art. 123 retail limbs pass and the QRRE gate
    is decided only by the Art. 154(4)(b) facility attributes under test.
    """
    rows: list[dict] = [
        {"counterparty_reference": CP_SOV_A, "entity_type": "sovereign", "country_code": "US"},
        {"counterparty_reference": CP_SOV_B, "entity_type": "sovereign", "country_code": "CA"},
        {"counterparty_reference": CP_SOV_C, "entity_type": "sovereign", "country_code": "JP"},
        {"counterparty_reference": CP_INST, "entity_type": "institution", "country_code": "GB"},
        {
            "counterparty_reference": CP_RRE,
            "entity_type": "individual",
            "country_code": "GB",
            "is_natural_person": True,
            "is_managed_as_retail": True,
        },
        {
            "counterparty_reference": CP_QRRE,
            "entity_type": "individual",
            "country_code": "GB",
            "is_natural_person": True,
            "is_managed_as_retail": True,
        },
        *(
            {
                "counterparty_reference": ref,
                "entity_type": "corporate",
                "country_code": "GB",
                # Above the SME ceiling: the PD-band axis is what is under test,
                # and an SME supporting factor would perturb every band cell.
                "annual_revenue": 400_000_000.0,
            }
            for ref in (corp_cp(grade) for grade, _pd in CORP_MASTERSCALE)
        ),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """Internal PD ratings only — an internal PD plus a matching permission is
    what routes a row IRB, and an external CQS would route it SA instead."""
    rows: list[dict] = [
        _internal(CP_SOV_A, pd=PD_SOV_A),
        _internal(CP_SOV_B, pd=PD_SOV_B),
        _internal(CP_SOV_C, pd=PD_SOV_C),
        _internal(CP_INST, pd=PD_INST),
        _internal(CP_RRE, pd=PD_RRE),
        _internal(CP_QRRE, pd=PD_QRRE),
        *(_internal(corp_cp(grade), pd=pd_value) for grade, pd_value in CORP_MASTERSCALE),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans() -> pl.DataFrame:
    """One drawn exposure per sheet / PD band. EAD = drawn_amount.

    The sovereign, institution and corporate rows carry NO firm LGD estimate, so
    the A-IRB branch is unavailable and they resolve F-IRB on the Art. 161
    supervisory LGD — which is also the only approach Art. 147A permits for
    institutions under Basel 3.1. The two retail rows carry ``lgd`` +
    ``has_sufficient_collateral_data`` so they resolve A-IRB (Art. 154(3)/(4)
    retail is A-IRB-only in both regimes).
    """
    rows: list[dict] = [
        _loan(LN_SOV_A, CP_SOV_A, DRAWN_SOV_A),
        _loan(LN_SOV_B, CP_SOV_B, DRAWN_SOV_B),
        _loan(LN_SOV_C, CP_SOV_C, DRAWN_SOV_C),
        _loan(LN_INST, CP_INST, DRAWN_INST),
        # Retail secured by residential property -> RETAIL_MORTGAGE. The linked
        # collateral row below is what makes the hierarchy stage set is_mortgage.
        _loan(
            LN_RRE,
            CP_RRE,
            DRAWN_RRE,
            lgd=0.15,
            has_sufficient_collateral_data=True,
            property_type="residential",
            ltv=0.60,
        ),
        # Qualifying revolving retail: drawn to the full parent limit so the
        # facility emits no synthetic undrawn leg (see the module docstring).
        _loan(
            LN_QRRE,
            CP_QRRE,
            DRAWN_QRRE,
            lgd=0.55,
            has_sufficient_collateral_data=True,
            product_type="revolving_credit_facility",
        ),
        # The corporate masterscale — one F-IRB exposure per internal grade.
        *(
            _loan(corp_ln(grade), corp_cp(grade), _corp_drawn(index))
            for index, (grade, _pd) in enumerate(CORP_MASTERSCALE)
        ),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _facilities() -> pl.DataFrame:
    """The single QRRE parent — the source of the Art. 154(4)(b) attributes.

    ``is_revolving`` / ``is_secured`` / ``risk_type`` / ``limit`` live on the
    facility, not the loan; the hierarchy stage coalesces them onto the drawn
    child, which is where the classifier reads them. ``risk_type="LR"`` is the
    unconditional-cancellability signal the CCF machinery already owns, reused
    here rather than duplicated as a second flag.
    """
    rows: list[dict] = [
        {
            "facility_reference": FAC_QRRE,
            "counterparty_reference": CP_QRRE,
            "product_type": "revolving_credit_facility",
            "limit": QRRE_LIMIT,
            "risk_type": "LR",
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "committed": True,
            "is_revolving": True,
            "is_secured": False,
            "is_qrre_transactor": False,
            "seniority": "senior",
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_SCHEMA))


def _facility_mappings() -> pl.DataFrame:
    """Link the drawn QRRE loan to its parent so the facility attributes reach it."""
    rows: list[dict] = [
        {
            "parent_facility_reference": FAC_QRRE,
            "child_reference": LN_QRRE,
            "child_type": "loan",
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _collateral() -> pl.DataFrame:
    """The residential property behind ``LN_RRE``.

    The loan-level ``property_type`` / ``ltv`` alone do not move an exposure into
    RETAIL_MORTGAGE — a property collateral row linked with
    ``beneficiary_type="loan"`` is what makes the HierarchyResolver populate the
    collateral-value columns the mortgage predicate reads.
    """
    return pl.DataFrame(
        [
            {
                "collateral_reference": "IRC-COLL-RRE",
                "collateral_type": "real_estate",
                "property_type": "residential",
                # 300k loan / 500k value -> 60% LTV.
                "market_value": 500_000.0,
                "property_ltv": 0.60,
                "beneficiary_type": "loan",
                "beneficiary_reference": LN_RRE,
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
    has_sufficient_collateral_data: bool = False,
    property_type: str | None = None,
    ltv: float | None = None,
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
    if property_type is not None:
        row["property_type"] = property_type
    if ltv is not None:
        row["ltv"] = ltv
    return row


def _corp_drawn(index: int) -> float:
    """Drawn amount for masterscale grade ``index`` (0-based)."""
    return DRAWN_CORP_BASE + index * DRAWN_CORP_STEP


def _internal(counterparty_reference: str, *, pd: float) -> dict:
    """Internal model rating row (PD + model_id — the IRB routing pair)."""
    return {
        "rating_reference": f"IRC-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "pd": pd,
        "model_id": _MODEL_ID,
        "rating_date": _VALUE_DATE,
    }
