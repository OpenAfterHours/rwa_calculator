"""Unit tests for hierarchy resolver max-depth truncation guard (P2.35).

Tests cover:
- A 12-node chain (depth 11) triggers HIE003 WARNING on the truncated node.
- The truncated chain still returns the deepest reachable parent (not the
  true ultimate) so the pipeline remains functional.
- Nodes whose chain terminates naturally at or below max_depth do NOT get
  a spurious HIE003 warning.
- Exactly one HIE003 is emitted for a single truncated chain.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_HIERARCHY_DEPTH
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.engine.hierarchy import HierarchyResolver
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# 12 nodes: CP_DEPTH_C0 is the leaf; CP_DEPTH_C11 is the true ultimate root.
# Edges:  C0→C1, C1→C2, ..., C10→C11  (11 edges, chain depth 11 from C0).
_NODES = [f"CP_DEPTH_C{i}" for i in range(12)]


@pytest.fixture
def depth_truncation_bundle() -> RawDataBundle:
    """RawDataBundle with a 12-node straight chain exceeding max_depth=10."""
    # Arrange: 11 child→parent edges
    children = [f"CP_DEPTH_C{i}" for i in range(11)]  # C0..C10
    parents = [f"CP_DEPTH_C{i}" for i in range(1, 12)]  # C1..C11

    org_mappings = pl.DataFrame(
        {
            "child_counterparty_reference": children,
            "parent_counterparty_reference": parents,
        }
    ).lazy()

    # All 12 counterparties - match the simple_counterparties shape in test_hierarchy.py
    n = len(_NODES)
    counterparties = pl.DataFrame(
        {
            "counterparty_reference": _NODES,
            "counterparty_name": [f"Depth Corp {i}" for i in range(n)],
            "entity_type": ["corporate"] * n,
            "country_code": ["GB"] * n,
            "annual_revenue": [100_000_000.0] * n,
            "total_assets": [500_000_000.0] * n,
            "default_status": [False] * n,
            "sector_code": ["MANU"] * n,
            "is_financial_institution": [False] * n,
            "apply_fi_scalar": [True] * n,
            "is_pse": [False] * n,
            "is_mdb": [False] * n,
            "is_international_org": [False] * n,
            "is_central_counterparty": [False] * n,
            "is_regional_govt_local_auth": [False] * n,
            "is_managed_as_retail": [False] * n,
        }
    ).lazy()

    # Minimal ratings — empty schema matching the resolver's expected shape.
    ratings: pl.LazyFrame = pl.LazyFrame(
        schema={
            "rating_reference": pl.String,
            "counterparty_reference": pl.String,
            "rating_type": pl.String,
            "rating_agency": pl.String,
            "rating_value": pl.String,
            "cqs": pl.Int64,
            "pd": pl.Float64,
            "model_id": pl.String,
            "rating_date": pl.Date,
        }
    )

    # Minimal empty loans (required positional field on RawDataBundle)
    loans: pl.LazyFrame = pl.LazyFrame(
        schema={
            "loan_reference": pl.String,
            "product_type": pl.String,
            "book_code": pl.String,
            "counterparty_reference": pl.String,
            "value_date": pl.Date,
            "maturity_date": pl.Date,
            "currency": pl.String,
            "drawn_amount": pl.Float64,
            "lgd": pl.Float64,
            "beel": pl.Float64,
            "seniority": pl.String,
            "risk_type": pl.String,
            "ccf_modelled": pl.Float64,
            "is_short_term_trade_lc": pl.Boolean,
        }
    )

    empty_lf: pl.LazyFrame = pl.LazyFrame()

    lending_mappings: pl.LazyFrame = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )

    facility_mappings: pl.LazyFrame = pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
        }
    )

    return make_raw_bundle(
        facilities=empty_lf,
        loans=loans,
        counterparties=counterparties,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        org_mappings=org_mappings,
        ratings=ratings,
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run_resolver(raw_bundle: RawDataBundle):  # type: ignore[return]
    """Run HierarchyResolver.resolve and return the ResolvedHierarchyBundle."""
    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    resolver = HierarchyResolver()
    return resolver.resolve(raw_bundle, config)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestHierarchyMaxDepthTruncation:
    """Tests for the HIE003 depth-truncation warning (P2.35)."""

    def test_chain_exceeding_max_depth_emits_hie003_warning(
        self,
        depth_truncation_bundle: RawDataBundle,
    ) -> None:
        """A 12-node chain (depth 11) must produce exactly one HIE003 WARNING.

        Arrange:
            depth_truncation_bundle — 12 counterparties connected in a straight
            chain with 11 parent-child edges.  max_depth inside
            _build_ultimate_parent_lazy defaults to 10, so CP_DEPTH_C0 is
            truncated after 10 hops.
        Act:
            Run HierarchyResolver.resolve.
        Assert:
            - At least one HIE003 is present in hierarchy_errors.
            - Its severity is WARNING (not ERROR).
            - Its category is HIERARCHY.
            - Its counterparty_reference is "CP_DEPTH_C0".
            - Its message contains "CP_DEPTH_C0" and "max_depth".
        """
        # Act
        bundle = _run_resolver(depth_truncation_bundle)

        # Assert — at least one HIE003 must exist
        hie003_errors = [e for e in bundle.hierarchy_errors if e.code == ERROR_HIERARCHY_DEPTH]
        assert len(hie003_errors) >= 1, (
            f"Expected at least one HIE003 error but got none. "
            f"All hierarchy_errors: {bundle.hierarchy_errors}"
        )

        err = hie003_errors[0]
        assert err.severity == ErrorSeverity.WARNING, (
            f"HIE003 must be WARNING severity, got {err.severity!r}"
        )
        assert err.category == ErrorCategory.HIERARCHY, (
            f"HIE003 must have HIERARCHY category, got {err.category!r}"
        )
        assert err.counterparty_reference == "CP_DEPTH_C0", (
            f"HIE003 must reference CP_DEPTH_C0, got {err.counterparty_reference!r}"
        )
        assert "CP_DEPTH_C0" in err.message, (
            f"HIE003 message must contain 'CP_DEPTH_C0', got: {err.message!r}"
        )
        assert "max_depth" in err.message, (
            f"HIE003 message must contain 'max_depth', got: {err.message!r}"
        )

    def test_truncated_chain_still_returns_deepest_reachable_parent(
        self,
        depth_truncation_bundle: RawDataBundle,
    ) -> None:
        """After truncation CP_DEPTH_C0 resolves to CP_DEPTH_C10 (not C11).

        The depth-guard is non-fatal: the pipeline continues and the truncated
        node is assigned the deepest parent reached before the limit fired.

        Arrange:
            Same 12-node chain as above.  max_depth=10 means C0 walks 10 hops
            (C0→C1→...→C10) and stops; it never reaches C11.
        Act:
            Run HierarchyResolver.resolve.
        Assert:
            - The ultimate_parent_mappings entry for CP_DEPTH_C0 has
              ultimate_parent_reference == "CP_DEPTH_C10".
            - hierarchy_depth == 10.
        """
        # Act
        bundle = _run_resolver(depth_truncation_bundle)

        # The ultimate_parent_mappings LazyFrame lives inside counterparty_lookup
        ump_df = bundle.counterparty_lookup.ultimate_parent_mappings.collect()
        c0_row = ump_df.filter(pl.col("counterparty_reference") == "CP_DEPTH_C0")

        assert len(c0_row) == 1, (
            f"Expected exactly one row for CP_DEPTH_C0 in ultimate_parent_mappings, "
            f"got {len(c0_row)}.  Full table:\n{ump_df}"
        )
        assert c0_row["ultimate_parent_reference"][0] == "CP_DEPTH_C10", (
            f"Truncated chain should resolve to CP_DEPTH_C10 (depth 10), "
            f"got {c0_row['ultimate_parent_reference'][0]!r}"
        )
        assert c0_row["hierarchy_depth"][0] == 10, (
            f"hierarchy_depth for truncated C0 should be 10, got {c0_row['hierarchy_depth'][0]}"
        )

    def test_chain_at_exactly_max_depth_does_not_emit_hie003(
        self,
        depth_truncation_bundle: RawDataBundle,
    ) -> None:
        """Nodes at depth <= max_depth from their root must not trigger HIE003.

        CP_DEPTH_C1 is depth 10 from the true root (C11) — it terminates
        naturally exactly at the limit.  CP_DEPTH_C2 is depth 9.  Neither
        is truncated, so neither should produce a HIE003.

        Arrange:
            Same 12-node chain fixture.
        Act:
            Run HierarchyResolver.resolve.
        Assert:
            No HIE003 error references CP_DEPTH_C1 or CP_DEPTH_C2.
        """
        # Act
        bundle = _run_resolver(depth_truncation_bundle)

        # Assert — no HIE003 for C1 or C2
        spurious = [
            e
            for e in bundle.hierarchy_errors
            if e.code == ERROR_HIERARCHY_DEPTH
            and e.counterparty_reference in {"CP_DEPTH_C1", "CP_DEPTH_C2"}
        ]
        assert len(spurious) == 0, (
            f"Expected no HIE003 for CP_DEPTH_C1 or CP_DEPTH_C2, got: {spurious}"
        )

    def test_only_one_hie003_emitted_for_single_truncated_chain(
        self,
        depth_truncation_bundle: RawDataBundle,
    ) -> None:
        """Exactly one HIE003 is emitted across the 12-node fixture.

        Only CP_DEPTH_C0 is truncated (depth 11 > max_depth 10).  All other
        nodes have depth <= 10 from the root they reach, so no further HIE003
        errors should appear.

        Arrange:
            Same 12-node chain fixture.
        Act:
            Run HierarchyResolver.resolve.
        Assert:
            Exactly one HIE003 in hierarchy_errors.
        """
        # Act
        bundle = _run_resolver(depth_truncation_bundle)

        # Assert
        all_hie003 = [e for e in bundle.hierarchy_errors if e.code == ERROR_HIERARCHY_DEPTH]
        assert len(all_hie003) == 1, (
            f"Expected exactly 1 HIE003 error (for CP_DEPTH_C0 only), "
            f"got {len(all_hie003)}: {all_hie003}"
        )
