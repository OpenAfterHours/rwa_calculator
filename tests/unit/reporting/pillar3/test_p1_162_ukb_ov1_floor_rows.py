"""Unit tests for P1.162: UKB OV1 pre-floor rows (Basel 3.1).

Tests cover the 7 new P3Row entries added to B31_OV1_ROWS:
    4a  — Total RWEAs (pre-floor)
    5a  — CET1 ratio (pre-floor)
    5b  — CET1 ratio (pre-floor, transitional)
    6a  — Tier 1 ratio (pre-floor)
    6b  — Tier 1 ratio (pre-floor, transitional)
    7a  — Total capital ratio (pre-floor)
    7b  — Total capital ratio (pre-floor, transitional)

...and the 5-row CCR block that BOTH regimes' OV1 must carry (rewritten
2026-07-14, docs/plans/c07-ccr-derivatives.md §4 D1): row 1 is labelled "Credit
risk (excluding CCR)" and the instructions are explicit that CCR RWEAs "are
excluded and disclosed in rows 6 and 16 of this template", so rows

    6      Counterparty credit risk – CCR              (the additive parent)
    7      CCR – Of which the standardised approach    (Section 3, SA-CCR)
    8      CCR – Of which internal model method (IMM)  (Section 6, null here)
    UK 8a  CCR – Of which exposures to a CCP           (Section 9)
    9      CCR – Of which other CCR                    (the explicit residual)

are part of the fixed format. The counts these tests pinned (B31 = 20, CRR = 8)
were pinning the ABSENCE of that block: B31 = 25 and CRR = 13 now.

The block's ``UK 8a`` row takes the ref string ``"UK8a"``, following the row
list's own existing convention for a UK-specific insert (``UK4a``, the equity
row) — a bare token, no space.

References:
    PRA PS1/26 Disclosure (CRR) Part, Art. 456
    UKB OV1 template — pre-floor supplementary rows + the CCR block
    CRR Art. 274-280f (Section 3), Art. 283 (Section 6), Art. 300-311 (Section 9)
    docs/plans/c07-ccr-derivatives.md §4 D1

Why: Regulatory disclosure templates are fixed-format. Any row count or
ordering deviation causes incorrect Pillar III submissions.
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.reporting.pillar3.templates import (
    B31_OV1_ROWS,
    CRR_OV1_ROWS,
)
from tests.fixtures.recon_ledger import LedgerShimPillar3Generator

# ---------------------------------------------------------------------------
# Expected constants
# ---------------------------------------------------------------------------

# The CCR block, in regulatory order. It is a CONTIGUOUS block sitting after the
# last "of which" row of row 1 (row 5, A-IRB) and before the memo rows (24) and
# the Total (29). Where it sits relative to the Basel 3.1 pre-floor/ratio grafts
# (4a, 5a-7b) is not pinned — those refs are our own supplementary rows, and the
# CCR block does not collide with them as strings.
_CCR_BLOCK_REFS: list[str] = ["6", "7", "8", "UK8a", "9"]

# The pre-CCR row sequences — every one of these refs must survive, in order.
_B31_BASE_REFS: list[str] = [
    "1",
    "2",
    "3",
    "4",
    "4a",
    "5",
    "5a",
    "5b",
    "6a",
    "6b",
    "7a",
    "7b",
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

_EXPECTED_B31_COUNT = len(_B31_BASE_REFS) + len(_CCR_BLOCK_REFS)  # 25
_EXPECTED_CRR_COUNT = len(_CRR_BASE_REFS) + len(_CCR_BLOCK_REFS)  # 13


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
# Helpers
# ---------------------------------------------------------------------------


def _make_pre_floor_lf() -> pl.LazyFrame:
    """Two-row LazyFrame: one IRB row (800/870) and one slotting row (200/218).

    rwa_pre_floor = modelled RWA before floor add-on (800 + 200 = 1000).
    rwa_final    = post-floor RWA (870 + 218 = 1088).
    """
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


# ---------------------------------------------------------------------------
# Template definition tests
# ---------------------------------------------------------------------------


class TestB31Ov1RowCount:
    """B31_OV1_ROWS = the 20 P1.162 rows + the 5-row CCR block = 25."""

    def test_b31_ov1_rows_count_is_25(self) -> None:
        # Arrange / Act — no computation needed; template is a module constant
        # Assert
        assert len(B31_OV1_ROWS) == _EXPECTED_B31_COUNT, (
            f"B31 OV1 must carry {_EXPECTED_B31_COUNT} rows: the 20 P1.162 rows plus "
            f"the CCR block {_CCR_BLOCK_REFS}. Got {[r.ref for r in B31_OV1_ROWS]}."
        )


class TestB31Ov1RowOrder:
    """B31_OV1_ROWS keeps its P1.162 sequence, with the CCR block inserted."""

    def test_b31_ov1_row_refs_in_expected_order(self) -> None:
        # Arrange
        actual_refs = [r.ref for r in B31_OV1_ROWS]
        # Assert
        _assert_ccr_block(actual_refs, _B31_BASE_REFS, "B31_OV1_ROWS")


class TestCrrOv1CcrBlock:
    """CRR_OV1_ROWS gets the CCR block too — the UKB OV1 carries the same one.

    P1.162's pre-floor rows are Basel 3.1 only, but the CCR block is not: row 1
    is labelled "Credit risk (excluding CCR)" in BOTH regimes, and under CRR the
    CCR legs carry ``approach_origin == "standardised"``, so today CRR's row 1
    AND row 2 both report them. CRR OV1 goes from 8 rows to 13.
    """

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
# Row 4a — pre-floor total RWEAs
# ---------------------------------------------------------------------------


class TestOv1Row4aPreFloorTotalRwea:
    """Row 4a must sum rwa_pre_floor across all exposures; c = a * 0.08."""

    def test_b31_ov1_row_4a_pre_floor_total_rwea(self) -> None:
        """generate_from_lazyframe (B31) produces row 4a with a=1000.0, c=80.0."""

        # Arrange
        lf = _make_pre_floor_lf()
        gen = LedgerShimPillar3Generator()

        # Act
        bundle = gen.generate_from_lazyframe(lf, framework="BASEL_3_1")

        # Assert
        assert bundle.ov1 is not None, "OV1 must be generated for B31 framework"
        df = bundle.ov1
        row_4a = df.filter(pl.col("row_ref") == "4a")
        assert row_4a.height == 1, "Exactly one row with ref '4a' must exist"

        a_val = row_4a["a"][0]
        c_val = row_4a["c"][0]
        assert a_val == pytest.approx(1000.0, abs=0.01), (
            f"Row 4a column 'a' (pre-floor total RWEAs): expected 1000.0, got {a_val}"
        )
        assert c_val == pytest.approx(80.0, abs=0.01), (
            f"Row 4a column 'c' (own funds requirement = 8% of a): expected 80.0, got {c_val}"
        )


# ---------------------------------------------------------------------------
# Rows 5a-7b — capital ratio rows default to None
# ---------------------------------------------------------------------------

_RATIO_ROW_REFS = ["5a", "5b", "6a", "6b", "7a", "7b"]


class TestOv1RatioRowsDefaultNone:
    """Without capital_ratios kwarg, rows 5a-7b must emit None for a/b/c."""

    def test_b31_ov1_rows_5a_to_7b_default_to_none(self) -> None:
        # Arrange
        lf = _make_pre_floor_lf()
        gen = LedgerShimPillar3Generator()

        # Act — no capital_ratios provided
        bundle = gen.generate_from_lazyframe(lf, framework="BASEL_3_1")

        # Assert
        assert bundle.ov1 is not None
        df = bundle.ov1
        for ref in _RATIO_ROW_REFS:
            ratio_row = df.filter(pl.col("row_ref") == ref)
            assert ratio_row.height == 1, f"Row '{ref}' must be present in OV1"
            for col in ("a", "b", "c"):
                val = ratio_row[col][0]
                assert val is None, (
                    f"Row '{ref}' column '{col}': expected None (no capital_ratios "
                    f"supplied), got {val}"
                )


# ---------------------------------------------------------------------------
# Rows 5a-7b — capital ratio rows use override when provided
# ---------------------------------------------------------------------------


class TestOv1RatioRowsUseOverride:
    """With Pillar3CapitalRatioOverrides, rows 5a/6a/7a carry the supplied ratios."""

    def test_b31_ov1_rows_5a_to_7b_use_override(self) -> None:
        import importlib

        # Assert the new config struct exists before proceeding — this is the
        # primary failing assertion when Pillar3CapitalRatioOverrides has not been
        # added to config.py yet.
        config_mod = importlib.import_module("rwa_calc.contracts.config")
        assert hasattr(config_mod, "Pillar3CapitalRatioOverrides"), (
            "Pillar3CapitalRatioOverrides must be defined in rwa_calc.contracts.config"
        )

        from rwa_calc.contracts.config import Pillar3CapitalRatioOverrides

        # Arrange
        overrides = Pillar3CapitalRatioOverrides(
            cet1_ratio_pre_floor=Decimal("0.135"),  # 13.5%
            tier1_ratio_pre_floor=Decimal("0.155"),  # 15.5%
            total_ratio_pre_floor=Decimal("0.185"),  # 18.5%
        )
        lf = _make_pre_floor_lf()
        gen = LedgerShimPillar3Generator()

        # Act
        bundle = gen.generate_from_lazyframe(
            lf,
            framework="BASEL_3_1",
            capital_ratios=overrides,
        )

        # Assert
        assert bundle.ov1 is not None
        df = bundle.ov1

        # Row 5a — CET1 ratio (pre-floor): 13.5% expressed as percentage points
        row_5a = df.filter(pl.col("row_ref") == "5a")
        assert row_5a.height == 1
        assert row_5a["a"][0] == pytest.approx(13.5, abs=0.001), (
            f"Row 5a 'a' (CET1 pre-floor %): expected 13.5, got {row_5a['a'][0]}"
        )

        # Row 6a — Tier 1 ratio (pre-floor): 15.5%
        row_6a = df.filter(pl.col("row_ref") == "6a")
        assert row_6a.height == 1
        assert row_6a["a"][0] == pytest.approx(15.5, abs=0.001), (
            f"Row 6a 'a' (Tier1 pre-floor %): expected 15.5, got {row_6a['a'][0]}"
        )

        # Row 7a — Total capital ratio (pre-floor): 18.5%
        row_7a = df.filter(pl.col("row_ref") == "7a")
        assert row_7a.height == 1
        assert row_7a["a"][0] == pytest.approx(18.5, abs=0.001), (
            f"Row 7a 'a' (Total capital pre-floor %): expected 18.5, got {row_7a['a'][0]}"
        )

        # Transitional rows 5b, 6b, 7b — still None (no transitional ratios supplied)
        for ref in ("5b", "6b", "7b"):
            tr_row = df.filter(pl.col("row_ref") == ref)
            assert tr_row.height == 1, f"Row '{ref}' must exist"
            val = tr_row["a"][0]
            assert val is None, (
                f"Row '{ref}' column 'a': expected None (transitional not supplied), got {val}"
            )
