"""
Pin for the S9f SA RE loan-split regime Features.

Phase 5 S9f moved the three RE loan-split decision gates in
engine/stages/re_split/flagging.py (run inside the classifier stage) off
``config.is_basel_3_1`` and onto cited pack Features, threaded from
classifier.py into ``flag_property_reclassification_candidates`` and its two
expression-block helpers. The helpers keep their ``config`` param for the
fallback resolve; only the regime reads move to the pack:

- ``sa_re_split_cre_rental_coverage_required`` — CRR Art. 126 requires the
  CRE rental-coverage test (>=1.5x interest) for split eligibility; Basel
  3.1 Art. 124H removes it. (CRR True / B31 False — the one affirmative-
  under-CRR Feature in this batch.)
- ``sa_re_split_art_124_4_all_or_nothing`` — Basel 3.1 Art. 124(4) drops a
  mixed-RE exposure with any non-qualifying component to Art. 124J; CRR has
  no such rule.
- ``sa_re_split_whole_loan_path_applies`` — Basel 3.1 Art. 124H(3) routes
  pure-CRE non-NP/SME corporates to a single whole-loan row; CRR splits all
  eligible exposures.

S9g additionally moved the splitter's RE-split parameter-set selection
(engine/stages/re_split/splitter.py) onto the pack, threading it through the
``RealEstateSplitterProtocol.split`` signature and the re_split stage adapter:

- ``sa_re_split_revised_parameters`` — selects the Basel 3.1 Art. 124F/124H
  LTV caps / risk weights (RRE 55%/20%, CRE 55%/60%) vs the CRR Art. 125/126
  values (RRE 80%/35%, CRE 50%/50%). The parameter VALUES live in
  data/tables/re_split_parameters.py; re_split_parameters and
  _split_unified_frame keep their is_basel_3_1 bool plumbing params.

Each Feature's value mirrors ``config.is_basel_3_1`` per regime, so this pin
is the byte-identical-parity contract.

References:
- CRR Art. 125/126 / PRA PS1/26 Art. 124F/124H/124(4).
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# (feature name, enabled under CRR, enabled under Basel 3.1)
_FEATURE_MATRIX = [
    ("sa_re_split_cre_rental_coverage_required", True, False),
    ("sa_re_split_art_124_4_all_or_nothing", False, True),
    ("sa_re_split_whole_loan_path_applies", False, True),
    ("sa_re_split_revised_parameters", False, True),
]


@pytest.mark.parametrize(("name", "crr_enabled", "b31_enabled"), _FEATURE_MATRIX)
def test_re_split_feature_values_per_regime(
    name: str, crr_enabled: bool, b31_enabled: bool
) -> None:
    # Arrange / Act / Assert
    assert _CRR_PACK.feature(name) is crr_enabled
    assert _B31_PACK.feature(name) is b31_enabled
