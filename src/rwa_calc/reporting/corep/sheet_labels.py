"""
Readable sheet-key labels for the C 07.00 / OF 07.00 exposure-class axis.

Pipeline position:
    corep/c07.py (sheet keys) -> here (readable names) -> the Excel tab
    (corep/generator.py) and the UI sheet picker (reporting/catalog.py)

Key responsibilities:
- Name each Article 112(1) sheet key as the published instructions name it, per
  REGIME, so neither the workbook nor the picker shows a reader a raw key.

Why a module of its own: the strings are display-only and regime-paired, and
``corep/templates.py`` — which owns the row/column STRUCTURE and the sheet-key
map itself — is the largest module in ``reporting/`` and ratcheted on length
(``max_reporting_module_loc``). The label CONSTANTS stay in ``templates.py``
beside the C 09.01 row tables that share them, and are read from there, so a
string still has exactly one home.

References:
- CRR Art. 112(1)(a)-(q); PRA PS1/26 Art. 112(1), Table A2
- Regulation (EU) 2021/451, Annex II (C 09.01 rows 0010-0160)
- PRA PS1/26, Annex II (OF 09.01 rows 0010-0160)
"""

from __future__ import annotations

from rwa_calc.reporting.corep.templates import (
    _LBL_SA_CENTRAL_GOVT,
    _LBL_SA_CORPORATES,
    _LBL_SA_COVERED_BOND,
    _LBL_SA_COVERED_BOND_B31,
    _LBL_SA_DEFAULTED,
    _LBL_SA_EQUITY,
    _LBL_SA_EQUITY_B31,
    _LBL_SA_HIGH_RISK,
    _LBL_SA_HIGH_RISK_B31,
    _LBL_SA_INSTITUTIONS,
    _LBL_SA_INTL_ORG,
    _LBL_SA_MDB,
    _LBL_SA_MORTGAGES,
    _LBL_SA_OTHER,
    _LBL_SA_PSE,
    _LBL_SA_REAL_ESTATE,
    _LBL_SA_RETAIL,
    _LBL_SA_RGLA,
)

# Readable name per sheet key, for the Excel tab and the UI sheet picker — both
# rendered the raw key until 2026-09-08, which is how a reader came to be shown
# "retail_mortgage" for a sheet holding commercial mortgages. An unlisted key
# falls back to itself, so a new class shows its key rather than disappearing.
# REGIME-DEPENDENT, hence two maps and an accessor and never one flat dict: four
# of the fourteen are renamed by PS1/26, and printing the CRR name on a Basel 3.1
# submission is the same defect in the other direction. Strings are the published
# row labels of the geographical template over this same Art. 112(1) axis — COREP
# Annex II C 09.01 / PS1/26 Annex II OF 09.01 rows 0010-0160 (pp. 139-141) — read
# where possible from the shared ``_LBL_SA_*`` constants that already serve
# ``CRR_C09_01_ROWS`` / ``B31_C09_01_ROWS``, so most entries cannot drift from
# them. TWO entries deliberately do NOT match the C 09.01 row they correspond to,
# and sharing a constant is therefore not a guarantee for the map as a whole:
#   - ``mdb``: OF 09.01 row 0040 prints "Multilateral developmentS banks", a typo
#     against the rule it cites (Art. 112(1)(d)) and against every other
#     appearance, so ``_LBL_SA_MDB`` is used rather than reproducing it.
#   - ``other`` under CRR: ``CRR_C09_01_ROWS`` row 0160 reads "Other exposures",
#     but Art. 112(1)(q) itself says "other items" and B31 agrees, so
#     ``_LBL_SA_OTHER`` is used here and the two legitimately differ.
CRR_C07_00_SA_SHEET_LABELS: dict[str, str] = {
    "central_govt_central_bank": _LBL_SA_CENTRAL_GOVT,
    "rgla": _LBL_SA_RGLA,
    "pse": _LBL_SA_PSE,
    "mdb": _LBL_SA_MDB,
    "international_organisation": _LBL_SA_INTL_ORG,
    "institution": _LBL_SA_INSTITUTIONS,
    "corporate": _LBL_SA_CORPORATES,
    "retail": _LBL_SA_RETAIL,
    "real_estate": _LBL_SA_MORTGAGES,
    "defaulted": _LBL_SA_DEFAULTED,
    "high_risk": _LBL_SA_HIGH_RISK,
    "covered_bond": _LBL_SA_COVERED_BOND,
    "equity": _LBL_SA_EQUITY,
    "other": _LBL_SA_OTHER,
}

# The four PS1/26 renames: (i) drops the security-interest description, (k)
# "Exposures" for "Items", (l) narrows to eligible covered bonds, (p) widens
# beyond equity to subordinated debt and other own funds instruments.
B31_C07_00_SA_SHEET_LABELS: dict[str, str] = {
    **CRR_C07_00_SA_SHEET_LABELS,
    "real_estate": _LBL_SA_REAL_ESTATE,
    "high_risk": _LBL_SA_HIGH_RISK_B31,
    "covered_bond": _LBL_SA_COVERED_BOND_B31,
    "equity": _LBL_SA_EQUITY_B31,
}


def get_c07_sheet_labels(framework: str = "CRR") -> dict[str, str]:
    """Return the readable C 07.00 / OF 07.00 sheet-key labels for the framework.

    Four Art. 112(1) classes are named differently under PS1/26 — (i), (k), (l)
    and (p) — so this must be resolved per regime and never flattened into one
    map. Callers should fall back to the key itself for an unmapped sheet: a
    missing label must never hide a sheet from a picker or an export.
    """
    return B31_C07_00_SA_SHEET_LABELS if framework == "BASEL_3_1" else CRR_C07_00_SA_SHEET_LABELS
