"""OF 08.01 rows 0031, 0032, 0001, 0033, 0034, 0035 — off-balance-sheet items by conversion factor.

Why this file exists: the Basel 3.1 OF 08.01 generator never produced these
rows. They were bound to no leg ("B31's CCF-bucket ... rows are inert"), so on
every sheet row 0030 carried the off-balance-sheet total and its breakdown was
empty, and the row axis itself was wrong — no row 0001 (the 40% bucket), and
0033 / 0034 / 0035 labelled with the factor of the bucket BELOW them. The Bank's
Error rules ``boe_b0741`` and ``boe_b0742`` (row 0030 = the sum of the six rows)
failed wherever an IRB off-balance-sheet item existed.

PS1/26 Annex II p.116: "For exposures subject to the slotting approach, the
FIRB approach, or the AIRB approach where neither conversion factors nor EADs
are estimated, institutions shall report values in rows that correspond to the
applicable conversion factors in Article 111 ... For exposures subject to the
AIRB approach for which conversion factors are estimated, or where EADs are
estimated directly, institutions shall report values in row 0035."

The book below has an F-IRB leg in each Table A1 bucket and four A-IRB legs that
separate the own-estimate row from a value match: a revolving own estimate, one
FLOORED to 0.20 (half of a 40% item — by value it would land in the 20% row), a
non-revolving leg that SUPPLIES an own estimate the engine may not apply (Art.
166D(1)(b): the Table A1 factor), and a directly estimated EAD.

References:
- PRA PS1/26 Annex II §3.3.3 rows 0031-0035 and 0001 (p.116)
- PRA PS1/26 Art. 111(1) Table A1; Art. 166D(1)(a), (1)(b) and (3)
- Bank of England taxonomy v4.1.1 rules ``boe_b0741``, ``boe_b0742``
"""

from __future__ import annotations

import logging

import polars as pl
import pytest

from rwa_calc.reporting.corep.c08_sheets import c08_class_sheets
from rwa_calc.reporting.corep.ccf_buckets import OF08_01_CCF_ROWS
from rwa_calc.reporting.corep.of08_published_cells import get_c08_01_unreported_cells
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._irb_sheet_frames import (
    OF08_CORPORATE_NON_SME_AIRB,
    OF08_CORPORATE_NON_SME_FIRB,
    OF08_INSTITUTIONS_FIRB,
    cell,
)

FRAMEWORK = "BASEL_3_1"
OFF_BS_ROW = "0030"

#: boe_b0742's 30-column scope less the two that do not add across rows: 0250
#: (an exposure-weighted average maturity) and 0300 (a count of obligors).
ADDITIVE_COLUMNS = (
    "0020", "0035", "0040", "0050", "0060", "0070", "0080", "0090", "0110", "0150",
    "0160", "0170", "0171", "0172", "0173", "0180", "0190", "0200", "0210", "0251",
    "0252", "0253", "0254", "0260", "0280", "0281", "0282", "0290",
)  # fmt: skip

#: (reference, approach, exposure type, gross, applied ccf, ccf_modelled,
#: ead_modelled, revolving, obligor, the row the leg belongs in). Exposure value
#: is gross x ccf, or the own estimate of EAD.
_F, _A = "foundation_irb", "advanced_irb"
type _Leg = tuple[str, str, str, float, float, float | None, float | None, bool, str, str]
LEGS: tuple[_Leg, ...] = (
    ("F10", _F, "facility_undrawn", 1_000.0, 0.1, None, None, False, "CP_A", "0031"),
    ("F20", _F, "contingent", 2_000.0, 0.2, None, None, False, "CP_B", "0032"),
    ("F40", _F, "facility_undrawn", 3_000.0, 0.4, None, None, False, "CP_A", "0001"),
    ("F50", _F, "facility_undrawn", 4_000.0, 0.5, None, None, False, "CP_C", "0033"),
    ("F100", _F, "contingent", 5_000.0, 1.0, None, None, False, "CP_D", "0034"),
    ("A20", _A, "facility_undrawn", 700.0, 0.2, None, None, False, "CP_E", "0032"),
    ("A_NONREV", _A, "contingent", 2_500.0, 0.5, 0.25, None, False, "CP_F", "0033"),
    ("A_OWN", _A, "facility_undrawn", 2_000.0, 0.3, 0.3, None, True, "CP_G", "0035"),
    ("A_FLOOR", _A, "facility_undrawn", 1_500.0, 0.2, 0.1, None, True, "CP_H", "0035"),
    ("A_EAD", _A, "facility_undrawn", 1_800.0, 0.4, None, 900.0, False, "CP_J", "0035"),
)
#: One drawn loan per sheet, carrying ccf 1.0, so an on-balance-sheet leg in a
#: bucket would show as 6,000 / 3,000 too much there.
LOANS: tuple[tuple[str, str, float, str], ...] = (
    ("F_LOAN", _F, 6_000.0, "CP_K"),
    ("A_LOAN", _A, 3_000.0, "CP_L"),
)
#: F50's covered part, guaranteed by an F-IRB institution: it leaves the
#: corporate sheet's row 0033 (col 0070) and arrives on the institution's.
GUARANTEED_LEG, GUARANTEED_AMOUNT, GUARANTEED_ROW = "F50", 1_000.0, "0033"

SHEET_OF = {_F: OF08_CORPORATE_NON_SME_FIRB, _A: OF08_CORPORATE_NON_SME_AIRB}


def _book(extra: tuple[_Leg, ...] = ()) -> pl.LazyFrame:
    """The legs and loans above as a synthetic Basel 3.1 ledger."""
    legs = LEGS + extra
    refs = [leg[0] for leg in legs] + [loan[0] for loan in LOANS]
    approach = [leg[1] for leg in legs] + [loan[1] for loan in LOANS]
    kind = [leg[2] for leg in legs] + ["loan"] * len(LOANS)
    ccf = [leg[4] for leg in legs] + [1.0] * len(LOANS)
    ead = [leg[6] if leg[6] is not None else leg[3] * leg[4] for leg in legs] + [
        loan[2] for loan in LOANS
    ]
    n = len(refs)
    covered = [GUARANTEED_AMOUNT if ref == GUARANTEED_LEG else 0.0 for ref in refs]
    return pl.LazyFrame(
        {
            "exposure_reference": refs,
            "approach_applied": approach,
            "exposure_class": ["corporate"] * n,
            "exposure_type": kind,
            "drawn_amount": [0.0] * len(legs) + [loan[2] for loan in LOANS],
            "undrawn_amount": _side(legs, "facility_undrawn"),
            "nominal_amount": _side(legs, "contingent"),
            "ccf": ccf,
            "ccf_modelled": [leg[5] for leg in legs] + [None] * len(LOANS),
            "ead_modelled": [leg[6] for leg in legs] + [None] * len(LOANS),
            "is_revolving": [leg[7] for leg in legs] + [False] * len(LOANS),
            "ead_final": ead,
            "rwa_final": [value * 0.8 for value in ead],
            "rwa_pre_adjustments": [value * 0.8 for value in ead],
            "sa_rwa": list(ead),
            "risk_weight": [0.8] * n,
            "pd_floored": [0.01] * n,
            "lgd_floored": [0.45] * n,
            "irb_maturity_m": [2.5] * n,
            "expected_loss": [value * 0.0045 for value in ead],
            "scra_provision_amount": [value * 0.001 for value in ead],
            "gcra_provision_amount": [0.0] * n,
            "counterparty_reference": [leg[8] for leg in legs] + [loan[3] for loan in LOANS],
            "guaranteed_portion": covered,
            "protection_type": ["guarantee" if c else None for c in covered],
            "post_crm_exposure_class_guaranteed": ["institution" if c else None for c in covered],
        }
    )


def _side(legs: tuple[_Leg, ...], exposure_type: str) -> list[float]:
    """Each leg's gross on the raw carrier its exposure type reads; 0 elsewhere."""
    return [leg[3] if leg[2] == exposure_type else 0.0 for leg in legs] + [0.0] * len(LOANS)


def _gross_in(row: str, approach: str) -> float:
    return sum(leg[3] for leg in LEGS if leg[9] == row and leg[1] == approach)


def _exposure_value_in(row: str, approach: str) -> float:
    return sum(
        leg[6] if leg[6] is not None else leg[3] * leg[4]
        for leg in LEGS
        if leg[9] == row and leg[1] == approach
    )


@pytest.fixture(scope="module")
def sheets() -> dict[str, pl.DataFrame]:
    return LedgerShimCorepGenerator().generate_from_lazyframe(_book(), framework=FRAMEWORK).c08_01


def test_the_book_can_tell_a_bucket_from_its_neighbour() -> None:
    # Arrange / Act
    rows = {leg[9] for leg in LEGS}
    obligor_rows: dict[str, set[str]] = {}
    for leg in LEGS:
        obligor_rows.setdefault(leg[8], set()).add(leg[9])
    floored = [leg for leg in LEGS if leg[0] == "A_FLOOR"]

    # Assert
    assert rows == set(OF08_01_CCF_ROWS), "every bucket row must hold a leg"
    assert any(len(found) > 1 for found in obligor_rows.values()), (
        "no obligor sits in two buckets: an obligor count summed across rows "
        "could not be told from one counted once"
    )
    assert floored and floored[0][4] == 0.2, (
        "the floored own estimate must equal a Table A1 factor, or precedence is untested"
    )


@pytest.mark.parametrize(("row", "approach"), [(r, a) for r in OF08_01_CCF_ROWS for a in (_F, _A)])
def test_each_bucket_row_reports_exactly_its_own_legs(
    sheets: dict[str, pl.DataFrame], row: str, approach: str
) -> None:
    # Arrange
    sheet = sheets[SHEET_OF[approach]]
    gross = _gross_in(row, approach)

    # Act
    reported_gross = cell(sheet, row, "0020")
    reported_value = cell(sheet, row, "0110")

    # Assert
    if gross == 0.0:
        assert reported_gross is None and reported_value is None, "an empty bucket is null"
        return
    assert reported_gross == pytest.approx(gross)
    assert reported_value == pytest.approx(_exposure_value_in(row, approach))


def test_a_floored_own_estimate_is_filed_as_an_own_estimate_not_by_its_value(
    sheets: dict[str, pl.DataFrame],
) -> None:
    # Arrange
    sheet = sheets[OF08_CORPORATE_NON_SME_AIRB]

    # Act
    twenty, own = cell(sheet, "0032", "0020"), cell(sheet, "0035", "0020")

    # Assert
    assert twenty == pytest.approx(700.0), "A_FLOOR (1,500 at 0.20) is not a Table A1 20% item"
    assert own == pytest.approx(2_000.0 + 1_500.0 + 1_800.0)


@pytest.mark.parametrize("column", ADDITIVE_COLUMNS)
@pytest.mark.parametrize("sheet_key", [OF08_CORPORATE_NON_SME_FIRB, OF08_CORPORATE_NON_SME_AIRB])
def test_the_off_balance_sheet_row_is_the_sum_of_its_six_rows(
    sheets: dict[str, pl.DataFrame], sheet_key: str, column: str
) -> None:
    """boe_b0742 on its additive columns; an unreported cell counts as zero, as
    the rule's ``dv: emptySequence()`` sums nothing for it."""
    # Arrange
    sheet = sheets[sheet_key]
    assert cell(sheet, OFF_BS_ROW, "0020"), "the sheet holds no off-balance-sheet item"

    # Act
    breakdown = sum(cell(sheet, row, column) or 0.0 for row in OF08_01_CCF_ROWS)

    # Assert
    assert (cell(sheet, OFF_BS_ROW, column) or 0.0) == pytest.approx(breakdown, abs=1e-9)


def test_the_identity_is_live_on_the_columns_that_carry_money(
    sheets: dict[str, pl.DataFrame],
) -> None:
    """Adequacy: the parametrised identity is not proved by zeros."""
    # Arrange
    sheet = sheets[OF08_CORPORATE_NON_SME_FIRB]

    # Act
    live = {column for column in ADDITIVE_COLUMNS if cell(sheet, OFF_BS_ROW, column)}

    # Assert
    assert {"0020", "0040", "0070", "0090", "0110", "0251", "0260", "0280", "0290"} <= live


@pytest.mark.parametrize("sheet_key", [OF08_CORPORATE_NON_SME_FIRB, OF08_CORPORATE_NON_SME_AIRB])
def test_the_unpublished_columns_are_empty_on_the_bucket_rows_only(
    sheets: dict[str, pl.DataFrame], sheet_key: str
) -> None:
    # Arrange
    sheet = sheets[sheet_key]
    declared = get_c08_01_unreported_cells(FRAMEWORK, sheet_key)
    populated = [row for row in OF08_01_CCF_ROWS if cell(sheet, row, "0020")]
    assert len(populated) >= 2, "fewer than two populated buckets"

    # Act
    filled = {
        (row, column)
        for row in populated
        for column in declared[row]
        if cell(sheet, row, column) is not None
    }

    # Assert
    assert all(len(declared[row]) == 13 for row in OF08_01_CCF_ROWS)
    assert filled == set()
    assert cell(sheet, OFF_BS_ROW, "0275") is not None, "row 0030 publishes 0275 and keeps it"


def test_the_obligor_count_is_per_row(sheets: dict[str, pl.DataFrame]) -> None:
    # Arrange
    sheet = sheets[OF08_CORPORATE_NON_SME_FIRB]

    # Act / Assert
    assert cell(sheet, "0031", "0300") == 1
    assert cell(sheet, "0001", "0300") == 1
    assert cell(sheet, OFF_BS_ROW, "0300") == 4, "CP_A is one obligor on row 0030"


@pytest.mark.parametrize("column", ["0080", "0090"])
def test_a_guaranteed_off_balance_sheet_item_arrives_in_its_own_bucket(
    sheets: dict[str, pl.DataFrame], column: str
) -> None:
    # Arrange
    destination = sheets[OF08_INSTITUTIONS_FIRB]
    assert cell(destination, OFF_BS_ROW, "0080") == pytest.approx(GUARANTEED_AMOUNT), (
        "no off-balance-sheet inflow reached the institution sheet"
    )

    # Act
    breakdown = sum(cell(destination, row, column) or 0.0 for row in OF08_01_CCF_ROWS)

    # Assert
    assert cell(destination, GUARANTEED_ROW, column) == pytest.approx(GUARANTEED_AMOUNT)
    assert cell(destination, OFF_BS_ROW, column) == pytest.approx(breakdown)


def test_the_outflow_leaves_the_bucket_it_was_in(sheets: dict[str, pl.DataFrame]) -> None:
    # Arrange
    origin = sheets[OF08_CORPORATE_NON_SME_FIRB]

    # Act / Assert
    assert cell(origin, GUARANTEED_ROW, "0070") == pytest.approx(-GUARANTEED_AMOUNT)
    assert cell(origin, GUARANTEED_ROW, "0090") == pytest.approx(4_000.0 - GUARANTEED_AMOUNT)


def _unbucketed(sheets: dict[str, pl.DataFrame]) -> float:
    """Off-balance-sheet gross on row 0030 that no bucket row carries, over the
    class sheets (LESSONS B6: sum what matches no row, never read the row list)."""
    total = 0.0
    for sheet in c08_class_sheets(sheets).values():
        breakdown = sum(cell(sheet, row, "0020") or 0.0 for row in OF08_01_CCF_ROWS)
        total += (cell(sheet, OFF_BS_ROW, "0020") or 0.0) - breakdown
    return total


def test_no_off_balance_sheet_money_misses_its_bucket(
    sheets: dict[str, pl.DataFrame], caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange
    with caplog.at_level(logging.WARNING, logger="rwa_calc.reporting.corep"):
        clean = LedgerShimCorepGenerator().generate_from_lazyframe(_book(), framework=FRAMEWORK)

    # Act
    missing = _unbucketed(clean.c08_01)

    # Assert
    assert missing == pytest.approx(0.0, abs=1e-9)
    assert not [r for r in caplog.records if "conversion-factor" in r.getMessage()]


def test_a_factor_that_matches_no_bucket_is_warned_about_and_measured(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The alarm and the identity both discriminate: silent and 0.00 on the
    clean book (test above), loud and exactly the stray amount here."""
    # Arrange
    stray = ("F30", _F, "facility_undrawn", 800.0, 0.3, None, None, False, "CP_M", "none")

    # Act
    with caplog.at_level(logging.WARNING, logger="rwa_calc.reporting.corep"):
        bundle = LedgerShimCorepGenerator().generate_from_lazyframe(
            _book((stray,)), framework=FRAMEWORK
        )

    # Assert
    assert _unbucketed(bundle.c08_01) == pytest.approx(800.0)
    warnings = [r.getMessage() for r in caplog.records if "conversion-factor" in r.getMessage()]
    assert warnings and "800" in warnings[0]


def test_crr_c08_01_has_no_conversion_factor_rows() -> None:
    # Arrange / Act
    sheets = LedgerShimCorepGenerator().generate_from_lazyframe(_book(), framework="CRR").c08_01
    corporate = sheets["corporate"]

    # Assert
    assert not set(OF08_01_CCF_ROWS) & set(corporate["row_ref"].to_list())
    assert cell(corporate, OFF_BS_ROW, "0020") == pytest.approx(sum(leg[3] for leg in LEGS))
