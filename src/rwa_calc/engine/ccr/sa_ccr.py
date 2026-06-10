"""
SA-CCR EAD top-level calculator.

Pipeline position:
    Classifier -> CCRCalculator -> CRMProcessor

Key responsibilities:
- Combine replacement cost (RC) and potential future exposure (PFE) into
  Exposure at Default per CRR Art. 274: ``EAD = alpha * (RC + PFE)``.
- Apply the legal-enforceability gate per CRR Art. 272(4) second
  subparagraph: when a netting set fails the Art. 295-297 contractual-
  netting recognition test, each trade in that NS is expanded into its
  own single-trade synthetic netting set so that no netting benefit is
  recognised on a non-enforceable agreement.

References:
- CRR Art. 272(4): netting set definition + legal-enforceability fallback
- CRR Art. 274: SA-CCR EAD = alpha * (RC + PFE)
- CRR Art. 295-297: conditions for recognition of contractual netting
"""

from __future__ import annotations

import dataclasses
import logging

import polars as pl

from rwa_calc.contracts.bundles import (
    NettingSetBundle,
    RawCCRBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CCRConfig
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity

logger = logging.getLogger(__name__)

#: Error code emitted by :func:`apply_legal_enforceability_gate` when a
#: netting set fails the Art. 295-297 contractual-netting recognition test.
CCR_LEGAL_ENFORCEABILITY_ERROR_CODE = "CCR001"

#: Regulatory citation attached to the CCR001 warning.
CCR_LEGAL_ENFORCEABILITY_REG_REF = "CRR Art. 272(4); Art. 295-297"


# NOTE: No ``@cites("CRR Art. 274")`` — watchfire's bundled rulebook index
# (rulebook_version 2026-05-15) does not yet contain CRR Art. 274. Article
# attribution is preserved in the docstring; re-extending the watchfire CRR
# index for Art. 274 is a separate follow-up (mirrors the P8.7 fix-commit
# pattern for Art. 280a/b/c).
def compute_ead(
    netting_sets: pl.LazyFrame,
    config: CCRConfig | None = None,
) -> pl.LazyFrame:
    """SA-CCR exposure value per CRR Art. 274(2): EAD = α × (RC + PFE).

    Pure composition layer that consumes pre-computed netting-set-grain
    columns ``rc_unmargined`` (Art. 275) and ``pfe_addon`` (Art. 278; for
    CCR-A1 the PFE multiplier of Art. 278(3) is 1, so ``pfe_addon`` equals
    the asset-class AddOn aggregate). α defaults to 1.4 (Art. 274(2)) but
    may be overridden via ``config.alpha``.

    Args:
        netting_sets: LazyFrame at netting-set grain with columns
            ``rc_unmargined: Float64`` and ``pfe_addon: Float64``.
        config: Optional CCRConfig; when provided ``config.alpha`` overrides
            the default α=1.4.

    Returns:
        Input LazyFrame with a new ``ead_ccr: Float64`` column.

    Per-row α (CRR Art. 274(2) second sub-paragraph): when an ``alpha_applied``
    column is present (set to 1.0 for non-financial / pension-scheme
    counterparties per the SA-CCR adapter) it is honoured per row; otherwise the
    scalar ``config.alpha`` / 1.4 is used for every row (backward-compatible
    default).

    References:
        CRR Art. 274(2); BCBS CRE52.
    """
    alpha_value = float(config.alpha) if config is not None else 1.4
    has_alpha_col = "alpha_applied" in netting_sets.collect_schema().names()
    alpha_expr = pl.col("alpha_applied") if has_alpha_col else pl.lit(alpha_value)
    return netting_sets.with_columns(
        (alpha_expr * (pl.col("rc_unmargined") + pl.col("pfe_addon"))).alias("ead_ccr")
    )


def apply_legal_enforceability_gate(raw_ccr: RawCCRBundle) -> RawCCRBundle:
    """Expand non-enforceable netting sets into single-trade synthetic NSes.

    CRR Art. 272(4) second subparagraph requires that when a netting
    agreement fails the recognition conditions of Art. 295-297
    (``is_legally_enforceable == False``), each trade in that netting
    set must be treated as its own single-trade netting set — i.e. no
    netting benefit is recognised. This gate implements that fallback
    by rewriting both the netting-set and trade frames and appending
    one ``CalculationError(code="CCR001", category=CCR_LEGAL)`` per
    affected original netting set.

    Pipeline position:
        Loader -> apply_legal_enforceability_gate -> CCR calculators

    Args:
        raw_ccr: Aggregate CCR input bundle.

    Returns:
        A new ``RawCCRBundle`` (frozen dataclass) with:

        - ``netting_sets`` expanded: each non-enforceable NS row is
          replaced by N rows (one per trade in that NS) whose
          ``netting_set_id`` is suffixed ``__split__<trade_id>``.
        - ``trades`` remapped: each affected trade carries its new
          synthetic ``netting_set_id``.
        - ``errors`` extended with one CCR001 WARNING per affected
          original netting set.

        Enforceable netting sets and their trades pass through
        unchanged.

    References:
        CRR Art. 272(4) second subparagraph; Art. 295-297.
    """
    netting_sets_lf = raw_ccr.netting_sets.netting_sets
    trades_lf = raw_ccr.trades.trades

    # Materialise the small NS frame to enumerate non-enforceable rows and
    # emit one error per affected NS. Netting-set frames are at firm scale
    # (hundreds to low thousands of rows), so collecting is acceptable.
    netting_sets_df = netting_sets_lf.collect()

    non_enforceable_mask = ~netting_sets_df["is_legally_enforceable"].fill_null(True)
    if not non_enforceable_mask.any():
        # Fast path: nothing to do.
        return raw_ccr

    non_enforceable_df = netting_sets_df.filter(non_enforceable_mask)
    enforceable_df = netting_sets_df.filter(~non_enforceable_mask)

    affected_ns_ids = non_enforceable_df["netting_set_id"].to_list()

    # --- Rewrite the trades frame: remap affected NS ids to synthetic ids ---
    new_trades_lf = trades_lf.with_columns(
        pl.when(pl.col("netting_set_id").is_in(affected_ns_ids))
        .then(pl.concat_str([pl.col("netting_set_id"), pl.lit("__split__"), pl.col("trade_id")]))
        .otherwise(pl.col("netting_set_id"))
        .alias("netting_set_id")
    )

    # --- Build synthetic NS rows: one row per (original NS, trade) pair ---
    # Materialise the trade keys to drive the join. Trade frames are also at
    # firm scale; collecting trade_id + netting_set_id is cheap.
    trade_keys_df = (
        trades_lf.select(["trade_id", "netting_set_id"])
        .filter(pl.col("netting_set_id").is_in(affected_ns_ids))
        .collect()
    )

    # Join trade rows against their original NS row to propagate all NS
    # columns, then build the synthetic ``netting_set_id`` for each split.
    synthetic_ns_df = (
        trade_keys_df.join(
            non_enforceable_df,
            on="netting_set_id",
            how="left",
        )
        .with_columns(
            pl.concat_str(
                [pl.col("netting_set_id"), pl.lit("__split__"), pl.col("trade_id")]
            ).alias("netting_set_id")
        )
        .drop("trade_id")
        .select(non_enforceable_df.columns)
    )

    # Stack enforceable rows + synthetic split rows. Schema matches because
    # ``synthetic_ns_df`` was projected back to ``non_enforceable_df.columns``.
    new_netting_sets_df = pl.concat([enforceable_df, synthetic_ns_df], how="vertical_relaxed")

    # --- Emit one CCR001 WARNING per affected original NS ---
    new_errors: list[CalculationError] = list(raw_ccr.errors)
    for ns_row in non_enforceable_df.iter_rows(named=True):
        ns_id = ns_row["netting_set_id"]
        cp_ref = ns_row.get("counterparty_reference")
        new_errors.append(
            CalculationError(
                code=CCR_LEGAL_ENFORCEABILITY_ERROR_CODE,
                message=(
                    f"Netting set {ns_id} is not legally enforceable per "
                    "Art. 295-297; trades expanded to single-trade netting "
                    "sets per Art. 272(4)."
                ),
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.CCR_LEGAL,
                counterparty_reference=cp_ref,
                regulatory_reference=CCR_LEGAL_ENFORCEABILITY_REG_REF,
                field_name="is_legally_enforceable",
                expected_value="True (Art. 295 conditions met)",
                actual_value="False",
            )
        )

    logger.info(
        "legal-enforceability gate expanded %d netting set(s) into single-trade NSes",
        len(affected_ns_ids),
    )

    return dataclasses.replace(
        raw_ccr,
        trades=TradeBundle(trades=new_trades_lf, errors=list(raw_ccr.trades.errors)),
        netting_sets=NettingSetBundle(
            netting_sets=new_netting_sets_df.lazy(),
            errors=list(raw_ccr.netting_sets.errors),
        ),
        errors=new_errors,
    )
