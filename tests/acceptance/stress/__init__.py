"""
Stress tests for pipeline correctness at scale.

Pipeline position:
    These tests validate end-to-end pipeline correctness with large datasets.
    Unlike benchmarks (which measure timing), stress tests assert on correctness
    properties: row counts, numerical stability, approach distribution, and
    regulatory bound compliance.

Key responsibilities:
- Verify N input exposures produce N output rows at 10K+ scale
- Confirm risk weights stay within regulatory bounds (0% to 1250%)
- Check numerical stability (no NaN/inf in RWA, finite sums)
- Validate approach distribution matches entity type mix
- Test Basel 3.1 output floor at portfolio level with many exposures

Usage:
    # Run stress tests (10K scale, included in normal suite)
    uv run pytest tests/acceptance/stress/ --benchmark-skip

    # Run including slow tests (100K scale)
    uv run pytest tests/acceptance/stress/ --benchmark-skip -m ""
"""
