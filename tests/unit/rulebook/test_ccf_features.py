"""
Pin for the S9c CCF / A-IRB-EAD-floor regime Features.

Phase 5 S9c moved two CCF-stage regime gates off ``config.is_basel_3_1``
and onto cited pack Features, threaded into the CCF calculator
(engine/ccf.py::apply_ccf -> _compute_ccf / _compute_ead) from the CRM
processor. The CCF builder helpers (``sa_ccf_expression`` /
``_firb_ccf_for_col``) keep their ``is_basel_3_1`` bool plumbing params
(Option B); only the regime reads move to the pack:

- ``firb_uses_sa_ccf`` — Basel 3.1 Art. 166C makes F-IRB CCFs equal the SA
  CCFs (and routes SL slotting to SA); CRR uses the Art. 166(8)+(10)
  bespoke/fallback CCFs (_compute_ccf line 329).
- ``airb_ead_floor_applies`` — Basel 3.1 Art. 166D(5) adds the A-IRB EAD
  floor tests (on-BS EAD + 50% off-BS at F-IRB CCF); CRR has none
  (_compute_ead line 535).

Both gate only the branch — the SA/F-IRB CCF tables and the 0.5 floor
multiplier stay static data-layer constants (not FX-derived). Each
Feature's value mirrors ``config.is_basel_3_1`` per regime (CRR False /
Basel 3.1 True), so this pin is the byte-identical-parity contract.

References:
- CRR Art. 166 (bespoke/fallback CCFs; no EAD floors) /
  PRA PS1/26 Art. 166C (F-IRB = SA CCFs), Art. 166D(5) (A-IRB EAD floors).
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# (feature name, enabled under CRR, enabled under Basel 3.1)
_FEATURE_MATRIX = [
    ("firb_uses_sa_ccf", False, True),
    ("airb_ead_floor_applies", False, True),
]


@pytest.mark.parametrize(("name", "crr_enabled", "b31_enabled"), _FEATURE_MATRIX)
def test_ccf_feature_values_per_regime(name: str, crr_enabled: bool, b31_enabled: bool) -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature(name) is crr_enabled
    assert _B31_PACK.feature(name) is b31_enabled
