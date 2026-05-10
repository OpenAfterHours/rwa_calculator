"""Unit tests for P1.162: UKB OV1 pre-floor rows (Basel 3.1).

Tests cover the 7 new P3Row entries added to B31_OV1_ROWS:
    4a  — Total RWEAs (pre-floor)
    5a  — CET1 ratio (pre-floor)
    5b  — CET1 ratio (pre-floor, transitional)
    6a  — Tier 1 ratio (pre-floor)
    6b  — Tier 1 ratio (pre-floor, transitional)
    7a  — Total capital ratio (pre-floor)
    7b  — Total capital ratio (pre-floor, transitional)

Final B31_OV1_ROWS length: 20. CRR_OV1_ROWS must remain at 8.

References:
    PRA PS1/26 Disclosure (CRR) Part, Art. 456
    UKB OV1 template — pre-floor supplementary rows

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

# ---------------------------------------------------------------------------
# Expected constants
# ---------------------------------------------------------------------------

_EXPECTED_B31_REFS: list[str] = [
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

_EXPECTED_B31_COUNT = 20
_EXPECTED_CRR_COUNT = 8

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
    """B31_OV1_ROWS must contain exactly 20 rows after P1.162."""

    def test_b31_ov1_rows_count_is_20(self) -> None:
        # Arrange / Act — no computation needed; template is a module constant
        # Assert
        assert len(B31_OV1_ROWS) == _EXPECTED_B31_COUNT


class TestB31Ov1RowOrder:
    """B31_OV1_ROWS must follow the exact 20-element ref sequence."""

    def test_b31_ov1_row_refs_in_expected_order(self) -> None:
        # Arrange
        actual_refs = [r.ref for r in B31_OV1_ROWS]
        # Assert
        assert actual_refs == _EXPECTED_B31_REFS


class TestCrrOv1Unchanged:
    """CRR_OV1_ROWS must remain at 8 rows (P1.162 is Basel 3.1 only)."""

    def test_crr_ov1_rows_unchanged(self) -> None:
        # Assert
        assert len(CRR_OV1_ROWS) == _EXPECTED_CRR_COUNT


# ---------------------------------------------------------------------------
# Row 4a — pre-floor total RWEAs
# ---------------------------------------------------------------------------


class TestOv1Row4aPreFloorTotalRwea:
    """Row 4a must sum rwa_pre_floor across all exposures; c = a * 0.08."""

    def test_b31_ov1_row_4a_pre_floor_total_rwea(self) -> None:
        """generate_from_lazyframe (B31) produces row 4a with a=1000.0, c=80.0."""
        from rwa_calc.reporting.pillar3.generator import Pillar3Generator

        # Arrange
        lf = _make_pre_floor_lf()
        gen = Pillar3Generator()

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
        from rwa_calc.reporting.pillar3.generator import Pillar3Generator

        # Arrange
        lf = _make_pre_floor_lf()
        gen = Pillar3Generator()

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
        from rwa_calc.reporting.pillar3.generator import Pillar3Generator

        # Arrange
        overrides = Pillar3CapitalRatioOverrides(
            cet1_ratio_pre_floor=Decimal("0.135"),  # 13.5%
            tier1_ratio_pre_floor=Decimal("0.155"),  # 15.5%
            total_ratio_pre_floor=Decimal("0.185"),  # 18.5%
        )
        lf = _make_pre_floor_lf()
        gen = Pillar3Generator()

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
