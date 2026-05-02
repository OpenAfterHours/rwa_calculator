"""Contract tests for ``apply_boolean_column_defaults``.

The helper is deliberately scoped to Boolean columns only. Float and String
defaults are anti-conservative for EAD and provisions and require Risk
sign-off to broaden. These tests pin the boundary so a future contributor
who tries to widen the helper without renaming it must also update this
contract — surfacing the change for explicit review.
"""

from __future__ import annotations

import polars as pl

from rwa_calc.data.column_spec import ColumnSpec, apply_boolean_column_defaults


class TestBooleanFillContract:
    """Pin the post-fill invariant for Boolean columns."""

    def test_fills_present_null_boolean(self) -> None:
        """A present-but-null Boolean column with non-None default is filled."""
        lf = pl.DataFrame({"committed": pl.Series([None, True, False], dtype=pl.Boolean)}).lazy()
        schema = {"committed": ColumnSpec(pl.Boolean, default=True, required=False)}

        out = apply_boolean_column_defaults(lf, schema).collect()

        assert out["committed"].to_list() == [True, True, False]

    def test_preserves_explicit_false_when_default_true(self) -> None:
        """Explicit False is regulatory-load-bearing and must not be flipped."""
        lf = pl.DataFrame({"committed": pl.Series([False, False], dtype=pl.Boolean)}).lazy()
        schema = {"committed": ColumnSpec(pl.Boolean, default=True, required=False)}

        out = apply_boolean_column_defaults(lf, schema).collect()

        assert out["committed"].to_list() == [False, False]

    def test_no_op_when_column_absent(self) -> None:
        """A missing column is not added (use ``ensure_columns`` for that)."""
        lf = pl.DataFrame({"other": [1, 2]}).lazy()
        schema = {"committed": ColumnSpec(pl.Boolean, default=True, required=False)}

        out = apply_boolean_column_defaults(lf, schema).collect()

        assert "committed" not in out.columns
        assert out["other"].to_list() == [1, 2]


class TestNonBooleanBoundary:
    """Pin that non-Boolean defaults are NOT filled by this helper."""

    def test_float_default_not_filled(self) -> None:
        """Float default is silently skipped (anti-conservative if filled)."""
        lf = pl.DataFrame({"amount": pl.Series([None, 1.5], dtype=pl.Float64)}).lazy()
        schema = {"amount": ColumnSpec(pl.Float64, default=0.0, required=False)}

        out = apply_boolean_column_defaults(lf, schema).collect()

        # First row stays None — must NOT become 0.0 silently.
        assert out["amount"][0] is None
        assert out["amount"][1] == 1.5

    def test_string_default_not_filled(self) -> None:
        """String default is silently skipped."""
        lf = pl.DataFrame({"book_code": pl.Series([None, "X"], dtype=pl.String)}).lazy()
        schema = {"book_code": ColumnSpec(pl.String, default="", required=False)}

        out = apply_boolean_column_defaults(lf, schema).collect()

        assert out["book_code"][0] is None
        assert out["book_code"][1] == "X"

    def test_mixed_schema_only_boolean_filled(self) -> None:
        """A schema with mixed dtypes fills Boolean only; others left as null."""
        lf = pl.DataFrame(
            {
                "committed": pl.Series([None], dtype=pl.Boolean),
                "amount": pl.Series([None], dtype=pl.Float64),
                "book_code": pl.Series([None], dtype=pl.String),
            }
        ).lazy()
        schema = {
            "committed": ColumnSpec(pl.Boolean, default=True, required=False),
            "amount": ColumnSpec(pl.Float64, default=0.0, required=False),
            "book_code": ColumnSpec(pl.String, default="", required=False),
        }

        out = apply_boolean_column_defaults(lf, schema).collect()

        assert out["committed"][0] is True  # filled
        assert out["amount"][0] is None  # NOT filled — Risk sign-off required
        assert out["book_code"][0] is None  # NOT filled
