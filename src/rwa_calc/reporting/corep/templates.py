"""
COREP template structure definitions.

Defines the row/column structure for COREP credit risk templates:
- C 07.00 / OF 07.00: SA credit risk — 24/22 columns, 5 row sections
- C 08.01 / OF 08.01: IRB totals — 35/40+ columns, row sections
- C 08.02 / OF 08.02: IRB PD grade bands for granular reporting
- C 08.03 / OF 08.03: IRB PD ranges — 11 columns, 17 fixed regulatory PD buckets
- C 08.04 / OF 08.04: IRB RWEA flow statements — 1 column, 9 rows
- C 08.05 / OF 08.05: IRB PD backtesting — 5 columns, 17 fixed regulatory PD buckets
- C 08.06 / OF 08.06: IRB specialised lending slotting — 10/11 columns, per SL type
- C 08.07 / OF 08.07: IRB scope of use — 5/18 columns, per exposure class (CRR/B31)
- OF 02.01: Output floor comparison — 4 columns, 8 risk-type rows (Basel 3.1 only)
- C 09.01 / OF 09.01: CR GB 1 — geographical breakdown SA, 13/10 columns
- C 09.02 / OF 09.02: CR GB 2 — geographical breakdown IRB, 17/15 columns

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
# Shared label / group / section constants (DRY — referenced by multiple templates)
# =============================================================================

# --- SA exposure-class labels ---
_LBL_SA_CENTRAL_GOVT = "Central governments or central banks"
_LBL_IRB_CENTRAL_GOVT = "Central governments and central banks"
_LBL_SA_RGLA = "Regional governments or local authorities"
_LBL_SA_PSE = "Public sector entities"
_LBL_SA_MDB = "Multilateral development banks"
_LBL_SA_INTL_ORG = "International organisations"
_LBL_SA_MORTGAGES = "Secured by mortgages on immovable property"
_LBL_SA_DEFAULTED = "Exposures in default"
_LBL_SA_COVERED_BOND = "Covered bonds"
_LBL_SA_OTHER = "Other items"

# --- Common column / row labels ---
_LBL_COL_ORIG_EXPOSURE = "Original exposure pre conversion factors"
_LBL_COL_VALUE_ADJUSTMENTS = "(-) Value adjustments and provisions"
_LBL_COL_GUARANTEES = "(-) Guarantees"
_LBL_COL_CREDIT_DERIVS = "(-) Credit derivatives"
_LBL_COL_OTHER_FUNDED = "(-) Other funded credit protection"
_LBL_COL_SUBST_OUTFLOWS = "(-) Substitution outflows"
_LBL_COL_SUBST_INFLOWS = "Substitution inflows (+)"
_LBL_COL_EXPOSURE_VALUE_LC = "Exposure value"
_LBL_COL_RWEA_PRE_SF = "RWEA pre supporting factors"
_LBL_COL_SME_SF_ADJ = "(-) SME supporting factor adjustment"
_LBL_COL_INFRA_SF_ADJ = "(-) Infrastructure supporting factor adjustment"
_LBL_COL_RWEA_POST_SF = "RWEA after supporting factors"
_LBL_COL_OF_WHICH_ECAI = "Of which: with ECAI credit assessment"
_LBL_COL_RWEA_HYPHEN = "Risk-weighted exposure amount"
_LBL_COL_RWEA_SPACE_SUFFIX = "Risk weighted exposure amount (RWEA)"
_LBL_COL_OF_WHICH_LARGE_FSE = "  Of which: large financial sector entities"
_LBL_COL_OF_WHICH_OFF_BS = "  Of which: off balance sheet"
_LBL_COL_EW_AVG_LGD = "Exposure-weighted average LGD (%)"
_LBL_COL_EXPECTED_LOSS = "Expected loss amount"
_LBL_COL_NUM_OBLIGORS = "Number of obligors"
_LBL_COL_EW_AVG_MATURITY_YRS = "Exposure-weighted average maturity (years)"
_LBL_COL_OBSERVED_DEFAULTS = "Observed new defaults for the period"
_LBL_COL_GEN_CRA = "General credit risk adjustments"
_LBL_COL_SPEC_CRA = "Specific credit risk adjustments"
_LBL_COL_CRA_WRITEOFFS = "Credit risk adjustments/write-offs for observed new defaults"
_LBL_ROW_TOTAL_EXPOSURES_UC = "TOTAL EXPOSURES"
_LBL_ROW_TOTAL_EXPOSURES_MC = "Total exposures"
_LBL_ROW_SFT_NETTING = "SFT netting sets"
_LBL_ROW_OF_WHICH_QCCP = "  of which: centrally cleared through a QCCP"
_LBL_ROW_DERIV_LST_NETTING = "Derivatives & Long Settlement Transactions netting sets"
_LBL_ROW_CCP_NETTING = "From Contractual Cross Product netting sets"
# Correct ONLY where a sibling "Counterparty credit risk" row exists (OF 02.01, OV1).
_LBL_ROW_CREDIT_RISK_EXCL_CCR = "Credit risk (excluding CCR)"
# C 02.00 / OF 02.00 row 0050 has no such sibling — CCR is INSIDE it (Annex II wording).
_LBL_ROW_CREDIT_CCR_DILUTION_FREE_DELIV = (
    "RISK WEIGHTED EXPOSURE AMOUNTS FOR CREDIT, COUNTERPARTY CREDIT AND DILUTION RISKS "
    "AND FREE DELIVERIES"
)
_LBL_ROW_OP_RISK = "Operational risk"
_LBL_ROW_CIU = "Collective investment undertakings (CIU)"
_LBL_ROW_OF_WHICH_SME_LC = "  of which: SME"

# --- Common group labels ---
_GRP_CRM_SUBST_UNFUNDED = "CRM Substitution: Unfunded"
_GRP_CRM_SUBST_FUNDED = "CRM Substitution: Funded"
_GRP_CRM_SUBST = "CRM Substitution"
_GRP_FIN_COLL_COMP = "Fin. Collateral Comprehensive"
_GRP_CCF_BREAKDOWN = "CCF Breakdown"
_GRP_EXPOSURE_VALUE = "Exposure Value"
_GRP_INTERNAL_RATING = "Internal Rating"
_GRP_CRM_LGD_UNFUNDED = "CRM in LGD: Unfunded"
_GRP_CRM_LGD_FUNDED = "CRM in LGD: Funded"
_GRP_OUTPUT_FLOOR = "Output Floor"
_GRP_COVERAGE_PCT = "Coverage %"
_GRP_RWEA_SA_BREAKDOWN = "RWEA: SA Breakdown"

# --- Section names ---
_SEC_BREAKDOWN_EXPOSURE_TYPES = "Breakdown by Exposure Types"
_SEC_MEMORANDUM_ITEMS = "Memorandum Items"

# --- Slotting category labels ---
_LBL_SLOT_CAT1 = "Category 1 (Strong)"
_LBL_SLOT_CAT2 = "Category 2 (Good)"
_LBL_SLOT_CAT3 = "Category 3 (Satisfactory)"
_LBL_SLOT_CAT4 = "Category 4 (Weak)"
_LBL_SLOT_CAT5 = "Category 5 (Default)"


# =============================================================================
# SA EXPOSURE CLASS FILTER — used by generator to filter pipeline data
# =============================================================================

# Mapping: ExposureClass.value -> (row_ref, display_name)
# These are filter values used by the generator to select data for each
# per-exposure-class template submission. They are NOT the row structure
# of the template itself — see SA_ROW_SECTIONS for that.
SA_EXPOSURE_CLASS_ROWS: dict[str, tuple[str, str]] = {
    "central_govt_central_bank": ("0010", _LBL_SA_CENTRAL_GOVT),
    "rgla": ("0020", _LBL_SA_RGLA),
    "pse": ("0030", _LBL_SA_PSE),
    "mdb": ("0040", _LBL_SA_MDB),
    "international_organisation": ("0050", _LBL_SA_INTL_ORG),
    "institution": ("0060", "Institutions"),
    "corporate": ("0070", "Corporates"),
    "corporate_sme": ("0071", "  Of which: SME corporates"),
    "retail_mortgage": ("0080", _LBL_SA_MORTGAGES),
    "retail_other": ("0090", "Retail"),
    "retail_qrre": ("0091", "  Of which: Qualifying revolving"),
    "defaulted": ("0100", _LBL_SA_DEFAULTED),
    "covered_bond": ("0105", _LBL_SA_COVERED_BOND),
    "equity": ("0110", "Equity exposures"),
    "other": ("0120", _LBL_SA_OTHER),
}

# IRB exposure class filter values — used by generator for per-class filtering.
# Not the row structure; see IRB_ROW_SECTIONS for that.
IRB_EXPOSURE_CLASS_ROWS: dict[str, tuple[str, str]] = {
    "central_govt_central_bank": ("0010", _LBL_IRB_CENTRAL_GOVT),
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
    COREPColumn("0010", _LBL_COL_ORIG_EXPOSURE, "Exposure"),
    COREPColumn("0020", "Exposures deducted from own funds", "Exposure"),
    COREPColumn("0030", _LBL_COL_VALUE_ADJUSTMENTS, "Exposure"),
    COREPColumn("0040", "Exposure net of value adjustments and provisions", "Exposure"),
    COREPColumn("0050", _LBL_COL_GUARANTEES, _GRP_CRM_SUBST_UNFUNDED),
    COREPColumn("0060", _LBL_COL_CREDIT_DERIVS, _GRP_CRM_SUBST_UNFUNDED),
    COREPColumn("0070", "(-) Financial collateral: Simple method", _GRP_CRM_SUBST_FUNDED),
    COREPColumn("0080", _LBL_COL_OTHER_FUNDED, _GRP_CRM_SUBST_FUNDED),
    COREPColumn("0090", _LBL_COL_SUBST_OUTFLOWS, _GRP_CRM_SUBST),
    COREPColumn("0100", _LBL_COL_SUBST_INFLOWS, _GRP_CRM_SUBST),
    COREPColumn("0110", "Net exposure after CRM substitution effects pre CCFs", "Post-CRM"),
    COREPColumn("0120", "Volatility adjustment to the exposure", _GRP_FIN_COLL_COMP),
    COREPColumn(
        "0130",
        "(-) Financial collateral: adjusted value (Cvam)",
        _GRP_FIN_COLL_COMP,
    ),
    COREPColumn(
        "0140",
        "(-) Of which: volatility and maturity adjustments",
        _GRP_FIN_COLL_COMP,
    ),
    COREPColumn("0150", "Fully adjusted exposure value (E*)", "Post-CRM"),
    COREPColumn("0160", "Off-BS by CCF: 0%", _GRP_CCF_BREAKDOWN),
    COREPColumn("0170", "Off-BS by CCF: 20%", _GRP_CCF_BREAKDOWN),
    COREPColumn("0180", "Off-BS by CCF: 50%", _GRP_CCF_BREAKDOWN),
    COREPColumn("0190", "Off-BS by CCF: 100%", _GRP_CCF_BREAKDOWN),
    COREPColumn("0200", _LBL_COL_EXPOSURE_VALUE_LC, "Final"),
    COREPColumn("0210", "Of which: arising from CCR", "Final"),
    COREPColumn("0211", "Of which: CCR excl. CCP", "Final"),
    COREPColumn("0215", _LBL_COL_RWEA_PRE_SF, "RWEA"),
    COREPColumn("0216", _LBL_COL_SME_SF_ADJ, "RWEA"),
    COREPColumn("0217", _LBL_COL_INFRA_SF_ADJ, "RWEA"),
    COREPColumn("0220", _LBL_COL_RWEA_POST_SF, "RWEA"),
    COREPColumn("0230", _LBL_COL_OF_WHICH_ECAI, "RWEA"),
    COREPColumn("0240", "Of which: credit assessment derived from central govt", "RWEA"),
]

# Basel 3.1 OF 07.00: 22 columns — adds 0035, 0171, 0235; removes 0215-0217;
# changes 0160 from 0% CCF to 10% CCF.
B31_C07_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", _LBL_COL_ORIG_EXPOSURE, "Exposure"),
    COREPColumn("0020", "Exposures deducted from own funds", "Exposure"),
    COREPColumn("0030", _LBL_COL_VALUE_ADJUSTMENTS, "Exposure"),
    COREPColumn(
        "0035", "(-) Adjustment due to on-balance sheet netting", "Exposure"
    ),  # New in B3.1
    COREPColumn(
        "0040", "Exposure net of adjustments, provisions, and netting", "Exposure"
    ),  # Changed
    COREPColumn("0050", "(-) Guarantees (adjusted values)", _GRP_CRM_SUBST_UNFUNDED),
    COREPColumn("0060", _LBL_COL_CREDIT_DERIVS, _GRP_CRM_SUBST_UNFUNDED),
    COREPColumn("0070", "(-) Financial collateral: Simple method", _GRP_CRM_SUBST_FUNDED),
    COREPColumn("0080", _LBL_COL_OTHER_FUNDED, _GRP_CRM_SUBST_FUNDED),
    COREPColumn("0090", _LBL_COL_SUBST_OUTFLOWS, _GRP_CRM_SUBST),
    COREPColumn("0100", _LBL_COL_SUBST_INFLOWS, _GRP_CRM_SUBST),
    COREPColumn("0110", "Net exposure after CRM substitution effects pre CCFs", "Post-CRM"),
    COREPColumn("0120", "Volatility adjustment to the exposure", _GRP_FIN_COLL_COMP),
    COREPColumn(
        "0130",
        "(-) Financial collateral: adjusted value (Cvam)",
        _GRP_FIN_COLL_COMP,
    ),
    COREPColumn(
        "0140",
        "(-) Of which: volatility and maturity adjustments",
        _GRP_FIN_COLL_COMP,
    ),
    COREPColumn("0150", "Fully adjusted exposure value (E*)", "Post-CRM"),
    COREPColumn("0160", "Off-BS by CCF: 10%", _GRP_CCF_BREAKDOWN),  # Changed: was 0% in CRR
    COREPColumn("0170", "Off-BS by CCF: 20%", _GRP_CCF_BREAKDOWN),
    COREPColumn("0171", "Off-BS by CCF: 40%", _GRP_CCF_BREAKDOWN),  # New in B3.1
    COREPColumn("0180", "Off-BS by CCF: 50%", _GRP_CCF_BREAKDOWN),
    COREPColumn("0190", "Off-BS by CCF: 100%", _GRP_CCF_BREAKDOWN),
    COREPColumn("0200", _LBL_COL_EXPOSURE_VALUE_LC, "Final"),
    COREPColumn("0210", "Of which: arising from CCR", "Final"),
    COREPColumn("0211", "Of which: CCR excl. CCP", "Final"),
    # 0215-0217 removed: supporting factors don't exist under Basel 3.1
    COREPColumn("0220", _LBL_COL_RWEA_HYPHEN, "RWEA"),  # Changed name
    COREPColumn("0230", _LBL_COL_OF_WHICH_ECAI, "RWEA"),
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
            COREPRow("0010", _LBL_ROW_TOTAL_EXPOSURES_UC),
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
        _SEC_BREAKDOWN_EXPOSURE_TYPES,
        [
            COREPRow("0070", "On balance sheet exposures subject to credit risk"),
            COREPRow("0080", "Off balance sheet exposures subject to credit risk"),
            COREPRow("0090", _LBL_ROW_SFT_NETTING),
            COREPRow("0100", _LBL_ROW_OF_WHICH_QCCP),
            COREPRow("0110", _LBL_ROW_DERIV_LST_NETTING),
            COREPRow("0120", _LBL_ROW_OF_WHICH_QCCP),
            COREPRow("0130", _LBL_ROW_CCP_NETTING),
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
        _SEC_MEMORANDUM_ITEMS,
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
            COREPRow("0010", _LBL_ROW_TOTAL_EXPOSURES_UC),
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
        _SEC_BREAKDOWN_EXPOSURE_TYPES,
        [
            COREPRow("0070", "On balance sheet exposures subject to credit risk"),
            COREPRow("0080", "Off balance sheet exposures subject to credit risk"),
            COREPRow("0090", _LBL_ROW_SFT_NETTING),
            COREPRow("0100", _LBL_ROW_OF_WHICH_QCCP),
            COREPRow("0110", _LBL_ROW_DERIV_LST_NETTING),
            COREPRow("0120", _LBL_ROW_OF_WHICH_QCCP),
            COREPRow("0130", _LBL_ROW_CCP_NETTING),
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
        _SEC_MEMORANDUM_ITEMS,
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
    COREPColumn("0010", "PD assigned to obligor grade or pool (%)", _GRP_INTERNAL_RATING),
    COREPColumn("0020", _LBL_COL_ORIG_EXPOSURE, "Exposure"),
    COREPColumn("0030", _LBL_COL_OF_WHICH_LARGE_FSE, "Exposure"),
    COREPColumn("0040", _LBL_COL_GUARANTEES, _GRP_CRM_SUBST_UNFUNDED),
    COREPColumn("0050", _LBL_COL_CREDIT_DERIVS, _GRP_CRM_SUBST_UNFUNDED),
    COREPColumn("0060", _LBL_COL_OTHER_FUNDED, _GRP_CRM_SUBST_FUNDED),
    COREPColumn("0070", _LBL_COL_SUBST_OUTFLOWS, _GRP_CRM_SUBST),
    COREPColumn("0080", _LBL_COL_SUBST_INFLOWS, _GRP_CRM_SUBST),
    COREPColumn("0090", "Exposure after CRM substitution pre CCFs", "Post-CRM"),
    COREPColumn("0100", _LBL_COL_OF_WHICH_OFF_BS, "Post-CRM"),
    COREPColumn("0110", _LBL_COL_EXPOSURE_VALUE_LC, _GRP_EXPOSURE_VALUE),
    COREPColumn("0120", _LBL_COL_OF_WHICH_OFF_BS, _GRP_EXPOSURE_VALUE),
    COREPColumn("0130", "  Of which: arising from CCR", _GRP_EXPOSURE_VALUE),
    COREPColumn("0140", _LBL_COL_OF_WHICH_LARGE_FSE, _GRP_EXPOSURE_VALUE),
    COREPColumn("0150", "Guarantees (own LGD estimates)", _GRP_CRM_LGD_UNFUNDED),
    COREPColumn("0160", "Credit derivatives (own LGD estimates)", _GRP_CRM_LGD_UNFUNDED),
    COREPColumn("0170", "Other funded credit protection (own LGD estimates)", _GRP_CRM_LGD_FUNDED),
    COREPColumn("0171", "  Cash on deposit", _GRP_CRM_LGD_FUNDED),
    COREPColumn("0172", "  Life insurance policies", _GRP_CRM_LGD_FUNDED),
    COREPColumn("0173", "  Instruments held by a third party", _GRP_CRM_LGD_FUNDED),
    COREPColumn("0180", "Eligible financial collateral", _GRP_CRM_LGD_FUNDED),
    COREPColumn("0190", "  Other eligible collateral: Real estate", _GRP_CRM_LGD_FUNDED),
    COREPColumn("0200", "  Other eligible collateral: Other physical", _GRP_CRM_LGD_FUNDED),
    COREPColumn("0210", "  Other eligible collateral: Receivables", _GRP_CRM_LGD_FUNDED),
    COREPColumn("0220", "Subject to double default treatment: Unfunded", "Double Default"),
    COREPColumn("0230", _LBL_COL_EW_AVG_LGD, "Parameters"),
    COREPColumn("0240", "  For large financial sector entities", "Parameters"),
    COREPColumn("0250", "Exposure-weighted average maturity (days)", "Parameters"),
    COREPColumn("0255", _LBL_COL_RWEA_PRE_SF, "RWEA"),
    COREPColumn("0256", _LBL_COL_SME_SF_ADJ, "RWEA"),
    COREPColumn("0257", _LBL_COL_INFRA_SF_ADJ, "RWEA"),
    COREPColumn("0260", _LBL_COL_RWEA_POST_SF, "RWEA"),
    COREPColumn("0270", _LBL_COL_OF_WHICH_LARGE_FSE, "RWEA"),
    COREPColumn("0280", _LBL_COL_EXPECTED_LOSS, "Memorandum"),
    COREPColumn("0290", _LBL_COL_VALUE_ADJUSTMENTS, "Memorandum"),
    COREPColumn("0300", _LBL_COL_NUM_OBLIGORS, "Memorandum"),
    COREPColumn("0310", "Pre-credit derivatives RWEA", "Memorandum"),
]

# Basel 3.1 OF 08.01: 40+ columns — removes PD (totals), double default,
# supporting factors; adds on-BS netting, slotting FCCM, defaulted breakdowns,
# post-model adjustments, output floor columns.
B31_C08_COLUMNS: list[COREPColumn] = [
    # 0010 removed: PD only in OF 08.02
    COREPColumn("0020", _LBL_COL_ORIG_EXPOSURE, "Exposure"),
    COREPColumn("0030", _LBL_COL_OF_WHICH_LARGE_FSE, "Exposure"),
    COREPColumn(
        "0035", "(-) Adjustment due to on-balance sheet netting", "Exposure"
    ),  # New in B3.1
    COREPColumn("0040", _LBL_COL_GUARANTEES, _GRP_CRM_SUBST_UNFUNDED),
    COREPColumn("0050", _LBL_COL_CREDIT_DERIVS, _GRP_CRM_SUBST_UNFUNDED),
    COREPColumn("0060", _LBL_COL_OTHER_FUNDED, _GRP_CRM_SUBST_FUNDED),
    COREPColumn("0070", _LBL_COL_SUBST_OUTFLOWS, _GRP_CRM_SUBST),
    COREPColumn("0080", _LBL_COL_SUBST_INFLOWS, _GRP_CRM_SUBST),
    COREPColumn("0090", "Exposure after CRM substitution pre CCFs", "Post-CRM"),
    COREPColumn("0100", _LBL_COL_OF_WHICH_OFF_BS, "Post-CRM"),
    COREPColumn("0101", "Volatility adjustment to the exposure (Slotting)", _GRP_FIN_COLL_COMP),
    COREPColumn(
        "0102",
        "(-) Financial collateral adjusted value Cvam (Slotting)",
        _GRP_FIN_COLL_COMP,
    ),
    COREPColumn(
        "0103",
        "(-) Of which: volatility and maturity adj (Slotting)",
        _GRP_FIN_COLL_COMP,
    ),
    COREPColumn("0104", "Exposure after all CRM pre CCFs (Slotting)", _GRP_FIN_COLL_COMP),
    COREPColumn("0110", _LBL_COL_EXPOSURE_VALUE_LC, _GRP_EXPOSURE_VALUE),
    COREPColumn("0120", _LBL_COL_OF_WHICH_OFF_BS, _GRP_EXPOSURE_VALUE),
    COREPColumn("0125", "  Of which: defaulted", _GRP_EXPOSURE_VALUE),  # New in B3.1
    COREPColumn("0130", "  Of which: arising from CCR", _GRP_EXPOSURE_VALUE),
    COREPColumn("0140", _LBL_COL_OF_WHICH_LARGE_FSE, _GRP_EXPOSURE_VALUE),
    COREPColumn("0150", "Guarantees", _GRP_CRM_LGD_UNFUNDED),
    COREPColumn("0160", "Credit derivatives", _GRP_CRM_LGD_UNFUNDED),
    COREPColumn("0170", "Other funded credit protection", _GRP_CRM_LGD_FUNDED),
    COREPColumn("0171", "  Cash on deposit", _GRP_CRM_LGD_FUNDED),
    COREPColumn("0172", "  Life insurance policies", _GRP_CRM_LGD_FUNDED),
    COREPColumn("0173", "  Instruments held by a third party", _GRP_CRM_LGD_FUNDED),
    COREPColumn("0180", "Eligible financial collateral", _GRP_CRM_LGD_FUNDED),
    COREPColumn("0190", "  Other eligible collateral: Real estate", _GRP_CRM_LGD_FUNDED),
    COREPColumn("0200", "  Other eligible collateral: Other physical", _GRP_CRM_LGD_FUNDED),
    COREPColumn("0210", "  Other eligible collateral: Receivables", _GRP_CRM_LGD_FUNDED),
    # 0220 removed: double default treatment removed in Basel 3.1
    COREPColumn("0230", _LBL_COL_EW_AVG_LGD, "Parameters"),
    COREPColumn("0240", "  For large financial sector entities", "Parameters"),
    COREPColumn("0250", "Exposure-weighted average maturity (days)", "Parameters"),
    COREPColumn("0251", "RWEA pre adjustments", "RWEA"),  # New in B3.1
    COREPColumn("0252", "Adjustment due to post-model adjustments", "RWEA"),  # New
    COREPColumn("0253", "Adjustment due to mortgage RW floor", "RWEA"),  # New
    COREPColumn("0254", "Unrecognised exposure adjustments", "RWEA"),  # New
    # 0255-0257 removed: supporting factors don't exist under Basel 3.1
    COREPColumn("0260", "RWEA after adjustments", "RWEA"),  # Changed name
    COREPColumn("0265", "  Of which: defaulted", "RWEA"),  # New in B3.1
    COREPColumn("0270", _LBL_COL_OF_WHICH_LARGE_FSE, "RWEA"),
    COREPColumn("0275", "Non-modelled approaches: exposure value", _GRP_OUTPUT_FLOOR),  # New
    COREPColumn("0276", "Non-modelled approaches: RWEA", _GRP_OUTPUT_FLOOR),  # New
    COREPColumn("0280", "Expected loss amount (pre post-model adj)", "Memorandum"),  # Changed
    COREPColumn(
        "0281", "Adjustment to EL due to post-model adjustments", "Memorandum"
    ),  # New in B3.1
    COREPColumn("0282", "Expected loss amount after post-model adjustments", "Memorandum"),  # New
    COREPColumn("0290", _LBL_COL_VALUE_ADJUSTMENTS, "Memorandum"),
    COREPColumn("0300", _LBL_COL_NUM_OBLIGORS, "Memorandum"),
    COREPColumn("0310", "Pre-credit derivatives RWEA", "Memorandum"),
]


# =============================================================================
# C 08.01 / OF 08.01 — IRB ROW SECTIONS
# =============================================================================

CRR_IRB_ROW_SECTIONS: list[RowSection] = [
    RowSection(
        "Total and Supporting Factors",
        [
            COREPRow("0010", _LBL_ROW_TOTAL_EXPOSURES_UC),
            COREPRow("0015", "of which: Exposures subject to SME-supporting factor"),
            COREPRow("0016", "of which: Exposures subject to infrastructure supporting factor"),
        ],
    ),
    RowSection(
        _SEC_BREAKDOWN_EXPOSURE_TYPES,
        [
            COREPRow("0020", "On balance sheet items subject to credit risk"),
            COREPRow("0030", "Off balance sheet items subject to credit risk"),
            COREPRow("0040", _LBL_ROW_SFT_NETTING),
            COREPRow("0050", _LBL_ROW_DERIV_LST_NETTING),
            COREPRow("0060", _LBL_ROW_CCP_NETTING),
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
            COREPRow("0010", _LBL_ROW_TOTAL_EXPOSURES_UC),
            COREPRow("0017", "of which: revolving loan commitments"),  # New in B3.1
            # 0015, 0016 removed: supporting factors don't exist under Basel 3.1
        ],
    ),
    RowSection(
        _SEC_BREAKDOWN_EXPOSURE_TYPES,
        [
            COREPRow("0020", "On balance sheet items subject to credit risk"),
            COREPRow("0030", "Off balance sheet items subject to credit risk"),
            COREPRow("0031", "  of which: off-BS by CCF 10%"),  # New in B3.1
            COREPRow("0032", "  of which: off-BS by CCF 20%"),
            COREPRow("0033", "  of which: off-BS by CCF 40%"),
            COREPRow("0034", "  of which: off-BS by CCF 50%"),
            COREPRow("0035", "  of which: off-BS by CCF 100%"),
            COREPRow("0040", _LBL_ROW_SFT_NETTING),
            COREPRow("0050", _LBL_ROW_DERIV_LST_NETTING),
            COREPRow("0060", _LBL_ROW_CCP_NETTING),
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
    COREPColumn("0005", "Obligor grade row identifier", _GRP_INTERNAL_RATING),
    *CRR_C08_COLUMNS,
]

B31_C08_02_COLUMNS: list[COREPColumn] = [
    COREPColumn("0005", "Obligor grade row identifier", _GRP_INTERNAL_RATING),
    # PD column 0010 is retained in OF 08.02 (removed from OF 08.01 totals only)
    COREPColumn("0010", "PD assigned to obligor grade or pool (%)", _GRP_INTERNAL_RATING),
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
    COREPColumn("0060", _LBL_COL_NUM_OBLIGORS, "Obligors"),
    COREPColumn("0070", _LBL_COL_EW_AVG_LGD, "LGD"),
    COREPColumn("0080", _LBL_COL_EW_AVG_MATURITY_YRS, "Maturity"),
    COREPColumn("0090", _LBL_COL_RWEA_SPACE_SUFFIX, "RWEA"),
    COREPColumn("0100", _LBL_COL_EXPECTED_LOSS, "EL"),
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
    COREPColumn("0060", _LBL_COL_NUM_OBLIGORS, "Obligors"),
    COREPColumn("0070", _LBL_COL_EW_AVG_LGD, "LGD"),
    COREPColumn("0080", _LBL_COL_EW_AVG_MATURITY_YRS, "Maturity"),
    COREPColumn("0090", _LBL_COL_RWEA_SPACE_SUFFIX, "RWEA"),
    COREPColumn("0100", _LBL_COL_EXPECTED_LOSS, "EL"),
    COREPColumn("0110", "Value adjustments and provisions", "Provisions"),
]

C08_03_COLUMN_REFS: list[str] = [c.ref for c in CRR_C08_03_COLUMNS]


# =============================================================================
# C 08.05 / OF 08.05 — IRB PD BACKTESTING
# =============================================================================

# C 08.05 / OF 08.05 provides PD backtesting analysis per IRB exposure class.
# Uses the same 17 fixed regulatory PD range buckets as C 08.03.
# One submission per IRB exposure class. Slotting exposures are excluded.
#
# 5 columns:
#   0010: Arithmetic average PD (%) — CRR: as-is; B31: post-input floor
#   0020: Number of obligors at end of previous year
#   0030: Of which: defaulted during the year
#   0040: Observed average default rate (%)
#   0050: Average historical annual default rate (%)
#
# Cols 0020 and 0050 require historical data. When historical data is not
# available from the pipeline, these columns are populated from current-period
# data as best-effort approximations:
#   - Col 0020 uses current-period obligor count (no prior-year data)
#   - Col 0050 uses current observed default rate (no multi-year lookback)
#
# Basel 3.1 distinction: Row allocation uses pre-input-floor PD
# (same as OF 08.03). Col 0010 reports the arithmetic average of the
# post-input-floor PD values (not exposure-weighted, unlike C 08.03 col 0050).
#
# References:
# - CRR Art. 180 (PD validation requirements)
# - Regulation (EU) 2021/451, Annex I (C 08.05 template layout)
# - Regulation (EU) 2021/451, Annex II (C 08.05 reporting instructions)
# - PRA PS1/26, Annex I (OF 08.05 template layout)
# - PRA PS1/26, Annex II (OF 08.05 reporting instructions)

CRR_C08_05_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", "Arithmetic average PD (%)", "PD"),
    COREPColumn("0020", "Number of obligors at end of previous year", "Obligors"),
    COREPColumn("0030", "Of which: defaulted during the year", "Defaults"),
    COREPColumn("0040", "Observed average default rate (%)", "Default Rate"),
    COREPColumn("0050", "Average historical annual default rate (%)", "Historical Rate"),
]

# OF 08.05 (Basel 3.1) has the same 5 columns but col 0010 clarifies
# that the average PD is post-input-floor.
B31_C08_05_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", "Arithmetic average PD (%) (post input floor)", "PD"),
    COREPColumn("0020", "Number of obligors at end of previous year", "Obligors"),
    COREPColumn("0030", "Of which: defaulted during the year", "Defaults"),
    COREPColumn("0040", "Observed average default rate (%)", "Default Rate"),
    COREPColumn("0050", "Average historical annual default rate (%)", "Historical Rate"),
]

C08_05_COLUMN_REFS: list[str] = [c.ref for c in CRR_C08_05_COLUMNS]


def get_c08_05_columns(framework: str = "CRR") -> list[COREPColumn]:
    """Return the C 08.05 / OF 08.05 column definitions for the given framework.

    C 08.05 (CRR) and OF 08.05 (Basel 3.1) have identical column structure
    but differ in col 0010 naming: B31 clarifies "post input floor".
    """
    return B31_C08_05_COLUMNS if framework == "BASEL_3_1" else CRR_C08_05_COLUMNS


# =============================================================================
# C 08.04 / OF 08.04 — IRB RWEA FLOW STATEMENTS
# =============================================================================

# C 08.04 reports quarter-over-quarter movements in IRB RWEA, decomposed into
# seven standardised driver categories. Submitted once per IRB exposure class.
# Excludes CCR exposures.
#
# CRR: 1 column (RWEA "after supporting factors"), 9 rows (0010-0090).
# Basel 3.1: 1 column (RWEA — supporting factors removed), identical 9 rows.
#
# Why: Flow statements explain RWEA movements to supervisors. The 7 driver
# categories (asset size, quality, model updates, methodology, acquisitions,
# FX, other) provide structured attribution of capital requirement changes.
#
# References:
# - Regulation (EU) 2021/451, Annex I (C 08.04 template layout)
# - Regulation (EU) 2021/451, Annex II (C 08.04 reporting instructions)
# - PRA PS1/26, Annex I (OF 08.04 template layout)

CRR_C08_04_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", "Risk-weighted exposure amount (after supporting factors)", "RWEA"),
]

B31_C08_04_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", _LBL_COL_RWEA_HYPHEN, "RWEA"),
]

C08_04_COLUMN_REFS: list[str] = [c.ref for c in CRR_C08_04_COLUMNS]

# 9 rows: opening balance, 7 movement drivers, closing balance.
# Identical between CRR and Basel 3.1.
C08_04_ROWS: list[COREPRow] = [
    COREPRow("0010", "RWEA at the end of the previous reporting period"),
    COREPRow("0020", "Asset size (+/-)"),
    COREPRow("0030", "Asset quality (+/-)"),
    COREPRow("0040", "Model updates (+/-)"),
    COREPRow("0050", "Methodology and policy (+/-)"),
    COREPRow("0060", "Acquisitions and disposals (+/-)"),
    COREPRow("0070", "Foreign exchange movements (+/-)"),
    COREPRow("0080", "Other (+/-)"),
    COREPRow("0090", "RWEA at the end of the reporting period"),
]


def get_c08_04_columns(framework: str = "CRR") -> list[COREPColumn]:
    """Return the C 08.04 / OF 08.04 column definitions for the given framework.

    C 08.04 (CRR) and OF 08.04 (Basel 3.1) differ only in col 0010 naming:
    CRR includes "after supporting factors", Basel 3.1 does not (Art 501/501a removed).
    """
    return B31_C08_04_COLUMNS if framework == "BASEL_3_1" else CRR_C08_04_COLUMNS


# =============================================================================
# OF 02.01 — OUTPUT FLOOR COMPARISON (Basel 3.1 only, PRA PS1/26 Art. 92)
# =============================================================================

# OF 02.01 compares modelled (U-TREA) vs standardised (S-TREA) risk exposure
# amounts by risk type. Basel 3.1 only — no CRR equivalent.
# Reference: PRA PS1/26 Art. 92 para 2A/3A, PRA COREP reporting framework

OF_02_01_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", "Total risk exposure amount (modelled approaches)", "Comparison"),
    COREPColumn("0020", "Total risk exposure amount (standardised approaches)", "Comparison"),
    COREPColumn("0030", "U-TREA", _GRP_OUTPUT_FLOOR),
    COREPColumn("0040", "S-TREA", _GRP_OUTPUT_FLOOR),
]

OF_02_01_ROW_SECTIONS: list[RowSection] = [
    RowSection(
        "Risk Type Breakdown",
        [
            COREPRow("0010", _LBL_ROW_CREDIT_RISK_EXCL_CCR),
            COREPRow("0020", "Counterparty credit risk"),
            COREPRow("0030", "Credit valuation adjustment risk"),
            COREPRow("0040", "Securitisation positions in the non-trading book"),
            COREPRow("0050", "Market risk"),
            COREPRow("0060", _LBL_ROW_OP_RISK),
            COREPRow("0070", "Other"),
            COREPRow("0080", "Total"),
        ],
    ),
]

OF_02_01_COLUMN_REFS: list[str] = [c.ref for c in OF_02_01_COLUMNS]


# =============================================================================
# C 08.06 / OF 08.06 — IRB SPECIALISED LENDING SLOTTING
# =============================================================================

# C 08.06 reports specialised lending exposures under the supervisory slotting
# criteria (CRR Art. 153(5)). Submitted once per SL type. Rows break down by
# slotting category (1–5: Strong/Good/Satisfactory/Weak/Default) × maturity band
# (< 2.5 years / ≥ 2.5 years).
#
# CRR: 4 SL types (PF, IPRE+HVCRE combined, OF, CF), 12 rows, 10 columns.
# Basel 3.1: 5 SL types (HVCRE separated from IPRE), 14 rows (adds
# "substantially stronger" sub-rows 0015/0025), 11 columns (adds col 0031
# FCCM deduction; supporting factors removed from RWEA label).
#
# References:
# - CRR Art. 153(5) (slotting criteria), Regulation (EU) 2021/451 Annex I
# - PRA PS1/26 Art. 153(5) Table A (slotting risk weights)
# - PRA PS1/26 Annex I (OF 08.06 template layout)
# - PRA PS1/26 Annex II (OF 08.06 reporting instructions)

CRR_C08_06_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", _LBL_COL_ORIG_EXPOSURE, "Exposure"),
    COREPColumn("0020", "Exposure after CRM substitution effects pre CCFs", "Post-CRM"),
    COREPColumn("0030", "Of which: off-balance sheet items (original)", "Exposure"),
    COREPColumn("0040", _LBL_COL_EXPOSURE_VALUE_LC, _GRP_EXPOSURE_VALUE),
    COREPColumn("0050", "Of which: off-balance sheet items (exposure value)", _GRP_EXPOSURE_VALUE),
    COREPColumn("0060", "Of which: arising from counterparty credit risk", _GRP_EXPOSURE_VALUE),
    COREPColumn("0070", "Risk weight", "Parameters"),
    COREPColumn("0080", "Risk-weighted exposure amount after supporting factors", "RWEA"),
    COREPColumn("0090", _LBL_COL_EXPECTED_LOSS, "Memorandum"),
    COREPColumn("0100", _LBL_COL_VALUE_ADJUSTMENTS, "Memorandum"),
]

B31_C08_06_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", _LBL_COL_ORIG_EXPOSURE, "Exposure"),
    COREPColumn("0020", "Exposure after CRM substitution effects pre CCFs", "Post-CRM"),
    COREPColumn("0030", "Of which: off-balance sheet items (original)", "Exposure"),
    COREPColumn("0031", "(-) Change in exposure due to FCCM", _GRP_FIN_COLL_COMP),  # New in B3.1
    COREPColumn("0040", _LBL_COL_EXPOSURE_VALUE_LC, _GRP_EXPOSURE_VALUE),
    COREPColumn("0050", "Of which: off-balance sheet items (exposure value)", _GRP_EXPOSURE_VALUE),
    COREPColumn("0060", "Of which: arising from counterparty credit risk", _GRP_EXPOSURE_VALUE),
    COREPColumn("0070", "Risk weight", "Parameters"),
    COREPColumn("0080", _LBL_COL_RWEA_HYPHEN, "RWEA"),  # No "after supporting factors"
    COREPColumn("0090", _LBL_COL_EXPECTED_LOSS, "Memorandum"),
    COREPColumn("0100", _LBL_COL_VALUE_ADJUSTMENTS, "Memorandum"),
]

C08_06_COLUMN_REFS: list[str] = [c.ref for c in CRR_C08_06_COLUMNS]

# Row definitions for C 08.06 / OF 08.06.
# Each tuple: (row_ref, category_label, is_short_maturity, risk_weight_display)
# is_short_maturity: True = < 2.5 years, False = >= 2.5 years, None = total

# CRR: 12 rows (5 categories × 2 maturity bands + 2 totals)
CRR_C08_06_ROWS: list[tuple[str, str, bool | None, str]] = [
    ("0010", _LBL_SLOT_CAT1, True, "50%"),
    ("0020", _LBL_SLOT_CAT1, False, "70%"),
    ("0030", _LBL_SLOT_CAT2, True, "70%"),
    ("0040", _LBL_SLOT_CAT2, False, "90%"),
    ("0050", _LBL_SLOT_CAT3, True, "115%"),
    ("0060", _LBL_SLOT_CAT3, False, "115%"),
    ("0070", _LBL_SLOT_CAT4, True, "250%"),
    ("0080", _LBL_SLOT_CAT4, False, "250%"),
    ("0090", _LBL_SLOT_CAT5, True, "0%"),
    ("0100", _LBL_SLOT_CAT5, False, "0%"),
    ("0110", "Total", True, ""),
    ("0120", "Total", False, ""),
]

# Basel 3.1: 14 rows (adds "substantially stronger" sub-rows 0015 and 0025).
# Sub-rows 0015/0025 are subsets of parent rows 0020/0040 respectively (not
# mutually exclusive — sub-row exposures also appear in the parent row).
B31_C08_06_ROWS: list[tuple[str, str, bool | None, str]] = [
    ("0010", _LBL_SLOT_CAT1, True, "50%"),
    ("0015", "Category 1 (Strong) — substantially stronger", False, "50%"),
    ("0020", _LBL_SLOT_CAT1, False, "70%"),
    ("0030", _LBL_SLOT_CAT2, True, "70%"),
    ("0025", "Category 2 (Good) — substantially stronger", False, "70%"),
    ("0040", _LBL_SLOT_CAT2, False, "90%"),
    ("0050", _LBL_SLOT_CAT3, True, "115%"),
    ("0060", _LBL_SLOT_CAT3, False, "115%"),
    ("0070", _LBL_SLOT_CAT4, True, "250%"),
    ("0080", _LBL_SLOT_CAT4, False, "250%"),
    ("0090", _LBL_SLOT_CAT5, True, "0%"),
    ("0100", _LBL_SLOT_CAT5, False, "0%"),
    ("0110", "Total", True, ""),
    ("0120", "Total", False, ""),
]

# Category name → slotting_category pipeline value mapping
C08_06_CATEGORY_MAP: dict[str, str] = {
    _LBL_SLOT_CAT1: "strong",
    "Category 1 (Strong) — substantially stronger": "strong",
    _LBL_SLOT_CAT2: "good",
    "Category 2 (Good) — substantially stronger": "good",
    _LBL_SLOT_CAT3: "satisfactory",
    _LBL_SLOT_CAT4: "weak",
    _LBL_SLOT_CAT5: "default",
}

# SL type filter values — maps sl_type pipeline values to display names.
# CRR combines IPRE+HVCRE; Basel 3.1 separates them.
CRR_SL_TYPES: dict[str, str] = {
    "project_finance": "Project finance",
    "ipre": "Income-producing real estate (incl. HVCRE)",
    "object_finance": "Object finance",
    "commodities_finance": "Commodities finance",
}

B31_SL_TYPES: dict[str, str] = {
    "project_finance": "Project finance",
    "ipre": "Income-producing real estate",
    "hvcre": "High-volatility commercial real estate",
    "object_finance": "Object finance",
    "commodities_finance": "Commodities finance",
}


def get_c08_06_columns(framework: str = "CRR") -> list[COREPColumn]:
    """Return the C 08.06 / OF 08.06 column definitions for the given framework."""
    return B31_C08_06_COLUMNS if framework == "BASEL_3_1" else CRR_C08_06_COLUMNS


def get_c08_06_rows(framework: str = "CRR") -> list[tuple[str, str, bool | None, str]]:
    """Return the C 08.06 / OF 08.06 row definitions for the given framework."""
    return B31_C08_06_ROWS if framework == "BASEL_3_1" else CRR_C08_06_ROWS


def get_c08_06_sl_types(framework: str = "CRR") -> dict[str, str]:
    """Return the SL type filter values for the given framework."""
    return B31_SL_TYPES if framework == "BASEL_3_1" else CRR_SL_TYPES


# =============================================================================
# C 08.07 / OF 08.07 — IRB SCOPE OF USE
# =============================================================================
#
# CRR C 08.07: 5 columns (0010-0050) — exposure values and coverage percentages.
# Basel 3.1 OF 08.07: 18 columns (0010-0180) — adds RWEA decomposition by
# SA-use reason (cols 0060-0140), IRB RWEA (0150), and materiality (0160-0180).
#
# Rows: CRR uses Art. 147(2) exposure classes (0010-0170, 17 rows).
# Basel 3.1 uses Art. 147B roll-out classes (0180-0260, 9 rows) plus
# materiality percentage row (0270).
#
# References:
# - CRR Art. 147(2) (IRB exposure classes)
# - CRR Art. 148 (roll-out plans), Art. 150 (permanent partial use)
# - PRA PS1/26 Art. 147B (roll-out classes), Art. 150(1A) (materiality)

CRR_C08_07_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", "Total exposure value subject to IRB", "Exposure"),
    COREPColumn("0020", "Total exposure value subject to SA and IRB", "Exposure"),
    COREPColumn("0030", "% subject to permanent partial use of SA", _GRP_COVERAGE_PCT),
    COREPColumn("0040", "% subject to a roll-out plan", _GRP_COVERAGE_PCT),
    COREPColumn("0050", "% subject to IRB approach", _GRP_COVERAGE_PCT),
]

B31_C08_07_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", "Total exposure value subject to IRB (Art 166A-166D)", "Exposure"),
    COREPColumn("0020", "Total exposure value subject to SA and IRB", "Exposure"),
    COREPColumn("0030", "% subject to permanent partial use of SA", _GRP_COVERAGE_PCT),
    COREPColumn("0040", "% subject to a roll-out plan", _GRP_COVERAGE_PCT),
    COREPColumn("0050", "% subject to IRB approach", _GRP_COVERAGE_PCT),
    COREPColumn("0060", "Total RWEA for exposures subject to SA or IRB", "RWEA"),
    COREPColumn(
        "0070", "RWEA for SA: connected counterparties (Art 150(1)(e))", _GRP_RWEA_SA_BREAKDOWN
    ),
    COREPColumn(
        "0080",
        "RWEA for SA: roll-out class — SA does not result in lower capital",
        _GRP_RWEA_SA_BREAKDOWN,
    ),
    COREPColumn(
        "0090", "RWEA for SA: roll-out class — cannot reasonably model", _GRP_RWEA_SA_BREAKDOWN
    ),
    COREPColumn("0100", "RWEA for SA: roll-out class — immaterial", _GRP_RWEA_SA_BREAKDOWN),
    COREPColumn(
        "0110", "RWEA for SA: exposure type — cannot reasonably model", _GRP_RWEA_SA_BREAKDOWN
    ),
    COREPColumn(
        "0120", "RWEA for SA: exposure type — immaterial in aggregate", _GRP_RWEA_SA_BREAKDOWN
    ),
    COREPColumn("0130", "RWEA for SA: due to roll-out plan", _GRP_RWEA_SA_BREAKDOWN),
    COREPColumn("0140", "RWEA for SA: other", _GRP_RWEA_SA_BREAKDOWN),
    COREPColumn("0150", "RWEA for exposures subject to IRB", "RWEA"),
    COREPColumn("0160", "Materiality of roll-out class (Art 150(1A)(c))", "Materiality"),
    COREPColumn("0170", "% subject to permanent partial use (type)", "Materiality"),
    COREPColumn(
        "0180", "% subject to permanent partial use (immaterial in aggregate)", "Materiality"
    ),
]

C08_07_COLUMN_REFS: list[str] = [c.ref for c in CRR_C08_07_COLUMNS]
B31_C08_07_COLUMN_REFS: list[str] = [c.ref for c in B31_C08_07_COLUMNS]

# CRR C 08.07 rows: Art. 147(2) exposure classes (17 rows)
# Tuples: (row_ref, display_name, exposure_class_value or None for sub-rows)
CRR_C08_07_ROWS: list[tuple[str, str, str | None]] = [
    ("0010", _LBL_SA_CENTRAL_GOVT, "central_govt_central_bank"),
    ("0020", "Of which: regional governments or local authorities", "rgla"),
    ("0030", "Of which: public sector entities", "pse"),
    ("0040", "Institutions", "institution"),
    ("0050", "Corporates", "corporate"),
    ("0060", "Of which: specialised lending, excluding slotting", None),
    ("0070", "Of which: specialised lending, including slotting", "specialised_lending"),
    ("0080", "Of which: SMEs", "corporate_sme"),
    ("0090", "Retail", None),
    ("0100", "Of which: secured by RE — SMEs", None),
    ("0110", "Of which: secured by RE — non-SMEs", "retail_mortgage"),
    ("0120", "Of which: qualifying revolving", "retail_qrre"),
    ("0130", "Of which: other SMEs", None),
    ("0140", "Of which: other non-SMEs", "retail_other"),
    ("0150", "Equity", "equity"),
    ("0160", "Other non-credit obligation assets", "other"),
    ("0170", "Total", None),
]

# Basel 3.1 OF 08.07 rows: Art. 147B roll-out classes (9 rows + materiality)
B31_C08_07_ROWS: list[tuple[str, str, str | None]] = [
    ("0180", "Sovereign and central bank", "central_govt_central_bank"),
    ("0190", "Institutions", "institution"),
    ("0200", "Corporate — other", "corporate"),
    ("0210", "Corporate — specialised lending (excl. slotting)", None),
    ("0220", "Corporate — specialised lending (slotting)", "specialised_lending"),
    ("0230", "Corporate — SME", "corporate_sme"),
    ("0240", "Retail — secured by immovable property", "retail_mortgage"),
    ("0250", "Retail — qualifying revolving", "retail_qrre"),
    ("0260", "Retail — other", "retail_other"),
    ("0270", "Total", None),
    ("0280", "Aggregate immateriality %", None),
]

# Exposure classes that count as "retail" for row aggregation in CRR rows 0090-0140
C08_07_CRR_RETAIL_CLASSES: frozenset[str] = frozenset(
    {
        "retail_mortgage",
        "retail_qrre",
        "retail_other",
    }
)

# Exposure classes that count as IRB approaches (not SA)
C08_07_IRB_APPROACHES: frozenset[str] = frozenset(
    {
        "foundation_irb",
        "advanced_irb",
        "slotting",
    }
)


def get_c08_07_columns(framework: str = "CRR") -> list[COREPColumn]:
    """Return the C 08.07 / OF 08.07 column definitions for the given framework."""
    return B31_C08_07_COLUMNS if framework == "BASEL_3_1" else CRR_C08_07_COLUMNS


def get_c08_07_rows(framework: str = "CRR") -> list[tuple[str, str, str | None]]:
    """Return the C 08.07 / OF 08.07 row definitions for the given framework."""
    return B31_C08_07_ROWS if framework == "BASEL_3_1" else CRR_C08_07_ROWS


# =============================================================================
# BACKWARD COMPATIBILITY ALIASES
# These are used by the current generator (pre-Task 1B) and will be removed
# when the generator is rewritten.
# =============================================================================

# Old 9-column C 07.00 definition — used by generator until Task 1B rewrites it.
C07_COLUMNS: list[COREPColumn] = [
    COREPColumn("010", _LBL_COL_ORIG_EXPOSURE),
    COREPColumn("020", _LBL_COL_VALUE_ADJUSTMENTS),
    COREPColumn("030", "Exposure net of value adjustments and provisions"),
    COREPColumn("040", "(-) Funded credit protection (collateral)"),
    COREPColumn("050", "(-) Unfunded credit protection (guarantees)"),
    COREPColumn("060", "Net exposure after CRM substitution effects"),
    COREPColumn("070", "Exposure value (E*) post CCF"),
    COREPColumn("080", _LBL_COL_RWEA_SPACE_SUFFIX),
    COREPColumn("090", _LBL_COL_OF_WHICH_ECAI),
]

# Old 11-column C 08.01 definition — used by generator until Task 1B rewrites it.
C08_01_COLUMNS: list[COREPColumn] = [
    COREPColumn("010", "Weighted average PD (%)"),
    COREPColumn("020", _LBL_COL_ORIG_EXPOSURE),
    COREPColumn("030", _LBL_COL_VALUE_ADJUSTMENTS),
    COREPColumn("040", "Exposure value (EAD)"),
    COREPColumn("050", _LBL_COL_EW_AVG_LGD),
    COREPColumn("060", _LBL_COL_EW_AVG_MATURITY_YRS),
    COREPColumn("070", _LBL_COL_RWEA_SPACE_SUFFIX),
    COREPColumn("080", _LBL_COL_EXPECTED_LOSS),
    COREPColumn("090", "(-) Provisions allocated"),
    COREPColumn("100", _LBL_COL_NUM_OBLIGORS),
    COREPColumn("110", "EL shortfall (-)  / excess (+)"),
]

# =============================================================================
# C 02.00 / OF 02.00 — OWN FUNDS REQUIREMENTS (CA2)
# =============================================================================

# C 02.00 (CRR) / OF 02.00 (Basel 3.1) is the master capital template that
# aggregates RWEA across all risk types. It is the template where the output
# floor is applied at total capital level.
#
# CRR: 1 column (col 0010 — all approaches).
# Basel 3.1: 3 columns — col 0010 (all approaches / U-TREA), col 0020
# (SA-only RWEA for floor comparison), col 0030 (output floor RWEA after
# applying floor multiplier and OF-ADJ per Art. 92).
#
# Rows cover credit risk (SA, F-IRB, A-IRB, slotting, equity), CCR, CVA,
# securitisation, market risk, and operational risk. This calculator only
# populates credit risk rows; all other risk-type rows are null.
#
# Basel 3.1 adds three indicator rows: 0034 (floor activated Yes/No),
# 0035 (floor multiplier %), 0036 (OF-ADJ monetary value).
#
# References:
# - CRR Art. 92 (own funds requirements)
# - PRA PS1/26 Art. 92 para 2A/3A/5 (output floor)
# - Regulation (EU) 2021/451 Annex I (CRR C 02.00 layout)
# - PRA PS1/26 Annex I (OF 02.00 layout)

CRR_C02_00_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", "Amount", "Own Funds Requirements"),
]

B31_C02_00_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", "All approaches (U-TREA components)", "Own Funds Requirements"),
    COREPColumn("0020", "Standardised approaches only (S-TREA components)", "Floor Comparison"),
    COREPColumn("0030", "Output floor (after floor multiplier and OF-ADJ)", _GRP_OUTPUT_FLOOR),
]

# --- CRR C 02.00 Row Sections ---
# Rows cover the complete own funds requirements structure. Only the credit risk
# section is populated by this calculator; market/op risk rows are null. CCR has no
# row of its own: Annex II folds it into 0050 and its SA child 0060 (c02.py::_SA_APPROACHES).

CRR_C02_00_ROW_SECTIONS: list[RowSection] = [
    RowSection(
        "Total and Credit Risk",
        [
            COREPRow("0010", "TOTAL RISK EXPOSURE AMOUNT"),
            COREPRow("0040", "TOTAL OWN FUNDS REQUIREMENTS"),
            # Credit, counterparty credit and dilution risk
            COREPRow("0050", _LBL_ROW_CREDIT_CCR_DILUTION_FREE_DELIV),
            COREPRow("0060", "Of which: Standardised Approach (SA)"),
            COREPRow("0070", _LBL_IRB_CENTRAL_GOVT),
            COREPRow("0080", "Regional governments and local authorities"),
            COREPRow("0090", _LBL_SA_PSE),
            COREPRow("0100", _LBL_SA_MDB),
            COREPRow("0110", _LBL_SA_INTL_ORG),
            COREPRow("0120", "Institutions"),
            COREPRow("0130", "Corporates"),
            COREPRow("0140", "Retail"),
            COREPRow("0150", _LBL_SA_MORTGAGES),
            COREPRow("0160", _LBL_SA_DEFAULTED),
            COREPRow("0170", "Higher-risk items"),
            COREPRow("0180", _LBL_SA_COVERED_BOND),
            COREPRow("0190", "Short-term credit assessment"),
            COREPRow("0200", _LBL_ROW_CIU),
            COREPRow("0210", "Equity"),
            COREPRow("0211", _LBL_SA_OTHER),
        ],
    ),
    RowSection(
        "IRB Approach",
        [
            COREPRow("0220", "Of which: IRB Approach"),
            COREPRow("0240", "Of which: Foundation IRB (F-IRB)"),
            COREPRow("0250", "F-IRB — Institutions"),
            COREPRow("0260", "F-IRB — Corporates"),
            COREPRow("0300", "Of which: Advanced IRB (A-IRB)"),
            COREPRow("0310", "A-IRB — Central governments and central banks"),
            COREPRow("0330", "A-IRB — Institutions"),
            COREPRow("0340", "A-IRB — Corporates"),
            COREPRow("0370", "A-IRB — Retail"),
            COREPRow("0380", "A-IRB — Retail, secured by immovable property"),
            COREPRow("0390", "A-IRB — Retail, qualifying revolving (QRRE)"),
            COREPRow("0400", "A-IRB — Retail, other SME"),
            COREPRow("0410", "Supervisory slotting"),
            COREPRow("0420", "Equity IRB"),
        ],
    ),
    RowSection(
        "Other Risk Types",
        [
            COREPRow("0430", "Settlement risk"),
            COREPRow("0440", "Securitisation positions in non-trading book"),
            COREPRow("0460", "Position, foreign exchange and commodities risk"),
            COREPRow("0590", "Credit valuation adjustment (CVA)"),
            COREPRow("0640", _LBL_ROW_OP_RISK),
            COREPRow("0680", "Additional risk exposure: fixed overheads"),
        ],
    ),
]

# --- Basel 3.1 OF 02.00 Row Sections ---
# Extends CRR rows with: F-IRB/A-IRB sub-class breakdowns (new refs 0271,
# 0290, 0295-0297, 0350, 0355-0356, 0382-0385), slotting by SL type
# (0411-0416), SA specialised lending (0131), output floor indicator rows
# (0034-0036), and expanded market/CVA rows.

B31_C02_00_ROW_SECTIONS: list[RowSection] = [
    RowSection(
        "Total and Output Floor",
        [
            COREPRow("0010", "TOTAL RISK EXPOSURE AMOUNT"),
            COREPRow("0034", "Output floor activated"),
            COREPRow("0035", "Output floor multiplier"),
            COREPRow("0036", "Output floor adjustment (OF-ADJ)"),
            COREPRow("0040", "TOTAL OWN FUNDS REQUIREMENTS"),
        ],
    ),
    RowSection(
        "Credit Risk — SA",
        [
            COREPRow("0050", _LBL_ROW_CREDIT_CCR_DILUTION_FREE_DELIV),
            COREPRow("0060", "Of which: Standardised Approach (SA)"),
            COREPRow("0070", _LBL_IRB_CENTRAL_GOVT),
            COREPRow("0080", "Regional governments and local authorities"),
            COREPRow("0090", _LBL_SA_PSE),
            COREPRow("0100", _LBL_SA_MDB),
            COREPRow("0110", _LBL_SA_INTL_ORG),
            COREPRow("0120", "Institutions"),
            COREPRow("0130", "Corporates"),
            COREPRow("0131", "Of which: specialised lending"),
            COREPRow("0140", "Retail"),
            COREPRow("0150", _LBL_SA_MORTGAGES),
            COREPRow("0160", _LBL_SA_DEFAULTED),
            COREPRow("0170", "Higher-risk items"),
            COREPRow("0180", _LBL_SA_COVERED_BOND),
            COREPRow("0190", "Short-term credit assessment"),
            COREPRow("0200", _LBL_ROW_CIU),
            COREPRow("0210", "Equity"),
            COREPRow("0211", _LBL_SA_OTHER),
        ],
    ),
    RowSection(
        "Credit Risk — F-IRB",
        [
            COREPRow("0220", "Of which: IRB Approach"),
            COREPRow("0240", "Of which: Foundation IRB (F-IRB)"),
            COREPRow("0250", "F-IRB — Institutions"),
            COREPRow("0271", "F-IRB — Institutions (detail)"),
            COREPRow("0260", "F-IRB — Corporates"),
            COREPRow("0290", "F-IRB — SL excluding slotting"),
            COREPRow("0295", "F-IRB — Financial and large corporates"),
            COREPRow("0296", "F-IRB — Other general corporates SME"),
            COREPRow("0297", "F-IRB — Other general corporates non-SME"),
        ],
    ),
    RowSection(
        "Credit Risk — A-IRB",
        [
            COREPRow("0300", "Of which: Advanced IRB (A-IRB)"),
            COREPRow("0310", "A-IRB — Central governments and central banks"),
            COREPRow("0330", "A-IRB — Institutions"),
            COREPRow("0340", "A-IRB — Corporates"),
            COREPRow("0350", "A-IRB — SL excluding slotting"),
            COREPRow("0355", "A-IRB — Other general corporates SME"),
            COREPRow("0356", "A-IRB — Other general corporates non-SME"),
            COREPRow("0370", "A-IRB — Retail"),
            COREPRow("0380", "A-IRB — Retail, secured by immovable property"),
            COREPRow("0382", "A-IRB — Retail, residential immovable SME"),
            COREPRow("0383", "A-IRB — Retail, residential immovable non-SME"),
            COREPRow("0384", "A-IRB — Retail, commercial RE SME"),
            COREPRow("0385", "A-IRB — Retail, commercial RE non-SME"),
            COREPRow("0390", "A-IRB — Retail, qualifying revolving (QRRE)"),
            COREPRow("0400", "A-IRB — Retail, other SME"),
            COREPRow("0410", "A-IRB — Retail, other non-SME"),
        ],
    ),
    RowSection(
        "Slotting and Equity",
        [
            COREPRow("0411", "Supervisory slotting"),
            COREPRow("0412", "Slotting — Project finance"),
            COREPRow("0413", "Slotting — Object finance"),
            COREPRow("0414", "Slotting — Commodities finance"),
            COREPRow("0415", "Slotting — IPRE"),
            COREPRow("0416", "Slotting — HVCRE"),
            COREPRow("0420", "Equity IRB"),
        ],
    ),
    RowSection(
        "Other Risk Types",
        [
            COREPRow("0430", "Settlement risk"),
            COREPRow("0440", "Securitisation positions in non-trading book"),
            COREPRow("0460", "Position, foreign exchange and commodities risk"),
            COREPRow("0590", "Credit valuation adjustment (CVA)"),
            COREPRow("0640", _LBL_ROW_OP_RISK),
            COREPRow("0680", "Additional risk exposure: fixed overheads"),
        ],
    ),
    RowSection(
        _SEC_MEMORANDUM_ITEMS,
        [
            # PRA PS1/26 Art. 123B: portfolio-total RWEA of retail/RE exposures
            # that received the 1.5x currency-mismatch multiplier. Memo-only
            # (col 0010 populated; S-TREA / output floor cols left None) and not
            # summed into the TREA total. Basel-3.1-only (absent under CRR).
            COREPRow(
                "0500",
                "Of which: retail/RE subject to currency mismatch multiplier (RWEA)",
            ),
        ],
    ),
]

CRR_C02_00_COLUMN_REFS: list[str] = [c.ref for c in CRR_C02_00_COLUMNS]
B31_C02_00_COLUMN_REFS: list[str] = [c.ref for c in B31_C02_00_COLUMNS]

# Mapping from pipeline approach_applied values to C 02.00 row structure.
# Used by the generator to route RWEA into correct rows.
C02_00_SA_CLASS_MAP: dict[str, str] = {
    "central_government": "0070",
    "regional_government": "0080",
    "public_sector_entity": "0090",
    "multilateral_development_bank": "0100",
    "international_organisation": "0110",
    "institution": "0120",
    "corporate": "0130",
    "retail": "0140",
    "secured_by_property": "0150",
    "defaulted": "0160",
    "higher_risk": "0170",
    "covered_bond": "0180",
    "short_term": "0190",
    "ciu": "0200",
    "equity": "0210",
    "other_items": "0211",
    # Additional SA class aliases
    "retail_mortgage": "0140",
    "retail_qrre": "0140",
    "retail_other": "0140",
    "specialised_lending": "0130",
}

# Rows that are populated from pipeline data (credit risk scope).
# All other rows are null (CCR, market, op risk out of scope).
C02_00_CREDIT_RISK_ROWS: frozenset[str] = frozenset(
    {
        "0010",
        "0040",
        "0050",
        "0060",
        "0070",
        "0080",
        "0090",
        "0100",
        "0110",
        "0120",
        "0130",
        "0131",
        "0140",
        "0150",
        "0160",
        "0170",
        "0180",
        "0190",
        "0200",
        "0210",
        "0211",
        "0220",
        "0240",
        "0250",
        "0260",
        "0271",
        "0290",
        "0295",
        "0296",
        "0297",
        "0300",
        "0310",
        "0330",
        "0340",
        "0350",
        "0355",
        "0356",
        "0370",
        "0380",
        "0382",
        "0383",
        "0384",
        "0385",
        "0390",
        "0400",
        "0410",
        "0411",
        "0412",
        "0413",
        "0414",
        "0415",
        "0416",
        "0420",
        "0034",
        "0035",
        "0036",
        # PRA PS1/26 Art. 123B currency-mismatch memo (B31 OF 02.00 row 0500).
        "0500",
    }
)


# =============================================================================
# C 09.01 / OF 09.01 — GEOGRAPHICAL BREAKDOWN SA
# =============================================================================
# C 09.01 provides a geographical breakdown of SA exposures by country of
# obligor residence. Submitted once at total level and once per material country.
#
# References:
# - Regulation (EU) 2021/451, Annex I/II (C 09.01)
# - PRA PS1/26, Annex I/II (OF 09.01)
# - CRR Art. 112 (SA exposure classes)

CRR_C09_01_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", _LBL_COL_ORIG_EXPOSURE, "Exposure"),
    COREPColumn("0020", "Defaulted exposures", "Exposure"),
    COREPColumn("0040", _LBL_COL_OBSERVED_DEFAULTS, "Defaults"),
    COREPColumn("0050", _LBL_COL_GEN_CRA, "Provisions"),
    COREPColumn("0055", _LBL_COL_SPEC_CRA, "Provisions"),
    COREPColumn("0060", "Write-offs", "Provisions"),
    COREPColumn(
        "0061", "Additional value adjustments and other own funds reductions", "Provisions"
    ),
    COREPColumn("0070", _LBL_COL_CRA_WRITEOFFS, "Provisions"),
    COREPColumn("0075", _LBL_COL_EXPOSURE_VALUE_LC, _GRP_EXPOSURE_VALUE),
    COREPColumn("0080", _LBL_COL_RWEA_PRE_SF, "RWEA"),
    COREPColumn("0081", _LBL_COL_SME_SF_ADJ, "RWEA"),
    COREPColumn("0082", _LBL_COL_INFRA_SF_ADJ, "RWEA"),
    COREPColumn("0090", _LBL_COL_RWEA_POST_SF, "RWEA"),
]

# OF 09.01 (Basel 3.1): removes supporting factor columns 0080-0082
B31_C09_01_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", _LBL_COL_ORIG_EXPOSURE, "Exposure"),
    COREPColumn("0020", "Defaulted exposures", "Exposure"),
    COREPColumn("0040", _LBL_COL_OBSERVED_DEFAULTS, "Defaults"),
    COREPColumn("0050", _LBL_COL_GEN_CRA, "Provisions"),
    COREPColumn("0055", _LBL_COL_SPEC_CRA, "Provisions"),
    COREPColumn("0060", "Write-offs", "Provisions"),
    COREPColumn(
        "0061", "Additional value adjustments and other own funds reductions", "Provisions"
    ),
    COREPColumn("0070", _LBL_COL_CRA_WRITEOFFS, "Provisions"),
    COREPColumn("0075", _LBL_COL_EXPOSURE_VALUE_LC, _GRP_EXPOSURE_VALUE),
    COREPColumn("0090", _LBL_COL_RWEA_HYPHEN, "RWEA"),
]

C09_01_COLUMN_REFS: list[str] = [c.ref for c in CRR_C09_01_COLUMNS]
B31_C09_01_COLUMN_REFS: list[str] = [c.ref for c in B31_C09_01_COLUMNS]

# CRR C 09.01 rows — SA exposure classes for geographical breakdown
CRR_C09_01_ROWS: list[COREPRow] = [
    COREPRow("0010", _LBL_SA_CENTRAL_GOVT, "central_govt_central_bank"),
    COREPRow("0020", _LBL_SA_RGLA, "rgla"),
    COREPRow("0030", _LBL_SA_PSE, "pse"),
    COREPRow("0040", _LBL_SA_MDB, "mdb"),
    COREPRow("0050", _LBL_SA_INTL_ORG, "international_organisation"),
    COREPRow("0060", "Institutions", "institution"),
    COREPRow("0070", "Corporates", "corporate"),
    COREPRow("0075", _LBL_ROW_OF_WHICH_SME_LC, "corporate_sme"),
    COREPRow("0080", "Retail", "retail"),
    COREPRow("0085", _LBL_ROW_OF_WHICH_SME_LC, "retail_sme"),
    COREPRow("0090", _LBL_SA_MORTGAGES, "retail_mortgage"),
    COREPRow("0095", _LBL_ROW_OF_WHICH_SME_LC, "mortgage_sme"),
    COREPRow("0100", _LBL_SA_DEFAULTED, "defaulted"),
    COREPRow("0110", "Items associated with particularly high risk", "high_risk"),
    COREPRow("0120", _LBL_SA_COVERED_BOND, "covered_bond"),
    COREPRow(
        "0130",
        "Claims on institutions and corporates with a short-term credit assessment",
        "short_term",
    ),
    COREPRow("0140", _LBL_ROW_CIU, "ciu"),
    COREPRow("0141", "  Look-through approach", "ciu_look_through"),
    COREPRow("0142", "  Mandate-based approach", "ciu_mandate"),
    COREPRow("0143", "  Fall-back approach", "ciu_fallback"),
    COREPRow("0150", "Equity exposures", "equity"),
    COREPRow("0160", "Other exposures", "other"),
    COREPRow("0170", _LBL_ROW_TOTAL_EXPOSURES_MC, None),
]

# OF 09.01 (Basel 3.1) rows — adds SL sub-rows, restructures RE rows
B31_C09_01_ROWS: list[COREPRow] = [
    COREPRow("0010", _LBL_SA_CENTRAL_GOVT, "central_govt_central_bank"),
    COREPRow("0020", _LBL_SA_RGLA, "rgla"),
    COREPRow("0030", _LBL_SA_PSE, "pse"),
    COREPRow("0040", _LBL_SA_MDB, "mdb"),
    COREPRow("0050", _LBL_SA_INTL_ORG, "international_organisation"),
    COREPRow("0060", "Institutions", "institution"),
    COREPRow("0070", "Corporates", "corporate"),
    COREPRow("0075", _LBL_ROW_OF_WHICH_SME_LC, "corporate_sme"),
    COREPRow("0071", "  of which: specialised lending - object finance", "sl_object_finance"),
    COREPRow(
        "0072", "  of which: specialised lending - commodities finance", "sl_commodities_finance"
    ),
    COREPRow("0073", "  of which: specialised lending - project finance", "sl_project_finance"),
    COREPRow("0080", "Retail", "retail"),
    COREPRow("0085", _LBL_ROW_OF_WHICH_SME_LC, "retail_sme"),
    COREPRow("0090", "Real estate exposures", "real_estate"),
    COREPRow("0095", _LBL_ROW_OF_WHICH_SME_LC, "re_sme"),
    COREPRow("0091", "  of which: regulatory residential real estate", "re_residential"),
    COREPRow("0092", "  of which: regulatory commercial real estate", "re_commercial"),
    COREPRow("0093", "  of which: other real estate", "re_other"),
    COREPRow("0094", "  of which: land acquisition, development and construction", "re_adc"),
    COREPRow("0100", _LBL_SA_DEFAULTED, "defaulted"),
    COREPRow("0110", "Exposures associated with particularly high risk", "high_risk"),
    COREPRow("0120", "Eligible covered bonds", "covered_bond"),
    COREPRow("0140", _LBL_ROW_CIU, "ciu"),
    COREPRow("0141", "  Look-through approach", "ciu_look_through"),
    COREPRow("0142", "  Mandate-based approach", "ciu_mandate"),
    COREPRow("0143", "  Fall-back approach", "ciu_fallback"),
    COREPRow("0150", "Subordinated debt, equity and other own funds instruments", "equity"),
    COREPRow("0160", _LBL_SA_OTHER, "other"),
    COREPRow("0170", _LBL_ROW_TOTAL_EXPOSURES_MC, None),
]


# =============================================================================
# C 09.02 / OF 09.02 — GEOGRAPHICAL BREAKDOWN IRB
# =============================================================================
# C 09.02 provides a geographical breakdown of IRB exposures by country of
# obligor residence, including PD, LGD, and expected loss parameters.
#
# References:
# - Regulation (EU) 2021/451, Annex I/II (C 09.02)
# - PRA PS1/26, Annex I/II (OF 09.02)
# - CRR Art. 147 (IRB exposure classes)

CRR_C09_02_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", _LBL_COL_ORIG_EXPOSURE, "Exposure"),
    COREPColumn("0030", "Of which: defaulted", "Exposure"),
    COREPColumn("0040", _LBL_COL_OBSERVED_DEFAULTS, "Defaults"),
    COREPColumn("0050", _LBL_COL_GEN_CRA, "Provisions"),
    COREPColumn("0055", _LBL_COL_SPEC_CRA, "Provisions"),
    COREPColumn("0060", "Write-offs", "Provisions"),
    COREPColumn("0070", _LBL_COL_CRA_WRITEOFFS, "Provisions"),
    COREPColumn("0080", "PD assigned to the obligor grade or pool (%)", "Parameters"),
    COREPColumn("0090", "Exposure weighted average LGD (%)", "Parameters"),
    COREPColumn("0100", "Of which: defaulted (LGD)", "Parameters"),
    COREPColumn("0105", _LBL_COL_EXPOSURE_VALUE_LC, _GRP_EXPOSURE_VALUE),
    COREPColumn("0110", _LBL_COL_RWEA_PRE_SF, "RWEA"),
    COREPColumn("0120", "Of which: defaulted (RWEA)", "RWEA"),
    COREPColumn("0121", _LBL_COL_SME_SF_ADJ, "RWEA"),
    COREPColumn("0122", _LBL_COL_INFRA_SF_ADJ, "RWEA"),
    COREPColumn("0125", _LBL_COL_RWEA_POST_SF, "RWEA"),
    COREPColumn("0130", _LBL_COL_EXPECTED_LOSS, "Memorandum"),
]

# OF 09.02 (Basel 3.1): adds 0107 (defaulted EV), removes 0110/0121/0122
B31_C09_02_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", _LBL_COL_ORIG_EXPOSURE, "Exposure"),
    COREPColumn("0030", "Of which: defaulted", "Exposure"),
    COREPColumn("0040", _LBL_COL_OBSERVED_DEFAULTS, "Defaults"),
    COREPColumn("0050", _LBL_COL_GEN_CRA, "Provisions"),
    COREPColumn("0055", _LBL_COL_SPEC_CRA, "Provisions"),
    COREPColumn("0060", "Write-offs", "Provisions"),
    COREPColumn("0070", _LBL_COL_CRA_WRITEOFFS, "Provisions"),
    COREPColumn("0080", "PD assigned to the obligor grade or pool (%)", "Parameters"),
    COREPColumn("0090", "Exposure weighted average LGD (%)", "Parameters"),
    COREPColumn("0100", "Of which: defaulted (LGD)", "Parameters"),
    COREPColumn("0105", _LBL_COL_EXPOSURE_VALUE_LC, _GRP_EXPOSURE_VALUE),
    COREPColumn("0107", "Of which: defaulted (exposure value)", _GRP_EXPOSURE_VALUE),
    COREPColumn("0120", "Of which: defaulted (RWEA)", "RWEA"),
    COREPColumn("0125", _LBL_COL_RWEA_HYPHEN, "RWEA"),
    COREPColumn("0130", _LBL_COL_EXPECTED_LOSS, "Memorandum"),
]

C09_02_COLUMN_REFS: list[str] = [c.ref for c in CRR_C09_02_COLUMNS]
B31_C09_02_COLUMN_REFS: list[str] = [c.ref for c in B31_C09_02_COLUMNS]

# CRR C 09.02 rows — IRB exposure classes for geographical breakdown
CRR_C09_02_ROWS: list[COREPRow] = [
    COREPRow("0010", _LBL_SA_CENTRAL_GOVT, "central_govt_central_bank"),
    COREPRow("0020", "Institutions", "institution"),
    COREPRow("0030", "Corporates", "corporate"),
    COREPRow(
        "0042", "  Of which: specialised lending (excl. slotting approach)", "sl_excl_slotting"
    ),
    COREPRow("0045", "  Of which: specialised lending under the slotting approach", "sl_slotting"),
    COREPRow("0050", "  Of which: SME", "corporate_sme"),
    COREPRow("0060", "Retail", "retail"),
    COREPRow("0070", "  Secured by immovable property", "retail_mortgage"),
    COREPRow("0080", "    SME", "retail_mortgage_sme"),
    COREPRow("0090", "    Non-SME", "retail_mortgage_non_sme"),
    COREPRow("0100", "  Qualifying revolving", "retail_qrre"),
    COREPRow("0110", "  Other retail", "retail_other"),
    COREPRow("0120", "    SME", "retail_other_sme"),
    COREPRow("0130", "    Non-SME", "retail_other_non_sme"),
    COREPRow("0140", "Equity", "equity"),
    COREPRow("0150", _LBL_ROW_TOTAL_EXPOSURES_MC, None),
]

# OF 09.02 (Basel 3.1) rows — adds corporate sub-rows, restructures retail RE,
# removes equity
B31_C09_02_ROWS: list[COREPRow] = [
    COREPRow("0010", _LBL_SA_CENTRAL_GOVT, "central_govt_central_bank"),
    COREPRow("0020", "Institutions", "institution"),
    COREPRow("0030", "Corporates", "corporate"),
    COREPRow(
        "0042", "  Of which: specialised lending (excl. slotting approach)", "sl_excl_slotting"
    ),
    COREPRow("0045", "  Of which: specialised lending under the slotting approach", "sl_slotting"),
    COREPRow(
        "0048",
        "  Of which: financial corporates and large corporates (Art 147(4C))",
        "corporate_fse_large",
    ),
    COREPRow(
        "0049", "  Of which: purchased receivables (Art 157)", "corporate_purchased_receivables"
    ),
    COREPRow(
        "0050", "  Of which: other general corporates - SME (Art 147(4E)(c))", "corporate_sme"
    ),
    COREPRow(
        "0055", "  Of which: other general corporates - non-SME (Art 147(4E))", "corporate_non_sme"
    ),
    COREPRow("0060", "Retail", "retail"),
    COREPRow("0071", "  Secured by residential immovable property - SME", "retail_resi_re_sme"),
    COREPRow(
        "0072", "  Secured by residential immovable property - non-SME", "retail_resi_re_non_sme"
    ),
    COREPRow("0073", "  Secured by commercial immovable property - SME", "retail_comm_re_sme"),
    COREPRow(
        "0074", "  Secured by commercial immovable property - non-SME", "retail_comm_re_non_sme"
    ),
    COREPRow("0100", "  Qualifying revolving", "retail_qrre"),
    COREPRow("0105", "  Purchased receivables (Art 157)", "retail_purchased_receivables"),
    COREPRow("0120", "  Other retail - SME", "retail_other_sme"),
    COREPRow("0130", "  Other retail - non-SME", "retail_other_non_sme"),
    COREPRow("0150", _LBL_ROW_TOTAL_EXPOSURES_MC, None),
]

# Mapping from pipeline exposure_class values to C 09.01 row filter keys.
# Sub-rows (SME, RE sub-types, SL sub-types) require additional pipeline fields.
C09_01_SA_CLASS_MAP: dict[str, str] = {
    "central_govt_central_bank": "central_govt_central_bank",
    "rgla": "rgla",
    "pse": "pse",
    "mdb": "mdb",
    "international_organisation": "international_organisation",
    "institution": "institution",
    "corporate": "corporate",
    "corporate_sme": "corporate",
    "retail_other": "retail",
    "retail_qrre": "retail",
    "retail_mortgage": "retail_mortgage",
    "defaulted": "defaulted",
    "high_risk": "high_risk",
    "covered_bond": "covered_bond",
    "equity": "equity",
    "other": "other",
    "specialised_lending": "corporate",
}

# Mapping from pipeline exposure_class values to C 09.02 row filter keys.
C09_02_IRB_CLASS_MAP: dict[str, str] = {
    "central_govt_central_bank": "central_govt_central_bank",
    "institution": "institution",
    "corporate": "corporate",
    "corporate_sme": "corporate",
    "specialised_lending": "corporate",
    "retail_mortgage": "retail",
    "retail_qrre": "retail",
    "retail_other": "retail",
    "equity": "equity",
}


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


def get_c02_00_columns(framework: str = "CRR") -> list[COREPColumn]:
    """Return the C 02.00 / OF 02.00 column definitions for the given framework."""
    return B31_C02_00_COLUMNS if framework == "BASEL_3_1" else CRR_C02_00_COLUMNS


def get_c02_00_row_sections(framework: str = "CRR") -> list[RowSection]:
    """Return the C 02.00 / OF 02.00 row sections for the given framework."""
    return B31_C02_00_ROW_SECTIONS if framework == "BASEL_3_1" else CRR_C02_00_ROW_SECTIONS


def get_c09_01_columns(framework: str = "CRR") -> list[COREPColumn]:
    """Return the C 09.01 / OF 09.01 column definitions for the given framework.

    CRR has 13 columns (incl. supporting factors 0080-0082).
    Basel 3.1 has 10 columns (supporting factors removed).
    """
    return B31_C09_01_COLUMNS if framework == "BASEL_3_1" else CRR_C09_01_COLUMNS


def get_c09_01_rows(framework: str = "CRR") -> list[COREPRow]:
    """Return the C 09.01 / OF 09.01 row definitions for the given framework.

    CRR: 23 rows (standard SA exposure classes).
    Basel 3.1: 29 rows (adds SL sub-rows 0071-0073, RE sub-rows 0091-0094,
    removes short-term row 0130, renames equity/RE rows).
    """
    return B31_C09_01_ROWS if framework == "BASEL_3_1" else CRR_C09_01_ROWS


def get_c09_02_columns(framework: str = "CRR") -> list[COREPColumn]:
    """Return the C 09.02 / OF 09.02 column definitions for the given framework.

    CRR has 17 columns (incl. supporting factors 0110, 0121, 0122).
    Basel 3.1 has 15 columns (adds 0107 defaulted EV, removes 3 supporting
    factor columns).
    """
    return B31_C09_02_COLUMNS if framework == "BASEL_3_1" else CRR_C09_02_COLUMNS


def get_c09_02_rows(framework: str = "CRR") -> list[COREPRow]:
    """Return the C 09.02 / OF 09.02 row definitions for the given framework.

    CRR: 16 rows (incl. equity row 0140).
    Basel 3.1: 19 rows (adds corporate sub-rows 0048/0049/0055, restructures
    retail RE rows, removes equity).
    """
    return B31_C09_02_ROWS if framework == "BASEL_3_1" else CRR_C09_02_ROWS


# =============================================================================
# C 34.01 / C 34.02 / C 34.04 / C 34.08 — COUNTERPARTY CREDIT RISK (CCR)
# =============================================================================

# The C 34 family reports counterparty credit risk (CCR) under the SA-CCR
# exposure measure, per-netting-set EAD, CVA capital, and CCP exposures.
# Both CRR and Basel 3.1 share the same column/row skeleton here — the only
# framework-conditional grid is C 34.04 (CVA), which the generator suppresses
# under CRR because cva_rwa is a Basel-3.1-only output.
#
# Only the four sub-templates in P8.50 scope are defined (01/02/04/08); the
# remaining C 34 grids (03/05/06/07/09/10/11) are out of scope.
#
# References:
# - Regulation (EU) 2021/451, Annex I/II (C 34 CCR template family)
# - CRR Art. 274(2): SA-CCR EAD = alpha * (RC + PFE)
# - CRR Art. 306(1)(a)/(c): 2% / 4% QCCP trade-leg risk weight
# - CRR Art. 308/309: default fund contribution exposures
# - PRA PS1/26 App.1 CVA Part Ch.4.2-4.4 (BA-CVA reduced — C 34.04)

# --- C 34.01: CCR analysis by approach (EAD + RWEA, SA-CCR total) ---
C34_01_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", _LBL_COL_EXPOSURE_VALUE_LC, "CCR"),
    COREPColumn("0020", _LBL_COL_RWEA_HYPHEN, "RWEA"),
]
C34_01_COLUMN_REFS: list[str] = [c.ref for c in C34_01_COLUMNS]

C34_01_ROWS: list[COREPRow] = [
    COREPRow("0010", "SA-CCR (Standardised Approach for Counterparty Credit Risk)"),
]

# --- C 34.02: SA-CCR EAD per netting set (one grid per netting_set_id) ---
C34_02_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", _LBL_COL_EXPOSURE_VALUE_LC, "CCR"),
]
C34_02_COLUMN_REFS: list[str] = [c.ref for c in C34_02_COLUMNS]

C34_02_ROWS: list[COREPRow] = [
    COREPRow("0010", "Netting set exposure value (SA-CCR)"),
]

# --- C 34.04: CVA capital (RWEA_CVA — Basel 3.1 only) ---
C34_04_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", _LBL_COL_RWEA_HYPHEN, "RWEA"),
]
C34_04_COLUMN_REFS: list[str] = [c.ref for c in C34_04_COLUMNS]

C34_04_ROWS: list[COREPRow] = [
    COREPRow("0010", "Total CVA capital charge (BA-CVA)"),
]

# --- C 34.08: CCP exposures (QCCP trade 2%/4%, non-QCCP, default fund) ---
C34_08_COLUMNS: list[COREPColumn] = [
    COREPColumn("0010", _LBL_COL_EXPOSURE_VALUE_LC, "CCR"),
    COREPColumn("0020", _LBL_COL_RWEA_HYPHEN, "RWEA"),
]
C34_08_COLUMN_REFS: list[str] = [c.ref for c in C34_08_COLUMNS]

C34_08_ROWS: list[COREPRow] = [
    COREPRow("0010", "QCCP trade exposures"),
    COREPRow("0020", "Non-QCCP trade exposures"),
    COREPRow("0030", "Default fund contributions"),
]


def get_c34_01_columns() -> list[COREPColumn]:
    """Return the C 34.01 (CCR analysis by approach) column definitions."""
    return C34_01_COLUMNS


def get_c34_02_columns() -> list[COREPColumn]:
    """Return the C 34.02 (SA-CCR EAD per netting set) column definitions."""
    return C34_02_COLUMNS


def get_c34_04_columns() -> list[COREPColumn]:
    """Return the C 34.04 (CVA capital, Basel 3.1) column definitions."""
    return C34_04_COLUMNS


def get_c34_08_columns() -> list[COREPColumn]:
    """Return the C 34.08 (CCP exposures) column definitions."""
    return C34_08_COLUMNS
