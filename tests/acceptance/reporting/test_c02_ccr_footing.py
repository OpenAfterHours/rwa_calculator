"""
COREP C 02.00 — the SA breakdown must include SA-CCR derivatives, and must foot.

Pipeline position:
    reporting_ccr_portfolio -> PipelineOrchestrator -> COREPGenerator
        -> C 02.00 / OF 02.00 (the master own-funds roll-up)

Key responsibilities (the oracle for docs/plans/c07-ccr-derivatives.md step 5):
- C 02.00's parent credit row is "RISK WEIGHTED EXPOSURE AMOUNTS FOR CREDIT,
  **COUNTERPARTY CREDIT** AND DILUTION RISKS AND FREE DELIVERIES" (Art. 92(3)(a),(f)).
  Rows 0010/0050 are a flat sum over the whole ledger, so they already carry the
  SA-CCR derivative RWEA.
- Its child row 0060 "Of which: Standardised Approach (SA)" is defined by Annex II
  as "**CR SA and SEC SA templates at the level of total exposures**" — the SA row
  IS the C 07.00 total. C 07.00 now reports SA-CCR derivatives (steps 3-4), so the
  SA row must carry them too.
- The SA exposure-class rows are "CR SA template at the level of total exposures",
  so the derivative RWEA belongs on row 0120 (Institutions) — its counterparty's
  Art. 112 class.

The defect this pins: row 0060 reads ``approach_rwa["standardised"]``, but under
Basel 3.1 the CCR legs carry ``approach_applied == "standardised_ccr"`` (the
output-floor relabel, which is load-bearing and must NOT be reverted). So under
Basel 3.1 the SA row excludes the derivatives and **C 02.00 does not foot**:
rows 0010/0050 total 4,060,296.72 while row 0060 reports only the 2,500,000 loan.

Under CRR the legs already carry ``"standardised"``, so C 02.00 foots today. The
CRR parametrisations below are therefore the "no cell moves" guard: if a CRR cell
moves when Basel 3.1 is fixed, the fix is wrong.

References:
- COREP Annex II, C 02.00 rows 0010 / 0050 / 0060 / 0120 / 0130
- CRR Art. 92(3)(a),(f) (own funds requirements for credit AND counterparty
  credit risk); Art. 120(1) (institution 50% RW); Art. 306(1)(a) (QCCP 2% RW)
- PS1/26 ECRA CQS 2 (institution 30% RW)
- docs/plans/c07-ccr-derivatives.md (step 5)
- tests/acceptance/reporting/test_c07_ccr_derivative_rows.py (the C 07.00 oracle
  and the C 07.00 <-> C 02.00 tie-out)
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl
import pytest
from tests.acceptance.reporting.test_reporting_ccr_golden import _REGIMES, _generate_frames

_REL = 1e-9

_C02_FRAME = "corep__c_02_00"

# The one column that carries RWEA in both regimes. (Basel 3.1 adds cols 0020
# SA-equivalent / 0030 output-floor; they mirror col 0010 on the SA rows and are
# not what this file measures.)
_RWEA = "0010"


@dataclass(frozen=True)
class _Expected:
    """Hand-derived C 02.00 expectations for one regime.

    ``derivative_rwea`` is the SA-CCR RWEA of BOTH netting sets (bilateral at the
    institution RW, cleared at the 2% QCCP RW); ``loan_rwea`` is the plain
    corporate term loan. The portfolio holds nothing else, so the total is their
    sum — and so is the SA row, because every exposure in it is standardised.
    """

    derivative_rwea: float  # -> row 0120 (Institutions)
    loan_rwea: float  # -> row 0130 (Corporates)

    @property
    def total_rwea(self) -> float:
        """Rows 0010 / 0050 / 0060 — all three, once C 02.00 foots."""
        return self.derivative_rwea + self.loan_rwea


_EXPECTED: dict[str, _Expected] = {
    # CRR: institution RW 50% (Art. 120(1), CQS 2) + QCCP 2% (Art. 306(1)(a)).
    "crr": _Expected(derivative_rwea=2_858_279.372710047, loan_rwea=2_500_000.0),
    # Basel 3.1: institution RW 30% (PS1/26 ECRA, CQS 2) + QCCP 2%.
    "b31": _Expected(derivative_rwea=1_560_296.719974031, loan_rwea=2_500_000.0),
}


@pytest.fixture(scope="module")
def c02_sheets() -> dict[str, pl.DataFrame]:
    """The C 02.00 frame for each regime (one pipeline run each)."""
    return {regime_key: _generate_frames(regime_key)[0][_C02_FRAME] for regime_key in _REGIMES}


# =============================================================================
# The movers — row 0060 (SA) and row 0120 (Institutions)
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c02_sa_row_0060_includes_the_sa_ccr_derivatives(
    regime_key: str, c02_sheets: dict[str, pl.DataFrame]
) -> None:
    """Row 0060 ("Of which: SA") covers the whole SA book — derivatives included.

    Annex II defines the row as the CR SA (+ SEC SA) template "at the level of
    total exposures". C 07.00 reports the SA-CCR derivative netting sets, so the
    SA row must report their RWEA too. Under Basel 3.1 it does not: the
    ``standardised_ccr`` output-floor relabel hides them from the approach
    group-by.

    Arrange: the CCR portfolio (one 5m corporate loan, two derivative netting sets).
    Act:     run the pipeline -> COREP C 02.00.
    Assert:  row 0060 == loan RWEA + derivative RWEA.
    """
    # Arrange + Act
    expected = _EXPECTED[regime_key]
    row = _row(c02_sheets[regime_key], "0060")

    # Assert
    assert row[_RWEA] == pytest.approx(expected.total_rwea, rel=_REL), (
        f"[{regime_key}] C 02.00 row 0060 ('Of which: Standardised Approach') must "
        f"carry the SA-CCR derivative RWEA ({expected.derivative_rwea:,.6f}) on top "
        f"of the loan ({expected.loan_rwea:,.2f}) — Annex II defines the row as the "
        f"CR SA template at the level of total exposures. Expected "
        f"{expected.total_rwea:,.6f}, got {row[_RWEA]}."
    )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c02_institutions_row_0120_carries_the_derivative_rwea(
    regime_key: str, c02_sheets: dict[str, pl.DataFrame]
) -> None:
    """Row 0120 (Institutions) carries the derivatives — their counterparty's class.

    The SA exposure-class rows are the "CR SA template at the level of total
    exposures", so a derivative reports under the Art. 112 class of the
    counterparty it faces. Both netting sets face institutions (one of them a
    QCCP), so all of the derivative RWEA lands on row 0120.

    Arrange: the CCR portfolio.
    Act:     run the pipeline -> COREP C 02.00.
    Assert:  row 0120 == the SA-CCR RWEA of both netting sets.
    """
    # Arrange + Act
    expected = _EXPECTED[regime_key]
    row = _row(c02_sheets[regime_key], "0120")

    # Assert
    assert row[_RWEA] == pytest.approx(expected.derivative_rwea, rel=_REL), (
        f"[{regime_key}] C 02.00 row 0120 (Institutions) must carry the SA-CCR "
        f"derivative RWEA — expected {expected.derivative_rwea:,.6f}, got {row[_RWEA]}."
    )


# =============================================================================
# The footing — the defect stated as arithmetic
# =============================================================================


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c02_credit_risk_breakdown_foots_to_the_total(
    regime_key: str, c02_sheets: dict[str, pl.DataFrame]
) -> None:
    """Rows 0010 == 0050 == 0060: the whole book is credit risk, all of it SA.

    This portfolio has no IRB, no equity, no market or operational risk — so the
    total risk exposure amount, the credit-risk row and the SA row are the same
    number. If row 0060 excludes the derivatives while 0010/0050 (flat sums over
    the ledger) include them, C 02.00 does not foot.

    Arrange: the CCR portfolio (SA-only, credit risk only).
    Act:     run the pipeline -> COREP C 02.00.
    Assert:  rows 0010, 0050 and 0060 are all the portfolio total RWEA.
    """
    # Arrange + Act
    expected = _EXPECTED[regime_key]
    sheet = c02_sheets[regime_key]
    total, credit, sa = (_row(sheet, ref)[_RWEA] for ref in ("0010", "0050", "0060"))

    # Assert
    assert total == pytest.approx(expected.total_rwea, rel=_REL), (
        f"[{regime_key}] C 02.00 row 0010 (total risk exposure amount) must be "
        f"{expected.total_rwea:,.6f}, got {total}."
    )
    assert credit == pytest.approx(total, rel=_REL), (
        f"[{regime_key}] C 02.00 row 0050 (credit, counterparty credit and dilution "
        f"risks) must equal the total — this portfolio has no other risk type "
        f"(row 0010 {total}, row 0050 {credit})."
    )
    assert sa == pytest.approx(total, rel=_REL), (
        f"[{regime_key}] C 02.00 DOES NOT FOOT: row 0060 (SA) reports {sa} but the "
        f"credit-risk row 0050 reports {credit}. Every exposure in this portfolio is "
        "standardised — the SA-CCR derivatives are missing from the SA row."
    )


@pytest.mark.parametrize("regime_key", list(_REGIMES))
def test_c02_sa_class_rows_sum_to_the_sa_total(
    regime_key: str, c02_sheets: dict[str, pl.DataFrame]
) -> None:
    """Rows 0120 (Institutions) + 0130 (Corporates) == row 0060 (the SA total).

    The per-class breakdown of the SA row must account for every SA exposure.
    The loan sits on 0130 and must not move; the derivatives belong on 0120.

    Arrange: the CCR portfolio.
    Act:     run the pipeline -> COREP C 02.00.
    Assert:  0130 == the loan RWEA, and 0120 + 0130 == row 0060.
    """
    # Arrange + Act
    expected = _EXPECTED[regime_key]
    sheet = c02_sheets[regime_key]
    institutions, corporates, sa = (
        _num(_row(sheet, ref), _RWEA) for ref in ("0120", "0130", "0060")
    )

    # Assert
    assert corporates == pytest.approx(expected.loan_rwea, rel=_REL), (
        f"[{regime_key}] C 02.00 row 0130 (Corporates) must be unchanged at "
        f"{expected.loan_rwea:,.2f} — the plain term loan (got {corporates})."
    )
    assert institutions + corporates == pytest.approx(sa, rel=_REL), (
        f"[{regime_key}] C 02.00's SA class rows must sum to the SA total: "
        f"0120 ({institutions}) + 0130 ({corporates}) != 0060 ({sa})."
    )


# =============================================================================
# Helpers
# =============================================================================


def _row(sheet: pl.DataFrame, ref: str) -> dict[str, float | str | None]:
    """The single C 02.00 row with the given ``row_ref``, as a dict of cells."""
    rows = sheet.filter(pl.col("row_ref") == ref)
    assert rows.height == 1, f"expected exactly one C 02.00 row {ref}, got {rows.height}"
    return rows.row(0, named=True)


def _num(row: dict[str, float | str | None], col: str) -> float:
    """The cell at ``col``, asserted numeric — a reported figure, not a label or a null."""
    value = row[col]
    assert isinstance(value, int | float), f"cell {col} must be numeric, got {value!r}"
    return float(value)
