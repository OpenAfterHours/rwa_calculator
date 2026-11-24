"""
P1.204: C 08.06 / OF 08.06 and CR10 cut their slotting maturity rows on ONE
carrier, the sealed short-maturity band, resolved by one kernel helper.

Pipeline position:
    OutputAggregator -> {COREPGenerator (C 08.06), Pillar3Generator (CR10)}

``slotting_short_maturity_rw_applied`` is the band: the maturity fact, except a
Basel 3.1 short-dated Strong / Good leg of a firm without the PS1/26
Art. 153(5)(d) election (column B / D, long band). There is no
``is_short_maturity`` rung beneath it: a rung would place a leg on its maturity
whenever the band is absent and silently undo the election's row choice. Both
production ledgers carry the band — our pipeline seals it, and the legacy
projection derives it from the firm's maturity band
(``tests/unit/analysis/test_legacy_ledger.py`` pins both routes).

The end-to-end placement (pipeline -> both templates, both regimes, both
election states) is pinned in
``tests/acceptance/basel31/test_p1_204_slotting_short_maturity_election.py`` and,
on a registered portfolio, ``tests/acceptance/reporting/test_of08_06_slotting_maturity_rows.py``.

References:
- PRA PS1/26 Art. 153(5)(c)-(d); Annex II OF 08.06; Annex XXIV UKB CR10 col c
"""

from __future__ import annotations

import pytest

from rwa_calc.reporting.kernel import slotting_maturity_band


@pytest.mark.parametrize(
    ("cols", "expected"),
    [
        pytest.param(
            {"slotting_short_maturity_rw_applied", "is_short_maturity"},
            "slotting_short_maturity_rw_applied",
            id="sealed-band",
        ),
        pytest.param({"is_short_maturity"}, None, id="maturity-fact-is-not-a-rung"),
        pytest.param({"slotting_category"}, None, id="neither"),
    ],
)
def test_the_band_carrier_is_the_only_key(cols: set[str], expected: str | None) -> None:
    # Arrange / Act
    band = slotting_maturity_band(cols)

    # Assert
    assert band == expected
