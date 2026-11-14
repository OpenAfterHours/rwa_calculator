"""The two OF 08 Total sheets (published codes 0001 and 0002).

Annex II §3.3.2: "The Total template must be reported for the FIRB and the
slotting approaches and, separately for the AIRB approach." The Bank's rules say
what a Total is where a figure can be added up — ``boe_b0748`` (the AIRB Total
equals the sum of the AIRB sheets) and ``boe_b0749`` (the FIRB-and-slotting
Total equals the sum of the FIRB sheets), each over a listed set of columns.
Neither lists the exposure-weighted averages (PD 0010, LGD 0230 / 0240), which
cannot be added up: on a Total they are the average over the exposures the
Total covers that carry the parameter.

Expected figures are stated from the leg list, never from the generator.

References:
- PRA PS1/26 Annex II §3.3.2 and §3.3.3 (columns 0010 / 0230 / 0250: weighted
  by the exposure value)
- Bank of England taxonomy v4.1.1: ``boe_b0748``, ``boe_b0749``, ``boe_b0749_1``
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.c08_sheets import c08_class_sheets
from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.reporting.corep.templates import C08_03_PD_PARENT_REFS
from rwa_calc.reporting.lineage import summed_sheet_reason
from rwa_calc.reporting.tieouts import check_cross_template_consistency
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator, LedgerShimPillar3Generator
from tests.unit.reporting.corep._builders import _irb_results
from tests.unit.reporting.corep._c02_frames import MODELLED_LEGS, SLOTTING_LEGS, Leg, own
from tests.unit.reporting.corep._irb_sheet_frames import (
    AIRB_CODES,
    FIRB_SLOTTING_CODES,
    FRAMEWORK,
    TOTAL_AIRB_CODE,
    TOTAL_FIRB_SLOTTING_CODE,
    cell,
    irb_book,
    legs_on,
    lgd_of,
    maturity_of,
    pd_of,
    sheet_key,
)

TOTALS = [(TOTAL_AIRB_CODE, AIRB_CODES), (TOTAL_FIRB_SLOTTING_CODE, FIRB_SLOTTING_CODES)]

#: The columns ``boe_b0748`` states as a sum over the AIRB sheets, less column
#: 0250 — an exposure-weighted average the rule lists all the same.
#: ``boe_b0749``'s list for the FIRB-and-slotting Total is a subset of these;
#: the Total sums every one of them, on both Totals (one definition).
SUMMED_COLUMNS = (
    "0020", "0030", "0035", "0040", "0050", "0060", "0070", "0080", "0090", "0101", "0102",
    "0103", "0104", "0110", "0125", "0140", "0150", "0160", "0170", "0171", "0172", "0173",
    "0180", "0190", "0200", "0210", "0251", "0252", "0253", "0254", "0260", "0265", "0270",
    "0275", "0276", "0280", "0281", "0282", "0290", "0300", "0310",
)  # fmt: skip
SUMMED_OFF_BS_COLUMNS = ("0100", "0120", "0130")


@pytest.fixture(scope="module")
def bundle() -> COREPTemplateBundle:
    return LedgerShimCorepGenerator().generate_from_lazyframe(irb_book(), framework=FRAMEWORK)


def _covered(codes: tuple[str, ...]) -> tuple[Leg, ...]:
    return tuple(leg for code in codes for leg in legs_on(code))


def _graded(legs: tuple[Leg, ...]) -> tuple[Leg, ...]:
    return tuple(leg for leg in legs if leg not in SLOTTING_LEGS)


def _weighted(legs: tuple[Leg, ...], value) -> float:  # noqa: ANN001 - a Leg -> float reader
    """The exposure-weighted average of ``value`` over ``legs`` (EAD = 2 x own)."""
    return sum(value(leg) * leg.own for leg in legs) / sum(leg.own for leg in legs)


# ---------------------------------------------------------------------------
# The Total sheets exist, on every template the axis applies to
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", ["c08_01", "c08_02", "c08_03", "c08_05"])
@pytest.mark.parametrize("code", [TOTAL_AIRB_CODE, TOTAL_FIRB_SLOTTING_CODE])
def test_each_template_carries_both_total_sheets(
    bundle: COREPTemplateBundle, template: str, code: str
) -> None:
    # Arrange / Act
    sheets = getattr(bundle, template)

    # Assert
    assert sheet_key(code) in sheets
    assert sheets[sheet_key(code)].height > 0


def test_a_total_sheet_has_the_layout_of_a_class_sheet(bundle: COREPTemplateBundle) -> None:
    # Arrange
    a_class = bundle.c08_01[sheet_key("0012")]

    # Act
    total = bundle.c08_01[sheet_key(TOTAL_FIRB_SLOTTING_CODE)]

    # Assert
    assert total.columns == a_class.columns
    assert total["row_ref"].to_list() == a_class["row_ref"].to_list()
    assert total.schema == a_class.schema


def test_a_firm_on_one_approach_reports_one_total() -> None:
    """Annex II ¶75: a second Total is reported where the firm uses the AIRB
    approach for part of its IRB exposures and FIRB or slotting for the rest."""
    # Arrange
    firb_only = tuple(leg for leg in MODELLED_LEGS if leg.approach == "foundation_irb")

    # Act
    c08_01 = (
        LedgerShimCorepGenerator()
        .generate_from_lazyframe(irb_book(firb_only), framework=FRAMEWORK)
        .c08_01
    )

    # Assert
    assert sheet_key(TOTAL_FIRB_SLOTTING_CODE) in c08_01
    assert sheet_key(TOTAL_AIRB_CODE) not in c08_01


def test_crr_has_no_total_sheet() -> None:
    # Arrange / Act
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(_irb_results(), framework="CRR")

    # Assert
    assert c08_class_sheets(bundle.c08_01) == bundle.c08_01
    assert not any(key.startswith("total") for key in bundle.c08_01)


# ---------------------------------------------------------------------------
# What a Total contains
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("total_code", "codes"), TOTALS)
def test_a_total_is_the_sum_of_its_sheets_in_every_column_the_rules_sum(
    bundle: COREPTemplateBundle, total_code: str, codes: tuple[str, ...]
) -> None:
    """``boe_b0748`` / ``boe_b0749`` (and ``boe_b0749_1`` for the off-balance-sheet
    of-which columns), on every row and not only on row 0010."""
    # Arrange
    total = bundle.c08_01[sheet_key(total_code)]
    sheets = [bundle.c08_01[sheet_key(code)] for code in codes]
    columns = [col for col in (*SUMMED_COLUMNS, *SUMMED_OFF_BS_COLUMNS) if col in total.columns]

    # Act
    apart = []
    for row_ref in total["row_ref"].to_list():
        for column in columns:
            reported = [
                value for sheet in sheets if (value := cell(sheet, row_ref, column)) is not None
            ]
            expected = sum(reported) if reported else None
            if cell(total, row_ref, column) != (
                None if expected is None else pytest.approx(expected)
            ):
                apart.append((row_ref, column, cell(total, row_ref, column), expected))

    # Assert
    assert len(columns) > 40
    assert apart == []


@pytest.mark.parametrize(("total_code", "codes"), TOTALS)
def test_a_total_counts_each_leg_once(
    bundle: COREPTemplateBundle, total_code: str, codes: tuple[str, ...]
) -> None:
    # Arrange
    legs = _covered(codes)

    # Act
    total = bundle.c08_01[sheet_key(total_code)]

    # Assert
    assert cell(total, "0010", "0260") == pytest.approx(own(legs))
    assert cell(total, "0010", "0110") == pytest.approx(2.0 * own(legs))
    assert cell(total, "0010", "0300") == len(legs)


@pytest.mark.parametrize(("total_code", "codes"), TOTALS)
def test_the_lgd_of_a_total_is_an_exposure_weighted_average_not_a_sum(
    bundle: COREPTemplateBundle, total_code: str, codes: tuple[str, ...]
) -> None:
    # Arrange
    legs = _covered(codes)
    sheets = [bundle.c08_01[sheet_key(code)] for code in codes]
    summed = sum(cell(sheet, "0010", "0230") or 0.0 for sheet in sheets)

    # Act
    total = bundle.c08_01[sheet_key(total_code)]

    # Assert
    assert cell(total, "0010", "0230") == pytest.approx(_weighted(legs, lgd_of))
    assert cell(total, "0010", "0230") != pytest.approx(summed), (
        "summing the sheets' LGDs would pass this test and the fixture would prove nothing"
    )


@pytest.mark.parametrize(("total_code", "codes"), TOTALS)
def test_the_pd_of_a_grade_total_is_an_exposure_weighted_average(
    bundle: COREPTemplateBundle, total_code: str, codes: tuple[str, ...]
) -> None:
    """OF 08.02 column 0010 (OF 08.01 has no PD column in this layout). Every
    leg of the book sits in the one "0.75% - 2.50%" band."""
    # Arrange
    legs = _graded(_covered(codes))

    # Act
    total = bundle.c08_02[sheet_key(total_code)]

    # Assert
    assert total["row_ref"].to_list() == ["0.75% - 2.50%"]
    assert cell(total, "0.75% - 2.50%", "0010") == pytest.approx(_weighted(legs, pd_of))


@pytest.mark.parametrize(("total_code", "codes"), TOTALS)
def test_the_maturity_of_a_total_is_an_exposure_weighted_average(
    bundle: COREPTemplateBundle, total_code: str, codes: tuple[str, ...]
) -> None:
    """Column 0250 is LISTED by ``boe_b0748`` as a sum over the AIRB sheets
    (``boe_b0749`` does not list it). Annex II defines it as an exposure-weighted
    average ("The exposure value (column 0110) shall be used for the calculation
    of the exposure-weighted averages"), and a sum of averages is not one."""
    # Arrange
    legs = _covered(codes)

    # Act
    total = bundle.c08_01[sheet_key(total_code)]

    # Assert
    assert cell(total, "0010", "0250") == pytest.approx(365.0 * _weighted(legs, maturity_of))


def _slotting_without_parameters() -> pl.LazyFrame:
    """The book with no maturity and no LGD on the slotting legs, as the engine
    seals them: slotting risk-weights by category (Art. 153(5)), so neither is
    an element of its risk-weighted exposure amount."""
    slotting = [leg.reference for leg in SLOTTING_LEGS]
    return irb_book().with_columns(
        pl.when(pl.col("exposure_reference").is_in(slotting))
        .then(None)
        .otherwise(pl.col(column))
        .alias(column)
        for column in ("irb_maturity_m", "lgd_floored")
    )


@pytest.mark.parametrize(
    ("column", "value", "scale"), [("0250", maturity_of, 365.0), ("0230", lgd_of, 1.0)]
)
def test_a_leg_with_no_parameter_does_not_dilute_the_average_of_a_total(
    column: str,
    value,
    scale: float,  # noqa: ANN001 - a Leg -> float reader
) -> None:
    """Annex II column 0250: "This column shall therefore not be filled in ... for
    exposures subject to the slotting approach". On the FIRB-and-slotting Total
    the slotting legs of sheet 0010 sit beside the F-IRB legs of every other
    sheet; a leg with no maturity (or LGD) is not an exposure of maturity zero,
    so the Total averages over the legs that carry the parameter."""
    # Arrange
    graded = _graded(_covered(FIRB_SLOTTING_CODES))
    covered = _covered(FIRB_SLOTTING_CODES)
    diluted = sum(value(leg) * leg.own for leg in graded) / sum(leg.own for leg in covered)
    assert len(covered) > len(graded), "no slotting leg on the Total: nothing could dilute it"

    # Act
    total = (
        LedgerShimCorepGenerator()
        .generate_from_lazyframe(_slotting_without_parameters(), framework=FRAMEWORK)
        .c08_01[sheet_key(TOTAL_FIRB_SLOTTING_CODE)]
    )

    # Assert
    assert cell(total, "0010", column) == pytest.approx(scale * _weighted(graded, value))
    assert cell(total, "0010", column) != pytest.approx(scale * diluted)


def test_the_obligor_grade_row_of_a_total_averages_the_graded_legs_only(
    bundle: COREPTemplateBundle,
) -> None:
    # Arrange — row 0070 is the F-IRB / A-IRB legs; slotting reports on row 0080.
    graded = _graded(_covered(FIRB_SLOTTING_CODES))

    # Act
    total = bundle.c08_01[sheet_key(TOTAL_FIRB_SLOTTING_CODE)]

    # Assert
    assert cell(total, "0070", "0230") == pytest.approx(_weighted(graded, lgd_of))
    assert cell(total, "0070", "0260") == pytest.approx(own(graded))


@pytest.mark.parametrize(("total_code", "codes"), TOTALS)
def test_the_pd_range_total_is_the_union_of_its_sheets_rows(
    bundle: COREPTemplateBundle, total_code: str, codes: tuple[str, ...]
) -> None:
    # Arrange
    legs = _graded(_covered(codes))
    total = bundle.c08_03[sheet_key(total_code)]
    leaves = total.filter(~pl.col("row_ref").is_in(list(C08_03_PD_PARENT_REFS)))

    # Act
    rows_of_sheets = {
        row for code in codes for row in bundle.c08_03[sheet_key(code)]["row_ref"].to_list()
    }

    # Assert
    assert set(total["row_ref"].to_list()) == rows_of_sheets
    assert total["row_ref"].to_list() == sorted(total["row_ref"].to_list())
    assert float(leaves["0090"].sum()) == pytest.approx(own(legs))
    assert float(leaves["0060"].sum()) == len(legs)
    assert cell(total, "0080", "0050") == pytest.approx(_weighted(legs, pd_of))


@pytest.mark.parametrize(("total_code", "codes"), TOTALS)
def test_the_backtesting_total_recomputes_its_rate_from_its_own_counts(
    bundle: COREPTemplateBundle, total_code: str, codes: tuple[str, ...]
) -> None:
    # Arrange
    legs = _graded(_covered(codes))
    total = bundle.c08_05[sheet_key(total_code)]

    # Act
    obligors = cell(total, "0080", "0020")
    defaulted = cell(total, "0080", "0030")

    # Assert
    assert obligors == len(legs)
    assert cell(total, "0080", "0040") == pytest.approx((defaulted or 0.0) / len(legs))
    assert cell(total, "0080", "0010") == pytest.approx(sum(pd_of(leg) for leg in legs) / len(legs))


def test_the_grade_total_sums_each_grade_row_across_its_sheets(
    bundle: COREPTemplateBundle,
) -> None:
    # Arrange
    legs = _graded(_covered(FIRB_SLOTTING_CODES))

    # Act
    total = bundle.c08_02[sheet_key(TOTAL_FIRB_SLOTTING_CODE)]

    # Assert
    assert float(total["0260"].sum()) == pytest.approx(own(legs))
    assert total["0005"].to_list() == total["row_ref"].to_list()


# ---------------------------------------------------------------------------
# Readers that add the sheets up
# ---------------------------------------------------------------------------


def test_the_class_sheet_view_leaves_the_totals_out(bundle: COREPTemplateBundle) -> None:
    # Arrange
    totals = {sheet_key(TOTAL_AIRB_CODE), sheet_key(TOTAL_FIRB_SLOTTING_CODE)}

    # Act
    classes = c08_class_sheets(bundle.c08_01)

    # Assert
    assert set(classes) == set(bundle.c08_01) - totals
    assert len(classes) == 15


def test_the_irb_tie_outs_do_not_count_the_total_sheets() -> None:
    """Σ OF 08.01 = OF 02.00 IRB = OV1 rows 3-5 must add the CLASS sheets: with
    the Totals in, every exposure is counted twice."""
    # Arrange
    results = irb_book()
    corep = LedgerShimCorepGenerator().generate_from_lazyframe(results, framework=FRAMEWORK)
    pillar3 = LedgerShimPillar3Generator().generate_from_lazyframe(results, framework=FRAMEWORK)

    # Act
    breaks = check_cross_template_consistency(corep, pillar3, FRAMEWORK)

    # Assert
    assert sheet_key(TOTAL_AIRB_CODE) in corep.c08_01
    assert [
        finding.field_name for finding in breaks if "c08_01" in (finding.field_name or "")
    ] == []


@pytest.mark.parametrize("template", ["c08_01", "c08_02", "c08_03", "c08_05"])
@pytest.mark.parametrize("code", [TOTAL_AIRB_CODE, TOTAL_FIRB_SLOTTING_CODE])
def test_a_cell_on_a_total_sheet_is_explained_as_built_from_its_sheets(
    template: str, code: str
) -> None:
    # Arrange / Act
    reason = summed_sheet_reason(template, sheet_key(code))

    # Assert
    assert reason is not None
    assert "sheets" in reason
