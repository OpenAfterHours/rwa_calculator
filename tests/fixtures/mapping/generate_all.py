"""
Generate all mapping test fixture parquet files.

Usage:
    uv run python tests/fixtures/mapping/generate_all.py
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import polars as pl


def main() -> None:
    """Entry point for mapping fixture generation."""
    output_dir = Path(__file__).parent
    results = generate_all_mappings(output_dir)
    print_report(results, output_dir)


@dataclass
class GeneratorResult:
    """Result of a single mapping generator execution."""

    name: str
    dataframe: pl.DataFrame
    output_path: Path

    @property
    def record_count(self) -> int:
        return len(self.dataframe)

    @property
    def filename(self) -> str:
        return self.output_path.name


@dataclass
class MappingGenerator:
    """Configuration for a mapping type generator."""

    name: str
    create: Callable[[], pl.DataFrame]
    save: Callable[[Path], Path]

    def run(self, output_dir: Path) -> GeneratorResult:
        df = self.create()
        output_path = self.save(output_dir)
        return GeneratorResult(name=self.name, dataframe=df, output_path=output_path)


def get_generators() -> list[MappingGenerator]:
    """Return all configured mapping generators."""
    from org_mapping import create_org_mappings, save_org_mappings
    from lending_mapping import create_lending_mappings, save_lending_mappings

    return [
        MappingGenerator("Organisation Hierarchy", create_org_mappings, save_org_mappings),
        MappingGenerator("Lending Groups", create_lending_mappings, save_lending_mappings),
    ]


def generate_all_mappings(output_dir: Path) -> list[GeneratorResult]:
    """
    Generate all mapping parquet files.

    Args:
        output_dir: Directory to write parquet files to.

    Returns:
        List of generation results for each mapping type.
    """
    return [generator.run(output_dir) for generator in get_generators()]


def print_report(results: list[GeneratorResult], output_dir: Path) -> None:
    """Print generation report to stdout."""
    print_header(output_dir)
    print_generation_progress(results)
    print_summary(results)
    print_relationship_details(results)


def print_header(output_dir: Path) -> None:
    print("=" * 70)
    print("MAPPING FIXTURE GENERATOR")
    print("=" * 70)
    print(f"Output directory: {output_dir}\n")


def print_generation_progress(results: list[GeneratorResult]) -> None:
    for result in results:
        print(f"✓ {result.name}: {result.record_count} relationships -> {result.filename}")


def print_summary(results: list[GeneratorResult]) -> None:
    total_records = sum(r.record_count for r in results)

    print("\n" + "-" * 70)
    print("SUMMARY")
    print("-" * 70)

    for result in results:
        print(f"  {result.name:<25} {result.record_count:>5} relationships  ({result.filename})")

    print("-" * 70)
    print(f"  {'TOTAL':<25} {total_records:>5} relationships")
    print("=" * 70)


def print_relationship_details(results: list[GeneratorResult]) -> None:
    print("\nRelationship details:")

    for result in results:
        print(f"\n  {result.name}:")
        parent_counts = (
            result.dataframe.group_by("parent_counterparty_reference").len().sort("parent_counterparty_reference")
        )
        for row in parent_counts.iter_rows(named=True):
            print(f"    {row['parent_counterparty_reference']}: {row['len']} connected")


if __name__ == "__main__":
    main()
