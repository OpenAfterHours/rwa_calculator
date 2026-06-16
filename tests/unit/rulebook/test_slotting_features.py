"""
Pin for the S7a slotting regime Feature.

Phase 5 S7a moved the slotting (supervisory specialised-lending) risk-weight and
expected-loss table selection off ``config.is_crr`` and onto a pack Feature (the
table VALUES they gate stay in ``data/tables/{crr,b31}_slotting.py``):

- ``slotting_revised_tables`` selects the CRR Art. 153(5) single-table family
  (HVCRE Table 2 not onshored) vs the Basel 3.1 PS1/26 Art. 153(5) Table A /
  CRE33 family (HVCRE + PF pre-operational splits). It gates both
  ``apply_slotting_weights`` and ``apply_el_rates`` in
  ``engine/slotting/transforms.py`` via ``is_crr = not pack.feature(...)``.

The Feature's value mirrors ``config.is_basel_3_1`` per regime (CRR False /
Basel 3.1 True), so this pin is the byte-identical-parity contract.

References:
- CRR Art. 153(5) / Art. 158(6) Table B: UK CRR slotting RW + EL rates.
- PRA PS1/26 Art. 153(5) Table A / BCBS CRE33: Basel 3.1 slotting tables.
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# (feature name, enabled under CRR, enabled under Basel 3.1)
_FEATURE_MATRIX = [
    ("slotting_revised_tables", False, True),
]


@pytest.mark.parametrize(("name", "crr_enabled", "b31_enabled"), _FEATURE_MATRIX)
def test_slotting_feature_values_per_regime(
    name: str, crr_enabled: bool, b31_enabled: bool
) -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature(name) is crr_enabled
    assert _B31_PACK.feature(name) is b31_enabled
