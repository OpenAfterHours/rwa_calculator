"""Unit tests for the reconciliation sub-row collapse helper.

Covers ``aggregate_to_key_grain``: collapsing guarantee (__G_/__REM) and
real-estate (split_parent_id) sub-rows back to the exposure grain, risk-weight
recomputation, composite/custom key aggregation, and the heterogeneity flag.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.aggregator._collapse import (
    HETEROGENEITY_FLAG,
    aggregate_to_key_grain,
)


def _row(df: pl.DataFrame, ref: str) -> dict:
    return df.filter(pl.col("exposure_reference") == ref).row(0, named=True)


class TestDefaultExposureGrain:
    def test_guarantee_split_sums_additive_and_recomputes_rw(self) -> None:
        # Arrange: L1 split into guaranteed (__G_) + remainder (__REM) sub-rows.
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["L1__G_GTR", "L1__REM", "L2"],
                "parent_exposure_reference": ["L1", "L1", "L2"],
                "exposure_class": ["corporate", "corporate", "retail"],
                "approach_applied": ["SA", "SA", "SA"],
                "ead_final": [60.0, 40.0, 200.0],
                "rwa_final": [12.0, 40.0, 150.0],
                "risk_weight": [0.20, 1.00, 0.75],
            }
        )

        # Act
        out = aggregate_to_key_grain(lf).collect()

        # Assert: L1 sums to ead 100 / rwa 52, rw recomputed as 52/100.
        l1 = _row(out, "L1")
        assert l1["ead_final"] == pytest.approx(100.0)
        assert l1["rwa_final"] == pytest.approx(52.0)
        assert l1["risk_weight"] == pytest.approx(0.52)

    def test_unsplit_row_is_unchanged(self) -> None:
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["L1__G_GTR", "L1__REM", "L2"],
                "parent_exposure_reference": ["L1", "L1", "L2"],
                "exposure_class": ["corporate", "corporate", "retail"],
                "approach_applied": ["SA", "SA", "SA"],
                "ead_final": [60.0, 40.0, 200.0],
                "rwa_final": [12.0, 40.0, 150.0],
                "risk_weight": [0.20, 1.00, 0.75],
            }
        )

        out = aggregate_to_key_grain(lf).collect()

        l2 = _row(out, "L2")
        assert l2["ead_final"] == pytest.approx(200.0)
        assert l2["rwa_final"] == pytest.approx(150.0)
        assert l2["risk_weight"] == pytest.approx(0.75)

    def test_re_split_collapses_via_split_parent_id(self) -> None:
        # Arrange: RE splits carry split_parent_id (no parent_exposure_reference).
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["M1_RES", "M1_COM", "M2"],
                "split_parent_id": ["M1", "M1", None],
                "exposure_class": ["retail", "retail", "corporate"],
                "approach_applied": ["SA", "SA", "SA"],
                "ead_final": [80.0, 20.0, 50.0],
                "rwa_final": [16.0, 10.0, 50.0],
                "risk_weight": [0.20, 0.50, 1.00],
            }
        )

        out = aggregate_to_key_grain(lf).collect()

        m1 = _row(out, "M1")
        assert m1["ead_final"] == pytest.approx(100.0)
        assert m1["rwa_final"] == pytest.approx(26.0)
        assert m1["risk_weight"] == pytest.approx(0.26)
        # M2 had a null split_parent_id -> keyed by its own reference.
        assert out.filter(pl.col("exposure_reference") == "M2").height == 1

    def test_no_parent_columns_falls_back_to_exposure_reference(self) -> None:
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["A", "B"],
                "ead_final": [10.0, 20.0],
                "rwa_final": [5.0, 20.0],
            }
        )

        out = aggregate_to_key_grain(lf).collect()

        assert out.height == 2
        assert set(out["exposure_reference"]) == {"A", "B"}

    def test_zero_ead_guard_yields_zero_risk_weight(self) -> None:
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["Z"],
                "parent_exposure_reference": ["Z"],
                "ead_final": [0.0],
                "rwa_final": [0.0],
                "risk_weight": [0.0],
            }
        )

        out = aggregate_to_key_grain(lf).collect()

        assert out["risk_weight"][0] == pytest.approx(0.0)


class TestCompositeKeyGrain:
    def test_aggregates_multiple_loans_to_key(self) -> None:
        # Arrange: two loans under one counterparty.
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["L1", "L2"],
                "counterparty_reference": ["C1", "C1"],
                "exposure_class": ["corporate", "corporate"],
                "approach_applied": ["SA", "SA"],
                "ead_final": [100.0, 50.0],
                "rwa_final": [50.0, 40.0],
                "risk_weight": [0.50, 0.80],
            }
        )

        # Act
        out = aggregate_to_key_grain(lf, ["counterparty_reference"]).collect()

        # Assert: single C1 row with summed ead/rwa and recomputed rw.
        assert out.height == 1
        c1 = out.row(0, named=True)
        assert c1["ead_final"] == pytest.approx(150.0)
        assert c1["rwa_final"] == pytest.approx(90.0)
        assert c1["risk_weight"] == pytest.approx(0.60)
        assert c1[HETEROGENEITY_FLAG] is False

    def test_flags_heterogeneous_class_when_aggregated(self) -> None:
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["L1", "L2"],
                "counterparty_reference": ["C1", "C1"],
                "exposure_class": ["corporate", "retail"],
                "approach_applied": ["SA", "SA"],
                "ead_final": [100.0, 50.0],
                "rwa_final": [50.0, 40.0],
                "risk_weight": [0.50, 0.80],
            }
        )

        out = aggregate_to_key_grain(lf, ["counterparty_reference"]).collect()

        assert out.row(0, named=True)[HETEROGENEITY_FLAG] is True

    def test_missing_key_column_raises(self) -> None:
        lf = pl.LazyFrame({"exposure_reference": ["L1"], "ead_final": [1.0]})

        with pytest.raises(ValueError, match="key columns not present"):
            aggregate_to_key_grain(lf, ["nonexistent_key"]).collect()
