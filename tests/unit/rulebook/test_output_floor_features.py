"""
Pins for the S11e-v1 output-floor percentage VALUE migration.

Phase 5 S11e-v1 moves the output-floor percentages off OutputFloorConfig onto
the rulepack: the Art. 92(5) transitional phase-in is the ``output_floor_pct``
Schedule and the fully-phased-in 72.5% is the ``output_floor_pct_full`` scalar.
The engine reads them via ``engine/aggregator/aggregator.py::_output_floor_pct``,
honouring the ``skip_transitional`` ELECTION that stays on the config.

The decisive byte-identity proof: the engine helper reproduces
``OutputFloorConfig.get_floor_percentage(on)`` EXACTLY for both the transitional
and skip paths at every date — before the phase-in start (0.0 via the Schedule's
before_first), each step boundary, and the post-2030 carry-forward.

References:
- PRA PS1/26 Art. 92: 72.5% aggregate output floor.
- PRA PS1/26 Art. 92(5): transitional phase-in (60/65/70/72.5%), permissive.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rwa_calc.contracts.config import OutputFloorConfig
from rwa_calc.engine.aggregator.aggregator import _output_floor_pct
from rwa_calc.rulebook.resolve import resolve

_B31_PACK = resolve("b31", date(2027, 1, 1))

# before-start, each step boundary, a mid-step date, and the carry-forward tail.
_DATES = (
    date(2026, 6, 15),
    date(2027, 1, 1),
    date(2027, 6, 15),
    date(2028, 6, 15),
    date(2029, 6, 15),
    date(2030, 6, 15),
    date(2031, 6, 15),
)


@pytest.mark.parametrize("skip", [False, True])
@pytest.mark.parametrize("on", _DATES)
def test_helper_matches_config_get_floor_percentage(on: date, skip: bool) -> None:
    """The pack-backed helper reproduces get_floor_percentage at every date.

    Covers both the transitional schedule path (skip=False) and the
    full-floor-from-day-one election (skip=True).
    """
    of_cfg = OutputFloorConfig.basel_3_1(skip_transitional=skip)
    assert _output_floor_pct(_B31_PACK, of_cfg, on) == of_cfg.get_floor_percentage(on)


def test_pack_values_pinned() -> None:
    # The fully-phased-in floor and the 2027 transitional step.
    assert _B31_PACK.scalar("output_floor_pct_full") == Decimal("0.725")
    assert _B31_PACK.schedule("output_floor_pct").resolve(date(2027, 6, 15)) == Decimal("0.60")
    assert _B31_PACK.schedule("output_floor_pct").resolve(date(2026, 6, 15)) == Decimal("0.0")


def test_skip_election_returns_full_floor_during_transitional() -> None:
    """skip_transitional=True returns the full 72.5% even mid-phase-in (2027)."""
    of_cfg = OutputFloorConfig.basel_3_1(skip_transitional=True)
    assert _output_floor_pct(_B31_PACK, of_cfg, date(2027, 6, 15)) == Decimal("0.725")
