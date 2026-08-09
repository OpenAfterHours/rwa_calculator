"""
Funded credit protection reporting portfolios — the two DEAD funded-CRM axes.

Pipeline position:
    build_reporting_fcsm_bundle()   -> RawDataBundle -> PipelineOrchestrator
    build_reporting_art199_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Why TWO builders in one module: they are the two halves of the same negative
space. Every funded-protection column in the estate that reports something
OTHER than the comprehensive-method EAD reduction was measured at ``0.00``
across all twelve registered golden runs — six portfolios x two regimes — for
the same reason in both cases: no fixture ever elected the Simple Method, and no
fixture ever pledged Art. 199 non-financial collateral. They belong together
because they are one gap seen from the SA side and the IRB side, and separating
them would leave two modules whose docstrings each said "see the other one".

Measured BEFORE state, per carrier, summed over those twelve runs:

    carrier                             | total  | template cell
    ------------------------------------|--------|--------------------------
    fcsm_collateral_value               |   0.00 | COREP C 07.00 col 0070
    collateral_receivables_value        |   0.00 | Pillar 3 CR7-A col e
    collateral_other_physical_value     |   0.00 | Pillar 3 CR7-A col f
    reporting_crm_lgd_receivables       |   0.00 | COREP C 08.01/02 col 0210
    reporting_crm_lgd_other_physical    |   0.00 | COREP C 08.01/02 col 0200
    reporting_crm_lgd_real_estate       |  35.6m | COREP C 08.01/02 col 0190

The last line is the point of the ``RE`` row in the Art. 199 portfolio: it is
the LIVE sibling that must NOT move. A conservation or coverage rule written
over the (real estate, other physical, receivables) family is vacuous while two
of its three members are identically zero — the rule passes on the empty set —
and a fixture that lit only the two dead members could not tell "the family is
now covered" from "the family moved wholesale". ``.claude/LESSONS.md`` B5's
two-leg pattern: one cell that survives, one that moves.

## Portfolio 1 — ``build_reporting_fcsm_bundle`` (CRR Art. 222)

The Financial Collateral Simple Method substitutes the COLLATERAL's own risk
weight on the covered part of the exposure instead of reducing the exposure
value, which is why COREP Annex II gives it a column of its own — C 07.00
col 0070 "(-) Financial collateral: Simple method" — separate from the
comprehensive method's effect on cols 0150/0200. The method is a firm-wide
election (Art. 191A), so this portfolio is only meaningful when run with
``crm_collateral_method=CRMCollateralMethod.SIMPLE``; under the default
comprehensive election the same rows produce ``0.00`` in col 0070 and the test
file asserts exactly that as the control.

    ref              | collateral        | Art. 222 limb
    -----------------|-------------------|----------------------------------
    FCSM_LN_ANCHOR   | none              | the unsubstituted survivor
    FCSM_LN_BOND     | 0%-RW sovereign   | (1) collateral RW, subject to the
                     |   bond, USD       |     ``fcsm_rw_floor``
    FCSM_LN_CASH     | cash, GBP         | (4)(a) same-currency 0% carve-out

``FCSM_LN_BOND`` is denominated in a DIFFERENT currency from the exposure on
purpose: Art. 222(4)'s 0%-RW carve-out is conditional on a currency match, so a
GBP sovereign bond would take the carve-out and the ``fcsm_rw_floor`` limb —
the general case, and the only one that produces a non-zero substituted weight
— would never be exercised. With the pair present, col 0070 carries both limbs
and the two are distinguishable by their effect on RWEA.

Both exposures are deliberately PARTLY covered. A fully covered exposure leaves
no unsubstituted remainder, so a defect in how the blend weights the two halves
would be invisible.

## Portfolio 2 — ``build_reporting_art199_bundle`` (CRR Art. 199)

Art. 199 is headed "Additional eligibility for collateral under the IRB
Approach" and admits three forms the Standardised Approach does not recognise:
(a) immovable property, (b) receivables, (c) other physical collateral. Their
effect is on LGD, not on the exposure value, so COREP C 08.01/02 reports them in
the "CRM techniques taken into account in LGD estimates" block (cols 0190 / 0200
/ 0210) and Pillar 3 CR7-A reports each as a percentage of exposure (cols d / e
/ f).

    ref               | collateral      | C 08.01 col | CR7-A col | state before
    ------------------|-----------------|-------------|-----------|-------------
    A199_LN_ANCHOR    | none            |      --     |     --    |     --
    A199_LN_RE        | immovable prop. |    0190     |     d     | LIVE (35.6m)
    A199_LN_RECV      | receivables     |    0210     |     e     | DEAD (0.00)
    A199_LN_PHYSICAL  | other physical  |    0200     |     f     | DEAD (0.00)

``is_eligible_irb_collateral=True`` is attested on every non-financial pledge
and is load-bearing: the Art. 199 recognition gate zeroes any non-financial
collateral without it, silently. The recorded blast radius of that gate when it
was introduced was 4 files and 38 tests, none of them findable by grepping for
the field — so its absence here would produce a portfolio that looks right and
reports nothing.

Coverage is sized above the Art. 230 ``min_collateralisation_thresholds`` entry
for each category, so each pledge actually reaches the LGD* calculation rather
than being dropped at the threshold. The pack is the source for both that
threshold and the Art. 230 overcollateralisation divisor; the amounts here are
chosen to clear the threshold comfortably, not to sit on it — this portfolio is
about the reporting columns, and the threshold boundary has its own unit tests.

The portfolio runs ``PermissionMode.IRB`` with an internal PD and no firm LGD
estimate, so every leg routes FOUNDATION IRB. That is deliberate: under A-IRB
the CRM-in-LGD columns switch basis to the estimated market value
(``_crm_lgd_carriers``), and an F-IRB run reports the adjusted value C_i — the
basis the Art. 199 recognition actually produces.

Deliberately OUT of scope:
- Life-insurance and third-party-deposit collateral (Art. 200(1) / Art. 232).
  They are "other funded credit protection" and land in C 07.00 col 0080, a
  different column with a different mechanism, and they already have carriers
  wired (``_OFCP_CARRIERS``).
- A-IRB legs. See above — they would report a different basis in the same
  columns and make a moved number ambiguous between basis and recognition.
- SA legs pledging receivables / other physical. Art. 199 is IRB-only, so under
  SA the pledge is correctly worth nothing; a row proving that belongs with the
  eligibility unit tests, not in a template-coverage portfolio.

References:
- CRR Art. 191A / PS1/26 Art. 191A: firm-wide CRM method election
- CRR Art. 222(1): Simple Method — collateral risk weight, subject to a floor
- CRR Art. 222(4): the same-currency 0% carve-out for cash and 0%-RW debt
- CRR Art. 199(a)/(b)/(c): IRB-only immovable property, receivables, other physical
- CRR Art. 230: overcollateralisation divisors and minimum collateralisation
- COREP Annex II, C 07.00 col 0070; C 08.01/02 cols 0190 / 0200 / 0210
- Pillar 3 CR7-A cols d / e / f (funded credit protection, % of exposure)
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: The model_id ``create_full_irb_model_permissions`` grants F-IRB for.
MODEL_ID: str = "TEST_FULL_IRB"

# --- Portfolio 1: Financial Collateral Simple Method (CRR Art. 222) --------

FCSM_CP: str = "RFP-CP-FCSM"

FCSM_LN_ANCHOR: str = "RFP-LN-FCSM-ANCHOR"  # no collateral — the survivor
FCSM_LN_BOND: str = "RFP-LN-FCSM-BOND"  # Art. 222(1) floored collateral RW
FCSM_LN_CASH: str = "RFP-LN-FCSM-CASH"  # Art. 222(4)(a) same-currency 0%

FCSM_DRAWN_ANCHOR: float = 1_000_000.0
FCSM_DRAWN_BOND: float = 2_000_000.0
FCSM_DRAWN_CASH: float = 1_000_000.0

FCSM_COLLATERAL_BOND: float = 800_000.0
FCSM_COLLATERAL_CASH: float = 400_000.0

#: What C 07.00 col 0070 must report: the raw market value of every eligible
#: financial collateral item recognised under the Simple Method. Distinct
#: per item so a dropped one is identifiable from the cell value alone.
FCSM_EXPECTED_COL_0070: float = FCSM_COLLATERAL_BOND + FCSM_COLLATERAL_CASH

FCSM_TOTAL_DRAWN: float = FCSM_DRAWN_ANCHOR + FCSM_DRAWN_BOND + FCSM_DRAWN_CASH

# --- Portfolio 2: Art. 199 IRB-only collateral -----------------------------

A199_CP: str = "RFP-CP-A199"

A199_LN_ANCHOR: str = "RFP-LN-A199-ANCHOR"  # unsecured
A199_LN_RE: str = "RFP-LN-A199-RE"  # Art. 199(a) — the LIVE sibling
A199_LN_RECV: str = "RFP-LN-A199-RECV"  # Art. 199(b) — dead before this
A199_LN_PHYSICAL: str = "RFP-LN-A199-PHYS"  # Art. 199(c) — dead before this

A199_DRAWN: float = 2_000_000.0
A199_DRAWN_ANCHOR: float = 1_000_000.0

A199_COLLATERAL_RE: float = 1_500_000.0
A199_COLLATERAL_RECV: float = 1_000_000.0
A199_COLLATERAL_PHYSICAL: float = 1_500_000.0

A199_TOTAL_DRAWN: float = A199_DRAWN_ANCHOR + 3 * A199_DRAWN

#: Internal PD, comfortably above every regime's PD floor so the floor is not
#: what determines the risk weight and a moved LGD is visible in RWEA.
A199_PD: float = 0.02

#: Aggregator carrier -> the COREP C 08.01/02 column that reports it. The test
#: file drives its assertions off this map so a fourth Art. 199 category added
#: later is covered without editing an assertion.
A199_CARRIER_TO_C08_COLUMN: dict[str, str] = {
    "reporting_crm_lgd_real_estate": "0190",
    "reporting_crm_lgd_other_physical": "0200",
    "reporting_crm_lgd_receivables": "0210",
}

#: Aggregator carrier -> the Pillar 3 CR7-A column that reports it as a
#: percentage of exposure.
A199_CARRIER_TO_CR7A_COLUMN: dict[str, str] = {
    "collateral_re_value": "d",
    "collateral_receivables_value": "e",
    "collateral_other_physical_value": "f",
}

#: The two carriers this portfolio exists to move off zero, and the one that
#: must stay live and unmoved beside them (LESSONS B5's two-leg pattern).
A199_PREVIOUSLY_DEAD_CARRIERS: tuple[str, ...] = (
    "reporting_crm_lgd_other_physical",
    "reporting_crm_lgd_receivables",
)
A199_LIVE_SIBLING_CARRIER: str = "reporting_crm_lgd_real_estate"

_VALUE_DATE: date = date(2015, 1, 1)
_MATURITY: date = date(2035, 12, 31)  # beyond both reporting dates


# ---------------------------------------------------------------------------
# Main public entry points
# ---------------------------------------------------------------------------


def build_reporting_fcsm_bundle() -> RawDataBundle:
    """Assemble the Financial Collateral Simple Method portfolio.

    Run it through ``PipelineOrchestrator().run_with_data`` under either regime
    with ``PermissionMode.STANDARDISED`` **and**
    ``crm_collateral_method=CRMCollateralMethod.SIMPLE`` — Art. 222 is an SA
    mechanism and a firm-wide election, so both are required for C 07.00
    col 0070 to carry anything.
    """
    return make_raw_bundle(
        counterparties=_fcsm_counterparties(),
        loans=_fcsm_loans(),
        collateral=_fcsm_collateral(),
        ratings=_fcsm_ratings(),
    )


def build_reporting_art199_bundle() -> RawDataBundle:
    """Assemble the Art. 199 IRB-collateral portfolio.

    Run it through ``PipelineOrchestrator().run_with_data`` under either regime
    with ``PermissionMode.IRB``. Every obligor carries an internal PD and no
    firm LGD estimate, so the legs route Foundation IRB and the CRM-in-LGD
    columns report the adjusted value C_i.
    """
    return make_raw_bundle(
        counterparties=_a199_counterparties(),
        loans=_a199_loans(),
        collateral=_a199_collateral(),
        ratings=_a199_ratings(),
        model_permissions=create_full_irb_model_permissions(),
    )


# ---------------------------------------------------------------------------
# Portfolio 1 table builders (private)
# ---------------------------------------------------------------------------


def _fcsm_counterparties() -> pl.DataFrame:
    """One large corporate — the Simple Method axis is about the COLLATERAL's
    risk weight, so a second obligor class would add a sheet without adding a
    limb of Art. 222."""
    rows: list[dict] = [
        {
            "counterparty_reference": FCSM_CP,
            "counterparty_name": FCSM_CP,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 250_000_000.0,
            "default_status": False,
        }
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _fcsm_ratings() -> pl.DataFrame:
    """An external CQS so the obligor's own weight is a table lookup, not the
    unrated default — the substituted and unsubstituted halves of each exposure
    must be distinguishable, and an unrated weight that happened to equal the
    floored collateral weight would hide a substitution that never ran."""
    rows: list[dict] = [
        {
            "rating_reference": "RFP-RTG-FCSM",
            "counterparty_reference": FCSM_CP,
            "rating_type": "external",
            "rating_agency": "TEST_AGENCY",
            "rating_value": "BBB",
            "cqs": 3,
            "rating_date": _VALUE_DATE,
        }
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _fcsm_loans() -> pl.DataFrame:
    """Three drawn term loans: one unsecured survivor and one per Art. 222 limb."""
    rows: list[dict] = [
        _loan(FCSM_LN_ANCHOR, FCSM_CP, FCSM_DRAWN_ANCHOR),
        _loan(FCSM_LN_BOND, FCSM_CP, FCSM_DRAWN_BOND),
        _loan(FCSM_LN_CASH, FCSM_CP, FCSM_DRAWN_CASH),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _fcsm_collateral() -> pl.DataFrame:
    """Two eligible financial pledges, one per Art. 222 limb.

    ``is_eligible_financial_collateral=True`` on both: Art. 197 is the financial
    collateral list and both a central-government debt security and cash are on
    it. ``issuer_type`` / ``issuer_cqs`` describe the ISSUER because Art. 222(1)
    substitutes "the risk weight prescribed under Chapter 2 of Title II for the
    type of collateral" — i.e. the weight the collateral would carry if it were
    itself an exposure — which is an issuer lookup.
    """
    rows: list[dict] = [
        {
            "collateral_reference": "RFP-COL-FCSM-BOND",
            # ``government_bond``, NOT ``bond``. Both pass loader validation, but
            # ``bond`` is absent from ``FINANCIAL_COLLATERAL_TYPES``, so the CRM
            # category dispatch treats it as unclassified: measured, it raises
            # CRM021 + CRM014 and leaves ``collateral_financial_value`` at 0.00
            # (col 0070 is unaffected either way, because the Simple Method gates
            # on ``is_eligible_financial_collateral`` rather than on the category
            # list — which is exactly how a dead pledge stays invisible).
            "collateral_type": "government_bond",
            # USD against a GBP exposure: Art. 222(4)'s 0% carve-out requires a
            # currency match, so this item takes the Art. 222(1) route and the
            # ``fcsm_rw_floor`` binds. See the module docstring.
            "currency": "USD",
            "market_value": FCSM_COLLATERAL_BOND,
            "nominal_value": FCSM_COLLATERAL_BOND,
            "beneficiary_type": "loan",
            "beneficiary_reference": FCSM_LN_BOND,
            "issuer_type": "sovereign",
            "issuer_cqs": 1,
            "residual_maturity_years": 10.0,
            "original_maturity_years": 15.0,
            "is_eligible_financial_collateral": True,
            "is_eligible_irb_collateral": False,
            "valuation_date": _VALUE_DATE,
            "valuation_type": "market",
        },
        {
            "collateral_reference": "RFP-COL-FCSM-CASH",
            "collateral_type": "cash",
            "currency": "GBP",
            "market_value": FCSM_COLLATERAL_CASH,
            "nominal_value": FCSM_COLLATERAL_CASH,
            "beneficiary_type": "loan",
            "beneficiary_reference": FCSM_LN_CASH,
            "issuer_type": "institution",
            "issuer_cqs": 1,
            "residual_maturity_years": 10.0,
            "original_maturity_years": 15.0,
            "is_eligible_financial_collateral": True,
            "is_eligible_irb_collateral": False,
            "valuation_date": _VALUE_DATE,
            "valuation_type": "market",
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Portfolio 2 table builders (private)
# ---------------------------------------------------------------------------


def _a199_counterparties() -> pl.DataFrame:
    """One large corporate. Art. 199 eligibility is a property of the
    COLLATERAL, not of the obligor, so one obligor reaches all three limbs and
    keeps every leg on a single C 08.01 sheet where the three columns sit side
    by side and can be compared against each other."""
    rows: list[dict] = [
        {
            "counterparty_reference": A199_CP,
            "counterparty_name": A199_CP,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 250_000_000.0,
            "default_status": False,
        }
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _a199_ratings() -> pl.DataFrame:
    """An internal PD with a ``model_id`` — the F-IRB routing requirement.

    No firm LGD estimate anywhere in the portfolio, so the supervisory LGD
    applies and the Art. 199 collateral works through the Foundation Collateral
    Method's LGD* rather than through an own estimate.
    """
    rows: list[dict] = [
        {
            "rating_reference": "RFP-RTG-A199",
            "counterparty_reference": A199_CP,
            "rating_type": "internal",
            "pd": A199_PD,
            "model_id": MODEL_ID,
            "rating_date": _VALUE_DATE,
        }
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _a199_loans() -> pl.DataFrame:
    """Four drawn term loans: the unsecured anchor plus one per Art. 199 limb."""
    rows: list[dict] = [
        _loan(A199_LN_ANCHOR, A199_CP, A199_DRAWN_ANCHOR),
        _loan(A199_LN_RE, A199_CP, A199_DRAWN),
        _loan(A199_LN_RECV, A199_CP, A199_DRAWN),
        _loan(A199_LN_PHYSICAL, A199_CP, A199_DRAWN),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _a199_collateral() -> pl.DataFrame:
    """One pledge per Art. 199 limb, each attested IRB-eligible.

    ``is_eligible_financial_collateral=False`` on all three: none of them is on
    the Art. 197 financial-collateral list, and attesting both flags would route
    one pledge through the financial-collateral haircut chain as well as the
    Art. 199 route and double-count the benefit.
    """
    rows: list[dict] = [
        _irb_collateral(
            "RFP-COL-A199-RE",
            A199_LN_RE,
            "real_estate",
            A199_COLLATERAL_RE,
            property_type="commercial",
            property_ltv=A199_DRAWN / A199_COLLATERAL_RE,
        ),
        _irb_collateral(
            "RFP-COL-A199-RECV",
            A199_LN_RECV,
            "receivables",
            A199_COLLATERAL_RECV,
        ),
        _irb_collateral(
            "RFP-COL-A199-PHYS",
            A199_LN_PHYSICAL,
            "other_physical",
            A199_COLLATERAL_PHYSICAL,
        ),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COLLATERAL_SCHEMA))


def _irb_collateral(
    reference: str,
    loan_ref: str,
    collateral_type: str,
    market_value: float,
    *,
    property_type: str | None = None,
    property_ltv: float | None = None,
) -> dict:
    """One Art. 199 non-financial pledge on one loan."""
    row = {
        "collateral_reference": reference,
        "collateral_type": collateral_type,
        "currency": "GBP",
        "market_value": market_value,
        "nominal_value": market_value,
        "beneficiary_type": "loan",
        "beneficiary_reference": loan_ref,
        "residual_maturity_years": 10.0,
        "original_maturity_years": 15.0,
        "is_eligible_financial_collateral": False,
        # Load-bearing: the Art. 199 recognition gate zeroes a non-financial
        # pledge that does not attest this, and does it silently.
        "is_eligible_irb_collateral": True,
        "valuation_date": _VALUE_DATE,
        "valuation_type": "market",
    }
    if property_type is None:
        return row
    return row | {
        "property_type": property_type,
        "property_ltv": property_ltv,
        "is_income_producing": False,
        "is_adc": False,
        "is_presold": False,
        "is_qualifying_re": True,
    }


# ---------------------------------------------------------------------------
# Shared row builder (private)
# ---------------------------------------------------------------------------


def _loan(ref: str, cp_ref: str, drawn: float) -> dict:
    """A plain drawn, on-balance-sheet, senior term loan.

    Both portfolios are 100% on balance sheet: a conversion factor between the
    nominal and the covered amount would put a second moving part between the
    pledge and the column under test.
    """
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
