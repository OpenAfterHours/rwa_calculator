"""
Contract tests: the equity method discriminator (``equity_method``) is a
declared optional String column on the sealed aggregator-exit edge, and — like
the other equity provenance columns — is produced by the equity calculator, so
it must NOT appear on the calculator branch edges (SA / IRB / slotting).

``equity_method`` records which CRR equity method the calculator applied
(``sa`` = Art. 133, ``irb_simple`` = Art. 155(2), ``pd_lgd`` = Art. 155(3)) so
Pillar 3 CR10.5 can disclose the Art. 155(2) simple-RW population without
re-deriving the approach — the sealed ``reporting_method`` collapses every
equity leg to ``EQUITY``.

References:
- CRR Art. 155(2) (IRB simple risk-weight equity); Art. 438(e) (CR10.5)
- src/rwa_calc/engine/equity/calculator.py (the producer)
"""

from __future__ import annotations

import polars as pl

from rwa_calc.contracts.edges import AGGREGATOR_EXIT_EDGE, CALC_BRANCH_EDGES
from rwa_calc.domain.enums import EquityApproach


def test_aggregator_exit_declares_equity_method() -> None:
    """``equity_method`` is a conditional String column on the aggregator exit.

    ``inject=False`` (like the other equity-run-only columns) keeps an
    equity-free run from injecting it, so the eager-backed seal stays shallow.
    """
    assert "equity_method" in AGGREGATOR_EXIT_EDGE.columns
    col = AGGREGATOR_EXIT_EDGE.columns["equity_method"]
    assert col.dtype == pl.String
    assert col.required is False
    assert col.inject is False


def test_equity_method_absent_from_branch_edges() -> None:
    """The discriminator is equity-calculator-produced — not a branch column."""
    for branch in ("sa_branch", "irb_branch", "slotting_branch"):
        assert "equity_method" not in CALC_BRANCH_EDGES[branch].columns


def test_equity_method_values_track_the_equity_approach_enum() -> None:
    """The tags the calculator writes are exactly the EquityApproach values."""
    assert EquityApproach.SA.value == "sa"
    assert EquityApproach.IRB_SIMPLE.value == "irb_simple"
    assert EquityApproach.PD_LGD.value == "pd_lgd"
