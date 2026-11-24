"""
Defaulted standardised populations — OF 07.00 / C 07.00 rows 0015, 0300 and 0320.

Pipeline position:
    build_reporting_default_populations_bundle(framework) -> RawDataBundle
        -> PipelineOrchestrator (STANDARDISED config) -> COREPGenerator
        -> C 07.00 / OF 07.00 -> the supervisory validation register (RUNS)

Why a separate portfolio (rather than extending ``reporting_portfolio.py``):
until this book the registered matrix held ONE defaulted standardised exposure,
``rich``'s ``RP-LN-DEFAULT`` — a 1,000,000 corporate loan at 150%, drawn, with no
provision and no guarantee. Every other population the OF 07.00 default fixes of
2026-11-16 reach (O-05, O-15, O-16, ``63c3b5c``) was exercised only by unit tests
on synthetic frames and by two unregistered acceptance books, so the published
rules over them were VACUOUS or NOT_EVALUATED on every registered run (LESSONS B5):
``boe_b0733_1`` (``{OF07.00.01.03} <= 0`` over c0030 / c0035) and its CRR twin
``v2040_s`` held at ``0 <= 0`` because no registered default carried a provision;
``boe_b0264`` (sheet 0012 row 0015 ties to OF 09.01 r0110) and every rule on the
high-risk sheet never ran. Adding the legs to ``rich`` would move its goldens and
break the tests that pin its single defaulted leg, so this book is its own.

The rule text each leg is built to:

- PS1/26 Art. 127(1) (ps126app1.pdf p.59): "(a) 150%, where the amount of specific
  credit risk adjustments ... is less than 20% of the outstanding amount of the
  item or facility; or (b) 100%, where ... equal to or greater than 20%". Art.
  127(3): "A residential real estate exposure which is a defaulted exposure and is
  not materially dependent on the cash-flows of the property shall be assigned a
  risk weight of 100%." CRR Art. 127(1) is the same 20% test on the unsecured part
  before the adjustments.
- PS1/26 Art. 128(1): "An institution shall assign a 150% risk weight to exposures
  that are associated with particularly high risk"; Art. 112(2) Table A2 ranks that
  class (row 4) above "in default" (row 5), so a defaulted high-risk leg KEEPS its
  class.
- PS1/26 Annex II ¶52-55 (pp.78-79) and rows 0300 / 0320 (p.97): rows 0300 (Art.
  127(1)(b) and (3)) and 0320 (Art. 127(1)(a)) report the "in default" class split
  by the class the exposure would otherwise have had — on the Total and on that
  class's sheet. Table OF07.00.01.03 publishes them on sheets 0001-0004 and
  0007-0009 only; the Bank's known-issues log (November 2026, #27) puts a
  real-estate-origin default on the Total sheet alone. An MDB or international-
  organisation origin has no memo cell either.
- PS1/26 Annex II row 0015 (p.88): "Only exposures in exposure classes 'exposures
  associated with particularly high risk', ... shall be reported in this row if they
  are in default."
- CRR Annex II ¶52-55 (pp.79-80) and rows 0300 / 0320 (p.94): the same memo rows,
  which the engine still keys on the APPLIED class under CRR (the open CRR half of
  P1.377), so under CRR this book lights the "in default" sheet and the Total only.
  CRR Art. 127(3) (watchfire snapshot; ``docs/assets/crr.pdf`` is empty here): "The
  exposure value remaining after specific credit risk adjustments of exposures fully
  and completely secured by mortgages on residential property in accordance with
  Article 125 shall be assigned a risk weight of 100 % if a default has occurred".
  Art. 125's limb (d) caps the secured part at 80% of the property's value, so a
  mortgage at 60% LTV is secured whole and takes 100% outright.

Composition. Every leg is a drawn GBP loan to a GB obligor unless stated, at a
distinct amount so a misplaced figure is identifiable from one cell; only the two
mortgages are collateralised (residential property, linked as a collateral row).
"Prov." is a specific credit risk adjustment (``provision_type='scra'``, IFRS 9
stage 3) on the loan; the weight is the one the engine applies.

    loan            | obligor class before default  | prov. | RW    | memo row / sheet     | regime
    ----------------|-------------------------------|-------|-------|----------------------|-------
    LN_SOV_DEF      | central government (CQS 3)    |  25%  | 100%  | 0300 / 0002 + Total  | both
    LN_RGLA_DEF     | regional government (US)      |   5%  | 150%  | 0320 / 0003 + Total  | both
    LN_PSE_DEF      | public sector entity          |  30%  | 100%  | 0300 / 0004 + Total  | both
    LN_INST_DEF     | institution (CQS 2)           |  10%  | 150%  | 0320 / 0007 + Total  | both
    LN_RET_DEF      | retail (natural person)       |  30%  | 100%  | 0300 / 0009 + Total  | both
    LN_CORP_GTD_DEF | corporate, 40% guaranteed by  |   -   | 150%  | 0320 / 0008 + Total  | both
                    | a CQS 2 institution (CRR 50%, |       |       | (covered part c0010, |
                    | Basel 3.1 30%)                |       |       |  not c0200 / c0220)  |
    LN_RRE_DEF      | real estate (natural person,  |   5%  | 100%  | 0300 / Total only    | both
                    | LTV 60%, not income-producing)|       |       | (B3.1 issue #27; CRR |
                    |                               |       |       |  Total + in default) |
    LN_HR_DEF       | high risk                     |   -   | 150%  | 0015 / 0012 + Total  | B3.1
    LN_HR_PERF      | high risk, performing         |   -   | 150%  | 0010 / 0012 only     | B3.1
    LN_RRE_GTD      | real estate (natural person,  |   -   | blend | two parts, 0180 and  | B3.1
                    | LTV 60%), 20% guaranteed by   |       |       | 0220 on 0010; covered|
                    | the UK sovereign (0%)         |       |       | EV on 0002 row 0140  |

Why each leg, and the pairs that make a cell discriminating (LESSONS B5, fourth form):

- The provisioned legs sit on BOTH sides of the Art. 127(1) 20% threshold — 25% / 30%
  in row 0300, 5% / 10% in row 0320 — and every one carries a non-zero c0030, so
  ``boe_b0733_1`` / ``v2040_s`` compare a figure rather than ``0 <= 0``. A single
  provisioned leg could not tell a row scoped correctly from one zeroed.
- ``LN_RRE_DEF`` carries a 5% provision and still lands in row 0300, in both
  regimes: Art. 127(3) overrides the provision test (PS1/26: a flat 100% for a
  non-income-producing residential default; CRR: 100% on the part secured within
  Art. 125, here the whole loan). Beside ``LN_RGLA_DEF`` (5%, row 0320) it separates
  the two Art. 127 routes into row 0300.
- ``LN_CORP_GTD_DEF`` is the ``63c3b5c`` composition: the covered part's ORIGINAL
  exposure stays in the obligor's memo row at the Art. 127 weight (c0010), its
  exposure value and RWEA go to the guarantor's sheet (c0200 / c0220 of the memo row
  hold the uncovered part only). Its protector is a CQS 2 institution, at a NON-ZERO
  weight (CRR Art. 120 Table 3 50%, PS1/26 Art. 120 Table 3 30%) that is still
  below 150% so the guarantee is beneficial: a 0% protector would make the RWEA that
  crosses over zero, and a covered part's RWEA wrongly added back into the memo row
  would then read the same as one correctly left out (LESSONS C2).
- ``LN_HR_PERF`` is the survivor beside ``LN_HR_DEF``: sheet 0012 row 0010 carries
  both, row 0015 only the defaulted one, so a row 0015 blanked everywhere and one
  scoped to the defaulted leg read differently.
- ``LN_RRE_GTD`` is the ``rw_parts`` substituted route: a beneficially guaranteed
  Art. 124F loan split, its covered part's original exposure reported in the loan's
  two parts on the real-estate sheet. Its protector stays the UK sovereign at 0%, so
  the benefit is unambiguous against either part's weight.
- Neither guarantor (``CP_INST_GTOR``, ``CP_SOV_GTOR``) has a loan of its own: each
  one's sheet rows at its weight are opened by the inflows alone.

CRR carries only the legs CRR can express: no high-risk class (UK onshored CRR
omits Art. 128; Feature ``b31_high_risk_class_applicable`` folds it to "other") and
no Art. 124F loan split — and so no ``CP_SOV_GTOR``, whose only beneficiary is that
split. The real-estate-origin default IS in the CRR book: within Art. 125's 80% the
whole loan is secured, so the blended Art. 127(3) share is 1 and the leg takes
exactly 100% (measured: exposure value 332,500, RWEA 332,500), the CRR twin of the
Basel 3.1 Art. 127(3)-against-provision pair.
``build_reporting_default_populations_bundle`` takes the framework because of the
two Basel-3.1-only populations; the RUNS entries bind it with
``functools.partial``, which keeps the builder's name for the registration check.

References:
- PS1/26 Art. 112(2) Table A2, Art. 124F, 127, 128; Annex II OF 07.00 ¶51-55,
  rows 0015 / 0300 / 0320
- CRR Art. 112, 127; COREP Annex II C 07.00 ¶51-55, rows 0015 / 0300 / 0320
- Bank of England known-issues log (November 2026), issue #27; taxonomy v4.1.1
  table OF07.00.01.03
- src/rwa_calc/reporting/corep/c07_sheet_scope.py; reporting/kernel/rw_parts.py
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    PROVISION_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: The frameworks the builder accepts (``CalculationConfig`` framework names).
FRAMEWORK_CRR: str = "CRR"
FRAMEWORK_B31: str = "BASEL_3_1"

CP_SOV_DEF: str = "DFP-CP-SOV-DEF"
CP_RGLA_DEF: str = "DFP-CP-RGLA-DEF"
CP_PSE_DEF: str = "DFP-CP-PSE-DEF"
CP_INST_DEF: str = "DFP-CP-INST-DEF"
CP_RET_DEF: str = "DFP-CP-RET-DEF"
CP_CORP_GTD_DEF: str = "DFP-CP-CORP-GTD-DEF"
CP_INST_GTOR: str = "DFP-CP-INST-GTOR"
CP_SOV_GTOR: str = "DFP-CP-SOV-GTOR"
CP_RRE_DEF: str = "DFP-CP-RRE-DEF"
CP_HR_DEF: str = "DFP-CP-HR-DEF"
CP_HR_PERF: str = "DFP-CP-HR-PERF"
CP_RRE_GTD: str = "DFP-CP-RRE-GTD"

LN_SOV_DEF: str = "DFP-LN-SOV-DEF"
LN_RGLA_DEF: str = "DFP-LN-RGLA-DEF"
LN_PSE_DEF: str = "DFP-LN-PSE-DEF"
LN_INST_DEF: str = "DFP-LN-INST-DEF"
LN_RET_DEF: str = "DFP-LN-RET-DEF"
LN_CORP_GTD_DEF: str = "DFP-LN-CORP-GTD-DEF"
LN_RRE_DEF: str = "DFP-LN-RRE-DEF"
LN_HR_DEF: str = "DFP-LN-HR-DEF"
LN_HR_PERF: str = "DFP-LN-HR-PERF"
LN_RRE_GTD: str = "DFP-LN-RRE-GTD"

#: Drawn amounts, in GBP. Distinct per leg, and so is each leg's RWEA.
DRAWN: dict[str, float] = {
    LN_SOV_DEF: 1_200_000.0,
    LN_RGLA_DEF: 800_000.0,
    LN_PSE_DEF: 600_000.0,
    LN_INST_DEF: 900_000.0,
    LN_RET_DEF: 150_000.0,
    LN_CORP_GTD_DEF: 2_000_000.0,
    LN_RRE_DEF: 350_000.0,
    LN_HR_DEF: 700_000.0,
    LN_HR_PERF: 450_000.0,
    LN_RRE_GTD: 500_000.0,
}

#: Specific credit risk adjustment on each provisioned leg, as a share of its drawn
#: amount. Three at or above the Art. 127(1) 20% threshold, two below, and the
#: real-estate default below it too (Art. 127(3) decides that leg, not the test).
PROVISION_SHARE: dict[str, float] = {
    LN_SOV_DEF: 0.25,
    LN_RGLA_DEF: 0.05,
    LN_PSE_DEF: 0.30,
    LN_INST_DEF: 0.10,
    LN_RET_DEF: 0.30,
    LN_RRE_DEF: 0.05,
}

#: The guaranteed shares.
GUARANTEED_SHARE: dict[str, float] = {
    LN_CORP_GTD_DEF: 0.40,
    LN_RRE_GTD: 0.20,
}

#: Who guarantees each guaranteed leg: a CQS 2 institution (a non-zero weight, so
#: the RWEA crossing to it is a figure — LESSONS C2) on the defaulted corporate, the
#: CQS 1 UK sovereign (0%, unambiguously beneficial) on the loan split.
GUARANTOR: dict[str, str] = {
    LN_CORP_GTD_DEF: CP_INST_GTOR,
    LN_RRE_GTD: CP_SOV_GTOR,
}

#: The guarantors' credit quality steps (external ratings).
GUARANTOR_CQS: dict[str, int] = {CP_INST_GTOR: 2, CP_SOV_GTOR: 1}

#: The loan-to-value of the two residential mortgages: past the Art. 124F 55% cap,
#: so the performing one splits into two parts.
RRE_LTV: float = 0.60

#: The legs each framework's book holds. CRR expresses no high-risk class and no
#: Art. 124F loan split (module docstring).
CRR_LOANS: tuple[str, ...] = (
    LN_SOV_DEF,
    LN_RGLA_DEF,
    LN_PSE_DEF,
    LN_INST_DEF,
    LN_RET_DEF,
    LN_CORP_GTD_DEF,
    LN_RRE_DEF,
)
B31_ONLY_LOANS: tuple[str, ...] = (LN_HR_DEF, LN_HR_PERF, LN_RRE_GTD)

#: Defaulted legs whose class before default has a published memo sheet, and the
#: Art. 112(1) class that sheet is keyed on (Basel 3.1).
B31_MEMO_ORIGIN_CLASS: dict[str, str] = {
    LN_SOV_DEF: "central_govt_central_bank",
    LN_RGLA_DEF: "rgla",
    LN_PSE_DEF: "pse",
    LN_INST_DEF: "institution",
    LN_RET_DEF: "retail_other",
    LN_CORP_GTD_DEF: "corporate",
}

_VALUE_DATE: date = date(2020, 1, 1)
_MATURITY: date = date(2031, 12, 31)  # > both reporting dates (CRR 2025, B31 2027)
_GUARANTEE_MATURITY: date = date(2035, 1, 1)

_FRAMEWORKS: frozenset[str] = frozenset({FRAMEWORK_CRR, FRAMEWORK_B31})


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_default_populations_bundle(framework: str) -> RawDataBundle:
    """Assemble the defaulted-populations book for one framework, as a sealed bundle.

    ``framework`` is ``"CRR"`` or ``"BASEL_3_1"``: the CRR book leaves out the legs
    CRR cannot express (``B31_ONLY_LOANS``, module docstring). Run it through
    ``PipelineOrchestrator().run_with_data`` with ``PermissionMode.STANDARDISED`` —
    every obligor carries an external rating or none, never an internal PD.

    Raises:
        ValueError: ``framework`` is not one of the two (a programming error).
    """
    if framework not in _FRAMEWORKS:
        msg = f"framework must be one of {sorted(_FRAMEWORKS)}, got {framework!r}"
        raise ValueError(msg)
    loans = CRR_LOANS if framework == FRAMEWORK_CRR else (*CRR_LOANS, *B31_ONLY_LOANS)
    return make_raw_bundle(
        counterparties=_counterparties(loans),
        loans=_loans(loans),
        ratings=_ratings(loans),
        provisions=_provisions(loans),
        guarantees=_guarantees(loans),
        collateral=_collateral(loans),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties(loans: tuple[str, ...]) -> pl.DataFrame:
    """The obligors of ``loans`` and their guarantors.

    A defaulted obligor carries ``default_status`` as well as its loan's
    ``is_defaulted``, as ``rich``'s ``CP_DEFAULT`` does.
    """
    rows: list[dict] = [
        _obligor(CP_SOV_DEF, "sovereign", defaulted=True),
        _obligor(CP_RGLA_DEF, "rgla_institution", defaulted=True, country_code="US"),
        _obligor(CP_PSE_DEF, "pse_institution", defaulted=True),
        _obligor(CP_INST_DEF, "institution", defaulted=True),
        _natural_person(CP_RET_DEF, defaulted=True),
        {
            **_obligor(CP_CORP_GTD_DEF, "corporate", defaulted=True),
            # Above the SME ceiling in both regimes: no supporting factor, no SME limb.
            "annual_revenue": 200_000_000.0,
        },
        _obligor(CP_INST_GTOR, "institution", defaulted=False),
        _natural_person(CP_RRE_DEF, defaulted=True),
    ]
    if LN_HR_DEF in loans:
        rows.extend(
            [
                _obligor(CP_HR_DEF, "high_risk", defaulted=True),
                _obligor(CP_HR_PERF, "high_risk", defaulted=False),
                _natural_person(CP_RRE_GTD, defaulted=False),
                _obligor(CP_SOV_GTOR, "sovereign", defaulted=False),
            ]
        )
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings(loans: tuple[str, ...]) -> pl.DataFrame:
    """External ratings only, so every leg routes SA.

    The defaulted sovereign and institution are rated so their class before default
    is unambiguous; each guarantor of a leg in ``loans`` at ``GUARANTOR_CQS``, a
    weight below every defaulted or real-estate weight it protects.
    """
    rows: list[dict] = [
        _external(CP_SOV_DEF, cqs=3),
        _external(CP_INST_DEF, cqs=2),
        *(
            _external(GUARANTOR[loan], cqs=GUARANTOR_CQS[GUARANTOR[loan]])
            for loan in GUARANTOR
            if loan in loans
        ),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans(loans: tuple[str, ...]) -> pl.DataFrame:
    """One drawn loan per leg in ``loans``. Defaulted legs carry ``is_defaulted``."""
    obligor = {
        LN_SOV_DEF: CP_SOV_DEF,
        LN_RGLA_DEF: CP_RGLA_DEF,
        LN_PSE_DEF: CP_PSE_DEF,
        LN_INST_DEF: CP_INST_DEF,
        LN_RET_DEF: CP_RET_DEF,
        LN_CORP_GTD_DEF: CP_CORP_GTD_DEF,
        LN_RRE_DEF: CP_RRE_DEF,
        LN_HR_DEF: CP_HR_DEF,
        LN_HR_PERF: CP_HR_PERF,
        LN_RRE_GTD: CP_RRE_GTD,
    }
    performing = {LN_HR_PERF, LN_RRE_GTD}
    mortgages = {LN_RRE_DEF, LN_RRE_GTD}
    rows: list[dict] = []
    for loan in loans:
        row = _loan(loan, obligor[loan], DRAWN[loan], defaulted=loan not in performing)
        if loan in mortgages:
            # Not income-producing: Art. 124F (performing) / Art. 127(3) (defaulted).
            row |= {"property_type": "residential", "ltv": RRE_LTV, "has_income_cover": False}
        rows.append(row)
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _collateral(loans: tuple[str, ...]) -> pl.DataFrame:
    """The residential property behind each mortgage in ``loans``, at ``RRE_LTV``.

    The real-estate branch fires only when a property collateral row is linked to the
    loan: the loan-level ``property_type`` / ``ltv`` alone leave it retail (measured,
    and the same note ``reporting_portfolio.py::_collateral`` carries).
    """
    rows: list[dict] = [
        {
            "collateral_reference": f"DFP-COL-{loan}",
            "collateral_type": "real_estate",
            "property_type": "residential",
            "currency": "GBP",
            "market_value": DRAWN[loan] / RRE_LTV,
            "property_ltv": RRE_LTV,
            "beneficiary_type": "loan",
            "beneficiary_reference": loan,
        }
        for loan in (LN_RRE_DEF, LN_RRE_GTD)
        if loan in loans
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COLLATERAL_SCHEMA))


def _provisions(loans: tuple[str, ...]) -> pl.DataFrame:
    """A stage-3 specific credit risk adjustment on each provisioned leg in ``loans``."""
    rows: list[dict] = [
        {
            "provision_reference": f"DFP-PRV-{loan}",
            "provision_type": "scra",
            "ifrs9_stage": 3,
            "currency": "GBP",
            "amount": DRAWN[loan] * share,
            "beneficiary_type": "loan",
            "beneficiary_reference": loan,
        }
        for loan, share in PROVISION_SHARE.items()
        if loan in loans
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(PROVISION_SCHEMA))


def _guarantees(loans: tuple[str, ...]) -> pl.DataFrame:
    """The partial guarantee of each guaranteed leg in ``loans``, by its ``GUARANTOR``."""
    rows: list[dict] = [
        {
            "guarantee_reference": f"DFP-GTE-{loan}",
            "guarantor": GUARANTOR[loan],
            "currency": "GBP",
            "maturity_date": _GUARANTEE_MATURITY,
            "amount_covered": DRAWN[loan] * share,
            "percentage_covered": share,
            "beneficiary_type": "loan",
            "beneficiary_reference": loan,
            "protection_type": "guarantee",
            "includes_restructuring": True,
            "guarantor_seniority": "senior",
            "is_unilaterally_cancellable": False,
            "is_unilaterally_changeable": False,
        }
        for loan, share in GUARANTEED_SHARE.items()
        if loan in loans
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(GUARANTEE_SCHEMA))


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _obligor(
    reference: str, entity_type: str, *, defaulted: bool, country_code: str = "GB"
) -> dict:
    return {
        "counterparty_reference": reference,
        "entity_type": entity_type,
        "country_code": country_code,
        "default_status": defaulted,
    }


def _natural_person(reference: str, *, defaulted: bool) -> dict:
    return {
        **_obligor(reference, "individual", defaulted=defaulted),
        "is_natural_person": True,
        "is_managed_as_retail": True,
        # Paid in the lending currency: no Art. 123B currency mismatch to identify.
        "borrower_income_currency": "GBP",
    }


def _loan(reference: str, counterparty: str, amount: float, *, defaulted: bool) -> dict:
    """One fully-drawn senior GBP loan (unset optional columns take schema defaults)."""
    return {
        "loan_reference": reference,
        "counterparty_reference": counterparty,
        "product_type": "term_loan",
        "drawn_amount": amount,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
        "is_defaulted": defaulted,
    }


def _external(counterparty_reference: str, *, cqs: int) -> dict:
    """External ECAI rating row (CQS only — no internal PD, so SA routing)."""
    return {
        "rating_reference": f"DFP-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "external",
        "rating_agency": "TEST_AGENCY",
        "cqs": cqs,
        "rating_date": _VALUE_DATE,
    }
