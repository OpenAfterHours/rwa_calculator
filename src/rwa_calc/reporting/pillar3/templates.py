"""
Pillar III Disclosure Template Definitions.

Template structure constants for 13 credit risk disclosure templates under
CRR Part 8 / Disclosure (CRR) Part. CRR templates use UK prefix;
Basel 3.1 templates use UKB prefix.

Templates:
    OV1    Overview of risk-weighted exposure amounts (Art. 438(d))
    CR4    SA exposure and CRM effects (Art. 444(e), 453(g-i))
    CR5    SA risk weight allocation (Art. 444(e))
    CR6    IRB exposures by exposure class and PD range (Art. 452(g))
    CR6-A  Scope of IRB and SA use (Art. 452(b))
    CR7    Credit derivatives effect on RWEA (Art. 453(j))
    CR7-A  Extent of CRM techniques for IRB (Art. 453(g))
    CR8    RWEA flow statements for IRB (Art. 438(h))
    CR9    IRB PD back-testing per exposure class (Art. 452(h)) — Basel 3.1 only
    CR9.1  IRB PD back-testing for ECAI mapping (Art. 180(1)(f)) — Basel 3.1 only
    CR10   Slotting approach exposures (Art. 438(e))
    CMS1   Output floor comparison by risk type (Art. 456(1)(a)) — Basel 3.1 only
    CMS2   Output floor comparison by asset class (Art. 456(1)(b)) — Basel 3.1 only

References:
    CRR Part 8 (Art. 438, 444, 452, 453)
    PRA PS1/26 Disclosure (CRR) Part, Art. 456, Art. 2a
    PRA PS1/26 Annex XXII (CR9/CR9.1 back-testing instructions)
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Structural dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class P3Column:
    """A Pillar III template column definition."""

    ref: str
    name: str
    group: str = ""


@dataclass(frozen=True)
class P3Row:
    """A Pillar III template row definition."""

    ref: str
    name: str
    exposure_classes: tuple[str, ...] = ()
    is_total: bool = False


# ---------------------------------------------------------------------------
# Letter-ref helper (used for CR5 risk-weight bucket columns)
# ---------------------------------------------------------------------------


def _letter_ref(i: int) -> str:
    """Convert 0-based index to letter ref: 0->a, 25->z, 26->aa, 27->ab."""
    if i < 26:
        return chr(ord("a") + i)
    return "a" + chr(ord("a") + i - 26)


# ---------------------------------------------------------------------------
# SA exposure class -> pipeline value mapping (used by CR4, CR5)
# ---------------------------------------------------------------------------

SA_DISCLOSURE_CLASSES: list[tuple[str, str, tuple[str, ...]]] = [
    ("1", "Central governments or central banks", ("central_govt_central_bank",)),
    ("2", "Regional governments or local authorities", ("rgla",)),
    ("3", "Public sector entities", ("pse",)),
    ("4", "Multilateral development banks", ("mdb",)),
    ("5", "International organisations", ("international_org",)),
    ("6", "Institutions", ("institution",)),
    ("7", "Corporates", ("corporate", "corporate_sme")),
    ("8", "Retail", ("retail_other", "retail_qrre")),
    ("9", "Secured by mortgages on immovable property", ("retail_mortgage",)),
    ("10", "Exposures in default", ("defaulted",)),
    ("11", "Items associated with particularly high risk", ()),
    ("12", "Covered bonds", ("covered_bond",)),
    ("13", "Short-term claims on institutions and corporates", ()),
    ("14", "Collective investment undertakings", ()),
    ("15", "Equity", ("equity",)),
    ("16", "Other items", ("other",)),
]

# IRB exposure class display names (used by CR6, CR6-A, CR7-A)
IRB_EXPOSURE_CLASSES: dict[str, str] = {
    "central_govt_central_bank": "Central governments or central banks",
    "institution": "Institutions",
    "corporate": "Corporates",
    "corporate_sme": "Corporates — SME",
    "specialised_lending": "Specialised lending",
    "retail_mortgage": "Retail — Secured by immovable property",
    "retail_qrre": "Retail — Qualifying revolving",
    "retail_other": "Retail — Other",
}

# ---------------------------------------------------------------------------
# OV1 — Overview of Risk-Weighted Exposure Amounts (Art. 438(d))
# ---------------------------------------------------------------------------

OV1_COLUMNS: list[P3Column] = [
    P3Column("a", "RWEAs (T)"),
    P3Column("b", "RWEAs (T-1)"),
    P3Column("c", "Total own funds requirements"),
]

CRR_OV1_ROWS: list[P3Row] = [
    P3Row("1", "Credit risk (excluding CCR)"),
    P3Row("2", "Of which: standardised approach"),
    P3Row("3", "Of which: foundation IRB approach"),
    P3Row("4", "Of which: slotting approach"),
    P3Row("UK4a", "Of which: equities under simple risk-weighted approach"),
    P3Row("5", "Of which: advanced IRB approach"),
    P3Row("24", "Amounts below deduction thresholds (250% RW)"),
    P3Row("29", "Total", is_total=True),
]

B31_OV1_ROWS: list[P3Row] = [
    P3Row("1", "Credit risk (excluding CCR)"),
    P3Row("2", "Of which: standardised approach"),
    P3Row("3", "Of which: foundation IRB approach"),
    P3Row("4", "Of which: slotting approach"),
    P3Row("5", "Of which: advanced IRB approach"),
    P3Row("11", "Equity positions under IRB Transitional Approach"),
    P3Row("12", "Equity investments in funds — look-through approach"),
    P3Row("13", "Equity investments in funds — mandate-based approach"),
    P3Row("14", "Equity investments in funds — fall-back approach"),
    P3Row("24", "Amounts below deduction thresholds (250% RW)"),
    P3Row("26", "Output floor multiplier"),
    P3Row("27", "Output floor adjustment"),
    P3Row("29", "Total", is_total=True),
]


# ---------------------------------------------------------------------------
# CR4 — SA Exposure and CRM Effects (Art. 444(e), 453(g-i))
# ---------------------------------------------------------------------------

CRR_CR4_COLUMNS: list[P3Column] = [
    P3Column("a", "On-BS exposures before CCF and CRM", "Exposures before CCF and CRM"),
    P3Column("b", "Off-BS exposures before CCF and CRM", "Exposures before CCF and CRM"),
    P3Column("c", "On-BS amount post CCF and post CRM", "Exposures post CCF and CRM"),
    P3Column("d", "Off-BS amount post CCF and post CRM", "Exposures post CCF and CRM"),
    P3Column("e", "RWEAs"),
    P3Column("f", "RWEA density"),
]

B31_CR4_COLUMNS: list[P3Column] = [
    P3Column("a", "On-BS exposures before CF and CRM", "Exposures before CF and CRM"),
    P3Column("b", "Off-BS exposures before CF and CRM", "Exposures before CF and CRM"),
    P3Column("c", "On-BS amount post CF and post CRM", "Exposures post CF and CRM"),
    P3Column("d", "Off-BS amount post CF and post CRM", "Exposures post CF and CRM"),
    P3Column("e", "RWEAs"),
    P3Column("f", "RWEA density"),
]

CRR_CR4_ROWS: list[P3Row] = [
    P3Row(ref, name, classes) for ref, name, classes in SA_DISCLOSURE_CLASSES
] + [P3Row("17", "Total", is_total=True)]

B31_CR4_ROWS: list[P3Row] = []
for _ref, _name, _classes in SA_DISCLOSURE_CLASSES:
    B31_CR4_ROWS.append(P3Row(_ref, _name, _classes))
    # Add Basel 3.1 sub-rows after specific exposure classes
    if _ref == "7":
        B31_CR4_ROWS.append(
            P3Row("7a", "  Of which: specialised lending", ("specialised_lending",))
        )
    elif _ref == "9":
        B31_CR4_ROWS.extend(
            [
                P3Row("9a", "  Residential RE — not income dependent"),
                P3Row("9b", "  Residential RE — income dependent"),
                P3Row("9c", "  Commercial RE — not income dependent"),
                P3Row("9d", "  Commercial RE — income dependent"),
                P3Row("9e", "  Land acquisition, development and construction"),
            ]
        )
B31_CR4_ROWS.append(P3Row("17", "Total", is_total=True))


# ---------------------------------------------------------------------------
# CR5 — SA Risk Weight Allocation (Art. 444(e))
# ---------------------------------------------------------------------------

CRR_CR5_RISK_WEIGHTS: list[tuple[float, str]] = [
    (0.00, "0%"),
    (0.02, "2%"),
    (0.04, "4%"),
    (0.10, "10%"),
    (0.20, "20%"),
    (0.35, "35%"),
    (0.50, "50%"),
    (0.70, "70%"),
    (0.75, "75%"),
    (1.00, "100%"),
    (1.50, "150%"),
    (2.50, "250%"),
    (3.70, "370%"),
    (12.50, "1250%"),
]

B31_CR5_RISK_WEIGHTS: list[tuple[float, str]] = [
    (0.00, "0%"),
    (0.02, "2%"),
    (0.04, "4%"),
    (0.10, "10%"),
    (0.15, "15%"),
    (0.20, "20%"),
    (0.25, "25%"),
    (0.30, "30%"),
    (0.35, "35%"),
    (0.40, "40%"),
    (0.45, "45%"),
    (0.50, "50%"),
    (0.60, "60%"),
    (0.65, "65%"),
    (0.70, "70%"),
    (0.75, "75%"),
    (0.80, "80%"),
    (0.85, "85%"),
    (1.00, "100%"),
    (1.05, "105%"),
    (1.10, "110%"),
    (1.30, "130%"),
    (1.35, "135%"),
    (1.50, "150%"),
    (2.50, "250%"),
    (3.00, "300%"),
    (4.00, "400%"),
    (12.50, "1250%"),
]


def _build_cr5_columns(
    rw_list: list[tuple[float, str]],
    *,
    is_b31: bool,
) -> list[P3Column]:
    """Build CR5 columns from a risk-weight band list."""
    cols: list[P3Column] = []
    for i, (_, label) in enumerate(rw_list):
        cols.append(P3Column(_letter_ref(i), label, "Risk weight"))
    n = len(rw_list)
    cols.append(P3Column(_letter_ref(n), "Other/Deducted", "Risk weight"))
    cols.append(P3Column(_letter_ref(n + 1), "Total"))
    cols.append(P3Column(_letter_ref(n + 2), "Of which: unrated"))
    if is_b31:
        cols.extend(
            [
                P3Column("ba", "On-BS exposure amount", "Exposure breakdown"),
                P3Column("bb", "Off-BS exposure amount", "Exposure breakdown"),
                P3Column("bc", "Weighted average CF", "Exposure breakdown"),
                P3Column("bd", "Total post CF and CRM", "Exposure breakdown"),
            ]
        )
    return cols


CRR_CR5_COLUMNS: list[P3Column] = _build_cr5_columns(CRR_CR5_RISK_WEIGHTS, is_b31=False)
B31_CR5_COLUMNS: list[P3Column] = _build_cr5_columns(B31_CR5_RISK_WEIGHTS, is_b31=True)

# CR5 rows are the same as CR4 rows
CRR_CR5_ROWS: list[P3Row] = CRR_CR4_ROWS
B31_CR5_ROWS: list[P3Row] = B31_CR4_ROWS


# ---------------------------------------------------------------------------
# CR6 — IRB Exposures by Exposure Class and PD Range (Art. 452(g))
# ---------------------------------------------------------------------------

CRR_CR6_COLUMNS: list[P3Column] = [
    P3Column("a", "PD range"),
    P3Column("b", "On-BS exposures"),
    P3Column("c", "Off-BS exposures pre-CCF"),
    P3Column("d", "Exposure-weighted average CCF"),
    P3Column("e", "Exposure value post CCF and CRM"),
    P3Column("f", "Exposure-weighted average PD (%)"),
    P3Column("g", "Number of obligors"),
    P3Column("h", "Exposure-weighted average LGD (%)"),
    P3Column("i", "Exposure-weighted average maturity (years)"),
    P3Column("j", "RWEAs"),
    P3Column("k", "RWEA density"),
    P3Column("l", "Expected loss amount"),
    P3Column("m", "Value adjustments and provisions"),
]

B31_CR6_COLUMNS: list[P3Column] = [
    P3Column("a", "PD range"),
    P3Column("b", "On-BS exposures"),
    P3Column("c", "Off-BS exposures pre-CCF"),
    P3Column("d", "Exposure-weighted average CCF"),
    P3Column("e", "Exposure value post CCF and CRM"),
    P3Column("f", "Exposure-weighted average PD (%) — post input floor"),
    P3Column("g", "Number of obligors"),
    P3Column("h", "Exposure-weighted average LGD (%) — including input floors"),
    P3Column("i", "Exposure-weighted average maturity (years)"),
    P3Column("j", "RWEAs"),
    P3Column("k", "RWEA density"),
    P3Column("l", "Expected loss amount"),
    P3Column("m", "Value adjustments and provisions"),
]

# 17 fixed regulatory PD range buckets (same as COREP C 08.03)
CR6_PD_RANGES: list[tuple[float, float, str, str]] = [
    (0.0000, 0.0003, "1", "0.00 to < 0.03%"),
    (0.0003, 0.0005, "2", "0.03 to < 0.05%"),
    (0.0005, 0.0010, "3", "0.05 to < 0.10%"),
    (0.0010, 0.0015, "4", "0.10 to < 0.15%"),
    (0.0015, 0.0020, "5", "0.15 to < 0.20%"),
    (0.0020, 0.0025, "6", "0.20 to < 0.25%"),
    (0.0025, 0.0050, "7", "0.25 to < 0.50%"),
    (0.0050, 0.0075, "8", "0.50 to < 0.75%"),
    (0.0075, 0.0100, "9", "0.75 to < 1.00%"),
    (0.0100, 0.0250, "10", "1.00 to < 2.50%"),
    (0.0250, 0.0500, "11", "2.50 to < 5.00%"),
    (0.0500, 0.1000, "12", "5.00 to < 10.00%"),
    (0.1000, 0.2000, "13", "10.00 to < 20.00%"),
    (0.2000, 0.3000, "14", "20.00 to < 30.00%"),
    (0.3000, 0.5000, "15", "30.00 to < 50.00%"),
    (0.5000, 1.0000, "16", "50.00 to < 100%"),
    (1.0000, float("inf"), "17", "100% (Default)"),
]

# ---------------------------------------------------------------------------
# CR6-A — Scope of IRB and SA Use (Art. 452(b))
# ---------------------------------------------------------------------------

CR6A_COLUMNS: list[P3Column] = [
    P3Column("a", "Exposure value for IRB exposures"),
    P3Column("b", "Total exposure value"),
    P3Column("c", "% subject to permanent partial use of SA"),
    P3Column("d", "% subject to IRB approach"),
    P3Column("e", "% subject to roll-out plan"),
]

CRR_CR6A_ROWS: list[P3Row] = [
    P3Row("1", "Central governments or central banks", ("central_govt_central_bank",)),
    P3Row("2", "Institutions", ("institution",)),
    P3Row("3", "Corporates", ("corporate", "corporate_sme", "specialised_lending")),
    P3Row("4", "Retail — Secured by immovable property", ("retail_mortgage",)),
    P3Row("5", "Retail — Qualifying revolving", ("retail_qrre",)),
    P3Row("6", "Retail — Other", ("retail_other",)),
    P3Row("7", "Equity", ("equity",)),
    P3Row("8", "Total", is_total=True),
]

B31_CR6A_ROWS: list[P3Row] = [
    P3Row("1", "Central governments or central banks", ("central_govt_central_bank",)),
    P3Row("2", "Institutions", ("institution",)),
    P3Row("3", "Corporates", ("corporate", "corporate_sme", "specialised_lending")),
    P3Row("4", "Retail — Secured by immovable property", ("retail_mortgage",)),
    P3Row("5", "Retail — Qualifying revolving", ("retail_qrre",)),
    P3Row("6", "Retail — Other", ("retail_other",)),
    P3Row("7", "Total", is_total=True),
]

# ---------------------------------------------------------------------------
# CR7 — Credit Derivatives Effect on RWEA (Art. 453(j))
# ---------------------------------------------------------------------------

CR7_COLUMNS: list[P3Column] = [
    P3Column("a", "Pre-credit derivatives RWEA"),
    P3Column("b", "Actual/post-credit derivatives RWEA"),
]

CRR_CR7_ROWS: list[P3Row] = [
    P3Row("1", "F-IRB subtotal"),
    P3Row("2", "  Central governments and central banks"),
    P3Row("3", "  Institutions"),
    P3Row("4", "  Corporates — SME"),
    P3Row("5", "  Corporates — Other"),
    P3Row("6", "A-IRB subtotal"),
    P3Row("7", "  Corporates"),
    P3Row("8", "  Retail — Secured by immovable property"),
    P3Row("9", "  Retail — Other"),
    P3Row("10", "Total", is_total=True),
]

B31_CR7_ROWS: list[P3Row] = [
    P3Row("1", "F-IRB subtotal"),
    P3Row("2", "  Institutions"),
    P3Row("3", "  Corporates"),
    P3Row("4", "A-IRB subtotal"),
    P3Row("5", "  Corporates"),
    P3Row("6", "  Retail"),
    P3Row("7", "Slotting subtotal"),
    P3Row("8", "Total", is_total=True),
]


# ---------------------------------------------------------------------------
# CR7-A — Extent of CRM Techniques for IRB (Art. 453(g))
# ---------------------------------------------------------------------------

CRR_CR7A_COLUMNS: list[P3Column] = [
    P3Column("a", "Total exposures", "Total"),
    P3Column("b", "FCP: Financial collateral (%)", "Funded credit protection"),
    P3Column("c", "FCP: Other eligible collateral (%)", "Funded credit protection"),
    P3Column("d", "FCP: Immovable property (%)", "Funded credit protection"),
    P3Column("e", "FCP: Receivables (%)", "Funded credit protection"),
    P3Column("f", "FCP: Other physical collateral (%)", "Funded credit protection"),
    P3Column("g", "FCP: Other funded CP (%)", "Funded credit protection"),
    P3Column("h", "FCP: Cash on deposit (%)", "Funded credit protection"),
    P3Column("i", "FCP: Life insurance policies (%)", "Funded credit protection"),
    P3Column("j", "FCP: Instruments held by third party (%)", "Funded credit protection"),
    P3Column("k", "UFCP: Guarantees (%)", "Unfunded credit protection"),
    P3Column("l", "UFCP: Credit derivatives (%)", "Unfunded credit protection"),
    P3Column("m", "RWEA post all CRM (obligor class)"),
    P3Column("n", "RWEA with substitution effects"),
]

B31_CR7A_COLUMNS: list[P3Column] = [
    *CRR_CR7A_COLUMNS,
    P3Column("o", "FCP for slotting (%)", "Slotting"),
    P3Column("p", "UFCP for slotting (%)", "Slotting"),
]

# CR7-A rows per approach: F-IRB, A-IRB (separate disclosure tables)
CR7A_FIRB_ROWS: list[P3Row] = [
    P3Row("1", "Central governments or central banks", ("central_govt_central_bank",)),
    P3Row("2", "Institutions", ("institution",)),
    P3Row("3", "Corporates — Specialised lending", ("specialised_lending",)),
    P3Row("4", "Corporates — Other", ("corporate", "corporate_sme")),
    P3Row("5", "Total", is_total=True),
]

CR7A_AIRB_ROWS: list[P3Row] = [
    P3Row("1", "Corporates — Specialised lending", ("specialised_lending",)),
    P3Row("2", "Corporates — Other", ("corporate", "corporate_sme")),
    P3Row("3", "Retail — Secured by immovable property", ("retail_mortgage",)),
    P3Row("4", "Retail — Qualifying revolving", ("retail_qrre",)),
    P3Row("5", "Retail — Other", ("retail_other",)),
    P3Row("6", "Total", is_total=True),
]


# ---------------------------------------------------------------------------
# CR8 — RWEA Flow Statements for IRB (Art. 438(h))
# ---------------------------------------------------------------------------

CR8_COLUMNS: list[P3Column] = [
    P3Column("a", "RWEA"),
]

CR8_ROWS: list[P3Row] = [
    P3Row("1", "RWEA at end of previous period"),
    P3Row("2", "Asset size"),
    P3Row("3", "Asset quality"),
    P3Row("4", "Model updates"),
    P3Row("5", "Methodology and policy"),
    P3Row("6", "Acquisitions and disposals"),
    P3Row("7", "Foreign exchange movements"),
    P3Row("8", "Other"),
    P3Row("9", "RWEA at end of disclosure period"),
]

# ---------------------------------------------------------------------------
# CR10 — Slotting Approach Exposures (Art. 438(e))
# ---------------------------------------------------------------------------

CRR_CR10_COLUMNS: list[P3Column] = [
    P3Column("a", "On-BS exposures"),
    P3Column("b", "Off-BS exposures"),
    P3Column("c", "Risk weight"),
    P3Column("d", "Exposure value"),
    P3Column("e", "RWEA"),
    P3Column("f", "Expected loss amount"),
]

B31_CR10_COLUMNS: list[P3Column] = [
    P3Column("a", "On-BS exposures"),
    P3Column("b", "Off-BS exposures"),
    P3Column("c", "Risk weight"),
    P3Column("d", "Exposure value post CCF and CRM"),
    P3Column("e", "RWEA"),
    P3Column("f", "Expected loss amount"),
]

CRR_CR10_SUBTEMPLATES: dict[str, str] = {
    "project_finance": "CR10.1 — Project finance",
    "ipre": "CR10.2 — Income-producing RE and HVCRE",
    "object_finance": "CR10.3 — Object finance",
    "commodities_finance": "CR10.4 — Commodities finance",
    "equity": "CR10.5 — Equity under simple RW approach",
}

B31_CR10_SUBTEMPLATES: dict[str, str] = {
    "project_finance": "CR10.1 — Project finance",
    "ipre": "CR10.2 — Income-producing real estate",
    "object_finance": "CR10.3 — Object finance",
    "commodities_finance": "CR10.4 — Commodities finance",
    "hvcre": "CR10.5 — High volatility commercial RE",
}

# Slotting rows within each CR10 sub-template (category, pipeline value, risk weight %)
# Risk weights are for non-HVCRE SL types; HVCRE has different weights (handled by generator)
CR10_SLOTTING_ROWS: list[P3Row] = [
    P3Row("1", "Strong"),
    P3Row("2", "Good"),
    P3Row("3", "Satisfactory"),
    P3Row("4", "Weak"),
    P3Row("5", "Default"),
    P3Row("6", "Total", is_total=True),
]

# Pipeline slotting_category values
CR10_CATEGORY_MAP: dict[str, str] = {
    "Strong": "strong",
    "Good": "good",
    "Satisfactory": "satisfactory",
    "Weak": "weak",
    "Default": "default",
}

# Standard slotting risk weights by category (non-HVCRE)
SLOTTING_RISK_WEIGHTS: dict[str, float] = {
    "strong": 0.70,
    "good": 0.90,
    "satisfactory": 1.15,
    "weak": 2.50,
    "default": 0.00,
}

HVCRE_RISK_WEIGHTS: dict[str, float] = {
    "strong": 0.95,
    "good": 1.20,
    "satisfactory": 1.40,
    "weak": 2.50,
    "default": 0.00,
}


# ---------------------------------------------------------------------------
# CR9 — IRB PD Back-Testing per Exposure Class (Art. 452(h))
# Basel 3.1 only (UKB CR9) — no CRR equivalent
#
# Separate templates per FIRB and AIRB approach, with one template per
# exposure class within each. Uses the same 17 fixed PD range buckets as
# CR6. Key distinction from CR6: PD allocation uses PD estimated at the
# beginning of the disclosure period, not the pre-input-floor PD.
# ---------------------------------------------------------------------------

CR9_COLUMNS: list[P3Column] = [
    P3Column("a", "Exposure class"),
    P3Column("b", "PD range"),
    P3Column("c", "Number of obligors at end of previous year"),
    P3Column("d", "Of which: defaulted during the year"),
    P3Column("e", "Observed average default rate (%)"),
    P3Column("f", "Exposure-weighted average PD (%) — post input floor"),
    P3Column("g", "Average PD at disclosure date (%) — post input floor"),
    P3Column("h", "Average historical annual default rate (%)"),
]

CR9_COLUMN_REFS: list[str] = [c.ref for c in CR9_COLUMNS]

# CR9 AIRB exposure class breakdown (Art. 147(2)(c)-(d))
CR9_AIRB_CLASSES: list[tuple[str, str]] = [
    ("corporate", "Corporates"),
    ("specialised_lending", "Corporates — Specialised lending"),
    ("corporate_sme", "Corporates — Other general corporates (SME)"),
    ("retail_mortgage", "Retail — Secured by immovable property"),
    ("retail_qrre", "Retail — Qualifying revolving"),
    ("retail_other", "Retail — Other"),
]

# CR9 FIRB exposure class breakdown (Art. 147(2)(b)-(c))
CR9_FIRB_CLASSES: list[tuple[str, str]] = [
    ("institution", "Institutions"),
    ("corporate", "Corporates"),
    ("specialised_lending", "Corporates — Specialised lending"),
    ("corporate_sme", "Corporates — Other general corporates (SME)"),
]

# Combined display names for Excel sheet naming
CR9_APPROACH_DISPLAY: dict[str, str] = {
    "foundation_irb": "F-IRB",
    "advanced_irb": "A-IRB",
}

# ---------------------------------------------------------------------------
# CR9.1 — IRB PD Back-Testing for ECAI Mapping (Art. 180(1)(f))
# Basel 3.1 only (UKB CR9.1) — no CRR equivalent
#
# Supplementary to CR9 for firms using Art. 180(1)(f) ECAI-based PD
# estimation. Same structure as CR9 but with variable-width PD ranges
# based on the firm's internal grades, plus one column per ECAI showing
# the external rating mapping.
# ---------------------------------------------------------------------------

CR9_1_COLUMNS: list[P3Column] = [
    P3Column("a", "Exposure class"),
    P3Column("b", "PD range (firm-defined)"),
    P3Column("c", "Number of obligors at end of previous year"),
    P3Column("d", "Of which: defaulted during the year"),
    P3Column("e", "Observed average default rate (%)"),
    P3Column("f", "Exposure-weighted average PD (%) — post input floor"),
    P3Column("g", "Average PD at disclosure date (%) — post input floor"),
    P3Column("h", "Average historical annual default rate (%)"),
    # Additional ECAI columns are added dynamically per firm
]

CR9_1_COLUMN_REFS: list[str] = [c.ref for c in CR9_1_COLUMNS]


# ---------------------------------------------------------------------------
# CMS1 — Output Floor Comparison by Risk Type (Art. 456(1)(a))
# Basel 3.1 only (UKB CMS1) — no CRR equivalent
# ---------------------------------------------------------------------------

CMS1_COLUMNS: list[P3Column] = [
    P3Column("a", "RWA for modelled approaches"),
    P3Column("b", "RWA for portfolios where standardised approaches are used"),
    P3Column("c", "Total actual RWA"),
    P3Column("d", "RWA calculated using full standardised approach"),
]

CMS1_ROWS: list[P3Row] = [
    P3Row("0010", "Credit risk (excluding CCR)"),
    P3Row("0020", "Counterparty credit risk"),
    P3Row("0030", "Credit valuation adjustment"),
    P3Row("0040", "Securitisation exposures in the banking book"),
    P3Row("0050", "Market risk"),
    P3Row("0060", "Operational risk"),
    P3Row("0070", "Residual RWA"),
    P3Row("0080", "Total", is_total=True),
]


# ---------------------------------------------------------------------------
# CMS2 — Output Floor Comparison by Asset Class (Art. 456(1)(b))
# Basel 3.1 only (UKB CMS2) — no CRR equivalent
# ---------------------------------------------------------------------------

CMS2_COLUMNS: list[P3Column] = [
    P3Column("a", "RWA for modelled approaches"),
    P3Column("b", "RWA for column (a) re-computed using SA"),
    P3Column("c", "Total actual RWA"),
    P3Column("d", "RWA calculated using full standardised approach"),
]

CMS2_ROWS: list[P3Row] = [
    P3Row("0010", "Sovereign", ("central_govt_central_bank",)),
    P3Row(
        "0011",
        "  Of which: categorised as MDB/PSE in SA",
        ("mdb", "pse"),
    ),
    P3Row("0020", "Institutions", ("institution",)),
    P3Row(
        "0030",
        "Subordinated debt, equity and other own funds",
        ("equity",),
    ),
    P3Row(
        "0040",
        "Corporates",
        ("corporate", "corporate_sme", "specialised_lending"),
    ),
    P3Row("0041", "  Of which are FIRB"),
    P3Row("0042", "  Of which are AIRB"),
    P3Row("0043", "  Of which: specialised lending exposures", ("specialised_lending",)),
    P3Row(
        "0044",
        "  Of which: IPRE and HVCRE exposures",
    ),
    P3Row("0045", "  Of which: purchased receivables"),
    P3Row(
        "0050",
        "Retail",
        ("retail_mortgage", "retail_qrre", "retail_other"),
    ),
    P3Row("0051", "  Of which: qualifying revolving retail", ("retail_qrre",)),
    P3Row("0052", "  Of which: other retail", ("retail_other",)),
    P3Row(
        "0053",
        "  Of which: retail secured by residential immovable property",
        ("retail_mortgage",),
    ),
    P3Row("0054", "  Of which: purchased receivables"),
    P3Row(
        "0060",
        "Others",
        ("other", "rgla", "covered_bond", "defaulted"),
    ),
    P3Row("0070", "Total", is_total=True),
]

# Mapping of CMS2 exposure classes to SA disclosure class pipeline values
# Used to compute column d (full SA RWA) at asset class level
CMS2_SA_CLASS_MAP: dict[str, tuple[str, ...]] = {
    "0010": ("central_govt_central_bank",),
    "0011": ("mdb", "pse"),
    "0020": ("institution",),
    "0030": ("equity",),
    "0040": ("corporate", "corporate_sme", "specialised_lending"),
    "0043": ("specialised_lending",),
    "0050": ("retail_mortgage", "retail_qrre", "retail_other"),
    "0051": ("retail_qrre",),
    "0052": ("retail_other",),
    "0053": ("retail_mortgage",),
    "0060": ("other", "rgla", "covered_bond", "defaulted"),
}


# ---------------------------------------------------------------------------
# Selector functions (framework switching)
# ---------------------------------------------------------------------------


def get_ov1_rows(framework: str) -> list[P3Row]:
    """Return OV1 rows for the given framework."""
    return B31_OV1_ROWS if framework == "BASEL_3_1" else CRR_OV1_ROWS


def get_cr4_columns(framework: str) -> list[P3Column]:
    """Return CR4 columns for the given framework."""
    return B31_CR4_COLUMNS if framework == "BASEL_3_1" else CRR_CR4_COLUMNS


def get_cr4_rows(framework: str) -> list[P3Row]:
    """Return CR4 rows for the given framework."""
    return B31_CR4_ROWS if framework == "BASEL_3_1" else CRR_CR4_ROWS


def get_cr5_columns(framework: str) -> list[P3Column]:
    """Return CR5 columns for the given framework."""
    return B31_CR5_COLUMNS if framework == "BASEL_3_1" else CRR_CR5_COLUMNS


def get_cr5_rows(framework: str) -> list[P3Row]:
    """Return CR5 rows for the given framework."""
    return B31_CR5_ROWS if framework == "BASEL_3_1" else CRR_CR5_ROWS


def get_cr5_risk_weights(framework: str) -> list[tuple[float, str]]:
    """Return risk weight band definitions for CR5."""
    return B31_CR5_RISK_WEIGHTS if framework == "BASEL_3_1" else CRR_CR5_RISK_WEIGHTS


def get_cr6_columns(framework: str) -> list[P3Column]:
    """Return CR6 columns for the given framework."""
    return B31_CR6_COLUMNS if framework == "BASEL_3_1" else CRR_CR6_COLUMNS


def get_cr6a_rows(framework: str) -> list[P3Row]:
    """Return CR6-A rows for the given framework."""
    return B31_CR6A_ROWS if framework == "BASEL_3_1" else CRR_CR6A_ROWS


def get_cr7_rows(framework: str) -> list[P3Row]:
    """Return CR7 rows for the given framework."""
    return B31_CR7_ROWS if framework == "BASEL_3_1" else CRR_CR7_ROWS


def get_cr7a_columns(framework: str) -> list[P3Column]:
    """Return CR7-A columns for the given framework."""
    return B31_CR7A_COLUMNS if framework == "BASEL_3_1" else CRR_CR7A_COLUMNS


def get_cr10_columns(framework: str) -> list[P3Column]:
    """Return CR10 columns for the given framework."""
    return B31_CR10_COLUMNS if framework == "BASEL_3_1" else CRR_CR10_COLUMNS


def get_cr10_subtemplates(framework: str) -> dict[str, str]:
    """Return CR10 sub-template definitions for the given framework."""
    return B31_CR10_SUBTEMPLATES if framework == "BASEL_3_1" else CRR_CR10_SUBTEMPLATES
