"""Tests for stage-edge materialisation — eager edges, spill mode, event capture.

Migration Phase 1 (docs/plans/target-architecture-migration.md): stages
exchange materialised frames; spill failure raises (never a silent in-memory
fallback); every edge records an EdgeEvent into the run capture.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import (
    EdgeColumn,
    EdgeContract,
    EdgeContractViolation,
    sealed_edge_of,
)
from rwa_calc.engine.materialise import (
    SpillError,
    begin_edge_capture,
    current_edge_events,
    end_edge_capture,
    materialise_branches,
    materialise_edge,
    materialise_sealed_edge,
    plan_node_count,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cpu_config() -> CalculationConfig:
    """Default config — in-memory edges."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture()
def spill_config(tmp_path: Path) -> CalculationConfig:
    """Config with spill-to-parquet edges."""
    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31), spill_dir=tmp_path)
    return replace(config, spill_edges=True)


def _sample_lf() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "id": [1, 2, 3],
            "value": [10.0, 20.0, 30.0],
        }
    )


# ---------------------------------------------------------------------------
# materialise_edge — in-memory
# ---------------------------------------------------------------------------


class TestMaterialiseEdgeInMemory:
    """In-memory edge semantics (the default)."""

    def test_returns_lazyframe_with_same_data(self, cpu_config: CalculationConfig) -> None:
        result = materialise_edge(_sample_lf(), cpu_config, "edge_test")

        assert isinstance(result, pl.LazyFrame)
        assert result.collect().to_dicts() == _sample_lf().collect().to_dicts()

    def test_result_plan_is_shallow(self, cpu_config: CalculationConfig) -> None:
        deep = _sample_lf()
        for i in range(50):
            deep = deep.with_columns((pl.col("value") + i).alias(f"v{i}"))

        result = materialise_edge(deep, cpu_config, "depth_test")

        assert plan_node_count(result) < plan_node_count(deep)

    def test_no_spill_files_created(self, cpu_config: CalculationConfig, tmp_path: Path) -> None:
        token = begin_edge_capture()
        materialise_edge(_sample_lf(), cpu_config, "no_spill")
        end_edge_capture(token)

        assert list(tmp_path.glob("*.parquet")) == []


# ---------------------------------------------------------------------------
# materialise_edge — spill mode
# ---------------------------------------------------------------------------


class TestMaterialiseEdgeSpill:
    """Spill-to-parquet edge semantics (opt-in)."""

    def test_spill_roundtrip_preserves_data(self, spill_config: CalculationConfig) -> None:
        token = begin_edge_capture()
        result = materialise_edge(_sample_lf(), spill_config, "spill_roundtrip")
        rows = result.collect().to_dicts()
        events = end_edge_capture(token)

        assert rows == _sample_lf().collect().to_dicts()
        assert events[0].spilled is True

    def test_spill_files_cleaned_up_at_capture_end(
        self, spill_config: CalculationConfig, tmp_path: Path
    ) -> None:
        token = begin_edge_capture()
        materialise_edge(_sample_lf(), spill_config, "spill_cleanup")
        assert len(list(tmp_path.glob("*.parquet"))) == 1

        end_edge_capture(token)

        assert list(tmp_path.glob("*.parquet")) == []

    def test_spill_failure_raises_never_falls_back(self, spill_config: CalculationConfig) -> None:
        """A sink failure must raise SpillError, not silently collect in-memory."""

        # map_elements with a Python callable cannot be sunk by the streaming
        # engine in all cases; force failure deterministically with a plan
        # that raises during execution.
        def _boom(_: int) -> int:
            raise ValueError("forced sink failure")

        failing = _sample_lf().with_columns(
            pl.col("id").map_elements(_boom, return_dtype=pl.Int64).alias("boom")
        )

        with pytest.raises(SpillError, match="spill-to-parquet failed for edge 'spill_fail'"):
            materialise_edge(failing, spill_config, "spill_fail")

    def test_streaming_collect_engine_is_deprecated_alias(self, tmp_path: Path) -> None:
        """collect_engine='streaming' still spills, with one warning per run.

        Captures via a handler attached directly to the module logger —
        caplog relies on propagation to root, which configure_logging
        disables for the rwa_calc namespace when other tests on the same
        xdist worker have run the pipeline.
        """
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            collect_engine="streaming",
            spill_dir=tmp_path,
        )
        records: list[logging.LogRecord] = []

        class _ListHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        module_logger = logging.getLogger("rwa_calc.engine.materialise")
        handler = _ListHandler(level=logging.WARNING)
        module_logger.addHandler(handler)
        old_level = module_logger.level
        module_logger.setLevel(logging.WARNING)
        try:
            token = begin_edge_capture()
            materialise_edge(_sample_lf(), config, "deprecated_streaming")
            materialise_edge(_sample_lf(), config, "deprecated_streaming_2")
            events = end_edge_capture(token)
        finally:
            module_logger.removeHandler(handler)
            module_logger.setLevel(old_level)

        assert all(e.spilled for e in events)
        deprecations = [r for r in records if "deprecated" in r.getMessage()]
        assert len(deprecations) == 1, "deprecation warning must fire once per run"


# ---------------------------------------------------------------------------
# Edge-event capture
# ---------------------------------------------------------------------------


class TestEdgeCapture:
    """The per-run materialisation map."""

    def test_events_record_label_rows_and_timing(self, cpu_config: CalculationConfig) -> None:
        token = begin_edge_capture()
        materialise_edge(_sample_lf(), cpu_config, "capture_a")
        materialise_edge(_sample_lf().head(2), cpu_config, "capture_b")
        events = end_edge_capture(token)

        assert [e.label for e in events] == ["capture_a", "capture_b"]
        assert [e.rows for e in events] == [3, 2]
        assert all(e.columns == 2 for e in events)
        assert all(e.wall_ms >= 0 for e in events)
        assert all(e.estimated_bytes > 0 for e in events)

    def test_current_edge_events_snapshots_mid_run(self, cpu_config: CalculationConfig) -> None:
        token = begin_edge_capture()
        materialise_edge(_sample_lf(), cpu_config, "mid_run")

        snapshot = current_edge_events()

        assert [e.label for e in snapshot] == ["mid_run"]
        end_edge_capture(token)
        assert current_edge_events() == []

    def test_plan_nodes_recorded_only_when_requested(self, cpu_config: CalculationConfig) -> None:
        token = begin_edge_capture(count_plan_nodes=True)
        materialise_edge(_sample_lf(), cpu_config, "with_nodes")
        events = end_edge_capture(token)
        assert events[0].plan_nodes is not None and events[0].plan_nodes > 0

        token = begin_edge_capture()
        materialise_edge(_sample_lf(), cpu_config, "without_nodes")
        events = end_edge_capture(token)
        assert events[0].plan_nodes is None

    def test_no_capture_active_is_silent(self, cpu_config: CalculationConfig) -> None:
        """Edges outside an orchestrated run (unit tests, notebooks) just work."""
        result = materialise_edge(_sample_lf(), cpu_config, "no_capture")

        assert result.collect().height == 3
        assert current_edge_events() == []

    def test_event_as_dict_is_manifest_ready(self, cpu_config: CalculationConfig) -> None:
        token = begin_edge_capture()
        materialise_edge(_sample_lf(), cpu_config, "manifest")
        events = end_edge_capture(token)

        payload = events[0].as_dict()

        assert payload["label"] == "manifest"
        assert payload["rows"] == 3
        assert payload["spilled"] is False
        assert "plan_nodes" not in payload


# ---------------------------------------------------------------------------
# materialise_branches
# ---------------------------------------------------------------------------


class TestMaterialiseBranches:
    """Calculator-branch collection."""

    def test_collects_all_branches_in_order(self, cpu_config: CalculationConfig) -> None:
        lf = _sample_lf()
        branches = [lf.filter(pl.col("id") == 1), lf.filter(pl.col("id") > 1)]

        first, second = materialise_branches(branches, cpu_config, ["one", "rest"])

        assert isinstance(first, pl.DataFrame)
        assert (first.height, second.height) == (1, 2)

    def test_branch_events_recorded(self, cpu_config: CalculationConfig) -> None:
        lf = _sample_lf()
        token = begin_edge_capture()
        materialise_branches(
            [lf.filter(pl.col("id") == 1), lf.filter(pl.col("id") > 1)],
            cpu_config,
            ["one", "rest"],
        )
        events = end_edge_capture(token)

        assert [(e.label, e.rows) for e in events] == [("one", 1), ("rest", 2)]

    def test_spill_mode_roundtrip(self, spill_config: CalculationConfig) -> None:
        lf = _sample_lf()
        token = begin_edge_capture()
        first, second = materialise_branches(
            [lf.filter(pl.col("id") == 1), lf.filter(pl.col("id") > 1)],
            spill_config,
            ["one", "rest"],
        )
        events = end_edge_capture(token)

        assert (first.height, second.height) == (1, 2)
        assert all(e.spilled for e in events)


# ---------------------------------------------------------------------------
# plan_node_count
# ---------------------------------------------------------------------------


class TestPlanNodeCount:
    """The depth-ceiling metric."""

    def test_grows_with_plan_depth(self) -> None:
        shallow = _sample_lf()
        deep = shallow
        for i in range(20):
            deep = deep.with_columns((pl.col("value") * i).alias(f"d{i}"))

        assert plan_node_count(deep) > plan_node_count(shallow)


# ---------------------------------------------------------------------------
# materialise_sealed_edge (migration Phase 3)
# ---------------------------------------------------------------------------


class TestMaterialiseSealedEdge:
    """Conform + materialise + brand at a sealed stage exit."""

    @staticmethod
    def _edge() -> EdgeContract:
        return EdgeContract(
            name="test_sealed_edge",
            columns={
                "id": EdgeColumn(dtype=pl.Int64),
                "value": EdgeColumn(dtype=pl.Float64),
                "is_flagged": EdgeColumn(
                    dtype=pl.Boolean, required=False, default=False, fill_null_default=True
                ),
            },
        )

    def test_returns_branded_eager_backed_frame(self, cpu_config: CalculationConfig) -> None:
        out = materialise_sealed_edge(_sample_lf(), cpu_config, self._edge())

        assert sealed_edge_of(out) == "test_sealed_edge"
        assert plan_node_count(out) <= 2

    def test_output_is_contract_shaped(self, cpu_config: CalculationConfig) -> None:
        lf = _sample_lf().with_columns(pl.lit(1).alias("_scratch"))

        out = materialise_sealed_edge(lf, cpu_config, self._edge()).collect()

        assert out.columns == ["id", "value", "is_flagged"]
        assert out["is_flagged"].to_list() == [False, False, False]

    def test_violation_raises_before_any_collect(self, cpu_config: CalculationConfig) -> None:
        token = begin_edge_capture()
        with pytest.raises(EdgeContractViolation):
            materialise_sealed_edge(_sample_lf().drop("value"), cpu_config, self._edge())
        events = end_edge_capture(token)

        assert events == []

    def test_edge_event_recorded_under_edge_name(self, cpu_config: CalculationConfig) -> None:
        token = begin_edge_capture()
        materialise_sealed_edge(_sample_lf(), cpu_config, self._edge())
        events = end_edge_capture(token)

        assert [e.label for e in events] == ["test_sealed_edge"]

    def test_spill_mode_output_also_branded(self, spill_config: CalculationConfig) -> None:
        token = begin_edge_capture()
        out = materialise_sealed_edge(_sample_lf(), spill_config, self._edge())
        events = end_edge_capture(token)

        assert sealed_edge_of(out) == "test_sealed_edge"
        assert events[0].spilled is True
