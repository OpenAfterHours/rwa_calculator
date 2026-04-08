"""
COREP template generation for credit risk reporting.

Generates EBA/PRA COREP templates from RWA calculation results:
- C 07.00 / OF 07.00: CR SA — Standardised Approach credit risk
- C 08.01 / OF 08.01: CR IRB — IRB approach totals by exposure class
- C 08.02 / OF 08.02: CR IRB — IRB approach breakdown by PD grade
- OF 02.01: Output floor comparison — modelled vs SA by risk type (Basel 3.1 only)

Supports both CRR (current) and Basel 3.1 (PRA PS1/26) frameworks.

References:
- Regulation (EU) 2021/451 (ITS on Supervisory Reporting), Annexes I/II
- PRA PS1/26 (Basel 3.1 OF template layouts)
- PRA PS1/26 Art. 92 para 2A/3A (output floor)
- CRR Art. 111-134 (SA), Art. 142-191 (IRB)
"""

from __future__ import annotations

from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.corep.templates import (
    B31_C07_COLUMNS,
    B31_C08_COLUMNS,
    B31_IRB_ROW_SECTIONS,
    B31_SA_RISK_WEIGHT_BANDS,
    B31_SA_ROW_SECTIONS,
    C07_COLUMNS,
    C08_01_COLUMNS,
    CRR_C07_COLUMNS,
    CRR_C08_COLUMNS,
    CRR_IRB_ROW_SECTIONS,
    CRR_SA_ROW_SECTIONS,
    IRB_EXPOSURE_CLASS_ROWS,
    OF_02_01_COLUMN_REFS,
    OF_02_01_COLUMNS,
    OF_02_01_ROW_SECTIONS,
    PD_BANDS,
    SA_EXPOSURE_CLASS_ROWS,
    SA_RISK_WEIGHT_BANDS,
    get_c07_columns,
    get_c08_columns,
    get_irb_row_sections,
    get_sa_risk_weight_bands,
    get_sa_row_sections,
)

__all__ = [
    "B31_C07_COLUMNS",
    "B31_C08_COLUMNS",
    "B31_IRB_ROW_SECTIONS",
    "B31_SA_RISK_WEIGHT_BANDS",
    "B31_SA_ROW_SECTIONS",
    "C07_COLUMNS",
    "C08_01_COLUMNS",
    "COREPGenerator",
    "COREPTemplateBundle",
    "CRR_C07_COLUMNS",
    "CRR_C08_COLUMNS",
    "CRR_IRB_ROW_SECTIONS",
    "CRR_SA_ROW_SECTIONS",
    "IRB_EXPOSURE_CLASS_ROWS",
    "OF_02_01_COLUMN_REFS",
    "OF_02_01_COLUMNS",
    "OF_02_01_ROW_SECTIONS",
    "PD_BANDS",
    "SA_EXPOSURE_CLASS_ROWS",
    "SA_RISK_WEIGHT_BANDS",
    "get_c07_columns",
    "get_c08_columns",
    "get_irb_row_sections",
    "get_sa_risk_weight_bands",
    "get_sa_row_sections",
]
