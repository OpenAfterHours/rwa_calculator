"""Unit tests for aggregator utility functions."""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.aggregator import (
    FLOOR_IMPACT_SCHEMA,
    IRB_APPROACHES,
    RESULT_SCHEMA,
    col_or_default,
    empty_frame,
    prepare_irb_results,
    prepare_sa_results,
    resolve_rwa_col,
)


class TestResolveRwaCol:
    """Tests for resolve_rwa_col fallback chain."""

    def test_prefers_rwa_post_factor(self) -> None:
        assert resolve_rwa_col({"rwa_post_factor", "rwa_final", "rwa"}) == "rwa_post_factor"

    def test_falls_back_to_rwa_final(self) -> None:
        assert resolve_rwa_col({"rwa_final", "rwa"}) == "rwa_final"

    def test_falls_back_to_rwa(self) -> None:
        assert resolve_rwa_col({"rwa", "other"}) == "rwa"

    def test_returns_none_when_missing(self) -> None:
        assert resolve_rwa_col({"ead", "risk_weight"}) is None

    def test_accepts_list(self) -> None:
        assert resolve_rwa_col(["rwa_final", "ead"]) == "rwa_final"


class TestColOrDefault:
    """Tests for col_or_default expression builder."""

    def test_returns_col_when_present(self) -> None:
        cols = {"exposure_class", "ead_final"}
        expr = col_or_default("exposure_class", cols)
        lf = pl.LazyFrame({"exposure_class": ["CORPORATE"]})
        result = lf.select(expr).collect()
        assert result["exposure_class"][0] == "CORPORATE"

    def test_returns_null_when_absent(self) -> None:
        cols: set[str] = {"ead_final"}
        expr = col_or_default("exposure_class", cols)
        lf = pl.LazyFrame({"ead_final": [100.0]})
        result = lf.select(expr).collect()
        assert result["exposure_class"][0] is None

    def test_returns_custom_default(self) -> None:
        cols: set[str] = {"ead_final"}
        expr = col_or_default("is_sme", cols, pl.lit(False))
        lf = pl.LazyFrame({"ead_final": [100.0]})
        result = lf.select(expr).collect()
        assert result["is_sme"][0] is False


class TestEmptyFrame:
    """Tests for empty_frame factory."""

    def test_creates_correct_schema(self) -> None:
        lf = empty_frame(RESULT_SCHEMA)
        schema = lf.collect_schema()
        assert schema["exposure_reference"] == pl.String
        assert schema["rwa_final"] == pl.Float64
        assert len(schema) == len(RESULT_SCHEMA)

    def test_has_zero_rows(self) -> None:
        df = empty_frame(FLOOR_IMPACT_SCHEMA).collect()
        assert len(df) == 0


class TestIRBApproaches:
    """Tests for IRB_APPROACHES constant."""

    @pytest.mark.parametrize(
        "approach",
        ["foundation_irb", "advanced_irb", "FIRB", "AIRB", "IRB"],
    )
    def test_contains_all_expected(self, approach: str) -> None:
        assert approach in IRB_APPROACHES

    def test_is_frozenset(self) -> None:
        assert isinstance(IRB_APPROACHES, frozenset)


class TestPrepareIRBResults:
    """Tests for prepare_irb_results guarantee-based approach substitution."""

    def test_fully_guaranteed_sa_becomes_standardised(self) -> None:
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "approach": ["FIRB"],
                "rwa": [100.0],
                "guarantor_approach": ["sa"],
                "guarantee_ratio": [1.0],
            }
        )
        result = prepare_irb_results(irb).collect()
        assert result["approach_applied"][0] == "standardised"

    def test_partially_guaranteed_keeps_original(self) -> None:
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "approach": ["FIRB"],
                "rwa": [100.0],
                "guarantor_approach": ["sa"],
                "guarantee_ratio": [0.5],
            }
        )
        result = prepare_irb_results(irb).collect()
        assert result["approach_applied"][0] == "FIRB"

    def test_no_guarantee_cols_defaults_to_approach(self) -> None:
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "approach": ["advanced_irb"],
                "rwa": [100.0],
            }
        )
        result = prepare_irb_results(irb).collect()
        assert result["approach_applied"][0] == "advanced_irb"


class TestPrepareSAResults:
    """Tests for prepare_sa_results."""

    def test_adds_sa_approach_and_rwa_final(self) -> None:
        sa = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "rwa_post_factor": [500.0],
                "rwa": [600.0],
            }
        )
        result = prepare_sa_results(sa).collect()
        assert result["approach_applied"][0] == "SA"
        assert result["rwa_final"][0] == 500.0  # prefers rwa_post_factor
