"""
Standardised Approach (SA) Calculator for RWA.

Thin orchestrator over the ``lf.sa`` Polars namespace. All pipeline stages
(risk-weight lookup, CRM substitution, guarantee substitution, currency
mismatch, due diligence, defaulted treatment, supporting factors, audit)
live in ``engine/sa/namespace.py``; ``SACalculator`` chains them in
regulatory order and layers caller-specific gating on top (e.g. the
``is_sa`` guard on the unified frame and the ``sa_rwa`` snapshot used by
the IRB output floor).

Pipeline position:
    CRMProcessor -> SACalculator -> Aggregation

Key responsibilities:
- Chain SA stages exposed via ``lf.sa.*`` in the correct regulatory order
- Emit SA-equivalent RWA (``sa_rwa``) on unified frames for the output floor
- Warn on equity-class rows routed through the main SA table (SA005)
- Translate bundle errors into ``CalculationError`` instances

References:
- CRR Art. 112-134: SA risk weights
- CRR Art. 127: Defaulted exposure risk weights
- CRR Art. 501: SME supporting factor
- CRR Art. 501a: Infrastructure supporting factor
- PRA PS1/26 (Basel 3.1): CRE20 revised SA framework
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

# Importing the namespace module registers the ``lf.sa`` fluent API with Polars.
import rwa_calc.engine.sa.namespace  # noqa: F401
from rwa_calc.contracts.bundles import CRMAdjustedBundle, SAResultBundle
from rwa_calc.contracts.errors import (
    ERROR_EQUITY_IN_MAIN_TABLE,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    LazyFrameResult,
)
from rwa_calc.domain.enums import ApproachType

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


logger = logging.getLogger(__name__)


@dataclass
class SACalculationError:
    """Error during SA calculation."""

    error_type: str
    message: str
    exposure_reference: str | None = None


class SACalculator:
    """
    Calculate RWA using Standardised Approach.

    Implements SACalculatorProtocol. The class is a thin orchestrator — the
    per-stage logic lives on the ``lf.sa`` namespace (see
    ``engine/sa/namespace.py``). Each of ``get_sa_result_bundle``,
    ``calculate_unified``, and ``calculate_branch`` reads as a fluent chain
    of ``lf.sa.*`` calls.

    Usage:
        calculator = SACalculator()
        result = calculator.calculate(crm_bundle, config)
    """

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate RWA using Standardised Approach.

        Args:
            data: CRM-adjusted exposures (uses sa_exposures)
            config: Calculation configuration

        Returns:
            LazyFrameResult with SA RWA calculations
        """
        bundle = self.get_sa_result_bundle(data, config)

        # Convert bundle errors to CalculationErrors, preserving any
        # CalculationError objects already created by sub-components
        calc_errors: list[CalculationError] = []
        for err in bundle.errors:
            if isinstance(err, CalculationError):
                calc_errors.append(err)
            else:
                calc_errors.append(
                    CalculationError(
                        code="SA001",
                        message=str(err),
                        severity=ErrorSeverity.ERROR,
                        category=ErrorCategory.CALCULATION,
                    )
                )

        return LazyFrameResult(
            frame=bundle.results,
            errors=calc_errors,
        )

    def get_sa_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> SAResultBundle:
        """
        Calculate SA RWA and return as a bundle.

        Args:
            data: CRM-adjusted exposures
            config: Calculation configuration

        Returns:
            SAResultBundle with results and audit trail
        """
        errors: list[CalculationError] = []
        dd_errors: list[CalculationError] = []
        sf_errors: list[CalculationError] = []

        exposures = data.sa_exposures

        # Warn if equity-class rows are present in the main exposure table.
        # These get correct SA equity RW (250% B31, 100% CRR) but miss
        # full equity treatment (CIU approaches, transitional floor, IRB Simple).
        self._warn_equity_in_main_table(exposures, errors)

        exposures = (
            exposures.sa.apply_risk_weights(config)
            .sa.apply_fcsm_rw_substitution(config)
            .sa.apply_life_insurance_rw_mapping()
            .sa.apply_guarantee_substitution(config)
            .sa.apply_currency_mismatch_multiplier(config)
            .sa.apply_due_diligence_override(config, errors=dd_errors)
            .sa.calculate_rwa()
            .sa.apply_supporting_factors(config, errors=sf_errors)
        )
        errors.extend(dd_errors)
        errors.extend(sf_errors)

        audit = exposures.sa.build_audit()

        return SAResultBundle(
            results=exposures,
            calculation_audit=audit,
            errors=errors,
        )

    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply SA risk weights to SA rows on a unified frame.

        Operates on the full unified frame (SA + IRB + slotting rows together).
        Only modifies the RWA column for rows where approach == 'standardised';
        the risk-weight pipeline itself runs unconditionally so that all rows
        carry an SA-equivalent RW used by the IRB output floor.

        Args:
            exposures: Unified frame with all approaches
            config: Calculation configuration

        Returns:
            Unified frame with SA columns populated for SA rows
        """
        is_sa = pl.col("approach") == ApproachType.SA.value

        # Risk weights + CRM substitution + guarantee + mismatch + due diligence.
        # Runs unconditionally — also provides SA-equivalent RW for the
        # IRB output floor.
        exposures = (
            exposures.sa.apply_risk_weights(config)
            .sa.apply_fcsm_rw_substitution(config)
            .sa.apply_life_insurance_rw_mapping()
            .sa.apply_guarantee_substitution(config)
            .sa.apply_currency_mismatch_multiplier(config)
            .sa.apply_due_diligence_override(config)
        )

        # Store SA-equivalent RWA for ALL rows before the IRB calculator
        # overwrites risk_weight. The output floor needs: floor_rwa = floor_pct × sa_rwa.
        schema = exposures.collect_schema()
        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"
        if config.output_floor.enabled:
            exposures = exposures.with_columns(
                (pl.col(ead_col) * pl.col("risk_weight")).alias("sa_rwa"),
            )

        # Pre-factor RWA — SA rows only. Non-SA rows keep their existing
        # rwa_pre_factor (or null if absent).
        exposures = exposures.with_columns(
            [
                pl.when(is_sa)
                .then(pl.col(ead_col) * pl.col("risk_weight"))
                .otherwise(
                    pl.col("rwa_pre_factor")
                    if "rwa_pre_factor" in schema.names()
                    else pl.lit(None).cast(pl.Float64)
                )
                .alias("rwa_pre_factor"),
            ]
        )

        # Supporting factors (SA rows only).
        exposures = exposures.sa.apply_supporting_factors(config)

        return exposures

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Calculate SA RWA on pre-filtered SA-only rows.

        Unlike calculate_unified(), expects only SA rows — no approach guards
        needed for RWA calculation. Risk weight join runs on ~55K SA rows
        instead of the full 100K unified frame.

        Args:
            exposures: Pre-filtered SA rows only
            config: Calculation configuration

        Returns:
            LazyFrame with SA RWA columns populated
        """
        exposures = (
            exposures.sa.apply_risk_weights(config)
            .sa.apply_fcsm_rw_substitution(config)
            .sa.apply_life_insurance_rw_mapping()
            .sa.apply_guarantee_substitution(config)
            .sa.apply_currency_mismatch_multiplier(config)
            .sa.apply_due_diligence_override(config)
            .sa.calculate_rwa()
            .sa.apply_supporting_factors(config)
        )

        # Standardise output for aggregator.
        schema = exposures.collect_schema()
        approach_expr = (
            pl.col("approach") if "approach" in schema.names() else pl.lit(ApproachType.SA.value)
        )
        exposures = exposures.with_columns(
            approach_expr.alias("approach_applied"),
            pl.col("rwa_post_factor").alias("rwa_final"),
        )

        return exposures

    @staticmethod
    def _warn_equity_in_main_table(
        exposures: pl.LazyFrame,
        errors: list[CalculationError],
    ) -> None:
        """Emit SA005 info if equity-class rows may be in main exposure table.

        Equity exposures in the main loan/contingent tables receive correct SA
        equity risk weights (250% Basel 3.1, 100% CRR) but miss full equity
        treatment available via the dedicated equity_exposures input table:
        CIU look-through/mandate-based approaches, transitional floor schedule,
        type-specific weights (central_bank 0%, subordinated_debt 150%,
        speculative 400%), and IRB Simple method (CRR).

        The check is based on the approach column containing equity values,
        which is set by the classifier for equity-class rows.
        """
        schema = exposures.collect_schema()
        if "approach" not in schema.names():  # arch-exempt: early-exit guard
            return
        # Approach == "equity" is only set for equity-class rows from the main
        # tables. We detect this via a lightweight one-row collect to avoid
        # materialising the full frame.
        has_equity = (
            exposures.filter(pl.col("approach") == ApproachType.EQUITY.value)
            .head(1)
            .collect()
            .height
            > 0
        )
        if has_equity:
            errors.append(
                CalculationError(
                    code=ERROR_EQUITY_IN_MAIN_TABLE,
                    message=(
                        "Equity-class exposures detected in main exposure table. "
                        "These receive default SA equity risk weights (250% Basel 3.1 "
                        "Art. 133(3), 100% CRR Art. 133(2)). For type-specific weights "
                        "(central_bank 0%, subordinated_debt 150%, speculative 400%), "
                        "CIU approaches, transitional floor, or IRB Simple, "
                        "use the dedicated equity_exposures input table."
                    ),
                    severity=ErrorSeverity.WARNING,
                    category=ErrorCategory.DATA_QUALITY,
                    regulatory_reference="CRR Art. 133 / PRA PS1/26 Art. 133",
                    field_name="exposure_class",
                )
            )


def create_sa_calculator() -> SACalculator:
    """
    Create an SA calculator instance.

    Returns:
        SACalculator ready for use
    """
    return SACalculator()
