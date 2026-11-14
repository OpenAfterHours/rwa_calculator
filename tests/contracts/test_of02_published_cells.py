"""
The Basel 3.1 OF 02.00 layout against the cells the Bank of England publishes.

Why this file exists: the own-funds-requirements layout was written from row
headings and never compared with the template itself. Its row CODES were not
the published ones — the credit-risk total sat at 0050 where the template has
it at 0040, the approach totals at 0220 / 0240 / 0300 where the template has
0240 / 0250 / 0310, and five rows had no published counterpart at all — and it
filled columns 0020 and 0030 on every row, where the template has column 0030
on four rows and column 0020 on the modelled rows only. Worse than a figure
with no cell: an "8% own funds requirement" was reported in row 0040, which the
template defines as the credit-risk RWEA.

The source of truth here is the PRA001 taxonomy pack, compiled from the Bank's
own data point model (table ``OF02.00.01.01``). Three things are held to it:

- the layout — every row and column is a published one, each row carries the
  published LABEL (a code can be right and its meaning wrong), and no row of the
  credit-risk block is missing;
- the cells — a figure is reported only where the template has a cell, and a
  cell of a row this calculator computes is not left empty; the declaration
  the generator reads its cells from (``corep/c02_rows.py``) equals the
  taxonomy's, row by row, in both directions;
- the slot table — every figure's Basel 3.1 row is a row of the layout, and no
  two figures share one;
- the return — what is generated can be placed and typed by the filing adapter
  with nothing left over.

References:
- PRA PS1/26 Annex I (OF 02.00 template) and Annex II §1.3
- Bank of England Banking Taxonomy v4.1.1, module PRA001
"""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._c02_frames import FLOOR_MULTIPLIER, b31_frame

from rwa_calc.contracts.bundles import OutputFloorSummary
from rwa_calc.reporting.corep import c02_rows
from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.reporting.corep.templates import get_c02_00_columns, get_c02_00_row_sections
from rwa_calc.reporting.filing.canonical import FILING_MODULE, build_canonical_return
from rwa_filer.model import ReturnHeader
from rwa_filer.taxonomy.pack import TaxonomyPack, resolve_pack
from rwa_filer.validate.returns import validate_return

REFERENCE_DATE = dt.date(2027, 3, 31)
FRAMEWORK = "BASEL_3_1"
TABLE = "OF02.00.01.01"
#: A checksum-valid LEI. Nothing here depends on who is reporting.
ENTITY_IDENTIFIER = "5493001KJTIIGC8Y1R12"

#: The rows of the template's credit-risk block that this calculator computes
#: nothing for, with the reason. Every OTHER row from 0010 to 0470 must be in the
#: layout and must carry a figure when the portfolio has exposure.
NOT_COMPUTED: dict[str, str] = {
    "0020": "investment-firm of-which (Art. 95(2) / 98): not an entity type this calculator runs",
    "0030": "investment-firm of-which (Art. 96(2) / 97): not an entity type this calculator runs",
    "0450": "Art. 156 other non credit-obligation assets: not a class the engine models",
    "0460": "Art. 307-309 default-fund contributions: no row-level carrier is sealed for them",
    "0470": "securitisation positions: the SEC framework is out of scope of the engine",
}
#: The last row of the credit-risk block (1.1.4 Securitisation positions).
LAST_CREDIT_ROW = "0470"


@pytest.fixture(scope="module")
def pack() -> TaxonomyPack:
    return resolve_pack(FILING_MODULE, REFERENCE_DATE)


@pytest.fixture(scope="module")
def published(pack: TaxonomyPack) -> set[tuple[str, str]]:
    """Every (row, column) OF 02.00 has a data point for."""
    cells = pack.cells.filter(pl.col("table") == TABLE)
    return set(zip(cells["row"].to_list(), cells["column"].to_list(), strict=True))


@pytest.fixture(scope="module")
def generated() -> pl.DataFrame:
    """OF 02.00 for a book with a leg in every row the template can place.

    The summary is what supplies OF-ADJ; without it the floor cannot be stated
    and row 0010 column 0030 stays empty, which would leave the column-0030
    cells unexamined.
    """
    summary = OutputFloorSummary(
        u_trea=0.0,
        s_trea=0.0,
        floor_pct=FLOOR_MULTIPLIER,
        floor_threshold=0.0,
        shortfall=0.0,
        portfolio_floor_binding=False,
        floored_modelled_rwa=0.0,
        of_adj=-125.0,
    )
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(
        b31_frame(), framework=FRAMEWORK, output_floor_summary=summary
    )
    assert bundle.c_02_00 is not None
    return bundle.c_02_00


def _layout_rows() -> dict[str, str]:
    return {
        row.ref: row.name for section in get_c02_00_row_sections(FRAMEWORK) for row in section.rows
    }


def _layout_columns() -> list[str]:
    return [column.ref for column in get_c02_00_columns(FRAMEWORK)]


def _reported(frame: pl.DataFrame) -> set[tuple[str, str]]:
    """The (row, column) cells of a generated frame that carry a value."""
    value_columns = [name for name in frame.columns if name not in ("row_ref", "row_name")]
    return {
        (row["row_ref"], column)
        for row in frame.to_dicts()
        for column in value_columns
        if row[column] is not None
    }


def test_the_layout_and_the_published_template_have_the_same_columns(
    published: set[tuple[str, str]],
) -> None:
    # Arrange
    published_columns = sorted({column for _, column in published})

    # Act
    layout = sorted(_layout_columns())

    # Assert
    assert layout == published_columns


def test_every_row_of_the_layout_is_a_published_row(published: set[tuple[str, str]]) -> None:
    # Arrange
    published_rows = {row for row, _ in published}

    # Act
    unpublished = sorted(ref for ref in _layout_rows() if ref not in published_rows)

    # Assert
    assert unpublished == [], f"OF 02.00 has no row {unpublished}"


def test_every_row_of_the_layout_carries_its_published_label(pack: TaxonomyPack) -> None:
    """A row code is half the claim: 0040 was a real row holding the wrong figure."""
    # Arrange
    labels = dict(pack.tables[TABLE].rows)

    # Act
    mislabelled = {
        ref: (name, labels[ref])
        for ref, name in _layout_rows().items()
        if ref in labels and name != labels[ref]
    }

    # Assert
    assert mislabelled == {}, "layout label vs published label"


def test_no_row_of_the_credit_risk_block_is_missing_from_the_layout(
    published: set[tuple[str, str]],
) -> None:
    # Arrange
    credit_block = {row for row, _ in published if row <= LAST_CREDIT_ROW} - set(NOT_COMPUTED)

    # Act
    missing = sorted(credit_block - set(_layout_rows()))

    # Assert
    assert missing == [], f"published credit-risk rows the layout lacks: {missing}"


def test_a_figure_is_reported_only_where_the_template_has_a_cell(
    published: set[tuple[str, str]], generated: pl.DataFrame
) -> None:
    # Arrange
    reported = _reported(generated)
    assert ("0010", "0030") in reported, "the floor was not stated - column 0030 is unexamined"
    assert any(column == "0020" for _, column in reported), "column 0020 is unexamined"

    # Act
    outside = sorted(reported - published)

    # Assert
    assert outside == [], f"figures reported where OF 02.00 has no cell: {outside}"


def test_no_cell_of_a_computed_row_is_left_empty(
    published: set[tuple[str, str]], generated: pl.DataFrame
) -> None:
    """The other direction: blanking a cell the template has loses a figure."""
    # Arrange
    expected = {
        (row, column)
        for row, column in published
        if row <= LAST_CREDIT_ROW and row not in NOT_COMPUTED
    }

    # Act
    empty = sorted(expected - _reported(generated))

    # Assert
    assert empty == [], f"published cells of computed rows left empty: {empty}"


def test_the_declared_cells_of_every_row_are_exactly_the_published_cells(
    published: set[tuple[str, str]],
) -> None:
    """The generator reports a column only where this declaration says the row
    has a cell, so the declaration is held to the taxonomy both ways: a cell it
    adds cannot be filed, and a cell it omits is a figure silently lost."""
    # Arrange
    declared = {
        (row, column)
        for row, columns in c02_rows.get_c02_00_cells(FRAMEWORK).items()
        for column in columns
    }
    rows = {row for row, _ in declared}

    # Act
    published_for_those_rows = {(row, column) for row, column in published if row in rows}

    # Assert
    assert sorted(declared - published_for_those_rows) == [], "declared cells the template lacks"
    assert sorted(published_for_those_rows - declared) == [], "published cells not declared"


@pytest.mark.parametrize("framework", ["CRR", FRAMEWORK])
def test_every_slot_names_one_row_of_its_layout_and_no_two_share_a_row(framework: str) -> None:
    """A slot pointing outside the layout is a figure computed and never shown;
    two slots on one row is one figure overwriting another."""
    # Arrange
    slots = [value for value in vars(c02_rows).values() if isinstance(value, c02_rows.Slot)]
    layout = set(c02_rows.get_c02_00_cells(framework))
    assert len(slots) > 30, "the slot table was not found"

    # Act
    refs = [slot.ref(framework) for slot in slots if slot.ref(framework) is not None]

    # Assert
    assert sorted(set(refs) - layout) == [], "slots naming a row the layout lacks"
    assert len(refs) == len(set(refs)), "two slots name the same row"


def test_the_generated_template_files_with_nothing_left_over(
    pack: TaxonomyPack, generated: pl.DataFrame
) -> None:
    """Placed, typed and internally consistent: the yes/no cell as a boolean, the
    multiplier as a rate, and no data point reported twice with two values."""
    # Arrange
    bundle = COREPTemplateBundle(
        c07_00={}, c08_01={}, c08_02={}, c_02_00=generated, framework=FRAMEWORK
    )
    header = ReturnHeader(ENTITY_IDENTIFIER, REFERENCE_DATE, FILING_MODULE)

    # Act
    mapping = build_canonical_return(bundle, header, pack=pack)
    findings = [
        finding
        for finding in validate_return(mapping.canonical, pack).structure
        if TABLE in finding.subject
    ]

    # Assert
    assert mapping.unplaced_figures.to_dicts() == []
    assert [(finding.code, finding.message) for finding in findings] == []
