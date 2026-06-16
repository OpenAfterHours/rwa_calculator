"""
Life Insurance Method (Art. 232).

Pipeline position:
    CRMProcessor (Step 4c) -> SACalculator._apply_life_insurance_rw_mapping

Key responsibilities:
- Aggregate life insurance collateral per exposure (surrender value = market_value)
- Map insurer risk weight to secured portion risk weight via Art. 232 table
- Set life_ins_* columns on exposure frame for SA calculator RW blending
- No EAD reduction for SA (life insurance uses RW mapping, not EAD reduction)
- IRB LGD handled separately via the waterfall (LGDS = 40%)

References:
- CRR Art. 232: Life insurance as funded credit protection
- Art. 200(b): Eligibility of life insurance policies
- Art. 212(2): Operational requirements for life insurance collateral
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.schemas import LIFE_INSURANCE_COLLATERAL_TYPES
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

# Art. 232(1) mapped risk-weight table (insurer SA RW -> secured-portion RW)
# lives in the common rulepack pack as the ``life_insurance_secured_rw_map``
# BandedTable; read it back here so the pack is the single source of truth and
# the mapping expression below derives from it (no inline duplicate).
_LIFE_INS_PACK = resolve("crr", date(2026, 1, 1))
_LIFE_INS_SECURED_RW_BANDS = _LIFE_INS_PACK.banded("life_insurance_secured_rw_map").bands


def _map_insurer_rw_to_secured_rw_expr() -> pl.Expr:
    """Build expression mapping insurer_risk_weight to Art. 232 secured portion RW.

    The mapping (CRR Art. 232(1), ``life_insurance_secured_rw_map`` pack band
    table) is:
        20%            -> 20%
        30% or 50%     -> 35%
        65%, 100%, 135% -> 70%
        150%           -> 150%

    A band applies when the insurer RW is <= its upper bound; the open-ended top
    band is the catch-all. Built from the pack so the values have one home.

    Returns:
        Polars expression producing the mapped secured portion risk weight.
    """
    rw = pl.col("insurer_risk_weight").fill_null(1.00)
    chain: pl.Expr | None = None
    catch_all = 0.0
    for bound, value in _LIFE_INS_SECURED_RW_BANDS:
        if bound is None:
            catch_all = float(value)
            continue
        predicate = rw <= float(bound)
        chain = (
            pl.when(predicate).then(pl.lit(float(value)))
            if chain is None
            else chain.when(predicate).then(pl.lit(float(value)))
        )
    if chain is None:
        return pl.lit(catch_all)
    return chain.otherwise(pl.lit(catch_all))


@cites("CRR Art. 232")
def compute_life_insurance_columns(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame | None,
    config: CalculationConfig,
) -> pl.LazyFrame:
    """Compute life insurance CRM columns on the exposure frame.

    Aggregates eligible life insurance collateral per exposure and sets:
    - life_ins_collateral_value: total surrender value allocated to this exposure
    - life_ins_secured_rw: value-weighted mapped risk weight per Art. 232

    Does NOT modify EAD columns. The SA calculator uses these columns
    for risk weight blending via _apply_life_insurance_rw_mapping().

    Args:
        exposures: Exposure frame with ead_gross, exposure_reference, etc.
        collateral: Collateral frame (may be None if no collateral).
        config: Calculation configuration.

    Returns:
        Exposure frame with life_ins_collateral_value and life_ins_secured_rw columns.
    """
    if collateral is None:
        return _add_default_life_ins_columns(exposures)

    # Filter to life insurance collateral only
    coll_schema = collateral.collect_schema()
    ctype_col = "collateral_type"
    if ctype_col not in coll_schema.names():
        return _add_default_life_ins_columns(exposures)

    li_coll = collateral.filter(
        pl.col(ctype_col).str.to_lowercase().is_in(LIFE_INSURANCE_COLLATERAL_TYPES)
    )

    # Check if insurer_risk_weight column exists
    has_insurer_rw = "insurer_risk_weight" in coll_schema.names()
    if not has_insurer_rw:
        li_coll = li_coll.with_columns(pl.lit(1.00).alias("insurer_risk_weight"))

    # Use market_value as the surrender value (documented convention)
    # Apply Art. 232 mapped RW per item
    li_coll = li_coll.with_columns(_map_insurer_rw_to_secured_rw_expr().alias("_li_item_rw"))

    # Build exposure reference lookups for multi-level matching
    exp_schema = exposures.collect_schema()
    exp_ref_col = (
        "exposure_reference" if "exposure_reference" in exp_schema.names() else "loan_reference"
    )
    ead_col = "ead_gross" if "ead_gross" in exp_schema.names() else "ead"

    # Direct-level: aggregate life insurance value and weighted RW per beneficiary
    li_agg = li_coll.group_by("beneficiary_reference").agg(
        pl.col("market_value").fill_null(0.0).sum().alias("_li_total_value"),
        (pl.col("market_value").fill_null(0.0) * pl.col("_li_item_rw"))
        .sum()
        .alias("_li_weighted_rw"),
    )

    # Join to exposures by beneficiary_reference = exposure_reference
    exposures = exposures.join(
        li_agg,
        left_on=exp_ref_col,
        right_on="beneficiary_reference",
        how="left",
    )

    # Compute per-exposure life insurance columns
    ead = pl.col(ead_col).fill_null(0.0)
    li_value = pl.col("_li_total_value").fill_null(0.0)
    li_wrw = pl.col("_li_weighted_rw").fill_null(0.0)

    # Cap life insurance value at EAD
    capped_value = pl.min_horizontal(li_value, ead)

    # Weighted-average mapped RW
    avg_rw = pl.when(li_value > 0).then(li_wrw / li_value).otherwise(pl.lit(0.0))

    exposures = exposures.with_columns(
        capped_value.alias("life_ins_collateral_value"),
        avg_rw.alias("life_ins_secured_rw"),
    ).drop(["_li_total_value", "_li_weighted_rw"])

    return exposures


def _add_default_life_ins_columns(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Add zero-valued life insurance columns when no life insurance collateral exists."""
    return exposures.with_columns(
        pl.lit(0.0).alias("life_ins_collateral_value"),
        pl.lit(0.0).alias("life_ins_secured_rw"),
    )
