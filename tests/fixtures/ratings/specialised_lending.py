"""
Specialised lending metadata fixture for slotting approach testing.

Provides per-counterparty SL metadata (sl_type, slotting_category, is_hvcre)
that drives slotting classification in the pipeline. Keyed by counterparty_reference
so all exposures to an SL counterparty inherit the same slotting treatment.

References:
    - CRR Art. 147(8), Art. 153(5): Specialised lending slotting approach
    - BCBS CRE33: Supervisory slotting criteria
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from rwa_calc.data.schemas import SPECIALISED_LENDING_SCHEMA


def create_specialised_lending_data() -> pl.DataFrame:
    """
    Create specialised lending metadata for all SL counterparties in the fixture set.

    Returns:
        pl.DataFrame: SL metadata matching SPECIALISED_LENDING_SCHEMA
    """
    rows = [
        # --- General SL counterparties ---
        {
            "counterparty_reference": "SL_PF_001",
            "sl_type": "project_finance",
            "slotting_category": "strong",
            "is_hvcre": False,
        },
        {
            "counterparty_reference": "SL_PF_002",
            "sl_type": "project_finance",
            "slotting_category": "good",
            "is_hvcre": False,
        },
        {
            "counterparty_reference": "SL_PF_003",
            "sl_type": "project_finance",
            "slotting_category": "satisfactory",
            "is_hvcre": False,
        },
        {
            "counterparty_reference": "SL_PF_004",
            "sl_type": "project_finance",
            "slotting_category": "weak",
            "is_hvcre": False,
        },
        {
            "counterparty_reference": "SL_OF_001",
            "sl_type": "object_finance",
            "slotting_category": "good",
            "is_hvcre": False,
        },
        {
            "counterparty_reference": "SL_OF_002",
            "sl_type": "object_finance",
            "slotting_category": "satisfactory",
            "is_hvcre": False,
        },
        {
            "counterparty_reference": "SL_CF_001",
            "sl_type": "commodities_finance",
            "slotting_category": "strong",
            "is_hvcre": False,
        },
        {
            "counterparty_reference": "SL_CF_002",
            "sl_type": "commodities_finance",
            "slotting_category": "good",
            "is_hvcre": False,
        },
        {
            "counterparty_reference": "SL_IPRE_001",
            "sl_type": "ipre",
            "slotting_category": "strong",
            "is_hvcre": False,
        },
        {
            "counterparty_reference": "SL_IPRE_002",
            "sl_type": "ipre",
            "slotting_category": "satisfactory",
            "is_hvcre": False,
        },
        {
            "counterparty_reference": "SL_HVCRE_001",
            "sl_type": "hvcre",
            "slotting_category": "strong",
            "is_hvcre": True,
        },
        {
            "counterparty_reference": "SL_HVCRE_002",
            "sl_type": "hvcre",
            "slotting_category": "good",
            "is_hvcre": True,
        },
        {
            "counterparty_reference": "SL_ADC_001",
            "sl_type": "hvcre",
            "slotting_category": "satisfactory",
            "is_hvcre": True,
        },
        {
            "counterparty_reference": "SL_DF_001",
            "sl_type": "project_finance",
            "slotting_category": "default",
            "is_hvcre": False,
        },
        # --- CRR-E Slotting test scenario counterparties ---
        # E1: Project Finance - Strong (70% RW)
        {
            "counterparty_reference": "SL_PF_STRONG",
            "sl_type": "project_finance",
            "slotting_category": "strong",
            "is_hvcre": False,
        },
        # E2: Project Finance - Good (90% RW, >=2.5yr maturity)
        {
            "counterparty_reference": "SL_PF_GOOD",
            "sl_type": "project_finance",
            "slotting_category": "good",
            "is_hvcre": False,
        },
        # E3: IPRE - Weak (250% RW)
        {
            "counterparty_reference": "SL_IPRE_WEAK",
            "sl_type": "ipre",
            "slotting_category": "weak",
            "is_hvcre": False,
        },
        # E4: HVCRE - Strong (95% RW, >=2.5yr maturity)
        {
            "counterparty_reference": "SL_HVCRE_STRONG",
            "sl_type": "hvcre",
            "slotting_category": "strong",
            "is_hvcre": True,
        },
    ]

    return pl.DataFrame(rows, schema=SPECIALISED_LENDING_SCHEMA)


def save_specialised_lending_data(output_dir: Path | None = None) -> Path:
    """
    Create and save specialised lending metadata to parquet.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures directory.

    Returns:
        Path to the saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_specialised_lending_data()
    output_path = output_dir / "specialised_lending.parquet"
    df.write_parquet(output_path)

    return output_path


if __name__ == "__main__":
    output_path = save_specialised_lending_data()
    print(f"Saved specialised lending data to: {output_path}")

    df = pl.read_parquet(output_path)
    print(f"\nCreated {len(df)} specialised lending entries:")
    print(df)
