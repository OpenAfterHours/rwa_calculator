"""
The filing adapter — our generated estate, handed to the ``rwa-filer`` rule engine.

Pipeline position:
    COREPGenerator + Pillar3Generator  ->  check_supervisory_validations
        ->  list[CalculationError]

Key responsibilities:
- Present this calculator's template bundles to ``rwa-filer`` in the publisher's
  own coordinates: which bundle member carries each published table code, and
  which of our per-class sheets each published sheet (z-axis) code addresses.
- Run the published supervisory validation rules through ``rwa-filer`` and bring
  the breaks back onto the error channel as ``VAL001`` (Error — blocks the
  submission) / ``VAL002`` (Warning) / ``VAL003`` (coverage) findings.

The boundary this package draws: everything that knows about OUR bundles, sheet
names and exposure classes is here; everything that knows how to load, parse and
evaluate a published rule is in ``rwa_filer`` — a separately released package
that never imports ``rwa_calc``. Import the engine's own names (rule shapes,
statuses, ``TemplateIndex``, ``ValidationReport``) from ``rwa_filer`` directly;
this package re-exports none of them.

Module map:
- ``sheet_maps`` — the cited publisher-sheet-code -> our-sheet-key maps
- ``bindings``   — publisher table codes -> bundle members; ``build_template_index``
- ``checks``     — the public entry points

References:
- docs/reference/validation-rules/index.md — provenance, schema, formula grammar
- docs/development/workspace.md — how the two packages share one repository
- COREP Annex II (CRR); PRA PS1/26 Annex II (Basel 3.1)
"""

from __future__ import annotations

from rwa_calc.reporting.filing.bindings import build_template_index, derive_variant_columns
from rwa_calc.reporting.filing.checks import (
    check_supervisory_validations,
    evaluate_all,
    to_calculation_error,
)
from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS

__all__ = [
    "SHEET_INDEX_MAPS",
    "build_template_index",
    "check_supervisory_validations",
    "derive_variant_columns",
    "evaluate_all",
    "to_calculation_error",
]
