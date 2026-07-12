"""
Unit tests: the template catalogue (reporting.catalog).

Pins the uniform view the report-template viewer (and, later, the cell
drill-down) reads the two generator bundles through:
- the index lists only templates that HAVE content, and carries the sheet keys
  of per-sheet templates;
- a sheet resolves to the generator's frame verbatim, plus readable column
  headers taken from the frozen per-template column definitions;
- the FRAME is authoritative for which columns exist (regime variants), and an
  undefined column falls back to its ref rather than vanishing — a missing label
  must never hide a reported cell.

References:
- docs/plans/report-cell-lineage.md §3 (Phase A — the template viewer)
"""

from __future__ import annotations

import polars as pl

from rwa_calc.reporting import catalog
from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle

# =============================================================================
# Builders
# =============================================================================


def _sheet(*refs: str) -> pl.DataFrame:
    """A minimal template frame: the two structural columns plus value refs."""
    data: dict[str, list[object]] = {"row_ref": ["0010"], "row_name": ["Total exposures"]}
    for i, ref in enumerate(refs):
        data[ref] = [float(i)]
    return pl.DataFrame(data)


def _corep(**fields: object) -> COREPTemplateBundle:
    base: dict[str, object] = {"c07_00": {}, "c08_01": {}, "c08_02": {}}
    base.update(fields)
    return COREPTemplateBundle(**base)  # type: ignore[arg-type]


# =============================================================================
# template_index
# =============================================================================


def test_index_lists_only_templates_with_content() -> None:
    # Arrange: one populated per-sheet template; every other field empty/None.
    corep = _corep(c07_00={"corporate": _sheet("0010")})

    # Act
    infos = catalog.template_index(corep, None)

    # Assert: the empty dicts and the None frames are absent, not empty entries.
    assert [info.id for info in infos] == ["c07_00"]


def test_index_carries_sheet_keys_sorted_and_labelled() -> None:
    # Arrange
    corep = _corep(c09_01={"GB": _sheet("0010"), "DE": _sheet("0010")})

    # Act
    (info,) = catalog.template_index(corep, None)

    # Assert
    assert info.sheets == ("DE", "GB")
    assert info.sheet_label == "Country"


def test_index_single_frame_template_has_no_sheets() -> None:
    # Arrange
    corep = _corep(c_02_00=_sheet("0010"))

    # Act
    (info,) = catalog.template_index(corep, None)

    # Assert
    assert info.sheets == ()
    assert info.family == "corep"


def test_index_spans_both_bundles_in_catalogue_order() -> None:
    # Arrange
    corep = _corep(c07_00={"corporate": _sheet("0010")})
    pillar3 = Pillar3TemplateBundle(cr4=_sheet("a"))

    # Act
    infos = catalog.template_index(corep, pillar3)

    # Assert: COREP precedes Pillar 3, and each is tagged with its family.
    assert [(info.id, info.family) for info in infos] == [
        ("c07_00", "corep"),
        ("cr4", "pillar3"),
    ]


# =============================================================================
# template_sheet
# =============================================================================


def test_sheet_resolves_frame_and_named_headers() -> None:
    # Arrange: real CRR C 07.00 refs — 0200 exposure value, 0220 RWEA.
    corep = _corep(c07_00={"corporate": _sheet("0200", "0220")})

    # Act
    view = catalog.template_sheet(corep, None, "c07_00", "corporate")

    # Assert: headers carry the regulatory names/groups, not just the refs.
    assert view is not None
    assert view.sheet == "corporate"
    assert [col.ref for col in view.columns] == ["0200", "0220"]
    assert all(col.name != col.ref for col in view.columns)
    assert view.columns[1].group == "RWEA"


def test_sheet_excludes_the_structural_columns() -> None:
    # Arrange
    corep = _corep(c07_00={"corporate": _sheet("0220")})

    # Act
    view = catalog.template_sheet(corep, None, "c07_00", "corporate")

    # Assert: row_ref / row_name are row identity, never addressable value cells.
    assert view is not None
    refs = [col.ref for col in view.columns]
    assert refs == ["0220"]
    assert not set(refs) & set(catalog.STRUCTURAL_COLS)


def test_sheet_defaults_to_the_first_sheet() -> None:
    # Arrange
    corep = _corep(c09_01={"GB": _sheet("0010"), "DE": _sheet("0010")})

    # Act: no sheet named — a caller can link to a template without knowing keys.
    view = catalog.template_sheet(corep, None, "c09_01")

    # Assert
    assert view is not None
    assert view.sheet == "DE"


def test_sheet_frame_is_the_generators_frame_verbatim() -> None:
    # Arrange
    frame = _sheet("0220")
    corep = _corep(c07_00={"corporate": frame})

    # Act
    view = catalog.template_sheet(corep, None, "c07_00", "corporate")

    # Assert: the catalogue never recomputes, re-signs or re-fills a cell.
    assert view is not None
    assert view.frame.equals(frame)


def test_undefined_column_falls_back_to_its_ref() -> None:
    # Arrange: a ref with no definition in C 07.00's column set.
    corep = _corep(c07_00={"corporate": _sheet("9999")})

    # Act
    view = catalog.template_sheet(corep, None, "c07_00", "corporate")

    # Assert: rendered as a bare ref rather than dropped — never hide a cell.
    assert view is not None
    assert view.columns == (catalog.ColumnHeader(ref="9999", name="9999", group=""),)


def test_headers_follow_the_frame_not_the_definitions() -> None:
    # Arrange: the frame carries only ONE of C 07.00's many defined columns.
    corep = _corep(c07_00={"corporate": _sheet("0220")})

    # Act
    view = catalog.template_sheet(corep, None, "c07_00", "corporate")

    # Assert: the regime's frame decides the column set (CRR vs B31 variants).
    assert view is not None
    assert len(view.columns) == 1


def test_unknown_template_and_unknown_sheet_resolve_to_none() -> None:
    # Arrange
    corep = _corep(c07_00={"corporate": _sheet("0220")})

    # Act / Assert
    assert catalog.template_sheet(corep, None, "not_a_template") is None
    assert catalog.template_sheet(corep, None, "c07_00", "retail") is None
    assert catalog.template_sheet(corep, None, "c08_01", "corporate") is None
