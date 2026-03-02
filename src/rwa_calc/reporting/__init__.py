"""
Regulatory reporting module for RWA Calculator.

Provides template generation for supervisory reporting formats:
- COREP (Common Reporting): C07.00, C08.01, C08.02

Why: CRR firms must submit quarterly COREP returns to the PRA.
The calculator produces all the underlying data; this module
reshapes it into the fixed-format regulatory templates.
"""

from __future__ import annotations

from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle

__all__ = ["COREPGenerator", "COREPTemplateBundle"]
