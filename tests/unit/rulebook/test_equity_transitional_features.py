"""
Pins for the S11e-v2 equity-transitional VALUE migration.

Phase 5 S11e moves the PRA Rules 4.2/4.3 transitional equity risk-weight
schedule off ``EquityTransitionalConfig.schedule`` onto the rulepack: the
standard / higher-risk RW VALUES live in the ``equity_transitional_std_rw`` /
``equity_transitional_hr_rw`` Schedules, read by
``engine/equity/calculator.py::_equity_transitional_rw`` (gated by the
``equity_transitional`` Feature, with the None-before-first contract preserved).

The decisive byte-identity proof: the engine helper reproduces
``EquityTransitionalConfig.basel_3_1().get_transitional_rw(on, is_higher_risk)``
EXACTLY at every date — including before the first scheduled step (None, not the
Schedule's before_first 0.0) and in the post-2030 carry-forward tail.

References:
- PRA PS1/26 Rules 4.1-4.10: equity transitional regime (Basel 3.1 only).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rwa_calc.contracts.config import EquityTransitionalConfig
from rwa_calc.engine.equity.calculator import _equity_transitional_rw
from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2027, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))
_B31_CONFIG_SCHED = EquityTransitionalConfig.basel_3_1()

# before-first, each step boundary, a mid-step date, and the carry-forward tail.
_DATES = (
    date(2026, 12, 31),
    date(2027, 1, 1),
    date(2027, 6, 30),
    date(2028, 1, 1),
    date(2029, 1, 1),
    date(2030, 1, 1),
    date(2031, 1, 1),
)


@pytest.mark.parametrize("is_higher_risk", [False, True])
@pytest.mark.parametrize("on", _DATES)
def test_b31_helper_matches_config_schedule(on: date, is_higher_risk: bool) -> None:
    # The pack-backed helper reproduces get_transitional_rw exactly at every date.
    expected = _B31_CONFIG_SCHED.get_transitional_rw(on, is_higher_risk=is_higher_risk)
    assert _equity_transitional_rw(_B31_PACK, on, is_higher_risk=is_higher_risk) == expected


@pytest.mark.parametrize("is_higher_risk", [False, True])
@pytest.mark.parametrize("on", _DATES)
def test_crr_helper_is_none(on: date, is_higher_risk: bool) -> None:
    # CRR has no transitional regime (Feature off) → None at every date, matching
    # the default EquityTransitionalConfig (enabled=False) the .crr() config carries.
    assert _equity_transitional_rw(_CRR_PACK, on, is_higher_risk=is_higher_risk) is None


def test_schedule_values_pinned_at_2027() -> None:
    # The pack Schedules resolve to the Rules 4.2/4.3 start-of-phase-in values.
    assert _B31_PACK.schedule_value("equity_transitional_std_rw") == Decimal("1.60")
    assert _B31_PACK.schedule_value("equity_transitional_hr_rw") == Decimal("2.20")
