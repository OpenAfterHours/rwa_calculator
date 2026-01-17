"""
Generate lending group mappings for retail exposure aggregation testing.

The output will be saved as `lending_mapping.parquet` ready to get picked up within the wider
testing process.

Lending mappings define connected party relationships for retail threshold testing:
    - Total exposure to connected group must be < £1m for retail classification
    - Connected parties include: spouses, business owners + their companies, family groups
    - If group exposure >= £1m, exposures must be treated as corporate (100% RW vs 75% RW)

Usage:
    uv run python tests/fixtures/mapping/lending_mapping.py
"""

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from rwa_calc.data.schemas import LENDING_MAPPING_SCHEMA


def main() -> None:
    """Entry point for lending mapping generation."""
    output_path = save_lending_mappings()
    print_summary(output_path)


@dataclass(frozen=True)
class LendingRelationship:
    """A connected party lending relationship."""

    parent: str
    child: str


def create_lending_mappings() -> pl.DataFrame:
    """
    Create lending group mappings for test counterparties.

    Returns:
        pl.DataFrame: Lending mappings matching LENDING_MAPPING_SCHEMA
    """
    relationships = [
        *_group1_married_couple(),
        *_group2_business_owner_company(),
        *_group3_family_business_group(),
        *_group4_boundary_threshold(),
        *_group5_over_threshold(),
    ]

    return pl.DataFrame(
        [{"parent_counterparty_reference": r.parent, "child_counterparty_reference": r.child} for r in relationships],
        schema=LENDING_MAPPING_SCHEMA,
    )


def _group1_married_couple() -> list[LendingRelationship]:
    """
    Lending Group 1: Married couple.

    Connected individuals whose exposures must aggregate for retail threshold.
    Tests basic two-party connected relationship.

    Structure:
        RTL_LG1_SPOUSE1 (David Wilson)
        └── RTL_LG1_SPOUSE2 (Emma Wilson)
    """
    return [
        LendingRelationship("RTL_LG1_SPOUSE1", "RTL_LG1_SPOUSE2"),
    ]


def _group2_business_owner_company() -> list[LendingRelationship]:
    """
    Lending Group 2: Business owner and their company.

    Individual's personal borrowing aggregates with their company's borrowing.
    Common scenario for sole traders and owner-managed businesses.

    Structure:
        RTL_LG2_OWNER (James Thompson)
        └── RTL_LG2_COMPANY (Thompson Plumbing Services)
    """
    return [
        LendingRelationship("RTL_LG2_OWNER", "RTL_LG2_COMPANY"),
    ]


def _group3_family_business_group() -> list[LendingRelationship]:
    """
    Lending Group 3: Family business group.

    Multiple family members with related small businesses.
    Tests multi-party aggregation within a connected group.

    Structure:
        RTL_LG3_PERSON1 (Thomas Green) - anchor
        ├── RTL_LG3_PERSON2 (Susan Green)
        ├── RTL_LG3_BIZ1 (Green's Bakery Ltd)
        └── RTL_LG3_BIZ2 (Green's Coffee Shop Ltd)
    """
    anchor = "RTL_LG3_PERSON1"
    return [
        LendingRelationship(anchor, "RTL_LG3_PERSON2"),
        LendingRelationship(anchor, "RTL_LG3_BIZ1"),
        LendingRelationship(anchor, "RTL_LG3_BIZ2"),
    ]


def _group4_boundary_threshold() -> list[LendingRelationship]:
    """
    Lending Group 4: Boundary threshold test.

    Group designed to have exactly £1m total exposure.
    Tests boundary condition - should still qualify as retail.

    Structure:
        RTL_LG4_PERSON (Boundary Test Individual)
        └── RTL_LG4_BIZ (Boundary Test Business Ltd)
    """
    return [
        LendingRelationship("RTL_LG4_PERSON", "RTL_LG4_BIZ"),
    ]


def _group5_over_threshold() -> list[LendingRelationship]:
    """
    Lending Group 5: Over threshold test.

    Group designed to exceed £1m total exposure.
    Individual exposures are small but aggregate > £1m.
    Should NOT qualify as retail - requires corporate treatment.

    Structure:
        RTL_LG5_PERSON (Over Threshold Individual)
        └── RTL_LG5_BIZ (Over Threshold Business Ltd)
    """
    return [
        LendingRelationship("RTL_LG5_PERSON", "RTL_LG5_BIZ"),
    ]


def save_lending_mappings(output_dir: Path | None = None) -> Path:
    """
    Create and save lending mappings to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures/mapping directory.

    Returns:
        Path: Path to the saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_lending_mappings()
    output_path = output_dir / "lending_mapping.parquet"
    df.write_parquet(output_path)

    return output_path


def print_summary(output_path: Path) -> None:
    """Print generation summary."""
    df = pl.read_parquet(output_path)

    print(f"Saved lending mappings to: {output_path}")
    print(f"\nCreated {len(df)} lending relationships:")
    print(df)

    print("\nLending group summary:")
    parent_counts = df.group_by("parent_counterparty_reference").len().sort("parent_counterparty_reference")
    for row in parent_counts.iter_rows(named=True):
        print(f"  {row['parent_counterparty_reference']}: {row['len']} connected parties")


if __name__ == "__main__":
    main()
