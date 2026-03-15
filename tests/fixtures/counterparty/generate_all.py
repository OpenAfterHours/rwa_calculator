"""
Generate consolidated counterparty test fixture parquet file.

Combines all counterparty types (sovereign, institution, corporate, retail,
specialised lending) into a single counterparties.parquet file.

Usage:
    uv run python tests/fixtures/counterparty/generate_all.py
"""

from pathlib import Path

import polars as pl


def main() -> None:
    """Entry point for counterparty fixture generation."""
    output_dir = Path(__file__).parent
    df = generate_all_counterparties()
    output_path = output_dir / "counterparties.parquet"
    df.write_parquet(output_path)
    print_report(df, output_path)


def generate_all_counterparties() -> pl.DataFrame:
    """
    Generate consolidated counterparty DataFrame from all type generators.

    Returns:
        Combined DataFrame of all counterparty types.
    """
    from corporate import create_corporate_counterparties
    from institution import create_institution_counterparties
    from retail import create_retail_counterparties
    from sovereign import create_sovereign_counterparties
    from specialised_lending import create_specialised_lending_counterparties

    frames = [
        create_sovereign_counterparties(),
        create_institution_counterparties(),
        create_corporate_counterparties(),
        create_retail_counterparties(),
        create_specialised_lending_counterparties(),
    ]

    return pl.concat(frames)


def print_report(df: pl.DataFrame, output_path: Path) -> None:
    """Print generation report to stdout."""
    print("=" * 70)
    print("COUNTERPARTY FIXTURE GENERATOR")
    print("=" * 70)
    print(f"Output: {output_path}")
    print(f"Total: {len(df)} counterparties")
    print(f"Schema: {df.schema}")

    # Entity type breakdown
    if "entity_type" in df.columns:
        print("\nEntity type breakdown:")
        for row in df.group_by("entity_type").len().sort("entity_type").iter_rows(named=True):
            print(f"  {row['entity_type']:<25} {row['len']:>5} records")

    # Reference prefixes
    print("\nCounterparty reference prefixes:")
    refs = df.select("counterparty_reference").to_series().to_list()
    prefixes = sorted({_extract_prefix(ref) for ref in refs})
    for prefix in prefixes:
        print(f"  {prefix}")

    print("=" * 70)


def _extract_prefix(reference: str) -> str:
    parts = reference.split("_")
    return f"{parts[0]}_{parts[1]}" if len(parts) >= 2 else reference


if __name__ == "__main__":
    main()
