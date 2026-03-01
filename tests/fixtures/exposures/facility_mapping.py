"""
Generate facility mapping fixtures for exposure hierarchy testing.

The output will be saved as `facility_mapping.parquet` ready to get picked up within the wider
testing process.

Facility mappings define parent-child relationships between:
    - Facilities and loans (facility -> loan)
    - Facilities and contingents (facility -> contingent)
    - Parent facilities and sub-facilities (facility -> facility)

This enables:
    - Aggregating drawn amounts at facility level
    - Calculating undrawn commitments (limit - drawn)
    - Multi-level facility hierarchies
    - Exposure hierarchy builder testing

Usage:
    uv run python tests/fixtures/exposures/facility_mapping.py
"""

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from rwa_calc.data.schemas import FACILITY_MAPPING_SCHEMA


def main() -> None:
    """Entry point for facility mapping generation."""
    output_path = save_facility_mappings()
    print_summary(output_path)


@dataclass(frozen=True)
class FacilityMapping:
    """A facility to child mapping."""

    parent_facility_reference: str
    child_reference: str
    child_type: str  # facility, loan, contingent

    def to_dict(self) -> dict:
        return {
            "parent_facility_reference": self.parent_facility_reference,
            "child_reference": self.child_reference,
            "child_type": self.child_type,
        }


def create_facility_mappings() -> pl.DataFrame:
    """
    Create facility mapping test data.

    Returns:
        pl.DataFrame: Facility mappings matching FACILITY_MAPPING_SCHEMA
    """
    mappings = [
        *_corporate_facility_mappings(),
        *_retail_facility_mappings(),
        *_hierarchy_test_mappings(),
    ]

    return pl.DataFrame([m.to_dict() for m in mappings], schema=FACILITY_MAPPING_SCHEMA)


def _corporate_facility_mappings() -> list[FacilityMapping]:
    """
    Mappings for corporate facilities to their loans.

    Standard facility -> loan relationships.
    """
    return [
        # FAC_CORP_001 (BP RCF) -> LOAN_FAC_CORP_001_A
        FacilityMapping("FAC_CORP_001", "LOAN_FAC_CORP_001_A", "loan"),
        # FAC_CORP_002 (Unilever term) -> LOAN_FAC_CORP_002_A
        FacilityMapping("FAC_CORP_002", "LOAN_FAC_CORP_002_A", "loan"),
        # FAC_CORP_SME_001 -> LOAN_FAC_SME_001_A
        FacilityMapping("FAC_CORP_SME_001", "LOAN_FAC_SME_001_A", "loan"),
    ]


def _retail_facility_mappings() -> list[FacilityMapping]:
    """
    Mappings for retail facilities to their loans.
    """
    return [
        # FAC_RTL_MTG_001 -> LOAN_RTL_MTG_001
        FacilityMapping("FAC_RTL_MTG_001", "LOAN_RTL_MTG_001", "loan"),
        # FAC_RTL_SME_001 -> LOAN_RTL_SME_001
        FacilityMapping("FAC_RTL_SME_001", "LOAN_RTL_SME_001", "loan"),
        # FAC_RTL_QRRE_001 -> LOAN_RTL_QRRE_001
        FacilityMapping("FAC_RTL_QRRE_001", "LOAN_RTL_QRRE_001", "loan"),
    ]


def _hierarchy_test_mappings() -> list[FacilityMapping]:
    """
    Mappings specifically for exposure hierarchy testing.

    Tests:
        - Multiple loans under single facility (H1 scenario)
        - Multi-level facility hierarchy (parent -> sub-facility -> loan)
        - Lending group facilities
        - Same reference pattern (facility_reference = loan_reference)
    """
    return [
        # =============================================================================
        # HIERARCHY TEST 1: Single facility with multiple loans
        # FAC_HIER_001 has 3 loans drawn against it
        # =============================================================================
        FacilityMapping("FAC_HIER_001", "LOAN_HIER_001_A", "loan"),
        FacilityMapping("FAC_HIER_001", "LOAN_HIER_001_B", "loan"),
        FacilityMapping("FAC_HIER_001", "LOAN_HIER_001_C", "loan"),
        # =============================================================================
        # HIERARCHY TEST 2: Multi-level facility hierarchy
        # Parent facility -> Sub-facilities -> Loans
        #
        # FAC_HIER_PARENT_001
        # ├── FAC_HIER_SUB_001 -> LOAN_HIER_SUB_001_A
        # └── FAC_HIER_SUB_002 -> LOAN_HIER_SUB_002_A
        # =============================================================================
        # Parent to sub-facilities
        FacilityMapping("FAC_HIER_PARENT_001", "FAC_HIER_SUB_001", "facility"),
        FacilityMapping("FAC_HIER_PARENT_001", "FAC_HIER_SUB_002", "facility"),
        # Sub-facilities to loans
        FacilityMapping("FAC_HIER_SUB_001", "LOAN_HIER_SUB_001_A", "loan"),
        FacilityMapping("FAC_HIER_SUB_002", "LOAN_HIER_SUB_002_A", "loan"),
        # =============================================================================
        # HIERARCHY TEST 3: Lending group facility mappings
        # =============================================================================
        FacilityMapping("FAC_LG2_OWNER", "LOAN_LG2_OWNER", "loan"),
        FacilityMapping("FAC_LG2_COMPANY", "LOAN_LG2_COMPANY", "loan"),
        # =============================================================================
        # HIERARCHY TEST 4: Same reference pattern
        # Facility and loan share the same reference ID - valid business pattern
        # when source systems use unified identifiers
        # =============================================================================
        FacilityMapping("SAME_REF_001", "SAME_REF_001", "loan"),
    ]


def save_facility_mappings(output_dir: Path | None = None) -> Path:
    """
    Create and save facility mappings to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures/exposures directory.

    Returns:
        Path: Path to the saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_facility_mappings()
    output_path = output_dir / "facility_mapping.parquet"
    df.write_parquet(output_path)

    return output_path


def print_summary(output_path: Path) -> None:
    """Print generation summary."""
    df = pl.read_parquet(output_path)

    print(f"Saved facility mappings to: {output_path}")
    print(f"\nCreated {len(df)} facility mappings:")

    print("\nBy child type:")
    type_counts = df.group_by("child_type").len().sort("child_type")
    for row in type_counts.iter_rows(named=True):
        print(f"  {row['child_type']}: {row['len']}")

    print("\nFacilities with multiple children:")
    multi_child = (
        df.group_by("parent_facility_reference")
        .len()
        .filter(pl.col("len") > 1)
        .sort("len", descending=True)
    )
    for row in multi_child.iter_rows(named=True):
        print(f"  {row['parent_facility_reference']}: {row['len']} children")

    print("\nHierarchy depth analysis:")
    # Find facilities that are also children (multi-level)
    parent_facilities = set(df.select("parent_facility_reference").to_series().to_list())
    child_facilities = set(
        df.filter(pl.col("child_type") == "facility")
        .select("child_reference")
        .to_series()
        .to_list()
    )
    intermediate = parent_facilities & child_facilities
    if intermediate:
        print(f"  Intermediate facilities (both parent and child): {intermediate}")
    else:
        print("  No multi-level facility hierarchies")


if __name__ == "__main__":
    main()
