"""OF 08.01 / 08.02 / 08.03 / 08.05 on the published Basel 3.1 sheet axis.

Each leg of a hand-built book must report on the sheet its PUBLISHED code
names — by approach, by SME / non-SME and by property type, not by exposure
class alone — and on the sheet whose total is the OF 02.00 row the same leg is
counted in, because the taxonomy makes those two cells one data point.

Expected figures are stated from the leg list (``_irb_sheet_frames``), never
from the generator's own grouping.

References:
- PRA PS1/26 Annex II §3.3.1-§3.3.3 (OF CR IRB sheets; row 0080 slotting)
- Bank of England taxonomy v4.1.1: ``boe_b0206`` / ``boe_b1041`` (where the
  slotting row is reported), ``boe_b0616``-``boe_b0631`` and
  ``boe_b0638``-``boe_b0654`` (OF 02.00 rows against OF 08.01 sheets)
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.domain.enums import ExposureClass
from rwa_calc.reporting.corep import c02_rows, irb_sheets
from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.reporting.corep.templates import C08_03_PD_PARENT_REFS
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._c02_frames import (
    CRR_ONLY_LEGS,
    FIRB_LEGS,
    MODELLED_LEGS,
    SLOTTING_LEGS,
    Leg,
    own,
    standardised,
)
from tests.unit.reporting.corep._irb_sheet_frames import (
    EXPECTED_SHEET_CODE,
    FRAMEWORK,
    SLOTTING_SHEET_CODE,
    TOTAL_AIRB_CODE,
    TOTAL_FIRB_SLOTTING_CODE,
    cell,
    irb_book,
    legs_on,
    sheet_key,
)

CLASS_CODES = sorted(set(EXPECTED_SHEET_CODE.values()))
#: The published retail sheets — taxonomy labels "Retail - ..." (0015-0021).
RETAIL_CODES = ("0015", "0016", "0017", "0018", "0019", "0020", "0021")
#: The published sheets whose total is one data point with an OF 02.00 row.
TIED_CODES = [code for code in CLASS_CODES if code != SLOTTING_SHEET_CODE]


@pytest.fixture(scope="module")
def bundle() -> COREPTemplateBundle:
    """The estate for a book with a leg on every published sheet."""
    return LedgerShimCorepGenerator().generate_from_lazyframe(irb_book(), framework=FRAMEWORK)


def _leaf_sum(frame: pl.DataFrame, col_ref: str) -> float:
    """A PD-range sheet's column over its leaf rows (parent bands repeat them)."""
    leaves = frame.filter(~pl.col("row_ref").is_in(list(C08_03_PD_PARENT_REFS)))
    return float(leaves[col_ref].fill_null(0.0).sum())


def _of02(bundle: COREPTemplateBundle, slot: c02_rows.Slot, column: str) -> float | None:
    assert bundle.c_02_00 is not None
    return cell(bundle.c_02_00, str(slot.b31), column)


# ---------------------------------------------------------------------------
# Each leg on the sheet its published code names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", CLASS_CODES)
def test_of08_01_reports_each_leg_on_its_published_sheet(
    bundle: COREPTemplateBundle, code: str
) -> None:
    # Arrange
    legs = legs_on(code)
    assert legs, f"the book has no leg for sheet {code} and this test would prove nothing"

    # Act
    sheet = bundle.c08_01[sheet_key(code)]

    # Assert
    assert cell(sheet, "0010", "0260") == pytest.approx(own(legs))
    assert cell(sheet, "0010", "0276") == pytest.approx(standardised(legs))
    assert cell(sheet, "0010", "0110") == pytest.approx(2.0 * own(legs))


@pytest.mark.parametrize("code", CLASS_CODES)
def test_of08_02_reports_each_graded_leg_on_its_published_sheet(
    bundle: COREPTemplateBundle, code: str
) -> None:
    # Arrange — OF 08.02 excludes slotting (Annex II §3.3.4 ¶77A).
    legs = tuple(leg for leg in legs_on(code) if leg not in SLOTTING_LEGS)

    # Act
    sheet = bundle.c08_02[sheet_key(code)]

    # Assert
    assert float(sheet["0260"].sum()) == pytest.approx(own(legs))


@pytest.mark.parametrize("code", CLASS_CODES)
def test_of08_03_reports_each_graded_leg_on_its_published_sheet(
    bundle: COREPTemplateBundle, code: str
) -> None:
    # Arrange — OF 08.03 excludes slotting (Annex II §3.3.5.1 ¶77).
    legs = tuple(leg for leg in legs_on(code) if leg not in SLOTTING_LEGS)

    # Act
    sheet = bundle.c08_03[sheet_key(code)]

    # Assert
    assert _leaf_sum(sheet, "0090") == pytest.approx(own(legs))
    assert _leaf_sum(sheet, "0060") == len(legs)


@pytest.mark.parametrize("code", CLASS_CODES)
def test_of08_03_reports_a_maturity_on_every_sheet_but_the_retail_ones(
    bundle: COREPTemplateBundle, code: str
) -> None:
    """Annex II OF 08.03 column 0080: "this column shall not be filled in for
    the exposure class 'retail'" — the seven published retail sheets."""
    # Arrange
    sheet = bundle.c08_03[sheet_key(code)]

    # Act
    reported = sheet["0080"].drop_nulls().len()

    # Assert
    if code in RETAIL_CODES:
        assert reported == 0
    else:
        assert reported > 0


@pytest.mark.parametrize("code", CLASS_CODES)
def test_of08_05_reports_each_graded_obligor_on_its_published_sheet(
    bundle: COREPTemplateBundle, code: str
) -> None:
    # Arrange
    legs = tuple(leg for leg in legs_on(code) if leg not in SLOTTING_LEGS)

    # Act
    sheet = bundle.c08_05[sheet_key(code)]

    # Assert
    assert _leaf_sum(sheet, "0020") == len(legs)


def test_no_sheet_is_keyed_by_exposure_class_alone(bundle: COREPTemplateBundle) -> None:
    # Arrange
    class_names = {member.value for member in ExposureClass}

    # Act
    keyed_by_class = {
        template: sorted(set(getattr(bundle, template)) & class_names)
        for template in ("c08_01", "c08_02", "c08_03", "c08_05")
    }

    # Assert
    assert keyed_by_class == {"c08_01": [], "c08_02": [], "c08_03": [], "c08_05": []}


# ---------------------------------------------------------------------------
# OF 02.00 and OF 08.01 are one data point per class
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", TIED_CODES)
def test_an_of02_class_row_equals_the_total_of_the_sheet_it_is_one_data_point_with(
    bundle: COREPTemplateBundle, code: str
) -> None:
    # Arrange
    (declared,) = (sheet for sheet in irb_sheets.B31_CLASS_SHEETS if sheet.code == code)

    # Act
    sheet = bundle.c08_01[sheet_key(code)]

    # Assert
    assert _of02(bundle, declared.slot, c02_rows.COL_ALL_APPROACHES) == pytest.approx(
        cell(sheet, "0010", "0260")
    )
    assert _of02(bundle, declared.slot, c02_rows.COL_STANDARDISED) == pytest.approx(
        cell(sheet, "0010", "0276")
    )


def test_the_of02_firb_specialised_lending_row_is_the_slotting_sheet_less_its_slotting_row(
    bundle: COREPTemplateBundle,
) -> None:
    """``boe_b0618``: OF 02.00 r0290 = sheet 0010 r0010 - r0080 (column 0260)."""
    # Arrange
    sheet = bundle.c08_01[sheet_key(SLOTTING_SHEET_CODE)]

    # Act
    graded = (cell(sheet, "0010", "0260") or 0.0) - (cell(sheet, "0080", "0260") or 0.0)

    # Assert
    assert graded == pytest.approx(own(FIRB_LEGS, "F_SL"))
    assert _of02(
        bundle, c02_rows.FIRB_SPECIALISED_LENDING, c02_rows.COL_ALL_APPROACHES
    ) == pytest.approx(graded)


# ---------------------------------------------------------------------------
# Supervisory slotting
# ---------------------------------------------------------------------------


def test_slotting_reports_on_the_slotting_row_of_the_specialised_lending_sheet(
    bundle: COREPTemplateBundle,
) -> None:
    # Arrange
    sheet = bundle.c08_01[sheet_key(SLOTTING_SHEET_CODE)]

    # Act / Assert
    assert cell(sheet, "0080", "0260") == pytest.approx(own(SLOTTING_LEGS))
    assert cell(sheet, "0070", "0260") == pytest.approx(own(FIRB_LEGS, "F_SL"))
    assert cell(sheet, "0010", "0260") == pytest.approx(own(SLOTTING_LEGS) + own(FIRB_LEGS, "F_SL"))


def test_the_of02_slotting_row_equals_the_slotting_row_of_the_firb_and_slotting_total(
    bundle: COREPTemplateBundle,
) -> None:
    """``boe_b0631``: OF 02.00 r0411 = OF 08.01 r0080 c0260 on sheet 0002."""
    # Arrange
    total = bundle.c08_01[sheet_key(TOTAL_FIRB_SLOTTING_CODE)]

    # Act
    reported = cell(total, "0080", "0260")

    # Assert
    assert reported == pytest.approx(own(SLOTTING_LEGS))
    assert _of02(bundle, c02_rows.SLOTTING, c02_rows.COL_ALL_APPROACHES) == pytest.approx(reported)


def test_the_slotting_row_is_empty_on_every_sheet_the_template_does_not_have_it_on(
    bundle: COREPTemplateBundle,
) -> None:
    """``boe_b0206``: row 0080 is null on every sheet but 0002 and 0010."""
    # Arrange
    with_slotting_row = {sheet_key(SLOTTING_SHEET_CODE), sheet_key(TOTAL_FIRB_SLOTTING_CODE)}

    # Act
    reported = {
        key: sheet.filter(pl.col("row_ref") == "0080").drop("row_ref", "row_name").row(0)
        for key, sheet in bundle.c08_01.items()
        if key not in with_slotting_row
    }

    # Assert
    assert len(reported) == 15
    assert {key: values for key, values in reported.items() if any(v is not None for v in values)}  == {}  # fmt: skip


def test_the_slotting_row_is_reported_as_zero_where_the_template_has_it() -> None:
    """``boe_b1041`` requires row 0080 on sheets 0002 and 0010 to be reported:
    a firm with no slotting exposure has a slotting total of zero, not none."""
    # Arrange — F-IRB specialised lending and nothing slotted.
    legs = tuple(leg for leg in FIRB_LEGS if leg.reference in ("F_SL", "F_OTH"))

    # Act
    c08_01 = (
        LedgerShimCorepGenerator()
        .generate_from_lazyframe(irb_book(legs), framework=FRAMEWORK)
        .c08_01
    )

    # Assert
    assert cell(c08_01[sheet_key(SLOTTING_SHEET_CODE)], "0080", "0260") == 0.0
    assert cell(c08_01[sheet_key(TOTAL_FIRB_SLOTTING_CODE)], "0080", "0260") == 0.0


def test_the_firb_and_slotting_total_reports_a_zero_slotting_row_with_no_specialised_lending() -> (
    None
):
    # Arrange — no specialised lending at all, so no sheet 0010 to take it from.
    legs = tuple(leg for leg in FIRB_LEGS if leg.reference in ("F_INST", "F_OTH"))

    # Act
    c08_01 = (
        LedgerShimCorepGenerator()
        .generate_from_lazyframe(irb_book(legs), framework=FRAMEWORK)
        .c08_01
    )

    # Assert
    assert sheet_key(SLOTTING_SHEET_CODE) not in c08_01
    assert cell(c08_01[sheet_key(TOTAL_FIRB_SLOTTING_CODE)], "0080", "0260") == 0.0
    assert cell(c08_01[sheet_key(TOTAL_FIRB_SLOTTING_CODE)], "0080", "0020") == 0.0


def test_a_slotting_leg_stays_on_the_slotting_sheet_whatever_class_it_moved_to() -> None:
    """A slotting leg covered by an IRB guarantor keeps the slotting approach
    and takes the guarantor's class. OF 02.00 counts it in the slotting row by
    approach, so OF 08.01 reports it on the only class sheet with a slotting row."""
    # Arrange
    frame = irb_book((SLOTTING_LEGS[0],)).with_columns(
        pl.lit("institution").alias("exposure_class_post_crm")
    )

    # Act
    c08_01 = LedgerShimCorepGenerator().generate_from_lazyframe(frame, framework=FRAMEWORK).c08_01

    # Assert
    assert sheet_key("0006") not in c08_01
    assert cell(c08_01[sheet_key(SLOTTING_SHEET_CODE)], "0080", "0260") == pytest.approx(
        SLOTTING_LEGS[0].own
    )


# ---------------------------------------------------------------------------
# A pair Basel 3.1 has no sheet for
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def off_axis_bundle() -> COREPTemplateBundle:
    """The full book plus an IRB sovereign under each approach and an A-IRB
    institution — the three pairs PS1/26 Art. 147A withdraws."""
    return LedgerShimCorepGenerator().generate_from_lazyframe(
        irb_book(MODELLED_LEGS + CRR_ONLY_LEGS), framework=FRAMEWORK
    )


def _crr_only(reference: str) -> Leg:
    (leg,) = (leg for leg in CRR_ONLY_LEGS if leg.reference == reference)
    return leg


@pytest.mark.parametrize(
    ("reference", "neighbour_code"),
    [("A_INST", "0006"), ("F_CG", "0006"), ("A_CG", "0011")],
)
def test_a_pair_with_no_sheet_is_not_added_to_a_neighbouring_sheet(
    off_axis_bundle: COREPTemplateBundle,
    bundle: COREPTemplateBundle,
    reference: str,
    neighbour_code: str,
) -> None:
    # Arrange
    key = sheet_key(neighbour_code)

    # Act
    with_pair = cell(off_axis_bundle.c08_01[key], "0010", "0260")

    # Assert
    assert _crr_only(reference).own > 0
    assert with_pair == pytest.approx(cell(bundle.c08_01[key], "0010", "0260"))


def test_a_pair_with_no_sheet_is_not_dropped(off_axis_bundle: COREPTemplateBundle) -> None:
    # Arrange
    published = set(irb_sheets.B31_SHEET_KEYS.values())

    # Act
    off_axis = {
        key: cell(sheet, "0010", "0260")
        for key, sheet in off_axis_bundle.c08_01.items()
        if key not in published
    }

    # Assert
    assert off_axis == {
        "central_govt_central_bank_firb": pytest.approx(_crr_only("F_CG").own),
        "central_govt_central_bank_airb": pytest.approx(_crr_only("A_CG").own),
        "institution_airb": pytest.approx(_crr_only("A_INST").own),
    }


def test_a_pair_with_no_sheet_is_counted_in_its_approach_total_as_of02_counts_it(
    off_axis_bundle: COREPTemplateBundle,
) -> None:
    """OF 02.00 row 0310 (the A-IRB total) and the A-IRB Total sheet are one
    data point, and OF 02.00 keeps a leg with no class row in its approach row."""
    # Arrange
    airb = tuple(leg for leg in MODELLED_LEGS if leg.approach == "advanced_irb")
    expected = own(airb) + _crr_only("A_CG").own + _crr_only("A_INST").own

    # Act
    total = cell(off_axis_bundle.c08_01[sheet_key(TOTAL_AIRB_CODE)], "0010", "0260")

    # Assert
    assert total == pytest.approx(expected)
    assert _of02(off_axis_bundle, c02_rows.AIRB, c02_rows.COL_ALL_APPROACHES) == pytest.approx(
        expected
    )


def test_a_pair_with_no_sheet_is_recorded_as_an_error_on_each_template(
    off_axis_bundle: COREPTemplateBundle,
) -> None:
    # Arrange / Act
    errors = off_axis_bundle.errors

    # Assert
    for template in ("C08.01", "C08.02", "C08.03", "C08.05"):
        assert any(
            error.startswith(template) and "institution_airb" in error for error in errors
        ), f"{template} reports an A-IRB institution with no error"


def test_a_book_on_the_published_axis_records_no_sheet_error(bundle: COREPTemplateBundle) -> None:
    # Arrange / Act
    sheet_errors = [error for error in bundle.errors if "published" in error]

    # Assert
    assert sheet_errors == []


# ---------------------------------------------------------------------------
# The sheet key itself
# ---------------------------------------------------------------------------


def _key_grid() -> pl.DataFrame:
    """Every (approach, class, SME, sub-class, property) combination a leg can carry."""
    approaches = ["foundation_irb", "advanced_irb", "slotting", "standardised", None]
    classes = [member.value for member in ExposureClass] + [None]
    subclasses = ["corporate_sme", "corporate_financial_large", "corporate_other", None]
    properties = ["residential", "commercial", "cre", None]
    rows = [
        {
            "approach": approach,
            "exposure_class": exposure_class,
            "is_sme": is_sme,
            "exposure_subclass": subclass,
            "property_type": property_type,
        }
        for approach in approaches
        for exposure_class in classes
        for is_sme in (True, False, None)
        for subclass in subclasses
        for property_type in properties
    ]
    schema = {
        "approach": pl.String,
        "exposure_class": pl.String,
        "is_sme": pl.Boolean,
        "exposure_subclass": pl.String,
        "property_type": pl.String,
    }
    frame = pl.DataFrame(rows, schema=schema)
    return frame.with_columns(
        irb_sheets.sheet_key_expr(
            set(frame.columns), pl.col("approach"), pl.col("exposure_class")
        ).alias("key")
    )


def test_every_irb_leg_with_a_class_has_exactly_one_sheet_key() -> None:
    # Arrange
    grid = _key_grid()
    irb = grid.filter(
        pl.col("approach").is_in(["foundation_irb", "advanced_irb"])
        & pl.col("exposure_class").is_not_null()
        | (pl.col("approach") == "slotting")
    )

    # Act
    unkeyed = irb.filter(pl.col("key").is_null())

    # Assert
    assert irb.height > 0
    assert unkeyed.height == 0


def test_a_leg_outside_the_irb_approaches_has_no_sheet_key() -> None:
    # Arrange
    grid = _key_grid()

    # Act
    keyed = grid.filter(
        (pl.col("approach").is_null() | (pl.col("approach") == "standardised"))
        & pl.col("key").is_not_null()
    )

    # Assert
    assert keyed.height == 0


def test_no_sheet_takes_a_leg_another_sheet_takes() -> None:
    """The sheets partition the legs: the key expression is first-match, so two
    sheets claiming one leg would silently send it to whichever is declared first."""
    # Arrange
    grid = _key_grid().with_columns(
        (
            (pl.col("exposure_subclass") == "corporate_sme").fill_null(value=False)
            | pl.col("is_sme").fill_null(value=False)
            | (pl.col("exposure_class") == "corporate_sme").fill_null(value=False)
        ).alias("_sme"),
        (pl.col("exposure_subclass") == "corporate_financial_large")
        .fill_null(value=False)
        .alias("_fse"),
        pl.col("property_type").is_in(["commercial", "cre"]).fill_null(value=False).alias("_comm"),
    )

    def takes(limb: irb_sheets.Limb, leg: dict[str, object]) -> bool:
        return (
            leg["approach"] == limb.approach
            and (limb.classes is None or leg["exposure_class"] in limb.classes)
            and limb.sme in (None, leg["_sme"])
            and limb.financial_large in (None, leg["_fse"])
            and limb.commercial in (None, leg["_comm"])
        )

    # Act
    disagreements = []
    for leg in grid.iter_rows(named=True):
        takers = [
            sheet.key
            for sheet in irb_sheets.B31_CLASS_SHEETS
            if any(takes(limb, leg) for limb in sheet.limbs)
        ]
        if len(takers) > 1 or (takers and takers[0] != leg["key"]):
            disagreements.append((leg, takers))

    # Assert
    assert disagreements == []


def test_an_off_axis_key_is_never_a_published_key() -> None:
    # Arrange
    grid = _key_grid()
    published = set(irb_sheets.B31_SHEET_KEYS.values())

    # Act — a leg no published sheet's limbs take, yet carrying a published key.
    takers_none = grid.filter(pl.col("key").is_not_null() & ~pl.col("key").is_in(list(published)))
    off_axis_keys = set(takers_none["key"].to_list())

    # Assert
    assert off_axis_keys, "the grid reaches no off-axis pair and this test would prove nothing"
    assert all(irb_sheets.place_of(key).published is False for key in off_axis_keys)
    assert {irb_sheets.place_of(key).total for key in off_axis_keys} == {
        irb_sheets.TOTAL_AIRB_KEY,
        irb_sheets.TOTAL_FIRB_SLOTTING_KEY,
    }
