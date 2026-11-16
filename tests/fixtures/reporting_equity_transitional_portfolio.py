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

## The five legs — two that move, two that must not, and an anchor

    ref                   | equity_type        | Art. 133 | applied | RWEA      | row  | memo
    ----------------------|--------------------|----------|---------|-----------|------|-----
    ETR-EQ-LISTED         | listed             | 250%     | 160%    | 1,600,000 | 0250 | 0372
    ETR-EQ-YOUNG          | unlisted, age 2y   | 400%     | 220%    | 1,100,000 | 0261 | 0371
    ETR-EQ-SUB-DEBT       | subordinated_debt  | 150%     | 150%    |   300,000 | 0240 | -
    ETR-EQ-SIGNIFICANT    | listed, Art. 48(4) | 250%     | 250%    |   750,000 | 0250 | -
    ETR-LN-ANCHOR         | corporate loan     | 100%     | 100%    | 2,000,000 | 0230 | -

Exposure values 1,000,000 / 500,000 / 200,000 / 300,000 / 2,000,000.

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

Hand calculation, OF 07.00 sheet 0016 (class (p)), cols 0200 / 0220:
row 0010 2,000,000 / 3,750,000; row 0240 200,000 / 300,000; row 0250
1,300,000 / 2,350,000; row 0261 500,000 / 1,100,000; row 0280 null; row 0371
500,000 / 1,100,000; row 0372 1,000,000 / 1,600,000; rows 0373 / 0374 null.

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
#: The non-equity anchor on the Total sheet.
LN_ANCHOR = "ETR-LN-ANCHOR"

#: Every equity-table reference, for adequacy assertions.
ALL_EQUITY_REFERENCES: tuple[str, ...] = (EQ_LISTED, EQ_YOUNG, EQ_SUB_DEBT, EQ_SIGNIFICANT)

#: The two references whose weight the transitional sets.
TRANSITIONAL_REFERENCES: tuple[str, ...] = (EQ_LISTED, EQ_YOUNG)

EXPOSURE_LISTED: float = 1_000_000.0
EXPOSURE_YOUNG: float = 500_000.0
EXPOSURE_SUB_DEBT: float = 200_000.0
EXPOSURE_SIGNIFICANT: float = 300_000.0
DRAWN_ANCHOR: float = 2_000_000.0


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
    """The four equity-table legs; see the module docstring for what each is for.

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
