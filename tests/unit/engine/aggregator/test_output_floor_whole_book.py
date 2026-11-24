"""
The Basel 3.1 output floor is taken over the whole book, not the modelled subset (P1.367).

Pipeline position:
    calculators -> OutputAggregator.aggregate -> apply_floor_with_impact

PS1/26 Art. 92(2A) sets ``TREA = max{U-TREA; x . S-TREA + OF-ADJ}``. Paragraph 3
builds U-TREA from points (a)-(f) "in respect of all the business activities of
an institution", and paragraph 3A builds S-TREA as "the sum of points (a) to (f)
of paragraph 3 ... calculated without using ... the IRB Approach". The SA book,
the equity book and the CVA own-funds requirement (para 3(d), x 12.5 by
para 4(b), not on the 3A exclusion list) therefore sit inside BOTH legs of the
max. They cancel only at ``x = 1``.

Until this fix the engine summed both legs over ``FLOOR_ELIGIBLE_APPROACHES``
alone and re-added the SA and equity books OUTSIDE the max, so wherever its floor
bound it overstated TREA by up to ``(1 - x) . (SA + equity)``, and its floor bound
on books where the article's does not (the "band" cases below).

Every expectation is an absolute hand calculation. Each case is run at both
Art. 92(5) multipliers that matter: 60% (2027) and the fully phased 72.5%. The
CRR leg is a regression guard: CRR has no output floor (the ``output_floor``
pack Feature is disabled), so it cannot be reddened by this defect and must not
move.

The shortfall is allocated to the floor-eligible (modelled) rows pro rata to
their ``sa_rwa`` and SA / equity rows keep their own RWEA. The article is silent
on allocation; that is the recorded firm/owner choice, asserted here so a change
to it is deliberate.

References:
- PRA PS1/26 Art. 92(2A), 92(3), 92(3A), 92(4), 92(5)
- PS1/26 Annex II OF 02.00 row 0010 col 0030; OF 02.01 cols 0030 / 0040
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.contract_columns import pad_irb_branch, pad_sa_branch, pad_slotting_branch

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.aggregator import OutputAggregator
from rwa_calc.engine.aggregator._floor import apply_floor_with_impact

EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})
EMPTY_SLOTTING = pad_slotting_branch(EMPTY)

#: Art. 92(5)(a): x = 60% from 1 January 2027 to 31 December 2027.
DATE_X_60 = date(2027, 6, 30)
#: Art. 92(2A): x = 72.5% once the transitional schedule has run out.
DATE_X_725 = date(2032, 1, 1)


def _sa_frame(rwa: float) -> pl.LazyFrame:
    """One standardised row whose own RWEA is also its standardised RWEA."""
    return pad_sa_branch(
        pl.LazyFrame(
            {
                "exposure_reference": ["SA1"],
                "exposure_class": ["corporate"],
                "approach_applied": ["standardised"],
                "ead_final": [rwa],
                "risk_weight": [1.0],
                "rwa_final": [rwa],
                "sa_rwa": [rwa],
            }
        )
    )


def _irb_frame(rwa: float, sa_rwa: float) -> pl.LazyFrame:
    """One F-IRB row with its own RWEA and its SA-equivalent."""
    return pad_irb_branch(
        pl.LazyFrame(
            {
                "exposure_reference": ["IRB1"],
                "exposure_class": ["corporate"],
                "approach_applied": ["foundation_irb"],
                "ead_final": [sa_rwa],
                "risk_weight": [rwa / sa_rwa],
                "rwa_final": [rwa],
                "sa_rwa": [sa_rwa],
            }
        )
    )


def _run(reporting_date: date, sa_rwa: float, irb_rwa: float, irb_sa_rwa: float):  # noqa: ANN202
    config = CalculationConfig.basel_3_1(reporting_date=reporting_date)
    result = OutputAggregator().aggregate(
        _sa_frame(sa_rwa), _irb_frame(irb_rwa, irb_sa_rwa), EMPTY_SLOTTING, None, config
    )
    rows = {row["exposure_reference"]: row for row in result.results.collect().to_dicts()}
    return result, rows


# Each case: (reporting date, SA RWEA, F-IRB own RWEA, F-IRB sa_rwa,
#             expected TREA, expected floor binding, engine-before-fix TREA).
#
# both_bind  - the article's floor binds: TREA = x . (SA + S_irb) > SA + U_irb.
# band       - only the subset formula bound: x . S_irb > U_irb, but
#              x . (SA + S_irb) <= SA + U_irb, so the article's floor does not.
_CASES = {
    # U = 130,000; x.S = 0.725 x 200,000 = 145,000. Before: 100,000 + 72,500.
    "both_bind_x725": (DATE_X_725, 100_000.0, 30_000.0, 100_000.0, 145_000.0, True, 172_500.0),
    # U = 110,000; x.S = 0.60 x 200,000 = 120,000. Before: 100,000 + 60,000.
    "both_bind_x60": (DATE_X_60, 100_000.0, 10_000.0, 100_000.0, 120_000.0, True, 160_000.0),
    # U = 550,000; x.S = 0.725 x 600,000 = 435,000. Before: 500,000 + 72,500.
    "band_x725": (DATE_X_725, 500_000.0, 50_000.0, 100_000.0, 550_000.0, False, 572_500.0),
    # U = 130,000; x.S = 0.60 x 200,000 = 120,000. Before: 100,000 + 60,000.
    "band_x60": (DATE_X_60, 100_000.0, 30_000.0, 100_000.0, 130_000.0, False, 160_000.0),
}


@pytest.mark.parametrize(
    ("reporting_date", "sa_rwa", "irb_rwa", "irb_sa_rwa", "trea", "binding", "before"),
    list(_CASES.values()),
    ids=list(_CASES),
)
def test_output_floor_max_is_taken_over_the_whole_book(
    reporting_date: date,
    sa_rwa: float,
    irb_rwa: float,
    irb_sa_rwa: float,
    trea: float,
    binding: bool,
    before: float,
) -> None:
    """
    TREA = max(U-TREA, x . S-TREA + OF-ADJ) with the SA book in both legs.

    Arrange: one standardised row and one F-IRB row, OF-ADJ = 0.
    Act:     aggregate under Basel 3.1.
    Assert:  the post-floor total, the ledger sum and the binding flag are the
             article's, and the SA row keeps its own RWEA.
    """
    # Arrange
    assert before != pytest.approx(trea), "the case must separate the two formulas"

    # Act
    result, rows = _run(reporting_date, sa_rwa, irb_rwa, irb_sa_rwa)
    summary = result.output_floor_summary
    assert summary is not None

    # Assert
    assert summary.total_rwa_post_floor == pytest.approx(trea, rel=1e-9)
    assert sum(row["rwa_final"] for row in rows.values()) == pytest.approx(trea, rel=1e-9)
    assert summary.portfolio_floor_binding is binding
    assert rows["IRB1"]["is_floor_binding"] is binding
    assert rows["SA1"]["rwa_final"] == pytest.approx(sa_rwa, rel=1e-9)
    assert rows["IRB1"]["rwa_final"] == pytest.approx(trea - sa_rwa, rel=1e-9)


def test_output_floor_summary_states_the_article_aggregates() -> None:
    """
    The summary's legs are the Art. 92(3) / 92(3A) aggregates over the whole book.

    Arrange: the both-binding x = 72.5% book (SA 100,000; F-IRB 30,000 own /
             100,000 SA-equivalent).
    Act:     aggregate.
    Assert:  U-TREA 130,000, S-TREA 200,000, threshold 145,000, shortfall 15,000;
             the modelled subset carries the whole add-on (30,000 + 15,000) and the
             SA book stays at 100,000; no CVA was supplied.
    """
    # Arrange / Act
    result, _rows = _run(DATE_X_725, 100_000.0, 30_000.0, 100_000.0)
    summary = result.output_floor_summary
    assert summary is not None

    # Assert
    assert summary.u_trea == pytest.approx(130_000.0, rel=1e-9)
    assert summary.s_trea == pytest.approx(200_000.0, rel=1e-9)
    assert summary.floor_threshold == pytest.approx(145_000.0, rel=1e-9)
    assert summary.shortfall == pytest.approx(15_000.0, rel=1e-9)
    assert summary.floored_modelled_rwa == pytest.approx(45_000.0, rel=1e-9)
    assert summary.sa_rwa_total == pytest.approx(100_000.0, rel=1e-9)
    assert summary.equity_rwa_total == pytest.approx(0.0, abs=1e-9)
    assert summary.cva_rwa == pytest.approx(0.0, abs=1e-9)


def test_crr_totals_do_not_move() -> None:
    """
    CRR has no output floor: the same book sums to its own RWEA.

    Arrange: the both-binding book under CRR.
    Act:     aggregate.
    Assert:  no floor summary, and the ledger is 100,000 + 30,000.

    A regression guard rather than a fail-first test: the ``output_floor`` pack
    Feature is disabled under CRR, so this defect could never reach it.
    """
    # Arrange
    config = CalculationConfig.crr(reporting_date=date(2025, 12, 31))

    # Act
    result = OutputAggregator().aggregate(
        _sa_frame(100_000.0), _irb_frame(30_000.0, 100_000.0), EMPTY_SLOTTING, None, config
    )

    # Assert
    assert result.output_floor_summary is None
    total = result.results.collect()["rwa_final"].sum()
    assert total == pytest.approx(130_000.0, rel=1e-9)


# =============================================================================
# The equity book and the CVA requirement sit in both legs too
# =============================================================================


def _combined(*rows: tuple[str, str, float, float]) -> pl.LazyFrame:
    """A combined results frame from ``(reference, approach, rwa_final, sa_rwa)``."""
    return pl.LazyFrame(
        {
            "exposure_reference": [row[0] for row in rows],
            "approach_applied": [row[1] for row in rows],
            "exposure_class": ["corporate"] * len(rows),
            "rwa_final": [row[2] for row in rows],
            "sa_rwa": [row[3] for row in rows],
        }
    )


def test_equity_book_is_inside_both_legs() -> None:
    """
    Equity RWEA enters U-TREA and S-TREA at the same value.

    Arrange: equity 50,000 (its SA-equivalent is its own RWEA, Art. 147A) and an
             F-IRB row at 10,000 own / 100,000 SA-equivalent; x = 72.5%.
    Act:     apply the floor.
    Assert:  U = 60,000, S = 150,000, threshold 108,750, so the F-IRB row carries
             the 48,750 shortfall and TREA is 108,750. Before the fix the equity
             book sat outside the max: 72,500 + 50,000 = 122,500.
    """
    # Arrange
    combined = _combined(("EQ1", "equity", 50_000.0, 50_000.0), ("IRB1", "FIRB", 10_000.0, 1e5))

    # Act
    floored, _impact, summary = apply_floor_with_impact(combined, combined, 0.725)

    # Assert
    rows = {row["exposure_reference"]: row for row in floored.collect().to_dicts()}
    assert summary.u_trea == pytest.approx(60_000.0, rel=1e-9)
    assert summary.s_trea == pytest.approx(150_000.0, rel=1e-9)
    assert summary.total_rwa_post_floor == pytest.approx(108_750.0, rel=1e-9)
    assert rows["EQ1"]["rwa_final"] == pytest.approx(50_000.0, rel=1e-9)
    assert rows["IRB1"]["rwa_final"] == pytest.approx(58_750.0, rel=1e-9)
    assert summary.equity_rwa_total == pytest.approx(50_000.0, rel=1e-9)


def test_cva_requirement_is_inside_both_legs() -> None:
    """
    The CVA RWEA (para 3(d) x 12.5) is added to U-TREA and S-TREA alike.

    Arrange: an F-IRB row at 30,000 own / 100,000 SA-equivalent and a CVA RWEA of
             50,000; x = 72.5%.
    Act:     apply the floor with the CVA RWEA.
    Assert:  U = 80,000, S = 150,000, threshold 108,750, shortfall 28,750 on the
             F-IRB row. The credit-risk ledger (``total_rwa_post_floor``) is
             58,750 and, with the CVA RWEA beside it, equals max(U, threshold).

    Without the CVA in the max the shortfall would be 42,500 (72,500 - 30,000) and
    the entity total 72,500 + 50,000 = 122,500: a (1 - x) . CVA overstatement.
    """
    # Arrange
    combined = _combined(("IRB1", "FIRB", 30_000.0, 100_000.0))

    # Act
    floored, _impact, summary = apply_floor_with_impact(combined, combined, 0.725, cva_rwa=50_000.0)

    # Assert
    rows = floored.collect()
    assert summary.u_trea == pytest.approx(80_000.0, rel=1e-9)
    assert summary.s_trea == pytest.approx(150_000.0, rel=1e-9)
    assert summary.shortfall == pytest.approx(28_750.0, rel=1e-9)
    assert summary.cva_rwa == pytest.approx(50_000.0, rel=1e-9)
    assert rows["rwa_final"][0] == pytest.approx(58_750.0, rel=1e-9)
    assert summary.total_rwa_post_floor == pytest.approx(58_750.0, rel=1e-9)
    assert summary.total_rwa_post_floor + summary.cva_rwa == pytest.approx(
        max(summary.u_trea, summary.floor_threshold), rel=1e-9
    )


def test_aggregate_threads_the_cva_requirement_into_the_floor() -> None:
    """
    ``OutputAggregator.aggregate(cva_rwa=...)`` reaches the floor.

    Arrange: the both-binding x = 72.5% book plus a CVA RWEA of 40,000.
    Act:     aggregate.
    Assert:  U = 170,000, S = 240,000, threshold 174,000 -> shortfall 4,000, so
             the ledger is 134,000 and the summary records the CVA RWEA.
    """
    # Arrange
    config = CalculationConfig.basel_3_1(reporting_date=DATE_X_725)

    # Act
    result = OutputAggregator().aggregate(
        _sa_frame(100_000.0),
        _irb_frame(30_000.0, 100_000.0),
        EMPTY_SLOTTING,
        None,
        config,
        cva_rwa=40_000.0,
    )

    # Assert
    summary = result.output_floor_summary
    assert summary is not None
    assert summary.cva_rwa == pytest.approx(40_000.0, rel=1e-9)
    assert summary.shortfall == pytest.approx(4_000.0, rel=1e-9)
    assert result.results.collect()["rwa_final"].sum() == pytest.approx(134_000.0, rel=1e-9)


def test_total_rwa_post_floor_foots_to_the_ledger_whatever_the_label() -> None:
    """
    Every row's own RWEA is in U-TREA, so the post-floor total is the ledger sum.

    Arrange: an F-IRB row (30,000 / 100,000) and a row carrying a label outside
             every approach set (the legacy ``"SA"`` spelling, 100,000).
    Act:     apply the floor at x = 72.5%.
    Assert:  the unrecognised row is standardised by construction (it is not
             modelled) and sits in both legs, exactly as OF 02.01 column 0020
             takes the COMPLEMENT of the modelled set: TREA = 145,000 and the
             ledger sums to it. Before the fix the row was in NEITHER leg and in
             NO component of ``total_rwa_post_floor``, which read 72,500.
    """
    # Arrange
    combined = _combined(("IRB1", "FIRB", 30_000.0, 100_000.0), ("X1", "SA", 1e5, 1e5))

    # Act
    floored, _impact, summary = apply_floor_with_impact(combined, combined, 0.725)

    # Assert
    ledger = floored.collect()["rwa_final"].sum()
    assert summary.total_rwa_post_floor == pytest.approx(145_000.0, rel=1e-9)
    assert ledger == pytest.approx(summary.total_rwa_post_floor, rel=1e-9)
    assert summary.total_rwa_post_floor == pytest.approx(
        summary.floored_modelled_rwa + summary.sa_rwa_total + summary.equity_rwa_total,
        rel=1e-9,
    )
