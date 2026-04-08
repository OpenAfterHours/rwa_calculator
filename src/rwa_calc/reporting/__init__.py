"""
Regulatory reporting module for RWA Calculator.

Provides template generation for supervisory reporting formats:
- COREP (Common Reporting): C07.00, C08.01-08.07, OF 02.01
- Pillar III (Public Disclosure): OV1, CR4-CR8, CR10

Why: CRR firms must submit quarterly COREP returns to the PRA
and publish Pillar III disclosures for market transparency.
The calculator produces all the underlying data; this module
reshapes it into the fixed-format regulatory templates.
"""

from __future__ import annotations

from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.pillar3.generator import Pillar3Generator, Pillar3TemplateBundle

__all__ = [
    "COREPGenerator",
    "COREPTemplateBundle",
    "Pillar3Generator",
    "Pillar3TemplateBundle",
]
