"""
Generate organisation hierarchy mappings for counterparty rating inheritance testing.

The output will be saved as `org_mapping.parquet` ready to get picked up within the wider
testing process.

Organisation mappings define parent-child relationships between counterparties for:
    - Rating inheritance: Unrated subsidiaries inherit parent's external rating
    - Consolidated turnover: Group turnover aggregation for SME classification
    - Ultimate parent identification: Tracing to top of corporate hierarchy

Usage:
    uv run python tests/fixtures/mapping/org_mapping.py
"""

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from rwa_calc.data.schemas import ORG_MAPPING_SCHEMA


def main() -> None:
    """Entry point for org mapping generation."""
    output_path = save_org_mappings()
    print_summary(output_path)


@dataclass(frozen=True)
class OrgRelationship:
    """A parent-child organisation relationship."""

    parent: str
    child: str


def create_org_mappings() -> pl.DataFrame:
    """
    Create organisation hierarchy mappings for test counterparties.

    Returns:
        pl.DataFrame: Organisation mappings matching ORG_MAPPING_SCHEMA
    """
    relationships = [
        *_group1_single_level_hierarchy(),
        *_group2_multi_level_hierarchy(),
        *_group3_sme_turnover_aggregation(),
        *_complex_scenario_hierarchy(),
    ]

    return pl.DataFrame(
        [
            {"parent_counterparty_reference": r.parent, "child_counterparty_reference": r.child}
            for r in relationships
        ],
        schema=ORG_MAPPING_SCHEMA,
    )


def _group1_single_level_hierarchy() -> list[OrgRelationship]:
    """
    Group 1: Single-level hierarchy for rating inheritance.

    Alpha Holdings PLC (rated CQS 2) owns three unrated subsidiaries.
    Subsidiaries should inherit parent's rating for RW calculation.

    Structure:
        CORP_GRP1_PARENT (Alpha Holdings PLC)
        ├── CORP_GRP1_SUB1 (Alpha Manufacturing Ltd)
        ├── CORP_GRP1_SUB2 (Alpha Services Ltd)
        └── CORP_GRP1_SUB3 (Alpha Logistics Ltd)
    """
    parent = "CORP_GRP1_PARENT"
    return [
        OrgRelationship(parent, "CORP_GRP1_SUB1"),
        OrgRelationship(parent, "CORP_GRP1_SUB2"),
        OrgRelationship(parent, "CORP_GRP1_SUB3"),
    ]


def _group2_multi_level_hierarchy() -> list[OrgRelationship]:
    """
    Group 2: Multi-level hierarchy for transitive rating inheritance.

    Tests that rating inheritance works through intermediate holding companies.

    Structure:
        CORP_GRP2_ULTIMATE (Beta Group PLC) - rated
        └── CORP_GRP2_INTHOLD (Beta UK Holdings Ltd) - intermediate
            ├── CORP_GRP2_OPSUB1 (Beta Retail Operations Ltd)
            └── CORP_GRP2_OPSUB2 (Beta Online Ltd)
    """
    return [
        OrgRelationship("CORP_GRP2_ULTIMATE", "CORP_GRP2_INTHOLD"),
        OrgRelationship("CORP_GRP2_INTHOLD", "CORP_GRP2_OPSUB1"),
        OrgRelationship("CORP_GRP2_INTHOLD", "CORP_GRP2_OPSUB2"),
    ]


def _group3_sme_turnover_aggregation() -> list[OrgRelationship]:
    """
    Group 3: SME group for consolidated turnover testing.

    Tests that group turnover is aggregated for SME classification.
    Individual entities may qualify as SME but consolidated group may not.

    Structure:
        CORP_GRP3_PARENT (Gamma SME Holdings Ltd) - £30m revenue
        ├── CORP_GRP3_SUB1 (Gamma Engineering Ltd) - £15m revenue
        └── CORP_GRP3_SUB2 (Gamma Construction Ltd) - £20m revenue

    Consolidated turnover: £65m (still SME, under £440m threshold)
    """
    parent = "CORP_GRP3_PARENT"
    return [
        OrgRelationship(parent, "CORP_GRP3_SUB1"),
        OrgRelationship(parent, "CORP_GRP3_SUB2"),
    ]


def _complex_scenario_hierarchy() -> list[OrgRelationship]:
    """
    CRR-H2: Counterparty group for rating inheritance testing.

    Tests rating inheritance from rated parent to unrated subsidiaries.

    Structure:
        CORP_GRP_001 (Group Holdings Parent PLC) - rated CQS 2 (50% RW)
        ├── CORP_GRP_001_SUB1 (unrated) - inherits parent CQS 2
        └── CORP_GRP_001_SUB2 (rated CQS 3 = 100% RW) - uses own rating

    Rating inheritance rule:
        - Unrated subsidiary inherits parent's rating
        - Subsidiary with own rating uses its own rating
    """
    parent = "CORP_GRP_001"
    return [
        OrgRelationship(parent, "CORP_GRP_001_SUB1"),
        OrgRelationship(parent, "CORP_GRP_001_SUB2"),
    ]


def save_org_mappings(output_dir: Path | None = None) -> Path:
    """
    Create and save organisation mappings to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures/mapping directory.

    Returns:
        Path: Path to the saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_org_mappings()
    output_path = output_dir / "org_mapping.parquet"
    df.write_parquet(output_path)

    return output_path


def print_summary(output_path: Path) -> None:
    """Print generation summary."""
    df = pl.read_parquet(output_path)

    print(f"Saved organisation mappings to: {output_path}")
    print(f"\nCreated {len(df)} organisation relationships:")
    print(df)

    print("\nHierarchy summary:")
    parent_counts = (
        df.group_by("parent_counterparty_reference").len().sort("parent_counterparty_reference")
    )
    for row in parent_counts.iter_rows(named=True):
        print(f"  {row['parent_counterparty_reference']}: {row['len']} direct children")


if __name__ == "__main__":
    main()
