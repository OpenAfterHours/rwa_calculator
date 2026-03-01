"""
Generate FX rates for test fixtures.

FX rates are used to convert exposure amounts from their original currencies
to a reporting currency (default: GBP). The rate represents a multiplier:
    amount_in_target = amount_in_source * rate

Example rates (approximate as of Jan 2026):
    USD to GBP: 0.79 (1 USD = 0.79 GBP)
    EUR to GBP: 0.8732 (1 EUR = 0.8732 GBP, i.e. 1 GBP = 1.14523 EUR)
    GBP to GBP: 1.00 (identity)

Usage:
    uv run python tests/fixtures/fx_rates/fx_rates.py
"""

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from rwa_calc.data.schemas import FX_RATES_SCHEMA


def main() -> None:
    """Entry point for FX rates generation."""
    output_path = save_fx_rates()
    print_summary(output_path)


@dataclass(frozen=True)
class FXRate:
    """An FX rate conversion entry."""

    currency_from: str
    currency_to: str
    rate: float

    def to_dict(self) -> dict:
        return {
            "currency_from": self.currency_from,
            "currency_to": self.currency_to,
            "rate": self.rate,
        }


def create_fx_rates() -> pl.DataFrame:
    """
    Create FX rates for currency conversion testing.

    Includes rates for common currencies to GBP (the default reporting currency).
    Also includes rates to EUR and USD for testing alternative base currencies.

    Returns:
        pl.DataFrame: FX rates matching FX_RATES_SCHEMA
    """
    rates = [
        # Rates TO GBP (default reporting currency)
        FXRate("GBP", "GBP", 1.0),  # Identity rate
        FXRate("USD", "GBP", 0.79),  # 1 USD = 0.79 GBP
        FXRate("EUR", "GBP", 0.88),  # 1 EUR = 0.88 GBP (used for CRR threshold conversions)
        FXRate("JPY", "GBP", 0.0053),  # 1 JPY = 0.0053 GBP
        FXRate("CHF", "GBP", 0.89),  # 1 CHF = 0.89 GBP
        FXRate("AUD", "GBP", 0.52),  # 1 AUD = 0.52 GBP
        FXRate("CAD", "GBP", 0.58),  # 1 CAD = 0.58 GBP
        FXRate("CNY", "GBP", 0.11),  # 1 CNY = 0.11 GBP
        FXRate("HKD", "GBP", 0.10),  # 1 HKD = 0.10 GBP
        FXRate("SGD", "GBP", 0.59),  # 1 SGD = 0.59 GBP
        # Rates TO EUR (alternative reporting currency)
        FXRate("GBP", "EUR", 1.14),  # 1 GBP = 1.14 EUR
        FXRate("EUR", "EUR", 1.0),  # Identity rate
        FXRate("USD", "EUR", 0.90),  # 1 USD = 0.90 EUR
        # Rates TO USD (alternative reporting currency)
        FXRate("GBP", "USD", 1.27),  # 1 GBP = 1.27 USD
        FXRate("EUR", "USD", 1.11),  # 1 EUR = 1.11 USD
        FXRate("USD", "USD", 1.0),  # Identity rate
    ]

    return pl.DataFrame([r.to_dict() for r in rates], schema=FX_RATES_SCHEMA)


def save_fx_rates(output_dir: Path | None = None) -> Path:
    """
    Create and save FX rates to parquet format.

    Args:
        output_dir: Directory to save the parquet file. Defaults to fixtures/fx_rates directory.

    Returns:
        Path: Path to the saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_fx_rates()
    output_path = output_dir / "fx_rates.parquet"
    df.write_parquet(output_path)

    return output_path


def print_summary(output_path: Path) -> None:
    """Print generation summary."""
    df = pl.read_parquet(output_path)

    print(f"Saved FX rates to: {output_path}")
    print(f"\nCreated {len(df)} FX rates:")

    print("\nRates by target currency:")
    target_counts = df.group_by("currency_to").len().sort("currency_to")
    for row in target_counts.iter_rows(named=True):
        print(f"  To {row['currency_to']}: {row['len']} rates")

    print("\nSample rates to GBP:")
    gbp_rates = df.filter(pl.col("currency_to") == "GBP").sort("currency_from")
    for row in gbp_rates.iter_rows(named=True):
        print(f"  {row['currency_from']} -> GBP: {row['rate']:.4f}")


if __name__ == "__main__":
    main()
