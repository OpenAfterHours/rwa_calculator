"""
Generate all guarantee test fixture parquet files.

Usage:
    uv run python tests/fixtures/guarantee/generate_all.py
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import polars as pl


def main() -> None:
    """Entry point for guarantee fixture generation."""
    output_dir = Path(__file__).parent
    results = generate_all_guarantees(output_dir)
    print_report(results, output_dir)
    print_guarantor_analysis(output_dir)


@dataclass
class GeneratorResult:
    """Result of a single guarantee generator execution."""

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
class GuaranteeGenerator:
    """Configuration for a guarantee type generator."""

    name: str
    create: Callable[[], pl.DataFrame]
    save: Callable[[Path], Path]

    def run(self, output_dir: Path) -> GeneratorResult:
        df = self.create()
        output_path = self.save(output_dir)
        return GeneratorResult(name=self.name, dataframe=df, output_path=output_path)


def get_generators() -> list[GuaranteeGenerator]:
    """Return all configured guarantee generators."""
    from guarantee import create_guarantees, save_guarantees

    return [
        GuaranteeGenerator("Guarantees", create_guarantees, save_guarantees),
    ]


def generate_all_guarantees(output_dir: Path) -> list[GeneratorResult]:
    """
    Generate all guarantee parquet files.

    Args:
        output_dir: Directory to write parquet files to.

    Returns:
        List of generation results for each guarantee type.
    """
    return [generator.run(output_dir) for generator in get_generators()]


def print_report(results: list[GeneratorResult], output_dir: Path) -> None:
    """Print generation report to stdout."""
    print("=" * 70)
    print("GUARANTEE FIXTURE GENERATOR")
    print("=" * 70)
    print(f"Output directory: {output_dir}\n")

    for result in results:
        print(f"[OK] {result.name}: {result.record_count} records -> {result.filename}")

    print("\n" + "-" * 70)
    print("SUMMARY")
    print("-" * 70)

    total_records = sum(r.record_count for r in results)
    for result in results:
        print(f"  {result.name:<20} {result.record_count:>5} records  ({result.filename})")

    print("-" * 70)
    print(f"  {'TOTAL':<20} {total_records:>5} records")
    print("=" * 70)


def print_guarantor_analysis(output_dir: Path) -> None:
    """Print analysis of guarantor types and substitution scenarios."""
    guarantees = pl.read_parquet(output_dir / "guarantee.parquet")

    print("\n" + "=" * 70)
    print("GUARANTOR ANALYSIS")
    print("=" * 70)

    # By guarantor type (based on reference prefix)
    print("\nBy guarantor category:")

    sovereign_guar = guarantees.filter(pl.col("guarantor").str.starts_with("SOV_"))
    institution_guar = guarantees.filter(pl.col("guarantor").str.starts_with("INST_"))
    corporate_guar = guarantees.filter(pl.col("guarantor").str.starts_with("CORP_"))

    if sovereign_guar.height > 0:
        total = sovereign_guar.select(pl.col("amount_covered").sum()).item()
        print(f"  Sovereign guarantors: {sovereign_guar.height} guarantees, total {total:,.0f}")

    if institution_guar.height > 0:
        total = institution_guar.select(pl.col("amount_covered").sum()).item()
        print(f"  Institution guarantors: {institution_guar.height} guarantees, total {total:,.0f}")

    if corporate_guar.height > 0:
        total = corporate_guar.select(pl.col("amount_covered").sum()).item()
        print(f"  Corporate guarantors: {corporate_guar.height} guarantees, total {total:,.0f}")

    # Substitution scenarios
    print("\nSubstitution Scenarios:")

    # D4: Bank guarantee on corporate
    d4_guar = guarantees.filter(pl.col("guarantee_reference") == "GUAR_BANK_001")
    if d4_guar.height > 0:
        row = d4_guar.row(0, named=True)
        print("  D4 - Bank guarantee substitution:")
        print(
            f"       {row['guarantor']} guarantees {row['percentage_covered']:.0%} of {row['beneficiary_reference']}"
        )

    # H4: Full CRM chain
    h4_guar = guarantees.filter(pl.col("guarantee_reference").str.contains("CRM_CHAIN"))
    if h4_guar.height > 0:
        print(f"  H4 - Full CRM chain guarantees: {h4_guar.height}")

    # Maturity mismatch
    mat_mismatch = guarantees.filter(pl.col("guarantee_reference").str.contains("MAT_MISMATCH"))
    if mat_mismatch.height > 0:
        print(f"  Maturity mismatch scenarios: {mat_mismatch.height}")

    # Currency mismatch
    ccy_mismatch = guarantees.filter(pl.col("guarantee_reference").str.contains("CCY_MISMATCH"))
    if ccy_mismatch.height > 0:
        print(f"  Currency mismatch scenarios: {ccy_mismatch.height}")

    # Coverage analysis
    print("\nCoverage Analysis:")
    coverage_stats = guarantees.select(
        [
            pl.col("percentage_covered").min().alias("min_coverage"),
            pl.col("percentage_covered").max().alias("max_coverage"),
            pl.col("percentage_covered").mean().alias("avg_coverage"),
        ]
    ).row(0, named=True)

    print(f"  Min coverage: {coverage_stats['min_coverage']:.0%}")
    print(f"  Max coverage: {coverage_stats['max_coverage']:.0%}")
    print(f"  Avg coverage: {coverage_stats['avg_coverage']:.0%}")

    print("=" * 70)


if __name__ == "__main__":
    main()
