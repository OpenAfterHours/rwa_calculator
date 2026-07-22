"""
Unit tests: the report-template viewer view (ui.views.report_templates).

Pins the two things the grid must not get wrong:
- a NULL cell (an inert/empty row, or a source the engine never produces) reads
  differently from a reported 0.0 — conflating them would misstate the return;
- every value cell is addressable by its cell key (template, sheet, row_ref,
  col_ref), which is the handle the lineage drill-down will attach to.

Plus the header band (column groups) and the picker defaults.

References:
- docs/plans/report-cell-lineage.md §3 (Phase A — the template viewer)
"""

from __future__ import annotations

import math
from typing import Any

import polars as pl

from rwa_calc.reporting.catalog import ColumnHeader
from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.ui.views import report_templates as view

# =============================================================================
# Builders
# =============================================================================


def _corep(**fields: object) -> COREPTemplateBundle:
    base: dict[str, Any] = {"c07_00": {}, "c08_01": {}, "c08_02": {}}
    base.update(fields)
    return COREPTemplateBundle(**base)


def _c07_sheet() -> pl.DataFrame:
    """A C 07.00 slice: a reported RWEA, a reported zero, and a null cell."""
    return pl.DataFrame(
        {
            "row_ref": ["0010", "0015"],
            "row_name": ["Total exposures", "Of which: defaulted"],
            "0200": [1_000_000.0, 0.0],
            "0220": [1_000_000.0, None],
        }
    )


def _page(**kwargs: Any) -> view.TemplatePage:
    corep = _corep(c07_00={"corporate": _c07_sheet()})
    return view.template_page(corep, None, run_id="r1", framework="CRR", **kwargs)


# =============================================================================
# format_value — null is not zero
# =============================================================================


def test_null_and_zero_render_differently() -> None:
    # Act
    null_display, null_is_null = view.format_value(None)
    zero_display, zero_is_null = view.format_value(0.0)

    # Assert: a not-reported cell must never read as a reported zero.
    assert (null_display, null_is_null) == ("—", True)
    assert (zero_display, zero_is_null) == ("0", False)


def test_non_finite_renders_as_null() -> None:
    # Act / Assert: NaN/Inf blank the cell, matching the Excel export.
    assert view.format_value(math.nan) == ("—", True)
    assert view.format_value(math.inf) == ("—", True)


def test_magnitudes_and_rates_keep_their_precision() -> None:
    # Act / Assert: money is grouped; a sub-unit rate must not round to nothing.
    assert view.format_value(1_000_000.0) == ("1,000,000", False)
    assert view.format_value(12.5) == ("12.50", False)
    assert view.format_value(0.0345) == ("0.0345", False)


# =============================================================================
# The cell-key contract (what the drill-down will attach to)
# =============================================================================


def test_every_value_cell_is_addressable_by_its_column_ref() -> None:
    # Act
    page = _page(template_id="c07_00", sheet="corporate")

    # Assert: (template, sheet, row_ref, col_ref) fully addresses each cell.
    assert page.selected is not None
    assert page.selected.id == "c07_00"
    assert page.sheet == "corporate"
    assert [row.row_ref for row in page.rows] == ["0010", "0015"]
    assert [cell.ref for cell in page.rows[0].cells] == ["0200", "0220"]


def test_cells_carry_the_generators_values_and_null_flags() -> None:
    # Act
    page = _page(template_id="c07_00", sheet="corporate")

    # Assert: the reported RWEA, the reported zero, and the null all survive.
    total, defaulted = page.rows
    assert total.cells[1].display == "1,000,000"
    assert defaulted.cells[0] == view.TemplateCell(ref="0200", display="0", is_null=False)
    assert defaulted.cells[1] == view.TemplateCell(ref="0220", display="—", is_null=True)


# =============================================================================
# has_lineage — the drill-down signal (a cell is only linkable where lineage exists)
# =============================================================================


def test_has_lineage_true_for_an_instrumented_template() -> None:
    # Act — C 07.00 exposes its execution plans (LINEAGE_PLANS).
    page = _page(template_id="c07_00", sheet="corporate")

    # Assert
    assert page.selected is not None
    assert page.has_lineage is True


def test_has_lineage_false_for_an_uninstrumented_template() -> None:
    # Arrange — C 02.00 is the pre-pass kernel-plus-thin-shell hybrid that never
    # runs through the executor, so it exposes no TemplateSpec and is the durable
    # uninstrumentable example. (R27a instrumented the prior example, C 34.01 —
    # every DECLARATIVE template now carries lineage; only C 02.00 and the still
    # -imperative C 34.02 / CCR1-8 remain.)
    corep = _corep(c_02_00=_c07_sheet())

    # Act
    page = view.template_page(
        corep, None, run_id="r1", framework="CRR", template_id="c_02_00", sheet=None
    )

    # Assert — the grid still renders; no cell is offered as a drill-down link.
    assert page.selected is not None
    assert page.selected.id == "c_02_00"
    assert page.has_lineage is False


# =============================================================================
# Header band + picker defaults
# =============================================================================


def test_column_groups_collapse_into_header_spans() -> None:
    # Arrange
    columns = (
        ColumnHeader("0010", "Original exposure", "Exposure"),
        ColumnHeader("0030", "Value adjustments", "Exposure"),
        ColumnHeader("0220", "RWEA", "RWEA"),
    )

    # Act
    groups = view.column_groups(columns)

    # Assert
    assert groups == (view.ColumnGroup("Exposure", 2), view.ColumnGroup("RWEA", 1))


def test_ungrouped_columns_produce_no_header_band() -> None:
    # Act
    groups = view.column_groups((ColumnHeader("a", "Exposure value"),))

    # Assert: no band beats a band of one meaningless empty span.
    assert groups == ()


def test_page_defaults_to_the_first_template_and_sheet() -> None:
    # Act: neither template nor sheet named.
    page = _page()

    # Assert
    assert page.selected is not None
    assert page.selected.id == "c07_00"
    assert page.sheet == "corporate"


def test_unknown_template_keeps_the_picker_and_drops_the_grid() -> None:
    # Act
    page = _page(template_id="not_a_template")

    # Assert: what a run produced is data, not a contract — never raise.
    assert page.selected is None
    assert page.rows == ()
    assert [info.id for info in page.templates] == ["c07_00"]


def test_run_with_no_templates_renders_an_empty_page() -> None:
    # Act
    page = view.template_page(_corep(), None, run_id="r1", framework="CRR")

    # Assert
    assert page.templates == ()
    assert page.selected is None
    assert page.rows == ()
