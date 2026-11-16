"""OF 08.01 and 08.02 column 0254 — not reported on an F-IRB or slotting sheet.

PS1/26 Annex II p.112, column 0254 (UNRECOGNISED EXPOSURE ADJUSTMENTS):
"Amounts added in accordance with Articles 153(5A)(b) and 154(4A)(c) ... This
column shall not be reported for sheets relating to the FIRB approach or the
slotting approach." OF 08.02 inherits it (p.118: "0010-0300 Instructions for each
of these columns are the same as for the corresponding numbered columns in OF CR
IRB 1 template"). The adjustment is the one Art. 166D(6) defines for a firm with
permission to apply the Advanced IRB Approach, so an F-IRB or slotting sheet has
nothing to report there — and the PRA001 taxonomy publishes the cell on those
sheets all the same, so only the instruction says to leave it out.

The F-IRB / slotting sheets are 0006, 0010, 0012, 0022, 0024 and their Total
0002; CRR has no column 0254.

Before this change every F-IRB and slotting sheet reported 0.0 there (110 zero
cells on the registered portfolios, never a non-zero one) — a figure where the
instruction says there is none. The leg below carries a non-zero adjustment
deliberately, so that leaving the column out cannot be told apart from summing
a zero.

References:
- PRA PS1/26 Annex II §3.3.3 column 0254 (p.112), §3.3.4 (p.118)
- PRA PS1/26 Art. 153(5A)(b), Art. 154(4A)(c), Art. 166D(6)
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._c02_frames import AIRB_LEGS, MODELLED_LEGS
from tests.unit.reporting.corep._irb_sheet_frames import (
    FIRB_SLOTTING_CODES,
    FRAMEWORK,
    OF08_CORPORATE_NON_SME_AIRB,
    OF08_TOTAL_AIRB,
    OF08_TOTAL_FIRB_SLOTTING,
    cell,
    irb_book,
    sheet_key,
)

#: The A-IRB leg's unrecognised exposure adjustment; every other leg carries 7.
AIRB_ADJUSTMENT = 5.0
OTHER_ADJUSTMENT = 7.0

FIRB_AND_SLOTTING_KEYS = [sheet_key(code) for code in FIRB_SLOTTING_CODES]


def _sheets(template: str) -> dict[str, pl.DataFrame]:
    book = irb_book(MODELLED_LEGS).with_columns(
        pl.when(pl.col("exposure_reference") == "A_OTH")
        .then(pl.lit(AIRB_ADJUSTMENT))
        .otherwise(pl.lit(OTHER_ADJUSTMENT))
        .alias("unrecognised_exposure_adjustment")
    )
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(book, framework=FRAMEWORK)
    return getattr(bundle, template)


@pytest.mark.parametrize("template", ["c08_01", "c08_02"])
@pytest.mark.parametrize("key", [*FIRB_AND_SLOTTING_KEYS, OF08_TOTAL_FIRB_SLOTTING])
def test_an_firb_or_slotting_sheet_reports_no_unrecognised_exposure_adjustment(
    template: str, key: str
) -> None:
    # Arrange
    sheets = _sheets(template)
    assert key in sheets, f"{template} generated no sheet {key}: nothing would be checked"

    # Act
    column = sheets[key]["0254"].to_list()

    # Assert
    assert column == [None] * len(column)


@pytest.mark.parametrize("template", ["c08_01", "c08_02"])
def test_an_airb_sheet_and_its_total_still_report_it(template: str) -> None:
    """Every leg of the book sits in one OF 08.02 band, so each sheet's first
    row is its Total row on OF 08.01 and its only grade row on OF 08.02."""
    # Arrange
    sheets = _sheets(template)
    on_total = AIRB_ADJUSTMENT + OTHER_ADJUSTMENT * (len(AIRB_LEGS) - 1)

    # Act
    sheet = sheets[OF08_CORPORATE_NON_SME_AIRB]
    total = sheets[OF08_TOTAL_AIRB]

    # Assert
    assert cell(sheet, sheet["row_ref"][0], "0254") == pytest.approx(AIRB_ADJUSTMENT)
    assert cell(total, total["row_ref"][0], "0254") == pytest.approx(on_total)
