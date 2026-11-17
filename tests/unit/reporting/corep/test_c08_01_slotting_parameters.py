"""C / OF 08.01 columns 0230 (LGD) and 0250 (maturity) on a sheet that holds slotting.

Why this file exists: a class sheet averaged LGD and maturity over EVERY leg's
exposure value, a leg with no value counting as zero. A slotting leg carries
neither (the engine seals ``lgd_floored`` and ``irb_maturity_m`` null on it), so
the specialised-lending sheet - Basel 3.1 sheet 0010 "Specialised Lending (FIRB
approach or slotting approach)", the CRR ``specialised_lending`` sheet, and the
CRR ``corporate`` sheet, which keeps corporate slotting beside corporate F-IRB -
reported 0.0 on a row of slotting exposure alone, and on a row that also holds
F-IRB specialised lending a diluted average: not the F-IRB legs' figure and not
anything else. The Totals already averaged only the legs that carry the
parameter (``corep/c08_sheets.py``); the class sheets now do the same, as column
0010 (PD) does since ``e8cb71c``.

The instruction, Basel 3.1 (PS1/26 Annex II §3.3.3, OF 08.01):
- column 0250, p.111: "This data shall not be reported for the exposure values
  for which the maturity is not an element in the calculation of risk-weighted
  exposure amounts. This column shall therefore not be filled in for the
  exposure class 'retail' or for exposures subject to the slotting approach."
- column 0230, p.111: "Data shall not be reported for specialised lending
  exposures subject to the slotting approach."

CRR (Reg (EU) 2021/451 Annex II, C 08.01): column 0230, p.103, excludes slotting
("Data shall not be reported for specialised lending exposures referred to in
Article 153(5) CRR"); column 0250, p.104, names retail only ("That means that
this column shall not be filled in for the exposure class 'retail'"), and
remaining maturity is an element of CRR slotting RWEA (Art. 153(5) Table 1). The
CRR cell is left empty all the same, on the ground that the engine carries no
Article 162 maturity for a slotting leg - one definition for both regimes, as
column 0010 has. Whether CRR C 08.01 should report a slotting maturity is a
separate, open question (IMPLEMENTATION_PLAN.md P2.74).

References:
- PRA PS1/26 Annex II §3.3.3 columns 0230 and 0250 (p.111)
- Reg (EU) 2021/451 Annex II C 08.01 columns 0230 (p.103) and 0250 (p.104)
- tests/unit/reporting/corep/test_c08_01_pd_column.py (column 0010, the precedent)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.reporting.cellspec import WeightedAvg
from rwa_calc.reporting.corep.c08 import c08_01_plans, c08_02_plans
from rwa_calc.reporting.corep.c08_sheets import parameter_weight
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator, with_reporting_ledger
from tests.unit.reporting.corep._irb_sheet_frames import (
    OF08_SPECIALISED_LENDING_FIRB_SLOTTING,
    OF08_TOTAL_FIRB_SLOTTING,
    cell,
    irb_sheet,
)
from tests.unit.reporting.corep.test_c08_01 import _irb_results_with_slotting
from tests.unit.reporting.corep.test_c08_01_pd_column import _mixed_specialised_lending

if TYPE_CHECKING:
    from collections.abc import Callable

    from rwa_calc.reporting.plans import SheetPlan

FRAMEWORKS = ("CRR", "BASEL_3_1")

#: Column -> (the parameter carrier, the scale the column reports it at).
#: Maturity is filed in days and sealed in years.
PARAMETERS: dict[str, tuple[str, float]] = {
    "0230": ("lgd_floored", 1.0),
    "0250": ("irb_maturity_m", 365.0),
}

#: The rows of the specialised-lending sheet the mixed book reaches: the total,
#: on-balance-sheet items and the obligor-grade (F-IRB / A-IRB) row.
MIXED_ROWS = ("0010", "0020", "0070")


def _mixed_book() -> pl.LazyFrame:
    """Two F-IRB specialised-lending legs and one slotting leg on one sheet.

    ``_mixed_specialised_lending`` with the F-IRB legs given different LGDs and
    maturities, so the average is exposure-weighted and not a constant:
    - SL_FIRB: EAD 4,000, LGD 40%, maturity 4 years.
    - SL_SLOT: slotting, EAD 6,000, no LGD and no maturity, as the engine seals it.
    - SL_FLOOR: EAD 1,000, LGD 30%, maturity 2 years.
    """
    return _mixed_specialised_lending().with_columns(
        pl.Series("lgd_floored", [0.40, None, 0.30]),
        pl.Series("irb_maturity_m", [4.0, None, 2.0]),
    )


def _averages(legs: pl.DataFrame, carrier: str, scale: float) -> tuple[float, float]:
    """(the average over the legs that carry ``carrier``, the average with every
    other leg counted as zero) - the figure due and the figure the defect filed."""
    weighted = float((legs[carrier].fill_null(0.0) * legs["ead_final"]).sum()) * scale
    carrying = float(legs.filter(pl.col(carrier).is_not_null())["ead_final"].sum())
    return weighted / carrying, weighted / float(legs["ead_final"].sum())


@pytest.mark.parametrize("column", sorted(PARAMETERS))
@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_slotting_leg_is_left_out_of_the_sheets_average(framework: str, column: str) -> None:
    # Arrange
    carrier, scale = PARAMETERS[column]
    legs = _mixed_book().collect()
    due, diluted = _averages(legs, carrier, scale)
    slotting = legs.filter(pl.col("approach_applied") == "slotting")
    assert slotting.height and slotting[carrier].is_null().all(), (
        "the sheet must hold a slotting leg with no parameter beside F-IRB legs, or "
        "leaving it out cannot be told from averaging it in"
    )
    assert due != pytest.approx(diluted)

    # Act
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(_mixed_book(), framework=framework)
    sheet = bundle.c08_01[
        irb_sheet(framework, "specialised_lending", OF08_SPECIALISED_LENDING_FIRB_SLOTTING)
    ]

    # Assert
    for row in MIXED_ROWS:
        assert cell(sheet, row, column) == pytest.approx(due, rel=1e-12), row
    assert cell(sheet, "0080", column) is None


@pytest.mark.parametrize("column", sorted(PARAMETERS))
@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_slotting_only_sheet_reports_no_lgd_and_no_maturity(framework: str, column: str) -> None:
    # Arrange
    generator = LedgerShimCorepGenerator()

    # Act
    bundle = generator.generate_from_lazyframe(_irb_results_with_slotting(), framework=framework)
    sheet = bundle.c08_01[
        irb_sheet(framework, "specialised_lending", OF08_SPECIALISED_LENDING_FIRB_SLOTTING)
    ]

    # Assert
    assert (cell(sheet, "0010", "0110") or 0.0) > 0, "the slotting sheet holds no exposure"
    for row in ("0010", "0020", "0080"):
        assert cell(sheet, row, column) is None, row


@pytest.mark.parametrize("column", sorted(PARAMETERS))
def test_crr_corporate_sheet_averages_its_f_irb_legs_beside_corporate_slotting(
    column: str,
) -> None:
    """CRR keeps corporate slotting on the corporate sheet (it keys sheets by
    exposure class), so that sheet mixes the two approaches on every registered
    shape that has corporate slotting."""
    # Arrange
    carrier, scale = PARAMETERS[column]
    legs = _irb_results_with_slotting().collect().filter(pl.col("exposure_class") == "corporate")
    due, diluted = _averages(legs, carrier, scale)
    assert due != pytest.approx(diluted), "no corporate slotting leg: nothing could dilute it"

    # Act
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(
        _irb_results_with_slotting(), framework="CRR"
    )

    # Assert
    assert cell(bundle.c08_01["corporate"], "0010", column) == pytest.approx(due, rel=1e-12)


@pytest.mark.parametrize("column", sorted(PARAMETERS))
def test_b31_firb_and_slotting_total_is_unchanged_by_the_class_sheets(column: str) -> None:
    """GUARD, green before and after the fix: Total 0002 already averaged only
    the legs that carry the parameter (``c08_sheets._averaged_cells``), so a
    class sheet that stops averaging slotting in moves nothing on it."""
    # Arrange - every leg of the book is F-IRB or slotting, so all are on the Total.
    carrier, scale = PARAMETERS[column]
    legs = _irb_results_with_slotting().collect()
    due, _diluted = _averages(legs, carrier, scale)

    # Act
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(
        _irb_results_with_slotting(), framework="BASEL_3_1"
    )

    # Assert
    assert cell(bundle.c08_01[OF08_TOTAL_FIRB_SLOTTING], "0010", column) == pytest.approx(
        due, rel=1e-12
    )


@pytest.mark.parametrize("plans", [c08_01_plans, c08_02_plans], ids=["C08.01", "C08.02"])
@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_every_parameter_average_weighs_only_the_legs_that_carry_the_parameter(
    framework: str, plans: Callable[..., dict[str, SheetPlan]]
) -> None:
    """The structural form of the two tests above, for every average the shared
    C / OF 08.01-08.02 spec binds, today's and any added later. ``cellspec``
    fills a ``WeightedAvg`` parameter's nulls with 0.0 and keeps the leg's weight,
    so an average weighted by the raw exposure value counts a leg with no value
    as zero. Weighted by ``parameter_weight`` (null where the parameter is null)
    it leaves the leg out."""
    # Arrange
    frame = with_reporting_ledger(_mixed_book())
    cols = set(frame.collect_schema().names())

    # Act
    averages = {
        (sheet, address): cell.binding
        for sheet, plan in plans(frame, cols, framework, []).items()
        for address, cell in plan.spec.cells.items()
        if isinstance(cell.binding, WeightedAvg)
    }

    # Assert
    assert {col for _sheet, (_row, col) in averages} >= {"0010", "0230", "0250"}
    assert {
        place: binding.weight
        for place, binding in averages.items()
        if binding.weight != parameter_weight(binding.col)
    } == {}
