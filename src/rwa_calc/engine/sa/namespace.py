"""
Polars LazyFrame namespace for Standardised Approach (SA) calculations.

Provides fluent API for SA RWA calculations via a registered namespace:
- `lf.sa.prepare_columns()`           - Ensure SA input contract columns
- `lf.sa.calculate_rwa()`             - Compute pre-factor RWA (EAD x RW)
- `lf.sa.apply_supporting_factors()`  - Apply SME / infrastructure factors
- `lf.sa.build_audit()`               - Build SA calculation audit trail

Pipeline position:
    CRMProcessor -> SACalculator -> Aggregation

This module is the first slice of the SA fluent API. Heavier stages
(risk-weight lookup, guarantee substitution, defaulted treatment,
currency mismatch, due diligence override) remain on `SACalculator`
for now and will migrate into this namespace in future refactor steps.

Importing this module registers the `sa` namespace with Polars.

Usage:
    import polars as pl
    import rwa_calc.engine.sa.namespace  # Register namespace

    result = (
        sa_exposures
        .sa.prepare_columns()
        # ... risk-weight stages still on SACalculator today ...
        .sa.calculate_rwa()
        .sa.apply_supporting_factors(config)
    )

References:
- CRR Art. 112-134: SA risk weights
- CRR Art. 501 / 501a: SME / infrastructure supporting factors
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.schemas import (
    CLASSIFIER_OUTPUT_SCHEMA,
    CRM_OUTPUT_SCHEMA,
    HIERARCHY_OUTPUT_SCHEMA,
)
from rwa_calc.engine.sa.supporting_factors import SupportingFactorCalculator

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError


# =============================================================================
# SA INPUT CONTRACT
# Defensive defaults for columns the SA pipeline reads. Composed of
# stage-output schemas (hierarchy / CRM / classifier) plus a small set of
# input-schema columns that may be absent when calculators are invoked
# directly from tests or ad-hoc pipelines.
# =============================================================================

SA_INPUT_CONTRACT: dict[str, ColumnSpec] = {
    **HIERARCHY_OUTPUT_SCHEMA,
    **CRM_OUTPUT_SCHEMA,
    **CLASSIFIER_OUTPUT_SCHEMA,
    "book_code": ColumnSpec(pl.String, default="", required=False),
    "seniority": ColumnSpec(pl.String, default="senior", required=False),
    "currency": ColumnSpec(pl.String, required=False),
    "property_type": ColumnSpec(pl.String, required=False),
    "residual_maturity_years": ColumnSpec(pl.Float64, required=False),
    "original_maturity_years": ColumnSpec(pl.Float64, required=False),
    "value_date": ColumnSpec(pl.Date, required=False),
    "maturity_date": ColumnSpec(pl.Date, required=False),
    "is_adc": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_presold": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_qualifying_re": ColumnSpec(pl.Boolean, required=False),
    "prior_charge_ltv": ColumnSpec(pl.Float64, default=0.0, required=False),
    "is_short_term_trade_lc": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_payroll_loan": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_qrre_transactor": ColumnSpec(pl.Boolean, default=False, required=False),
    "sl_type": ColumnSpec(pl.String, required=False),
}


# Columns required by SupportingFactorCalculator that are not part of the
# main SA input contract.
_SUPPORTING_FACTOR_COLUMNS: dict[str, ColumnSpec] = {
    "is_sme": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_infrastructure": ColumnSpec(pl.Boolean, default=False, required=False),
}


# =============================================================================
# LAZYFRAME NAMESPACE
# =============================================================================


@pl.api.register_lazyframe_namespace("sa")
class SALazyFrame:
    """
    SA calculation namespace for Polars LazyFrames.

    Provides fluent API for the simpler stages of the SA pipeline.
    Heavier stages (risk-weight when/then chains, guarantee substitution,
    defaulted / currency-mismatch / due-diligence overrides) remain on
    ``SACalculator`` pending future migration.

    Example:
        result = (
            exposures
            .sa.prepare_columns()
            .sa.calculate_rwa()
            .sa.apply_supporting_factors(config)
            .sa.build_audit()
        )
    """

    def __init__(self, lf: pl.LazyFrame) -> None:
        self._lf = lf

    def prepare_columns(self) -> pl.LazyFrame:
        """Apply SA input contract defaults to absent columns.

        Ensures downstream SA stages can rely on the SA column contract
        without per-stage existence checks.
        """
        return ensure_columns(self._lf, SA_INPUT_CONTRACT)

    def calculate_rwa(self) -> pl.LazyFrame:
        """Compute pre-factor RWA = EAD x Risk Weight.

        Uses ``ead_final`` when present, else falls back to ``ead``.
        Emits ``rwa_pre_factor`` for downstream supporting-factor scaling.
        """
        schema = self._lf.collect_schema()
        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"
        return self._lf.with_columns(
            (pl.col(ead_col) * pl.col("risk_weight")).alias("rwa_pre_factor"),
        )

    def apply_supporting_factors(
        self,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """Apply SME / infrastructure supporting factors (CRR Art. 501 / 501a).

        Under Basel 3.1 the supporting-factor calculator returns a factor of
        1.0 for every row, preserving RWA unchanged.

        Args:
            config: Calculation configuration (selects framework).
            errors: Optional accumulator for data-quality warnings.
        """
        lf = ensure_columns(self._lf, _SUPPORTING_FACTOR_COLUMNS)

        # ead_final is a multi-source derivation (fallback to ead), not a
        # simple default — cannot use ensure_columns.
        if "ead_final" not in lf.collect_schema().names():  # arch-exempt: derivation
            lf = lf.with_columns(pl.col("ead").alias("ead_final"))

        return SupportingFactorCalculator().apply_factors(lf, config, errors=errors)

    def build_audit(self) -> pl.LazyFrame:
        """Build SA calculation audit trail.

        Selects ``exposure_reference`` plus any audit columns present on the
        frame and emits ``sa_calculation`` — a human-readable formula string.
        """
        schema = self._lf.collect_schema()
        available = schema.names()

        optional_cols = [
            "counterparty_reference",
            "exposure_class",
            "cqs",
            "ltv",
            "ead_final",
            "risk_weight",
            "rwa_pre_factor",
            "supporting_factor",
            "rwa_post_factor",
            "supporting_factor_applied",
        ]
        select_cols = ["exposure_reference"] + [c for c in optional_cols if c in available]

        return self._lf.select(select_cols).with_columns(
            pl.concat_str(
                [
                    pl.lit("SA: EAD="),
                    pl.col("ead_final").round(0).cast(pl.String),
                    pl.lit(" \u00d7 RW="),
                    (pl.col("risk_weight") * 100).round(1).cast(pl.String),
                    pl.lit("% \u00d7 SF="),
                    (pl.col("supporting_factor") * 100).round(2).cast(pl.String),
                    pl.lit("% \u2192 RWA="),
                    pl.col("rwa_post_factor").round(0).cast(pl.String),
                ]
            ).alias("sa_calculation"),
        )
