"""Contract tests for ``_normalise_facility_mappings`` schema normalisation.

The resolver boundary (`HierarchyResolver.resolve`) calls
``_normalise_facility_mappings`` so that all downstream stages can rely on
``child_type`` existing on every ``facility_mappings`` frame. This test
pins the three accepted input shapes and the idempotency invariant.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.hierarchy import _normalise_facility_mappings


class TestNormaliseFacilityMappings:
    """Pin the three accepted input shapes + idempotency."""

    def _expected_columns(self) -> set[str]:
        return {"parent_facility_reference", "child_reference", "child_type"}

    def test_canonical_child_type_passes_through(self) -> None:
        """A frame already carrying ``child_type`` is unchanged in column set."""
        lf = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC1"],
                "child_reference": ["LOAN1"],
                "child_type": ["loan"],
            }
        ).lazy()

        normalised = _normalise_facility_mappings(lf)

        assert set(normalised.collect_schema().names()) == self._expected_columns()
        df = normalised.collect()
        assert df["child_type"][0] == "loan"

    def test_legacy_node_type_renamed_to_child_type(self) -> None:
        """``node_type`` is renamed to ``child_type``; values preserved."""
        lf = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC1"],
                "child_reference": ["LOAN1"],
                "node_type": ["loan"],
            }
        ).lazy()

        normalised = _normalise_facility_mappings(lf)

        cols = set(normalised.collect_schema().names())
        assert cols == self._expected_columns()
        assert "node_type" not in cols
        df = normalised.collect()
        assert df["child_type"][0] == "loan"

    def test_neither_column_synthesises_null_child_type(self) -> None:
        """A frame with no type column gets a synthesised null ``child_type``."""
        lf = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC1"],
                "child_reference": ["LOAN1"],
            }
        ).lazy()

        normalised = _normalise_facility_mappings(lf)

        cols = set(normalised.collect_schema().names())
        assert cols == self._expected_columns()
        df = normalised.collect()
        assert df["child_type"][0] is None

    def test_collision_raises_value_error(self) -> None:
        """Both ``child_type`` and ``node_type`` present is an ambiguous shape."""
        lf = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC1"],
                "child_reference": ["LOAN1"],
                "child_type": ["loan"],
                "node_type": ["facility"],
            }
        ).lazy()

        with pytest.raises(ValueError, match="ambiguous discriminator"):
            _normalise_facility_mappings(lf)

    def test_idempotent_on_canonical_input(self) -> None:
        """Calling twice on a canonical frame is a no-op."""
        lf = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC1"],
                "child_reference": ["LOAN1"],
                "child_type": ["loan"],
            }
        ).lazy()

        once = _normalise_facility_mappings(lf)
        twice = _normalise_facility_mappings(once)

        cols_once = set(once.collect_schema().names())
        cols_twice = set(twice.collect_schema().names())
        assert cols_once == cols_twice == self._expected_columns()

        df_once = once.collect()
        df_twice = twice.collect()
        assert df_once.equals(df_twice)

    def test_idempotent_on_legacy_input(self) -> None:
        """A second call after rename does not raise (no ``node_type`` left)."""
        lf = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC1"],
                "child_reference": ["LOAN1"],
                "node_type": ["loan"],
            }
        ).lazy()

        once = _normalise_facility_mappings(lf)
        twice = _normalise_facility_mappings(once)

        df_once = once.collect()
        df_twice = twice.collect()
        assert df_once.equals(df_twice)

    def test_idempotent_on_synthesised_input(self) -> None:
        """A second call after synthesis preserves the synthesised null column."""
        lf = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC1"],
                "child_reference": ["LOAN1"],
            }
        ).lazy()

        once = _normalise_facility_mappings(lf)
        twice = _normalise_facility_mappings(once)

        df_once = once.collect()
        df_twice = twice.collect()
        assert df_once.equals(df_twice)

    def test_three_shapes_produce_identical_column_sets(self) -> None:
        """The three accepted shapes converge on the same column set."""
        canonical = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC1"],
                "child_reference": ["LOAN1"],
                "child_type": ["loan"],
            }
        ).lazy()
        legacy = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC1"],
                "child_reference": ["LOAN1"],
                "node_type": ["loan"],
            }
        ).lazy()
        neither = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC1"],
                "child_reference": ["LOAN1"],
            }
        ).lazy()

        cols_canonical = set(_normalise_facility_mappings(canonical).collect_schema().names())
        cols_legacy = set(_normalise_facility_mappings(legacy).collect_schema().names())
        cols_neither = set(_normalise_facility_mappings(neither).collect_schema().names())

        assert cols_canonical == cols_legacy == cols_neither == self._expected_columns()
