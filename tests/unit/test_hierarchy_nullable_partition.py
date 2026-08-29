"""Tests for null-partition guarding in window-aggregate enrichments.

Polars ``.over(key)`` collapses ALL null-keyed rows into a single partition.
Without the ``partition_by_nullable`` guard, two unrelated counterparties that
both have a null ``lending_group_reference`` would be aggregated together —
silently pooling their drawn / nominal amounts.

These tests pin the behaviour of ``_enrich_with_lending_group`` against that
regression. Each test runs under both ``cpu`` and ``streaming`` collect
engines because the streaming engine has historically had subtle differences
in null-group handling.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.hierarchy import HierarchyResolver

# ---------------------------------------------------------------------------
# Engine-config fixtures (copied verbatim from tests/unit/test_materialise.py
# so this module is self-contained and does not depend on cross-test imports).
# Acknowledged duplication; lifting to conftest is out of scope for this PR.
# ---------------------------------------------------------------------------


@pytest.fixture()
def cpu_config() -> CalculationConfig:
    """Config with cpu engine — uses in-memory collect."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31), collect_engine="cpu")


@pytest.fixture()
def streaming_config(tmp_path: Path) -> CalculationConfig:
    """Config with streaming engine — uses disk-spill via sink_parquet."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        collect_engine="streaming",
        spill_dir=tmp_path,
    )


@pytest.fixture(params=["cpu_config", "streaming_config"])
def any_config(request: pytest.FixtureRequest) -> CalculationConfig:
    """Parametrised over both engines — every test runs twice."""
    return request.getfixturevalue(request.param)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _build_minimal_exposures(rows: list[dict[str, object]]) -> pl.LazyFrame:
    """Build the minimal exposure frame ``_enrich_with_lending_group`` consumes."""
    return pl.DataFrame(rows).lazy()


# ---------------------------------------------------------------------------
# Tests — null-partition guard for lending_group_reference
# ---------------------------------------------------------------------------


class TestNullableLendingGroupAggregation:
    """Null `lending_group_reference` rows must NOT pool across counterparties."""

    def test_two_unrelated_unmapped_counterparties_do_not_pool(
        self,
        any_config: CalculationConfig,  # noqa: ARG002 (engine parametrisation)
    ) -> None:
        """Two counterparties with no lending group must aggregate separately.

        Pre-fix (raw `.over("lending_group_reference")`): both rows share a
        null partition, so each row's ``lending_group_total_exposure`` would
        be the SUM of both counterparties' exposures.

        Post-fix (`partition_by_nullable`): the null branch falls back to
        ``.over("counterparty_reference")``, so each row aggregates only
        within its own counterparty.
        """
        resolver = HierarchyResolver()

        # Two unrelated counterparties, neither in a lending group.
        exposures = _build_minimal_exposures(
            [
                {
                    "exposure_reference": "EXP_A",
                    "counterparty_reference": "CP_A",
                    "drawn_amount": 100.0,
                    "nominal_amount": 0.0,
                    "exposure_for_retail_threshold": 100.0,
                },
                {
                    "exposure_reference": "EXP_B",
                    "counterparty_reference": "CP_B",
                    "drawn_amount": 500.0,
                    "nominal_amount": 0.0,
                    "exposure_for_retail_threshold": 500.0,
                },
            ]
        )
        empty_lending = pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        )

        result = resolver._enrich_with_lending_group(exposures, empty_lending).collect()

        cp_a = result.filter(pl.col("counterparty_reference") == "CP_A")
        cp_b = result.filter(pl.col("counterparty_reference") == "CP_B")

        assert len(cp_a) == 1 and len(cp_b) == 1

        # Each must see only its own counterparty's exposure, NOT the pooled sum.
        assert cp_a["lending_group_total_exposure"][0] == 100.0, (
            "CP_A's total pooled with CP_B — null-partition collapse regression"
        )
        assert cp_b["lending_group_total_exposure"][0] == 500.0, (
            "CP_B's total pooled with CP_A — null-partition collapse regression"
        )
        assert cp_a["lending_group_adjusted_exposure"][0] == 100.0
        assert cp_b["lending_group_adjusted_exposure"][0] == 500.0

    def test_mixed_grouped_and_ungrouped_no_cross_pooling(
        self,
        any_config: CalculationConfig,  # noqa: ARG002 (engine parametrisation)
    ) -> None:
        """A grouped counterparty and an ungrouped one must not cross-pool.

        The grouped counterparty's total includes its lending-group siblings;
        the ungrouped counterparty's total is its own exposure only — even
        though both branches share the null-vs-non-null distinction.
        """
        resolver = HierarchyResolver()

        # CP_GROUPED is in a lending group with CP_SIBLING (each 100 drawn).
        # CP_UNGROUPED is alone (500 drawn).
        exposures = _build_minimal_exposures(
            [
                {
                    "exposure_reference": "EXP_GROUPED",
                    "counterparty_reference": "CP_GROUPED",
                    "drawn_amount": 100.0,
                    "nominal_amount": 0.0,
                    "exposure_for_retail_threshold": 100.0,
                },
                {
                    "exposure_reference": "EXP_SIBLING",
                    "counterparty_reference": "CP_SIBLING",
                    "drawn_amount": 100.0,
                    "nominal_amount": 0.0,
                    "exposure_for_retail_threshold": 100.0,
                },
                {
                    "exposure_reference": "EXP_UNGROUPED",
                    "counterparty_reference": "CP_UNGROUPED",
                    "drawn_amount": 500.0,
                    "nominal_amount": 0.0,
                    "exposure_for_retail_threshold": 500.0,
                },
            ]
        )
        lending = pl.DataFrame(
            {
                "parent_counterparty_reference": ["LG_PARENT", "LG_PARENT"],
                "child_counterparty_reference": ["CP_GROUPED", "CP_SIBLING"],
            }
        ).lazy()

        result = resolver._enrich_with_lending_group(exposures, lending).collect()

        grouped = result.filter(pl.col("counterparty_reference") == "CP_GROUPED")
        ungrouped = result.filter(pl.col("counterparty_reference") == "CP_UNGROUPED")

        # Grouped row aggregates over its lending group (100 + 100 = 200).
        assert grouped["lending_group_total_exposure"][0] == 200.0
        # Ungrouped row aggregates over its own counterparty (500), NOT pooled
        # with any other null-membership rows.
        assert ungrouped["lending_group_total_exposure"][0] == 500.0
        # Ungrouped row's lending_group_reference should be null.
        assert ungrouped["lending_group_reference"][0] is None
