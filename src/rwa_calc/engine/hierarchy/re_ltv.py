"""
Real-estate loan-to-value derivation for the hierarchy stage.

Pipeline position:
    Loader -> HierarchyResolver (engine/hierarchy) -> Classifier
    Sub-module of the hierarchy stage package; called by
    ``enrich.add_collateral_ltv`` once every supplied LTV (collateral
    ``property_ltv`` at any level, else the loan row's own ``ltv``) has been
    coalesced onto the exposure.

Key responsibilities:
- Fill a null ``ltv`` from the value of the real-estate collateral linked to
  the exposure, so a property supplied without a ``property_ltv`` is weighted
  on its true loan-to-value rather than on a filled one. Before this, a null
  LTV priced CRR at the 35% band and Basel 3.1 at an LTV of 100% whatever the
  loan and the property were (review RE-10 / CL-08).
- Flag every derived value (``ltv_derived``) so the classifier can report the
  substitution (``RE006``).

The numerator is the PS1/26 Art. 124C(2) "amount of the loan": the outstanding
amount (drawn, plus accrued interest) and any undrawn committed amount, before
credit risk adjustments and credit protection. Art. 124C(3) adds the loans
secured by charges ranking ahead, which the input contract carries as
``prior_charge_ltv`` (a share of the property value), so the derived figure is
the same quantity the input contract asks ``property_ltv`` to hold. CRR has no
LTV-numerator article: Art. 125(2)(d) / 126(2)(d) measure "the part of the
loan" against the property's market value. The hierarchy stage runs before any
exposure value exists, and a conversion factor never exceeds 100%, so the
Art. 124C(2) amount is never below the CRR exposure value — the derived LTV is
the conservative bound under CRR, and one numerator serves both regimes.

The levels follow the property-coverage step (direct / facility /
counterparty; an unknown beneficiary type is direct), so an exposure that
counts as carrying property collateral there always receives an LTV here. At
each level the LTV is the total amount of the loans that level's pledges secure
over the total value pledged at that level — a facility's LTV is its drawn plus
undrawn amount over the facility's property — and the most specific level wins.
A property with no ``market_value`` supports no LTV and is ignored.

References:
- PS1/26 Art. 124C(1)-(3): LTV = amount of the loan / value of the property
- CRR Art. 125(2)(d) / Art. 126(2)(d): the 80% / 50% of market value limits
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

from rwa_calc.engine.kernels.allocation import beneficiary_level_expr
from rwa_calc.engine.utils import partition_by_nullable

logger = logging.getLogger(__name__)


# (level label, exposure-side key) in precedence order — the property-coverage
# step's levels, most specific first.
_LEVELS: tuple[tuple[str, str], ...] = (
    ("direct", "exposure_reference"),
    ("facility", "parent_facility_reference"),
    ("counterparty", "counterparty_reference"),
)
_LOAN_AMOUNT = "_ltv_loan_amount"
_LEVEL = "_ltv_level"


@cites("CRR Art. 125")
@cites("PS1/26, paragraph 124C")
def derive_missing_ltv(exposures: pl.LazyFrame, collateral: pl.LazyFrame) -> pl.LazyFrame:
    """Fill a null ``ltv`` from the linked property value and flag it ``ltv_derived``.

    Args:
        exposures: Unified exposures carrying the coalesced supplied ``ltv``,
            ``drawn_amount`` / ``interest`` / ``nominal_amount`` and the three
            linking keys.
        collateral: The sealed collateral table (``collateral_type``,
            ``market_value``, ``prior_charge_ltv``, ``beneficiary_type``,
            ``beneficiary_reference`` always present).

    Returns:
        ``exposures`` with ``ltv`` filled where a valued property is linked and
        no LTV was supplied, and the Boolean ``ltv_derived`` marking those rows.
    """
    pledges = collateral.filter(
        (pl.col("collateral_type").str.to_lowercase() == "real_estate")
        & (pl.col("market_value") > 0.0)
    ).with_columns(beneficiary_level_expr(unknown="direct").alias(_LEVEL))
    exposures = exposures.with_columns(_loan_amount_expr().alias(_LOAN_AMOUNT))

    level_ltvs: list[pl.Expr] = []
    scratch: list[str] = [_LOAN_AMOUNT]
    for level, key in _LEVELS:
        value_col, prior_col = f"_ltv_value_{level}", f"_ltv_prior_{level}"
        pledged = (
            pledges.filter(pl.col(_LEVEL) == level)
            .group_by("beneficiary_reference")
            .agg(
                pl.col("market_value").sum().alias(value_col),
                # Art. 124C(3): the prior charges, as an amount (share x value).
                (pl.col("prior_charge_ltv") * pl.col("market_value")).sum().alias(prior_col),
            )
        )
        exposures = exposures.join(
            pledged, left_on=key, right_on="beneficiary_reference", how="left"
        )
        scratch.extend((value_col, prior_col))
        level_ltvs.append(
            pl.when(pl.col(value_col) > 0.0).then(
                (_secured_loans_expr(level, key) + pl.col(prior_col)) / pl.col(value_col)
            )
        )

    derived = pl.coalesce(level_ltvs)
    supplied = pl.col("ltv")
    return exposures.with_columns(
        pl.coalesce(supplied, derived).alias("ltv"),
        (supplied.is_null() & derived.is_not_null()).alias("ltv_derived"),
    ).drop(scratch)


def _loan_amount_expr() -> pl.Expr:
    """PS1/26 Art. 124C(2): outstanding (drawn + interest) plus undrawn committed amount.

    ``sum_horizontal`` skips nulls, so an unreported component contributes
    nothing rather than voiding the sum.
    """
    return pl.sum_horizontal(
        pl.col("drawn_amount").clip(lower_bound=0.0),
        pl.col("interest").clip(lower_bound=0.0),
        pl.col("nominal_amount").clip(lower_bound=0.0),
    )


def _secured_loans_expr(level: str, key: str) -> pl.Expr:
    """Total amount of the loans one level's pledge secures, on each exposure row.

    Direct pledges secure the exposure alone; a facility or counterparty pledge
    secures every exposure sharing the key, so their amounts are summed over it.
    """
    if level == "direct":
        return pl.col(_LOAN_AMOUNT)
    return partition_by_nullable(
        pl.col(_LOAN_AMOUNT).sum().over(key),
        key,
        pl.col(_LOAN_AMOUNT),
    )
