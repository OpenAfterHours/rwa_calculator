"""R16 Part (a): OV1 row 24 is the Art. 48(4) threshold-item 250%-RW memo.

UKB / UK OV1 row 24 ("Amounts below the thresholds for deduction (subject to
250% risk weight)") is NOT "any leg risk-weighted at 250%". PS1/26 Annex II
("Template UKB OV1", row 24, pp. 4-5) defines it as the items subject to a 250%
risk weight under **Art. 48(4) CRR** — deferred-tax assets from temporary
differences and significant investments in a financial-sector entity's CET1,
each below the 10%-of-CET1 deduction threshold of Art. 48(1).

The earlier predicate matched ``reporting_rw`` in [2.495, 2.505] over the WHOLE
ledger, so under Basel 3.1 the Art. 133 equity holdings that weight exactly 250%
were wrongly swept into row 24 (the rich B31 book mis-stated 2.5M there).

The sealed ledger carries no positive Art. 48(4) flag, so row 24 is a RECORDED
APPROXIMATION (see ``reporting/pillar3/ov1.py`` module docstring): sum
``rwa_final`` over legs whose ORIGIN class is the SA "Other items" bucket
(``reporting_class_origin == "other"`` — CR4/CR5 row 16, "items below deduction
thresholds") AND ``reporting_rw`` in the 250% band. This file pins:

    - equity at exactly 250% is EXCLUDED (equity is definitionally not an
      Art. 48(4) item);
    - an "other items" leg at 250% (the genuine threshold-item shape) IS
      included;
    - the residual: within the "other" class we cannot distinguish a genuine
      Art. 48(4) item from a hypothetical non-threshold 250% "other item".

The narrowing is regime-clean (identical predicate under CRR and Basel 3.1 —
row 24 exists in both).

References:
    CRR Art. 48(4), Art. 48(1); PS1/26 Annex II "Template UKB OV1" row 24
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimPillar3Generator

_FRAMEWORKS: tuple[str, ...] = ("CRR", "BASEL_3_1")

# The equity leg's RWEA (1,000,000 EAD x 250% SA RW) — the false positive the
# old predicate swept into row 24. The "other items" leg's RWEA is distinct so
# the assertions can tell them apart.
_EQUITY_RWA = 2_500_000.0
_OTHER_RWA = 1_000_000.0


def _row24(df: pl.DataFrame) -> float | None:
    """Column ``a`` of OV1 row 24."""
    row = df.filter(pl.col("row_ref") == "24")
    assert row.height == 1, f"expected exactly one OV1 row 24, got {row.height}"
    return row["a"][0]


def _lf(*, equity: bool, other: bool) -> pl.LazyFrame:
    """A synthetic ledger with an optional equity@250% and/or other@250% leg.

    Always carries a plain 100%-RW corporate loan so the book is non-empty and
    row 29 (Total) has something to sum.
    """
    refs = ["CORP1"]
    classes = ["corporate"]
    approaches = ["standardised"]
    rws = [1.0]
    eads = [1_000_000.0]
    rwas = [1_000_000.0]
    if equity:
        refs.append("EQ1")
        classes.append("equity")
        approaches.append("equity")
        rws.append(2.5)
        eads.append(1_000_000.0)
        rwas.append(_EQUITY_RWA)
    if other:
        refs.append("OTH1")
        classes.append("other")
        approaches.append("standardised")
        rws.append(2.5)
        eads.append(400_000.0)
        rwas.append(_OTHER_RWA)
    return pl.LazyFrame(
        {
            "exposure_reference": refs,
            "exposure_class": classes,
            "approach_applied": approaches,
            "risk_weight": rws,
            "ead_final": eads,
            "rwa_final": rwas,
        }
    )


@pytest.mark.parametrize("framework", _FRAMEWORKS)
def test_equity_at_250pct_is_excluded_from_row_24(framework: str) -> None:
    """An equity holding at exactly 250% RW must NOT enter row 24.

    Equity exposures are definitionally not Art. 48(4) threshold-deduction
    items. With only an equity@250% leg (plus a 100% loan), row 24 stays null.
    """
    # Arrange
    gen = LedgerShimPillar3Generator()
    # Act
    bundle = gen.generate_from_lazyframe(_lf(equity=True, other=False), framework=framework)
    # Assert
    assert bundle.ov1 is not None
    assert _row24(bundle.ov1) is None, (
        f"[{framework}] OV1 row 24 reports the equity RWEA, but Art. 48(4) row 24 is "
        "threshold-deduction items only — an Art. 133 equity holding at 250% is not one."
    )


@pytest.mark.parametrize("framework", _FRAMEWORKS)
def test_other_items_leg_at_250pct_populates_row_24(framework: str) -> None:
    """A 250%-RW leg in the SA "Other items" class IS the row-24 population.

    This is the genuine threshold-item shape (Art. 48(4) items are filed under
    "Other items", CR4/CR5 row 16). It is the best available positive proxy —
    the recorded residual is that we cannot distinguish it from a hypothetical
    non-threshold 250% "other item".
    """
    # Arrange
    gen = LedgerShimPillar3Generator()
    # Act
    bundle = gen.generate_from_lazyframe(_lf(equity=False, other=True), framework=framework)
    # Assert
    assert bundle.ov1 is not None
    assert _row24(bundle.ov1) == pytest.approx(_OTHER_RWA), (
        f"[{framework}] OV1 row 24 must sum the 250%-RW 'Other items' leg "
        f"({_OTHER_RWA}), got {_row24(bundle.ov1)}."
    )


@pytest.mark.parametrize("framework", _FRAMEWORKS)
def test_row_24_counts_only_the_other_leg_when_both_present(framework: str) -> None:
    """With both an equity@250% and an other@250% leg, row 24 = the other leg only.

    Pins that the narrowing subtracts exactly the equity misstatement: row 24 is
    the "other items" RWEA, never the equity RWEA folded in.
    """
    # Arrange
    gen = LedgerShimPillar3Generator()
    # Act
    bundle = gen.generate_from_lazyframe(_lf(equity=True, other=True), framework=framework)
    # Assert
    assert bundle.ov1 is not None
    assert _row24(bundle.ov1) == pytest.approx(_OTHER_RWA), (
        f"[{framework}] OV1 row 24 must count the 'Other items' leg ({_OTHER_RWA}) and "
        f"exclude the equity leg ({_EQUITY_RWA}); got {_row24(bundle.ov1)}."
    )
