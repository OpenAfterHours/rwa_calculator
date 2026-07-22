"""Unit tests for the UKB OV1 row set — output-floor rows and the CCR block.

R16 rectification (this file): the pre-floor RWEA row ``4a`` and the six
pre-floor capital-ratio rows ``5a/5b/6a/6b/7a/7b`` that P1.162 grafted onto
``B31_OV1_ROWS`` were REMOVED — they do NOT belong to UKB OV1. The authoritative
PS1/26 Annex II ("Template UKB OV1 — Overview of risk-weighted exposure amounts.
Fixed format", pp. 1-9) runs rows 1..29 whose only output-floor lines are:

    26     Output floor multiplier   (Art. 92(5))
    27     Output floor adjustment   (Art. 92)

Rows 25 and 28 are "Empty set in the UK". The pre-floor RWEA line and the
pre-floor capital-ratio lines are UKB **KM1** rows (KM1 4a "Total risk-weighted
exposure amounts (RWEA) (pre-floor)"; KM1 5b/6b/7b the pre-floor CET1/Tier1/Total
ratios — KM1 5a/6a/7a are the "Fully loaded ECL accounting model" ratios, not
pre-floor). This calculator does not produce KM1, so pre-floor RWEA/ratios are a
documented gap, not OV1 rows.

The CCR block that BOTH regimes' OV1 must carry (rows 6 / 7 / 8 / UK 8a / 9,
rewritten 2026-07-14, docs/plans/c07-ccr-derivatives.md §4 D1) is unchanged and
still pinned here.

References:
    PRA PS1/26 Annex II — "Template UKB OV1" (rows 1-29) and "Template UKB KM1"
      (rows 4a / 5b / 6b / 7b — where the pre-floor RWEA and ratios live)
    CRR Art. 274-280f (Section 3), Art. 283 (Section 6), Art. 300-311 (Section 9)
    docs/plans/c07-ccr-derivatives.md §4 D1

Why: Regulatory disclosure templates are fixed-format. Any row count or
ordering deviation causes incorrect Pillar III submissions.
"""

from __future__ import annotations

import polars as pl

from rwa_calc.reporting.pillar3.templates import (
    B31_OV1_ROWS,
    CRR_OV1_ROWS,
)
from tests.fixtures.recon_ledger import LedgerShimPillar3Generator

# ---------------------------------------------------------------------------
# Expected constants
# ---------------------------------------------------------------------------

# The CCR block, in regulatory order. It is a CONTIGUOUS block sitting after the
# last "of which" row of row 1 (row 5, A-IRB) and before the equity memo rows
# (11-14), the threshold memo (24) and the output-floor rows (26/27) — its fixed
# position in the UKB OV1 template.
_CCR_BLOCK_REFS: list[str] = ["6", "7", "8", "UK8a", "9"]

# The pre-CCR row sequences — every one of these refs must survive, in order.
# Note the ABSENCE of 4a and 5a-7b: those are KM1 rows, removed from OV1 (R16).
_B31_BASE_REFS: list[str] = [
    "1",
    "2",
    "3",
    "4",
    "5",
    "11",
    "12",
    "13",
    "14",
    "24",
    "26",
    "27",
    "29",
]

_CRR_BASE_REFS: list[str] = ["1", "2", "3", "4", "UK4a", "5", "24", "29"]

_EXPECTED_B31_COUNT = len(_B31_BASE_REFS) + len(_CCR_BLOCK_REFS)  # 18
_EXPECTED_CRR_COUNT = len(_CRR_BASE_REFS) + len(_CCR_BLOCK_REFS)  # 13

# The KM1 rows that MUST NOT appear in OV1 — the P1.162 graft that R16 removed.
_KM1_ONLY_REFS: list[str] = ["4a", "5a", "5b", "6a", "6b", "7a", "7b"]


def _assert_ccr_block(refs: list[str], base: list[str], label: str) -> None:
    """The CCR block is present, contiguous, ordered, and correctly placed."""
    assert [r for r in refs if r not in _CCR_BLOCK_REFS] == base, (
        f"{label}: the pre-existing OV1 rows must keep their exact order — the CCR "
        f"block is an insertion, not a reshuffle. Got {refs}."
    )
    positions = [refs.index(ref) for ref in _CCR_BLOCK_REFS if ref in refs]
    assert len(positions) == len(_CCR_BLOCK_REFS), (
        f"{label}: the CCR block {_CCR_BLOCK_REFS} is missing from OV1 (got {refs}). "
        "Row 1 is 'Credit risk (excluding CCR)' — the CCR RWEAs it excludes must be "
        "'disclosed in rows 6 and 16 of this template'."
    )
    assert positions == sorted(positions), (
        f"{label}: the CCR block must appear in regulatory order "
        f"{_CCR_BLOCK_REFS}, got {[refs[p] for p in sorted(positions)]}."
    )
    assert positions == list(range(positions[0], positions[0] + len(positions))), (
        f"{label}: the CCR block must be CONTIGUOUS (rows 7 / 8 / UK8a / 9 are the "
        f"'of which' rows of row 6), got positions {positions} in {refs}."
    )
    assert refs.index("5") < positions[0], (
        f"{label}: the CCR block must follow row 5 (the last 'of which' of row 1)."
    )
    assert positions[-1] < refs.index("24"), (
        f"{label}: the CCR block must precede the memo row 24 and the Total row 29."
    )


# ---------------------------------------------------------------------------
# Template definition tests — the corrected UKB OV1 row set
# ---------------------------------------------------------------------------


class TestB31Ov1RowSet:
    """B31_OV1_ROWS = the corrected UKB OV1 layout (no KM1 pre-floor grafts)."""

    def test_b31_ov1_rows_count_is_18(self) -> None:
        # Arrange / Act — no computation; the template is a module constant
        # Assert
        assert len(B31_OV1_ROWS) == _EXPECTED_B31_COUNT, (
            f"B31 OV1 must carry {_EXPECTED_B31_COUNT} rows: {_B31_BASE_REFS} plus the "
            f"CCR block {_CCR_BLOCK_REFS}. Got {[r.ref for r in B31_OV1_ROWS]}."
        )

    def test_b31_ov1_row_refs_in_expected_order(self) -> None:
        # Arrange
        actual_refs = [r.ref for r in B31_OV1_ROWS]
        # Assert
        _assert_ccr_block(actual_refs, _B31_BASE_REFS, "B31_OV1_ROWS")

    def test_b31_ov1_excludes_km1_pre_floor_rows(self) -> None:
        """Rows 4a / 5a-7b are UKB KM1 rows and must NOT appear in OV1.

        UKB OV1 (PS1/26 Annex II) has no pre-floor RWEA row and no pre-floor
        capital-ratio rows — those are KM1 4a / 5b / 6b / 7b. The earlier P1.162
        graft mis-stated the fixed template; R16 removed it.
        """
        # Arrange
        actual_refs = {r.ref for r in B31_OV1_ROWS}
        # Assert
        leaked = [ref for ref in _KM1_ONLY_REFS if ref in actual_refs]
        assert not leaked, (
            f"B31_OV1_ROWS still carries KM1-only refs {leaked}. UKB OV1 has NO "
            "pre-floor RWEA row (4a) and NO pre-floor capital-ratio rows (5a-7b); "
            "those belong to UKB KM1 (rows 4a / 5b / 6b / 7b), a template this "
            "calculator does not produce."
        )


class TestCrrOv1CcrBlock:
    """CRR_OV1_ROWS is unchanged: 8 original rows + the shared CCR block = 13."""

    def test_crr_ov1_rows_count_is_13(self) -> None:
        # Assert
        assert len(CRR_OV1_ROWS) == _EXPECTED_CRR_COUNT, (
            f"CRR OV1 must carry {_EXPECTED_CRR_COUNT} rows: the 8 original rows plus "
            f"the CCR block {_CCR_BLOCK_REFS}. Got {[r.ref for r in CRR_OV1_ROWS]}."
        )

    def test_crr_ov1_row_refs_in_expected_order(self) -> None:
        # Arrange
        actual_refs = [r.ref for r in CRR_OV1_ROWS]
        # Assert
        _assert_ccr_block(actual_refs, _CRR_BASE_REFS, "CRR_OV1_ROWS")


# ---------------------------------------------------------------------------
# Generated-frame regression — the removed rows must not reappear at runtime
# ---------------------------------------------------------------------------


def _make_lf() -> pl.LazyFrame:
    """Two-row LazyFrame: one IRB row and one slotting row."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["IRB1", "SL1"],
            "approach_applied": ["foundation_irb", "slotting"],
            "exposure_class": ["corporate", "specialised_lending"],
            "ead_final": [1000.0, 500.0],
            "rwa_pre_floor": [800.0, 200.0],
            "rwa_final": [870.0, 218.0],
        }
    )


class TestB31Ov1GeneratedRowSet:
    """The generated B31 OV1 frame carries exactly the corrected row set."""

    def test_generated_b31_ov1_has_no_km1_rows(self) -> None:
        # Arrange
        gen = LedgerShimPillar3Generator()

        # Act
        bundle = gen.generate_from_lazyframe(_make_lf(), framework="BASEL_3_1")

        # Assert
        assert bundle.ov1 is not None, "OV1 must be generated for B31 framework"
        refs = set(bundle.ov1["row_ref"].to_list())
        leaked = [ref for ref in _KM1_ONLY_REFS if ref in refs]
        assert not leaked, (
            f"generated B31 OV1 still emits KM1-only rows {leaked}; they were removed "
            "from the template (R16)."
        )
        assert bundle.ov1.height == _EXPECTED_B31_COUNT, (
            f"generated B31 OV1 must have {_EXPECTED_B31_COUNT} rows, got {bundle.ov1.height}"
        )
