"""
The OF-ADJ GCRA cap base is the whole book's paragraph-3A RWEA (P1.212).

Pipeline position:
    calculators -> OutputAggregator.aggregate -> compute_of_adj -> apply_floor_with_impact

PS1/26 Art. 92(2A) defines GCRA as "general credit risk adjustments, gross of tax
effects, of up to 1.25% of risk-weighted exposure amounts calculated in
accordance with paragraph 3A". Paragraph 3A is the sum of paragraph 3's points
"in respect of all the business activities of an institution", calculated
without the IRB Approach. So the base is the standardised RWEA of EVERY credit
and counterparty-credit row - SA, equity, IRB / slotting at their SA-equivalent,
CCR, and the Art. 379 Column 4 free deliveries, which paragraph 3(a) names
("Articles 379 and 380 of CRR"). It is NOT S-TREA: the Art. 378 DvP settlement
lines are own-funds requirements under paragraph 3(ca), not "risk-weighted
exposure amounts", and stay out. The engine summed the modelled subset only,
so for a mixed book the cap was too tight, OF-ADJ too high and the floor
threshold too high (conservative).

Each test is an absolute hand calculation at x = 72.5% (2032). The rule is
Basel-3.1-only: under CRR there is no output floor and no OF-ADJ, which
``tests/unit/test_of_adj.py::test_crr_no_of_adj`` already pins.

References:
- PRA PS1/26 Art. 92(2A), 92(3)(a), 92(3)(ca), 92(3A)
- CRR Art. 378 (DvP), Art. 379(1) Table 2 Column 4 (free deliveries, 1250%)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.contract_columns import pad_irb_branch, pad_sa_branch, pad_slotting_branch

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.aggregator import OutputAggregator

EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})
EMPTY_SLOTTING = pad_slotting_branch(EMPTY)

#: The 1.25% Art. 92(2A) cap applied to the base, as the hand calculations use it.
_CAP = 0.0125


def _config(gcra_amount: float) -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2032, 1, 1), gcra_amount=gcra_amount)


def _irb(rows: list[tuple[str, float, float]]) -> pl.LazyFrame:
    """F-IRB rows ``(reference, rwa_final, sa_rwa)``."""
    return pad_irb_branch(
        pl.LazyFrame(
            {
                "exposure_reference": [row[0] for row in rows],
                "exposure_class": ["corporate"] * len(rows),
                "approach_applied": ["foundation_irb"] * len(rows),
                "ead_final": [100_000_000.0] * len(rows),
                "risk_weight": [0.3] * len(rows),
                "rwa_final": [row[1] for row in rows],
                "sa_rwa": [row[2] for row in rows],
            }
        )
    )


def _sa(rows: list[tuple[str, float, str | None, str | None]]) -> pl.LazyFrame:
    """Standardised rows ``(reference, rwa, risk_type, regulatory_band)``."""
    return pad_sa_branch(
        pl.LazyFrame(
            {
                "exposure_reference": [row[0] for row in rows],
                "exposure_class": ["corporate"] * len(rows),
                "approach_applied": ["standardised"] * len(rows),
                "ead_final": [row[1] for row in rows],
                "risk_weight": [1.0] * len(rows),
                "rwa_final": [row[1] for row in rows],
                "sa_rwa": [row[1] for row in rows],
                "risk_type": pl.Series([row[2] for row in rows], dtype=pl.String),
                "regulatory_band": pl.Series([row[3] for row in rows], dtype=pl.String),
            }
        )
    )


def _summary(gcra_amount: float, irb: pl.LazyFrame, sa: pl.LazyFrame):  # noqa: ANN202
    result = OutputAggregator().aggregate(sa, irb, EMPTY_SLOTTING, None, _config(gcra_amount))
    assert result.output_floor_summary is not None
    return result.output_floor_summary


_IRB_BOOK = [("IRB1", 30_000_000.0, 60_000_000.0)]
_SA_BOOK = [("SA1", 40_000_000.0, None, None)]


def test_gcra_cap_base_includes_the_standardised_book() -> None:
    """
    A 40m SA book raises the cap base from 60m to 100m.

    Arrange: F-IRB 30m own / 60m SA-equivalent, plus a 40m standardised row;
             GCRA 1.0m.
    Act:     aggregate.
    Assert:  the cap is 1.25% x 100m = 1.25m, so GCRA enters whole at 1.0m and
             OF-ADJ = -12.5 x 1.0m. Before the fix the base was 60m: GCRA capped
             at 750,000, OF-ADJ -9,375,000.
    """
    # Arrange / Act
    summary = _summary(1_000_000.0, _irb(_IRB_BOOK), _sa(_SA_BOOK))

    # Assert
    assert summary.gcra_amount == pytest.approx(1_000_000.0, rel=1e-9)
    assert summary.of_adj == pytest.approx(-12_500_000.0, rel=1e-9)


def test_gcra_cap_base_keeps_free_deliveries_and_drops_dvp_lines() -> None:
    """
    Art. 379 Column 4 free deliveries are in the base; Art. 378 DvP lines are not.

    Arrange: the 100m book plus two settlement rows of 20m RWEA each - a DvP line
             (band ``dvp_16_30``) and a Column 4 free delivery (band
             ``non_dvp_col4_t5_plus``); GCRA 1.6m.
    Act:     aggregate.
    Assert:  base = 60 + 40 + 20 = 120m, cap 1.5m, OF-ADJ -18.75m. Each wrong rule
             gives a distinct figure: dropping every SETTLEMENT_FAILED_TRADE row
             caps at 1.25m, dropping none at 1.6m (cap 1.75m), the modelled subset
             at 750,000.
    """
    # Arrange
    sa = _sa(
        [
            *_SA_BOOK,
            ("FT_DVP", 20_000_000.0, "SETTLEMENT_FAILED_TRADE", "dvp_16_30"),
            ("FT_COL4", 20_000_000.0, "SETTLEMENT_FAILED_TRADE", "non_dvp_col4_t5_plus"),
        ]
    )

    # Act
    summary = _summary(1_600_000.0, _irb(_IRB_BOOK), sa)

    # Assert
    assert summary.gcra_amount == pytest.approx(_CAP * 120_000_000.0, rel=1e-9)
    assert summary.of_adj == pytest.approx(-12.5 * 1_500_000.0, rel=1e-9)


def test_gcra_below_the_cap_is_unchanged() -> None:
    """
    A GCRA below both the old and the new cap passes through untouched.

    Arrange: the 100m book with GCRA 500,000 (below 1.25% of 60m and of 100m).
    Act:     aggregate.
    Assert:  GCRA 500,000 and OF-ADJ -6,250,000 - the row SHORT of the clamp
             (LESSONS B5) beside the rows past it above.
    """
    # Arrange / Act
    summary = _summary(500_000.0, _irb(_IRB_BOOK), _sa(_SA_BOOK))

    # Assert
    assert summary.gcra_amount == pytest.approx(500_000.0, rel=1e-9)
    assert summary.of_adj == pytest.approx(-6_250_000.0, rel=1e-9)


def test_non_finite_sa_equivalent_does_not_uncap_gcra() -> None:
    """
    A NaN SA-equivalent counts as zero in the base, never as an uncapped GCRA.

    Arrange: the 100m book plus a second F-IRB row whose ``sa_rwa`` is NaN; GCRA
             2.0m.
    Act:     aggregate.
    Assert:  the cap is 1.25% of the finite 100m, i.e. 1.25m. Before the fix the
             NaN poisoned the sum and ``min(2.0m, NaN)`` returned the full 2.0m.
    """
    # Arrange
    irb = _irb([*_IRB_BOOK, ("IRB_NAN", 10_000_000.0, float("nan"))])

    # Act
    summary = _summary(2_000_000.0, irb, _sa(_SA_BOOK))

    # Assert
    assert summary.gcra_amount == pytest.approx(1_250_000.0, rel=1e-9)
