"""
FX conversion module for RWA calculator.

Provides currency conversion functionality to convert exposure amounts
from their original currencies to a configurable reporting currency.

Classes:
    FXConverter: Main converter for applying FX rates to exposures and CRM data

Usage:
    from rwa_calc.engine.fx_converter import FXConverter

    converter = FXConverter()
    exposures = converter.convert_exposures(exposures, fx_rates, config)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)


class FXConverter:
    """
    Convert exposure and CRM amounts to reporting currency.

    Applies FX rates to convert amounts from their original currencies
    to the configured base currency (default: GBP). Preserves original
    values in audit trail columns.

    Key features:
    - Converts drawn_amount, undrawn_amount, nominal_amount for exposures
    - Converts collateral market_value and nominal_value
    - Converts guarantee amount_covered
    - Converts provision amount
    - Preserves original values for audit trail
    - Handles missing FX rates gracefully (keeps original currency)
    """

    def convert_exposures(
        self,
        exposures: pl.LazyFrame,
        fx_rates: pl.LazyFrame | None,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Convert exposure amounts to reporting currency.

        Args:
            exposures: Unified exposures with currency and amount columns
            fx_rates: FX rates with currency_from, currency_to, rate columns
            config: Calculation configuration with base_currency

        Returns:
            Exposures with amounts converted and audit trail columns added:
            - original_currency: Currency before conversion
            - original_amount: Total amount before conversion
            - fx_rate_applied: Rate used for conversion (null if none)
        """
        if fx_rates is None or not config.apply_fx_conversion:
            # No FX rates or conversion disabled - add null audit columns
            return exposures.with_columns([
                pl.col("currency").alias("original_currency"),
                (pl.col("drawn_amount") + pl.col("interest").fill_null(0.0) + pl.col("nominal_amount")).alias("original_amount"),
                pl.lit(None).cast(pl.Float64).alias("fx_rate_applied"),
            ])

        target_currency = config.base_currency

        # Filter FX rates to only those targeting our base currency
        rates_to_target = fx_rates.filter(
            pl.col("currency_to") == target_currency
        ).select([
            pl.col("currency_from"),
            pl.col("rate"),
        ])

        # Join exposures with FX rates on currency
        converted = exposures.join(
            rates_to_target,
            left_on="currency",
            right_on="currency_from",
            how="left",
        )

        # Apply conversion with audit trail
        converted = converted.with_columns([
            # Preserve original currency
            pl.col("currency").alias("original_currency"),
            # Preserve original total amount (including accrued interest)
            (pl.col("drawn_amount") + pl.col("interest").fill_null(0.0) + pl.col("nominal_amount")).alias("original_amount"),
            # Track rate applied (null if same currency or no rate)
            pl.when(pl.col("currency") == target_currency)
            .then(pl.lit(None).cast(pl.Float64))
            .otherwise(pl.col("rate"))
            .alias("fx_rate_applied"),
        ])

        # Convert amounts where rate is available
        # If currency matches target or no rate found, keep original amounts
        converted = converted.with_columns([
            pl.when(pl.col("currency") == target_currency)
            .then(pl.col("drawn_amount"))
            .when(pl.col("rate").is_not_null())
            .then(pl.col("drawn_amount") * pl.col("rate"))
            .otherwise(pl.col("drawn_amount"))
            .alias("drawn_amount"),

            pl.when(pl.col("currency") == target_currency)
            .then(pl.col("undrawn_amount"))
            .when(pl.col("rate").is_not_null())
            .then(pl.col("undrawn_amount") * pl.col("rate"))
            .otherwise(pl.col("undrawn_amount"))
            .alias("undrawn_amount"),

            pl.when(pl.col("currency") == target_currency)
            .then(pl.col("nominal_amount"))
            .when(pl.col("rate").is_not_null())
            .then(pl.col("nominal_amount") * pl.col("rate"))
            .otherwise(pl.col("nominal_amount"))
            .alias("nominal_amount"),

            # Convert interest (nullable - preserve nulls through conversion)
            pl.when(pl.col("interest").is_null())
            .then(pl.lit(None).cast(pl.Float64))
            .when(pl.col("currency") == target_currency)
            .then(pl.col("interest"))
            .when(pl.col("rate").is_not_null())
            .then(pl.col("interest") * pl.col("rate"))
            .otherwise(pl.col("interest"))
            .alias("interest"),

            # Update currency to target where conversion applied
            pl.when(pl.col("currency") == target_currency)
            .then(pl.col("currency"))
            .when(pl.col("rate").is_not_null())
            .then(pl.lit(target_currency))
            .otherwise(pl.col("currency"))
            .alias("currency"),
        ])

        # Drop the temporary rate column from join
        converted = converted.drop("rate")

        return converted

    def convert_collateral(
        self,
        collateral: pl.LazyFrame,
        fx_rates: pl.LazyFrame | None,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Convert collateral values to reporting currency.

        Args:
            collateral: Collateral with currency, market_value, nominal_value
            fx_rates: FX rates with currency_from, currency_to, rate columns
            config: Calculation configuration with base_currency

        Returns:
            Collateral with values converted to base currency
        """
        if fx_rates is None or not config.apply_fx_conversion:
            return collateral

        target_currency = config.base_currency

        # Filter FX rates to only those targeting our base currency
        rates_to_target = fx_rates.filter(
            pl.col("currency_to") == target_currency
        ).select([
            pl.col("currency_from"),
            pl.col("rate"),
        ])

        # Join collateral with FX rates on currency
        converted = collateral.join(
            rates_to_target,
            left_on="currency",
            right_on="currency_from",
            how="left",
        )

        # Convert amounts where rate is available
        converted = converted.with_columns([
            pl.when(pl.col("currency") == target_currency)
            .then(pl.col("market_value"))
            .when(pl.col("rate").is_not_null())
            .then(pl.col("market_value") * pl.col("rate"))
            .otherwise(pl.col("market_value"))
            .alias("market_value"),

            pl.when(pl.col("currency") == target_currency)
            .then(pl.col("nominal_value"))
            .when(pl.col("rate").is_not_null())
            .then(pl.col("nominal_value") * pl.col("rate"))
            .otherwise(pl.col("nominal_value"))
            .alias("nominal_value"),

            # Update currency to target where conversion applied
            pl.when(pl.col("currency") == target_currency)
            .then(pl.col("currency"))
            .when(pl.col("rate").is_not_null())
            .then(pl.lit(target_currency))
            .otherwise(pl.col("currency"))
            .alias("currency"),
        ])

        # Drop the temporary rate column from join
        converted = converted.drop("rate")

        return converted

    def convert_guarantees(
        self,
        guarantees: pl.LazyFrame,
        fx_rates: pl.LazyFrame | None,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Convert guarantee amounts to reporting currency.

        Args:
            guarantees: Guarantees with currency and amount_covered
            fx_rates: FX rates with currency_from, currency_to, rate columns
            config: Calculation configuration with base_currency

        Returns:
            Guarantees with amount_covered converted to base currency
        """
        if fx_rates is None or not config.apply_fx_conversion:
            return guarantees

        target_currency = config.base_currency

        # Filter FX rates to only those targeting our base currency
        rates_to_target = fx_rates.filter(
            pl.col("currency_to") == target_currency
        ).select([
            pl.col("currency_from"),
            pl.col("rate"),
        ])

        # Join guarantees with FX rates on currency
        converted = guarantees.join(
            rates_to_target,
            left_on="currency",
            right_on="currency_from",
            how="left",
        )

        # Convert amounts where rate is available
        converted = converted.with_columns([
            pl.when(pl.col("currency") == target_currency)
            .then(pl.col("amount_covered"))
            .when(pl.col("rate").is_not_null())
            .then(pl.col("amount_covered") * pl.col("rate"))
            .otherwise(pl.col("amount_covered"))
            .alias("amount_covered"),

            # Update currency to target where conversion applied
            pl.when(pl.col("currency") == target_currency)
            .then(pl.col("currency"))
            .when(pl.col("rate").is_not_null())
            .then(pl.lit(target_currency))
            .otherwise(pl.col("currency"))
            .alias("currency"),
        ])

        # Drop the temporary rate column from join
        converted = converted.drop("rate")

        return converted

    def convert_provisions(
        self,
        provisions: pl.LazyFrame,
        fx_rates: pl.LazyFrame | None,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Convert provision amounts to reporting currency.

        Args:
            provisions: Provisions with currency and amount
            fx_rates: FX rates with currency_from, currency_to, rate columns
            config: Calculation configuration with base_currency

        Returns:
            Provisions with amount converted to base currency
        """
        if fx_rates is None or not config.apply_fx_conversion:
            return provisions

        target_currency = config.base_currency

        # Filter FX rates to only those targeting our base currency
        rates_to_target = fx_rates.filter(
            pl.col("currency_to") == target_currency
        ).select([
            pl.col("currency_from"),
            pl.col("rate"),
        ])

        # Join provisions with FX rates on currency
        converted = provisions.join(
            rates_to_target,
            left_on="currency",
            right_on="currency_from",
            how="left",
        )

        # Convert amounts where rate is available
        converted = converted.with_columns([
            pl.when(pl.col("currency") == target_currency)
            .then(pl.col("amount"))
            .when(pl.col("rate").is_not_null())
            .then(pl.col("amount") * pl.col("rate"))
            .otherwise(pl.col("amount"))
            .alias("amount"),

            # Update currency to target where conversion applied
            pl.when(pl.col("currency") == target_currency)
            .then(pl.col("currency"))
            .when(pl.col("rate").is_not_null())
            .then(pl.lit(target_currency))
            .otherwise(pl.col("currency"))
            .alias("currency"),
        ])

        # Drop the temporary rate column from join
        converted = converted.drop("rate")

        return converted


    def convert_equity_exposures(
        self,
        equity_exposures: pl.LazyFrame,
        fx_rates: pl.LazyFrame | None,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Convert equity exposure values to reporting currency.

        Args:
            equity_exposures: Equity exposures with currency, carrying_value, fair_value
            fx_rates: FX rates with currency_from, currency_to, rate columns
            config: Calculation configuration with base_currency

        Returns:
            Equity exposures with values converted to base currency
        """
        if fx_rates is None or not config.apply_fx_conversion:
            return equity_exposures

        target_currency = config.base_currency

        # Filter FX rates to only those targeting our base currency
        rates_to_target = fx_rates.filter(
            pl.col("currency_to") == target_currency
        ).select([
            pl.col("currency_from"),
            pl.col("rate"),
        ])

        # Join equity exposures with FX rates on currency
        converted = equity_exposures.join(
            rates_to_target,
            left_on="currency",
            right_on="currency_from",
            how="left",
        )

        # Convert amounts where rate is available
        converted = converted.with_columns([
            pl.when(pl.col("currency") == target_currency)
            .then(pl.col("carrying_value"))
            .when(pl.col("rate").is_not_null())
            .then(pl.col("carrying_value") * pl.col("rate"))
            .otherwise(pl.col("carrying_value"))
            .alias("carrying_value"),

            pl.when(pl.col("currency") == target_currency)
            .then(pl.col("fair_value"))
            .when(pl.col("rate").is_not_null())
            .then(pl.col("fair_value") * pl.col("rate"))
            .otherwise(pl.col("fair_value"))
            .alias("fair_value"),

            # Update currency to target where conversion applied
            pl.when(pl.col("currency") == target_currency)
            .then(pl.col("currency"))
            .when(pl.col("rate").is_not_null())
            .then(pl.lit(target_currency))
            .otherwise(pl.col("currency"))
            .alias("currency"),
        ])

        # Drop the temporary rate column from join
        converted = converted.drop("rate")

        return converted


def create_fx_converter() -> FXConverter:
    """
    Create an FX converter instance.

    Returns:
        FXConverter ready for use
    """
    return FXConverter()
