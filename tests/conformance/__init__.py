"""
Conformance suite — externally-authored decision tables vs the engine (C4).

Two components, both built on the principle that a validation layer's source of
truth must be causally independent of the code it validates:

- **C4a** (``test_classification_conformance.py``): a decision table authored
  from the CRR / PS1/26 article text and held as a data file
  (``classification_table.toml``), asserted against the classifier over a
  combinatorially generated input space. A combination with no verdict in the
  table is a hard failure, not a skip.
- **C4a keying** (``test_reporting_class_keys.py``): every exposure-class
  collection in ``rwa_calc.reporting`` is discovered by introspection and
  checked against ``{m.value for m in ExposureClass}``.

References:
- docs/plans/independent-validation-system.md §C4
- .claude/LESSONS.md B2, B3 (a test written from production's own wrong
  sentence proves nothing)
"""

from __future__ import annotations
