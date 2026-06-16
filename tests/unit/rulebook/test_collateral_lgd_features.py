"""
Pin for the S9h CRM collateral-LGD regime Feature.

Phase 5 S9h replaced the multi-concept ``config.is_basel_3_1`` bool in the
CRM collateral-LGD path (engine/crm/collateral.py) with honest cited pack
Features read at each branch point. Most branches reuse existing Features
(firb_fse_senior_lgd_split for the FSE 45/40 split,
collateral_haircut_maturity_bands_revised for the exposure-haircut bands,
firb_overcollateralisation_divisor_applies for the Art. 230(2) subordinated
secured-portion rows). One genuinely new concept needed a Feature:

- ``airb_lgd_collateral_method_applicable`` — Basel 3.1 Art. 169A/169B
  introduce the AIRB Foundation Collateral Method election and the
  LGD-modelling / insufficient-data fallback that route AIRB exposures to
  the supervisory LGD formula. CRR AIRB is free-form (own LGD always kept),
  so the Feature is disabled under CRR. Gates the AIRB-method branches in
  airb_lgd_preserved_expr / apply_firb_supervisory_lgd_no_collateral /
  _apply_collateral_unified.

The ``airb_collateral_method`` election itself (Foundation vs LGD-modelling)
stays a config field (→ S11); this Feature gates only the regime on/off.
The Feature's value mirrors ``config.is_basel_3_1`` per regime (CRR False /
Basel 3.1 True), so this pin is the byte-identical-parity contract.

References:
- CRR Art. 181 (AIRB own-LGD free-form) / PRA PS1/26 Art. 169A/169B.
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# (feature name, enabled under CRR, enabled under Basel 3.1)
_FEATURE_MATRIX = [
    ("airb_lgd_collateral_method_applicable", False, True),
]


@pytest.mark.parametrize(("name", "crr_enabled", "b31_enabled"), _FEATURE_MATRIX)
def test_collateral_lgd_feature_values_per_regime(
    name: str, crr_enabled: bool, b31_enabled: bool
) -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature(name) is crr_enabled
    assert _B31_PACK.feature(name) is b31_enabled
