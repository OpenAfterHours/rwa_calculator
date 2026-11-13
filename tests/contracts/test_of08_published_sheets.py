"""
The Basel 3.1 OF 08 sheet axis against the sheets the Bank of England publishes.

Why this file exists: OF 08.01, OF 08.02, OF 08.03 and OF 08.05 are published on
seventeen sheets — fifteen exposure sub-classes each under one approach, and two
Totals — and were generated on sheets keyed by exposure class alone. That is a
coarser partition: one ``corporate`` sheet answered the published F-IRB and A-IRB
"other general corporates non-SME" sheets at once, one ``retail_mortgage`` sheet
answered four. A figure on such a sheet has no published sheet to be filed on,
and 816 distinct non-zero figures across the registered Basel 3.1 portfolios had
none.

The source of truth here is the PRA001 taxonomy pack, compiled from the Bank's
own data point model. Four things are held to it, each in both directions:

- the axis — the declared sheets (``corep/irb_sheets.py``) are the published
  sheet codes, with the published labels, on every OF 08 table that has the axis;
- the sheet map — every published code names exactly one of our sheet keys and
  no key is named twice (``filing/sheet_maps.py``, which ``arch_check`` check 22
  requires to be written as literals — so this is what keeps the literals equal
  to the declaration);
- the population — each sheet takes the approach, the exposure class, the SME /
  non-SME side and the property type its taxonomy dimension members name;
- the tie to OF 02.00 — each sheet's total is the data point of the OF 02.00
  row its legs are counted in.

And one thing is held to the generator: a book with a leg for every sheet emits
every published sheet and no other, on all four templates, and a pair Basel 3.1
has no sheet for is reported off the axis and said so — never dropped, never
added to a neighbouring sheet.

The dimension-member readings below (``eba_AP:x66`` is the AIRB approach, and so
on) are taken from the pack's own sheet labels, on which they co-vary without
exception; they are written out here rather than derived from the declaration
so that a sheet declared with the wrong approach or the wrong side fails.

References:
- PRA PS1/26 Annex II §3.3.1-§3.3.2 (the OF CR IRB exposure and sub-exposure
  classes; "The Total template must be reported for the FIRB and the slotting
  approaches and, separately for the AIRB approach")
- Bank of England Banking Taxonomy v4.1.1, module PRA001, tables
  ``OF08.01.01.01`` / ``.02``, ``OF08.02.01.01``, ``OF08.03.01.01``,
  ``OF08.05.00.01`` / ``OF08.05.01.01`` and ``OF02.00.01.01``
"""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._c02_frames import (
    CRR_ONLY_LEGS,
    MODELLED_LEGS,
    b31_frame,
    crr_frame,
)

from rwa_calc.reporting.corep import c02_rows, irb_sheets
from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    REASON_SHEET_COARSER,
    REASON_SHEET_UNPUBLISHED,
    build_canonical_return,
)
from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS
from rwa_filer.model import ReturnHeader
from rwa_filer.taxonomy.pack import Sheet, TaxonomyPack, resolve_pack

REFERENCE_DATE = dt.date(2027, 3, 31)
FRAMEWORK = "BASEL_3_1"
#: A checksum-valid LEI. Nothing here depends on who is reporting.
ENTITY_IDENTIFIER = "5493001KJTIIGC8Y1R12"

#: The table the axis is read from, and every other OF 08 table that carries it.
AXIS_TABLE = "OF08.01.01.01"
SHEETED_TABLES = (
    "OF08.01.01.01",
    "OF08.01.01.02",
    "OF08.02.01.01",
    "OF08.03.01.01",
    "OF08.05.00.01",
    "OF08.05.01.01",
)
OF02_TABLE = "OF02.00.01.01"

#: The four generated templates the axis applies to (bundle members).
SHEETED_TEMPLATES = ("c08_01", "c08_02", "c08_03", "c08_05")

# What each taxonomy dimension member on the sheet axis means, read off the
# pack's own sheet labels.
APPROACH_MEMBER = "eba_dim:APR"
APPROACHES_BY_MEMBER: dict[str, set[str]] = {
    "eba_AP:x66": {"advanced_irb"},
    "eba_AP:x67": {"foundation_irb"},
    "boe_eba_AP:x10050": {"foundation_irb", "slotting"},
}
CLASS_MEMBER = "eba_dim:EXC"
#: Member -> (the exposure classes, whether "financial or large corporate").
CLASSES_BY_MEMBER: dict[str, tuple[set[str], bool | None]] = {
    "eba_EC:x35": ({"institution"}, None),
    "eba_EC:x3": ({"specialised_lending"}, None),
    "boe_eba_EC:x10006": ({"corporate", "corporate_sme"}, False),
    "boe_eba_EC:x10005": ({"corporate", "corporate_sme"}, True),
    "eba_EC:x8": ({"retail_qrre"}, None),
    "eba_EC:x7": ({"retail_other"}, None),
    "eba_EC:x9": ({"retail_mortgage"}, None),
}
SIZE_MEMBER = "eba_dim:CPZ"
SME_BY_MEMBER: dict[str, bool] = {"boe_eba_CT:x10023": True, "boe_eba_CT:x10024": False}
PROPERTY_MEMBER = "eba_dim:MCG"
COMMERCIAL_BY_MEMBER: dict[str, bool] = {"eba_MC:x293": True, "eba_MC:x294": False}

#: The published codes of the two Total sheets and the sheet with the slotting row.
TOTAL_CODES = {"0001", "0002"}
SLOTTING_SHEET_CODE = "0010"


@pytest.fixture(scope="module")
def pack() -> TaxonomyPack:
    return resolve_pack(FILING_MODULE, REFERENCE_DATE)


@pytest.fixture(scope="module")
def published(pack: TaxonomyPack) -> dict[str, Sheet]:
    """The published sheets of OF 08.01, by code."""
    return _sheets(pack, AXIS_TABLE)


@pytest.fixture(scope="module")
def generated() -> COREPTemplateBundle:
    """The estate for a book with a leg on every published sheet, and no other."""
    return LedgerShimCorepGenerator().generate_from_lazyframe(
        _with_pd(b31_frame(MODELLED_LEGS)), framework=FRAMEWORK
    )


def _sheets(pack: TaxonomyPack, table: str) -> dict[str, Sheet]:
    fixed = [axis for axis in pack.tables[table].z_axes if axis.kind == "fixed"]
    assert len(fixed) == 1, f"{table} does not have exactly one fixed sheet axis"
    return {sheet.code: sheet for sheet in fixed[0].sheets}


def _with_pd(frame: pl.LazyFrame) -> pl.LazyFrame:
    """The carriers OF 08.02 / 08.03 / 08.05 need to emit a sheet at all."""
    return frame.with_columns(
        pl.lit(0.01).alias("pd_floored"),
        pl.lit(0.01).alias("pd"),
        pl.lit(0.45).alias("lgd_floored"),
        pl.col("exposure_reference").alias("counterparty_reference"),
    )


def _member(sheet: Sheet, dimension: str) -> str | None:
    return dict(sheet.members).get(dimension)


def _datapoint(pack: TaxonomyPack, table: str, row: str, column: str, sheet: str | None) -> int:
    cells = pack.cells.filter(
        (pl.col("table") == table) & (pl.col("row") == row) & (pl.col("column") == column)
    )
    cells = cells.filter(pl.col("sheet").is_null() if sheet is None else pl.col("sheet") == sheet)
    assert cells.height == 1, f"{table} r{row} c{column} z{sheet}: {cells.height} cell(s)"
    return int(cells["datapoint"][0])


# ---------------------------------------------------------------------------
# The axis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table", SHEETED_TABLES)
def test_the_declared_sheets_are_exactly_the_published_sheet_codes(
    pack: TaxonomyPack, table: str
) -> None:
    # Arrange
    published_codes = set(_sheets(pack, table))

    # Act
    declared = set(irb_sheets.B31_SHEET_KEYS)

    # Assert
    assert sorted(published_codes - declared) == [], f"{table}: published sheets with no key"
    assert sorted(declared - published_codes) == [], f"{table}: keys with no published sheet"


def test_each_declared_sheet_carries_the_published_label(published: dict[str, Sheet]) -> None:
    # Arrange
    declared = {sheet.code: sheet.label for sheet in irb_sheets.B31_CLASS_SHEETS} | {
        code: label for code, _key, label, _tab in irb_sheets.B31_TOTAL_SHEETS
    }

    # Act
    wrong = {
        code: (label, published[code].label)
        for code, label in declared.items()
        if label != published[code].label
    }

    # Assert
    assert wrong == {}


def test_no_two_published_sheets_share_a_key() -> None:
    # Arrange / Act
    keys = list(irb_sheets.B31_SHEET_KEYS.values())

    # Assert
    assert len(set(keys)) == len(keys) == 17


# ---------------------------------------------------------------------------
# The sheet map the filing adapter and the rule engine place sheets through
# ---------------------------------------------------------------------------


def test_every_published_code_names_exactly_one_bundle_key(published: dict[str, Sheet]) -> None:
    # Arrange
    sheet_map = SHEET_INDEX_MAPS["of08"]

    # Act
    cardinality = {code: len(entry.bundle_keys) for code, entry in sheet_map.items()}

    # Assert
    assert set(sheet_map) == set(published)
    assert {code: n for code, n in cardinality.items() if n != 1} == {}, (
        "a published sheet code that names no key cannot be filed, and one that names two "
        "is a sheet of ours coarser than the published axis"
    )


def test_the_sheet_map_names_the_declared_keys() -> None:
    """``sheet_maps.py`` spells each key as a literal (arch_check check 22 reads
    them off the source); this is what keeps the literals and the declaration
    the generator keys its sheets from equal."""
    # Arrange / Act
    mapped = {code: entry.bundle_keys for code, entry in SHEET_INDEX_MAPS["of08"].items()}

    # Assert
    assert mapped == {code: (key,) for code, key in irb_sheets.B31_SHEET_KEYS.items()}


# ---------------------------------------------------------------------------
# The population each sheet takes
# ---------------------------------------------------------------------------


def test_each_sheet_takes_the_approach_its_dimension_member_names(
    published: dict[str, Sheet],
) -> None:
    # Arrange / Act
    wrong: dict[str, tuple[set[str], set[str]]] = {}
    for sheet in irb_sheets.B31_CLASS_SHEETS:
        expected = APPROACHES_BY_MEMBER[str(_member(published[sheet.code], APPROACH_MEMBER))]
        declared = {limb.approach for limb in sheet.limbs}
        if declared != expected:
            wrong[sheet.code] = (declared, expected)

    # Assert
    assert wrong == {}


def test_each_total_sheet_is_the_total_of_the_approach_its_member_names(
    published: dict[str, Sheet],
) -> None:
    # Arrange
    key_of = {code: key for code, key, _label, _tab in irb_sheets.B31_TOTAL_SHEETS}

    # Act
    wrong: dict[str, object] = {}
    for code in sorted(TOTAL_CODES):
        expected = APPROACHES_BY_MEMBER[str(_member(published[code], APPROACH_MEMBER))]
        adding_in = {
            limb.approach
            for sheet in irb_sheets.B31_CLASS_SHEETS
            if sheet.total == key_of[code]
            for limb in sheet.limbs
        }
        if adding_in != expected:
            wrong[code] = (adding_in, expected)

    # Assert
    assert set(key_of) == TOTAL_CODES
    assert wrong == {}


def test_each_sheet_takes_the_class_its_dimension_member_names(
    published: dict[str, Sheet],
) -> None:
    # Arrange / Act
    wrong: dict[str, object] = {}
    for sheet in irb_sheets.B31_CLASS_SHEETS:
        classes, financial_large = CLASSES_BY_MEMBER[
            str(_member(published[sheet.code], CLASS_MEMBER))
        ]
        limb = sheet.limbs[0]
        if set(limb.classes or ()) != classes or limb.financial_large != financial_large:
            wrong[sheet.code] = (limb.classes, limb.financial_large)

    # Assert
    assert wrong == {}


def test_each_sheet_takes_the_size_and_property_its_dimension_members_name(
    published: dict[str, Sheet],
) -> None:
    # Arrange / Act
    wrong: dict[str, object] = {}
    for sheet in irb_sheets.B31_CLASS_SHEETS:
        size = _member(published[sheet.code], SIZE_MEMBER)
        prop = _member(published[sheet.code], PROPERTY_MEMBER)
        expected = (
            None if size is None else SME_BY_MEMBER[size],
            None if prop is None else COMMERCIAL_BY_MEMBER[prop],
        )
        limb = sheet.limbs[0]
        if (limb.sme, limb.commercial) != expected:
            wrong[sheet.code] = ((limb.sme, limb.commercial), expected)

    # Assert
    assert wrong == {}


# ---------------------------------------------------------------------------
# The tie to OF 02.00: a sheet's total is the row its legs are counted in
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("of02_column", "of08_column"),
    [(c02_rows.COL_ALL_APPROACHES, "0260"), (c02_rows.COL_STANDARDISED, "0276")],
)
def test_each_sheet_total_is_one_data_point_with_its_of02_row(
    pack: TaxonomyPack, of02_column: str, of08_column: str
) -> None:
    # Arrange
    tied = [sheet for sheet in irb_sheets.B31_CLASS_SHEETS if sheet.code != SLOTTING_SHEET_CODE]

    # Act
    apart = [
        (sheet.code, sheet.slot.name)
        for sheet in tied
        if _datapoint(pack, OF02_TABLE, str(sheet.slot.b31), of02_column, None)
        != _datapoint(pack, AXIS_TABLE, "0010", of08_column, sheet.code)
    ]

    # Assert
    assert len(tied) == 14
    assert apart == []


def test_the_airb_total_sheet_is_one_data_point_with_the_of02_airb_row(
    pack: TaxonomyPack,
) -> None:
    # Arrange / Act
    of02 = _datapoint(pack, OF02_TABLE, str(c02_rows.AIRB.b31), c02_rows.COL_ALL_APPROACHES, None)
    of08 = _datapoint(pack, AXIS_TABLE, "0010", "0260", "0001")

    # Assert
    assert of02 == of08


def test_the_sheets_that_carry_slotting_are_no_of02_row(pack: TaxonomyPack) -> None:
    """Sheets 0010 and 0002 total F-IRB AND slotting; OF 02.00 reports slotting
    in rows of its own (0411-0416), so neither total is an OF 02.00 data point —
    which is why the slotting sheet's slot is its F-IRB legs alone."""
    # Arrange
    of02 = set(pack.cells.filter(pl.col("table") == OF02_TABLE)["datapoint"].to_list())

    # Act
    shared = [
        code
        for code in (SLOTTING_SHEET_CODE, "0002")
        if _datapoint(pack, AXIS_TABLE, "0010", "0260", code) in of02
    ]

    # Assert
    assert shared == []


# ---------------------------------------------------------------------------
# The generator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", SHEETED_TEMPLATES)
def test_a_book_with_a_leg_for_every_sheet_emits_every_published_sheet_and_no_other(
    generated: COREPTemplateBundle, template: str
) -> None:
    # Arrange
    published_keys = set(irb_sheets.B31_SHEET_KEYS.values())

    # Act
    emitted = set(getattr(generated, template))

    # Assert
    assert sorted(published_keys - emitted) == [], f"{template}: published sheets not generated"
    assert sorted(emitted - published_keys) == [], f"{template}: sheets with no published code"


def test_nothing_generated_is_on_a_sheet_the_taxonomy_cannot_place(
    generated: COREPTemplateBundle, pack: TaxonomyPack
) -> None:
    # Arrange
    header = ReturnHeader(ENTITY_IDENTIFIER, REFERENCE_DATE, FILING_MODULE)

    # Act
    mapping = build_canonical_return(generated, header, pack=pack)
    unplaceable = mapping.unplaced.filter(
        pl.col("template").is_in(list(SHEETED_TEMPLATES))
        & pl.col("reason").is_in([REASON_SHEET_COARSER, REASON_SHEET_UNPUBLISHED])
    )

    # Assert
    assert unplaceable.group_by("template", "sheet", "reason").len().to_dicts() == []


def test_a_pair_basel31_has_no_sheet_for_is_reported_off_the_axis_and_said_so() -> None:
    """An A-IRB institution and an IRB sovereign (PS1/26 Art. 147A withdraws
    both) are neither dropped nor added to a neighbouring sheet."""
    # Arrange
    frame = _with_pd(b31_frame(MODELLED_LEGS + CRR_ONLY_LEGS))
    published_keys = set(irb_sheets.B31_SHEET_KEYS.values())

    # Act
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(frame, framework=FRAMEWORK)
    off_axis = set(bundle.c08_01) - published_keys

    # Assert
    assert off_axis == {
        "central_govt_central_bank_firb",
        "central_govt_central_bank_airb",
        "institution_airb",
    }
    for key in sorted(off_axis):
        assert any(key in error for error in bundle.errors), f"{key} is reported silently"


def test_the_crr_sheets_stay_keyed_by_exposure_class() -> None:
    """C 08.01 has its own published axis and no EBA taxonomy is held to lay it
    out against, so the CRR sheets are not re-keyed (``corep/c08_sheets.py``)."""
    # Arrange
    frame = _with_pd(crr_frame())

    # Act
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(frame, framework="CRR")

    # Assert
    assert set(bundle.c08_01) == {
        "central_govt_central_bank",
        "corporate",
        "corporate_sme",
        "institution",
        "retail_mortgage",
        "retail_other",
        "retail_qrre",
        "specialised_lending",
    }
