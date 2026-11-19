"""OF 08.01 row 0035 ("Own estimate") follows the engine's Basel 3.1 own-estimate scope.

PS1/26 Annex II p.116: "For exposures subject to ... the AIRB approach where neither
conversion factors nor EADs are estimated, institutions shall report values in rows
that correspond to the applicable conversion factors in Article 111 ... For exposures
subject to the AIRB approach for which conversion factors are estimated, or where EADs
are estimated directly, institutions shall report values in row 0035."

Which A-IRB legs have a conversion factor that "is estimated" is decided by the engine
(``engine/ccf.py::CCFCalculator._compute_ccf``) and ``reporting/corep/ccf_buckets.py``
reads it back from the leg's columns, since the decision is not sealed. Two engine
changes in the 2026-11 ``ccf`` cluster narrowed that scope, and the reporting mirror
has to narrow with it or it files a supervisory factor as an own estimate:

- CM-03, PS1/26 Art. 166D(1): own estimates only "(a) for revolving loan commitments
  ..."; "(b) for all other off-balance sheet items: the conversion factor that would
  be applicable ... under the Standardised Approach". A commitment is, by the PS1/26
  glossary, "not itself an issued off-balance sheet item", so an issued letter of
  credit under a revolving facility (``is_obs_commitment`` False) takes the Table A1
  factor even when it carries ``ccf_modelled``. Its 20% belongs in row 0032.
- TR-02, PS1/26 Art. 166A(5): "An institution shall, for undrawn purchase commitments
  for revolving purchased receivables, calculate the exposure value using a
  conversion factor of 40%" — a fixed factor, no own estimate. The 40% belongs in row
  0001.

An absent ``is_obs_commitment`` column reads as a commitment and an absent
``is_purchased_receivable_commitment`` as unflagged — the engine's own defaults when
those columns are missing — so frames that never carried them file as before.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.ccf_buckets import OWN_ESTIMATE_ROW, of08_01_ccf_row_expr

_AIRB = "advanced_irb"


def _leg(**columns: object) -> pl.DataFrame:
    """One A-IRB revolving leg carrying an own estimate; ``columns`` override or add."""
    row: dict[str, object] = {
        "reporting_approach_origin": _AIRB,
        "ccf": 0.3,
        "ccf_modelled": 0.3,
        "ead_modelled": None,
        "is_revolving": True,
    }
    row.update(columns)
    return pl.DataFrame(
        [row],
        schema_overrides={
            "ccf_modelled": pl.Float64,
            "ead_modelled": pl.Float64,
            "is_revolving": pl.Boolean,
            **{c: pl.Boolean for c in columns if c.startswith("is_")},
        },
    )


def _row_of(frame: pl.DataFrame) -> str | None:
    expr = of08_01_ccf_row_expr(set(frame.columns))
    assert expr is not None, "the frame carries a ccf carrier, so a row must be derived"
    return frame.select(expr.alias("row"))["row"][0]


def test_issued_item_under_a_revolving_facility_files_by_its_factor() -> None:
    """CM-03: an issued LC carrying ccf_modelled took the SA 20% - row 0032, not 0035."""
    # Arrange
    frame = _leg(ccf=0.2, ccf_modelled=0.05, is_obs_commitment=False)

    # Act / Assert
    assert _row_of(frame) == "0032"


def test_purchased_receivable_commitment_files_by_its_fixed_factor() -> None:
    """TR-02: a flagged revolving purchase commitment took the fixed 40% - row 0001."""
    # Arrange
    frame = _leg(
        ccf=0.4,
        ccf_modelled=0.25,
        is_obs_commitment=True,
        is_purchased_receivable_commitment=True,
    )

    # Act / Assert
    assert _row_of(frame) == "0001"


@pytest.mark.parametrize(
    "columns",
    [
        pytest.param({"is_obs_commitment": True}, id="commitment"),
        pytest.param(
            {"is_obs_commitment": True, "is_purchased_receivable_commitment": False},
            id="commitment-unflagged",
        ),
        pytest.param({}, id="flags-absent"),
    ],
)
def test_revolving_loan_commitment_with_an_own_estimate_stays_in_row_0035(
    columns: dict[str, object],
) -> None:
    """Control: Art. 166D(1)(a) still applies to a revolving loan commitment."""
    # Arrange
    frame = _leg(**columns)

    # Act / Assert
    assert _row_of(frame) == OWN_ESTIMATE_ROW


@pytest.mark.parametrize(
    ("columns", "row"),
    [
        pytest.param({"is_obs_commitment": False}, "0032", id="issued-item"),
        pytest.param(
            {"is_obs_commitment": True, "is_revolving": False}, "0032", id="non-revolving"
        ),
        pytest.param(
            {"is_obs_commitment": True, "is_purchased_receivable_commitment": True},
            "0032",
            id="purchased-receivable",
        ),
        pytest.param({"is_obs_commitment": True}, OWN_ESTIMATE_ROW, id="revolving-commitment"),
    ],
)
def test_an_own_estimate_of_ead_files_in_row_0035_only_on_a_revolving_loan_commitment(
    columns: dict[str, object], row: str
) -> None:
    """Art. 166D(3): a single own estimate of EAD only for a revolving loan facility.

    The engine (``engine/ccf.py::_compute_ead``) ignores ``ead_modelled`` on any
    other leg, which then carries its Table A1 / Art. 166A(5) factor (here 20%).
    """
    # Arrange
    frame = _leg(ccf=0.2, ccf_modelled=None, ead_modelled=900.0, **columns)

    # Act / Assert
    assert _row_of(frame) == row
