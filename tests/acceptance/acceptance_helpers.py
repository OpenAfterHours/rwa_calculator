"""
Shared, framework-agnostic helpers for acceptance tests.

Pipeline position:
    Used by the CRR / Basel 3.1 / comparison acceptance conftests and test
    modules to look up pipeline results, assert tolerances, and assemble
    RawDataBundles from loaded fixtures.

Key responsibilities:
- Scenario-group filtering (`get_scenarios_by_group`)
- Tolerance assertions (RWA / risk weight / EAD / supporting factor)
- Result lookup by exposure reference, with guarantee sub-row aggregation
- RawDataBundle assembly shared between the plain and IRB-enriched bundles

These helpers are byte-identical across the crr and basel31 conftests and are
extracted here (rather than a parent conftest) so the explicit-path imports in
the per-framework test modules keep resolving via the conftest re-exports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl
import pytest

from rwa_calc.data.schemas import ADDITIVE_OUTPUT_FIELDS
from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import RawDataBundle

# Numeric result fields that must be summed across guarantee sub-rows
# (guaranteed + remainder) when aggregating a parent exposure's result. Sourced
# from data/schemas so the engine collapse helper and these test helpers share a
# single source of truth (see engine/aggregator/_collapse.py).
_ADDITIVE_FIELDS = ADDITIVE_OUTPUT_FIELDS


# =============================================================================
# Scenario Selection
# =============================================================================


def get_scenarios_by_group(
    expected_outputs_df: pl.DataFrame,
    group: str,
) -> list[dict[str, Any]]:
    """Filter scenarios by group prefix."""
    return expected_outputs_df.filter(pl.col("scenario_group") == group).to_dicts()


# =============================================================================
# Assertion Helpers
# =============================================================================


def assert_rwa_within_tolerance(
    actual: float,
    expected: float,
    tolerance: float = 0.01,
    scenario_id: str = "",
) -> None:
    """
    Assert RWA values are within acceptable tolerance.

    Args:
        actual: The calculated RWA value
        expected: The expected RWA value
        tolerance: Relative tolerance (default 1%)
        scenario_id: Scenario ID for error messages
    """
    if expected == 0:
        assert actual == 0, f"{scenario_id}: Expected 0, got {actual}"
    else:
        relative_diff = abs(actual - expected) / abs(expected)
        assert relative_diff <= tolerance, (
            f"{scenario_id}: RWA difference {relative_diff * 100:.2f}% exceeds "
            f"tolerance {tolerance * 100:.0f}%: actual={actual:,.2f}, expected={expected:,.2f}"
        )


def assert_risk_weight_match(
    actual: float,
    expected: float,
    tolerance: float = 0.0001,
    scenario_id: str = "",
) -> None:
    """
    Assert risk weight values match exactly (or within very small tolerance).

    Args:
        actual: The calculated risk weight
        expected: The expected risk weight
        tolerance: Absolute tolerance (default 0.01%)
        scenario_id: Scenario ID for error messages
    """
    diff = abs(actual - expected)
    assert diff <= tolerance, (
        f"{scenario_id}: Risk weight mismatch: actual={actual:.4f}, expected={expected:.4f}"
    )


def assert_ead_match(
    actual: float,
    expected: float,
    tolerance: float = 0.01,
    scenario_id: str = "",
) -> None:
    """
    Assert EAD values match within tolerance.

    Args:
        actual: The calculated EAD value
        expected: The expected EAD value
        tolerance: Relative tolerance (default 1%)
        scenario_id: Scenario ID for error messages
    """
    if expected == 0:
        assert actual == 0, f"{scenario_id}: Expected EAD 0, got {actual}"
    else:
        relative_diff = abs(actual - expected) / abs(expected)
        assert relative_diff <= tolerance, (
            f"{scenario_id}: EAD difference {relative_diff * 100:.2f}% exceeds "
            f"tolerance {tolerance * 100:.0f}%: actual={actual:,.2f}, expected={expected:,.2f}"
        )


def assert_supporting_factor_match(
    actual: float,
    expected: float,
    scenario_id: str = "",
) -> None:
    """
    Assert supporting factor matches exactly.

    Args:
        actual: The calculated supporting factor
        expected: The expected supporting factor
        scenario_id: Scenario ID for error messages
    """
    assert actual == pytest.approx(expected, rel=0.0001), (
        f"{scenario_id}: Supporting factor mismatch: actual={actual}, expected={expected}"
    )


# =============================================================================
# Result Lookup
# =============================================================================


def get_result_for_exposure(
    results_df: pl.DataFrame,
    exposure_reference: str,
) -> dict | None:
    """
    Look up calculation result for a specific exposure.

    Tries exact match on exposure_reference first. If not found, falls back to
    matching via parent_exposure_reference and aggregates numeric fields across
    guarantee sub-rows (guaranteed + remainder).

    Args:
        results_df: DataFrame of pipeline results
        exposure_reference: The exposure reference to find

    Returns:
        dict of result values, or None if not found
    """
    filtered = results_df.filter(pl.col("exposure_reference") == exposure_reference)

    if filtered.height > 0:
        return filtered.row(0, named=True)

    # Fall back to parent_exposure_reference for guarantee sub-rows
    if "parent_exposure_reference" in results_df.columns:
        filtered = results_df.filter(pl.col("parent_exposure_reference") == exposure_reference)
    if filtered.height == 0:
        return None

    # Aggregate across sub-rows: sum additive fields, take first for others
    result: dict = {}
    for col_name in filtered.columns:
        if col_name in _ADDITIVE_FIELDS:
            result[col_name] = filtered[col_name].sum()
        else:
            result[col_name] = filtered[col_name][0]
    return result


def get_sa_result_for_exposure(
    sa_results_df: pl.DataFrame,
    exposure_reference: str,
) -> dict | None:
    """Look up SA result for a specific exposure."""
    return get_result_for_exposure(sa_results_df, exposure_reference)


def get_irb_result_for_exposure(
    irb_results_df: pl.DataFrame,
    exposure_reference: str,
) -> dict | None:
    """Look up IRB result for a specific exposure."""
    return get_result_for_exposure(irb_results_df, exposure_reference)


# =============================================================================
# RawDataBundle Assembly
# =============================================================================


def build_raw_bundle(
    fixtures: Any,
    *,
    model_permissions: pl.LazyFrame | None = None,
    enrich: bool = False,
) -> RawDataBundle:
    """
    Assemble a RawDataBundle from loaded fixtures.

    Args:
        fixtures: The loaded fixture container (LazyFrame attributes).
        model_permissions: Optional per-model IRB permissions table.
        enrich: When True, enrich internal ratings with a model_id so the
            pipeline can route exposures to IRB approaches.

    Returns:
        A RawDataBundle built from the fixture LazyFrames.
    """

    ratings = fixtures.ratings
    if enrich:
        from tests.fixtures.irb_test_helpers import enrich_ratings_with_model_id

        ratings = enrich_ratings_with_model_id(ratings)

    return make_raw_bundle(
        facilities=fixtures.facilities,
        loans=fixtures.loans,
        contingents=fixtures.contingents,
        counterparties=fixtures.counterparties,
        collateral=fixtures.collateral,
        guarantees=fixtures.guarantees,
        provisions=fixtures.provisions,
        ratings=ratings,
        facility_mappings=fixtures.facility_mappings,
        org_mappings=fixtures.org_mappings,
        lending_mappings=fixtures.lending_mappings,
        specialised_lending=fixtures.specialised_lending,
        model_permissions=model_permissions,
    )


def make_irb_bundle(fixtures: Any, model_permissions: pl.LazyFrame) -> RawDataBundle:
    """Build a RawDataBundle with enriched ratings and given model_permissions."""
    return build_raw_bundle(fixtures, model_permissions=model_permissions, enrich=True)
