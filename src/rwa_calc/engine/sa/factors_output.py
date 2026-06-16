"""
Standardised Approach RWA computation, supporting factors and audit output.

Plain typed functions for the tail of the SA pipeline: pre-factor RWA
(EAD x RW), the CRR Art. 501 / 501a supporting factors, and the SA audit
trail. ``SACalculator`` composes them via ``LazyFrame.pipe`` after the
risk-weight assignment and adjustment stages.

Pipeline position:
    CRMProcessor -> SACalculator -> Aggregation

Key responsibilities:
- Pre-factor RWA computation (``rwa_pre_factor``)
- SME / infrastructure supporting factors (CRR Art. 501 / 501a)
- SA calculation audit trail (``sa_calculation``)

References:
- CRR Art. 113: Calculation of risk-weighted exposure amounts
- CRR Art. 501 / 501a: SME / infrastructure supporting factors
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.engine.supporting_factors import SupportingFactorCalculator

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)


# Columns required by SupportingFactorCalculator that are not part of the
# main SA input contract.
_SUPPORTING_FACTOR_COLUMNS: dict[str, ColumnSpec] = {
    "is_sme": ColumnSpec(pl.Boolean, default=False, required=False),
    "is_infrastructure": ColumnSpec(pl.Boolean, default=False, required=False),
    "lending_group_reference": ColumnSpec(pl.String, default=None, required=False),
}


@cites("CRR Art. 113")
def calculate_rwa(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Compute pre-factor RWA = EAD x Risk Weight.

    Emits ``rwa_pre_factor`` for downstream supporting-factor scaling.

    References:
    - CRR Art. 113(1)-(5): general rule for SA risk-weighted exposure amounts.
    """
    return lf.with_columns(
        (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa_pre_factor"),
    )


@cites("CRR Art. 501")
def apply_supporting_factors(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    *,
    errors: list[CalculationError] | None = None,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Apply SME / infrastructure supporting factors (CRR Art. 501 / 501a).

    Under Basel 3.1 the supporting-factor calculator returns a factor of
    1.0 for every row, preserving RWA unchanged.

    Args:
        lf: SA exposures frame with ``rwa_pre_factor`` computed.
        config: Calculation configuration (selects framework).
        errors: Optional accumulator for data-quality warnings.
    """
    lf = ensure_columns(lf, _SUPPORTING_FACTOR_COLUMNS)
    return SupportingFactorCalculator().apply_factors(lf, config, errors=errors, pack=pack)


def build_audit(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Build SA calculation audit trail.

    Selects ``exposure_reference`` plus any audit columns present on the
    frame and emits ``sa_calculation`` — a human-readable formula string.
    """
    schema = lf.collect_schema()
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

    return lf.select(select_cols).with_columns(
        pl.concat_str(
            [
                pl.lit("SA: EAD="),
                pl.col("ead_final").round(0).cast(pl.String),
                pl.lit(" × RW="),
                (pl.col("risk_weight") * 100).round(1).cast(pl.String),
                pl.lit("% × SF="),
                (pl.col("supporting_factor") * 100).round(2).cast(pl.String),
                pl.lit("% → RWA="),
                pl.col("rwa_post_factor").round(0).cast(pl.String),
            ]
        ).alias("sa_calculation"),
    )
