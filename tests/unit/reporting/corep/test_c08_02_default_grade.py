"""
C / OF 08.02 firm-grade path: defaulted legs report on a default row, last.

Pipeline position:
    sealed-shape IRB results (``cp_internal_rating_grade`` set)
        -> COREPGenerator (ledger shim) -> COREPTemplateBundle.c08_02

When the firm supplies internal grades, C 08.02 keys its rows on them. A
defaulted obligor that still carries a performing grade label - its last grade
before default - pooled into that grade's row, so the row's PD (col 0010) and
exposure value mixed a 100% obligor into a performing grade. Annex II forbids
both halves:

- CRR Annex II C 08.02 rows / PS1/26 Annex II OF 08.02 rows: "PD of obligors in
  default shall be 100%."
- C / OF 08.02 col 0005: "The last reported grade or grades (or pool) shall be
  that of exposures in default."

The frame is the sealed ledger's shape after P1.381 (a defaulted IRB leg carries
``pd_floored`` 1.0, Art. 160(3) / 163(2)). The grade column is supplied on the
frame, as ``tests/fixtures/p4_20`` does, because no pipeline input populates
``cp_internal_rating_grade`` today; the band path, which every registered
portfolio takes, is asserted end to end in
``tests/acceptance/reporting/test_p1_381_defaulted_pd_100.py``.

References:
- CRR / PRA PS1/26 Art. 160(3), 163(2)
- CRR Annex II p.108 (C 08.02 rows, col 0005); PS1/26 Annex II pp.118-119
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.templates import PD_BANDS
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator

# =============================================================================
# Constants
# =============================================================================

GRADE_STRONG: str = "G03"
GRADE_WEAK: str = "G06"
PD_STRONG: float = 0.0012
PD_WEAK: float = 0.006

EAD_STRONG: float = 2_000.0
EAD_WEAK: float = 1_000.0
EAD_DEFAULTED: float = 500.0

#: The default row's label: the 100% band of the PD scale the band path uses.
DEFAULT_ROW: str = PD_BANDS[-1][2]


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
def test_defaulted_leg_leaves_its_performing_grade_for_a_default_row_reported_last(
    framework: str,
) -> None:
    """The defaulted leg carries the WEAK grade's label; it must not pool there.

    The weak grade keeps its one performing leg (the live-cell control), and the
    default row comes after every performing grade at PD 100%.
    """
    # Arrange
    frame = _graded_frame()
    defaulted = frame.filter(pl.col("is_defaulted")).collect()
    assert defaulted["cp_internal_rating_grade"].to_list() == [GRADE_WEAK], (
        "the defaulted leg must share a performing leg's grade, or nothing can pool"
    )

    # Act
    sheet = _corporate_sheet(frame, framework)

    # Assert
    assert sheet["row_ref"].to_list() == [GRADE_STRONG, GRADE_WEAK, DEFAULT_ROW]
    weak = _row(sheet, GRADE_WEAK)
    assert (weak["0010"], weak["0110"]) == pytest.approx((PD_WEAK, EAD_WEAK))
    default = _row(sheet, DEFAULT_ROW)
    assert (default["0010"], default["0110"]) == pytest.approx((1.0, EAD_DEFAULTED))


@pytest.mark.parametrize("framework", ["CRR", "BASEL_3_1"])
def test_grade_path_without_a_defaulted_leg_emits_no_default_row(framework: str) -> None:
    """No defaulted leg, no default row: the grade set is the firm's alone."""
    # Arrange
    frame = _graded_frame().filter(pl.col("is_defaulted").not_())

    # Act
    sheet = _corporate_sheet(frame, framework)

    # Assert
    assert sheet["row_ref"].to_list() == [GRADE_STRONG, GRADE_WEAK]


# =============================================================================
# Helpers
# =============================================================================


def _graded_frame() -> pl.LazyFrame:
    """Three F-IRB corporate legs on two firm grades; the third is in default."""
    rows = [
        _leg("GR-STRONG", "CP-STRONG", GRADE_STRONG, PD_STRONG, EAD_STRONG, defaulted=False),
        _leg("GR-WEAK", "CP-WEAK", GRADE_WEAK, PD_WEAK, EAD_WEAK, defaulted=False),
        # Post-P1.381 sealed shape: a defaulted leg's pd_floored is 1.0.
        _leg("GR-DEF", "CP-DEF", GRADE_WEAK, 1.0, EAD_DEFAULTED, defaulted=True),
    ]
    return pl.DataFrame(rows).lazy()


def _leg(
    reference: str,
    counterparty: str,
    grade: str,
    pd_floored: float,
    ead: float,
    *,
    defaulted: bool,
) -> dict[str, object]:
    return {
        "exposure_reference": reference,
        "approach_applied": "foundation_irb",
        "exposure_class": "corporate",
        "counterparty_reference": counterparty,
        "drawn_amount": ead,
        "undrawn_amount": 0.0,
        "ead_final": ead,
        "rwa_final": 0.0 if defaulted else ead * 0.7,
        "pd_floored": pd_floored,
        "lgd_floored": 0.45,
        "irb_maturity_m": 2.5,
        "expected_loss": pd_floored * 0.45 * ead,
        "is_defaulted": defaulted,
        "cp_internal_rating_grade": grade,
    }


def _corporate_sheet(frame: pl.LazyFrame, framework: str) -> pl.DataFrame:
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(frame, framework=framework)
    sheets = bundle.c08_02
    key = "corporate" if framework == "CRR" else _only_corporate_key(sheets)
    return sheets[key]


def _only_corporate_key(sheets: dict[str, pl.DataFrame]) -> str:
    keys = [key for key in sheets if key.startswith("corporate")]
    assert len(keys) == 1, f"corporate C 08.02 sheets: {list(sheets)}"
    return keys[0]


def _row(sheet: pl.DataFrame, ref: str) -> dict:
    rows = sheet.filter(pl.col("row_ref") == ref)
    assert rows.height == 1, f"row {ref} not emitted; rows are {sheet['row_ref'].to_list()}"
    return rows.row(0, named=True)
