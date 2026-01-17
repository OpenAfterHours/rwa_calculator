"""
Generate all counterparty test fixture parquet files.

Usage:
    uv run python tests/fixtures/counterparty/generate_all.py
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import polars as pl


def main() -> None:
    """Entry point for counterparty fixture generation."""
    output_dir = Path(__file__).parent
    results = generate_all_counterparties(output_dir)
    print_report(results, output_dir)


@dataclass
class GeneratorResult:
    """Result of a single counterparty generator execution."""

    name: str
    dataframe: pl.DataFrame
    output_path: Path

    @property
    def record_count(self) -> int:
        return len(self.dataframe)

    @property
    def filename(self) -> str:
        return self.output_path.name

    @property
    def reference_prefixes(self) -> list[str]:
        refs = self.dataframe.select("counterparty_reference").to_series().to_list()
        return sorted({self._extract_prefix(ref) for ref in refs})

    @staticmethod
    def _extract_prefix(reference: str) -> str:
        parts = reference.split("_")
        return f"{parts[0]}_{parts[1]}" if len(parts) >= 2 else reference


@dataclass
class CounterpartyGenerator:
    """Configuration for a counterparty type generator."""

    name: str
    create: Callable[[], pl.DataFrame]
    save: Callable[[Path], Path]

    def run(self, output_dir: Path) -> GeneratorResult:
        df = self.create()
        output_path = self.save(output_dir)
        return GeneratorResult(name=self.name, dataframe=df, output_path=output_path)


def get_generators() -> list[CounterpartyGenerator]:
    """Return all configured counterparty generators."""
    from sovereign import create_sovereign_counterparties, save_sovereign_counterparties
    from institution import create_institution_counterparties, save_institution_counterparties
    from corporate import create_corporate_counterparties, save_corporate_counterparties
    from retail import create_retail_counterparties, save_retail_counterparties
    from specialised_lending import (
        create_specialised_lending_counterparties,
        save_specialised_lending_counterparties,
    )

    return [
        CounterpartyGenerator("Sovereign", create_sovereign_counterparties, save_sovereign_counterparties),
        CounterpartyGenerator("Institution", create_institution_counterparties, save_institution_counterparties),
        CounterpartyGenerator("Corporate", create_corporate_counterparties, save_corporate_counterparties),
        CounterpartyGenerator("Retail", create_retail_counterparties, save_retail_counterparties),
        CounterpartyGenerator("Specialised Lending", create_specialised_lending_counterparties, save_specialised_lending_counterparties),
    ]


def generate_all_counterparties(output_dir: Path) -> list[GeneratorResult]:
    """
    Generate all counterparty parquet files.

    Args:
        output_dir: Directory to write parquet files to.

    Returns:
        List of generation results for each counterparty type.
    """
    return [generator.run(output_dir) for generator in get_generators()]


def print_report(results: list[GeneratorResult], output_dir: Path) -> None:
    """Print generation report to stdout."""
    print_header(output_dir)
    print_generation_progress(results)
    print_summary(results)
    print_schema_validation(results)
    print_reference_prefixes(results)


def print_header(output_dir: Path) -> None:
    print("=" * 70)
    print("COUNTERPARTY FIXTURE GENERATOR")
    print("=" * 70)
    print(f"Output directory: {output_dir}\n")


def print_generation_progress(results: list[GeneratorResult]) -> None:
    for result in results:
        print(f"✓ {result.name}: {result.record_count} counterparties -> {result.filename}")


def print_summary(results: list[GeneratorResult]) -> None:
    total_records = sum(r.record_count for r in results)

    print("\n" + "-" * 70)
    print("SUMMARY")
    print("-" * 70)

    for result in results:
        print(f"  {result.name:<25} {result.record_count:>5} records  ({result.filename})")

    print("-" * 70)
    print(f"  {'TOTAL':<25} {total_records:>5} records")
    print("=" * 70)


def print_schema_validation(results: list[GeneratorResult]) -> None:
    combined = pl.concat([r.dataframe for r in results])

    print("\nSchema validation:")
    print(f"  Combined DataFrame: {len(combined)} rows x {len(combined.columns)} columns")
    print(f"  Schema: {combined.schema}")


def print_reference_prefixes(results: list[GeneratorResult]) -> None:
    print("\nCounterparty reference prefixes:")
    for result in results:
        print(f"  {result.name}: {', '.join(result.reference_prefixes)}")


if __name__ == "__main__":
    main()
