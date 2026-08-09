"""
Contract: the Polars thread pool is capped for the test session.

Pipeline position:
    None — this is a harness contract, not a pipeline stage. It guards the
    ``POLARS_MAX_THREADS`` default set at the top of ``tests/conftest.py``.

Key responsibilities:
- Assert the cap is actually in force, and that it took effect *before* Polars
  first initialised its pool. Setting the variable after the first
  ``import polars`` anywhere in the process is a silent no-op: the variable
  would read back correctly while the pool stayed at the core count.
- Stay correct when the cap is deliberately overridden. The CI benchmark job
  exports the real core count so it measures production-like throughput, so
  this asserts pool size *agrees with* the environment rather than pinning a
  literal 1.

Why this is a test and not a comment: the failure mode is silent. Dropping the
conftest line costs ~2.4x wall time and ~3 GB of peak memory on the reference
box with every test still green, so nothing else in the estate would notice.
"""

from __future__ import annotations

import os

import polars as pl


def test_polars_max_threads_is_set_for_the_test_session() -> None:
    """The cap is present in the environment of every worker."""
    # Arrange / Act
    configured = os.environ.get("POLARS_MAX_THREADS")

    # Assert
    assert configured is not None, (
        "POLARS_MAX_THREADS is unset. tests/conftest.py sets it via "
        "os.environ.setdefault before importing polars; without it every xdist "
        "worker starts a thread pool sized from the core count."
    )
    assert configured.isdigit() and int(configured) >= 1, (
        f"POLARS_MAX_THREADS must be a positive integer, got {configured!r}. "
        "Polars accepts 0 at import and then panics at compute time with "
        "'Worker threads cannot be set to 0'."
    )


def test_polars_thread_pool_honours_the_configured_cap() -> None:
    """The cap was applied before Polars built its pool, not after."""
    # Arrange
    configured = int(os.environ["POLARS_MAX_THREADS"])

    # Act
    actual = pl.thread_pool_size()

    # Assert
    assert actual == configured, (
        f"Polars thread pool is {actual} but POLARS_MAX_THREADS is {configured}. "
        "The variable is only read when Polars first initialises its pool, so "
        "this means something imported polars before tests/conftest.py set it."
    )
