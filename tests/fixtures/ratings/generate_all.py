"""
Generate all ratings test fixture parquet files.

Usage:
    uv run python tests/fixtures/ratings/generate_all.py
"""

from pathlib import Path

import polars as pl

from ratings import create_ratings, save_ratings


def main() -> None:
    """Entry point for ratings fixture generation."""
    output_dir = Path(__file__).parent
    df = create_ratings()
    output_path = save_ratings(output_dir)
    print_report(df, output_path)


def print_report(df: pl.DataFrame, output_path: Path) -> None:
    """Print generation report to stdout."""
    print("=" * 70)
    print("RATINGS FIXTURE GENERATOR")
    print("=" * 70)
    print(f"Output: {output_path}\n")

    print(f"✓ Created {len(df)} ratings\n")

    print("-" * 70)
    print("SUMMARY BY RATING TYPE")
    print("-" * 70)
    type_counts = df.group_by("rating_type").len().sort("rating_type")
    for row in type_counts.iter_rows(named=True):
        print(f"  {row['rating_type']:<15} {row['len']:>5} ratings")

    print("\n" + "-" * 70)
    print("EXTERNAL RATINGS BY CQS")
    print("-" * 70)
    external = df.filter(pl.col("rating_type") == "external")
    cqs_counts = external.group_by("cqs").len().sort("cqs")
    for row in cqs_counts.iter_rows(named=True):
        print(f"  CQS {row['cqs']}: {row['len']:>3} counterparties")

    print("\n" + "-" * 70)
    print("EXTERNAL RATINGS BY AGENCY")
    print("-" * 70)
    agency_counts = external.group_by("rating_agency").len().sort("rating_agency")
    for row in agency_counts.iter_rows(named=True):
        print(f"  {row['rating_agency']:<10} {row['len']:>3} ratings")

    print("\n" + "-" * 70)
    print("INTERNAL RATINGS PD DISTRIBUTION")
    print("-" * 70)
    internal = df.filter(pl.col("rating_type") == "internal")
    if len(internal) > 0:
        pd_stats = internal.select(
            pl.col("pd").min().alias("min"),
            pl.col("pd").max().alias("max"),
            pl.col("pd").mean().alias("mean"),
            pl.col("pd").median().alias("median"),
        ).row(0, named=True)
        print(f"  Min PD:    {pd_stats['min']:.4%}")
        print(f"  Max PD:    {pd_stats['max']:.4%}")
        print(f"  Mean PD:   {pd_stats['mean']:.4%}")
        print(f"  Median PD: {pd_stats['median']:.4%}")

    print("\n" + "-" * 70)
    print("COUNTERPARTY COVERAGE")
    print("-" * 70)
    unique_counterparties = df.select("counterparty_reference").unique()
    print(f"  Unique counterparties with ratings: {len(unique_counterparties)}")

    # Show counterparties with both external and internal ratings
    both = (
        df.group_by("counterparty_reference")
        .agg(pl.col("rating_type").n_unique().alias("type_count"))
        .filter(pl.col("type_count") > 1)
    )
    print(f"  Counterparties with both rating types: {len(both)}")

    print("=" * 70)


if __name__ == "__main__":
    main()
