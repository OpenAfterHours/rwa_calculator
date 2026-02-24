"""
Benchmark testing module for RWA Calculator.

This module provides performance benchmarks to:
- Detect performance regressions early
- Validate scalability to production data volumes
- Track memory usage for large datasets

Usage:
    # Run all benchmarks
    uv run pytest tests/benchmarks/ --benchmark-only

    # Run specific scale
    uv run pytest tests/benchmarks/ -k "100k" --benchmark-only

    # Compare against baseline
    uv run pytest tests/benchmarks/ --benchmark-only --benchmark-compare=baseline

    # Save new baseline
    uv run pytest tests/benchmarks/ --benchmark-only --benchmark-save=baseline
"""
