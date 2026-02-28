"""
Generate all exposure test fixture parquet files.

Usage:
    uv run python tests/fixtures/exposures/generate_all.py
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import polars as pl


def main() -> None:
    """Entry point for exposure fixture generation."""
    output_dir = Path(__file__).parent
    results = generate_all_exposures(output_dir)
    print_report(results, output_dir)
    print_hierarchy_analysis(output_dir)


@dataclass
class GeneratorResult:
    """Result of a single exposure generator execution."""

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
class ExposureGenerator:
    """Configuration for an exposure type generator."""

    name: str
    create: Callable[[], pl.DataFrame]
    save: Callable[[Path], Path]

    def run(self, output_dir: Path) -> GeneratorResult:
        df = self.create()
        output_path = self.save(output_dir)
        return GeneratorResult(name=self.name, dataframe=df, output_path=output_path)


def get_generators() -> list[ExposureGenerator]:
    """Return all configured exposure generators."""
    from contingents import create_contingents, save_contingents
    from facilities import create_facilities, save_facilities
    from facility_mapping import create_facility_mappings, save_facility_mappings
    from loans import create_loans, save_loans

    return [
        ExposureGenerator("Facilities", create_facilities, save_facilities),
        ExposureGenerator("Loans", create_loans, save_loans),
        ExposureGenerator("Contingents", create_contingents, save_contingents),
        ExposureGenerator("Facility Mappings", create_facility_mappings, save_facility_mappings),
    ]


def generate_all_exposures(output_dir: Path) -> list[GeneratorResult]:
    """
    Generate all exposure parquet files.

    Args:
        output_dir: Directory to write parquet files to.

    Returns:
        List of generation results for each exposure type.
    """
    return [generator.run(output_dir) for generator in get_generators()]


def print_report(results: list[GeneratorResult], output_dir: Path) -> None:
    """Print generation report to stdout."""
    print("=" * 70)
    print("EXPOSURE FIXTURE GENERATOR")
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


def print_hierarchy_analysis(output_dir: Path) -> None:
    """Print analysis of exposure hierarchy relationships."""
    facilities = pl.read_parquet(output_dir / "facilities.parquet")
    loans = pl.read_parquet(output_dir / "loans.parquet")
    mappings = pl.read_parquet(output_dir / "facility_mapping.parquet")

    print("\n" + "=" * 70)
    print("EXPOSURE HIERARCHY ANALYSIS")
    print("=" * 70)

    # Facilities with loans
    facility_refs = set(facilities.select("facility_reference").to_series().to_list())
    mapped_facilities = set(mappings.select("parent_facility_reference").to_series().to_list())
    unmapped_facilities = facility_refs - mapped_facilities

    print(f"\nFacilities: {len(facilities)}")
    print(f"  With mapped children: {len(mapped_facilities)}")
    print(f"  Without mapped children: {len(unmapped_facilities)}")

    # Loans analysis
    loan_refs = set(loans.select("loan_reference").to_series().to_list())
    mapped_loans = set(
        mappings.filter(pl.col("child_type") == "loan")
        .select("child_reference")
        .to_series()
        .to_list()
    )
    standalone_loans = loan_refs - mapped_loans

    print(f"\nLoans: {len(loans)}")
    print(f"  Under facilities: {len(mapped_loans)}")
    print(f"  Standalone: {len(standalone_loans)}")

    # Exposure totals
    total_limit = facilities.select(pl.col("limit").sum()).item()
    total_drawn = loans.select(pl.col("drawn_amount").sum()).item()

    print("\nExposure Totals:")
    print(f"  Total facility limits: £{total_limit:,.0f}")
    print(f"  Total loans drawn: £{total_drawn:,.0f}")

    # Multi-level hierarchy
    child_facilities = set(
        mappings.filter(pl.col("child_type") == "facility")
        .select("child_reference")
        .to_series()
        .to_list()
    )
    if child_facilities:
        print("\nMulti-level hierarchy:")
        print(f"  Sub-facilities: {child_facilities}")

    # Hierarchy test scenarios
    print("\nHierarchy Test Scenarios:")

    # H1: Single facility with multiple loans
    hier_001_loans = mappings.filter(pl.col("parent_facility_reference") == "FAC_HIER_001")
    if len(hier_001_loans) > 0:
        loan_count = len(hier_001_loans)
        loan_refs = hier_001_loans.select("child_reference").to_series().to_list()
        total_drawn_h1 = (
            loans.filter(pl.col("loan_reference").is_in(loan_refs))
            .select(pl.col("drawn_amount").sum())
            .item()
        )
        facility_limit = (
            facilities.filter(pl.col("facility_reference") == "FAC_HIER_001").select("limit").item()
        )
        print("  H1 - Multiple loans under facility:")
        print(
            f"       FAC_HIER_001: {loan_count} loans, £{total_drawn_h1:,.0f} drawn of £{facility_limit:,.0f} limit"
        )

    # H2: Multi-level hierarchy
    parent_001 = mappings.filter(pl.col("parent_facility_reference") == "FAC_HIER_PARENT_001")
    if len(parent_001) > 0:
        sub_facs = (
            parent_001.filter(pl.col("child_type") == "facility")
            .select("child_reference")
            .to_series()
            .to_list()
        )
        print("  H2 - Multi-level facility hierarchy:")
        print(f"       FAC_HIER_PARENT_001 -> {sub_facs}")

    print("=" * 70)


if __name__ == "__main__":
    main()
