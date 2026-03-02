"""
COREP template structure definitions.

Defines the row/column structure for COREP credit risk templates:
- C 07.00: SA exposure class rows, risk weight band columns
- C 08.01: IRB exposure class rows, IRB parameter columns
- C 08.02: IRB PD grade bands for granular reporting

Why: COREP templates have a fixed regulatory format (EBA DPM taxonomy).
These definitions are the single source of truth for template structure,
used by the generator to produce correctly-formatted output.

References:
- Regulation (EU) 2021/451, Annex I (template layouts)
- Regulation (EU) 2021/451, Annex II (reporting instructions)
- CRR Art. 112 (SA exposure classes)
- CRR Art. 147 (IRB exposure classes)
"""

from __future__ import annotations

from dataclasses import dataclass

# =============================================================================
# COREP ROW / COLUMN METADATA
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

    ref: str  # Column reference, e.g. "010"
    name: str  # Display name, e.g. "Original exposure pre conversion factors"


# =============================================================================
# C 07.00 — CR SA (Standardised Approach)
# =============================================================================

# Mapping: ExposureClass.value -> (row_ref, display_name)
# Based on CRR Art. 112 and Regulation (EU) 2021/451, Annex I, C 07.00
SA_EXPOSURE_CLASS_ROWS: dict[str, tuple[str, str]] = {
    "central_govt_central_bank": ("0010", "Central governments or central banks"),
    "rgla": ("0020", "Regional governments or local authorities"),
    "pse": ("0030", "Public sector entities"),
    "mdb": ("0040", "Multilateral development banks"),
    "institution": ("0060", "Institutions"),
    "corporate": ("0070", "Corporates"),
    "corporate_sme": ("0071", "  Of which: SME corporates"),
    "retail_mortgage": ("0080", "Secured by mortgages on immovable property"),
    "retail_other": ("0090", "Retail"),
    "retail_qrre": ("0091", "  Of which: Qualifying revolving"),
    "defaulted": ("0100", "Exposures in default"),
    "equity": ("0110", "Equity exposures"),
    "other": ("0120", "Other items"),
}

# C 07.00 column definitions (key measures)
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

# Risk weight bands for the C 07.00 exposure breakdown
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


# =============================================================================
# C 08.01 — CR IRB (IRB Approach Totals)
# =============================================================================

# Mapping: ExposureClass.value -> (row_ref, display_name)
# Based on CRR Art. 147 and Regulation (EU) 2021/451, Annex I, C 08.01
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

# C 08.01 column definitions
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
# C 08.02 — CR IRB (Breakdown by PD Grade)
# =============================================================================

# Standard PD bands for obligor grade grouping
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

# C 08.02 uses the same columns as C 08.01
C08_02_COLUMNS: list[COREPColumn] = C08_01_COLUMNS
