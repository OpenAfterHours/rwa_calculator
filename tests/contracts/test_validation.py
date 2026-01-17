"""Tests for schema validation functions.

Tests the validation utilities for checking LazyFrame schemas
against expected definitions.
"""

import polars as pl
import pytest

from rwa_calc.contracts.validation import (
    validate_lgd_range,
    validate_non_negative_amounts,
    validate_pd_range,
    validate_required_columns,
    validate_schema,
    validate_schema_to_errors,
)
from rwa_calc.domain.enums import ErrorCategory


class TestValidateSchema:
    """Tests for validate_schema function."""

    def test_valid_schema_returns_empty(self):
        """Valid schema should return empty error list."""
        lf = pl.LazyFrame({
            "col1": [1, 2, 3],
            "col2": ["a", "b", "c"],
        })
        expected = {
            "col1": pl.Int64,
            "col2": pl.String,
        }

        errors = validate_schema(lf, expected)

        assert errors == []

    def test_missing_column_detected(self):
        """Missing column should be reported."""
        lf = pl.LazyFrame({"col1": [1, 2, 3]})
        expected = {
            "col1": pl.Int64,
            "col2": pl.String,  # Missing
        }

        errors = validate_schema(lf, expected, context="test")

        assert len(errors) == 1
        assert "col2" in errors[0]
        assert "Missing" in errors[0]
        assert "[test]" in errors[0]

    def test_type_mismatch_detected(self):
        """Type mismatch should be reported."""
        lf = pl.LazyFrame({"col1": ["a", "b", "c"]})  # String, not Int64
        expected = {"col1": pl.Int64}

        errors = validate_schema(lf, expected)

        assert len(errors) == 1
        assert "col1" in errors[0]
        assert "mismatch" in errors[0].lower()

    def test_compatible_int_types_allowed(self):
        """Compatible integer types should not cause errors."""
        lf = pl.LazyFrame({"col1": pl.Series([1, 2, 3], dtype=pl.Int32)})
        expected = {"col1": pl.Int64}

        errors = validate_schema(lf, expected)

        assert errors == []

    def test_compatible_float_types_allowed(self):
        """Compatible float types should not cause errors."""
        lf = pl.LazyFrame({"col1": pl.Series([1.0, 2.0], dtype=pl.Float32)})
        expected = {"col1": pl.Float64}

        errors = validate_schema(lf, expected)

        assert errors == []

    def test_strict_mode_flags_extra_columns(self):
        """Strict mode should flag unexpected columns."""
        lf = pl.LazyFrame({
            "col1": [1, 2, 3],
            "col2": ["a", "b", "c"],
            "extra": [True, False, True],
        })
        expected = {
            "col1": pl.Int64,
            "col2": pl.String,
        }

        errors = validate_schema(lf, expected, strict=True)

        assert len(errors) == 1
        assert "extra" in errors[0]
        assert "Unexpected" in errors[0]

    def test_multiple_errors_reported(self):
        """Multiple issues should all be reported."""
        lf = pl.LazyFrame({"col1": ["a", "b"]})  # Wrong type
        expected = {
            "col1": pl.Int64,  # Type mismatch
            "col2": pl.String,  # Missing
            "col3": pl.Float64,  # Missing
        }

        errors = validate_schema(lf, expected)

        assert len(errors) == 3


class TestValidateRequiredColumns:
    """Tests for validate_required_columns function."""

    def test_all_required_present(self):
        """All required columns present should return empty list."""
        lf = pl.LazyFrame({"col1": [1], "col2": [2], "col3": [3]})
        required = ["col1", "col2"]

        errors = validate_required_columns(lf, required)

        assert errors == []

    def test_missing_required_reported(self):
        """Missing required columns should be reported."""
        lf = pl.LazyFrame({"col1": [1]})
        required = ["col1", "col2", "col3"]

        errors = validate_required_columns(lf, required, context="test")

        assert len(errors) == 2
        assert any("col2" in e for e in errors)
        assert any("col3" in e for e in errors)


class TestValidateSchemaToErrors:
    """Tests for validate_schema_to_errors function."""

    def test_returns_calculation_errors(self):
        """Should return CalculationError objects."""
        lf = pl.LazyFrame({"col1": [1]})
        expected = {
            "col1": pl.Int64,
            "col2": pl.String,  # Missing
        }

        errors = validate_schema_to_errors(lf, expected, context="test")

        assert len(errors) == 1
        assert errors[0].category == ErrorCategory.SCHEMA_VALIDATION
        assert errors[0].field_name == "col2"

    def test_type_mismatch_error(self):
        """Type mismatch should create CalculationError."""
        lf = pl.LazyFrame({"col1": ["string"]})
        expected = {"col1": pl.Int64}

        errors = validate_schema_to_errors(lf, expected)

        assert len(errors) == 1
        assert "Int64" in str(errors[0].expected_value)
        assert "String" in str(errors[0].actual_value)


class TestValidateNonNegativeAmounts:
    """Tests for validate_non_negative_amounts function."""

    def test_adds_validation_columns(self):
        """Should add _valid_ columns for amount fields."""
        lf = pl.LazyFrame({
            "amount1": [100.0, -50.0, 0.0],
            "amount2": [200.0, 300.0, -100.0],
        })

        result = validate_non_negative_amounts(lf, ["amount1", "amount2"])
        df = result.collect()

        assert "_valid_amount1" in df.columns
        assert "_valid_amount2" in df.columns
        assert df["_valid_amount1"].to_list() == [True, False, True]
        assert df["_valid_amount2"].to_list() == [True, True, False]

    def test_ignores_missing_columns(self):
        """Should ignore columns not in LazyFrame."""
        lf = pl.LazyFrame({"amount1": [100.0, 200.0]})

        result = validate_non_negative_amounts(lf, ["amount1", "missing"])
        df = result.collect()

        assert "_valid_amount1" in df.columns
        assert "_valid_missing" not in df.columns


class TestValidatePDRange:
    """Tests for validate_pd_range function."""

    def test_valid_pd_values(self):
        """Valid PD values should pass validation."""
        lf = pl.LazyFrame({"pd": [0.0, 0.01, 0.5, 1.0]})

        result = validate_pd_range(lf)
        df = result.collect()

        assert all(df["_valid_pd"].to_list())

    def test_invalid_pd_values(self):
        """Invalid PD values should fail validation."""
        lf = pl.LazyFrame({"pd": [-0.01, 0.5, 1.01]})

        result = validate_pd_range(lf)
        df = result.collect()

        assert df["_valid_pd"].to_list() == [False, True, False]

    def test_custom_pd_range(self):
        """Should respect custom min/max values."""
        lf = pl.LazyFrame({"pd": [0.0003, 0.01, 0.5]})

        result = validate_pd_range(lf, min_pd=0.0003)
        df = result.collect()

        assert all(df["_valid_pd"].to_list())


class TestValidateLGDRange:
    """Tests for validate_lgd_range function."""

    def test_valid_lgd_values(self):
        """Valid LGD values should pass validation."""
        lf = pl.LazyFrame({"lgd": [0.0, 0.45, 1.0]})

        result = validate_lgd_range(lf)
        df = result.collect()

        assert all(df["_valid_lgd"].to_list())

    def test_lgd_can_exceed_one(self):
        """LGD can exceed 1.0 in some cases (downturn LGD)."""
        lf = pl.LazyFrame({"lgd": [0.45, 1.1, 1.25]})

        result = validate_lgd_range(lf, max_lgd=1.25)
        df = result.collect()

        assert all(df["_valid_lgd"].to_list())

    def test_invalid_lgd_values(self):
        """Invalid LGD values should fail validation."""
        lf = pl.LazyFrame({"lgd": [-0.1, 0.45, 1.5]})

        result = validate_lgd_range(lf, max_lgd=1.25)
        df = result.collect()

        assert df["_valid_lgd"].to_list() == [False, True, False]
