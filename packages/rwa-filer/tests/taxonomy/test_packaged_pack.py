"""
Integrity of the packaged taxonomy packs.

Pipeline position:
    taxonomy/data/<module>-<version>/ (package data)  ->  resolve_pack  ->  everything downstream

Why this exists: a pack is compiled from the publisher's DPM files, which are
not redistributed and so cannot be re-derived in CI
(``test_compiler_integration.py`` does that, opt-in, where the files are
present). This file is the offline guard: it catches a truncated, half-written
or mis-packaged pack with no network and no source workbook, and it pins the
pack's measured size so a re-compile that changes it is a deliberate act.

The pinned numbers are those of the compile recorded in the changelog: PRA001
v4.1.1, checked against the Bank of England's own sample instance, every one of
whose 61,428 facts maps to a cell of this pack.
"""

from __future__ import annotations

import json
from datetime import date
from importlib import resources

import polars as pl
import pytest

from rwa_filer.taxonomy.pack import (
    CELLS_FILE,
    DATAPOINTS_FILE,
    MEMBER_OPEN,
    MEMBER_OPEN_OPTIONAL,
    MEMBER_TYPED_PREFIX,
    PACK_FILE,
    PACKS_DIRECTORY,
    PACKS_PACKAGE,
    SOURCE_LINKBASE,
    SOURCE_WORKBOOK,
    PackNotFoundError,
    TaxonomyPack,
    available_packs,
    resolve_pack,
)

PRA001_KEY = "pra001-4.1.1"
#: (tables, cells, cells established from the linkbase alone, data points, filing indicators)
PRA001_COUNTS = (104, 61_615, 42, 61_428, 83)
PRA001_ENTRY_POINT = (
    "http://www.bankofengland.co.uk/data/xbrl/fws/banking/banking_reporting/"
    "2026-08-17/mod/pra001.xsd"
)
#: The credit-risk tables rwa-calc's Basel 3.1 estate is filed in.
CREDIT_RISK_TABLES = (
    "OF02.00.01.01",
    "OF07.00.01.01",
    "OF08.01.01.01",
    "OF08.02.01.01",
    "OF09.01.01.01",
    "OF09.02.01.01",
    "C34.02.01.01",
)


@pytest.fixture(scope="module")
def pra001() -> TaxonomyPack:
    return resolve_pack("PRA001", date(2027, 3, 31))


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filename", [PACK_FILE, CELLS_FILE, DATAPOINTS_FILE])
def test_each_pack_file_is_reachable_as_package_data(filename: str) -> None:
    """All three, through ``importlib.resources`` — as an installed wheel reads them."""
    # Act
    resource = resources.files(PACKS_PACKAGE).joinpath(PACKS_DIRECTORY, PRA001_KEY, filename)

    # Assert
    assert resource.is_file()


def test_the_pack_tables_are_not_parquet() -> None:
    """The repository git-ignores ``*.parquet``, and the build honours that file.

    A Parquet pack would be neither committed nor shipped — it would work only
    on the machine that compiled it.
    """
    assert not CELLS_FILE.endswith(".parquet") and not DATAPOINTS_FILE.endswith(".parquet")


def test_pack_json_is_pure_ascii() -> None:
    # Act
    text = (
        resources.files(PACKS_PACKAGE)
        .joinpath(PACKS_DIRECTORY, PRA001_KEY, PACK_FILE)
        .read_text(encoding="utf-8")
    )

    # Assert
    assert text.isascii()
    assert json.loads(text)["info"]["module"] == "PRA001"


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_pra001_is_packaged_from_the_first_of_january_2027() -> None:
    # Act
    infos = [info for info in available_packs() if info.module == "PRA001"]

    # Assert
    assert [(info.version, info.valid_from, info.valid_to) for info in infos] == [
        ("4.1.1", date(2027, 1, 1), None)
    ]


def test_a_2027_reference_date_resolves_to_v4_1_1(pra001: TaxonomyPack) -> None:
    assert (pra001.info.module, pra001.info.version) == ("PRA001", "4.1.1")
    assert pra001.info.entry_point == PRA001_ENTRY_POINT


def test_a_2026_reference_date_has_no_pack() -> None:
    """The Basel 3.1 return starts on 1 January 2027; nothing earlier is packaged."""
    with pytest.raises(PackNotFoundError, match="PRA001"):
        resolve_pack("PRA001", date(2026, 12, 31))


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------


def test_the_pack_has_its_measured_size(pra001: TaxonomyPack) -> None:
    # Act
    measured = (
        len(pra001.tables),
        pra001.cells.height,
        pra001.cells.filter(pl.col("source") == SOURCE_LINKBASE).height,
        len(pra001.datapoints),
        len(pra001.filing_indicators),
    )

    # Assert
    assert measured == PRA001_COUNTS


def test_every_cell_names_a_table_and_a_data_point_the_pack_has(pra001: TaxonomyPack) -> None:
    # Act
    tables = set(pra001.cells["table"].unique().to_list())
    highest = pra001.cells["datapoint"].max()

    # Assert
    assert tables == set(pra001.tables)
    assert highest == len(pra001.datapoints) - 1
    assert set(pra001.cells["source"].unique().to_list()) <= {SOURCE_WORKBOOK, SOURCE_LINKBASE}


def test_no_cell_is_listed_twice(pra001: TaxonomyPack) -> None:
    # Act
    distinct = pra001.cells.select("table", "row", "column", "sheet").unique().height

    # Assert
    assert distinct == pra001.cells.height


def test_every_data_point_names_a_known_metric_and_known_dimensions(
    pra001: TaxonomyPack,
) -> None:
    # Act
    unknown_metrics = {p.metric for p in pra001.datapoints} - set(pra001.metrics)
    unknown_dimensions = {
        dimension for point in pra001.datapoints for dimension, _member in point.dimensions
    } - set(pra001.dimensions)

    # Assert
    assert unknown_metrics == set()
    assert unknown_dimensions == set()


def test_a_data_point_never_names_a_dimensions_default_member(pra001: TaxonomyPack) -> None:
    """An instance must not report a default member; a pack that held one would write it."""
    # Act
    offenders = [
        (point.metric, dimension, member)
        for point in pra001.datapoints
        for dimension, member in point.dimensions
        if pra001.dimensions[dimension].default == member
    ]

    # Assert
    assert offenders == []


def test_open_members_are_one_of_the_three_placeholders(pra001: TaxonomyPack) -> None:
    # Act
    placeholders = {
        member
        for point in pra001.datapoints
        for _dimension, member in point.dimensions
        if member.startswith("*")
    }

    # Assert
    assert all(
        member in (MEMBER_OPEN, MEMBER_OPEN_OPTIONAL) or member.startswith(MEMBER_TYPED_PREFIX)
        for member in placeholders
    )
    assert MEMBER_OPEN in placeholders, "the geography tables have an open axis"


@pytest.mark.parametrize("table", CREDIT_RISK_TABLES)
def test_the_credit_risk_tables_are_present_with_cells(pra001: TaxonomyPack, table: str) -> None:
    assert table in pra001.tables
    assert pra001.cells.filter(pl.col("table") == table).height > 0


def test_the_sa_table_has_one_sheet_per_exposure_class(pra001: TaxonomyPack) -> None:
    """OF 07.00: a total plus the SA exposure classes — and no sheet 0014."""
    # Act
    codes = pra001.tables["OF07.00.01.01"].sheet_codes

    # Assert
    assert len(codes) == 16
    assert "0014" not in codes and codes[0] == "0001"


def test_the_geography_tables_are_open_over_the_country_dimension(pra001: TaxonomyPack) -> None:
    # Act
    axis = pra001.tables["OF09.01.01.01"].open_axis

    # Assert
    assert axis is not None and axis.dimension == "eba_dim:CEG"
    assert "eba_GA:x1" in axis.members and "eba_GA:GB" in axis.members


def test_the_pd_scale_table_has_open_rows(pra001: TaxonomyPack) -> None:
    # Act
    table = pra001.tables["OF08.02.01.01"]

    # Assert
    assert table.open_rows and table.row_codes == ()
    assert [key.dimension for key in table.open_keys] == ["eba_dim:OGR"]


def test_several_tables_can_share_one_filing_indicator(pra001: TaxonomyPack) -> None:
    # Act
    sharing = [t.code for t in pra001.tables.values() if t.filing_indicator == "OF07.00.01"]

    # Assert
    assert len(sharing) == 5
