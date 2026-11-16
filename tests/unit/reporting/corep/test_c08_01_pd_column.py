"""C 08.01 / OF 08.01 column 0010 — PD assigned to the obligor grade or pool.

Why this file exists: the Basel 3.1 OF 08.01 layout left column 0010 out, on the
premise that Basel 3.1 moved PD to OF 08.02 only. The Bank's Annex I template
and the PRA001 taxonomy both carry it, on every sheet and on every row but 0080
(slotting) and 0170 (free deliveries), and ``boe_b0356`` / ``boe_b0410`` read it.

What the column reports, both regimes: the exposure-weighted average of the
post-input-floor PD (``pd_floored``) over the row's legs that CARRY a PD,
weighted by the exposure value. CRR Annex II C 08.01 col 0010: "the exposure
weighted average of the PDs assigned to the obligor grades or pools included in
the aggregation shall be provided. The exposure value (column 0110) shall be used
for the calculation of the exposure-weighted average PD." A slotting leg has no
PD and is left out, not averaged in as a zero — the rule the Total sheets
already apply (``corep/c08_sheets.py``). Before this, CRR reported 0.0 on a
slotting-only row and a diluted PD on a row that mixed the two.

References:
- PRA PS1/26 Annex I OF 08.01 (column 0010); Annex II p.118 (OF 08.02 columns
  0010-0300 "the same as for the corresponding numbered columns in OF CR IRB 1")
- Reg (EU) 2021/451 Annex II C 08.01 column 0010
- Bank of England taxonomy v4.1.1 rules ``boe_b0356``, ``boe_b0410``
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.templates import get_c08_02_columns
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import _irb_results
from tests.unit.reporting.corep._irb_sheet_frames import (
    OF08_CORPORATE_NON_SME_FIRB,
    OF08_SPECIALISED_LENDING_FIRB_SLOTTING,
    OF08_TOTAL_FIRB_SLOTTING,
    cell,
    irb_sheet,
)
from tests.unit.reporting.corep.test_c08_01 import _irb_results_with_slotting

FRAMEWORKS = ("CRR", "BASEL_3_1")

#: (5,500 x 0.005 + 3,000 x 0.01) / 8,500 — the two F-IRB corporate legs of
#: ``_irb_results`` and of ``_irb_results_with_slotting``.
CORPORATE_PD = 57.5 / 8_500

#: (4,000 x 0.02 + 1,000 x 0.0005) / 5,000 — the two F-IRB legs of
#: ``_mixed_specialised_lending``; the slotting leg carries no PD. Pre-floor it
#: would be (80 + 0.2) / 5,000 = 0.01604; averaged with slotting as a zero,
#: 80.5 / 11,000.
MIXED_SL_PD = 80.5 / 5_000


def _mixed_specialised_lending() -> pl.LazyFrame:
    """One specialised-lending sheet holding a PD-carrying and a PD-less leg.

    - SL_FIRB: F-IRB, EAD 4,000, PD 2%.
    - SL_SLOT: slotting, EAD 6,000, no PD (Art. 153(5): slotting has none).
    - SL_FLOOR: F-IRB, EAD 1,000, model PD 0.02% floored to 0.05% (Art. 160(1)).
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["SL_FIRB", "SL_SLOT", "SL_FLOOR"],
            "approach_applied": ["foundation_irb", "slotting", "foundation_irb"],
            "exposure_class": ["specialised_lending"] * 3,
            "bs_type": ["ONB"] * 3,
            "drawn_amount": [4000.0, 6000.0, 1000.0],
            "ead_final": [4000.0, 6000.0, 1000.0],
            "rwa_final": [3000.0, 4200.0, 300.0],
            "risk_weight": [0.75, 0.70, 0.30],
            "pd": [0.02, None, 0.0002],
            "pd_floored": [0.02, None, 0.0005],
            "lgd_floored": [0.40, None, 0.40],
            "irb_maturity_m": [2.5, None, 2.5],
            "expected_loss": [32.0, 0.0, 0.2],
            "counterparty_reference": ["CP1", "CP2", "CP3"],
        }
    )


def test_b31_class_sheet_reports_the_exposure_weighted_pd() -> None:
    # Arrange
    generator = LedgerShimCorepGenerator()

    # Act
    bundle = generator.generate_from_lazyframe(_irb_results(), framework="BASEL_3_1")
    sheet = bundle.c08_01[OF08_CORPORATE_NON_SME_FIRB]

    # Assert
    assert cell(sheet, "0010", "0010") == pytest.approx(CORPORATE_PD, rel=1e-12)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_leg_with_no_pd_is_left_out_of_the_average(framework: str) -> None:
    # Arrange
    frame = _mixed_specialised_lending()
    legs = frame.collect()
    with_pd = legs.filter(pl.col("pd_floored").is_not_null() & (pl.col("ead_final") > 0))
    without_pd = legs.filter(pl.col("pd_floored").is_null() & (pl.col("ead_final") > 0))
    floored = legs.filter(pl.col("pd") < pl.col("pd_floored"))
    assert with_pd.height and without_pd.height, (
        "the sheet must mix PD-carrying and PD-less legs, or leaving one out "
        "cannot be told from averaging it in"
    )
    assert floored.height, "no leg sits below the PD input floor: pre/post-floor would agree"

    # Act
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(frame, framework=framework)
    sheet = bundle.c08_01[
        irb_sheet(framework, "specialised_lending", OF08_SPECIALISED_LENDING_FIRB_SLOTTING)
    ]

    # Assert
    for row in ("0010", "0020", "0070"):
        assert cell(sheet, row, "0010") == pytest.approx(MIXED_SL_PD, rel=1e-12), row
    assert cell(sheet, "0080", "0010") is None


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_a_slotting_only_sheet_reports_no_pd(framework: str) -> None:
    # Arrange
    generator = LedgerShimCorepGenerator()

    # Act
    bundle = generator.generate_from_lazyframe(_irb_results_with_slotting(), framework=framework)
    slotting = bundle.c08_01[
        irb_sheet(framework, "specialised_lending", OF08_SPECIALISED_LENDING_FIRB_SLOTTING)
    ]
    corporate = bundle.c08_01[irb_sheet(framework, "corporate", OF08_CORPORATE_NON_SME_FIRB)]

    # Assert
    assert (cell(slotting, "0010", "0110") or 0.0) > 0, "the slotting sheet holds no exposure"
    assert cell(slotting, "0010", "0010") is None
    assert cell(slotting, "0080", "0010") is None
    assert cell(corporate, "0010", "0010") == pytest.approx(CORPORATE_PD, rel=1e-12)


def test_b31_firb_and_slotting_total_averages_the_legs_that_carry_a_pd() -> None:
    """(5,500 x 0.005 + 3,000 x 0.01 + 2,000 x 0.002) / 10,500: the two slotting
    legs (6,000 of exposure value) are on the Total and carry no PD."""
    # Arrange
    generator = LedgerShimCorepGenerator()

    # Act
    bundle = generator.generate_from_lazyframe(_irb_results_with_slotting(), framework="BASEL_3_1")
    total = bundle.c08_01[OF08_TOTAL_FIRB_SLOTTING]

    # Assert
    assert cell(total, "0010", "0110") == pytest.approx(16_500.0)
    assert cell(total, "0010", "0010") == pytest.approx(61.5 / 10_500, rel=1e-12)
    assert cell(total, "0080", "0010") is None


def test_of0802_keeps_its_pd_column_once_and_in_place() -> None:
    """GUARD, green before and after the fix: OF 08.02 takes its columns from
    OF 08.01's list after the grade identifier. Adding 0010 to OF 08.01 must not
    move it on OF 08.02 nor list it twice there."""
    # Arrange / Act
    refs = [col.ref for col in get_c08_02_columns("BASEL_3_1")]

    # Assert
    assert refs[:3] == ["0005", "0010", "0020"]
    assert len(refs) == len(set(refs))
