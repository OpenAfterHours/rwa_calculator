"""
Pin for the S9d FCCM collateral-haircut maturity-band regime Feature.

Phase 5 S9d moved the FCCM collateral-haircut maturity-band structure gate
off ``config.is_basel_3_1`` and onto one cited pack Feature read at
engine/crm/haircuts.py::apply_haircuts. The band-classification helper
``_maturity_band_expression`` keeps its ``is_b31: bool`` plumbing param
(Option B); only the regime read moves to the pack:

- ``collateral_haircut_maturity_bands_revised`` selects the Basel 3.1
  5-band structure (0_1y / 1_3y / 3_5y / 5_10y / 10y_plus, Art. 224) vs the
  CRR 3-band structure (0_1y / 1_5y / 5y_plus). The haircut VALUES live in
  the ``collateral_haircuts`` DecisionTable (already pack-backed); this
  Feature gates only the band-classification expression.

The Feature's value mirrors ``config.is_basel_3_1`` per regime (CRR False /
Basel 3.1 True), so this pin is the byte-identical-parity contract.

References:
- CRR Art. 224 Table 1 (3 maturity bands) / PRA PS1/26 Art. 224 (5 bands).
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# (feature name, enabled under CRR, enabled under Basel 3.1)
_FEATURE_MATRIX = [
    ("collateral_haircut_maturity_bands_revised", False, True),
]


@pytest.mark.parametrize(("name", "crr_enabled", "b31_enabled"), _FEATURE_MATRIX)
def test_haircut_feature_values_per_regime(name: str, crr_enabled: bool, b31_enabled: bool) -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature(name) is crr_enabled
    assert _B31_PACK.feature(name) is b31_enabled
