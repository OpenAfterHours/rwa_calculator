"""Unit tests for ColumnSpec, ensure_columns, and dtypes_of."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import polars as pl
import pytest

from rwa_calc.data.column_spec import ColumnSpec, dtypes_of, ensure_columns

# =============================================================================
# ColumnSpec — frozen dataclass invariants
# =============================================================================


class TestColumnSpecFrozen:
    def test_column_spec_is_frozen(self) -> None:
        spec = ColumnSpec(pl.String)
        with pytest.raises(FrozenInstanceError):
            spec.dtype = pl.Int64  # type: ignore[misc]  # ty: ignore[invalid-assignment]

    def test_defaults_to_required_true_and_none_default(self) -> None:
        spec = ColumnSpec(pl.String)
        assert spec.required is True
        assert spec.default is None

    def test_accepts_explicit_default_and_required(self) -> None:
        spec = ColumnSpec(pl.Float64, default=0.0, required=False)
        assert spec.dtype == pl.Float64
        assert spec.default == 0.0
        assert spec.required is False


# =============================================================================
# ensure_columns — optional-only, idempotent, dtype-correct
# =============================================================================


class TestEnsureColumns:
    def test_adds_missing_optional_column_with_declared_default(self) -> None:
        lf = pl.LazyFrame({"a": [1, 2, 3]})
        schema = {
            "a": ColumnSpec(pl.Int64),
            "b": ColumnSpec(pl.String, default="", required=False),
        }

        result = ensure_columns(lf, schema).collect()

        assert result.columns == ["a", "b"]
        assert result["b"].to_list() == ["", "", ""]
        assert result.schema["b"] == pl.String

    def test_preserves_declared_dtype_for_missing_column(self) -> None:
        lf = pl.LazyFrame({"a": [1]})
        schema = {
            "a": ColumnSpec(pl.Int64),
            "ltv": ColumnSpec(pl.Float64, default=None, required=False),
            "flag": ColumnSpec(pl.Boolean, default=False, required=False),
        }

        result = ensure_columns(lf, schema).collect()

        assert result.schema["ltv"] == pl.Float64
        assert result.schema["flag"] == pl.Boolean
        assert result["ltv"].to_list() == [None]
        assert result["flag"].to_list() == [False]

    def test_does_not_add_missing_required_column(self) -> None:
        lf = pl.LazyFrame({"a": [1]})
        schema = {
            "a": ColumnSpec(pl.Int64),
            "required_missing": ColumnSpec(pl.String, default="x", required=True),
        }

        result = ensure_columns(lf, schema).collect()

        assert result.columns == ["a"]

    def test_is_noop_when_all_optional_columns_present(self) -> None:
        lf = pl.LazyFrame({"a": [1], "b": ["x"]})
        schema = {
            "a": ColumnSpec(pl.Int64),
            "b": ColumnSpec(pl.String, default="", required=False),
        }

        result = ensure_columns(lf, schema).collect()

        assert result.columns == ["a", "b"]
        assert result["b"].to_list() == ["x"]

    def test_does_not_recast_existing_column(self) -> None:
        # Column exists but with a wider dtype than declared — ensure_columns
        # must not interfere (loader is responsible for casting).
        lf = pl.LazyFrame({"a": [1.5]}, schema={"a": pl.Float64})
        schema = {"a": ColumnSpec(pl.Float32, default=0.0, required=False)}

        result = ensure_columns(lf, schema).collect()

        assert result.schema["a"] == pl.Float64
        assert result["a"].to_list() == [1.5]

    def test_empty_schema_is_noop(self) -> None:
        lf = pl.LazyFrame({"a": [1]})
        result = ensure_columns(lf, {}).collect()
        assert result.columns == ["a"]

    def test_adds_multiple_missing_optional_columns_in_single_pass(self) -> None:
        lf = pl.LazyFrame({"a": [1]})
        schema = {
            "b": ColumnSpec(pl.String, default="", required=False),
            "c": ColumnSpec(pl.Boolean, default=True, required=False),
            "d": ColumnSpec(pl.Float64, default=0.0, required=False),
        }

        result = ensure_columns(lf, schema).collect()

        assert set(result.columns) == {"a", "b", "c", "d"}
        assert result["b"].to_list() == [""]
        assert result["c"].to_list() == [True]
        assert result["d"].to_list() == [0.0]


# =============================================================================
# ensure_columns(present=) — the caller-supplied column set
# =============================================================================


class TestEnsureColumnsPresent:
    """``present=`` lets a caller skip a plan walk it has already paid for.

    The hazard it introduces is silent: ``with_columns`` on an alias that
    already exists REPLACES the column rather than duplicating it or raising,
    so a ``present`` that under-specifies overwrites live data with a typed
    null. On the ``ofcp_routing`` site that null meets
    ``airb_lgd_preserved_expr``'s ``.fill_null(True)`` and flips every A-IRB
    leg onto the LGD-Modelling route with no error anywhere.
    """

    def test_present_that_omits_a_live_column_does_not_null_it(self) -> None:
        # Arrange — `present` under-specifies: it omits a column the frame HAS.
        lf = pl.LazyFrame({"ref": ["a", "b"], "has_flag": [False, False]})
        schema = {"has_flag": ColumnSpec(pl.Boolean, default=None, required=False)}

        result = ensure_columns(lf, schema, present=["ref"]).collect()

        # Unguarded, this is [None, None] — the live column overwritten.
        assert result["has_flag"].to_list() == [False, False]

    def test_present_that_names_an_absent_column_still_skips_the_injection(self) -> None:
        # The overstating direction stays as it was: the injection is skipped
        # and surfaces later as a ColumnNotFound. Loud, so not guarded.
        lf = pl.LazyFrame({"ref": ["a"]})
        schema = {"has_flag": ColumnSpec(pl.Boolean, default=None, required=False)}

        result = ensure_columns(lf, schema, present=["ref", "has_flag"]).collect()

        assert result.columns == ["ref"]

    def test_present_is_a_noop_when_it_matches_the_frame(self) -> None:
        lf = pl.LazyFrame({"ref": ["a"], "has_flag": [True]})
        schema = {"has_flag": ColumnSpec(pl.Boolean, default=None, required=False)}

        result = ensure_columns(lf, schema, present=["ref", "has_flag"]).collect()

        assert result["has_flag"].to_list() == [True]

    def test_present_injects_in_schema_order_not_set_order(self) -> None:
        # The guard recomputes `missing` from the frame. Expressing that as a
        # set difference would make injection order follow set iteration, which
        # varies with the process hash seed -- non-deterministic column order,
        # and intermittently red structure-exact goldens.
        lf = pl.LazyFrame({"ref": ["a"], "keep": [1]})
        schema = {
            "b": ColumnSpec(pl.String, default="", required=False),
            "c": ColumnSpec(pl.Boolean, default=True, required=False),
            "d": ColumnSpec(pl.Float64, default=0.0, required=False),
        }

        without = ensure_columns(lf, schema).collect()
        with_present = ensure_columns(lf, schema, present=["ref"]).collect()

        assert with_present.columns == without.columns


# =============================================================================
# dtypes_of — projection compatible with Polars constructors
# =============================================================================


class TestDtypesOf:
    def test_returns_plain_dtype_dict(self) -> None:
        schema = {
            "a": ColumnSpec(pl.Int64),
            "b": ColumnSpec(pl.String, default="", required=False),
        }

        dtypes = dtypes_of(schema)

        assert dtypes == {"a": pl.Int64, "b": pl.String}

    def test_result_is_accepted_by_polars_dataframe_constructor(self) -> None:
        schema = {
            "a": ColumnSpec(pl.Int64),
            "b": ColumnSpec(pl.String, default="", required=False),
        }

        df = pl.DataFrame({"a": [1], "b": ["x"]}, schema=dtypes_of(schema))

        assert df.schema["a"] == pl.Int64
        assert df.schema["b"] == pl.String

    def test_empty_schema_returns_empty_dict(self) -> None:
        assert dtypes_of({}) == {}
