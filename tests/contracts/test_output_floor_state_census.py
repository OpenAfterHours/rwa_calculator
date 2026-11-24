"""
The output-floor state census reads each run's floor state and row shapes correctly.

Pipeline position:
    (no pipeline stage — drives the census helpers of the supervisory register
    with synthetic frames and states; nothing here runs a pipeline)
    tests/acceptance/reporting/test_supervisory_validations.py — floor-state legs

PS1/26 Art. 92(2A) makes the output floor a maximum, TREA = max{U-TREA;
x . S-TREA + OF-ADJ}, so every Basel 3.1 return is in one of two states, and a
published rule over a floored figure has a branch for each. ``boe_b0751`` /
``boe_b0763`` broke the first time a registered portfolio entered the binding
state, because no run had before (escape log 2026-11-16; plan item P5.64). The
supervisory register therefore records, for every Basel 3.1 run, the engine's
floor state (``OutputFloorSummary.portfolio_floor_binding``), the state OF 02.00
reports (row 0034 column 0030, "Output floor activated", PS1/26 Annex II p.29:
column 0030 "equal to or greater than" column 0010 on row 0010), and which
modelled-book row shapes the run holds — and ratchets the binding set and the
shapes reached in each state.

Watching those legs fail through the acceptance file costs every pipeline run of
``RUNS``. These tests feed the helpers directly, so each failure mode is shown
to be detectable on an input that has it and silent on one that does not
(LESSONS B9: an alarm that cannot tell the two apart is not a gate).

References:
- PRA PS1/26 Appendix 1, Art. 92(2A) (pp.13-14)
- PRA PS1/26 Annex II, OF 02.00 rows 0010 and 0034 (p.29)
- tests/acceptance/reporting/test_supervisory_validations.py — the census legs
"""

from __future__ import annotations

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import (
    FLOOR_SHAPES,
    FloorState,
    _activation_disagreements,
    _binding_runs,
    _modelled_shapes,
    _reported_activation,
    _shapes_by_state,
)

from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.aggregator._schemas import SA_CCR_APPROACH


def _of_02_00(activated: float | None, floor_amount: float = 1.0) -> pl.DataFrame:
    """A minimal OF 02.00 frame: row 0010 with the floor in col 0030, row 0034."""
    return pl.DataFrame(
        {
            "row_ref": ["0010", "0034"],
            "0010": [2.0, None],
            "0030": [floor_amount, activated],
        },
        schema={"row_ref": pl.String, "0010": pl.Float64, "0030": pl.Float64},
    )


def _state(
    *,
    binding: bool,
    reported: bool | None,
    shapes: frozenset[str] = frozenset(),
) -> FloorState:
    return FloorState(
        engine_binding=binding,
        reported_activated=reported,
        u_trea=100.0,
        floor_threshold=150.0 if binding else 50.0,
        shapes=shapes,
    )


def _ledger(rows: list[dict[str, object]]) -> pl.LazyFrame:
    """Sealed-ledger rows carrying only the four columns the shape census reads."""
    return pl.LazyFrame(
        rows,
        schema={
            "approach_applied": pl.String,
            "exposure_class": pl.String,
            "is_defaulted": pl.Boolean,
            "cp_apply_fi_scalar": pl.Boolean,
        },
    )


def _row(
    approach: str, exposure_class: str, *, defaulted: bool = False, lfse: bool = False
) -> dict[str, object]:
    return {
        "approach_applied": approach,
        "exposure_class": exposure_class,
        "is_defaulted": defaulted,
        "cp_apply_fi_scalar": lfse,
    }


# ---------------------------------------------------------------------------
# The reported state: OF 02.00 row 0034, column 0030
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cell", "expected"),
    [pytest.param(1.0, True, id="yes"), pytest.param(0.0, False, id="no")],
)
def test_the_reported_activation_is_row_0034_column_0030(cell: float, expected: bool) -> None:
    """Row 0034 decides, not row 0010's floor amount in the same column.

    Arrange: an OF 02.00 frame whose row 0010 column 0030 holds a non-zero floor.
    Act:     read the activation.
    Assert:  it follows row 0034 whichever value row 0010 holds.
    """
    # Arrange
    frame = _of_02_00(activated=cell, floor_amount=1.0)
    # Act
    activated = _reported_activation(frame)
    # Assert
    assert activated is expected


@pytest.mark.parametrize(
    "frame",
    [
        pytest.param(None, id="no-of-02-00"),
        pytest.param(_of_02_00(activated=None), id="null-cell"),
        pytest.param(_of_02_00(activated=1.0).filter(pl.col("row_ref") != "0034"), id="no-row"),
        pytest.param(_of_02_00(activated=1.0).drop("0030"), id="no-column"),
    ],
)
def test_an_unreported_activation_reads_as_unknown_not_as_no(frame: pl.DataFrame | None) -> None:
    """An empty cell is not a "No": it must not agree with a slack engine floor.

    Arrange: an OF 02.00 that states no activation, four ways.
    Act:     read the activation.
    Assert:  None, never False.
    """
    # Act
    activated = _reported_activation(frame)
    # Assert
    assert activated is None


# ---------------------------------------------------------------------------
# The states, per run
# ---------------------------------------------------------------------------


def test_a_run_whose_engine_and_reported_states_differ_is_a_disagreement() -> None:
    """Each kind of mismatch is found; two agreeing runs are not.

    Arrange: two agreeing runs and three that disagree — engine binds and the
             return says No, the reverse, and a return that says nothing.
    Act:     list the disagreements.
    Assert:  exactly the three.
    """
    # Arrange
    floors = {
        "b31/agree-binding": _state(binding=True, reported=True),
        "b31/agree-slack": _state(binding=False, reported=False),
        "b31/engine-only": _state(binding=True, reported=False),
        "b31/reported-only": _state(binding=False, reported=True),
        "b31/unreported": _state(binding=False, reported=None),
    }
    # Act
    disagreements = _activation_disagreements(floors)
    # Assert
    assert disagreements == ("b31/engine-only", "b31/reported-only", "b31/unreported")


def test_the_binding_set_is_the_runs_whose_engine_floor_binds() -> None:
    """The ENGINE state decides membership; the reported one is checked separately.

    Arrange: a binding run, a slack run, and a slack run whose return says Yes.
    Act:     take the binding set.
    Assert:  only the run the engine floors.
    """
    # Arrange
    floors = {
        "b31/bound": _state(binding=True, reported=True),
        "b31/slack": _state(binding=False, reported=False),
        "b31/misreported": _state(binding=False, reported=True),
    }
    # Act
    binding = _binding_runs(floors)
    # Assert
    assert binding == frozenset({"b31/bound"})


def test_each_state_holds_the_union_of_its_runs_shapes_and_both_are_always_named() -> None:
    """A state no run reaches is present and empty, not missing.

    Arrange: two slack runs with overlapping shapes and no binding run.
    Act:     group the shapes by state.
    Assert:  the slack union, and an empty binding set under its own name.
    """
    # Arrange
    floors = {
        "b31/a": _state(binding=False, reported=False, shapes=frozenset({"slotting"})),
        "b31/b": _state(binding=False, reported=False, shapes=frozenset({"slotting", "ccr"})),
    }
    # Act
    by_state = _shapes_by_state(floors)
    # Assert
    assert by_state == {"binding": frozenset(), "not binding": frozenset({"slotting", "ccr"})}


# ---------------------------------------------------------------------------
# The row shapes
# ---------------------------------------------------------------------------


def test_every_shape_is_found_on_a_ledger_that_holds_it() -> None:
    """One row per shape lights all six names the census banks.

    Arrange: an F-IRB corporate, an A-IRB retail, a slotting, a defaulted
             A-IRB retail, an F-IRB large financial sector entity and a CCR row.
    Act:     read the shapes.
    Assert:  every name in FLOOR_SHAPES.
    """
    # Arrange
    ledger = _ledger(
        [
            _row(ApproachType.FIRB.value, ExposureClass.CORPORATE.value),
            _row(ApproachType.AIRB.value, ExposureClass.RETAIL_QRRE.value),
            _row(ApproachType.SLOTTING.value, ExposureClass.SPECIALISED_LENDING.value),
            _row(ApproachType.AIRB.value, ExposureClass.RETAIL_OTHER.value, defaulted=True),
            _row(ApproachType.FIRB.value, ExposureClass.INSTITUTION.value, lfse=True),
            _row(SA_CCR_APPROACH, ExposureClass.INSTITUTION.value),
        ]
    )
    # Act
    shapes = _modelled_shapes(ledger)
    # Assert
    assert shapes == frozenset(FLOOR_SHAPES)


def test_no_shape_is_found_on_a_row_the_floor_does_not_reach() -> None:
    """A defaulted or LFSE row under the standardised approach, an A-IRB corporate
    and an equity row light nothing: the census is about the modelled book.

    Arrange: rows that carry each flag outside the modelled and CCR approaches.
    Act:     read the shapes.
    Assert:  none.
    """
    # Arrange
    ledger = _ledger(
        [
            _row(ApproachType.SA.value, ExposureClass.DEFAULTED.value, defaulted=True),
            _row(ApproachType.SA.value, ExposureClass.INSTITUTION.value, lfse=True),
            _row(ApproachType.SA.value, ExposureClass.RETAIL_OTHER.value),
            _row(ApproachType.AIRB.value, ExposureClass.CORPORATE.value),
            _row(ApproachType.EQUITY.value, ExposureClass.EQUITY.value),
        ]
    )
    # Act
    shapes = _modelled_shapes(ledger)
    # Assert
    assert shapes == frozenset()


def test_a_missing_shape_carrier_raises_rather_than_reading_as_absent() -> None:
    """A renamed carrier must fail loudly, not report a shape as never reached.

    Arrange: an otherwise LFSE-bearing ledger without ``cp_apply_fi_scalar``.
    Act / Assert: reading the shapes raises.
    """
    # Arrange
    ledger = _ledger(
        [_row(ApproachType.FIRB.value, ExposureClass.INSTITUTION.value, lfse=True)]
    ).drop("cp_apply_fi_scalar")
    # Act / Assert
    with pytest.raises(pl.exceptions.ColumnNotFoundError):
        _modelled_shapes(ledger)
