"""
Stage-edge materialisation for the RWA pipeline.

Pipeline position:
    Called by PipelineOrchestrator at every stage exit, and by CRMProcessor at
    the single sanctioned intra-stage checkpoint (``crm_pre_guarantee``).

Key responsibilities:
- ``materialise_edge``: eager-collect a stage's output plan once at its exit
- ``materialise_branches``: collect the calculator branches to DataFrames
- ``EdgeEvent`` capture: the per-run materialisation map (label, rows, bytes,
  wall time, spill mode, optional plan-node count)
- Optional spill-to-parquet edge mode; a spill failure RAISES ``SpillError``
  — never a silent in-memory fallback

Architecture (migration Phase 1 — docs/plans/target-architecture-migration.md):
stages exchange materialised frames and laziness is strictly intra-stage.
Bundle fields remain ``pl.LazyFrame``-typed (a cheap ``.lazy()`` wrap over the
eager frame) until the Phase 3 producer seal flips them to ``DataFrame``.

Why eager edges: the constraint on the old lazy-first design was recursive
plan-tree DEPTH, not executor capacity. On very deep plans Polars hard-crashes
(SIGSEGV) during plan construction, the optimizer pass inside ``collect()``,
or Rust ``Drop`` teardown of the nested plan nodes — all BEFORE any executor
runs, so the streaming engine does not avoid it. Measured on Polars 1.37: the
crash threshold is ~25,000 plan nodes for trivial ``with_columns`` chains and
far lower for heavy ``when/then`` + join expressions; unbounded depth also
re-walks the full upstream per consumer during plan construction (~100x
slowdown measured on a 150-row fixture). Materialising at every stage exit
makes the inter-stage failure class unrepresentable; the per-edge plan-node
ceiling tests (tests/integration/test_stage_edges.py) bound the residual
intra-stage depth. The node threshold is a property of the installed Polars
version and must be re-measured on every Polars upgrade. Full investigation:
docs/plans/single-lazy-plan-refactor.md (superseded by this design).

References:
- docs/architecture/pipeline-collect-barriers.md (stage-edge inventory)
- docs/plans/target-architecture-migration.md (Phase 1)
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)


class SpillError(RuntimeError):
    """A spill-to-parquet edge failed to sink.

    Raised instead of silently falling back to an in-memory collect: the only
    reason to enable spill mode is a memory ceiling, so a silent fallback
    converts an explicit operator choice into an OOM at the worst moment.
    """


@dataclass(frozen=True)
class EdgeEvent:
    """One materialisation event in the per-run materialisation map."""

    label: str
    rows: int
    columns: int
    estimated_bytes: int
    wall_ms: float
    spilled: bool
    plan_nodes: int | None = None

    def as_dict(self) -> dict[str, object]:
        """Manifest-ready representation."""
        payload: dict[str, object] = {
            "label": self.label,
            "rows": self.rows,
            "columns": self.columns,
            "estimated_bytes": self.estimated_bytes,
            "wall_ms": self.wall_ms,
            "spilled": self.spilled,
        }
        if self.plan_nodes is not None:
            payload["plan_nodes"] = self.plan_nodes
        return payload


@dataclass
class _EdgeCapture:
    """Run-scoped mutable capture of edge events and spill-file lifecycle."""

    count_plan_nodes: bool = False
    events: list[EdgeEvent] = field(default_factory=list)
    spill_paths: list[Path] = field(default_factory=list)
    deprecation_warned: bool = False


_capture: ContextVar[_EdgeCapture | None] = ContextVar("rwa_edge_capture", default=None)


def begin_edge_capture(*, count_plan_nodes: bool = False) -> Token[_EdgeCapture | None]:
    """Start a run-scoped edge capture.

    The orchestrator calls this at run start; ``end_edge_capture`` (in the
    run's ``finally``) returns the events and deletes any spill files.
    ``count_plan_nodes=True`` additionally records the unoptimised plan-node
    count of every incoming edge plan — used by the plan-node ceiling tests;
    off by default because rendering the plan costs a full plan walk.
    """
    return _capture.set(_EdgeCapture(count_plan_nodes=count_plan_nodes))


def current_edge_events() -> list[EdgeEvent]:
    """Snapshot the events captured so far in this run (manifest hook)."""
    cap = _capture.get()
    return list(cap.events) if cap is not None else []


def end_edge_capture(token: Token[_EdgeCapture | None]) -> list[EdgeEvent]:
    """Finish the run's capture: delete spill files, return the event list."""
    cap = _capture.get()
    _capture.reset(token)
    if cap is None:
        return []
    for path in cap.spill_paths:
        try:
            if path.exists():
                path.unlink()
                logger.debug("cleaned up spill file %s", path)
        except OSError:
            logger.warning("failed to clean up spill file %s", path)
    return list(cap.events)


def plan_node_count(lf: pl.LazyFrame) -> int:
    """Count non-blank lines of the UNOPTIMISED logical plan rendering.

    This is the depth-ceiling metric used by the per-edge plan-node ceiling
    tests. It is a *consistent proxy* for native plan-tree size, not an exact
    node census; ceilings pinned against it must be re-measured on every
    Polars upgrade (calibration history: a ">500 nodes" comment survived for
    months while the measured SIGSEGV threshold was ~25,000).
    """
    rendered = lf.explain(optimized=False)
    return sum(1 for line in rendered.splitlines() if line.strip())


def materialise_edge(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    label: str,
) -> pl.LazyFrame:
    """Materialise a stage's output plan once, at its exit.

    In-memory by default (``lf.collect()`` then a cheap ``.lazy()`` wrap).
    With ``config.spill_edges`` (or the deprecated
    ``collect_engine="streaming"``) the frame is sunk to parquet and scanned
    back, capping peak memory at roughly one column batch; a sink failure
    raises :class:`SpillError` — never a silent in-memory fallback.

    Every call records an :class:`EdgeEvent` into the run's capture (when one
    is active) for the per-run materialisation map.
    """
    cap = _capture.get()
    nodes = plan_node_count(lf) if cap is not None and cap.count_plan_nodes else None

    started = time.perf_counter()
    if _spill_requested(config, cap):
        spill_path = _sink_to_parquet(lf, config, label, cap)
        out = pl.scan_parquet(spill_path)
        rows = int(out.select(pl.len()).collect().item())
        columns = len(out.collect_schema().names())
        estimated_bytes = spill_path.stat().st_size
        spilled = True
        result = out
    else:
        df = lf.collect()
        rows = df.height
        columns = df.width
        estimated_bytes = df.estimated_size()
        spilled = False
        result = df.lazy()
    wall_ms = round((time.perf_counter() - started) * 1000.0, 2)

    event = EdgeEvent(
        label=label,
        rows=rows,
        columns=columns,
        estimated_bytes=estimated_bytes,
        wall_ms=wall_ms,
        spilled=spilled,
        plan_nodes=nodes,
    )
    if cap is not None:
        cap.events.append(event)
    logger.debug(
        "edge %s materialised %d rows x %d cols in %.1f ms (%s)",
        label,
        rows,
        columns,
        wall_ms,
        "spill" if spilled else "in-memory",
    )
    return result


def materialise_branches(
    branches: list[pl.LazyFrame],
    config: CalculationConfig,
    labels: list[str],
) -> list[pl.DataFrame]:
    """Materialise the calculator branches, replacing ``pl.collect_all()``.

    In-memory mode collects all branches in one ``pl.collect_all`` call;
    spill mode sinks each branch sequentially (peak memory = one branch).
    Each branch records an :class:`EdgeEvent`.
    """
    cap = _capture.get()
    node_counts = (
        [plan_node_count(lf) for lf in branches]
        if cap is not None and cap.count_plan_nodes
        else [None] * len(branches)
    )

    started = time.perf_counter()
    if _spill_requested(config, cap):
        results: list[pl.DataFrame] = []
        for lf, label in zip(branches, labels, strict=True):
            spill_path = _sink_to_parquet(lf, config, cap=cap, label=label)
            results.append(pl.read_parquet(spill_path))
        spilled = True
    else:
        results = list(pl.collect_all(branches))
        spilled = False
    wall_ms = round((time.perf_counter() - started) * 1000.0, 2)

    if cap is not None:
        for df, label, nodes in zip(results, labels, node_counts, strict=True):
            cap.events.append(
                EdgeEvent(
                    label=label,
                    rows=df.height,
                    columns=df.width,
                    estimated_bytes=df.estimated_size(),
                    # collect_all computes branches together; attribute the
                    # shared wall time to each branch rather than inventing
                    # a split.
                    wall_ms=wall_ms,
                    spilled=spilled,
                    plan_nodes=nodes,
                )
            )
    return results


def _spill_requested(config: CalculationConfig, cap: _EdgeCapture | None) -> bool:
    """True when the run asked for spill-to-parquet edges.

    ``collect_engine="streaming"`` is the deprecated spelling — accepted with
    a once-per-run warning for one release; use ``spill_edges=True``.
    """
    if getattr(config, "spill_edges", False):
        return True
    if config.collect_engine == "streaming":
        if cap is None or not cap.deprecation_warned:
            logger.warning(
                "config.collect_engine='streaming' is deprecated; "
                "use spill_edges=True (same semantics: spill-to-parquet edges)"
            )
            if cap is not None:
                cap.deprecation_warned = True
        return True
    return False


def _sink_to_parquet(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    label: str,
    cap: _EdgeCapture | None,
) -> Path:
    """Sink a LazyFrame to a temp parquet file; raise ``SpillError`` on failure."""
    spill_dir = config.spill_dir if config.spill_dir is not None else None
    safe_label = label.replace("/", "_").replace(" ", "_")

    fd, tmp_path_str = tempfile.mkstemp(
        suffix=".parquet",
        prefix=f"rwa_{safe_label}_",
        dir=spill_dir,
    )
    os.close(fd)
    tmp_path = Path(tmp_path_str)
    if cap is not None:
        cap.spill_paths.append(tmp_path)

    try:
        lf.sink_parquet(tmp_path)
    except Exception as exc:
        raise SpillError(
            f"spill-to-parquet failed for edge '{label}' at {tmp_path}: {exc}. "
            "Spill mode exists to cap memory, so an in-memory fallback is "
            "never substituted — fix the sink failure or disable spill_edges."
        ) from exc
    logger.debug("spilled edge %s to %s", label, tmp_path)
    return tmp_path
