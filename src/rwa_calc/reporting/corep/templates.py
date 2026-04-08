"""
COREP template structure definitions.

Defines the row/column structure for COREP credit risk templates:
- C 07.00 / OF 07.00: SA credit risk — 24/22 columns, 5 row sections
- C 08.01 / OF 08.01: IRB totals — 35/40+ columns, row sections
- C 08.02 / OF 08.02: IRB PD grade bands for granular reporting
- C 08.03 / OF 08.03: IRB PD ranges — 11 columns, 17 fixed regulatory PD buckets
- OF 02.01: Output floor comparison — 4 columns, 8 risk-type rows (Basel 3.1 only)

Supports both CRR (current) and Basel 3.1 (PRA PS1/26) frameworks.

Why: COREP templates have a fixed regulatory format (EBA DPM taxonomy).
These definitions are the single source of truth for template structure,
used by the generator to produce correctly-formatted output.

References:
- Regulation (EU) 2021/451, Annex I (CRR template layouts)
- Regulation (EU) 2021/451, Annex II (CRR reporting instructions)
- PRA PS1/26, Annex I (Basel 3.1 OF template layouts)
- PRA PS1/26, Annex II (Basel 3.1 OF reporting instructions)
- CRR Art. 112 (SA exposure classes)
- CRR Art. 147 (IRB exposure classes)
"""

from __future__ import annotations

from dataclasses import dataclass, field

# =============================================================================
# COREP ROW / COLUMN / SECTION METADATA
# =============================================================================


@dataclass(frozen=True)
class COREPRow:
    """A row in a COREP template (exposure class or sub-category)."""

    ref: str  # Row reference, e.g. "0010"
    name: str  # Display name, e.g. "Central governments or central banks"
    exposure_class_value: str | None = None  # Maps to ExposureClass.value


@dataclass(frozen=True)
class COREPColumn:
    """A column in a COREP template."""

    ref: str  # Column reference, e.g. "0010" (4-digit COREP refs)
    name: str  # Display name
    group: str = ""  # Logical group (e.g. "Exposure", "CRM Substitution")


@dataclass(frozen=True)
class RowSection:
    """A section of rows within a COREP template.

    Each SA/IRB template submission contains multiple row sections
    (e.g. totals, exposure type breakdown, risk weight breakdown).
    """

    name: str  # Section name, e.g. "Total Exposures"
    rows: list[COREPRow] = field(default_factory=list)


# =============================================================================
# SA EXPOSURE CLASS FILTER — used by generator to filter pipeline data
# =============================================================================

# Mapping: ExposureClass.value -> (row_ref, display_name)
# These are filter values used by the generator to select data for each
# per-exposure-class template submission. They are NOT the row structure
# of the template itself — see SA_ROW_SECTIONS for that.
SA_EXPOSURE_CLASS_ROWS: dict[str, tuple[str, str]] = {
    "central_govt_central_bank": ("0010", "Central governments or central banks"),
    "rgla": ("0020", "Regional governments or local authorities"),
    "pse": ("0030", "Public sector entities"),
    "mdb": ("0040", "Multilateral development banks"),
    "international_org": ("0050", "International organisations"),
    "institution": ("0060", "Institutions"),
    "corporate": ("0070", "Corporates"),
    "corporate_sme": ("0071", "  Of which: SME corporates"),
    "retail_mortgage": ("0080", "Secured by mortgages on immovable property"),
    "retail_other": ("0090", "Retail"),
    "retail_qrre": ("0091", "  Of which: Qualifying revolving"),
    "defaulted": ("0100", "Exposures in default"),
    "covered_bond": ("0105", "Covered bonds"),
    "equity": ("0110", "Equity exposures"),
    "other": ("0120", "Other items"),
}

# IRB exposure class filter values — used by generator for per-class filtering.
# Not the row structure; see IRB_ROW_SECTIONS for that.
IRB_EXPOSURE_CLASS_ROWS: dict[str, tuple[str, str]] = {
    "central_govt_central_bank": ("0010", "Central governments and central banks"),
    "institution": ("0020", "Institutions"),
    "corporate": ("0030", "Corporates - Other"),
    "corporate_sme": ("0040", "Corporates - SME"),
    "specialised_lending": ("0050", "Corporates - Specialised lending"),
    "retail_mortgage": ("0060", "Retail - Secured by immovable property"),
    "retail_qrre": ("0070", "Retail - Qualifying revolving (QRRE)"),
    "retail_other": ("0080", "Retail - Other"),
}


# =============================================================================
# C 07.00 / OF 07.00 — SA COLUMN DEFINITIONS
# =============================================================================

# CRR C 07.00: 24 columns (refs 0010-0240) covering the full SA credit risk
# waterfall from original exposure through CRM to final RWEA.
CRR_C07_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", "Original exposure pre conversion factors", "Exposure"),
    COREPColumn("0030", "(-) Value adjustments and provisions", "Exposure"),
    COREPColumn("0040", "Exposure net of value adjustments and provisions", "Exposure"),
    COREPColumn("0050", "(-) Guarantees", "CRM Substitution: Unfunded"),
    COREPColumn("0060", "(-) Credit derivatives", "CRM Substitution: Unfunded"),
    COREPColumn("0070", "(-) Financial collateral: Simple method", "CRM Substitution: Funded"),
    COREPColumn("0080", "(-) Other funded credit protection", "CRM Substitution: Funded"),
    COREPColumn("0090", "(-) Substitution outflows", "CRM Substitution"),
    COREPColumn("0100", "Substitution inflows (+)", "CRM Substitution"),
    COREPColumn("0110", "Net exposure after CRM substitution effects pre CCFs", "Post-CRM"),
    COREPColumn("0120", "Volatility adjustment to the exposure", "Fin. Collateral Comprehensive"),
    COREPColumn(
        "0130",
        "(-) Financial collateral: adjusted value (Cvam)",
        "Fin. Collateral Comprehensive",
    ),
    COREPColumn(
        "0140",
        "(-) Of which: volatility and maturity adjustments",
        "Fin. Collateral Comprehensive",
    ),
    COREPColumn("0150", "Fully adjusted exposure value (E*)", "Post-CRM"),
    COREPColumn("0160", "Off-BS by CCF: 0%", "CCF Breakdown"),
    COREPColumn("0170", "Off-BS by CCF: 20%", "CCF Breakdown"),
    COREPColumn("0180", "Off-BS by CCF: 50%", "CCF Breakdown"),
    COREPColumn("0190", "Off-BS by CCF: 100%", "CCF Breakdown"),
    COREPColumn("0200", "Exposure value", "Final"),
    COREPColumn("0210", "Of which: arising from CCR", "Final"),
    COREPColumn("0211", "Of which: CCR excl. CCP", "Final"),
    COREPColumn("0215", "RWEA pre supporting factors", "RWEA"),
    COREPColumn("0216", "(-) SME supporting factor adjustment", "RWEA"),
    COREPColumn("0217", "(-) Infrastructure supporting factor adjustment", "RWEA"),
    COREPColumn("0220", "RWEA after supporting factors", "RWEA"),
    COREPColumn("0230", "Of which: with ECAI credit assessment", "RWEA"),
    COREPColumn("0240", "Of which: credit assessment derived from central govt", "RWEA"),
]

# Basel 3.1 OF 07.00: 22 columns — adds 0035, 0171, 0235; removes 0215-0217;
# changes 0160 from 0% CCF to 10% CCF.
B31_C07_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", "Original exposure pre conversion factors", "Exposure"),
    COREPColumn("0030", "(-) Value adjustments and provisions", "Exposure"),
    COREPColumn(
        "0035", "(-) Adjustment due to on-balance sheet netting", "Exposure"
    ),  # New in B3.1
    COREPColumn(
        "0040", "Exposure net of adjustments, provisions, and netting", "Exposure"
    ),  # Changed
    COREPColumn("0050", "(-) Guarantees (adjusted values)", "CRM Substitution: Unfunded"),
    COREPColumn("0060", "(-) Credit derivatives", "CRM Substitution: Unfunded"),
    COREPColumn("0070", "(-) Financial collateral: Simple method", "CRM Substitution: Funded"),
    COREPColumn("0080", "(-) Other funded credit protection", "CRM Substitution: Funded"),
    COREPColumn("0090", "(-) Substitution outflows", "CRM Substitution"),
    COREPColumn("0100", "Substitution inflows (+)", "CRM Substitution"),
    COREPColumn("0110", "Net exposure after CRM substitution effects pre CCFs", "Post-CRM"),
    COREPColumn("0120", "Volatility adjustment to the exposure", "Fin. Collateral Comprehensive"),
    COREPColumn(
        "0130",
        "(-) Financial collateral: adjusted value (Cvam)",
        "Fin. Collateral Comprehensive",
    ),
    COREPColumn(
        "0140",
        "(-) Of which: volatility and maturity adjustments",
        "Fin. Collateral Comprehensive",
    ),
    COREPColumn("0150", "Fully adjusted exposure value (E*)", "Post-CRM"),
    COREPColumn("0160", "Off-BS by CCF: 10%", "CCF Breakdown"),  # Changed: was 0% in CRR
    COREPColumn("0170", "Off-BS by CCF: 20%", "CCF Breakdown"),
    COREPColumn("0171", "Off-BS by CCF: 40%", "CCF Breakdown"),  # New in B3.1
    COREPColumn("0180", "Off-BS by CCF: 50%", "CCF Breakdown"),
    COREPColumn("0190", "Off-BS by CCF: 100%", "CCF Breakdown"),
    COREPColumn("0200", "Exposure value", "Final"),
    COREPColumn("0210", "Of which: arising from CCR", "Final"),
    COREPColumn("0211", "Of which: CCR excl. CCP", "Final"),
    # 0215-0217 removed: supporting factors don't exist under Basel 3.1
    COREPColumn("0220", "Risk-weighted exposure amount", "RWEA"),  # Changed name
    COREPColumn("0230", "Of which: with ECAI credit assessment", "RWEA"),
    COREPColumn("0235", "Of which: without ECAI credit assessment", "RWEA"),  # New in B3.1
    COREPColumn("0240", "Of which: credit assessment derived from central govt", "RWEA"),
]


# =============================================================================
# C 07.00 / OF 07.00 — SA ROW SECTIONS
# =============================================================================

# Each SA template is submitted once per exposure class. Within each submission,
# there are 5 row sections. These define the row structure.

CRR_SA_ROW_SECTIONS: list[RowSection] = [
    RowSection(
        "Total Exposures",
        [
            COREPRow("0010", "TOTAL EXPOSURES"),
            COREPRow("0015", "of which: Defaulted exposures"),
            COREPRow("0020", "of which: SME"),
            COREPRow("0030", "of which: Exposures subject to SME-supporting factor"),
            COREPRow("0035", "of which: Exposures subject to infrastructure supporting factor"),
            COREPRow("0040", "of which: Secured by mortgages on immovable property - Residential"),
            COREPRow("0050", "of which: Exposures under permanent partial use of SA"),
            COREPRow("0060", "of which: Exposures under sequential IRB implementation"),
        ],
    ),
    RowSection(
        "Breakdown by Exposure Types",
        [
            COREPRow("0070", "On balance sheet exposures subject to credit risk"),
            COREPRow("0080", "Off balance sheet exposures subject to credit risk"),
            COREPRow("0090", "SFT netting sets"),
            COREPRow("0100", "  of which: centrally cleared through a QCCP"),
            COREPRow("0110", "Derivatives & Long Settlement Transactions netting sets"),
            COREPRow("0120", "  of which: centrally cleared through a QCCP"),
            COREPRow("0130", "From Contractual Cross Product netting sets"),
        ],
    ),
    RowSection(
        "Breakdown by Risk Weights",
        [
            COREPRow("0140", "0%"),
            COREPRow("0150", "2%"),
            COREPRow("0160", "4%"),
            COREPRow("0170", "10%"),
            COREPRow("0180", "20%"),
            COREPRow("0190", "35%"),
            COREPRow("0200", "50%"),
            COREPRow("0210", "70%"),
            COREPRow("0220", "75%"),
            COREPRow("0230", "100%"),
            COREPRow("0240", "150%"),
            COREPRow("0250", "250%"),
            COREPRow("0260", "370%"),
            COREPRow("0270", "1250%"),
            COREPRow("0280", "Other risk weights"),
        ],
    ),
    RowSection(
        "Breakdown by CIU Approach",
        [
            COREPRow("0281", "Look-through approach"),
            COREPRow("0282", "Mandate-based approach"),
            COREPRow("0283", "Fall-back approach"),
        ],
    ),
    RowSection(
        "Memorandum Items",
        [
            COREPRow("0290", "Exposures secured by mortgages on commercial immovable property"),
            COREPRow("0300", "Exposures in default subject to RW of 100%"),
            COREPRow("0310", "Exposures secured by mortgages on residential immovable property"),
            COREPRow("0320", "Exposures in default subject to RW of 150%"),
        ],
    ),
]

B31_SA_ROW_SECTIONS: list[RowSection] = [
    RowSection(
        "Total Exposures",
        [
            COREPRow("0010", "TOTAL EXPOSURES"),
            COREPRow("0015", "of which: Defaulted exposures"),
            COREPRow("0020", "of which: SME"),
            # 0030 removed: SME supporting factor doesn't exist under Basel 3.1
            # 0035 removed: infrastructure supporting factor doesn't exist under Basel 3.1
            COREPRow("0021", "of which: Specialised lending - Object finance"),
            COREPRow("0022", "of which: Specialised lending - Commodities finance"),
            COREPRow("0023", "of which: Specialised lending - Project finance"),
            COREPRow("0024", "  of which: pre-operational phase"),
            COREPRow("0025", "  of which: operational phase"),
            COREPRow("0026", "  of which: high quality operational phase"),
            COREPRow("0330", "of which: Regulatory residential RE"),
            COREPRow("0331", "  of which: not materially dependent on property cash flows"),
            COREPRow("0332", "  of which: materially dependent on property cash flows"),
            COREPRow("0340", "of which: Regulatory commercial RE"),
            COREPRow("0341", "  of which: not materially dependent (non-SME)"),
            COREPRow("0342", "  of which: materially dependent"),
            COREPRow("0343", "  of which: SME (non-materially dependent)"),
            COREPRow("0344", "  of which: SME (materially dependent)"),
            COREPRow("0350", "of which: Other real estate"),
            COREPRow("0351", "  of which: Residential (not mat. dependent)"),
            COREPRow("0352", "  of which: Residential (mat. dependent)"),
            COREPRow("0353", "  of which: Commercial (not mat. dependent)"),
            COREPRow("0354", "  of which: Commercial (mat. dependent)"),
            COREPRow("0360", "of which: Land ADC exposures"),
            # 0040 removed: replaced by detailed RE breakdown above
            COREPRow("0050", "of which: Exposures under permanent partial use of SA"),
            COREPRow("0060", "of which: Exposures under sequential IRB implementation"),
        ],
    ),
    RowSection(
        "Breakdown by Exposure Types",
        [
            COREPRow("0070", "On balance sheet exposures subject to credit risk"),
            COREPRow("0080", "Off balance sheet exposures subject to credit risk"),
            COREPRow("0090", "SFT netting sets"),
            COREPRow("0100", "  of which: centrally cleared through a QCCP"),
            COREPRow("0110", "Derivatives & Long Settlement Transactions netting sets"),
            COREPRow("0120", "  of which: centrally cleared through a QCCP"),
            COREPRow("0130", "From Contractual Cross Product netting sets"),
        ],
    ),
    RowSection(
        "Breakdown by Risk Weights",
        [
            COREPRow("0140", "0%"),
            COREPRow("0150", "2%"),
            COREPRow("0160", "4%"),
            COREPRow("0170", "10%"),
            COREPRow("0171", "15%"),
            COREPRow("0180", "20%"),
            COREPRow("0181", "25%"),
            COREPRow("0182", "30%"),
            COREPRow("0190", "35%"),
            COREPRow("0191", "40%"),
            COREPRow("0192", "45%"),
            COREPRow("0200", "50%"),
            COREPRow("0201", "60%"),
            COREPRow("0202", "65%"),
            COREPRow("0210", "70%"),
            COREPRow("0220", "75%"),
            COREPRow("0221", "80%"),
            COREPRow("0222", "85%"),
            COREPRow("0230", "100%"),
            COREPRow("0231", "105%"),
            COREPRow("0232", "110%"),
            COREPRow("0233", "130%"),
            COREPRow("0234", "135%"),
            COREPRow("0240", "150%"),
            COREPRow("0250", "250%"),
            COREPRow("0261", "400%"),  # Replaces 370% in CRR
            COREPRow("0270", "1250%"),
            COREPRow("0280", "Other risk weights"),
        ],
    ),
    RowSection(
        "Breakdown by CIU Approach",
        [
            COREPRow("0281", "Look-through approach"),
            COREPRow("0284", "  of which: exposures to relevant CIUs"),
            COREPRow("0282", "Mandate-based approach"),
            COREPRow("0285", "  of which: exposures to relevant CIUs"),
            COREPRow("0283", "Fall-back approach"),
        ],
    ),
    RowSection(
        "Memorandum Items",
        [
            # 0290, 0310 removed: replaced by detailed RE breakdown in Section 1
            COREPRow("0300", "Exposures in default subject to RW of 100%"),
            COREPRow("0320", "Exposures in default subject to RW of 150%"),
            COREPRow("0371", "Equity transitional: SA higher risk"),
            COREPRow("0372", "Equity transitional: SA other equity"),
            COREPRow("0373", "Equity transitional: IRB higher risk"),
            COREPRow("0374", "Equity transitional: IRB other equity"),
            COREPRow("0380", "Retail and RE: subject to currency mismatch multiplier"),
        ],
    ),
]


# =============================================================================
# SA RISK WEIGHT BANDS
# =============================================================================

# CRR: 14 standard risk weight bands + "Other"
# Each tuple: (risk_weight_decimal, display_label)
SA_RISK_WEIGHT_BANDS: list[tuple[float, str]] = [
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

# Basel 3.1: 28 risk weight bands (adds 15 new granular weights, removes 370%)
B31_SA_RISK_WEIGHT_BANDS: list[tuple[float, str]] = [
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
    (4.00, "400%"),
    (12.50, "1250%"),
]


# =============================================================================
# C 08.01 / OF 08.01 — IRB COLUMN DEFINITIONS
# =============================================================================

# CRR C 08.01: 35 columns covering PD, exposure, CRM substitution, CRM in LGD
# estimates, exposure value, LGD, maturity, RWEA, expected loss, memorandum items.
CRR_C08_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", "PD assigned to obligor grade or pool (%)", "Internal Rating"),
    COREPColumn("0020", "Original exposure pre conversion factors", "Exposure"),
    COREPColumn("0030", "  Of which: large financial sector entities", "Exposure"),
    COREPColumn("0040", "(-) Guarantees", "CRM Substitution: Unfunded"),
    COREPColumn("0050", "(-) Credit derivatives", "CRM Substitution: Unfunded"),
    COREPColumn("0060", "(-) Other funded credit protection", "CRM Substitution: Funded"),
    COREPColumn("0070", "(-) Substitution outflows", "CRM Substitution"),
    COREPColumn("0080", "Substitution inflows (+)", "CRM Substitution"),
    COREPColumn("0090", "Exposure after CRM substitution pre CCFs", "Post-CRM"),
    COREPColumn("0100", "  Of which: off balance sheet", "Post-CRM"),
    COREPColumn("0110", "Exposure value", "Exposure Value"),
    COREPColumn("0120", "  Of which: off balance sheet", "Exposure Value"),
    COREPColumn("0130", "  Of which: arising from CCR", "Exposure Value"),
    COREPColumn("0140", "  Of which: large financial sector entities", "Exposure Value"),
    COREPColumn("0150", "Guarantees (own LGD estimates)", "CRM in LGD: Unfunded"),
    COREPColumn("0160", "Credit derivatives (own LGD estimates)", "CRM in LGD: Unfunded"),
    COREPColumn("0170", "Other funded credit protection (own LGD estimates)", "CRM in LGD: Funded"),
    COREPColumn("0171", "  Cash on deposit", "CRM in LGD: Funded"),
    COREPColumn("0172", "  Life insurance policies", "CRM in LGD: Funded"),
    COREPColumn("0173", "  Instruments held by a third party", "CRM in LGD: Funded"),
    COREPColumn("0180", "Eligible financial collateral", "CRM in LGD: Funded"),
    COREPColumn("0190", "  Other eligible collateral: Real estate", "CRM in LGD: Funded"),
    COREPColumn("0200", "  Other eligible collateral: Other physical", "CRM in LGD: Funded"),
    COREPColumn("0210", "  Other eligible collateral: Receivables", "CRM in LGD: Funded"),
    COREPColumn("0220", "Subject to double default treatment: Unfunded", "Double Default"),
    COREPColumn("0230", "Exposure-weighted average LGD (%)", "Parameters"),
    COREPColumn("0240", "  For large financial sector entities", "Parameters"),
    COREPColumn("0250", "Exposure-weighted average maturity (days)", "Parameters"),
    COREPColumn("0255", "RWEA pre supporting factors", "RWEA"),
    COREPColumn("0256", "(-) SME supporting factor adjustment", "RWEA"),
    COREPColumn("0257", "(-) Infrastructure supporting factor adjustment", "RWEA"),
    COREPColumn("0260", "RWEA after supporting factors", "RWEA"),
    COREPColumn("0270", "  Of which: large financial sector entities", "RWEA"),
    COREPColumn("0280", "Expected loss amount", "Memorandum"),
    COREPColumn("0290", "(-) Value adjustments and provisions", "Memorandum"),
    COREPColumn("0300", "Number of obligors", "Memorandum"),
    COREPColumn("0310", "Pre-credit derivatives RWEA", "Memorandum"),
]

# Basel 3.1 OF 08.01: 40+ columns — removes PD (totals), double default,
# supporting factors; adds on-BS netting, slotting FCCM, defaulted breakdowns,
# post-model adjustments, output floor columns.
B31_C08_COLUMNS: list[COREPColumn] = [
    # 0010 removed: PD only in OF 08.02
    COREPColumn("0020", "Original exposure pre conversion factors", "Exposure"),
    COREPColumn("0030", "  Of which: large financial sector entities", "Exposure"),
    COREPColumn(
        "0035", "(-) Adjustment due to on-balance sheet netting", "Exposure"
    ),  # New in B3.1
    COREPColumn("0040", "(-) Guarantees", "CRM Substitution: Unfunded"),
    COREPColumn("0050", "(-) Credit derivatives", "CRM Substitution: Unfunded"),
    COREPColumn("0060", "(-) Other funded credit protection", "CRM Substitution: Funded"),
    COREPColumn("0070", "(-) Substitution outflows", "CRM Substitution"),
    COREPColumn("0080", "Substitution inflows (+)", "CRM Substitution"),
    COREPColumn("0090", "Exposure after CRM substitution pre CCFs", "Post-CRM"),
    COREPColumn("0100", "  Of which: off balance sheet", "Post-CRM"),
    COREPColumn(
        "0101", "Volatility adjustment to the exposure (Slotting)", "Fin. Collateral Comprehensive"
    ),
    COREPColumn(
        "0102",
        "(-) Financial collateral adjusted value Cvam (Slotting)",
        "Fin. Collateral Comprehensive",
    ),
    COREPColumn(
        "0103",
        "(-) Of which: volatility and maturity adj (Slotting)",
        "Fin. Collateral Comprehensive",
    ),
    COREPColumn(
        "0104", "Exposure after all CRM pre CCFs (Slotting)", "Fin. Collateral Comprehensive"
    ),
    COREPColumn("0110", "Exposure value", "Exposure Value"),
    COREPColumn("0120", "  Of which: off balance sheet", "Exposure Value"),
    COREPColumn("0125", "  Of which: defaulted", "Exposure Value"),  # New in B3.1
    COREPColumn("0130", "  Of which: arising from CCR", "Exposure Value"),
    COREPColumn("0140", "  Of which: large financial sector entities", "Exposure Value"),
    COREPColumn("0150", "Guarantees", "CRM in LGD: Unfunded"),
    COREPColumn("0160", "Credit derivatives", "CRM in LGD: Unfunded"),
    COREPColumn("0170", "Other funded credit protection", "CRM in LGD: Funded"),
    COREPColumn("0171", "  Cash on deposit", "CRM in LGD: Funded"),
    COREPColumn("0172", "  Life insurance policies", "CRM in LGD: Funded"),
    COREPColumn("0173", "  Instruments held by a third party", "CRM in LGD: Funded"),
    COREPColumn("0180", "Eligible financial collateral", "CRM in LGD: Funded"),
    COREPColumn("0190", "  Other eligible collateral: Real estate", "CRM in LGD: Funded"),
    COREPColumn("0200", "  Other eligible collateral: Other physical", "CRM in LGD: Funded"),
    COREPColumn("0210", "  Other eligible collateral: Receivables", "CRM in LGD: Funded"),
    # 0220 removed: double default treatment removed in Basel 3.1
    COREPColumn("0230", "Exposure-weighted average LGD (%)", "Parameters"),
    COREPColumn("0240", "  For large financial sector entities", "Parameters"),
    COREPColumn("0250", "Exposure-weighted average maturity (days)", "Parameters"),
    COREPColumn("0251", "RWEA pre adjustments", "RWEA"),  # New in B3.1
    COREPColumn("0252", "Adjustment due to post-model adjustments", "RWEA"),  # New
    COREPColumn("0253", "Adjustment due to mortgage RW floor", "RWEA"),  # New
    COREPColumn("0254", "Unrecognised exposure adjustments", "RWEA"),  # New
    # 0255-0257 removed: supporting factors don't exist under Basel 3.1
    COREPColumn("0260", "RWEA after adjustments", "RWEA"),  # Changed name
    COREPColumn("0265", "  Of which: defaulted", "RWEA"),  # New in B3.1
    COREPColumn("0270", "  Of which: large financial sector entities", "RWEA"),
    COREPColumn("0275", "Non-modelled approaches: exposure value", "Output Floor"),  # New
    COREPColumn("0276", "Non-modelled approaches: RWEA", "Output Floor"),  # New
    COREPColumn("0280", "Expected loss amount (pre post-model adj)", "Memorandum"),  # Changed
    COREPColumn(
        "0281", "Adjustment to EL due to post-model adjustments", "Memorandum"
    ),  # New in B3.1
    COREPColumn("0282", "Expected loss amount after post-model adjustments", "Memorandum"),  # New
    COREPColumn("0290", "(-) Value adjustments and provisions", "Memorandum"),
    COREPColumn("0300", "Number of obligors", "Memorandum"),
    COREPColumn("0310", "Pre-credit derivatives RWEA", "Memorandum"),
]


# =============================================================================
# C 08.01 / OF 08.01 — IRB ROW SECTIONS
# =============================================================================

CRR_IRB_ROW_SECTIONS: list[RowSection] = [
    RowSection(
        "Total and Supporting Factors",
        [
            COREPRow("0010", "TOTAL EXPOSURES"),
            COREPRow("0015", "of which: Exposures subject to SME-supporting factor"),
            COREPRow("0016", "of which: Exposures subject to infrastructure supporting factor"),
        ],
    ),
    RowSection(
        "Breakdown by Exposure Types",
        [
            COREPRow("0020", "On balance sheet items subject to credit risk"),
            COREPRow("0030", "Off balance sheet items subject to credit risk"),
            COREPRow("0040", "SFT netting sets"),
            COREPRow("0050", "Derivatives & Long Settlement Transactions netting sets"),
            COREPRow("0060", "From Contractual Cross Product netting sets"),
        ],
    ),
    RowSection(
        "Calculation Approaches",
        [
            COREPRow("0070", "Exposures assigned to obligor grades or pools: Total"),
            COREPRow("0080", "Specialised lending slotting approach: Total"),
            COREPRow("0160", "Alternative treatment: Secured by real estate"),
            COREPRow("0170", "Exposures from free deliveries"),
            COREPRow("0180", "Dilution risk: Total purchased receivables"),
        ],
    ),
]

B31_IRB_ROW_SECTIONS: list[RowSection] = [
    RowSection(
        "Total",
        [
            COREPRow("0010", "TOTAL EXPOSURES"),
            COREPRow("0017", "of which: revolving loan commitments"),  # New in B3.1
            # 0015, 0016 removed: supporting factors don't exist under Basel 3.1
        ],
    ),
    RowSection(
        "Breakdown by Exposure Types",
        [
            COREPRow("0020", "On balance sheet items subject to credit risk"),
            COREPRow("0030", "Off balance sheet items subject to credit risk"),
            COREPRow("0031", "  of which: off-BS by CCF 10%"),  # New in B3.1
            COREPRow("0032", "  of which: off-BS by CCF 20%"),
            COREPRow("0033", "  of which: off-BS by CCF 40%"),
            COREPRow("0034", "  of which: off-BS by CCF 50%"),
            COREPRow("0035", "  of which: off-BS by CCF 100%"),
            COREPRow("0040", "SFT netting sets"),
            COREPRow("0050", "Derivatives & Long Settlement Transactions netting sets"),
            COREPRow("0060", "From Contractual Cross Product netting sets"),
        ],
    ),
    RowSection(
        "Calculation Approaches",
        [
            COREPRow("0070", "Exposures assigned to obligor grades or pools: Total"),
            COREPRow("0080", "Specialised lending slotting approach: Total"),
            # 0160 removed: alternative RE treatment removed in Basel 3.1
            COREPRow("0170", "Exposures from free deliveries"),
            COREPRow("0175", "Purchased receivables"),  # New in B3.1
            COREPRow("0180", "Dilution risk: Total purchased receivables"),
            COREPRow("0190", "Corporates without ECAI"),  # New in B3.1
            COREPRow("0200", "  of which: investment grade"),  # New in B3.1
        ],
    ),
]


# =============================================================================
# C 08.02 / OF 08.02 — IRB PD GRADE BANDS
# =============================================================================

# Standard PD bands for obligor grade grouping. The actual COREP template
# uses firm-specific internal rating grades (dynamic rows), not pre-defined
# PD bands. These bands are provided for aggregation convenience when
# firm-specific grade data is not available.
# Each tuple: (lower_bound_inclusive, upper_bound_exclusive, display_label)
PD_BANDS: list[tuple[float, float, str]] = [
    (0.0, 0.0015, "0.00% - 0.15%"),
    (0.0015, 0.0025, "0.15% - 0.25%"),
    (0.0025, 0.005, "0.25% - 0.50%"),
    (0.005, 0.0075, "0.50% - 0.75%"),
    (0.0075, 0.025, "0.75% - 2.50%"),
    (0.025, 0.10, "2.50% - 10.00%"),
    (0.10, 0.9999, "10.00% - 99.99%"),
    (0.9999, float("inf"), "Default (100%)"),
]

# C 08.02 uses the same columns as C 08.01 with addition of 0005 (obligor grade).
# The column set depends on the framework.
CRR_C08_02_COLUMNS: list[COREPColumn] = [
    COREPColumn("0005", "Obligor grade row identifier", "Internal Rating"),
    *CRR_C08_COLUMNS,
]

B31_C08_02_COLUMNS: list[COREPColumn] = [
    COREPColumn("0005", "Obligor grade row identifier", "Internal Rating"),
    # PD column 0010 is retained in OF 08.02 (removed from OF 08.01 totals only)
    COREPColumn("0010", "PD assigned to obligor grade or pool (%)", "Internal Rating"),
    *B31_C08_COLUMNS,
]


# =============================================================================
# C 08.03 / OF 08.03 — IRB PD RANGES (regulatory fixed buckets)
# =============================================================================

# C 08.03 uses 17 fixed regulatory PD range buckets (unlike C 08.02 which uses
# firm-specific internal rating grades). One submission per IRB exposure class.
# Slotting exposures are excluded.
# Each tuple: (lower_bound_inclusive, upper_bound_exclusive, row_ref, display_label)
#
# Basel 3.1 distinction: Row allocation uses pre-input-floor PD
# ("PD RANGE (PRE-INPUT FLOOR)"), but column 0050 reports the post-input-floor
# exposure-weighted average PD ("EXPOSURE WEIGHTED AVERAGE PD (POST INPUT FLOOR)").
#
# References:
# - CRR Art. 153 (IRB PD distribution), Regulation (EU) 2021/451 Annex I
# - PRA PS1/26 Annex I (OF 08.03 template layout)
# - PRA PS1/26 Annex II (OF 08.03 reporting instructions)

C08_03_PD_RANGES: list[tuple[float, float, str, str]] = [
    (0.0, 0.0003, "0010", "0.00 to < 0.03%"),
    (0.0003, 0.0005, "0020", "0.03 to < 0.05%"),
    (0.0005, 0.0010, "0030", "0.05 to < 0.10%"),
    (0.0010, 0.0015, "0040", "0.10 to < 0.15%"),
    (0.0015, 0.0020, "0050", "0.15 to < 0.20%"),
    (0.0020, 0.0025, "0060", "0.20 to < 0.25%"),
    (0.0025, 0.0050, "0070", "0.25 to < 0.50%"),
    (0.0050, 0.0075, "0080", "0.50 to < 0.75%"),
    (0.0075, 0.0100, "0090", "0.75 to < 1.00%"),
    (0.0100, 0.0250, "0100", "1.00 to < 2.50%"),
    (0.0250, 0.0500, "0110", "2.50 to < 5.00%"),
    (0.0500, 0.1000, "0120", "5.00 to < 10.00%"),
    (0.1000, 0.2000, "0130", "10.00 to < 20.00%"),
    (0.2000, 0.3000, "0140", "20.00 to < 30.00%"),
    (0.3000, 0.5000, "0150", "30.00 to < 50.00%"),
    (0.5000, 1.0000, "0160", "50.00 to < 100%"),
    (1.0000, float("inf"), "0170", "100% (Default)"),
]

# C 08.03 / OF 08.03 has 11 columns — simpler than C 08.01/08.02.
# References: Regulation (EU) 2021/451 Annex I (C 08.03), PRA PS1/26 Annex I (OF 08.03)
CRR_C08_03_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", "Original exposure pre conversion factors — on-balance sheet", "Exposure"),
    COREPColumn("0020", "Original exposure pre conversion factors — off-balance sheet", "Exposure"),
    COREPColumn("0030", "Average CCF (%)", "CCF"),
    COREPColumn("0040", "Exposure value (post CCF and post CRM)", "EAD"),
    COREPColumn("0050", "Exposure-weighted average PD (%)", "PD"),
    COREPColumn("0060", "Number of obligors", "Obligors"),
    COREPColumn("0070", "Exposure-weighted average LGD (%)", "LGD"),
    COREPColumn("0080", "Exposure-weighted average maturity (years)", "Maturity"),
    COREPColumn("0090", "Risk weighted exposure amount (RWEA)", "RWEA"),
    COREPColumn("0100", "Expected loss amount", "EL"),
    COREPColumn("0110", "Value adjustments and provisions", "Provisions"),
]

# OF 08.03 (Basel 3.1) has the same 11 columns but with adjusted naming for the
# PD column to clarify it reports post-input-floor values.
# Supporting factors are removed (no sub-columns under RWEA).
B31_C08_03_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", "Original exposure pre conversion factors — on-balance sheet", "Exposure"),
    COREPColumn("0020", "Original exposure pre conversion factors — off-balance sheet", "Exposure"),
    COREPColumn("0030", "Average CCF (%)", "CCF"),
    COREPColumn("0040", "Exposure value (post CCF and post CRM)", "EAD"),
    COREPColumn(
        "0050",
        "Exposure-weighted average PD (%) (post input floor)",
        "PD",
    ),
    COREPColumn("0060", "Number of obligors", "Obligors"),
    COREPColumn("0070", "Exposure-weighted average LGD (%)", "LGD"),
    COREPColumn("0080", "Exposure-weighted average maturity (years)", "Maturity"),
    COREPColumn("0090", "Risk weighted exposure amount (RWEA)", "RWEA"),
    COREPColumn("0100", "Expected loss amount", "EL"),
    COREPColumn("0110", "Value adjustments and provisions", "Provisions"),
]

C08_03_COLUMN_REFS: list[str] = [c.ref for c in CRR_C08_03_COLUMNS]


# =============================================================================
# OF 02.01 — OUTPUT FLOOR COMPARISON (Basel 3.1 only, PRA PS1/26 Art. 92)
# =============================================================================

# OF 02.01 compares modelled (U-TREA) vs standardised (S-TREA) risk exposure
# amounts by risk type. Basel 3.1 only — no CRR equivalent.
# Reference: PRA PS1/26 Art. 92 para 2A/3A, PRA COREP reporting framework

OF_02_01_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", "Total risk exposure amount (modelled approaches)", "Comparison"),
    COREPColumn("0020", "Total risk exposure amount (standardised approaches)", "Comparison"),
    COREPColumn("0030", "U-TREA", "Output Floor"),
    COREPColumn("0040", "S-TREA", "Output Floor"),
]

OF_02_01_ROW_SECTIONS: list[RowSection] = [
    RowSection(
        "Risk Type Breakdown",
        [
            COREPRow("0010", "Credit risk (excluding CCR)"),
            COREPRow("0020", "Counterparty credit risk"),
            COREPRow("0030", "Credit valuation adjustment risk"),
            COREPRow("0040", "Securitisation positions in the non-trading book"),
            COREPRow("0050", "Market risk"),
            COREPRow("0060", "Operational risk"),
            COREPRow("0070", "Other"),
            COREPRow("0080", "Total"),
        ],
    ),
]

OF_02_01_COLUMN_REFS: list[str] = [c.ref for c in OF_02_01_COLUMNS]


# =============================================================================
# BACKWARD COMPATIBILITY ALIASES
# These are used by the current generator (pre-Task 1B) and will be removed
# when the generator is rewritten.
# =============================================================================

# Old 9-column C 07.00 definition — used by generator until Task 1B rewrites it.
C07_COLUMNS: list[COREPColumn] = [
    COREPColumn("010", "Original exposure pre conversion factors"),
    COREPColumn("020", "(-) Value adjustments and provisions"),
    COREPColumn("030", "Exposure net of value adjustments and provisions"),
    COREPColumn("040", "(-) Funded credit protection (collateral)"),
    COREPColumn("050", "(-) Unfunded credit protection (guarantees)"),
    COREPColumn("060", "Net exposure after CRM substitution effects"),
    COREPColumn("070", "Exposure value (E*) post CCF"),
    COREPColumn("080", "Risk weighted exposure amount (RWEA)"),
    COREPColumn("090", "Of which: with ECAI credit assessment"),
]

# Old 11-column C 08.01 definition — used by generator until Task 1B rewrites it.
C08_01_COLUMNS: list[COREPColumn] = [
    COREPColumn("010", "Weighted average PD (%)"),
    COREPColumn("020", "Original exposure pre conversion factors"),
    COREPColumn("030", "(-) Value adjustments and provisions"),
    COREPColumn("040", "Exposure value (EAD)"),
    COREPColumn("050", "Exposure-weighted average LGD (%)"),
    COREPColumn("060", "Exposure-weighted average maturity (years)"),
    COREPColumn("070", "Risk weighted exposure amount (RWEA)"),
    COREPColumn("080", "Expected loss amount"),
    COREPColumn("090", "(-) Provisions allocated"),
    COREPColumn("100", "Number of obligors"),
    COREPColumn("110", "EL shortfall (-)  / excess (+)"),
]

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_c07_columns(framework: str = "CRR") -> list[COREPColumn]:
    """Return the C 07.00 / OF 07.00 column definitions for the given framework."""
    return B31_C07_COLUMNS if framework == "BASEL_3_1" else CRR_C07_COLUMNS


def get_c08_columns(framework: str = "CRR") -> list[COREPColumn]:
    """Return the C 08.01 / OF 08.01 column definitions for the given framework."""
    return B31_C08_COLUMNS if framework == "BASEL_3_1" else CRR_C08_COLUMNS


def get_c08_02_columns(framework: str = "CRR") -> list[COREPColumn]:
    """Return the C 08.02 / OF 08.02 column definitions for the given framework."""
    return B31_C08_02_COLUMNS if framework == "BASEL_3_1" else CRR_C08_02_COLUMNS


def get_c08_03_columns(framework: str = "CRR") -> list[COREPColumn]:
    """Return the C 08.03 / OF 08.03 column definitions for the given framework."""
    return B31_C08_03_COLUMNS if framework == "BASEL_3_1" else CRR_C08_03_COLUMNS


def get_sa_row_sections(framework: str = "CRR") -> list[RowSection]:
    """Return the SA row sections for the given framework."""
    return B31_SA_ROW_SECTIONS if framework == "BASEL_3_1" else CRR_SA_ROW_SECTIONS


def get_irb_row_sections(framework: str = "CRR") -> list[RowSection]:
    """Return the IRB row sections for the given framework."""
    return B31_IRB_ROW_SECTIONS if framework == "BASEL_3_1" else CRR_IRB_ROW_SECTIONS


def get_sa_risk_weight_bands(framework: str = "CRR") -> list[tuple[float, str]]:
    """Return the SA risk weight bands for the given framework."""
    return B31_SA_RISK_WEIGHT_BANDS if framework == "BASEL_3_1" else SA_RISK_WEIGHT_BANDS
