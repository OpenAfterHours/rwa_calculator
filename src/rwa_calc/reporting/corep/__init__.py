"""
COREP template generation for credit risk reporting.

Generates EBA/PRA COREP templates from RWA calculation results:
- C 07.00: CR SA — Standardised Approach credit risk
- C 08.01: CR IRB — IRB approach totals by exposure class
- C 08.02: CR IRB — IRB approach breakdown by PD grade

References:
- Regulation (EU) 2021/451 (ITS on Supervisory Reporting), Annexes I/II
- PRA CP16/22 Chapter 12 (Basel 3.1 reporting amendments)
- CRR Art. 111-134 (SA), Art. 142-191 (IRB)
"""

from __future__ import annotations

from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.corep.templates import (
    IRB_EXPOSURE_CLASS_ROWS,
    PD_BANDS,
    SA_EXPOSURE_CLASS_ROWS,
    SA_RISK_WEIGHT_BANDS,
)

__all__ = [
    "COREPGenerator",
    "COREPTemplateBundle",
    "IRB_EXPOSURE_CLASS_ROWS",
    "PD_BANDS",
    "SA_EXPOSURE_CLASS_ROWS",
    "SA_RISK_WEIGHT_BANDS",
]
