"""
Generate all provision test fixture parquet files.

Usage:
    uv run python tests/fixtures/provision/generate_all.py
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import polars as pl


def main() -> None:
    """Entry point for provision fixture generation."""
    output_dir = Path(__file__).parent
    results = generate_all_provisions(output_dir)
    print_report(results, output_dir)
    print_ifrs9_analysis(output_dir)


@dataclass
class GeneratorResult:
    """Result of a single provision generator execution."""

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
class ProvisionGenerator:
    """Configuration for a provision type generator."""

    name: str
    create: Callable[[], pl.DataFrame]
    save: Callable[[Path], Path]

    def run(self, output_dir: Path) -> GeneratorResult:
        df = self.create()
        output_path = self.save(output_dir)
        return GeneratorResult(name=self.name, dataframe=df, output_path=output_path)


def get_generators() -> list[ProvisionGenerator]:
    """Return all configured provision generators."""
    from provision import create_provisions, save_provisions

    return [
        ProvisionGenerator("Provisions", create_provisions, save_provisions),
    ]


def generate_all_provisions(output_dir: Path) -> list[GeneratorResult]:
    """
    Generate all provision parquet files.

    Args:
        output_dir: Directory to write parquet files to.

    Returns:
        List of generation results for each provision type.
    """
    return [generator.run(output_dir) for generator in get_generators()]


def print_report(results: list[GeneratorResult], output_dir: Path) -> None:
    """Print generation report to stdout."""
    print("=" * 70)
    print("PROVISION FIXTURE GENERATOR")
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


def print_ifrs9_analysis(output_dir: Path) -> None:
    """Print analysis of IFRS 9 staging and provision coverage."""
    provisions = pl.read_parquet(output_dir / "provision.parquet")

    print("\n" + "=" * 70)
    print("IFRS 9 STAGING ANALYSIS")
    print("=" * 70)

    # Stage breakdown
    print("\nProvision by IFRS 9 Stage:")
    for stage in [1, 2, 3]:
        stage_prov = provisions.filter(pl.col("ifrs9_stage") == stage)
        if stage_prov.height > 0:
            total = stage_prov.select(pl.col("amount").sum()).item()
            count = stage_prov.height
            stage_desc = {
                1: "12-month ECL (Performing)",
                2: "Lifetime ECL (Watch-list)",
                3: "Credit-impaired (Defaulted)",
            }
            print(f"  Stage {stage} - {stage_desc[stage]}:")
            print(f"    Count: {count}, Total: GBP {total:,.0f}")

    # SCRA vs GCRA
    print("\nSCRA vs GCRA:")
    scra = provisions.filter(pl.col("provision_type") == "SCRA")
    gcra = provisions.filter(pl.col("provision_type") == "GCRA")

    if scra.height > 0:
        total = scra.select(pl.col("amount").sum()).item()
        print(f"  Specific (SCRA): {scra.height} provisions, GBP {total:,.0f}")

    if gcra.height > 0:
        total = gcra.select(pl.col("amount").sum()).item()
        print(f"  General (GCRA): {gcra.height} provisions, GBP {total:,.0f}")

    # CRM test scenarios
    print("\nCRM Test Scenarios:")

    # H4: Full CRM chain
    crm_chain = provisions.filter(pl.col("provision_reference").str.contains("CRM_CHAIN"))
    if crm_chain.height > 0:
        total = crm_chain.select(pl.col("amount").sum()).item()
        print(f"  H4 - Full CRM chain provisions: {crm_chain.height}, GBP {total:,.0f}")

    # Defaulted exposure provisions
    stage3 = provisions.filter(pl.col("ifrs9_stage") == 3)
    if stage3.height > 0:
        total = stage3.select(pl.col("amount").sum()).item()
        print(f"  Defaulted exposure provisions (Stage 3): {stage3.height}, GBP {total:,.0f}")

    # Coverage by beneficiary type
    print("\nCoverage by Beneficiary Type:")
    by_ben = (
        provisions.group_by("beneficiary_type")
        .agg([
            pl.len().alias("count"),
            pl.col("amount").sum().alias("total"),
        ])
        .sort("beneficiary_type")
    )
    for row in by_ben.iter_rows(named=True):
        print(f"  {row['beneficiary_type']}: {row['count']} provisions, GBP {row['total']:,.0f}")

    print("=" * 70)


if __name__ == "__main__":
    main()
