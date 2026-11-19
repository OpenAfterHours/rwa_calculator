"""
SA-CCR exposure value of a netting set: RC, PFE, the margined cap and shared CSAs.

Pipeline position:
    ccr_rows_to_exposures: resolve_margin_terms -> value_ccr_collateral ->
    [compose_exposure_value] -> transitional alpha add-on -> synthetic row

Key responsibilities:
- Unmargined basis, every netting set (Art. 275(1), 278(1)/(3)):
  ``RC = max{CMV - NICA, 0}``, multiplier ``z = CMV - NICA``, add-on on the
  unmargined maturity factor, ``EV = α · (RC + PFE)``. NICA here is all the
  recognised collateral (no item is VM without a margin agreement) plus the
  NICA term stated on the netting set / CSA.
- Margined basis, a margined netting set (Art. 275(2), 278(3)):
  ``RC = max{CMV - VM - NICA, TH + MTA - NICA, 0}``, ``z = CMV - VM - NICA``,
  add-on on the margined (MPOR) maturity factor. An unstated TH or MTA is 0.
- Art. 274(3) cap: a margined netting set's exposure value is the lesser of the
  two. Before review CC-03 there was no cap, so a margined set whose TH + MTA
  floor or long remargining period lifted its EV above the unmargined value kept
  the higher figure. Where the cap binds the row reports the unmargined RC, PFE
  and add-on, so ``ead_ccr = α · (rc + pfe_addon)`` still holds.
- Art. 275(3) / 278(2) shared margin agreement: margined netting sets naming the
  same ``margin_agreement_id`` take one replacement cost for the agreement and
  each its own PFE "as if ... not subject to any form of a margin agreement"
  (``z_i = CMV_i - NICA_i``). The agreement RC is apportioned to the netting
  sets in proportion to their unmargined RC (equally when those are all zero) —
  only the allocation is the engine's choice; the agreement total is the
  article's. The Art. 274(3) cap is applied to the agreement total. The
  agreement's NICA term is counted once (the agreement's own statement, else
  the sum of the netting sets').

References:
- CCR (CRR) Part; PS1/26 Annex R leaves Art. 274(3), 275 and 278 unamended.
- Art. 274(3): "The exposure value of a netting set that is subject to a
  contractual margin agreement shall be capped at the exposure value of the same
  netting set not subject to any form of margin agreement."
- Art. 275(1): "RC = max{CMV - NICA, 0}"; 275(2): "RC = max{CMV - VM - NICA,
  TH + MTA - NICA, 0}"; 275(3): "RC = max{Σ_i max{CMV_i, 0} - max{VM_MA +
  NICA_MA, 0}, 0} + max{Σ_i min{CMV_i, 0} - min{VM_MA + NICA_MA, 0}, 0}".
- Art. 278(2): "The potential future exposure of multiple netting sets that are
  subject to one margin agreement ... shall be calculated as the sum of the
  potential future exposures of all the individual netting sets as if they were
  not subject to any form of a margin agreement."
- Art. 278(3): "z = CMV - NICA for the netting sets referred to in Article
  275(1); CMV - VM - NICA for ... 275(2); CMV_i - NICA_i for ... 275(3)".
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

from rwa_calc.engine.ccr.pfe import compute_pfe, pfe_multiplier
from rwa_calc.engine.ccr.rc import compute_rc_margined

logger = logging.getLogger(__name__)

#: The basis tokens a row's reported components are taken from.
_UNMARGINED = "unmargined"
_MARGINED = "margined"
_SHARED = "shared"

#: Scratch columns dropped before the frame leaves this module.
_SCRATCH = (
    "_nica_unmargined",
    "_nica_margined",
    "_nica_own",
    "_basis_used",
    "_shared_member",
    "_shared_rc",
    "_shared_capped",
    "c_net",
    *(
        f"_{name}_{basis}"
        for name in ("multiplier", "pfe", "ev")
        for basis in (_UNMARGINED, _MARGINED, _SHARED)
    ),
    "_rc_margined",
    *(
        f"{name}_{basis}"
        for name in ("addon_aggregate", "addon_by_asset_class")
        for basis in (_UNMARGINED, _MARGINED)
    ),
)


# Art. 274 and Art. 275 are not in watchfire's bundled CRR index; attribution for
# them is kept in the docstring (the rc.py / sa_ccr.py pattern).
@cites("CRR Art. 278")
def compose_exposure_value(netting_sets: pl.LazyFrame) -> pl.LazyFrame:
    """The Art. 274 exposure value of each netting set and its RC / PFE components.

    Args:
        netting_sets: One row per netting set carrying ``v_net`` (CMV, reporting
            currency), ``is_margined``, ``margin_agreement_id``,
            ``margin_threshold``, ``minimum_transfer_amount``, ``nica`` (the
            resolved stated NICA), ``_nica_netting_set`` / ``_nica_agreement``
            (the raw statements), ``vm_net``, ``nica_collateral``,
            ``collateral_unmargined`` (``value_ccr_collateral``), the add-on per
            basis ``addon_aggregate_{margined,unmargined}`` and
            ``addon_by_asset_class_{margined,unmargined}``, and ``alpha_applied``.

    Returns:
        ``netting_sets`` with ``rc_unmargined``, ``rc_margined`` (null when not
        margined), ``rc``, ``pfe_multiplier``, ``pfe_addon``,
        ``addon_aggregate``, ``addon_by_asset_class`` and ``ead_ccr``.
    """
    # ``sum_horizontal`` reads an unstated NICA term (null) as no NICA.
    frame = netting_sets.with_columns(
        pl.sum_horizontal("nica", "collateral_unmargined").alias("_nica_unmargined"),
        pl.sum_horizontal("nica", "nica_collateral").alias("_nica_margined"),
        pl.sum_horizontal("_nica_netting_set", "nica_collateral").alias("_nica_own"),
    )
    frame = _unmargined_basis(frame)
    frame = _margined_basis(frame)
    frame = _shared_agreements(frame)

    shared = pl.col("_shared_member")
    margined = pl.col("is_margined") & ~shared
    capped = (margined & (pl.col("_ev_margined") > pl.col("_ev_unmargined"))) | (
        shared & pl.col("_shared_capped")
    )
    basis = (
        pl.when(~pl.col("is_margined") | capped)
        .then(pl.lit(_UNMARGINED))
        .when(shared)
        .then(pl.lit(_SHARED))
        .otherwise(pl.lit(_MARGINED))
    )
    return (
        frame.with_columns(basis.alias("_basis_used"))
        .with_columns(
            pl.when(shared)
            .then(pl.col("_shared_rc"))
            .when(margined)
            .then(pl.col("_rc_margined"))
            .otherwise(pl.lit(None, dtype=pl.Float64))
            .alias("rc_margined"),
            _pick(
                "rc",
                unmargined=pl.col("rc_unmargined"),
                margined=pl.col("_rc_margined"),
                shared=pl.col("_shared_rc"),
            ),
            _pick("pfe_multiplier", *_per_basis("_multiplier")),
            _pick("pfe_addon", *_per_basis("_pfe")),
            _pick("ead_ccr", *_per_basis("_ev")),
            _pick(
                "addon_aggregate",
                unmargined=pl.col("addon_aggregate_unmargined"),
                margined=pl.col("addon_aggregate_margined"),
                shared=pl.col("addon_aggregate_unmargined"),
            ),
            _pick(
                "addon_by_asset_class",
                unmargined=pl.col("addon_by_asset_class_unmargined"),
                margined=pl.col("addon_by_asset_class_margined"),
                shared=pl.col("addon_by_asset_class_unmargined"),
            ),
        )
        .drop(*_SCRATCH, strict=False)
    )


def _unmargined_basis(frame: pl.LazyFrame) -> pl.LazyFrame:
    """Art. 275(1) / 278: RC, multiplier, PFE and EV with all collateral as NICA."""
    return (
        compute_pfe(
            frame.with_columns(
                pl.col("_nica_unmargined").alias("c_net"),
                pl.col("addon_aggregate_unmargined").alias("addon_aggregate"),
            )
        )
        .rename(
            {
                "pfe_multiplier": "_multiplier_unmargined",
                "pfe_addon": "_pfe_unmargined",
                "ead_ccr": "_ev_unmargined",
            }
        )
        .drop("addon_aggregate")
    )


def _margined_basis(frame: pl.LazyFrame) -> pl.LazyFrame:
    """Art. 275(2) / 278(3): RC on VM, NICA and the TH + MTA floor; MPOR add-on."""
    z = pl.col("v_net") - pl.col("vm_net") - pl.col("_nica_margined")
    addon = pl.col("addon_aggregate_margined")
    with_rc = compute_rc_margined(
        frame.with_columns(
            (pl.col("vm_net") + pl.col("_nica_margined")).alias("c_net"),
            pl.col("_nica_margined").alias("nica"),
        )
    ).rename({"rc_margined": "_rc_margined"})
    return (
        with_rc.with_columns(pfe_multiplier(z, addon).alias("_multiplier_margined"))
        .with_columns(
            (pl.col("_multiplier_margined") * addon).alias("_pfe_margined"),
        )
        .with_columns(
            (pl.col("alpha_applied") * (pl.col("_rc_margined") + pl.col("_pfe_margined"))).alias(
                "_ev_margined"
            )
        )
    )


def _shared_agreements(frame: pl.LazyFrame) -> pl.LazyFrame:
    """Art. 275(3) / 278(2): one RC per shared margin agreement, own unmargined PFE."""
    addon = pl.col("addon_aggregate_unmargined")
    frame = frame.with_columns(
        pfe_multiplier(pl.col("v_net") - pl.col("_nica_own"), addon).alias("_multiplier_shared")
    ).with_columns((pl.col("_multiplier_shared") * addon).alias("_pfe_shared"))

    candidates = pl.col("is_margined") & pl.col("margin_agreement_id").is_not_null()
    c_items = pl.col("vm_net") + pl.col("nica_collateral")
    agreements = (
        frame.filter(candidates)
        .group_by("margin_agreement_id")
        .agg(
            pl.len().alias("_members"),
            pl.col("v_net").clip(lower_bound=0.0).sum().alias("_cmv_positive"),
            pl.col("v_net").clip(upper_bound=0.0).sum().alias("_cmv_negative"),
            c_items.sum().alias("_c_items"),
            pl.col("_nica_agreement").drop_nulls().first().alias("_agreement_nica"),
            pl.col("_nica_netting_set").sum().alias("_netting_set_nica"),
            pl.col("rc_unmargined").sum().alias("_rc_unmargined_total"),
            pl.col("_ev_unmargined").sum().alias("_ev_unmargined_total"),
            (pl.col("alpha_applied") * pl.col("_pfe_shared")).sum().alias("_alpha_pfe_total"),
            pl.col("alpha_applied").max().alias("_alpha"),
        )
        .filter(pl.col("_members") >= 2)
    )
    collateral = pl.col("_c_items") + pl.coalesce(
        pl.col("_agreement_nica"), pl.col("_netting_set_nica")
    )
    agreement_rc = pl.max_horizontal(
        pl.col("_cmv_positive") - pl.max_horizontal(collateral, pl.lit(0.0)), pl.lit(0.0)
    ) + pl.max_horizontal(
        pl.col("_cmv_negative") - pl.min_horizontal(collateral, pl.lit(0.0)), pl.lit(0.0)
    )
    agreements = agreements.with_columns(agreement_rc.alias("_agreement_rc")).with_columns(
        (
            pl.col("_alpha") * pl.col("_agreement_rc") + pl.col("_alpha_pfe_total")
            > pl.col("_ev_unmargined_total")
        ).alias("_shared_capped")
    )
    share = (
        pl.when(pl.col("_rc_unmargined_total") > 0.0)
        .then(pl.col("rc_unmargined") / pl.col("_rc_unmargined_total"))
        .otherwise(1.0 / pl.col("_members"))
    )
    return (
        frame.join(
            agreements.select(
                "margin_agreement_id",
                "_members",
                "_rc_unmargined_total",
                "_agreement_rc",
                "_shared_capped",
            ),
            on="margin_agreement_id",
            how="left",
        )
        .with_columns((candidates & pl.col("_agreement_rc").is_not_null()).alias("_shared_member"))
        .with_columns(
            pl.when(pl.col("_shared_member"))
            .then(pl.col("_agreement_rc") * share)
            .otherwise(pl.lit(None, dtype=pl.Float64))
            .alias("_shared_rc"),
        )
        .with_columns(
            (pl.col("alpha_applied") * (pl.col("_shared_rc") + pl.col("_pfe_shared"))).alias(
                "_ev_shared"
            ),
        )
        .drop("_members", "_rc_unmargined_total", "_agreement_rc")
    )


def _per_basis(prefix: str) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
    """``(unmargined, margined, shared)`` columns named ``<prefix>_<basis>``."""
    return (
        pl.col(f"{prefix}_{_UNMARGINED}"),
        pl.col(f"{prefix}_{_MARGINED}"),
        pl.col(f"{prefix}_{_SHARED}"),
    )


def _pick(name: str, unmargined: pl.Expr, margined: pl.Expr, shared: pl.Expr) -> pl.Expr:
    """The ``name`` component of the basis the row's exposure value is taken on."""
    return (
        pl.when(pl.col("_basis_used") == _UNMARGINED)
        .then(unmargined)
        .when(pl.col("_basis_used") == _SHARED)
        .then(shared)
        .otherwise(margined)
        .alias(name)
    )
