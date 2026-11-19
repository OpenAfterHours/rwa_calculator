"""
SA-CCR margin terms: one resolved set of CSA terms per netting set.

Pipeline position:
    ccr_rows_to_exposures: resolve_margin_terms -> (MPOR cascade, collateral
    valuation, replacement cost) -> compose_exposure_value

Key responsibilities:
- Coalesce the margin threshold (TH), minimum transfer amount (MTA), NICA and
  MPOR stated on a netting set with the same terms stated on the margin
  agreement it names (``margin_agreement_id``). Before review CC-03 the margin
  agreement's terms had no reader at all: a CSA whose terms were supplied only on
  ``ccr.margin_agreements`` — the table built to hold "a single ISDA CSA covering
  multiple netting sets" — was priced as TH = MTA = NICA = 0.
- Where both state a term and the two differ, take the capital-conservative one
  (the larger TH / MTA / MPOR, the smaller signed NICA) and report CCR025 from
  :func:`margin_term_conflicts`. A null is "not stated", never a conflict.
- Count the trades of each netting set: the Art. 285(3)(a) large-netting-set
  test uses ``max(stated number_of_trades, trades in the input)`` — the input
  is a lower bound on "the number of trades ... at any point during a quarter".
- Carry the CSA's remargining frequency and dispute count (the Art. 285(4)-(5)
  cascade inputs) and the raw netting-set / agreement NICA, which the Art. 275(3)
  shared-agreement replacement cost counts once per agreement.

References:
- CCR (CRR) Part Art. 275(2): RC = max{CMV - VM - NICA, TH + MTA - NICA, 0},
  "TH = the margin threshold applicable to the netting set under the margin
  agreements ... MTA = the minimum transfer amount applicable to the netting set
  under the margin agreements".
- CRR Art. 285(3)(a): "for all netting sets where the number of trades exceeds
  5 000 at any point during a quarter, the margin period of risk for the following
  quarter shall not be less than 20 business days".
- PS1/26 Annex R leaves Art. 275 and Art. 285 unamended (regime-invariant).
"""

from __future__ import annotations

import logging

import polars as pl

from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.schemas import MARGIN_AGREEMENT_SCHEMA, NETTING_SET_SCHEMA

logger = logging.getLogger(__name__)

#: (term, conservative pick, 0 when unstated) — the terms a netting set and its
#: margin agreement may both state. ``max`` raises TH / MTA / MPOR (a higher RC
#: floor, a longer MPOR); ``min`` lowers the signed NICA (less received, more
#: posted). TH and MTA are amounts at or above zero, so an unstated one reads
#: as 0 (a zero-threshold CSA) and a posted NICA still lifts the Art. 275(2)
#: floor term; an unstated NICA or MPOR stays null.
_TERMS: tuple[tuple[str, str, bool], ...] = (
    ("margin_threshold", "max", True),
    ("minimum_transfer_amount", "max", True),
    ("nica", "min", False),
    ("mpor_days", "max", False),
)

_NETTING_SET_COLUMNS = {
    name: NETTING_SET_SCHEMA[name]
    for name in (
        "is_margined",
        "margin_agreement_id",
        "number_of_trades",
        "has_illiquid_collateral_or_hard_to_replace_otc",
        *(term for term, *_ in _TERMS),
    )
}

_AGREEMENT_COLUMNS = {
    name: MARGIN_AGREEMENT_SCHEMA[name]
    for name in (
        "remargining_frequency_days",
        "dispute_count_qtr",
        *(term for term, *_ in _TERMS),
    )
}


def resolve_margin_terms(
    netting_sets: pl.LazyFrame,
    margin_agreements: pl.LazyFrame,
    trades: pl.LazyFrame,
) -> pl.LazyFrame:
    """Resolve each netting set's CSA terms against its margin agreement.

    Args:
        netting_sets: Netting-set frame (NETTING_SET_SCHEMA), one row per set.
        margin_agreements: Margin-agreement frame (MARGIN_AGREEMENT_SCHEMA).
        trades: The netting sets' trades (``netting_set_id``), counted for the
            Art. 285(3)(a) large-netting-set test.

    Returns:
        ``netting_sets`` with ``margin_threshold``, ``minimum_transfer_amount``,
        ``nica`` and ``mpor_days`` replaced by the resolved terms and
        ``number_of_trades`` by ``max(stated, counted)``, plus the cascade
        inputs ``mpor_days_input``, ``has_illiquid``,
        ``remargining_frequency_days`` and ``dispute_count_qtr`` and the raw
        ``_nica_netting_set`` / ``_nica_agreement`` statements.
    """
    netting_sets = ensure_columns(netting_sets, _NETTING_SET_COLUMNS)
    agreement_terms = _agreement_terms(margin_agreements)
    trade_counts = trades.group_by("netting_set_id").agg(pl.len().cast(pl.Int32).alias("_counted"))

    joined = netting_sets.join(agreement_terms, on="margin_agreement_id", how="left").join(
        trade_counts, on="netting_set_id", how="left"
    )
    return (
        joined.with_columns(
            *(_resolved(*spec) for spec in _TERMS),
            # max_horizontal ignores nulls: an unstated count is the counted one.
            pl.max_horizontal(pl.col("number_of_trades"), pl.col("_counted"))
            .cast(pl.Int32)
            .alias("number_of_trades"),
            # Art. 275(2) is evaluated for a margined netting set only; an
            # unstated is_margined reads as unmargined (the schema default).
            pl.col("is_margined").eq_missing(True).alias("is_margined"),
            pl.col("nica").alias("_nica_netting_set"),
            pl.col("_agreement_nica").alias("_nica_agreement"),
        )
        .with_columns(
            pl.col("mpor_days").alias("mpor_days_input"),
            pl.col("has_illiquid_collateral_or_hard_to_replace_otc").alias("has_illiquid"),
        )
        .drop(
            "_counted",
            *(f"_agreement_{term}" for term, *_ in _TERMS),
        )
    )


def margin_term_conflicts(
    netting_sets: pl.LazyFrame,
    margin_agreements: pl.LazyFrame,
) -> pl.LazyFrame:
    """Netting sets whose stated terms disagree with their margin agreement's.

    One row per (netting set, term) where both state the term and the values
    differ — the CCR025 findings plan, decoded by
    ``contracts/ccr_collateral_checks.py``. Reads the same columns and the same
    conservative pick as :func:`resolve_margin_terms`.

    Args:
        netting_sets: Netting-set frame (NETTING_SET_SCHEMA).
        margin_agreements: Margin-agreement frame (MARGIN_AGREEMENT_SCHEMA).

    Returns:
        LazyFrame ``(netting_set_id, counterparty_reference, margin_agreement_id,
        term, netting_set_value, agreement_value, applied_value)``.
    """
    netting_sets = ensure_columns(
        netting_sets,
        {
            **_NETTING_SET_COLUMNS,
            "counterparty_reference": ColumnSpec(pl.String, required=False),
        },
    )
    joined = netting_sets.join(
        _agreement_terms(margin_agreements), on="margin_agreement_id", how="inner"
    )
    plans = [
        joined.filter(
            pl.col(term).is_not_null()
            & pl.col(f"_agreement_{term}").is_not_null()
            & (pl.col(term).cast(pl.Float64) != pl.col(f"_agreement_{term}").cast(pl.Float64))
        ).select(
            pl.col("netting_set_id").cast(pl.String),
            pl.col("counterparty_reference").cast(pl.String),
            pl.col("margin_agreement_id").cast(pl.String),
            pl.lit(term).alias("term"),
            pl.col(term).cast(pl.Float64).alias("netting_set_value"),
            pl.col(f"_agreement_{term}").cast(pl.Float64).alias("agreement_value"),
            _resolved(term, pick, zero_floor).cast(pl.Float64).alias("applied_value"),
        )
        for term, pick, zero_floor in _TERMS
    ]
    return pl.concat(plans, how="vertical").sort("netting_set_id", "term", nulls_last=True)


def _agreement_terms(margin_agreements: pl.LazyFrame) -> pl.LazyFrame:
    """The margin agreement's terms, one row per agreement, ``_agreement_``-prefixed."""
    agreements = ensure_columns(margin_agreements, _AGREEMENT_COLUMNS)
    return agreements.select(
        pl.col("margin_agreement_id"),
        *(pl.col(term).alias(f"_agreement_{term}") for term, *_ in _TERMS),
        pl.col("remargining_frequency_days"),
        pl.col("dispute_count_qtr"),
    ).unique(subset=["margin_agreement_id"], keep="first")


def _resolved(term: str, pick: str, zero_floor: bool) -> pl.Expr:
    """The applied value of ``term``: the stated one, the conservative one on a conflict.

    ``max_horizontal`` / ``min_horizontal`` ignore nulls, so a term stated on one
    side only is taken as stated; both null stays null unless ``zero_floor``
    (TH, MTA), which reads an unstated term as 0.
    """
    sides = [pl.col(term), pl.col(f"_agreement_{term}")]
    if zero_floor:
        sides.append(pl.lit(0.0))
    combined = pl.max_horizontal(*sides) if pick == "max" else pl.min_horizontal(*sides)
    return combined.cast(NETTING_SET_SCHEMA[term].dtype).alias(term)
