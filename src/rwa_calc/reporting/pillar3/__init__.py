"""Pillar III credit risk disclosure templates.

Public disclosures under CRR Part 8 / Disclosure (CRR) Part.
CRR templates use UK prefix; Basel 3.1 templates use UKB prefix.
"""
from __future__ import annotations

from rwa_calc.reporting.pillar3.generator import Pillar3Generator, Pillar3TemplateBundle

__all__ = ["Pillar3Generator", "Pillar3TemplateBundle"]
