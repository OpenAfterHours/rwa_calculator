"""
CRR Supporting Factors for SA calculator (CRR2 Art. 501).

Applies SME and infrastructure supporting factors to RWA calculations.
These factors are CRR-specific and NOT available under Basel 3.1.

SME Supporting Factor - Tiered Approach (CRR2 Art. 501):
- Exposures up to EUR 2.5m (GBP 2.2m): factor of 0.7619
- Exposures above EUR 2.5m (GBP 2.2m): factor of 0.85

Formula:
    factor = [min(E, threshold) × 0.7619 + max(E - threshold, 0) × 0.85] / E

Infrastructure Supporting Factor (CRR Art. 501a):
- Qualifying infrastructure: factor of 0.75

References:
- CRR2 Art. 501 (EU 2019/876 amending EU 575/2013)
- CRR Art. 501a: Infrastructure supporting factor
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


@dataclass
class SupportingFactorResult:
    """Result of supporting factor calculation."""

    factor: Decimal
    was_applied: bool
    description: str


class SupportingFactorCalculator:
    """
    Calculate SME and infrastructure supporting factors for CRR.

    The supporting factors reduce RWA for qualifying exposures:
    - SME: Tiered factor (0.7619 up to threshold, 0.85 above)
    - Infrastructure: Flat 0.75 factor

    Under Basel 3.1, these factors are not available (returns 1.0).
    """

    def calculate_sme_factor(
        self,
        total_exposure: Decimal,
        config: CalculationConfig,
    ) -> Decimal:
        """
        Calculate SME supporting factor based on total exposure.

        Args:
            total_exposure: Total exposure amount to the SME
            config: Calculation configuration

        Returns:
            Effective supporting factor (0.7619 to 0.85)
        """
        if not config.supporting_factors.enabled:
            return Decimal("1.0")

        if total_exposure <= 0:
            return Decimal("1.0")

        # Get thresholds and factors from config
        threshold_eur = config.supporting_factors.sme_exposure_threshold_eur
        threshold_gbp = threshold_eur * config.eur_gbp_rate

        factor_tier1 = config.supporting_factors.sme_factor_under_threshold
        factor_tier2 = config.supporting_factors.sme_factor_above_threshold

        # Use GBP threshold for GBP currency (default)
        threshold = threshold_gbp

        # Calculate tiered factor
        tier1_amount = min(total_exposure, threshold)
        tier2_amount = max(total_exposure - threshold, Decimal("0"))

        weighted_factor = (
            tier1_amount * factor_tier1 +
            tier2_amount * factor_tier2
        )

        return weighted_factor / total_exposure

    def calculate_infrastructure_factor(
        self,
        config: CalculationConfig,
    ) -> Decimal:
        """
        Get infrastructure supporting factor.

        Args:
            config: Calculation configuration

        Returns:
            Infrastructure factor (0.75 for CRR, 1.0 for Basel 3.1)
        """
        if not config.supporting_factors.enabled:
            return Decimal("1.0")

        return config.supporting_factors.infrastructure_factor

    def get_effective_factor(
        self,
        is_sme: bool,
        is_infrastructure: bool,
        total_exposure: Decimal,
        config: CalculationConfig,
    ) -> Decimal:
        """
        Get the most beneficial supporting factor.

        If both SME and infrastructure apply, returns the lower factor
        (more beneficial to the bank).

        Args:
            is_sme: Whether exposure qualifies for SME factor
            is_infrastructure: Whether exposure qualifies for infrastructure
            total_exposure: Total exposure amount (for SME tier calculation)
            config: Calculation configuration

        Returns:
            Most beneficial factor (lowest value)
        """
        if not config.supporting_factors.enabled:
            return Decimal("1.0")

        factors = [Decimal("1.0")]

        if is_sme:
            factors.append(self.calculate_sme_factor(total_exposure, config))

        if is_infrastructure:
            factors.append(self.calculate_infrastructure_factor(config))

        # Return lowest factor (most beneficial)
        return min(factors)

    def apply_factors(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply supporting factors to exposures LazyFrame.

        The SME supporting factor threshold (EUR 2.5m) is applied at the
        counterparty level, not per-exposure. This means all exposures to
        the same counterparty are aggregated before determining the tiered
        factor, and that blended factor is applied to each exposure.

        Expects columns:
        - is_sme: bool
        - is_infrastructure: bool
        - ead_final: float (exposure amount for tier calculation)
        - rwa_pre_factor: float (RWA before supporting factor)
        - counterparty_reference: str (optional, for aggregation)

        Adds columns:
        - supporting_factor: float
        - rwa_post_factor: float (RWA after supporting factor)
        - supporting_factor_applied: bool
        - total_cp_ead: float (total counterparty EAD, for SME exposures)

        Args:
            exposures: Exposures with RWA calculated
            config: Calculation configuration

        Returns:
            Exposures with supporting factors applied
        """
        if not config.supporting_factors.enabled:
            # Basel 3.1: No supporting factors
            return exposures.with_columns([
                pl.lit(1.0).alias("supporting_factor"),
                pl.col("rwa_pre_factor").alias("rwa_post_factor"),
                pl.lit(False).alias("supporting_factor_applied"),
            ])

        # Get threshold in GBP
        threshold_gbp = float(
            config.supporting_factors.sme_exposure_threshold_eur * config.eur_gbp_rate
        )
        factor_tier1 = float(config.supporting_factors.sme_factor_under_threshold)
        factor_tier2 = float(config.supporting_factors.sme_factor_above_threshold)
        infra_factor = float(config.supporting_factors.infrastructure_factor)

        # Check for required columns
        schema = exposures.collect_schema()
        has_sme = "is_sme" in schema.names()
        has_infra = "is_infrastructure" in schema.names()
        has_counterparty = "counterparty_reference" in schema.names()
        has_btl = "is_buy_to_let" in schema.names()

        # Build SME factor expression with counterparty-level aggregation
        if has_sme:
            if has_counterparty:
                # Calculate total EAD at counterparty level using window function
                # Only aggregate SME exposures with valid counterparty references
                total_cp_ead_expr = pl.when(
                    pl.col("is_sme") & pl.col("counterparty_reference").is_not_null()
                ).then(
                    pl.col("ead_final").sum().over("counterparty_reference")
                ).otherwise(
                    # Fall back to individual EAD if no counterparty ref or not SME
                    pl.col("ead_final")
                )

                exposures = exposures.with_columns([
                    total_cp_ead_expr.alias("total_cp_ead")
                ])

                # Use counterparty total for tier calculation
                ead_for_tier = pl.col("total_cp_ead")
            else:
                # No counterparty reference column - use individual EAD
                ead_for_tier = pl.col("ead_final")

            # Calculate tiered factor based on aggregated exposure
            tier1_expr = pl.when(ead_for_tier <= threshold_gbp).then(
                ead_for_tier
            ).otherwise(pl.lit(threshold_gbp))

            tier2_expr = pl.when(ead_for_tier > threshold_gbp).then(
                ead_for_tier - threshold_gbp
            ).otherwise(pl.lit(0.0))

            # BTL exposures are excluded from the SME factor but still
            # contribute to total_cp_ead for tier calculation (CRR Art. 501)
            is_btl = pl.col("is_buy_to_let") if has_btl else pl.lit(False)

            sme_factor_expr = pl.when(
                pl.col("is_sme") & (ead_for_tier > 0) & ~is_btl
            ).then(
                (tier1_expr * factor_tier1 + tier2_expr * factor_tier2) / ead_for_tier
            ).otherwise(pl.lit(1.0))
        else:
            sme_factor_expr = pl.lit(1.0)

        # Build infrastructure factor expression inline
        if has_infra:
            infra_factor_expr = pl.when(pl.col("is_infrastructure")).then(
                pl.lit(infra_factor)
            ).otherwise(pl.lit(1.0))
        else:
            infra_factor_expr = pl.lit(1.0)

        # Compute minimum (most beneficial) factor
        min_factor_expr = pl.min_horizontal(sme_factor_expr, infra_factor_expr)

        # Single with_columns call for maximum performance
        return exposures.with_columns([
            min_factor_expr.alias("supporting_factor"),
            (pl.col("rwa_pre_factor") * min_factor_expr).alias("rwa_post_factor"),
            (min_factor_expr < 1.0).alias("supporting_factor_applied"),
        ])


def create_supporting_factor_calculator() -> SupportingFactorCalculator:
    """Create a SupportingFactorCalculator instance."""
    return SupportingFactorCalculator()
