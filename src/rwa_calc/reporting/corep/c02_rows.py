"""
C 02.00 / OF 02.00 — the published rows, and where each figure is reported.

Pipeline position:
    here (row codes, labels, the cells each row has)
        -> corep/templates.py (the ``RowSection`` layout objects)
        -> corep/c02.py (what each figure counts) -> reporting/tieouts.py

Key responsibilities:
- Hold the ONE table that says where each figure of the own-funds-requirements
  template is reported under each regime (``Slot``): a figure is named once,
  for what it means, and carries the row code CRR gives it and the row code
  Basel 3.1 gives it. ``None`` is a statement, not a gap — that regime's
  template has no such row.
- Hold both published layouts row by row, with the publisher's own labels and,
  for Basel 3.1, the columns each row has a cell in.

Why the table exists. The two templates re-use row codes for different things
and until this module the generator addressed rows by code: its "8% own funds
requirement" was written to row 0040, which both templates define as the
credit-risk RWEA; its approach totals sat at 0220 / 0240 / 0300 against the
published 0240 / 0250 / 0310; under CRR supervisory slotting was written to
row 0410, "Retail - Other non-SME". A figure in a real cell that means
something else is worse than a figure with no cell, because every published
rule over that cell then evaluates the wrong number without complaint.

Sources, in the order they are trusted:
- Basel 3.1 — the Bank of England PRA001 taxonomy v4.1.1, table
  ``OF02.00.01.01`` (rows, labels and the cells each row has), and PS1/26
  Annex II §1.3. ``tests/contracts/test_of02_published_cells.py`` holds
  ``B31_LAYOUT`` to the taxonomy exactly.
- CRR — the PRA's own rendering of the template being replaced, sheet
  "C 02.00 - OWN FUNDS REQUIREMENTS (CA2)" of the PS1/26 Annex I OF 02.00
  workbook (codes and labels), and the EBA validation rules, which state its
  structure: ``v0204_m`` (0010), ``v0205_m`` (0040 = 0050 + 0240 + 0460 +
  0470), ``v0207_m`` (0060), ``v0210_m`` (0250), ``v0211_m`` (0310) and the
  ``v4245_i``-``v4260_i`` ties of rows 0260-0420 to C 08.01 and C 10.01.

Rows this calculator computes nothing for are still laid out where they are a
term of a published total (the other risk types of row 0010; rows 0450 / 0460 /
0470 of row 0040) and stay empty — empty is not the same claim as zero. Their
own sub-rows, the investment-firm rows 0020 / 0030 and the CRR "of which:
stricter prudential requirements" rows 0051 / 0241 / 0242 are not laid out.

References:
- CRR Art. 92(3); Regulation (EU) 2021/451 Annex I/II (C 02.00)
- PRA PS1/26 Art. 92(2A), Art. 147A; Annex I / Annex II §1.3 (OF 02.00)
- Bank of England Banking Taxonomy v4.1.1, module PRA001
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# =============================================================================
# Constants
# =============================================================================

FRAMEWORK_BASEL_3_1: Final = "BASEL_3_1"

#: The amount column of both templates ("All approaches" under Basel 3.1).
COL_ALL_APPROACHES: Final = "0010"
#: Basel 3.1: "Standardised approaches only (Output Floor)".
COL_STANDARDISED: Final = "0020"
#: Basel 3.1: "Output Floor".
COL_OUTPUT_FLOOR: Final = "0030"

# The column sets a Basel 3.1 row can have a cell in (taxonomy OF02.00.01.01).
_AMOUNT: Final = (COL_ALL_APPROACHES,)
_AMOUNT_AND_STANDARDISED: Final = (COL_ALL_APPROACHES, COL_STANDARDISED)
_AMOUNT_AND_FLOOR: Final = (COL_ALL_APPROACHES, COL_OUTPUT_FLOOR)
_FLOOR: Final = (COL_OUTPUT_FLOOR,)


# =============================================================================
# The slot table — one figure, its row under each regime
# =============================================================================


@dataclass(frozen=True)
class Slot:
    """One figure of the template and the row each regime reports it in.

    Attributes:
        name: What the figure is, for a log line or a test failure.
        crr: Its C 02.00 row code, or ``None`` where C 02.00 has no such row.
        b31: Its OF 02.00 row code, or ``None`` where OF 02.00 has no such row.
    """

    name: str
    crr: str | None
    b31: str | None

    def ref(self, framework: str) -> str | None:
        """The row code under ``framework``; ``None`` if its template has no such row."""
        return self.b31 if framework == FRAMEWORK_BASEL_3_1 else self.crr


# --- Totals ------------------------------------------------------------------
TOTAL: Final = Slot("total risk exposure amount", crr="0010", b31="0010")
CREDIT_RISK: Final = Slot("credit, counterparty credit and dilution risk", crr="0040", b31="0040")

# --- Output floor (PS1/26 Art. 92(2A); OF 02.00 only) ------------------------
FLOOR_ACTIVATED: Final = Slot("output floor activated", crr=None, b31="0034")
FLOOR_MULTIPLIER: Final = Slot("output floor multiplier", crr=None, b31="0035")
FLOOR_ADJUSTMENT: Final = Slot("output floor adjustment (OF-ADJ)", crr=None, b31="0036")

# --- Standardised approach ---------------------------------------------------
# Rows 0050 and 0060 are one figure: "SA" has the single component "SA exposure
# classes excluding securitisation positions" now that securitisation is row
# 0470, and the Basel 3.1 taxonomy makes the two cells ONE data point. The
# Art. 112(1) class rows 0070-0211 carry the same codes in both templates and
# are routed by ``templates.C02_00_SA_CLASS_MAP``.
SA: Final = Slot("standardised approach", crr="0050", b31="0050")
SA_CLASSES: Final = Slot("SA exposure classes excl. securitisation", crr="0060", b31="0060")
SA_SPECIALISED_LENDING: Final = Slot("SA of which: specialised lending", crr=None, b31="0131")
# Art. 112(1)(n), a class PS1/26 does not have. This calculator classifies no
# exposure to it (``templates.C02_00_SA_CLASS_MAP`` has no key for the row), so
# the CRR row reports zero and is a term of ``v0207_m`` like any other class row.
SA_SHORT_TERM_ASSESSMENT: Final = Slot("SA short-term credit assessment", crr="0190", b31=None)

# --- IRB approach ------------------------------------------------------------
IRB: Final = Slot("IRB approach", crr="0240", b31="0240")

# Foundation IRB. PS1/26 Art. 147A withdraws the IRB approach for sovereigns and
# adds the "financial and large corporates" sub-class, which CRR Art. 147(2)(c)
# does not have.
FIRB: Final = Slot("F-IRB", crr="0250", b31="0250")
FIRB_CENTRAL_GOVERNMENTS: Final = Slot("F-IRB central governments", crr="0260", b31=None)
FIRB_INSTITUTIONS: Final = Slot("F-IRB institutions", crr="0270", b31="0271")
FIRB_CORPORATES_SME: Final = Slot("F-IRB corporates SME", crr="0280", b31="0296")
FIRB_SPECIALISED_LENDING: Final = Slot("F-IRB specialised lending", crr="0290", b31="0290")
FIRB_CORPORATES_OTHER: Final = Slot("F-IRB corporates other", crr="0300", b31="0297")
FIRB_FINANCIAL_LARGE_CORPORATES: Final = Slot(
    "F-IRB financial and large corporates", crr=None, b31="0295"
)

# Advanced IRB. Art. 147A also withdraws A-IRB for institutions, and PS1/26
# splits retail real estate by property type where CRR splits it by SME only.
AIRB: Final = Slot("A-IRB", crr="0310", b31="0310")
AIRB_CENTRAL_GOVERNMENTS: Final = Slot("A-IRB central governments", crr="0320", b31=None)
AIRB_INSTITUTIONS: Final = Slot("A-IRB institutions", crr="0330", b31=None)
AIRB_CORPORATES_SME: Final = Slot("A-IRB corporates SME", crr="0340", b31="0355")
AIRB_SPECIALISED_LENDING: Final = Slot("A-IRB specialised lending", crr="0350", b31="0350")
AIRB_CORPORATES_OTHER: Final = Slot("A-IRB corporates other", crr="0360", b31="0356")
AIRB_RETAIL_REAL_ESTATE_SME: Final = Slot("A-IRB retail real estate SME", crr="0370", b31=None)
AIRB_RETAIL_REAL_ESTATE_NON_SME: Final = Slot(
    "A-IRB retail real estate non-SME", crr="0380", b31=None
)
AIRB_RETAIL_RESIDENTIAL_SME: Final = Slot("A-IRB retail residential SME", crr=None, b31="0382")
AIRB_RETAIL_RESIDENTIAL_NON_SME: Final = Slot(
    "A-IRB retail residential non-SME", crr=None, b31="0383"
)
AIRB_RETAIL_COMMERCIAL_SME: Final = Slot("A-IRB retail commercial SME", crr=None, b31="0384")
AIRB_RETAIL_COMMERCIAL_NON_SME: Final = Slot(
    "A-IRB retail commercial non-SME", crr=None, b31="0385"
)
AIRB_RETAIL_QRRE: Final = Slot("A-IRB retail qualifying revolving", crr="0390", b31="0390")
AIRB_RETAIL_OTHER_SME: Final = Slot("A-IRB retail other SME", crr="0400", b31="0400")
AIRB_RETAIL_OTHER_NON_SME: Final = Slot("A-IRB retail other non-SME", crr="0410", b31="0410")

# Supervisory slotting has rows of its own under Basel 3.1 only. C 02.00 reports
# it as specialised lending without own estimates — see ``c02.py``.
SLOTTING: Final = Slot("slotting approach", crr=None, b31="0411")
SLOTTING_PROJECT_FINANCE: Final = Slot("slotting project finance", crr=None, b31="0412")
SLOTTING_OBJECT_FINANCE: Final = Slot("slotting object finance", crr=None, b31="0413")
SLOTTING_COMMODITIES_FINANCE: Final = Slot("slotting commodities finance", crr=None, b31="0414")
SLOTTING_IPRE: Final = Slot("slotting income-producing real estate", crr=None, b31="0415")
SLOTTING_HVCRE: Final = Slot("slotting high-volatility commercial RE", crr=None, b31="0416")

# Art. 155 IRB equity: withdrawn by PS1/26 Art. 147A.
EQUITY_IRB: Final = Slot("equity IRB", crr="0420", b31=None)

#: Each total and the detail slots the published template breaks it into. Used
#: to report RWEA that reaches a total but none of its detail rows — an
#: (approach, class) pair the regime's template has no row for.
BREAKDOWNS: Final[tuple[tuple[Slot, tuple[Slot, ...]], ...]] = (
    (CREDIT_RISK, (SA, IRB)),
    (IRB, (FIRB, AIRB, SLOTTING, EQUITY_IRB)),
    (
        FIRB,
        (
            FIRB_CENTRAL_GOVERNMENTS,
            FIRB_INSTITUTIONS,
            FIRB_CORPORATES_SME,
            FIRB_SPECIALISED_LENDING,
            FIRB_CORPORATES_OTHER,
            FIRB_FINANCIAL_LARGE_CORPORATES,
        ),
    ),
    (
        AIRB,
        (
            AIRB_CENTRAL_GOVERNMENTS,
            AIRB_INSTITUTIONS,
            AIRB_CORPORATES_SME,
            AIRB_SPECIALISED_LENDING,
            AIRB_CORPORATES_OTHER,
            AIRB_RETAIL_REAL_ESTATE_SME,
            AIRB_RETAIL_REAL_ESTATE_NON_SME,
            AIRB_RETAIL_RESIDENTIAL_SME,
            AIRB_RETAIL_RESIDENTIAL_NON_SME,
            AIRB_RETAIL_COMMERCIAL_SME,
            AIRB_RETAIL_COMMERCIAL_NON_SME,
            AIRB_RETAIL_QRRE,
            AIRB_RETAIL_OTHER_SME,
            AIRB_RETAIL_OTHER_NON_SME,
        ),
    ),
    (
        SLOTTING,
        (
            SLOTTING_PROJECT_FINANCE,
            SLOTTING_OBJECT_FINANCE,
            SLOTTING_COMMODITIES_FINANCE,
            SLOTTING_IPRE,
            SLOTTING_HVCRE,
        ),
    ),
)


# =============================================================================
# The published layouts
# =============================================================================


@dataclass(frozen=True)
class PublishedRow:
    """One row of a published template.

    Attributes:
        ref: The row code.
        label: The publisher's label.
        columns: The columns the row has a cell in. C 02.00 has one column; the
            Basel 3.1 sets are the taxonomy's.
    """

    ref: str
    label: str
    columns: tuple[str, ...] = _AMOUNT


_LABEL_TOTAL: Final = "TOTAL RISK EXPOSURE AMOUNT"
_LABEL_CREDIT_RISK: Final = (
    "RISK WEIGHTED EXPOSURE AMOUNTS FOR CREDIT, COUNTERPARTY CREDIT AND DILUTION RISKS "
    "AND FREE DELIVERIES"
)
_LABEL_SA_CLASSES: Final = "SA exposure classes excluding securitisation positions"
_LABEL_CENTRAL_GOVT_SA: Final = "Central governments or central banks"
_LABEL_REGIONAL_GOVT: Final = "Regional governments or local authorities"
_LABEL_PSE: Final = "Public sector entities"
_LABEL_MDB: Final = "Multilateral Development Banks"
_LABEL_INTL_ORG: Final = "International Organisations"
_LABEL_INSTITUTIONS: Final = "Institutions"
_LABEL_CORPORATES: Final = "Corporates"
_LABEL_RETAIL: Final = "Retail"
_LABEL_DEFAULT: Final = "Exposures in default"
_LABEL_CIU: Final = "Collective investments undertakings (CIU)"
_LABEL_OTHER_ITEMS: Final = "Other items"
_LABEL_IRB: Final = "Internal ratings based Approach (IRB)"
_LABEL_CENTRAL_GOVT_IRB: Final = "Central governments and central banks"
_LABEL_QRRE: Final = "Retail - Qualifying revolving"
_LABEL_RETAIL_OTHER_SME: Final = "Retail - Other SME"
_LABEL_RETAIL_OTHER_NON_SME: Final = "Retail - Other non-SME"
_LABEL_NON_CREDIT_OBLIGATION: Final = "Other non credit-obligation assets"
_LABEL_DEFAULT_FUND: Final = "Risk exposure amount for contributions to the default fund of a CCP"
_LABEL_SECURITISATION: Final = "Securitisation positions"
_LABEL_SETTLEMENT: Final = "TOTAL RISK EXPOSURE AMOUNT FOR SETTLEMENT/DELIVERY"
_LABEL_MARKET: Final = (
    "TOTAL RISK EXPOSURE AMOUNT FOR POSITION, FOREIGN EXCHANGE AND COMMODITIES RISKS"
)
_LABEL_OPERATIONAL: Final = "TOTAL RISK EXPOSURE AMOUNT FOR OPERATIONAL RISK (OpR)"
_LABEL_FIXED_OVERHEADS: Final = "ADDITIONAL RISK EXPOSURE AMOUNT DUE TO FIXED OVERHEADS"
_LABEL_CVA: Final = "TOTAL RISK EXPOSURE AMOUNT FOR CREDIT VALUATION ADJUSTMENT"
_LABEL_LARGE_EXPOSURES: Final = (
    "TOTAL RISK EXPOSURE AMOUNT RELATED TO LARGE EXPOSURES IN THE TRADING BOOK"
)
_LABEL_OTHER_AMOUNTS: Final = "OTHER RISK EXPOSURE AMOUNTS"

_SECTION_OTHER_RISK_TYPES: Final = "Other Risk Types"

type Layout = tuple[tuple[str, tuple[PublishedRow, ...]], ...]

#: C 02.00 (CRR): ``(section name, rows)`` in published order.
CRR_LAYOUT: Final[Layout] = (
    (
        "Total and Credit Risk",
        (
            PublishedRow("0010", _LABEL_TOTAL),
            PublishedRow("0040", _LABEL_CREDIT_RISK),
            PublishedRow("0050", "Standardised approach (SA)"),
            PublishedRow("0060", _LABEL_SA_CLASSES),
            PublishedRow("0070", _LABEL_CENTRAL_GOVT_SA),
            PublishedRow("0080", _LABEL_REGIONAL_GOVT),
            PublishedRow("0090", _LABEL_PSE),
            PublishedRow("0100", _LABEL_MDB),
            PublishedRow("0110", _LABEL_INTL_ORG),
            PublishedRow("0120", _LABEL_INSTITUTIONS),
            PublishedRow("0130", _LABEL_CORPORATES),
            PublishedRow("0140", _LABEL_RETAIL),
            PublishedRow("0150", "Secured by mortgages on immovable property"),
            PublishedRow("0160", _LABEL_DEFAULT),
            PublishedRow("0170", "Items associated with particular high risk"),
            PublishedRow("0180", "Covered bonds"),
            PublishedRow(
                "0190", "Claims on institutions and corporates with a short-term credit assessment"
            ),
            PublishedRow("0200", _LABEL_CIU),
            PublishedRow("0210", "Equity"),
            PublishedRow("0211", _LABEL_OTHER_ITEMS),
        ),
    ),
    (
        "IRB Approach",
        (
            PublishedRow("0240", _LABEL_IRB),
            PublishedRow(
                "0250",
                "IRB approaches when neither own estimates of LGD nor Conversion Factors are used",
            ),
            PublishedRow("0260", _LABEL_CENTRAL_GOVT_IRB),
            PublishedRow("0270", _LABEL_INSTITUTIONS),
            PublishedRow("0280", "Corporates - SME"),
            PublishedRow("0290", "Corporates - Specialised Lending"),
            PublishedRow("0300", "Corporates - Other"),
            PublishedRow(
                "0310",
                "IRB approaches when own estimates of LGD and/or Conversion Factors are used",
            ),
            PublishedRow("0320", _LABEL_CENTRAL_GOVT_IRB),
            PublishedRow("0330", _LABEL_INSTITUTIONS),
            PublishedRow("0340", "Corporates - SME"),
            PublishedRow("0350", "Corporates - Specialised Lending"),
            PublishedRow("0360", "Corporates - Other"),
            PublishedRow("0370", "Retail - Secured by real estate SME"),
            PublishedRow("0380", "Retail - Secured by real estate non-SME"),
            PublishedRow("0390", _LABEL_QRRE),
            PublishedRow("0400", _LABEL_RETAIL_OTHER_SME),
            PublishedRow("0410", _LABEL_RETAIL_OTHER_NON_SME),
            PublishedRow("0420", "Equity IRB"),
            PublishedRow("0450", _LABEL_NON_CREDIT_OBLIGATION),
        ),
    ),
    (
        _SECTION_OTHER_RISK_TYPES,
        (
            PublishedRow("0460", _LABEL_DEFAULT_FUND),
            PublishedRow("0470", _LABEL_SECURITISATION),
            PublishedRow("0490", _LABEL_SETTLEMENT),
            PublishedRow("0520", _LABEL_MARKET),
            PublishedRow("0590", _LABEL_OPERATIONAL),
            PublishedRow("0630", _LABEL_FIXED_OVERHEADS),
            PublishedRow("0640", _LABEL_CVA),
            PublishedRow("0680", _LABEL_LARGE_EXPOSURES),
            PublishedRow("0690", _LABEL_OTHER_AMOUNTS),
        ),
    ),
)

#: OF 02.00 (Basel 3.1): ``(section name, rows)`` in published order, each row
#: with the columns the taxonomy has a cell in.
B31_LAYOUT: Final[Layout] = (
    (
        "Total and Output Floor",
        (
            PublishedRow("0010", _LABEL_TOTAL, _AMOUNT_AND_FLOOR),
            PublishedRow("0034", "Output floor activated", _FLOOR),
            PublishedRow("0035", "Output floor multiplier", _FLOOR),
            PublishedRow("0036", "Output floor adjustment (OF-ADJ)", _FLOOR),
        ),
    ),
    (
        "Credit Risk — SA",
        (
            PublishedRow("0040", _LABEL_CREDIT_RISK, _AMOUNT_AND_STANDARDISED),
            PublishedRow("0050", "Standardised Approach (SA)"),
            PublishedRow("0060", _LABEL_SA_CLASSES),
            PublishedRow("0070", _LABEL_CENTRAL_GOVT_SA),
            PublishedRow("0080", _LABEL_REGIONAL_GOVT),
            PublishedRow("0090", _LABEL_PSE),
            PublishedRow("0100", _LABEL_MDB),
            PublishedRow("0110", _LABEL_INTL_ORG),
            PublishedRow("0120", _LABEL_INSTITUTIONS),
            PublishedRow("0130", _LABEL_CORPORATES),
            PublishedRow("0131", "of which: specialised lending"),
            PublishedRow("0140", _LABEL_RETAIL),
            PublishedRow("0150", "Real estate exposures"),
            PublishedRow("0160", _LABEL_DEFAULT),
            PublishedRow("0170", "Exposures associated with particularly high risk"),
            PublishedRow("0180", "Eligible covered bonds"),
            PublishedRow("0200", _LABEL_CIU),
            PublishedRow("0210", "Subordinated debt, equity and other own funds instruments"),
            PublishedRow("0211", _LABEL_OTHER_ITEMS),
        ),
    ),
    (
        "Credit Risk — F-IRB",
        (
            PublishedRow("0240", _LABEL_IRB, _AMOUNT_AND_STANDARDISED),
            PublishedRow(
                "0250", "Exposures subject to the FIRB approach", _AMOUNT_AND_STANDARDISED
            ),
            PublishedRow("0271", _LABEL_INSTITUTIONS, _AMOUNT_AND_STANDARDISED),
            PublishedRow(
                "0290", "Corporates - Specialised lending exposures", _AMOUNT_AND_STANDARDISED
            ),
            PublishedRow(
                "0295",
                "Corporates - Financial corporates and large corporates",
                _AMOUNT_AND_STANDARDISED,
            ),
            PublishedRow(
                "0296", "Corporates - Other general corporates SME", _AMOUNT_AND_STANDARDISED
            ),
            PublishedRow(
                "0297", "Corporates - Other general corporates non-SME", _AMOUNT_AND_STANDARDISED
            ),
        ),
    ),
    (
        "Credit Risk — A-IRB",
        (
            PublishedRow(
                "0310", "Exposures subject to the AIRB approach", _AMOUNT_AND_STANDARDISED
            ),
            PublishedRow(
                "0350", "Corporates - Specialised lending exposures", _AMOUNT_AND_STANDARDISED
            ),
            PublishedRow(
                "0355", "Corporates - Other general corporates SME", _AMOUNT_AND_STANDARDISED
            ),
            PublishedRow(
                "0356", "Corporates - Other general corporates non-SME", _AMOUNT_AND_STANDARDISED
            ),
            PublishedRow(
                "0382",
                "Retail - Secured by residential immovable property SME",
                _AMOUNT_AND_STANDARDISED,
            ),
            PublishedRow(
                "0383",
                "Retail - Secured by residential immovable property non-SME",
                _AMOUNT_AND_STANDARDISED,
            ),
            PublishedRow(
                "0384",
                "Retail - Secured by commercial immovable property SME",
                _AMOUNT_AND_STANDARDISED,
            ),
            PublishedRow(
                "0385",
                "Retail - Secured by commercial immovable property non-SME",
                _AMOUNT_AND_STANDARDISED,
            ),
            PublishedRow("0390", _LABEL_QRRE, _AMOUNT_AND_STANDARDISED),
            PublishedRow("0400", _LABEL_RETAIL_OTHER_SME, _AMOUNT_AND_STANDARDISED),
            PublishedRow("0410", _LABEL_RETAIL_OTHER_NON_SME, _AMOUNT_AND_STANDARDISED),
        ),
    ),
    (
        "Credit Risk — Slotting and Other IRB",
        (
            PublishedRow(
                "0411", "Exposures subject to the slotting approach", _AMOUNT_AND_STANDARDISED
            ),
            PublishedRow("0412", "Project finance exposures", _AMOUNT_AND_STANDARDISED),
            PublishedRow("0413", "Object finance exposures", _AMOUNT_AND_STANDARDISED),
            PublishedRow("0414", "Commodities finance exposures", _AMOUNT_AND_STANDARDISED),
            PublishedRow(
                "0415", "Income Producing Real Estate (IPRE) exposures", _AMOUNT_AND_STANDARDISED
            ),
            PublishedRow(
                "0416",
                "High Volatility Commercial Real Estate (HVCRE) exposures",
                _AMOUNT_AND_STANDARDISED,
            ),
            PublishedRow("0450", _LABEL_NON_CREDIT_OBLIGATION, _AMOUNT_AND_STANDARDISED),
        ),
    ),
    (
        _SECTION_OTHER_RISK_TYPES,
        (
            PublishedRow("0460", _LABEL_DEFAULT_FUND, _AMOUNT_AND_STANDARDISED),
            PublishedRow("0470", _LABEL_SECURITISATION, _AMOUNT_AND_STANDARDISED),
            PublishedRow("0490", _LABEL_SETTLEMENT),
            PublishedRow("0520", _LABEL_MARKET, _AMOUNT_AND_STANDARDISED),
            PublishedRow(
                "5898",
                "TOTAL RISK EXPOSURE AMOUNT FOR CAPITAL CHARGE DUE TO SWITCHING POSITIONS "
                "BETWEEN TRADING AND NON-TRADING BOOK",
            ),
            PublishedRow("0590", _LABEL_OPERATIONAL),
            PublishedRow("0630", _LABEL_FIXED_OVERHEADS),
            PublishedRow("0640", _LABEL_CVA, _AMOUNT_AND_STANDARDISED),
            PublishedRow("0680", _LABEL_LARGE_EXPOSURES, _AMOUNT_AND_STANDARDISED),
            PublishedRow("0690", _LABEL_OTHER_AMOUNTS, _AMOUNT_AND_STANDARDISED),
        ),
    ),
)


# =============================================================================
# Public accessors
# =============================================================================


def get_c02_00_layout(framework: str = "CRR") -> Layout:
    """The published layout for ``framework``: ``(section name, rows)`` in order."""
    return B31_LAYOUT if framework == FRAMEWORK_BASEL_3_1 else CRR_LAYOUT


def get_c02_00_cells(framework: str = "CRR") -> dict[str, tuple[str, ...]]:
    """Row code -> the columns that row has a cell in, for ``framework``."""
    return {row.ref: row.columns for _, rows in get_c02_00_layout(framework) for row in rows}
