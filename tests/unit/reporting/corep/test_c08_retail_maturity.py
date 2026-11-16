"""C / OF 08.01 and 08.02 column 0250 — no maturity on a retail sheet.

Annex II column 0250 (EXPOSURE-WEIGHTED AVERAGE MATURITY VALUE (DAYS)), both
regimes:

- PS1/26 Annex II p.111: "This data shall not be reported for the exposure
  values for which the maturity is not an element in the calculation of
  risk-weighted exposure amounts. This column shall therefore not be filled in
  for the exposure class 'retail' or for exposures subject to the slotting
  approach."
- Reg (EU) 2021/451 Annex II p.104 (C 08.01): "... That means that this column
  shall not be filled in for the exposure class "retail"."

C / OF 08.02 inherits it ("0010-0300 Instructions for each of these columns are
the same as for the corresponding numbered columns in [OF] CR IRB 1 template",
PS1/26 Annex II p.118; CRR Annex II p.108). C 08.03 col 0080 already applied
the same sentence (``corep/c08_03_cells.py``); its two sibling templates did
not, and the A-IRB Total averaged the retail legs' maturity in with the
corporate legs'. On the registered portfolios that put 1,673 days on retail
sheets 0015 / 0017 / 0021 and broke the Bank's Error rule ``boe_b0748`` on
column 0250 — which sums the A-IRB sheets — on two returns.

References:
- PRA PS1/26 Annex II §3.3.3 col 0250 (p.111), §3.3.4 (p.118)
- Reg (EU) 2021/451 Annex II C 08.01 col 0250 (p.104), C 08.02 (p.108)
- CRR Art. 154 (retail risk weights carry no maturity term)
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._c02_frames import MODELLED_LEGS, Leg
from tests.unit.reporting.corep._irb_sheet_frames import (
    FRAMEWORK,
    OF08_CORPORATE_NON_SME_AIRB,
    OF08_RETAIL_OTHER_NON_SME,
    OF08_TOTAL_AIRB,
    cell,
    irb_book,
    irb_sheet,
    maturity_of,
)

FRAMEWORKS = ("CRR", "BASEL_3_1")
DAYS = 365.0

RETAIL = next(leg for leg in MODELLED_LEGS if leg.reference == "A_ONON")
CORPORATE = next(leg for leg in MODELLED_LEGS if leg.reference == "A_OTH")


def _sheets(legs: tuple[Leg, ...], template: str, framework: str) -> dict[str, pl.DataFrame]:
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(irb_book(legs), framework=framework)
    return getattr(bundle, template)


def _retail_key(framework: str) -> str:
    return irb_sheet(framework, "retail_other", OF08_RETAIL_OTHER_NON_SME)


def _corporate_key(framework: str) -> str:
    return irb_sheet(framework, "corporate", OF08_CORPORATE_NON_SME_AIRB)


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("template", ["c08_01", "c08_02"])
def test_a_retail_sheet_reports_no_maturity_on_any_row(template: str, framework: str) -> None:
    # Arrange
    assert maturity_of(RETAIL) > 0.0, "the retail leg must carry a maturity to leave out"

    # Act
    sheet = _sheets((RETAIL, CORPORATE), template, framework)[_retail_key(framework)]

    # Assert
    assert sheet.height > 0
    assert sheet["0250"].to_list() == [None] * sheet.height


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("template", ["c08_01", "c08_02"])
def test_a_corporate_sheet_still_reports_its_maturity(template: str, framework: str) -> None:
    # Arrange
    expected = DAYS * maturity_of(CORPORATE)

    # Act
    sheet = _sheets((RETAIL, CORPORATE), template, framework)[_corporate_key(framework)]

    # Assert
    first_row = sheet["row_ref"][0]
    assert cell(sheet, first_row, "0250") == pytest.approx(expected)


@pytest.mark.parametrize("template", ["c08_01", "c08_02"])
def test_the_airb_total_averages_the_maturity_of_the_non_retail_legs_only(template: str) -> None:
    # Arrange
    corporate_only = DAYS * maturity_of(CORPORATE)
    all_legs = (
        DAYS
        * (maturity_of(RETAIL) * RETAIL.own + maturity_of(CORPORATE) * CORPORATE.own)
        / (RETAIL.own + CORPORATE.own)
    )
    assert all_legs != pytest.approx(corporate_only), (
        "equal maturities would make averaging the retail leg in undetectable"
    )

    # Act
    total = _sheets((RETAIL, CORPORATE), template, FRAMEWORK)[OF08_TOTAL_AIRB]

    # Assert
    first_row = total["row_ref"][0]
    assert cell(total, first_row, "0250") == pytest.approx(corporate_only)


@pytest.mark.parametrize("template", ["c08_01", "c08_02"])
def test_a_total_of_retail_sheets_alone_reports_no_maturity(template: str) -> None:
    # Arrange / Act
    total = _sheets((RETAIL,), template, FRAMEWORK)[OF08_TOTAL_AIRB]

    # Assert
    assert total.height > 0
    assert total["0250"].to_list() == [None] * total.height
