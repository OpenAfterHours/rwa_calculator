"""
Wrong-way risk (WWR) identification gate.

Pipeline position:
    apply_legal_enforceability_gate -> apply_wwr_gate -> CCR calculators

Key responsibilities:
- Identify trades flagged with ``is_specific_wwr=True`` (CRR Art. 291(1)(b))
  and break each one out into its own single-trade synthetic netting set
  with id ``<original_ns_id>__wwr__<trade_id>`` (Art. 291(5)(a)).
- Tag the synthetic netting set with ``wwr_lgd_override = 1.0`` so that
  downstream IRB consumption can apply LGD = 100% per Art. 291(5)(c).
- Emit one ``CalculationError(code="CCR010", severity=WARNING,
  category=CCR_WWR_SPECIFIC)`` per original netting set containing at
  least one WWR trade (aggregation key: original ``netting_set_id``).
- Emit one ``CalculationError(code="CCR011", severity=WARNING,
  category=CCR_WWR_GENERAL)`` per netting set with
  ``has_general_wwr_flag=True`` (CRR Art. 291(1)(a), 291(6)).

This stage does not modify the SA-CCR EAD calculation itself; it
partitions the netting-set frame and emits diagnostic flags consumed by
downstream IRB modules.

References:
- CRR Art. 291(1)(a)/(1)(b)/(4)/(5)(a)/(5)(c)/(6): WWR definitions and
  treatment.
- CRR Art. 272(4): netting set definition.
- CRR Art. 274(2): netting set membership.
- ``data/tables/sa_ccr_factors.py::CCR_WWR_SPECIFIC_LGD_OVERRIDE``:
  source of the Art. 291(5)(c) LGD = 100% scalar.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import date

import polars as pl
from watchfire import cites

from rwa_calc.contracts.bundles import (
    NettingSetBundle,
    RawCCRBundle,
    TradeBundle,
)
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.data.column_spec import ensure_columns
from rwa_calc.data.schemas import NETTING_SET_SCHEMA, TRADE_SCHEMA
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

# CRR Art. 291(5)(c) specific wrong-way-risk LGD = 100% override, resolved from
# the rulepack once at module load.
_PACK = resolve("crr", date(2026, 1, 1))
_WWR_SPECIFIC_LGD_OVERRIDE = scalar_value(_PACK.scalar_param("ccr_wwr_specific_lgd_override"))

#: Schema projection used by :func:`apply_wwr_gate` to backfill the WWR
#: columns (``has_general_wwr_flag`` and ``wwr_lgd_override``) on the
#: netting-set frame when the loader has not yet populated them — keeps
#: this stage independent of upstream column-presence quirks.
_WWR_NS_DEFAULTS = {
    "has_general_wwr_flag": NETTING_SET_SCHEMA["has_general_wwr_flag"],
    "wwr_lgd_override": NETTING_SET_SCHEMA["wwr_lgd_override"],
}

#: Schema projection used by :func:`apply_wwr_gate` to backfill the
#: ``is_specific_wwr`` flag on the trade frame when the loader has not yet
#: populated it.
_WWR_TRADE_DEFAULTS = {"is_specific_wwr": TRADE_SCHEMA["is_specific_wwr"]}

logger = logging.getLogger(__name__)

#: Error code emitted per original netting set containing >=1 trade with
#: ``is_specific_wwr=True`` (CRR Art. 291(4)-(5)).
CCR_WWR_SPECIFIC_ERROR_CODE = "CCR010"

#: Error code emitted per netting set with ``has_general_wwr_flag=True``
#: (CRR Art. 291(1)(a), 291(6)).
CCR_WWR_GENERAL_ERROR_CODE = "CCR011"

#: Regulatory citation attached to CCR010 warnings (specific WWR break-out).
CCR_WWR_SPECIFIC_REG_REF = "CRR Art. 291(4)-(5)"

#: Regulatory citation attached to CCR011 warnings (general WWR flag).
CCR_WWR_GENERAL_REG_REF = "CRR Art. 291(1)(a), 291(6)"

#: Synthetic netting-set id separator: ``<original>__wwr__<trade_id>``.
_WWR_NS_ID_SEPARATOR = "__wwr__"


@cites("CRR Art. 291")
def apply_wwr_gate(raw_ccr: RawCCRBundle) -> RawCCRBundle:
    """Partition netting sets to isolate specific-WWR trades; tag general WWR.

    Implements CRR Art. 291(4)-(5):

    - **Specific WWR** (Art. 291(1)(b) / 291(5)(a)/(c)): every trade with
      ``is_specific_wwr=True`` is broken out into its own single-trade
      synthetic netting set whose id is
      ``<original_ns_id>__wwr__<trade_id>``. The synthetic NS inherits all
      attributes from the original and additionally carries
      ``wwr_lgd_override = 1.0`` so downstream IRB consumption applies
      LGD = 100% (Art. 291(5)(c)). A residual NS keyed by the original
      ``netting_set_id`` retains the non-WWR trades with
      ``wwr_lgd_override = null``.
    - **General WWR** (Art. 291(1)(a) / 291(6)): netting sets with
      ``has_general_wwr_flag=True`` are not partitioned but emit a
      diagnostic CCR011 WARNING.

    Pipeline position:
        apply_legal_enforceability_gate -> apply_wwr_gate -> CCR calculators

    Args:
        raw_ccr: Aggregate CCR input bundle.

    Returns:
        A new ``RawCCRBundle`` (frozen dataclass) with:

        - ``trades`` remapped: each specific-WWR trade carries its new
          synthetic ``netting_set_id``.
        - ``netting_sets`` partitioned: each affected original NS is
          replaced by (1) a residual row (non-WWR trades, override null)
          plus (2) one synthetic row per WWR trade (override = 1.0).
        - ``errors`` extended with one CCR010 WARNING per original NS
          containing >=1 WWR trade, plus one CCR011 WARNING per NS with
          ``has_general_wwr_flag=True``.

        Netting sets with no WWR trades and ``has_general_wwr_flag=False``
        pass through unchanged.

    References:
        CRR Art. 291(1)(a)/(1)(b)/(4)/(5)(a)/(5)(c)/(6).
    """
    # Backfill the schema-declared WWR columns when the loader/fixture has
    # not yet populated them. ``ensure_columns`` is a no-op when the columns
    # are already present.
    netting_sets_lf = ensure_columns(raw_ccr.netting_sets.netting_sets, _WWR_NS_DEFAULTS)
    trades_lf = ensure_columns(raw_ccr.trades.trades, _WWR_TRADE_DEFAULTS)

    # Materialise the small NS and trade frames to drive partition logic.
    # Netting-set and trade frames are at firm scale (hundreds to low
    # thousands of rows), so collecting is acceptable — mirrors the
    # apply_legal_enforceability_gate precedent.
    netting_sets_df = netting_sets_lf.collect()
    trades_df = trades_lf.collect()

    new_errors: list[CalculationError] = list(raw_ccr.errors)

    # --- General WWR (Art. 291(1)(a), 291(6)): diagnostic only --------------
    general_wwr_mask = netting_sets_df["has_general_wwr_flag"].fill_null(False)
    general_wwr_rows = netting_sets_df.filter(general_wwr_mask)
    for ns_row in general_wwr_rows.iter_rows(named=True):
        new_errors.append(
            CalculationError(
                code=CCR_WWR_GENERAL_ERROR_CODE,
                message=(
                    f"Netting set {ns_row['netting_set_id']} carries "
                    "has_general_wwr_flag=True per Art. 291(1)(a); "
                    "general WWR identified for downstream review."
                ),
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.CCR_WWR_GENERAL,
                counterparty_reference=ns_row.get("counterparty_reference"),
                regulatory_reference=CCR_WWR_GENERAL_REG_REF,
                field_name="has_general_wwr_flag",
                expected_value="False (no general WWR correlation)",
                actual_value="True",
            )
        )

    # --- Specific WWR (Art. 291(1)(b), 291(5)(a)/(c)): break-out -----------
    wwr_trade_mask = trades_df["is_specific_wwr"].fill_null(False)
    if not wwr_trade_mask.any():
        logger.info("wwr gate: no specific-WWR trades flagged; no break-out applied")
        return dataclasses.replace(raw_ccr, errors=new_errors)

    wwr_trades_df = trades_df.filter(wwr_trade_mask)
    affected_ns_ids = wwr_trades_df["netting_set_id"].unique().to_list()

    # Rewrite the trades frame: each WWR trade gets a synthetic NS id.
    new_trades_lf = trades_lf.with_columns(
        pl.when(pl.col("is_specific_wwr").fill_null(False))
        .then(
            pl.concat_str(
                [pl.col("netting_set_id"), pl.lit(_WWR_NS_ID_SEPARATOR), pl.col("trade_id")]
            )
        )
        .otherwise(pl.col("netting_set_id"))
        .alias("netting_set_id")
    )

    # Build the partitioned netting-set frame. Both halves already carry the
    # ``wwr_lgd_override`` column thanks to the ``ensure_columns`` call above.
    affected_ns_df = netting_sets_df.filter(
        netting_sets_df["netting_set_id"].is_in(affected_ns_ids)
    )
    unaffected_ns_df = netting_sets_df.filter(
        ~netting_sets_df["netting_set_id"].is_in(affected_ns_ids)
    )

    # Residual rows: same NS attributes, override null. Synthetic rows: same
    # attributes plus override = 1.0 and the synthetic id.
    residual_rows_df = affected_ns_df.with_columns(
        pl.lit(None, dtype=pl.Float64).alias("wwr_lgd_override")
    )

    synthetic_rows_df = (
        wwr_trades_df.select(["trade_id", "netting_set_id"])
        .join(affected_ns_df, on="netting_set_id", how="left")
        .with_columns(
            pl.concat_str(
                [pl.col("netting_set_id"), pl.lit(_WWR_NS_ID_SEPARATOR), pl.col("trade_id")]
            ).alias("netting_set_id"),
            pl.lit(_WWR_SPECIFIC_LGD_OVERRIDE).alias("wwr_lgd_override"),
        )
        .drop("trade_id")
        .select(residual_rows_df.columns)
    )

    new_netting_sets_df = pl.concat(
        [unaffected_ns_df, residual_rows_df, synthetic_rows_df],
        how="vertical_relaxed",
    )

    # Emit one CCR010 WARNING per affected original netting set.
    for ns_row in affected_ns_df.iter_rows(named=True):
        ns_id = ns_row["netting_set_id"]
        new_errors.append(
            CalculationError(
                code=CCR_WWR_SPECIFIC_ERROR_CODE,
                message=(
                    f"Netting set {ns_id} contains >=1 trade with "
                    "is_specific_wwr=True per Art. 291(1)(b); each WWR trade "
                    "broken out into its own synthetic netting set with "
                    "LGD = 100% per Art. 291(5)(c)."
                ),
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.CCR_WWR_SPECIFIC,
                counterparty_reference=ns_row.get("counterparty_reference"),
                regulatory_reference=CCR_WWR_SPECIFIC_REG_REF,
                field_name="is_specific_wwr",
                expected_value="False (no Art. 291(1)(b) legal connection)",
                actual_value="True",
            )
        )

    logger.info(
        "wwr gate broke out %d trade(s) across %d netting set(s) into synthetic single-trade NSes",
        wwr_trades_df.height,
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
