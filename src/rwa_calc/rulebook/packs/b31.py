"""
Basel 3.1 rulebook pack — PRA PS1/26 cited regime entries.

Pipeline position:
    Amendment layer for the ``"b31"`` regime (``REGIME_PACKS["b31"] =
    ("common", "b31")``); overlaid on the common pack by
    ``rulebook/resolve.py``, overriding any colliding entry names (e.g. the
    IRB scaling factor, which Basel 3.1 removes).

Key responsibilities:
- Hold the Basel-3.1-specific proof-pack values: the removed IRB scaling
  factor (1.0), the A-IRB LGD floor and output-floor feature flags, and the
  output-floor transitional ``Schedule``.

References:
- PRA PS1/26 Art. 153(1): IRB scaling factor removed under Basel 3.1 (1.0).
- PRA PS1/26 Art. 161(5): A-IRB own-estimate LGD floors.
- PRA PS1/26 Art. 92: the aggregate output floor.
- PRA PS1/26 Art. 92(5): output-floor transitional phase-in percentages.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from rwa_calc.rulebook.model import Citation, Feature, RuleEntry, ScalarParam, Schedule

ENTRIES: dict[str, RuleEntry] = {
    "irb_scaling_factor": ScalarParam(
        name="irb_scaling_factor",
        value=Decimal("1.0"),
        citation=Citation("PS1/26", "153(1)"),
    ),
    "airb_lgd_floor": Feature(
        name="airb_lgd_floor",
        enabled=True,
        citation=Citation("PS1/26", "161(5)"),
    ),
    "output_floor": Feature(
        name="output_floor",
        enabled=True,
        citation=Citation("PS1/26", "92"),
    ),
    "output_floor_pct": Schedule(
        name="output_floor_pct",
        steps=(
            (date(2027, 1, 1), Decimal("0.60")),
            (date(2028, 1, 1), Decimal("0.65")),
            (date(2029, 1, 1), Decimal("0.70")),
            (date(2030, 1, 1), Decimal("0.725")),
        ),
        before_first=Decimal("0.0"),
        citation=Citation("PS1/26", "92(5)"),
    ),
}
