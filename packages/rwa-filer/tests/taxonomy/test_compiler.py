"""
The taxonomy pack compiler: publisher workbooks and taxonomy in, a pack dict out.

Pipeline position:
    annotated templates + DPM dictionary + taxonomy package
        -> compiler.compile_pack -> compiled pack (format 1)

The publisher's files are not redistributed, so these tests compile a miniature
module that ``taxonomy_builders`` lays out the way the Bank of England lays out
its own: the same sheet anatomy, the same linkbase shapes. The real files are
exercised by the opt-in ``test_compiler_integration.py``.

Key responsibilities pinned here:
- One annotation cell parses to a metric (optionally with its enumeration
  hierarchy), a dimension header or a member — and to nothing else.
- A fixed z-axis entry parses per dimension; the EMPTY entry is the all-default
  sheet, whose code and label only the taxonomy can supply.
- The grid is found from grey code cells alone, closed or open-row.
- REPORTABILITY is the taxonomy's: a greyed cell the hypercubes accept is emitted
  and flagged ``"linkbase"``; a white cell they reject is dropped and recorded.
- A stated default member is dropped from the data point.
- The result is deterministic, and identical from a zipped or an extracted package.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import taxonomy_builders as builders
from rwa_filer.taxonomy import _linkbase, _workbook, compiler

DEFAULTS = {"eba_dim:BAS": "eba_BA:x0", "eba_dim:MCY": "eba_MC:x0", "eba_dim:CUE": "eba_CU:x0"}


@dataclass(frozen=True)
class Publisher:
    """Paths of the three miniature inputs."""

    annotated: Path
    dictionary: Path
    taxonomy: Path


@pytest.fixture(scope="module")
def publisher(tmp_path_factory: pytest.TempPathFactory) -> Publisher:
    root = tmp_path_factory.mktemp("publisher")
    return Publisher(
        annotated=builders.build_annotated_workbook(root / "Annotated Templates v9.9.9 Demo.xlsx"),
        dictionary=builders.build_dictionary_workbook(root / "DPM dictionary v9.9.9.xlsx"),
        taxonomy=builders.build_taxonomy_package(root / "taxonomy"),
    )


@pytest.fixture(scope="module")
def pack(publisher: Publisher) -> dict[str, Any]:
    return compiler.compile_pack(
        publisher.annotated, publisher.dictionary, publisher.taxonomy, module=builders.MODULE
    )


@pytest.fixture(scope="module")
def workbook(publisher: Publisher) -> _workbook.AnnotatedWorkbook:
    return _workbook.read_annotated_workbook(publisher.annotated)


def _layout(workbook: _workbook.AnnotatedWorkbook, publisher: Publisher, table: str) -> Any:
    notes: list[str] = []
    layout = compiler.read_table_layout(
        workbook.sheets[table],
        workbook,
        _workbook.read_dictionary(publisher.dictionary),
        compiler.Recorder(table, notes),
    )
    assert layout is not None, notes
    return layout


def _cubes(*cubes: tuple[Any, ...], park: tuple[bool, ...] = ()) -> _linkbase.Hypercubes:
    text = builders.definition_linkbase(list(cubes), park_last_dimension=park)
    return _linkbase.read_hypercubes(io.BytesIO(text.encode()))


# ── Parsing one annotation cell ───────────────────────────────────────────────


def test_metric_annotation_yields_its_qname() -> None:
    # Arrange
    text = "eba_met:mi180 (Original exposure pre conversion factors)"

    # Act
    parsed = compiler.parse_metric(text)

    # Assert
    assert parsed == ("eba_met:mi180", None)


def test_enumeration_metric_annotation_names_its_hierarchy() -> None:
    # Arrange
    text = "eba_met:ei555 (Type of entity) [eba_ZZ:eba_ZZ14]"

    # Act
    parsed = compiler.parse_metric(text)

    # Assert
    assert parsed == ("eba_met:ei555", "eba_ZZ:eba_ZZ14")


@pytest.mark.parametrize("text", ["Metrics", "eba_BA:x9 (Exposures)", "eba_dim:BAS (Base)", "0010"])
def test_non_metric_cell_is_not_a_metric(text: str) -> None:
    # Act
    parsed = compiler.parse_metric(text)

    # Assert
    assert parsed is None


def test_member_annotation_yields_its_qname_even_with_brackets_in_the_label() -> None:
    # Arrange
    text = "boe_eba_CT:x10023 (SME (PRA definition))"

    # Act
    member = compiler.parse_member(text)

    # Assert
    assert member == "boe_eba_CT:x10023"


@pytest.mark.parametrize("text", ["eba_dim:BAS (Base)", "eba_met:mi1 (Amount)", "Total", ""])
def test_dimension_metric_and_plain_text_are_not_members(text: str) -> None:
    # Act
    member = compiler.parse_member(text)

    # Assert
    assert member is None


def test_dimension_header_yields_the_dimension() -> None:
    # Act
    header = compiler.parse_dimension_header("eba_dim:PDT (PD Range (Typed))")
    not_header = compiler.parse_dimension_header("eba_BA:x9 (Exposures)")

    # Assert
    assert header == "eba_dim:PDT"
    assert not_header is None


# ── Z-axis entries, axis labels, key comments ─────────────────────────────────


def test_fixed_sheet_entry_collects_one_member_per_dimension() -> None:
    # Arrange — labels with brackets and a colon, as the publisher writes them
    entry = (
        "Securitisations (SEC-SA) (0010): eba_dim:MRW (Methods (risk weights)) eba_AP:x122 (SEC-SA)"
        " | Securitisations (SEC-SA) (0010): eba_dim:APR (Approach) eba_AP:x42 (Standardised)"
    )

    # Act
    sheet = compiler.parse_sheet_entry(entry)

    # Assert
    assert sheet == compiler.SheetEntry(
        code="0010",
        label="Securitisations (SEC-SA)",
        members=(("eba_dim:APR", "eba_AP:x42"), ("eba_dim:MRW", "eba_AP:x122")),
    )


def test_empty_sheet_entry_is_the_all_default_sheet_without_code_or_label() -> None:
    # Act
    sheet = compiler.parse_sheet_entry("")

    # Assert
    assert sheet == compiler.SheetEntry(code=None, label=None, members=())


@pytest.mark.parametrize(
    "entry",
    [
        "eba_CU:EUR (Euro)",  # a bare member, not a sheet definition
        "Euro (0002): eba_dim:CUE (Currency) eba_CU:EUR (Euro) | Lek (0003): eba_dim:APR (A) eba_AP:x1 (B)",
    ],
)
def test_malformed_sheet_entry_is_rejected(entry: str) -> None:
    # Act
    sheet = compiler.parse_sheet_entry(entry)

    # Assert
    assert sheet is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Sheets (Z1)", ("Z1", "Sheets")),
        ("Portfolios (0001)", ("0001", "Portfolios")),
        ('Country "mandatory" (0001)', ("0001", "Country")),
        ('Desk number "mandatory" (0005) String used as an identifier', ("0005", "Desk number")),
        ("No code here", (None, "No code here")),
    ],
)
def test_axis_label_splits_into_code_and_label(text: str, expected: tuple[str | None, str]) -> None:
    # Act
    parsed = compiler.parse_axis_label(text)

    # Assert
    assert parsed == expected


def test_key_comment_distinguishes_typed_from_listed_dimensions() -> None:
    # Act
    typed = compiler.parse_key_comment("eba_dim:LGS (Entity in Group Solvency)")
    listed = compiler.parse_key_comment(
        "eba_dim:IGS (Is LEI Code) = eba_exp:BT - BT3 (Type of Entity Code (LEI or Non-LEI))"
    )
    garbage = compiler.parse_key_comment("see the instructions")

    # Assert
    assert typed == ("eba_dim:LGS", False)
    assert listed == ("eba_dim:IGS", True)
    assert garbage is None


def test_stated_default_member_is_dropped_from_a_data_point() -> None:
    # Arrange
    dims = {"eba_dim:BAS": "eba_BA:x0", "eba_dim:MCY": "eba_MC:x1"}

    # Act
    kept = compiler.drop_default_members(dims, DEFAULTS)

    # Assert
    assert kept == {"eba_dim:MCY": "eba_MC:x1"}


@pytest.mark.parametrize(
    ("prefix", "uri"),
    [
        ("eba_met", "http://www.eba.europa.eu/xbrl/crr/dict/met"),
        ("eba_AP", "http://www.eba.europa.eu/xbrl/crr/dict/dom/AP"),
        ("boe_dim", "http://www.bankofengland.co.uk/data/xbrl/dict/dim"),
        ("boe_eba_AP", "http://www.bankofengland.co.uk/data/xbrl/dict/dom/eba_AP"),
        ("eba_typ", "http://www.eba.europa.eu/xbrl/crr/dict/typ"),
    ],
)
def test_namespace_follows_the_publishers_prefix_rule(prefix: str, uri: str) -> None:
    # Act
    namespace = compiler.namespace_for_prefix(prefix)

    # Assert
    assert namespace == uri


# ── Reading the workbook ──────────────────────────────────────────────────────


def test_grey_fill_marks_headers_and_non_reportable_cells(
    workbook: _workbook.AnnotatedWorkbook,
) -> None:
    # Arrange
    sheet = workbook.sheets[builders.CLOSED_TABLE]

    # Act
    greyed_cell, white_cell, header = sheet.is_grey(8, 5), sheet.is_grey(8, 4), sheet.is_grey(6, 4)

    # Assert
    assert greyed_cell is True
    assert white_cell is False
    assert header is True


def test_dropdown_and_comment_survive_reading(workbook: _workbook.AnnotatedWorkbook) -> None:
    # Act — both are discarded by a plain cell read, and both carry layout
    dropdown = workbook.sheets[builders.CLOSED_TABLE].dropdown_at(3, 2)
    comment = workbook.sheets[builders.OPEN_TABLE].comments.get((4, 1))

    # Assert
    assert dropdown == "Enumerations!$A$1:$B$1"
    assert comment == "eba_dim:UDI (Unique desk identifier)"


def test_enumeration_range_keeps_its_empty_entry(workbook: _workbook.AnnotatedWorkbook) -> None:
    # Act
    entries = workbook.enumeration("Enumerations!$A$1:$B$1")

    # Assert
    assert entries is not None
    assert entries[0] == ""
    assert entries[1].startswith("Euro (0002): eba_dim:CUE")


def test_table_of_contents_gives_modules_groups_and_membership(
    workbook: _workbook.AnnotatedWorkbook,
) -> None:
    # Act
    contents = workbook.contents

    # Assert
    assert contents.modules == {"DEMO01": "DEMO01 Demo module"}
    assert contents.group_of == {
        builders.CLOSED_TABLE: "T01.00.01",
        builders.OPEN_TABLE: "T02.00.01",
    }
    assert contents.modules_of[builders.CLOSED_TABLE] == ("DEMO01",)


def test_closed_grid_is_found_from_its_code_row_and_code_column(
    workbook: _workbook.AnnotatedWorkbook, publisher: Publisher
) -> None:
    # Act
    grid = _layout(workbook, publisher, builders.CLOSED_TABLE).grid

    # Assert
    assert (grid.code_row, grid.code_column, grid.key_columns) == (6, 3, ())
    assert [(line.code, line.label) for line in grid.rows] == [
        ("0010", "Total"),
        ("0020", "Of which: part"),
    ]
    assert [(line.code, line.label) for line in grid.columns] == [
        ("0010", "Amount"),
        ("0020", "Other"),
    ]


def test_open_row_grid_has_key_columns_and_one_template_row(
    workbook: _workbook.AnnotatedWorkbook, publisher: Publisher
) -> None:
    # Act
    grid = _layout(workbook, publisher, builders.OPEN_TABLE).grid

    # Assert
    assert (grid.code_row, grid.code_column, grid.key_columns) == (4, None, (1,))
    assert grid.rows == ()
    assert [(line.code, line.index) for line in grid.data_rows] == [(None, 5)]
    assert [line.code for line in grid.columns] == ["0010"]


def test_sheet_without_code_cells_is_recorded_not_raised() -> None:
    # Arrange
    sheet = _workbook.SheetGrid("X", {(1, 1): "X - X EMPTY"}, frozenset(), (), {}, ())
    notes: list[str] = []

    # Act
    grid = compiler.detect_grid(sheet, compiler.Recorder("X", notes))

    # Assert
    assert grid is None
    assert len(notes) == 1
    assert notes[0].startswith("X: skipped")


def test_layout_reads_the_fixed_axis_with_its_unnamed_default_sheet(
    workbook: _workbook.AnnotatedWorkbook, publisher: Publisher
) -> None:
    # Act
    axes = _layout(workbook, publisher, builders.CLOSED_TABLE).axes

    # Assert — the workbook alone cannot name the all-default sheet
    assert axes == (
        compiler.FixedAxis(
            code="Z1",
            label="Sheets",
            sheets=(
                compiler.SheetEntry(None, None, ()),
                compiler.SheetEntry("0002", "Euro", (("eba_dim:CUE", "eba_CU:EUR"),)),
            ),
        ),
    )


def test_layout_reads_row_and_column_annotations(
    workbook: _workbook.AnnotatedWorkbook, publisher: Publisher
) -> None:
    # Act
    layout = _layout(workbook, publisher, builders.CLOSED_TABLE)

    # Assert
    assert layout.column_annotations == {
        4: compiler.Annotation("eba_met:mi1", None, {"eba_dim:BAS": "eba_BA:x9"}),
        5: compiler.Annotation("eba_met:mi2", None, {"eba_dim:BAS": "eba_BA:x0"}),
    }
    assert layout.row_annotations == {
        7: compiler.Annotation(None, None, {"eba_dim:MCY": "eba_MC:x1"}),
        8: compiler.Annotation(None, None, {"eba_dim:MCY": "eba_MC:x2"}),
    }


def test_layout_reads_a_typed_key_from_the_header_and_its_comment(
    workbook: _workbook.AnnotatedWorkbook, publisher: Publisher
) -> None:
    # Act
    keys = _layout(workbook, publisher, builders.OPEN_TABLE).open_keys

    # Assert
    assert keys == (
        compiler.OpenKey(
            code="0005",
            label="Desk number",
            dimension="eba_dim:UDI",
            kind="typed",
            typed_element="eba_typ:IS",
            typed_type="string",
            members=(),
            default_allowed=False,
        ),
    )


def test_dictionary_gives_types_typed_elements_and_defaults(publisher: Publisher) -> None:
    # Act
    dictionary = _workbook.read_dictionary(publisher.dictionary)

    # Assert
    assert dictionary.metrics["eba_met:mi1"].type == "monetary"
    assert dictionary.metrics["eba_met:si3"].type == "string"
    assert dictionary.dimensions["eba_dim:BAS"].default == "eba_BA:x0"
    assert dictionary.dimensions["eba_dim:BAS"].kind == "explicit"
    assert dictionary.dimensions["eba_dim:UDI"].typed_element == "eba_typ:IS"
    assert dictionary.dimensions["eba_dim:UDI"].default is None


# ── Hypercubes: the taxonomy's reportability test ─────────────────────────────

BASE_AND_CATEGORY = [("eba_BAS", "eba_BA", "ba", ["x9"]), ("eba_MCY", "eba_MC", "mc", ["x0", "x1"])]


def test_data_point_inside_a_hypercube_is_accepted() -> None:
    # Arrange
    cubes = _cubes(("eba_mi1", BASE_AND_CATEGORY, []))
    fixed = {"eba_dim:BAS": "eba_BA:x9", "eba_dim:MCY": "eba_MC:x1"}

    # Act
    accepted = _linkbase.accepts(cubes, "eba_met:mi1", fixed, (), DEFAULTS)

    # Assert
    assert accepted is True


@pytest.mark.parametrize(
    ("metric", "fixed", "why"),
    [
        (
            "eba_met:mi1",
            {"eba_dim:BAS": "eba_BA:x9", "eba_dim:MCY": "eba_MC:x2"},
            "member not allowed",
        ),
        (
            "eba_met:mi1",
            {"eba_dim:MCY": "eba_MC:x1"},
            "absent dimension whose default is not allowed",
        ),
        (
            "eba_met:mi1",
            {"eba_dim:BAS": "eba_BA:x9", "eba_dim:CUE": "eba_CU:EUR"},
            "dimension outside a closed hypercube",
        ),
        ("eba_met:mi9", {"eba_dim:BAS": "eba_BA:x9"}, "metric with no hypercube"),
    ],
)
def test_data_point_outside_every_hypercube_is_rejected(
    metric: str, fixed: dict[str, str], why: str
) -> None:
    # Arrange
    cubes = _cubes(("eba_mi1", BASE_AND_CATEGORY, []))

    # Act
    accepted = _linkbase.accepts(cubes, metric, fixed, (), DEFAULTS)

    # Assert
    assert accepted is False, why


def test_absent_dimension_is_accepted_when_its_default_is_allowed() -> None:
    # Arrange — MCY lists x0, its default, so a data point may omit MCY
    cubes = _cubes(("eba_mi1", BASE_AND_CATEGORY, []))

    # Act
    accepted = _linkbase.accepts(cubes, "eba_met:mi1", {"eba_dim:BAS": "eba_BA:x9"}, (), DEFAULTS)

    # Assert
    assert accepted is True


def test_typed_dimension_is_accepted_only_as_an_open_axis() -> None:
    # Arrange — a hypercube-dimension arc with no domain is a typed dimension
    cubes = _cubes(
        ("eba_si3", [("eba_BAS", "eba_BA", "ba", ["x9"]), ("eba_UDI", None, None, [])], [])
    )
    fixed = {"eba_dim:BAS": "eba_BA:x9"}

    # Act
    with_key = _linkbase.accepts(cubes, "eba_met:si3", fixed, {"eba_dim:UDI"}, DEFAULTS)
    without_key = _linkbase.accepts(cubes, "eba_met:si3", fixed, (), DEFAULTS)

    # Assert
    assert with_key is True
    assert without_key is False


def test_members_parked_in_a_target_role_are_followed() -> None:
    # Arrange — the last dimension's members live in another link role
    cubes = _cubes(
        ("eba_mi1", BASE_AND_CATEGORY, [("eba_CUE", "eba_CU", "cu", ["EUR"])]), park=(True,)
    )
    fixed = {"eba_dim:BAS": "eba_BA:x9", "eba_dim:MCY": "eba_MC:x1"}

    # Act
    in_list = _linkbase.accepts(
        cubes, "eba_met:mi1", fixed | {"eba_dim:CUE": "eba_CU:EUR"}, (), DEFAULTS
    )
    not_in_list = _linkbase.accepts(
        cubes, "eba_met:mi1", fixed | {"eba_dim:CUE": "eba_CU:USD"}, (), DEFAULTS
    )

    # Assert
    assert cubes["eba_met:mi1"][0]["eba_dim:CUE"] == frozenset({"eba_CU:EUR"})
    assert in_list is True
    assert not_in_list is False


@pytest.mark.parametrize(
    ("href", "qname"),
    [
        ("http://www.eba.europa.eu/eu/fr/xbrl/crr/dict/dom/ap/mem.xsd#eba_x42", "eba_AP:x42"),
        ("../../../../../../dict/dom/eba_ap/mem.xsd#boe_x10050", "boe_eba_AP:x10050"),
        ("../../../../../../dict/dom/in/mem.xsd#boe_x6001", "boe_IN:x6001"),
        ("../../../../../../dict/met/met.xsd#boe_mi10047", "boe_met:mi10047"),
        ("http://www.eba.europa.eu/eu/fr/xbrl/crr/dict/dim/dim.xsd#eba_BAS", "eba_dim:BAS"),
        ("http://www.eba.europa.eu/eu/fr/xbrl/crr/dict/dom/exp.xsd#eba_AP", "eba_exp:AP"),
    ],
)
def test_dictionary_locator_maps_to_the_instance_qname(href: str, qname: str) -> None:
    # Act
    mapped = _linkbase.href_to_qname(href)

    # Assert
    assert mapped == qname


def test_module_listing_gives_entry_point_and_filing_indicators(publisher: Publisher) -> None:
    # Arrange
    package = _linkbase.TaxonomyPackage.open(publisher.taxonomy)

    # Act
    listing = _linkbase.read_module(package, builders.MODULE)

    # Assert
    assert listing.entry_point == builders.ENTRY_POINT
    assert {code: table.filing_indicator for code, table in listing.tables.items()} == {
        builders.CLOSED_TABLE: "T01.00.01",
        builders.OPEN_TABLE: builders.OPEN_TABLE,
    }


# ── compile_pack end to end ───────────────────────────────────────────────────


def test_pack_has_the_format_1_sections_in_order(pack: dict[str, Any]) -> None:
    # Assert
    assert list(pack) == [
        "format",
        "info",
        "namespaces",
        "metrics",
        "dimensions",
        "enumerations",
        "tables",
        "datapoints",
    ]
    assert pack["format"] == 1
    assert list(pack["tables"]) == [builders.CLOSED_TABLE, builders.OPEN_TABLE]
    assert list(pack["tables"][builders.CLOSED_TABLE]) == [
        "title",
        "group",
        "filing_indicator",
        "rows",
        "columns",
        "open_rows",
        "open_keys",
        "z",
        "cells",
    ]


def test_cells_are_exactly_those_the_hypercubes_accept(pack: dict[str, Any]) -> None:
    # Act
    cells = pack["tables"][builders.CLOSED_TABLE]["cells"]

    # Assert — the whole list: what is absent matters as much as what is present.
    # r0020/c0010 is white in the workbook but rejected, so it is not here;
    # r0020/c0020 is greyed in the workbook but accepted, so it is, flagged.
    assert cells == [
        ["0010", "0010", "0001", 0, "workbook"],
        ["0010", "0010", "0002", 1, "workbook"],
        ["0010", "0020", "0001", 2, "workbook"],
        ["0010", "0020", "0002", 3, "workbook"],
        ["0020", "0020", "0001", 4, "linkbase"],
        ["0020", "0020", "0002", 5, "linkbase"],
    ]


def test_data_points_are_interned_in_first_use_order_with_sorted_dimensions(
    pack: dict[str, Any],
) -> None:
    # Assert — BAS=x0 on column 0020 is a stated default and is dropped
    assert pack["datapoints"] == [
        ["eba_met:mi1", ["eba_dim:BAS", "eba_BA:x9", "eba_dim:MCY", "eba_MC:x1"]],
        [
            "eba_met:mi1",
            ["eba_dim:BAS", "eba_BA:x9", "eba_dim:CUE", "eba_CU:EUR", "eba_dim:MCY", "eba_MC:x1"],
        ],
        ["eba_met:mi2", ["eba_dim:MCY", "eba_MC:x1"]],
        ["eba_met:mi2", ["eba_dim:CUE", "eba_CU:EUR", "eba_dim:MCY", "eba_MC:x1"]],
        ["eba_met:mi2", ["eba_dim:MCY", "eba_MC:x2"]],
        ["eba_met:mi2", ["eba_dim:CUE", "eba_CU:EUR", "eba_dim:MCY", "eba_MC:x2"]],
        ["eba_met:si3", ["eba_dim:BAS", "eba_BA:x9", "eba_dim:UDI", "*typed:eba_typ:IS"]],
    ]


def test_rejected_white_cell_and_promoted_grey_cell_are_recorded(pack: dict[str, Any]) -> None:
    # Act
    notes = [n for n in pack["info"]["irregularities"] if n.startswith(builders.CLOSED_TABLE)]

    # Assert
    assert any("2 white cells are rejected" in n and "r0020/c0010" in n for n in notes), notes
    assert any(
        "2 cells greyed in the workbook are accepted" in n and "r0020/c0020" in n for n in notes
    )
    assert any("default member eba_dim:BAS=eba_BA:x0" in n for n in notes), notes


def test_all_default_sheet_is_named_by_the_taxonomy(pack: dict[str, Any]) -> None:
    # Act
    axis = pack["tables"][builders.CLOSED_TABLE]["z"]

    # Assert
    assert axis == [
        {
            "kind": "fixed",
            "code": "Z1",
            "label": "Sheets",
            "sheets": [
                {"code": "0001", "label": "Total", "members": []},
                {"code": "0002", "label": "Euro", "members": [["eba_dim:CUE", "eba_CU:EUR"]]},
            ],
        }
    ]


def test_filing_indicator_and_group_come_from_their_own_sources(pack: dict[str, Any]) -> None:
    # Act
    closed, opened = pack["tables"][builders.CLOSED_TABLE], pack["tables"][builders.OPEN_TABLE]

    # Assert — the group is the workbook's; the indicator only the taxonomy knows,
    # and for the open table it is NOT the group code
    assert (closed["group"], closed["filing_indicator"]) == ("T01.00.01", "T01.00.01")
    assert (opened["group"], opened["filing_indicator"]) == ("T02.00.01", builders.OPEN_TABLE)


def test_open_row_table_has_a_typed_key_and_a_row_less_cell(pack: dict[str, Any]) -> None:
    # Act
    table = pack["tables"][builders.OPEN_TABLE]

    # Assert
    assert table["open_rows"] is True
    assert table["rows"] == []
    assert table["open_keys"] == [
        {
            "code": "0005",
            "label": "Desk number",
            "dimension": "eba_dim:UDI",
            "kind": "typed",
            "typed_element": "eba_typ:IS",
            "typed_type": "string",
            "members": [],
        }
    ]
    assert table["cells"] == [[None, "0010", None, 6, "workbook"]]


def test_info_names_the_module_version_entry_point_and_sources(
    pack: dict[str, Any], publisher: Publisher
) -> None:
    # Act
    info = {k: v for k, v in pack["info"].items() if k != "irregularities"}

    # Assert
    assert info == {
        "module": "DEMO01",
        "title": "DEMO01 Demo module",
        "taxonomy": "boe-banking",
        "version": "9.9.9",
        "entry_point": builders.ENTRY_POINT,
        "sources": {
            "annotated_workbook": publisher.annotated.name,
            "dictionary_workbook": publisher.dictionary.name,
            "taxonomy_package": "taxonomy",
        },
    }


def test_dictionary_sections_cover_every_metric_dimension_and_prefix(pack: dict[str, Any]) -> None:
    # Assert
    assert pack["metrics"]["eba_met:mi1"] == {
        "type": "monetary",
        "period": "instant",
        "label": "Amount",
        "enumeration": None,
    }
    assert pack["dimensions"]["eba_dim:UDI"] == {
        "label": "Unique desk identifier",
        "domain": "eba_IS",
        "kind": "typed",
        "default": None,
        "typed_element": "eba_typ:IS",
        "typed_type": "string",
    }
    assert sorted(pack["metrics"]) == ["eba_met:mi1", "eba_met:mi2", "eba_met:si3"]
    assert sorted(pack["dimensions"]) == [
        "eba_dim:BAS",
        "eba_dim:CUE",
        "eba_dim:MCY",
        "eba_dim:UDI",
    ]
    assert sorted(pack["namespaces"]) == [
        "eba_BA",
        "eba_CU",
        "eba_MC",
        "eba_dim",
        "eba_met",
        "eba_typ",
    ]


def test_compiling_twice_gives_equal_packs(pack: dict[str, Any], publisher: Publisher) -> None:
    # Act
    again = compiler.compile_pack(
        publisher.annotated, publisher.dictionary, publisher.taxonomy, module=builders.MODULE
    )

    # Assert — equal as data and byte for byte once serialised (key order included)
    assert again == pack
    assert json.dumps(again) == json.dumps(pack)


def test_zipped_package_compiles_to_the_same_pack(
    pack: dict[str, Any], publisher: Publisher, tmp_path: Path
) -> None:
    # Arrange
    archive = builders.zip_package(publisher.taxonomy, tmp_path / "taxonomy.zip")

    # Act
    zipped = compiler.compile_pack(
        publisher.annotated, publisher.dictionary, archive, module=builders.MODULE
    )

    # Assert — only the recorded source name differs
    assert zipped["info"]["sources"]["taxonomy_package"] == "taxonomy.zip"
    zipped["info"]["sources"]["taxonomy_package"] = "taxonomy"
    assert zipped == pack


def test_unknown_module_is_a_usage_error(publisher: Publisher) -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="NOPE99"):
        compiler.compile_pack(
            publisher.annotated, publisher.dictionary, publisher.taxonomy, module="NOPE99"
        )


def test_a_dictionary_that_is_not_one_is_a_usage_error(publisher: Publisher) -> None:
    # Act / Assert — the annotated workbook, given as the dictionary, has none of its sheets
    with pytest.raises(ValueError, match="not a DPM dictionary: no sheet.s. Domains, Dimensions"):
        compiler.compile_pack(
            publisher.annotated, publisher.annotated, publisher.taxonomy, module=builders.MODULE
        )


def test_missing_input_is_a_usage_error(publisher: Publisher, tmp_path: Path) -> None:
    # Act / Assert
    with pytest.raises(FileNotFoundError, match="absent.zip"):
        compiler.compile_pack(
            publisher.annotated,
            publisher.dictionary,
            tmp_path / "absent.zip",
            module=builders.MODULE,
        )
