"""
Valuation of unfunded credit protection (Art. 233) ahead of the guarantee split.

Pipeline position:
    guarantees._prepare_guarantees:
        protection_screen -> attach_shared_cap -> multi-level expansion
        -> value_unfunded_protection -> maturity mismatch -> split

Key responsibilities:
- Art. 233(1): resolve G, the amount the provider undertook to pay, from
  ``amount_covered`` and ``percentage_covered``. Where both are given the
  undertaking is "x% of the exposure, up to the amount", so
  G = min(percentage x E, amount).
- One contract, one cap: rows sharing a ``guarantee_reference`` are one
  undertaking, so their total G is capped at the contract amount and the cap is
  shared pro-rata to each row's covered demand min(G, E). A contract repeated
  for the same beneficiary and guarantor is one undertaking on that obligation:
  only its largest row is used (this also covers the percentage form, which has
  no amount to cap).
- Art. 233(2): a credit derivative that does not include restructuring as a
  credit event is valued at 60% of G where G <= E (the 40% reduction, point (a))
  and at no more than 60% of E where G > E (point (b)).
- Art. 233(3): the FX mismatch haircut G* = G x (1 - Hfx), applied to the value
  "as determined by paragraph 1 and 2" — i.e. AFTER the restructuring step.

E is the exposure value at the CCF=100% basis (``ead_for_crm``), the basis
Art. 235(1)(a) sizes the covered part against; it falls back to
``ead_after_collateral`` where the CRM basis is absent.

The output carries G* in ``amount_covered``; ``percentage_covered`` has been
consumed and is dropped, so the split downstream reads one column.

References:
- CRR Art. 233(1)-(4) and PRA PS1/26 Art. 233(1)-(4): valuation of unfunded
  credit protection. The two texts differ only in how paragraph 3 names G: CRR
  calls it "the nominal amount of the credit protection", PS1/26 "the value of
  the credit protection as determined by paragraph 1 and 2". Both regimes apply
  paragraph 2 before paragraph 3 here; under CRR that is the more conservative
  reading where the two orders differ (G > E with a currency mismatch).
- CRR / PS1/26 Art. 213(1)(b): the extent of the protection must be clearly
  defined and incontrovertible (one contract, one cap).
- CRR / PS1/26 Art. 235(1)(a): E at 100% of an off-balance-sheet item's value.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.engine.utils import partition_by_nullable
from rwa_calc.rulebook.compile import scalar_value

if TYPE_CHECKING:
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

# One protection contract: rows sharing it share one cap (null = no contract).
_CONTRACT_KEY = "guarantee_reference"

# One contract on one obligation from one provider: repeated rows are one undertaking.
_UNDERTAKING_KEYS = [_CONTRACT_KEY, "beneficiary_reference", "guarantor"]

# Columns the valuation reads that an input may legitimately omit.
_VALUATION_COLUMNS: dict[str, ColumnSpec] = {
    "percentage_covered": ColumnSpec(pl.Float64, required=False),
    "guarantee_reference": ColumnSpec(pl.String, required=False),
    "protection_type": ColumnSpec(pl.String, default="guarantee", required=False),
    "includes_restructuring": ColumnSpec(pl.Boolean, required=False),
}


@cites("CRR Art. 233")
@cites("PS1/26, paragraph 233")
def value_unfunded_protection(
    guarantees: pl.LazyFrame,
    exposures: pl.LazyFrame,
    exposure_names: list[str],
    *,
    pack: ResolvedRulepack,
) -> pl.LazyFrame:
    """
    Value each exposure-level guarantee row under Art. 233(1)-(3).

    Args:
        guarantees: Exposure-level guarantee rows (after multi-level expansion),
            carrying ``_shared_cap`` from :func:`attach_shared_cap`.
        exposures: Exposures with ``exposure_reference`` and the E basis.
        exposure_names: Column names of ``exposures`` (already resolved by the
            caller, so no further schema walk is needed here).
        pack: The run's resolved rulepack (haircut scalars).

    Returns:
        Guarantee rows with ``amount_covered`` = G* and the applied
        ``guarantee_restructuring_haircut`` / ``guarantee_fx_haircut`` rates;
        ``percentage_covered`` and the transient columns are dropped.
    """
    guar_names = guarantees.collect_schema().names()
    guarantees = ensure_columns(guarantees, _VALUATION_COLUMNS, present=guar_names)

    guar_ccy = _first_present(guar_names, ("original_currency", "currency"))
    exp_ccy = _first_present(exposure_names, ("original_currency", "currency"))
    exp_select = [pl.col("exposure_reference"), crm_basis_expr(exposure_names)]
    if exp_ccy is not None:
        exp_select.append(pl.col(exp_ccy).alias("_exp_ccy"))

    guarantees = guarantees.join(
        exposures.select(exp_select),
        left_on="beneficiary_reference",
        right_on="exposure_reference",
        how="left",
    )

    guarantees = (
        guarantees.with_columns(resolve_guarantee_amount_expr("amount_covered"))
        .pipe(_keep_one_row_per_undertaking)
        .pipe(_apply_shared_cap)
    )
    guarantees = _apply_restructuring_exclusion(guarantees, pack)
    guarantees = _apply_fx_mismatch(guarantees, pack, guar_ccy, has_exp_ccy=exp_ccy is not None)
    return guarantees.drop(
        ["percentage_covered", "_shared_cap", "_crm_basis", "_exp_ccy"], strict=False
    )


def attach_shared_cap(guarantees: pl.LazyFrame) -> pl.LazyFrame:
    """
    Record each guarantee contract's cap on its rows BEFORE multi-level expansion.

    Rows sharing a non-null ``guarantee_reference`` are one undertaking; its cap
    is the largest ``amount_covered`` across those rows (the screen raises
    CRM028 where they disagree). Read pre-expansion because expansion rescales
    ``amount_covered`` to each child's share. A null reference, or a contract
    stated only as a percentage (no supplied amount), carries no cap.
    """
    guarantees = ensure_columns(guarantees, _VALUATION_COLUMNS)
    supplied = pl.when(_amount_supplied()).then(pl.col("amount_covered"))
    return guarantees.with_columns(
        partition_by_nullable(
            supplied.max().over(_CONTRACT_KEY),
            _CONTRACT_KEY,
            pl.lit(None, dtype=pl.Float64),
        ).alias("_shared_cap"),
    )


def crm_basis_expr(names: list[str]) -> pl.Expr:
    """
    E, the exposure value at the CCF=100% basis, aliased ``_crm_basis``.

    CRR / PS1/26 Art. 235(1)(a): the covered part is sized against the exposure
    value with off-balance-sheet items at 100% of their value — ``ead_for_crm``.
    Falls back to ``ead_after_collateral`` where the CRM basis is absent or null
    (pure on-balance-sheet rows carry the same value on both).
    """
    if "ead_for_crm" in names:
        return pl.coalesce(pl.col("ead_for_crm"), pl.col("ead_after_collateral")).alias(
            "_crm_basis"
        )
    return pl.col("ead_after_collateral").alias("_crm_basis")


@cites("CRR Art. 233")
def resolve_guarantee_amount_expr(alias: str) -> pl.Expr:
    """
    G under Art. 233(1): the amount the provider undertook to pay.

    - Amount only: ``amount_covered``.
    - Percentage only (amount null or ~0): ``percentage_covered x E``.
    - Both: ``min(percentage_covered x E, amount_covered)`` — "x% of the
      exposure, up to the amount" undertakes the smaller of the two.
    - Neither: 0.

    E is ``_crm_basis`` (CCF=100% basis, Art. 235(1)(a)), which the caller has
    already joined onto the frame.
    """
    amount = pl.col("amount_covered")
    percentage = pl.col("percentage_covered")
    has_amount = _amount_supplied()
    has_percentage = percentage > 0
    by_percentage = percentage * pl.col("_crm_basis")
    return (
        pl.when(has_amount & has_percentage)
        .then(pl.min_horizontal(by_percentage, amount))
        .when(has_percentage)
        .then(by_percentage)
        .otherwise(amount)
        .fill_null(0.0)
        .alias(alias)
    )


def _keep_one_row_per_undertaking(guarantees: pl.LazyFrame) -> pl.LazyFrame:
    """
    Use one row per (contract, beneficiary, guarantor): the one with the largest G.

    A ``guarantee_reference`` repeated for the same beneficiary and guarantor
    restates one undertaking on one obligation (Art. 233(1)), so the repeat adds
    no cover — the screen raises CRM028 for it. The contract cap cannot do this
    alone: a percentage-only contract has no amount to cap, and the cap of a
    "x% up to an amount" contract can exceed its one undertaking. Dropping the
    repeat (rather than sharing G across the rows) also keeps the Art. 233(2)
    test of G against E on the whole undertaking. Rows with no reference are
    separate contracts and are all kept. The first of equal rows is kept.
    """
    guarantees = guarantees.with_columns(
        partition_by_nullable(
            pl.col("amount_covered").max().over(_UNDERTAKING_KEYS),
            _CONTRACT_KEY,
            pl.col("amount_covered"),
        ).alias("_undertaking_g"),
        partition_by_nullable(
            pl.int_range(pl.len()).over(_UNDERTAKING_KEYS), _CONTRACT_KEY, pl.lit(0)
        ).alias("_undertaking_pos"),
    )
    first_largest = partition_by_nullable(
        pl.when(pl.col("amount_covered") == pl.col("_undertaking_g"))
        .then(pl.col("_undertaking_pos"))
        .min()
        .over(_UNDERTAKING_KEYS),
        _CONTRACT_KEY,
        pl.col("_undertaking_pos"),
    )
    return guarantees.filter(pl.col("_undertaking_pos") == first_largest).drop(
        "_undertaking_g", "_undertaking_pos"
    )


def _apply_shared_cap(guarantees: pl.LazyFrame) -> pl.LazyFrame:
    """
    Share one contract's cap across its rows, pro-rata to each row's demand.

    A row's covered demand is min(G, E): the cover it can actually use. Where
    the demands of a contract's rows exceed its cap, each row receives
    ``demand x cap / total demand`` (so the total equals the cap and no row
    exceeds its exposure); otherwise G is left unchanged.
    """
    demand = pl.min_horizontal(pl.col("amount_covered"), pl.col("_crm_basis"))
    guarantees = guarantees.with_columns(demand.alias("_demand"))
    total_demand = partition_by_nullable(
        pl.col("_demand").sum().over(_CONTRACT_KEY), _CONTRACT_KEY, pl.col("_demand")
    )
    cap = pl.col("_shared_cap")
    binds = cap.is_not_null() & (total_demand > cap)
    return guarantees.with_columns(
        pl.when(binds)
        .then(pl.col("_demand") * cap / total_demand)
        .otherwise(pl.col("amount_covered"))
        .alias("amount_covered"),
    ).drop("_demand")


@cites("CRR Art. 233")
@cites("PS1/26, paragraph 233")
def _apply_restructuring_exclusion(
    guarantees: pl.LazyFrame, pack: ResolvedRulepack
) -> pl.LazyFrame:
    """
    Art. 233(2): value a credit derivative that excludes restructuring.

    (a) G <= E: reduce G by the restructuring-exclusion haircut (40%).
    (b) G > E: value the protection at no more than the cap share (60%) of E.

    Applies to every credit derivative whose ``includes_restructuring`` is
    False, whether its cover was stated as an amount or a percentage (G is
    already resolved). A null flag is permissive (no haircut); the loader
    defaults the declared column to False.
    """
    haircut = scalar_value(pack.scalar_param("restructuring_exclusion_haircut"))
    exposure_cap = scalar_value(pack.scalar_param("restructuring_exclusion_exposure_cap"))
    applies = (pl.col("protection_type") == "credit_derivative") & ~pl.col(
        "includes_restructuring"
    ).fill_null(True)
    g = pl.col("amount_covered")
    e = pl.col("_crm_basis")
    return guarantees.with_columns(
        pl.when(applies & (g > e))
        .then(e * exposure_cap)
        .when(applies)
        .then(g * (1.0 - haircut))
        .otherwise(g)
        .alias("amount_covered"),
        pl.when(applies)
        .then(pl.lit(haircut))
        .otherwise(pl.lit(0.0))
        .alias("guarantee_restructuring_haircut"),
    )


@cites("CRR Art. 233")
@cites("PS1/26, paragraph 233")
def _apply_fx_mismatch(
    guarantees: pl.LazyFrame,
    pack: ResolvedRulepack,
    guar_ccy: str | None,
    *,
    has_exp_ccy: bool,
) -> pl.LazyFrame:
    """
    Art. 233(3)-(4): G* = G x (1 - Hfx) where the protection and exposure
    currencies differ.

    Hfx is the 10-business-day FX volatility adjustment (pack ``fx_haircut``).
    Applied to the post-paragraph-2 value and before the cap at E, so a large
    foreign-currency guarantee still fully covers a smaller exposure. A null
    currency on either side is not a mismatch.
    """
    if guar_ccy is None or not has_exp_ccy:
        return guarantees.with_columns(pl.lit(0.0).alias("guarantee_fx_haircut"))
    h_fx = scalar_value(pack.scalar_param("fx_haircut"))
    mismatch = (
        pl.col(guar_ccy).is_not_null()
        & pl.col("_exp_ccy").is_not_null()
        & (pl.col(guar_ccy) != pl.col("_exp_ccy"))
        & (pl.col("amount_covered") > 0)
    )
    return guarantees.with_columns(
        pl.when(mismatch)
        .then(pl.col("amount_covered") * (1.0 - h_fx))
        .otherwise(pl.col("amount_covered"))
        .alias("amount_covered"),
        pl.when(mismatch).then(pl.lit(h_fx)).otherwise(pl.lit(0.0)).alias("guarantee_fx_haircut"),
    )


def _amount_supplied() -> pl.Expr:
    """True where ``amount_covered`` states an amount (null where it is null).

    An amount below 1e-10 is "not supplied": a zero ``amount_covered`` beside a
    positive ``percentage_covered`` means the percentage form was used, so it
    neither caps the percentage nor sets a contract cap.
    """
    return pl.col("amount_covered").abs() >= 1e-10


def _first_present(names: list[str], candidates: tuple[str, ...]) -> str | None:
    """Return the first of ``candidates`` present in ``names`` (None if none)."""
    return next((c for c in candidates if c in names), None)
