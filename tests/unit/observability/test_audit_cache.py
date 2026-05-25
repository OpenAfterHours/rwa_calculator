"""Unit tests for the opt-in audit cache helpers in ``engine/materialise.py``.

Covers ``sink_audit`` (the per-frame writer surfaced to the CRM stages) and
``prune_audit_cache`` (the size-cap helper invoked at the start of each run).
Behaviour pinned here:

- ``sink_audit`` no-ops when ``CalculationConfig.audit_cache_dir`` is None.
- ``sink_audit`` writes a parquet under ``<dir>/<run_id>/<name>.parquet`` and
  the write is atomic (``.tmp`` then ``os.replace``).
- The active ``run_id`` is read from ``observability.context.current_run_id``;
  with no run id bound, ``sink_audit`` logs a warning and skips.
- ``prune_audit_cache`` retains only the ``audit_cache_max_runs`` newest
  subdirectories (mtime-ordered) and is a no-op when either field is None.
- Failures during the write are logged and swallowed — the helper must never
  raise into a real pipeline run.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.materialise import prune_audit_cache, sink_audit
from rwa_calc.observability import clear_run_id, new_run_id
from rwa_calc.observability.logging_setup import _NAMESPACE


@pytest.fixture(autouse=True)
def _reset_namespace_logger() -> Iterator[None]:
    """Reset the ``rwa_calc`` namespace logger so caplog can capture records.

    A prior test elsewhere in the suite may have called ``configure_logging``,
    which sets ``propagate=False`` on the namespace logger and attaches its
    own handler. Both states prevent caplog from receiving WARNING records
    we assert on below. Mirrors the analogous fixture in ``test_logging.py``.
    """
    from rwa_calc.observability import logging_setup

    def _reset() -> None:
        namespace_logger = logging.getLogger(_NAMESPACE)
        for handler in namespace_logger.handlers:
            namespace_logger.removeHandler(handler)
        namespace_logger.filters.clear()
        namespace_logger.propagate = True
        namespace_logger.setLevel(logging.NOTSET)
        if hasattr(namespace_logger, "_rwa_calc_handler"):
            delattr(namespace_logger, "_rwa_calc_handler")
        logging_setup._configured = None

    _reset()
    yield
    _reset()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def crr_config_with_cache(tmp_path: Path) -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        audit_cache_dir=tmp_path,
    )


def test_sink_audit_noop_when_audit_cache_dir_is_none(
    tmp_path: Path,
    crr_config: CalculationConfig,
) -> None:
    """Default config disables the cache: no files anywhere."""
    sink_audit(pl.DataFrame({"x": [1, 2, 3]}), crr_config, "should_not_appear")

    assert list(tmp_path.iterdir()) == []


def test_sink_audit_writes_dataframe_to_run_subdir(
    crr_config_with_cache: CalculationConfig,
    tmp_path: Path,
) -> None:
    """Eager DataFrame is round-trippable under ``<dir>/<run_id>/<name>.parquet``."""
    run_id, token = new_run_id()
    try:
        sink_audit(pl.DataFrame({"x": [1, 2, 3]}), crr_config_with_cache, "df_artifact")
    finally:
        clear_run_id(token)

    final_path = tmp_path / run_id / "df_artifact.parquet"
    assert final_path.is_file(), f"missing artifact {final_path}"
    round_trip = pl.read_parquet(final_path)
    assert round_trip["x"].to_list() == [1, 2, 3]


def test_sink_audit_writes_lazyframe(
    crr_config_with_cache: CalculationConfig,
    tmp_path: Path,
) -> None:
    """LazyFrame goes through ``sink_parquet`` and round-trips identically."""
    run_id, token = new_run_id()
    try:
        sink_audit(pl.LazyFrame({"y": [10, 20]}), crr_config_with_cache, "lf_artifact")
    finally:
        clear_run_id(token)

    round_trip = pl.read_parquet(tmp_path / run_id / "lf_artifact.parquet")
    assert round_trip["y"].to_list() == [10, 20]


def test_sink_audit_atomic_no_tmp_files_left_behind(
    crr_config_with_cache: CalculationConfig,
    tmp_path: Path,
) -> None:
    """``.tmp`` shim is renamed away — only the final ``.parquet`` survives."""
    run_id, token = new_run_id()
    try:
        sink_audit(pl.DataFrame({"x": [1]}), crr_config_with_cache, "atomic_check")
    finally:
        clear_run_id(token)

    run_dir = tmp_path / run_id
    leftover = [p.name for p in run_dir.iterdir() if p.suffix == ".tmp"]
    assert leftover == [], f"left behind {leftover}"


def test_sink_audit_warns_and_skips_when_no_run_id(
    crr_config_with_cache: CalculationConfig,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    """No active run_id => log WARNING, write nothing, do not raise."""
    caplog.set_level(logging.WARNING, logger="rwa_calc.engine.materialise")

    sink_audit(pl.DataFrame({"x": [1]}), crr_config_with_cache, "orphan")

    assert any("no active run_id" in r.message for r in caplog.records)
    assert list(tmp_path.iterdir()) == []


def test_sink_audit_swallows_failure(
    monkeypatch: pytest.MonkeyPatch,
    crr_config_with_cache: CalculationConfig,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    """Disk / permission errors are logged at WARNING and never re-raised."""
    caplog.set_level(logging.WARNING, logger="rwa_calc.engine.materialise")

    def _boom(self, *_args, **_kwargs):  # noqa: ANN001 - mirroring polars signature
        raise OSError("simulated disk full")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", _boom)

    run_id, token = new_run_id()
    try:
        sink_audit(pl.DataFrame({"x": [1]}), crr_config_with_cache, "will_fail")
    finally:
        clear_run_id(token)

    assert any("sink_audit(will_fail) failed" in r.message for r in caplog.records)
    assert not (tmp_path / run_id / "will_fail.parquet").exists()
    assert not (tmp_path / run_id / "will_fail.parquet.tmp").exists()


def test_sink_audit_sanitises_artifact_name(
    crr_config_with_cache: CalculationConfig,
    tmp_path: Path,
) -> None:
    """Slashes and spaces in artifact names are replaced — no nested paths."""
    run_id, token = new_run_id()
    try:
        sink_audit(pl.DataFrame({"x": [1]}), crr_config_with_cache, "my path/name")
    finally:
        clear_run_id(token)

    expected = tmp_path / run_id / "my_path_name.parquet"
    assert expected.is_file()


def test_prune_noop_when_max_runs_is_none(
    crr_config_with_cache: CalculationConfig,
    tmp_path: Path,
) -> None:
    """No cap => no deletion regardless of subdir count."""
    for name in ("a", "b", "c", "d"):
        (tmp_path / name).mkdir()

    prune_audit_cache(crr_config_with_cache)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["a", "b", "c", "d"]


def test_prune_keeps_n_newest_dirs(tmp_path: Path) -> None:
    """``audit_cache_max_runs=2`` retains the two newest, deletes the rest."""
    cfg = CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        audit_cache_dir=tmp_path,
        audit_cache_max_runs=2,
    )
    # Create four run-style dirs each with a fake parquet, in ascending mtime order.
    for i, name in enumerate(("oldest", "older", "newer", "newest")):
        d = tmp_path / name
        d.mkdir()
        (d / "x.parquet").write_bytes(b"fake")
        ts = time.time() + i
        os.utime(d, (ts, ts))

    prune_audit_cache(cfg)

    survivors = sorted(p.name for p in tmp_path.iterdir())
    assert survivors == ["newer", "newest"]


def test_prune_zero_keeps_everything(tmp_path: Path) -> None:
    """``audit_cache_max_runs=0`` is treated as a no-op guard (defensive)."""
    cfg = CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        audit_cache_dir=tmp_path,
        audit_cache_max_runs=0,
    )
    for name in ("a", "b"):
        (tmp_path / name).mkdir()

    prune_audit_cache(cfg)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["a", "b"]


def test_prune_noop_when_dir_missing(tmp_path: Path) -> None:
    """Cache dir not yet materialised: prune is silent, does not create it."""
    missing = tmp_path / "does_not_exist"
    cfg = CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        audit_cache_dir=missing,
        audit_cache_max_runs=2,
    )

    prune_audit_cache(cfg)

    assert not missing.exists()


def test_prune_ignores_non_directory_entries(tmp_path: Path) -> None:
    """Stray files in the cache root are left alone; only subdirs are counted."""
    cfg = CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        audit_cache_dir=tmp_path,
        audit_cache_max_runs=1,
    )
    (tmp_path / "stray.txt").write_text("hello", encoding="utf-8")
    for i, name in enumerate(("run_a", "run_b")):
        d = tmp_path / name
        d.mkdir()
        (d / "x.parquet").write_bytes(b"x")
        ts = time.time() + i
        os.utime(d, (ts, ts))

    prune_audit_cache(cfg)

    names = sorted(p.name for p in tmp_path.iterdir())
    assert "stray.txt" in names
    assert "run_b" in names  # newer survives
    assert "run_a" not in names  # older dropped
