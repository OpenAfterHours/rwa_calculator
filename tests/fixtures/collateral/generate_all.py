"""
Generate all collateral test fixture parquet files.

Usage:
    uv run python tests/fixtures/collateral/generate_all.py
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import polars as pl


def main() -> None:
    """Entry point for collateral fixture generation."""
    output_dir = Path(__file__).parent
    results = generate_all_collateral(output_dir)
    print_report(results, output_dir)
    print_crm_scenario_analysis(output_dir)


@dataclass
class GeneratorResult:
    """Result of a single collateral generator execution."""

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
class CollateralGenerator:
    """Configuration for a collateral type generator."""

    name: str
    create: Callable[[], pl.DataFrame]
    save: Callable[[Path], Path]

    def run(self, output_dir: Path) -> GeneratorResult:
        df = self.create()
        output_path = self.save(output_dir)
        return GeneratorResult(name=self.name, dataframe=df, output_path=output_path)


def get_generators() -> list[CollateralGenerator]:
    """Return all configured collateral generators."""
    from collateral import create_collateral, save_collateral

    return [
        CollateralGenerator("Collateral", create_collateral, save_collateral),
    ]


def generate_all_collateral(output_dir: Path) -> list[GeneratorResult]:
    """
    Generate all collateral parquet files.

    Args:
        output_dir: Directory to write parquet files to.

    Returns:
        List of generation results for each collateral type.
    """
    return [generator.run(output_dir) for generator in get_generators()]


def print_report(results: list[GeneratorResult], output_dir: Path) -> None:
    """Print generation report to stdout."""
    print("=" * 70)
    print("COLLATERAL FIXTURE GENERATOR")
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


def print_crm_scenario_analysis(output_dir: Path) -> None:
    """Print analysis of CRM test scenarios covered."""
    collateral = pl.read_parquet(output_dir / "collateral.parquet")

    print("\n" + "=" * 70)
    print("CRM SCENARIO ANALYSIS")
    print("=" * 70)

    _print_financial_collateral(collateral)
    _print_real_estate_collateral(collateral)
    _print_crm_test_scenarios(collateral)

    print("=" * 70)


def _print_financial_collateral(collateral: pl.DataFrame) -> None:
    """Print the SA-eligible financial collateral breakdown by type."""
    print("\nFinancial Collateral (SA eligible):")
    fin_coll = collateral.filter(pl.col("is_eligible_financial_collateral"))
    if fin_coll.height == 0:
        return

    by_type = (
        fin_coll.group_by("collateral_type")
        .agg(
            pl.col("market_value").sum().alias("total_value"),
            pl.len().alias("count"),
        )
        .sort("collateral_type")
    )
    for row in by_type.iter_rows(named=True):
        print(f"  {row['collateral_type']}: {row['count']} items, £{row['total_value']:,.0f}")


def _print_real_estate_collateral(collateral: pl.DataFrame) -> None:
    """Print the per-item real-estate collateral analysis."""
    print("\nReal Estate Collateral:")
    re_coll = collateral.filter(pl.col("collateral_type") == "real_estate")
    for row in re_coll.iter_rows(named=True):
        adc_status = _adc_status_label(row)
        income = " (income-producing)" if row["is_income_producing"] else ""
        print(
            f"  {row['collateral_reference']}: {row['property_type']}, "
            f"LTV={row['property_ltv']:.0%}{adc_status}{income}"
        )


def _adc_status_label(row: dict[str, object]) -> str:
    """Return the ADC status suffix for a real-estate collateral row."""
    if not row["is_adc"]:
        return ""
    return " (ADC-presold)" if row["is_presold"] else " (ADC)"


def _print_crm_test_scenarios(collateral: pl.DataFrame) -> None:
    """Print the labelled CRM test scenarios (cash, bonds, equity, mismatches)."""
    print("\nCRM Test Scenarios:")

    _print_valued_scenario(
        collateral.filter(pl.col("collateral_type") == "cash"),
        "D1 - Cash collateral",
    )
    _print_valued_scenario(
        collateral.filter(
            (pl.col("collateral_type") == "bond") & (pl.col("issuer_type") == "sovereign")
        ),
        "D2 - Government bonds",
    )
    _print_valued_scenario(
        collateral.filter(pl.col("collateral_type") == "equity"),
        "D3 - Equity collateral",
    )
    _print_count_scenario(
        collateral.filter(pl.col("collateral_reference").str.contains("MAT_MISMATCH")),
        "D5 - Maturity mismatch",
    )
    _print_count_scenario(
        collateral.filter(pl.col("collateral_reference").str.contains("CCY_MISMATCH")),
        "D6 - Currency mismatch",
    )
    _print_count_scenario(
        collateral.filter(
            ~pl.col("is_eligible_financial_collateral") & ~pl.col("is_eligible_irb_collateral")
        ),
        "Ineligible collateral (test exclusion)",
    )


def _print_valued_scenario(subset: pl.DataFrame, label: str) -> None:
    """Print a scenario line with item count and summed market value."""
    if subset.height == 0:
        return
    total = subset.select(pl.col("market_value").sum()).item()
    print(f"  {label}: {subset.height} items, £{total:,.0f}")


def _print_count_scenario(subset: pl.DataFrame, label: str) -> None:
    """Print a scenario line with item count only."""
    if subset.height == 0:
        return
    print(f"  {label}: {subset.height} items")


if __name__ == "__main__":
    main()
