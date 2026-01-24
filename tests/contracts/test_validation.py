"""Tests for schema validation functions.

Tests the validation utilities for checking LazyFrame schemas
against expected definitions.
"""

import polars as pl
import pytest

from rwa_calc.contracts.validation import (
    normalize_risk_type,
    validate_ccf_modelled,
    validate_lgd_range,
    validate_non_negative_amounts,
    validate_pd_range,
    validate_required_columns,
    validate_risk_type,
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


class TestValidateRiskType:
    """Tests for validate_risk_type function."""

    def test_valid_risk_type_codes(self):
        """Valid risk type codes (FR, MR, MLR, LR) should pass."""
        lf = pl.LazyFrame({"risk_type": ["FR", "MR", "MLR", "LR"]})

        result = validate_risk_type(lf)
        df = result.collect()

        assert all(df["_valid_risk_type"].to_list())

    def test_valid_risk_type_full_values(self):
        """Valid full values should pass."""
        lf = pl.LazyFrame({
            "risk_type": ["full_risk", "medium_risk", "medium_low_risk", "low_risk"]
        })

        result = validate_risk_type(lf)
        df = result.collect()

        assert all(df["_valid_risk_type"].to_list())

    def test_case_insensitive(self):
        """Validation should be case insensitive."""
        lf = pl.LazyFrame({"risk_type": ["fr", "Fr", "FR", "FULL_RISK", "Full_Risk"]})

        result = validate_risk_type(lf)
        df = result.collect()

        assert all(df["_valid_risk_type"].to_list())

    def test_invalid_values_fail(self):
        """Invalid risk type values should fail validation."""
        lf = pl.LazyFrame({"risk_type": ["FR", "INVALID", "HIGH", "MR"]})

        result = validate_risk_type(lf)
        df = result.collect()

        assert df["_valid_risk_type"].to_list() == [True, False, False, True]

    def test_missing_column(self):
        """Should return original LazyFrame if column missing."""
        lf = pl.LazyFrame({"other_column": [1, 2, 3]})

        result = validate_risk_type(lf)
        df = result.collect()

        assert "_valid_risk_type" not in df.columns


class TestValidateCCFModelled:
    """Tests for validate_ccf_modelled function."""

    def test_valid_range(self):
        """Valid CCF values (0.0 to 1.5) should pass. Retail IRB can exceed 100%."""
        lf = pl.LazyFrame({"ccf_modelled": [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5]})

        result = validate_ccf_modelled(lf)
        df = result.collect()

        assert all(df["_valid_ccf_modelled"].to_list())

    def test_null_is_valid(self):
        """Null values should be valid (optional field)."""
        lf = pl.LazyFrame({"ccf_modelled": [0.5, None, 0.75, None]})

        result = validate_ccf_modelled(lf)
        df = result.collect()

        assert all(df["_valid_ccf_modelled"].to_list())

    def test_out_of_range_fails(self):
        """Values outside [0.0, 1.5] should fail."""
        lf = pl.LazyFrame({"ccf_modelled": [-0.1, 0.5, 1.25, 1.6, 2.0]})

        result = validate_ccf_modelled(lf)
        df = result.collect()

        # -0.1 fails (below 0), 0.5 passes, 1.25 passes (Retail IRB can exceed 100%), 1.6 and 2.0 fail (above 150%)
        assert df["_valid_ccf_modelled"].to_list() == [False, True, True, False, False]

    def test_missing_column(self):
        """Should return original LazyFrame if column missing."""
        lf = pl.LazyFrame({"other_column": [1.0, 2.0, 3.0]})

        result = validate_ccf_modelled(lf)
        df = result.collect()

        assert "_valid_ccf_modelled" not in df.columns


class TestNormalizeRiskType:
    """Tests for normalize_risk_type function."""

    def test_normalizes_codes_to_full_values(self):
        """Should normalize codes to full values."""
        lf = pl.LazyFrame({"risk_type": ["FR", "MR", "MLR", "LR"]})

        result = normalize_risk_type(lf)
        df = result.collect()

        assert df["risk_type"].to_list() == [
            "full_risk",
            "medium_risk",
            "medium_low_risk",
            "low_risk",
        ]

    def test_preserves_full_values(self):
        """Full values should be preserved (lowercased)."""
        lf = pl.LazyFrame({
            "risk_type": ["full_risk", "MEDIUM_RISK", "medium_low_risk", "LOW_RISK"]
        })

        result = normalize_risk_type(lf)
        df = result.collect()

        # Full values are lowercased and preserved
        assert df["risk_type"].to_list() == [
            "full_risk",
            "medium_risk",
            "medium_low_risk",
            "low_risk",
        ]

    def test_case_insensitive_normalization(self):
        """Normalization should be case insensitive."""
        lf = pl.LazyFrame({"risk_type": ["fr", "Fr", "FR", "fR"]})

        result = normalize_risk_type(lf)
        df = result.collect()

        assert df["risk_type"].to_list() == [
            "full_risk",
            "full_risk",
            "full_risk",
            "full_risk",
        ]

    def test_missing_column(self):
        """Should return original LazyFrame if column missing."""
        lf = pl.LazyFrame({"other_column": ["a", "b", "c"]})

        result = normalize_risk_type(lf)
        df = result.collect()

        assert "other_column" in df.columns
        assert "risk_type" not in df.columns
