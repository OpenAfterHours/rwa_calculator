"""
Pins for the S8 classifier regime Features.

Phase 5 S8 moved the classifier stage's regime branches off
``config.is_basel_3_1`` and onto cited pack Features (the FX-derived thresholds
and overridable elections those branches read stay in ``config`` → S11):

- ``approach_restrictions_b31_applicable`` (S8a) gates the Basel 3.1 Art. 147A(1)
  IRB-approach restriction family in ``engine/stages/classify/{approach,audit}.py``
  (FSE/large-corp/institution no A-IRB, sovereign-like + equity SA-only,
  IPRE/HVCRE slotting-only, plus the CLS008 large-corp conservatism warning).
- ``b31_high_risk_class_applicable`` (S8b) gates the Art. 128 150% high-risk class
  (CRR omitted it via SI 2021/1078, rewriting HIGH_RISK→OTHER; B31 retains it).
- ``b31_art_124e_three_property_limit_applies`` (S8b) gates the Art. 124E(1)(b)/(2)
  natural-person RRE three-property income-producing re-route.
- ``b31_exposure_subclass_reporting_applies`` (S8b) gates the Art. 147A(1) COREP
  corporate exposure-subclass split.

Each Feature's value mirrors ``config.is_basel_3_1`` per regime (CRR False /
Basel 3.1 True), so this pin is the byte-identical-parity contract.

References:
- CRR Art. 147 (no Art. 147A restrictions) / PRA PS1/26 Art. 147A(1).
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# (feature name, enabled under CRR, enabled under Basel 3.1)
_FEATURE_MATRIX = [
    ("approach_restrictions_b31_applicable", False, True),
    ("b31_high_risk_class_applicable", False, True),
    ("b31_art_124e_three_property_limit_applies", False, True),
    ("b31_exposure_subclass_reporting_applies", False, True),
]


@pytest.mark.parametrize(("name", "crr_enabled", "b31_enabled"), _FEATURE_MATRIX)
def test_classifier_feature_values_per_regime(
    name: str, crr_enabled: bool, b31_enabled: bool
) -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature(name) is crr_enabled
    assert _B31_PACK.feature(name) is b31_enabled
