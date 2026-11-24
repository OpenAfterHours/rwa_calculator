"""
Pack entries for the PS1/26 rule 4.11 unfunded credit protection transitional.

Rule 4.11 (PS1/26 Credit Risk: General Provisions (CRR) Part, ps126app1.pdf):
    "During the period beginning with 1 January 2027 and ending with 30 June
    2028, point (b) of paragraph 1A of ... Article 183 and point (c)(i) of
    paragraph 1 of ... Article 213 shall apply to unfunded credit protection
    entered into prior to 1 January 2027 with the words 'or change' wherever
    they appear omitted."

The three dates are Basel 3.1 pack entries cited to rule 4.11. CRR needs none:
its Art. 213(1)(c)(i) has no "or change" words to omit, and the screen reads
the dates only where ``ucp_unilateral_change_ineligible`` is on (off in CRR).
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.rulebook.resolve import resolve

_B31_PACK = resolve("b31", date(2027, 6, 30))
_CRR_PACK = resolve("crr", date(2026, 6, 30))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ucp_change_limb_transitional_start", date(2027, 1, 1)),
        ("ucp_change_limb_transitional_end", date(2028, 6, 30)),
        ("ucp_change_limb_grandfather_inception_cutoff", date(2027, 1, 1)),
    ],
)
def test_rule_4_11_dates_are_cited_b31_entries(name: str, expected: date) -> None:
    # Act
    entry = _B31_PACK.date_param(name)

    # Assert
    assert entry.value == expected
    assert entry.citation.article == "4.11"


def test_crr_change_limb_is_off_so_no_transitional_dates_are_read() -> None:
    # Assert — the screen reads the dates only behind this Feature
    assert _CRR_PACK.feature("ucp_unilateral_change_ineligible") is False
    assert _B31_PACK.feature("ucp_unilateral_change_ineligible") is True
