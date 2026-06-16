"""
Pins for the S5d IRB maturity + double-default regime Features.

Phase 5 S5d moved four regime on/off branches off ``config.is_crr`` /
``config.is_basel_3_1`` and onto pack Features (the numeric constants they gate —
0.5y SFT supervisory M, the 1/365 one-day floor, the 0.15+160xPD double-default
multiplier — stay engine literals). These pins lock each Feature's value per
regime so a pack typo fails here, before the engine-level behaviour tests.

References:
- CRR Art. 162(1): F-IRB SFT supervisory maturity (CRR-only).
- CRR Art. 162(3): short-term-trade one-day maturity floor derivation (CRR-only).
- PRA PS1/26 Art. 162(2A)(k): revolving facilities use the termination date (B31-only).
- CRR Art. 153(3), 202-203: double-default treatment (CRR-only).
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# (feature name, enabled under CRR, enabled under Basel 3.1)
_FEATURE_MATRIX = [
    ("firb_sft_supervisory_maturity", True, False),
    ("one_day_maturity_floor", True, False),
    ("revolving_uses_termination_maturity", False, True),
    ("double_default_treatment", True, False),
]


@pytest.mark.parametrize(("name", "crr_enabled", "b31_enabled"), _FEATURE_MATRIX)
def test_maturity_double_default_feature_values_per_regime(
    name: str, crr_enabled: bool, b31_enabled: bool
) -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature(name) is crr_enabled
    assert _B31_PACK.feature(name) is b31_enabled
