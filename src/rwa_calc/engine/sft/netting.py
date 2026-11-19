"""
SFT master-netting eligibility gate for the FCCM netting set.

Pipeline position:
    sft_fccm stage -> sft_bundle_to_exposures -> apply_sft_netting_gate
        -> per-netting-set E* (engine/sft/fccm.py)

Key responsibilities:
- Decide, per SFT ``netting_set_id``, whether its trades may be netted into ONE
  fully adjusted exposure value E*. They may only when the set is covered by an
  ELIGIBLE master netting agreement with ONE counterparty:
    * CRR / PS1/26 Art. 220(1): the netted E* is for "the exposures subject to
      an eligible master netting agreement covering securities financing
      transactions";
    * Art. 206(1)(a)-(d): the eligibility conditions (legally effective and
      enforceable incl. insolvency, close-out right, netting of gains and
      losses, prompt liquidation / set-off of collateral);
    * PS1/26 Art. 111(2A): under a master netting agreement the exposure value
      is "a single exposure value at netting set level" — otherwise per
      transaction (Art. 223(5));
    * Art. 220(4): E* is "the exposure value of the exposure to the
      counterparty" — a master netting agreement is bilateral.
  Eligibility is attested per trade by ``under_master_netting_agreement`` AND
  ``is_legally_enforceable`` (both default False, conservative); a set nets only
  when EVERY trade carries both and the set names one counterparty.
- Split every other multi-trade set into one single-trade set per trade
  (``<netting_set_id>__split__<trade_id>``, the derivative gate's naming,
  ``engine/ccr/sa_ccr.py::apply_legal_enforceability_gate``). Collateral on a
  split set follows its trade through the optional ``trade_id`` link; a row with
  no link to one of the set's own trades cannot be attributed to a single
  transaction and is not recognised.
- Emit CCR028 (WARNING, no eligible MNA) or CCR029 (ERROR, more than one
  counterparty) per split set, naming any unrecognised collateral rows.

Single-trade sets are never touched: splitting one trade is the identity, and
the documented scope of ``SFT_TRADE_SCHEMA`` is exactly that shape. A netted set
keeps the gross sum Sum E(1+HE) - Sum C(1-HC-HFX), which is never below the
Art. 220(3) net-position formula; that formula is not modelled.

References:
- CRR / PS1/26 Art. 206(1), 220(1), 220(4), 223(5); PS1/26 Art. 111(2A).
"""

from __future__ import annotations

import logging
from typing import Any

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import (
    ERROR_SFT_MULTI_COUNTERPARTY_NETTING_SET,
    ERROR_SFT_NETTING_NOT_RECOGNISED,
    CalculationError,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity

logger = logging.getLogger(__name__)

#: Regulatory citation attached to the CCR028 warning.
SFT_NETTING_NOT_RECOGNISED_REG_REF = "CRR / PS1/26 Art. 206(1), 220(1), 223(5); PS1/26 Art. 111(2A)"

#: Regulatory citation attached to the CCR029 error.
SFT_MULTI_COUNTERPARTY_REG_REF = "CRR / PS1/26 Art. 220(4), 223(5)"


@cites("CRR Art. 206")
@cites("CRR Art. 220")
@cites("PS1/26, paragraph 220")
def apply_sft_netting_gate(
    trades: pl.DataFrame,
    collateral: pl.DataFrame | None,
) -> tuple[pl.DataFrame, pl.DataFrame | None, list[CalculationError]]:
    """Split SFT netting sets that are not under an eligible bilateral MNA.

    Args:
        trades: Sealed ``SFT_TRADE_SCHEMA`` rows (already materialised by the
            caller — the SFT book is firm-scale).
        collateral: Sealed ``SFT_COLLATERAL_SCHEMA`` rows, or ``None`` for an
            uncollateralised book.

    Returns:
        ``(trades, collateral, errors)``: the trade frame with each split set's
        ``netting_set_id`` rewritten per trade; the collateral frame with linked
        rows re-keyed to their trade's split set and unlinked rows on a split set
        removed (not recognised); one CCR028 / CCR029 per split set. Both frames
        are returned unchanged, with no error, when no set needs splitting.
    """
    ns_stats = trades.group_by("netting_set_id", maintain_order=True).agg(
        pl.len().alias("_n_trades"),
        pl.col("counterparty_reference").unique(maintain_order=True).alias("_counterparties"),
        (
            pl.col("under_master_netting_agreement").eq_missing(True)
            & pl.col("is_legally_enforceable").eq_missing(True)
        )
        .all()
        .alias("_eligible_mna"),
    )
    to_split = ns_stats.filter(
        (pl.col("_n_trades") > 1)
        & ((pl.col("_counterparties").list.len() > 1) | ~pl.col("_eligible_mna"))
    )
    if to_split.is_empty():
        return trades, collateral, []

    split_ids = to_split["netting_set_id"].to_list()
    in_split = pl.col("netting_set_id").is_in(split_ids)
    split_trades = trades.with_columns(
        pl.when(in_split)
        .then(_split_key())
        .otherwise(pl.col("netting_set_id"))
        .alias("netting_set_id")
    )

    split_collateral, unlinked = _rekey_collateral(trades, collateral, in_split)
    errors = [
        _split_error(row, unlinked.get(row["netting_set_id"], []))
        for row in to_split.iter_rows(named=True)
    ]
    logger.info("SFT netting gate split %d netting set(s) into single-trade sets", len(split_ids))
    return split_trades, split_collateral, errors


def _split_key() -> pl.Expr:
    """The per-trade netting-set id of a split set (derivative gate naming)."""
    return pl.concat_str([pl.col("netting_set_id"), pl.lit("__split__"), pl.col("trade_id")])


def _rekey_collateral(
    trades: pl.DataFrame,
    collateral: pl.DataFrame | None,
    in_split: pl.Expr,
) -> tuple[pl.DataFrame | None, dict[str, list[str]]]:
    """Move linked collateral onto its trade's split set; drop the unlinked rows.

    A row on a split set is linked when its ``trade_id`` names a trade of THAT
    set (a null ``trade_id`` never joins). Returns the re-keyed frame and, per
    original split set, the references of the rows that were not recognised.
    """
    if collateral is None:
        return None, {}
    # ``unique`` so a duplicated trade id can never fan one collateral row out
    # into two recognised copies.
    trade_links = (
        trades.filter(in_split)
        .select("netting_set_id", "trade_id", pl.lit(True).alias("_linked"))
        .unique()
    )
    joined = collateral.join(trade_links, on=["netting_set_id", "trade_id"], how="left")
    unlinked_mask = in_split & pl.col("_linked").is_null()
    unlinked: dict[str, list[str]] = dict(
        joined.filter(unlinked_mask)
        .group_by("netting_set_id", maintain_order=True)
        .agg(pl.col("sft_collateral_reference"))
        .iter_rows()
    )
    rekeyed = (
        joined.filter(~unlinked_mask)
        .with_columns(
            pl.when(in_split)
            .then(_split_key())
            .otherwise(pl.col("netting_set_id"))
            .alias("netting_set_id")
        )
        .drop("_linked")
    )
    return rekeyed, unlinked


def _split_error(row: dict[str, Any], unlinked_refs: list[str]) -> CalculationError:
    """CCR029 for a multi-counterparty set, else CCR028, for one split set."""
    ns_id = row["netting_set_id"]
    n_trades = row["_n_trades"]
    counterparties = [str(cp) for cp in row["_counterparties"]]
    collateral_note = (
        f" {len(unlinked_refs)} collateral row(s) not linked by trade_id to one of its "
        f"trades are not recognised: {', '.join(unlinked_refs)}."
        if unlinked_refs
        else ""
    )
    if len(counterparties) > 1:
        return CalculationError(
            code=ERROR_SFT_MULTI_COUNTERPARTY_NETTING_SET,
            message=(
                f"SFT netting set {ns_id} spans {len(counterparties)} counterparties "
                f"({', '.join(counterparties)}); a master netting agreement is bilateral, "
                f"so its {n_trades} trades are each priced as a separate exposure to "
                f"their own counterparty (Art. 220(4), 223(5)).{collateral_note}"
            ),
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.DATA_QUALITY,
            regulatory_reference=SFT_MULTI_COUNTERPARTY_REG_REF,
            field_name="counterparty_reference",
            expected_value="one counterparty per netting_set_id",
            actual_value=", ".join(counterparties),
        )
    return CalculationError(
        code=ERROR_SFT_NETTING_NOT_RECOGNISED,
        message=(
            f"SFT netting set {ns_id} holds {n_trades} trades but is not covered by an "
            "eligible master netting agreement (under_master_netting_agreement and "
            "is_legally_enforceable are not both True on every trade); each trade is "
            f"priced as a separate exposure (Art. 220(1), 223(5)).{collateral_note}"
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.CCR_LEGAL,
        counterparty_reference=counterparties[0],
        regulatory_reference=SFT_NETTING_NOT_RECOGNISED_REG_REF,
        field_name="is_legally_enforceable",
        expected_value="True with under_master_netting_agreement on every trade (Art. 206)",
        actual_value="False or null on at least one trade",
    )
