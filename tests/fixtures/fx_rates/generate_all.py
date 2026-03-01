"""
Generate all FX rates fixtures.

Usage:
    uv run python tests/fixtures/fx_rates/generate_all.py
"""

from pathlib import Path

from fx_rates import create_fx_rates, save_fx_rates


def main() -> None:
    """Generate all FX rate fixtures."""
    output_dir = Path(__file__).parent

    print("=" * 60)
    print("FX RATES FIXTURE GENERATOR")
    print("=" * 60)
    print(f"Output directory: {output_dir}\n")

    df = create_fx_rates()
    save_fx_rates(output_dir)

    print(f"[OK] fx_rates.parquet: {len(df)} records")
    print("=" * 60)


if __name__ == "__main__":
    main()
