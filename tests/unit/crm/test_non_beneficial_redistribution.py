"""
Unit tests for redistribute_non_beneficial() — greedy RW-ordered reallocation.

When multi-guarantor exposures have mixed beneficial/non-beneficial sub-rows,
the non-beneficial portions are reallocated to beneficial guarantors in order
of ascending guarantor_rw (lowest risk weight first) to minimise total RWA.

References:
    CRR Art. 213: Only beneficial guarantees should be applied
    CRR Art. 215-217: Guarantee substitution with multiple protections
    GitHub issue #239: Multiple guarantors — some not beneficial
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.crm.guarantees import redistribute_non_beneficial


def _make_multi_guarantor_frame(
    *,
    parent: str = "EXP001",
    guarantors: list[dict],
    remainder_ead: float = 0.0,
) -> pl.LazyFrame:
    """Build a LazyFrame simulating multi-guarantor sub-rows from _apply_guarantee_splits."""
    rows: list[dict] = []
    for g in guarantors:
        rows.append(
            {
                "parent_exposure_reference": parent,
                "exposure_reference": f"{parent}__G_{g['ref']}",
                "is_guarantee_beneficial": g["beneficial"],
                "guaranteed_portion": g["portion"],
                "ead_after_collateral": g["portion"],
                "original_guarantee_amount": g["original"],
                "guarantor_rw": g["rw"],
                "unguaranteed_portion": 0.0,
            }
        )
    # Remainder row
    rows.append(
        {
            "parent_exposure_reference": parent,
            "exposure_reference": f"{parent}__REM",
            "is_guarantee_beneficial": False,
            "guaranteed_portion": 0.0,
            "ead_after_collateral": remainder_ead,
            "original_guarantee_amount": 0.0,
            "guarantor_rw": None,
            "unguaranteed_portion": remainder_ead,
        }
    )
    return pl.LazyFrame(rows)


class TestRedistributeNonBeneficial:
    """redistribute_non_beneficial() reallocates EAD from non-beneficial to beneficial."""

    def test_mixed_beneficial_redistributes_to_best_guarantor(self) -> None:
        """Non-beneficial portion is absorbed by the lowest-RW beneficial guarantor."""
        # 3 guarantors, 1 non-beneficial:
        # G1 (RW=0.20, beneficial): 200k used, 1000k original capacity
        # G2 (RW=0.50, beneficial): 200k used, 200k original (no spare capacity)
        # G3 (RW=1.00, non-beneficial): 200k used
        # Remainder: 400k
        # Total EAD: 200+200+200+400 = 1000k
        lf = _make_multi_guarantor_frame(
            guarantors=[
                {"ref": "G1", "beneficial": True, "portion": 200.0, "original": 1000.0, "rw": 0.20},
                {"ref": "G2", "beneficial": True, "portion": 200.0, "original": 200.0, "rw": 0.50},
                {"ref": "G3", "beneficial": False, "portion": 200.0, "original": 200.0, "rw": 1.00},
            ],
            remainder_ead=400.0,
        )

        result = redistribute_non_beneficial(lf).collect()

        # G3's 200k freed. G1 has 800k spare capacity (1000-200), G2 has 0.
        # Greedy fill by RW: G1 absorbs all 200k (lowest RW, has capacity).
        g1 = result.filter(pl.col("exposure_reference") == "EXP001__G_G1")
        assert g1["guaranteed_portion"][0] == pytest.approx(400.0, rel=1e-6)
        assert g1["ead_after_collateral"][0] == pytest.approx(400.0, rel=1e-6)

        # G2 unchanged (no spare capacity)
        g2 = result.filter(pl.col("exposure_reference") == "EXP001__G_G2")
        assert g2["guaranteed_portion"][0] == pytest.approx(200.0, rel=1e-6)

        # G3 zeroed out
        g3 = result.filter(pl.col("exposure_reference") == "EXP001__G_G3")
        assert g3["guaranteed_portion"][0] == pytest.approx(0.0, rel=1e-6)
        assert g3["ead_after_collateral"][0] == pytest.approx(0.0, rel=1e-6)

        # Remainder absorbs any un-redistributable amount
        rem = result.filter(pl.col("exposure_reference") == "EXP001__REM")
        # Total new beneficial EAD = 400 + 200 = 600, parent EAD = 1000
        assert rem["ead_after_collateral"][0] == pytest.approx(400.0, rel=1e-6)

    def test_all_beneficial_no_change(self) -> None:
        """When all guarantors are beneficial, nothing changes."""
        lf = _make_multi_guarantor_frame(
            guarantors=[
                {"ref": "G1", "beneficial": True, "portion": 300.0, "original": 300.0, "rw": 0.20},
                {"ref": "G2", "beneficial": True, "portion": 300.0, "original": 300.0, "rw": 0.50},
            ],
            remainder_ead=400.0,
        )

        result = redistribute_non_beneficial(lf).collect()

        g1 = result.filter(pl.col("exposure_reference") == "EXP001__G_G1")
        assert g1["guaranteed_portion"][0] == pytest.approx(300.0, rel=1e-6)

        g2 = result.filter(pl.col("exposure_reference") == "EXP001__G_G2")
        assert g2["guaranteed_portion"][0] == pytest.approx(300.0, rel=1e-6)

    def test_all_non_beneficial_zeroes_all(self) -> None:
        """When all guarantors are non-beneficial, all portions become 0."""
        lf = _make_multi_guarantor_frame(
            guarantors=[
                {"ref": "G1", "beneficial": False, "portion": 400.0, "original": 400.0, "rw": 1.00},
                {"ref": "G2", "beneficial": False, "portion": 400.0, "original": 400.0, "rw": 1.00},
            ],
            remainder_ead=200.0,
        )

        result = redistribute_non_beneficial(lf).collect()

        # No beneficial guarantors → no redistribution, all portions zeroed
        g1 = result.filter(pl.col("exposure_reference") == "EXP001__G_G1")
        assert g1["guaranteed_portion"][0] == pytest.approx(400.0, rel=1e-6)

        g2 = result.filter(pl.col("exposure_reference") == "EXP001__G_G2")
        assert g2["guaranteed_portion"][0] == pytest.approx(400.0, rel=1e-6)

    def test_capacity_limited_excess_to_remainder(self) -> None:
        """When beneficial guarantors can't absorb all, excess goes to remainder."""
        # G1 (beneficial, 100k used, 150k original → 50k spare)
        # G2 (non-beneficial, 300k used)
        # Remainder: 600k
        # Total EAD: 100+300+600 = 1000k
        lf = _make_multi_guarantor_frame(
            guarantors=[
                {"ref": "G1", "beneficial": True, "portion": 100.0, "original": 150.0, "rw": 0.20},
                {"ref": "G2", "beneficial": False, "portion": 300.0, "original": 300.0, "rw": 1.00},
            ],
            remainder_ead=600.0,
        )

        result = redistribute_non_beneficial(lf).collect()

        # G1 absorbs 50k (all spare capacity), 250k unabsorbed
        g1 = result.filter(pl.col("exposure_reference") == "EXP001__G_G1")
        assert g1["guaranteed_portion"][0] == pytest.approx(150.0, rel=1e-6)

        # G2 zeroed
        g2 = result.filter(pl.col("exposure_reference") == "EXP001__G_G2")
        assert g2["guaranteed_portion"][0] == pytest.approx(0.0, rel=1e-6)

        # Remainder: 1000 - 150 = 850 (original 600 + 250 unabsorbed)
        rem = result.filter(pl.col("exposure_reference") == "EXP001__REM")
        assert rem["ead_after_collateral"][0] == pytest.approx(850.0, rel=1e-6)

    def test_single_guarantor_not_affected(self) -> None:
        """Single guarantor (no multi-split) passes through unchanged."""
        lf = pl.LazyFrame(
            {
                "parent_exposure_reference": ["EXP001"],
                "exposure_reference": ["EXP001"],  # Same → not a sub-row
                "is_guarantee_beneficial": [False],
                "guaranteed_portion": [500.0],
                "ead_after_collateral": [1000.0],
                "original_guarantee_amount": [500.0],
                "guarantor_rw": [1.0],
                "unguaranteed_portion": [500.0],
            }
        )

        result = redistribute_non_beneficial(lf).collect()

        # Unchanged — redistribution only affects multi-guarantor sub-rows
        assert result["guaranteed_portion"][0] == pytest.approx(500.0, rel=1e-6)
        assert result["unguaranteed_portion"][0] == pytest.approx(500.0, rel=1e-6)

    def test_missing_columns_returns_unchanged(self) -> None:
        """When required columns are missing, function returns input unchanged."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "ead_after_collateral": [1000.0],
            }
        )

        result = redistribute_non_beneficial(lf).collect()
        assert result.columns == ["exposure_reference", "ead_after_collateral"]

    def test_greedy_fills_lowest_rw_first(self) -> None:
        """Two beneficial guarantors: lowest RW gets filled before higher RW."""
        # G1 (RW=0.05, beneficial, 100k used, 500k original → 400k spare)
        # G2 (RW=0.20, beneficial, 100k used, 500k original → 400k spare)
        # G3 (non-beneficial, 300k used)
        # Remainder: 500k, Total EAD: 1000k
        lf = _make_multi_guarantor_frame(
            guarantors=[
                {"ref": "G1", "beneficial": True, "portion": 100.0, "original": 500.0, "rw": 0.05},
                {"ref": "G2", "beneficial": True, "portion": 100.0, "original": 500.0, "rw": 0.20},
                {"ref": "G3", "beneficial": False, "portion": 300.0, "original": 300.0, "rw": 1.00},
            ],
            remainder_ead=500.0,
        )

        result = redistribute_non_beneficial(lf).collect()

        # G3's 300k freed. G1 (RW=0.05) has 400k spare → absorbs all 300k.
        g1 = result.filter(pl.col("exposure_reference") == "EXP001__G_G1")
        assert g1["guaranteed_portion"][0] == pytest.approx(400.0, rel=1e-6)

        # G2 (RW=0.20) has 400k spare but G1 already absorbed all → no change
        g2 = result.filter(pl.col("exposure_reference") == "EXP001__G_G2")
        assert g2["guaranteed_portion"][0] == pytest.approx(100.0, rel=1e-6)

        # Remainder unchanged (all 300k absorbed by G1)
        rem = result.filter(pl.col("exposure_reference") == "EXP001__REM")
        assert rem["ead_after_collateral"][0] == pytest.approx(500.0, rel=1e-6)
