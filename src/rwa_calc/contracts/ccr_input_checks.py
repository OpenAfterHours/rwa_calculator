"""
SA-CCR trade-input checks: risk category, risk factor and netting-set link.

Pipeline position:
    Input gate — ``contracts/validation.py::validate_bundle_values`` runs the plan
    built here inside its single ``pl.collect_all`` — upstream of the
    ``ccr_sa_ccr`` stage whose conservative fallbacks it reports.

Key responsibilities:
- CCR021 — a derivative trade whose ``asset_class`` is missing or is not one of
  the six CRR Art. 277(1) risk categories. engine/ccr prices it in the
  other-risks category (Art. 280f, SF 8%) as its own hedging set.
- CCR022 — a credit trade whose ``credit_quality``, or a commodity trade whose
  ``commodity_type``, is missing or outside its supervisory-factor table.
  engine/ccr gives it the highest factor of that table.
- CCR023 — a derivative trade whose ``netting_set_id`` names no netting-set row.
  engine/ccr prices it as its own non-enforceable netting set with no
  counterparty instead of dropping it.
- Flag exactly the trades engine/ccr applies a fallback to: the predicates read
  the same recognised-value sets (``data/schemas.py``) and the same case folding
  (trim; lower-case asset class; upper-case quality / type) as
  ``engine/ccr/risk_categories.py``. Before review CC-06 each of these inputs
  gave its netting set a silently zero add-on (or lost the trade) with no error.

References:
- CRR Art. 277(1) (six risk categories); Art. 277a(1)(c)/(e) (credit / commodity
  hedging sets); Art. 280 (supervisory factors); Art. 280f (other risks).
- CRR Art. 272(4); CCR (CRR) Part Art. 274(1) (a transaction with no recognised
  netting agreement is its own netting set).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.errors import (
    ERROR_CCR_ORPHAN_TRADE,
    ERROR_CCR_UNRECOGNISED_RISK_CATEGORY,
    ERROR_CCR_UNRECOGNISED_RISK_FACTOR,
    CalculationError,
)
from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.schemas import (
    VALID_SA_CCR_ASSET_CLASSES,
    VALID_SA_CCR_COMMODITY_TYPES,
    VALID_SA_CCR_CREDIT_QUALITIES,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import RawDataBundle

#: The trade columns the checks read. Injected as typed nulls when an in-memory
#: frame omits one, so the plan can never fail the gate's shared collect.
_READ_COLUMNS = {
    name: ColumnSpec(dtype, required=False)
    for name, dtype in (
        ("trade_id", pl.String),
        ("netting_set_id", pl.String),
        ("transaction_type", pl.String),
        ("asset_class", pl.String),
        ("credit_quality", pl.String),
        ("commodity_type", pl.String),
    )
}

_NETTING_SET_READ_COLUMNS = {"counterparty_reference": ColumnSpec(pl.String, required=False)}

#: (code, field, finding flag, what engine/ccr does instead, citation) per finding.
_FINDINGS = (
    (
        ERROR_CCR_UNRECOGNISED_RISK_CATEGORY,
        "asset_class",
        "_unrecognised_category",
        "is not an SA-CCR risk category; the trade is priced in the other-risks "
        "category (Art. 280f, SF 8%) as its own hedging set",
        "CRR Art. 277(1); Art. 280f",
    ),
    (
        ERROR_CCR_UNRECOGNISED_RISK_FACTOR,
        "credit_quality",
        "_unrecognised_credit_quality",
        "is outside the credit supervisory-factor table; the trade takes the "
        "highest factor of its single-name / index table",
        "CRR Art. 277a(1)(c); Art. 280",
    ),
    (
        ERROR_CCR_UNRECOGNISED_RISK_FACTOR,
        "commodity_type",
        "_unrecognised_commodity_type",
        "is outside the commodity supervisory-factor table; the trade is assigned "
        "to the commodity hedging set with the highest factor",
        "CRR Art. 277a(1)(e); Art. 280",
    ),
    (
        ERROR_CCR_ORPHAN_TRADE,
        "netting_set_id",
        "_orphan",
        "names no row in ccr.netting_sets; the trade is priced as its own "
        "non-enforceable netting set with no counterparty (unrated fallback risk "
        "weight, alpha 1.4) — an entity-scoped run, which keeps trades only "
        "through their netting set's booking, excludes it",
        "CRR Art. 272(4); CCR (CRR) Part Art. 274(1)",
    ),
)

_EXPECTED = {
    "asset_class": ", ".join(sorted(VALID_SA_CCR_ASSET_CLASSES)),
    "credit_quality": ", ".join(sorted(VALID_SA_CCR_CREDIT_QUALITIES)),
    "commodity_type": ", ".join(sorted(VALID_SA_CCR_COMMODITY_TYPES)),
    "netting_set_id": "a ccr.netting_sets netting_set_id",
}


def ccr_trade_findings(
    bundle: RawDataBundle,
    trade_columns: frozenset[str],
) -> pl.LazyFrame | None:
    """The lazy plan of SA-CCR trade-input findings for ``bundle``, or None.

    One row per derivative trade (``transaction_type`` not ``"sft"`` — those are
    CCR020's and never reach the Art. 274 chain) that trips at least one finding,
    carrying ``trade_id``, ``netting_set_id``, the counterparty of its netting set,
    the raw values of the three checked columns and one Boolean flag per finding.

    Args:
        bundle: The raw input bundle.
        trade_columns: The ``ccr.trades`` frame's column names, already resolved
            by the input gate (``validation._table_column_names``).

    Returns:
        The findings plan, or None when the bundle has no CCR book.
    """
    if bundle.ccr is None:
        return None
    trades = ensure_columns(bundle.ccr.trades.trades, _READ_COLUMNS, present=trade_columns)
    netting_sets = (
        ensure_columns(bundle.ccr.netting_sets.netting_sets, _NETTING_SET_READ_COLUMNS)
        .select(
            pl.col("netting_set_id").cast(pl.String),
            pl.col("counterparty_reference").cast(pl.String),
            pl.lit(True).alias("_ns_present"),
        )
        .unique(subset="netting_set_id", keep="first")
        .filter(pl.col("netting_set_id").is_not_null())
    )

    asset = pl.col("asset_class").cast(pl.String).str.strip_chars().str.to_lowercase()
    quality = pl.col("credit_quality").cast(pl.String).str.strip_chars().str.to_uppercase()
    commodity = pl.col("commodity_type").cast(pl.String).str.strip_chars().str.to_uppercase()
    recognised = asset.is_in(sorted(VALID_SA_CCR_ASSET_CLASSES)).fill_null(False)

    flags = trades.filter(pl.col("transaction_type").cast(pl.String).ne_missing("sft")).select(
        pl.col("trade_id").cast(pl.String),
        pl.col("netting_set_id").cast(pl.String),
        pl.col("asset_class").cast(pl.String),
        pl.col("credit_quality").cast(pl.String),
        pl.col("commodity_type").cast(pl.String),
        (~recognised).alias("_unrecognised_category"),
        (
            recognised
            & (asset == "credit")
            & ~quality.is_in(sorted(VALID_SA_CCR_CREDIT_QUALITIES)).fill_null(False)
        ).alias("_unrecognised_credit_quality"),
        (
            recognised
            & (asset == "commodity")
            & ~commodity.is_in(sorted(VALID_SA_CCR_COMMODITY_TYPES)).fill_null(False)
        ).alias("_unrecognised_commodity_type"),
    )
    return (
        flags.join(netting_sets, on="netting_set_id", how="left")
        .with_columns(pl.col("_ns_present").is_null().alias("_orphan"))
        .filter(
            pl.any_horizontal(
                "_unrecognised_category",
                "_unrecognised_credit_quality",
                "_unrecognised_commodity_type",
                "_orphan",
            )
        )
        .sort("trade_id", nulls_last=True)
    )


def ccr_trade_errors(findings: pl.DataFrame, sample_cap: int = 5) -> list[CalculationError]:
    """Turn the collected :func:`ccr_trade_findings` frame into CCR021/022/023 errors.

    Follows the input gate's sampling contract: up to ``sample_cap`` row-named
    ERRORs per (code, field), then one summary ERROR carrying the truthful count
    of the rows it omits.

    Args:
        findings: The collected findings frame.
        sample_cap: Maximum row-named errors per (code, field).

    Returns:
        The errors, in finding order (CCR021, CCR022 credit, CCR022 commodity,
        CCR023).
    """
    errors: list[CalculationError] = []
    for code, field, flag, treatment, citation in _FINDINGS:
        rows = findings.filter(pl.col(flag))
        errors.extend(
            _row_error(code, field, row, treatment, citation)
            for row in rows.head(sample_cap).iter_rows(named=True)
        )
        omitted = rows.height - min(rows.height, sample_cap)
        if omitted:
            errors.append(
                CalculationError(
                    code=code,
                    message=(
                        f"[ccr.trades] '{field}': {omitted} additional trade(s) with the same "
                        f"finding omitted beyond sample_cap={sample_cap}"
                    ),
                    severity=ErrorSeverity.ERROR,
                    category=ErrorCategory.DATA_QUALITY,
                    regulatory_reference=citation,
                    field_name=field,
                    expected_value=_EXPECTED[field],
                )
            )
    return errors


def _row_error(
    code: str,
    field: str,
    row: Mapping[str, object],
    treatment: str,
    citation: str,
) -> CalculationError:
    """One row-named CCR021/022/023 error for the trade in ``row``."""
    value = row[field]
    shown = "null" if value is None else f"'{value}'"
    return CalculationError(
        code=code,
        message=(
            f"[ccr.trades] trade '{row['trade_id']}' (netting set "
            f"'{row['netting_set_id']}'): {field} {shown} {treatment}."
        ),
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.DATA_QUALITY,
        counterparty_reference=_optional_str(row.get("counterparty_reference")),
        regulatory_reference=citation,
        field_name=field,
        expected_value=_EXPECTED[field],
        actual_value="null" if value is None else str(value),
    )


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)
