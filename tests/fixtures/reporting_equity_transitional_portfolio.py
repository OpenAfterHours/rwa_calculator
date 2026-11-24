"""
Standardised-firm equity under the PS1/26 transitional — OF 07.00 rows 0250 / 0261 / 0371-0374.

Pipeline position:
    build_reporting_equity_transitional_bundle() -> RawDataBundle
        -> PipelineOrchestrator (Basel 3.1, PermissionMode.STANDARDISED, 2027-06-01)
        -> AggregatedResultBundle -> COREPGenerator (OF 07.00 sheet 0016 and Total)

Why this portfolio exists. It is the first registered book in which a firm
WITHOUT IRB permission holds class (p) equity during 2027-2029, so it is the
first in which an equity leg's applied risk weight is not its Article 133
weight. Every earlier registered run either held no direct equity
(``off-bs`` holds a CIU, the others nothing) or held it under an IRB
permission (``b31/rich``), which keeps the Art. 133 weights. Two things were
therefore unobservable on the gated estate (``.claude/LESSONS.md`` B5):

- the Credit Risk: General Provisions (CRR) Part rules 4.2 / 4.3 weights
  themselves (ps126app1.pdf pp.20-21: "shall be assigned the following risk
  weights: (1) 160% [...] 2027" and, for higher risk equity, "(1) 220%
  [...] 2027"); and
- the row they are REPORTED on. PS1/26 Annex II p.95: such exposures "shall be
  reported against the risk weights set out in Article 133 [...] disregarding
  the transitional provisions. However, the RWEA shall still reflect the
  transitional provisions." p.96, row 0250: "Exposures subject to rules 4.1 to
  4.10 [...] should be reported in this row during the transitional period if
  they qualify as an equity exposure as set out in Article 133(1) and (2)";
  row 0261 likewise for "a higher risk equity exposure". 160% and 220% are not
  rows of the template, so a leg banded on its applied weight falls to row
  0280 "Other risk weights", which the Bank's ``boe_b0458`` requires empty on
  sheet 0016. Memorandum rows 0371-0374 (p.97: "Institutions shall report all
  equity exposures to which the Standardised Transitional Approach for equities
  applies in these rows") were null on every registered run.

## The ten legs — the transitional's movers and stayers, the weight-chain pairs, an anchor

    ref                   | equity_type             | Art. 133 | applied | RWEA      | row  | memo
    ----------------------|-------------------------|----------|---------|-----------|------|-----
    ETR-EQ-LISTED         | listed                  | 250%     | 160%    | 1,600,000 | 0250 | 0372
    ETR-EQ-YOUNG          | unlisted, age 2y        | 400%     | 220%    | 1,100,000 | 0261 | 0371
    ETR-EQ-SUB-DEBT       | subordinated_debt       | 150%     | 150%    |   300,000 | 0240 | -
    ETR-EQ-SIGNIFICANT    | listed, Art. 48(4)      | 250%     | 250%    |   750,000 | 0250 | -
    ETR-EQ-FLAGGED        | other, flag             | 400%     | 220%    |   220,000 | 0261 | 0371
    ETR-EQ-FLAGGED-LISTED | listed, flag            | 250%     | 160%    |   640,000 | 0250 | 0372
    ETR-EQ-FLAGGED-AGED   | other, flag, age 10y    | 250%     | 160%    |   960,000 | 0250 | 0372
    ETR-EQ-GOV-YOUNG      | government_supported 2y | 400%     | 220%    |   550,000 | 0261 | 0371
    ETR-EQ-SIG-YOUNG      | unlisted 2y, Art. 48(4) | 250%     | 250%    |   375,000 | 0250 | -
    ETR-LN-ANCHOR         | corporate loan          | 100%     | 100%    | 2,000,000 | 0230 | -

Exposure values 1,000,000 / 500,000 / 200,000 / 300,000 / 100,000 / 400,000 /
600,000 / 250,000 / 150,000 / 2,000,000.

- ``ETR-EQ-LISTED`` and ``ETR-EQ-YOUNG`` are the legs the transitional MOVES.
  The young leg reaches the Art. 133(4) rung through the Glossary limb ("not
  listed on a recognised exchange; and [...] whose business has existed for a
  period of less than five years"), not through a flag, so its higher-risk
  status is the predicate's to decide.
- ``ETR-EQ-SUB-DEBT`` must NOT move: Art. 133(5) gives 150% to an instrument
  "not classified as an equity exposure", which rules 4.2 / 4.3 do not reach.
  It also keeps row 0240 live beside the moving rows.
- ``ETR-EQ-SIGNIFICANT`` must NOT move: an Art. 133(6)(c) item (an Own Funds
  Art. 48(4) holding at 250%), which both rules exclude by name ("within the
  scope of paragraph 6"). It shares row 0250 with ``ETR-EQ-LISTED``, so row 0250
  is NOT memorandum row 0372 and a test cannot confuse the two.
- ``ETR-LN-ANCHOR`` puts a second class on the Total sheet, so the Total's row
  0010 is not the equity sheet's.

The five weight-chain legs (P1.207, P1.393) are two-leg pairs with the legs
above (``.claude/LESSONS.md`` B5: a leg that moves beside one that must not), so
OF 07.00 placement is gated on each side of the Glossary "higher risk equity
exposure" test ("(1) not listed on a recognised exchange; and (2) [...] whose
business has existed for a period of less than five years"):

- ``ETR-EQ-FLAGGED`` stays on the 400% rung: the ``is_speculative`` flag supplies
  the business age the row does not state. ``ETR-EQ-FLAGGED-LISTED`` and
  ``ETR-EQ-FLAGGED-AGED`` carry the same flag but contradict the test (a listed
  type; a business age of ten years), so they are Art. 133(3) 250% legs and take
  rule 4.2. Before P1.207 both were weighted 400% / rule 4.3 and reported in rows
  0261 / 0371.
- ``ETR-EQ-GOV-YOUNG`` is unlisted government-supported equity with a business
  under five years: the Glossary has no government-supported carve-out, so it is
  higher risk like ``ETR-EQ-YOUNG``. Before P1.393(c) it took rule 4.2 in rows
  0250 / 0372.
- ``ETR-EQ-SIG-YOUNG`` is higher risk AND an Art. 133(6)(c) significant
  investment: paragraph 6 displaces Art. 133(4), so it is 250% on every date and
  outside the transitional, like ``ETR-EQ-SIGNIFICANT``. Before P1.393(b) it took
  400% and was reported in row 0261.

Hand calculation, OF 07.00 sheet 0016 (class (p)), cols 0200 / 0220:
row 0010 3,500,000 / 6,495,000; row 0240 200,000 / 300,000; row 0250
2,450,000 / 4,325,000; row 0261 850,000 / 1,870,000; row 0280 null; row 0371
850,000 / 1,870,000; row 0372 2,000,000 / 3,200,000; rows 0373 / 0374 null.

What a correct return of this book does to the Bank's rules (PI-01, a defect
in the published rules, not in this book): ``boe_b1016`` / ``boe_b1031``
(ERROR, Total sheet: RWEA >= 2.5 x / 4 x exposure value on rows 0250 / 0261)
and ``boe_b0491`` / ``boe_b0506`` (WARNING, sheet 0016: RWEA = 2.5 x / 4 x)
FAIL, because the transitional weights are below the row weights for all of
2027-2029; ``boe_b0710_2`` (ERROR, rows 0371-0374: col 0150 = the sum of the
off-balance-sheet conversion-factor columns) FAILS because an equity holding is
on-balance-sheet. Those are register entries to bank, never figures to bend.

What it is NOT: an IRB-permission book (rules 4.4-4.6, rows 0373 / 0374 are
not implemented), a CIU book, or a CRR book (no transitional exists there).
Registered under Basel 3.1 only.

References:
- PS1/26 Credit Risk: General Provisions (CRR) Part rules 4.1-4.3
- PS1/26 Art. 133(3)-(6); Glossary "higher risk equity exposure"
- IMPLEMENTATION_PLAN.md P1.207 / P1.393: the weight-chain legs
- PS1/26 Annex II, OF 07.00 rows 0240-0280 and 0371-0374 (pp.95-98), ¶55A-55D (p.79)
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import EQUITY_EXPOSURE_SCHEMA
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALUE_DATE = date(2024, 12, 31)
_MATURITY = date(2031, 12, 31)  # beyond the 2027-06-01 reporting date

CP_EQUITY = "ETR-CP-EQUITY"
CP_CORP = "ETR-CP-CORP"

#: Moves: Art. 133(3) 250% -> rule 4.2(1) 160%.
EQ_LISTED = "ETR-EQ-LISTED"
#: Moves: Art. 133(4) 400% (Glossary: unlisted, business under five years) -> rule 4.3(1) 220%.
EQ_YOUNG = "ETR-EQ-YOUNG"
#: Stays: Art. 133(5) 150%, not an equity exposure.
EQ_SUB_DEBT = "ETR-EQ-SUB-DEBT"
#: Stays: Art. 133(6)(c), an Own Funds Art. 48(4) holding at 250%.
EQ_SIGNIFICANT = "ETR-EQ-SIGNIFICANT"
#: Stays higher risk: the speculative flag supplies the unstated business age -> rule 4.3.
EQ_FLAGGED = "ETR-EQ-FLAGGED"
#: P1.207: the flag cannot contradict a listed type -> Art. 133(3), rule 4.2.
EQ_FLAGGED_LISTED = "ETR-EQ-FLAGGED-LISTED"
#: P1.207: the flag cannot contradict a ten-year business age -> Art. 133(3), rule 4.2.
EQ_FLAGGED_AGED = "ETR-EQ-FLAGGED-AGED"
#: P1.393(c): unlisted government-supported, business 2y -> Art. 133(4), rule 4.3.
EQ_GOV_YOUNG = "ETR-EQ-GOV-YOUNG"
#: P1.393(b): higher risk AND Art. 133(6)(c) -> 250% on every date, no transitional.
EQ_SIG_YOUNG = "ETR-EQ-SIG-YOUNG"
#: The non-equity anchor on the Total sheet.
LN_ANCHOR = "ETR-LN-ANCHOR"

#: Every equity-table reference, for adequacy assertions.
ALL_EQUITY_REFERENCES: tuple[str, ...] = (
    EQ_LISTED,
    EQ_YOUNG,
    EQ_SUB_DEBT,
    EQ_SIGNIFICANT,
    EQ_FLAGGED,
    EQ_FLAGGED_LISTED,
    EQ_FLAGGED_AGED,
    EQ_GOV_YOUNG,
    EQ_SIG_YOUNG,
)

#: The references whose weight the transitional sets, by rule.
RULE_4_2_REFERENCES: tuple[str, ...] = (EQ_LISTED, EQ_FLAGGED_LISTED, EQ_FLAGGED_AGED)
RULE_4_3_REFERENCES: tuple[str, ...] = (EQ_YOUNG, EQ_FLAGGED, EQ_GOV_YOUNG)
TRANSITIONAL_REFERENCES: tuple[str, ...] = RULE_4_2_REFERENCES + RULE_4_3_REFERENCES

EXPOSURE_LISTED: float = 1_000_000.0
EXPOSURE_YOUNG: float = 500_000.0
EXPOSURE_SUB_DEBT: float = 200_000.0
EXPOSURE_SIGNIFICANT: float = 300_000.0
EXPOSURE_FLAGGED: float = 100_000.0
EXPOSURE_FLAGGED_LISTED: float = 400_000.0
EXPOSURE_FLAGGED_AGED: float = 600_000.0
EXPOSURE_GOV_YOUNG: float = 250_000.0
EXPOSURE_SIG_YOUNG: float = 150_000.0
DRAWN_ANCHOR: float = 2_000_000.0

#: Exposure value of each equity-table reference.
EQUITY_EXPOSURES: dict[str, float] = {
    EQ_LISTED: EXPOSURE_LISTED,
    EQ_YOUNG: EXPOSURE_YOUNG,
    EQ_SUB_DEBT: EXPOSURE_SUB_DEBT,
    EQ_SIGNIFICANT: EXPOSURE_SIGNIFICANT,
    EQ_FLAGGED: EXPOSURE_FLAGGED,
    EQ_FLAGGED_LISTED: EXPOSURE_FLAGGED_LISTED,
    EQ_FLAGGED_AGED: EXPOSURE_FLAGGED_AGED,
    EQ_GOV_YOUNG: EXPOSURE_GOV_YOUNG,
    EQ_SIG_YOUNG: EXPOSURE_SIG_YOUNG,
}


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_equity_transitional_bundle() -> RawDataBundle:
    """Assemble the standardised-firm equity book as a sealed ``RawDataBundle``.

    Run it under ``CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 1),
    permission_mode=PermissionMode.STANDARDISED)``: no model permission is
    supplied, so the firm had no IRB permission on 31 December 2026 and rule 4.1
    applies rules 4.2 / 4.3 to it.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        equity_exposures=_equity_exposures(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """One equity issuer and one unrated large corporate borrower."""
    return pl.DataFrame(
        [
            {
                "counterparty_reference": CP_EQUITY,
                "counterparty_name": CP_EQUITY,
                "entity_type": "corporate",
                "country_code": "GB",
                "annual_revenue": 200_000_000.0,
                "default_status": False,
            },
            {
                "counterparty_reference": CP_CORP,
                "counterparty_name": CP_CORP,
                "entity_type": "corporate",
                "country_code": "GB",
                "annual_revenue": 250_000_000.0,
                "default_status": False,
            },
        ]
    )


def _loans() -> pl.DataFrame:
    """The anchor: one drawn, senior, unrated corporate term loan (100%)."""
    return pl.DataFrame(
        [
            {
                "loan_reference": LN_ANCHOR,
                "counterparty_reference": CP_CORP,
                "product_type": "term_loan",
                "drawn_amount": DRAWN_ANCHOR,
                "currency": "GBP",
                "value_date": _VALUE_DATE,
                "maturity_date": _MATURITY,
                "seniority": "senior",
                "is_defaulted": False,
            }
        ]
    )


def _equity_exposures() -> pl.DataFrame:
    """The nine equity-table legs; see the module docstring for what each is for.

    Carrying value = fair value = exposure value: an equity holding is wholly on
    balance sheet and takes no conversion factor.
    """
    specs: tuple[tuple[str, float, dict[str, object]], ...] = (
        (EQ_LISTED, EXPOSURE_LISTED, {"equity_type": "listed", "is_exchange_traded": True}),
        (EQ_YOUNG, EXPOSURE_YOUNG, {"equity_type": "unlisted", "business_age_years": 2.0}),
        (EQ_SUB_DEBT, EXPOSURE_SUB_DEBT, {"equity_type": "subordinated_debt"}),
        (
            EQ_SIGNIFICANT,
            EXPOSURE_SIGNIFICANT,
            {
                "equity_type": "listed",
                "is_exchange_traded": True,
                "is_significant_investment": True,
            },
        ),
        (EQ_FLAGGED, EXPOSURE_FLAGGED, {"equity_type": "other", "is_speculative": True}),
        (
            EQ_FLAGGED_LISTED,
            EXPOSURE_FLAGGED_LISTED,
            {"equity_type": "listed", "is_speculative": True},
        ),
        (
            EQ_FLAGGED_AGED,
            EXPOSURE_FLAGGED_AGED,
            {"equity_type": "other", "is_speculative": True, "business_age_years": 10.0},
        ),
        (
            EQ_GOV_YOUNG,
            EXPOSURE_GOV_YOUNG,
            {
                "equity_type": "government_supported",
                "is_government_supported": True,
                "business_age_years": 2.0,
            },
        ),
        (
            EQ_SIG_YOUNG,
            EXPOSURE_SIG_YOUNG,
            {
                "equity_type": "unlisted",
                "business_age_years": 2.0,
                "is_significant_investment": True,
            },
        ),
    )
    return pl.DataFrame(
        [
            {
                "exposure_reference": reference,
                "counterparty_reference": CP_EQUITY,
                "currency": "GBP",
                "carrying_value": exposure,
                "fair_value": exposure,
                **attributes,
            }
            for reference, exposure, attributes in specs
        ],
        schema_overrides=dtypes_of(EQUITY_EXPOSURE_SCHEMA),
    )
