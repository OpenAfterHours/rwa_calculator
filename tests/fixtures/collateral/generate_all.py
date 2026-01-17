"""
Generate all collateral test fixture parquet files.

Usage:
    uv run python tests/fixtures/collateral/generate_all.py
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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

    # Financial collateral by type
    print("\nFinancial Collateral (SA eligible):")
    fin_coll = collateral.filter(pl.col("is_eligible_financial_collateral"))
    if fin_coll.height > 0:
        by_type = fin_coll.group_by("collateral_type").agg(
            pl.col("market_value").sum().alias("total_value"),
            pl.len().alias("count"),
        ).sort("collateral_type")
        for row in by_type.iter_rows(named=True):
            print(f"  {row['collateral_type']}: {row['count']} items, £{row['total_value']:,.0f}")

    # Real estate analysis
    print("\nReal Estate Collateral:")
    re_coll = collateral.filter(pl.col("collateral_type") == "real_estate")
    if re_coll.height > 0:
        for row in re_coll.iter_rows(named=True):
            prop_type = row["property_type"]
            ltv = row["property_ltv"]
            ref = row["collateral_reference"]
            adc_status = ""
            if row["is_adc"]:
                adc_status = " (ADC-presold)" if row["is_presold"] else " (ADC)"
            income = " (income-producing)" if row["is_income_producing"] else ""
            print(f"  {ref}: {prop_type}, LTV={ltv:.0%}{adc_status}{income}")

    # CRM test scenarios
    print("\nCRM Test Scenarios:")

    # D1: Cash collateral
    cash_coll = collateral.filter(pl.col("collateral_type") == "cash")
    if cash_coll.height > 0:
        total_cash = cash_coll.select(pl.col("market_value").sum()).item()
        print(f"  D1 - Cash collateral: {cash_coll.height} items, £{total_cash:,.0f}")

    # D2: Government bonds
    govt_bonds = collateral.filter(
        (pl.col("collateral_type") == "bond") & (pl.col("issuer_type") == "sovereign")
    )
    if govt_bonds.height > 0:
        total_bonds = govt_bonds.select(pl.col("market_value").sum()).item()
        print(f"  D2 - Government bonds: {govt_bonds.height} items, £{total_bonds:,.0f}")

    # D3: Equity
    equity = collateral.filter(pl.col("collateral_type") == "equity")
    if equity.height > 0:
        total_equity = equity.select(pl.col("market_value").sum()).item()
        print(f"  D3 - Equity collateral: {equity.height} items, £{total_equity:,.0f}")

    # D5: Maturity mismatch
    mat_mismatch = collateral.filter(pl.col("collateral_reference").str.contains("MAT_MISMATCH"))
    if mat_mismatch.height > 0:
        print(f"  D5 - Maturity mismatch: {mat_mismatch.height} items")

    # D6: Currency mismatch
    ccy_mismatch = collateral.filter(pl.col("collateral_reference").str.contains("CCY_MISMATCH"))
    if ccy_mismatch.height > 0:
        print(f"  D6 - Currency mismatch: {ccy_mismatch.height} items")

    # Ineligible collateral
    inelig = collateral.filter(
        ~pl.col("is_eligible_financial_collateral") & ~pl.col("is_eligible_irb_collateral")
    )
    if inelig.height > 0:
        print(f"  Ineligible collateral (test exclusion): {inelig.height} items")

    print("=" * 70)


if __name__ == "__main__":
    main()
