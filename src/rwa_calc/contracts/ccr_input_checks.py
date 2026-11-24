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
- CCR035 (WARNING, P1.406) — an equity or commodity trade with no
  ``market_price`` x ``number_of_units``: engine/ccr takes its ``|notional|``
  as the adjusted notional (Art. 279b(1)(c), a transaction "contractually
  expressed as a notional amount") instead of the null product that used to
  leave the trade out of the add-on. A separate plan (:func:`ccr_notional_limb_findings`)
  because the treatment is the article's own limb, not a fallback. CCR038
  (ERROR) instead when that notional is 0 or null: neither limb gives the trade
  an adjusted notional, so it adds nothing to its add-on.
- CCR036 (WARNING) / CCR037 (ERROR), P1.406 — an FX trade with no
  ``notional_leg2``: engine/ccr takes its first leg's notional as the adjusted
  notional. CCR036 when ``currency_leg2`` is null too (read as a transaction of
  one payment leg, Art. 279b(1)(b)(i), whose pair is not stated: its own FX
  hedging set); CCR037 when ``currency_leg2`` is stated and the rule needs that
  leg's unknown notional (the value is an estimate: its own FX hedging set).
  Not reported when the stated second leg is the reporting currency: rule (ii)
  then takes the first leg's notional at spot, the trade's complete value.
  CCR037 therefore reads the run's reporting currency and, like DQ020, is raised
  only by the configured (pipeline-entry) call. Before P1.406 such a trade could
  price at zero, or net its estimate against the pair's other trades, with no
  error (:func:`ccr_fx_second_leg_findings`).

References:
- CRR Art. 277(1) (six risk categories); Art. 277a(1)(c)/(e) (credit / commodity
  hedging sets); Art. 280 (supervisory factors); Art. 280f (other risks).
- CRR Art. 272(4); CCR (CRR) Part Art. 274(1) (a transaction with no recognised
  netting agreement is its own netting set).
- CCR (CRR) Part Art. 279b(1)(c) (equity / commodity adjusted notional: market
  price x units, or the notional of a transaction expressed as one).
- CCR (CRR) Part Art. 279b(1)(b) (FX adjusted notional: one payment leg, or the
  legs' notionals); Art. 277a(1)(b) (an FX hedging set is one currency pair).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.errors import (
    ERROR_CCR_FX_SECOND_LEG_NOTIONAL_MISSING,
    ERROR_CCR_FX_SINGLE_PAYMENT_LEG,
    ERROR_CCR_NO_ADJUSTED_NOTIONAL,
    ERROR_CCR_NOTIONAL_LIMB_APPLIED,
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

#: The extra trade columns the CCR035 notional-limb check reads.
_UNIT_READ_COLUMNS = {
    name: ColumnSpec(dtype, required=False)
    for name, dtype in (
        ("market_price", pl.Float64),
        ("number_of_units", pl.Float64),
        ("notional", pl.Float64),
        ("currency", pl.String),
    )
}

#: The SA-CCR risk categories whose Art. 279b(1)(c) adjusted notional is market
#: price x number of units (or the notional) — routing tokens of
#: VALID_SA_CCR_ASSET_CLASSES, not regulatory values.
_UNIT_PRICED_CATEGORIES = ("equity", "commodity")

_NOTIONAL_LIMB_CITATION = "CCR (CRR) Part Art. 279b(1)(c)"

#: (code, the ``_no_notional`` flag value, severity, summary field) per
#: notional-limb finding: CCR035 the limb's own value, CCR038 no value at all.
_NOTIONAL_LIMB_FINDINGS = (
    (ERROR_CCR_NOTIONAL_LIMB_APPLIED, False, ErrorSeverity.WARNING, "market_price"),
    (ERROR_CCR_NO_ADJUSTED_NOTIONAL, True, ErrorSeverity.ERROR, "notional"),
)

#: The extra trade columns the CCR036 / CCR037 FX second-leg check reads.
_FX_LEG_READ_COLUMNS = {
    name: ColumnSpec(dtype, required=False)
    for name, dtype in (
        ("notional", pl.Float64),
        ("currency", pl.String),
        ("notional_leg2", pl.Float64),
        ("currency_leg2", pl.String),
    )
}

#: The SA-CCR risk category the FX second-leg check reads — a routing token of
#: VALID_SA_CCR_ASSET_CLASSES, not a regulatory value.
_FX_CATEGORY = "fx"

#: (code, currency_leg2 stated, severity, expected value, citation) per FX
#: second-leg finding.
_FX_LEG_FINDINGS = (
    (
        ERROR_CCR_FX_SINGLE_PAYMENT_LEG,
        False,
        ErrorSeverity.WARNING,
        "a second payment leg (notional_leg2, currency_leg2), or a contract of one payment leg",
        "CCR (CRR) Part Art. 279b(1)(b)(i); Art. 277a(1)(b)",
    ),
    (
        ERROR_CCR_FX_SECOND_LEG_NOTIONAL_MISSING,
        True,
        ErrorSeverity.ERROR,
        "notional_leg2 for the stated currency_leg2",
        "CCR (CRR) Part Art. 279b(1)(b); Art. 277a(1)(b)",
    ),
)

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


def ccr_notional_limb_findings(
    bundle: RawDataBundle,
    trade_columns: frozenset[str],
) -> pl.LazyFrame | None:
    """The lazy plan of the CCR035 / CCR038 notional-limb findings for ``bundle``, or None.

    One row per derivative trade (``transaction_type`` not ``"sft"``) whose
    ``asset_class`` folds (trim, lower-case — as ``engine/ccr`` folds it) to
    ``equity`` or ``commodity`` and whose ``market_price`` or
    ``number_of_units`` is null: exactly the trades
    ``engine/ccr/adjusted_notional.py`` prices on ``|notional|``. Carries
    ``trade_id``, ``netting_set_id``, the counterparty of its netting set,
    ``asset_class``, the two unit inputs, ``notional``, ``currency`` and
    ``_no_notional`` — the notional is null or 0, so the engine's adjusted
    notional is null or 0 and the trade adds nothing to its add-on (CCR038,
    else CCR035).

    Args:
        bundle: The raw input bundle.
        trade_columns: The ``ccr.trades`` frame's column names, already resolved
            by the input gate.

    Returns:
        The findings plan, or None when the bundle has no CCR book.
    """
    if bundle.ccr is None:
        return None
    trades = ensure_columns(
        bundle.ccr.trades.trades, {**_READ_COLUMNS, **_UNIT_READ_COLUMNS}, present=trade_columns
    )
    asset = pl.col("asset_class").cast(pl.String).str.strip_chars().str.to_lowercase()
    unit_priced = (pl.col("market_price") * pl.col("number_of_units")).is_not_null()
    return (
        trades.filter(
            pl.col("transaction_type").cast(pl.String).ne_missing("sft")
            & asset.is_in(_UNIT_PRICED_CATEGORIES).fill_null(False)
            & ~unit_priced
        )
        .select(
            pl.col("trade_id").cast(pl.String),
            pl.col("netting_set_id").cast(pl.String),
            asset.alias("asset_class"),
            pl.col("market_price").cast(pl.Float64),
            pl.col("number_of_units").cast(pl.Float64),
            pl.col("notional").cast(pl.Float64),
            pl.col("currency").cast(pl.String),
            # Kleene OR: a null notional is True on its own, no fill needed.
            (pl.col("notional").is_null() | (pl.col("notional") == 0.0)).alias("_no_notional"),
        )
        .join(
            _netting_set_counterparties(bundle.ccr.netting_sets.netting_sets),
            on="netting_set_id",
            how="left",
        )
        .sort("trade_id", nulls_last=True)
    )


def ccr_notional_limb_errors(findings: pl.DataFrame, sample_cap: int = 5) -> list[CalculationError]:
    """Turn the collected :func:`ccr_notional_limb_findings` frame into CCR035 / CCR038.

    Follows the input gate's sampling contract: up to ``sample_cap`` row-named
    entries per code, then one summary carrying the truthful count of the rows
    it omits — CCR035 a WARNING (the trade is priced on its notional), CCR038 an
    ERROR (its notional is 0 or null, so it is priced at zero).

    Args:
        findings: The collected findings frame.
        sample_cap: Maximum row-named entries per code.

    Returns:
        The errors, CCR035 first.
    """
    errors: list[CalculationError] = []
    for code, no_notional, severity, field in _NOTIONAL_LIMB_FINDINGS:
        rows = findings.filter(pl.col("_no_notional") == no_notional)
        errors.extend(
            _notional_limb_error(row) if not no_notional else _no_adjusted_notional_error(row)
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
                    severity=severity,
                    category=ErrorCategory.DATA_QUALITY,
                    regulatory_reference=_NOTIONAL_LIMB_CITATION,
                    field_name=field,
                )
            )
    return errors


def ccr_fx_second_leg_findings(
    bundle: RawDataBundle,
    trade_columns: frozenset[str],
    *,
    base_currency: str | None,
) -> pl.LazyFrame | None:
    """The lazy plan of the CCR036 / CCR037 FX second-leg findings, or None.

    One row per derivative trade (``transaction_type`` not ``"sft"``) whose
    ``asset_class`` folds (trim, lower-case — as ``engine/ccr`` folds it) to
    ``fx`` and whose ``notional_leg2`` is null — the trades
    ``engine/ccr/adjusted_notional.py::compute_adjusted_notional_fx`` prices on
    the first leg's notional — except a trade whose stated ``currency_leg2`` is
    ``base_currency`` and whose ``currency`` is not: Art. 279b(1)(b)(ii) takes
    "the notional amount of the other payment leg", the first leg at spot, so
    its missing notional is never needed (the engine nets it in its pair, and a
    first leg with no rate is CCR026's). Carries ``trade_id``,
    ``netting_set_id``, the counterparty of its netting set, ``notional``,
    ``currency``, ``currency_leg2`` and ``_leg2_stated`` (``currency_leg2`` not
    null: CCR037, else CCR036). A frame that omits the two optional second-leg
    columns reads them as null — every FX trade then has no second leg.

    CCR037 depends on the reporting currency, so with ``base_currency`` None
    (the configless file-loader call) only the CCR036 rows are planned; the
    configured pipeline-entry call adds the CCR037 rows, which its de-duplication
    against the loader's errors keeps (as for DQ020).

    Args:
        bundle: The raw input bundle.
        trade_columns: The ``ccr.trades`` frame's column names, already resolved
            by the input gate.
        base_currency: The run's reporting currency
            (``CalculationConfig.base_currency``), or None when the caller has no
            configuration.

    Returns:
        The findings plan, or None when the bundle has no CCR book.
    """
    if bundle.ccr is None:
        return None
    trades = ensure_columns(
        bundle.ccr.trades.trades, {**_READ_COLUMNS, **_FX_LEG_READ_COLUMNS}, present=trade_columns
    )
    asset = pl.col("asset_class").cast(pl.String).str.strip_chars().str.to_lowercase()
    leg2 = pl.col("currency_leg2").cast(pl.String)
    if base_currency is None:
        reported_leg2 = leg2.is_null()
    else:
        # The engine's own test (compute_adjusted_notional_fx): an exact match.
        leg1_is_base = pl.col("currency").cast(pl.String).eq_missing(pl.lit(base_currency))
        reported_leg2 = ~(leg2.eq_missing(pl.lit(base_currency)) & ~leg1_is_base)
    return (
        trades.filter(
            pl.col("transaction_type").cast(pl.String).ne_missing("sft")
            & asset.eq_missing(_FX_CATEGORY)
            & pl.col("notional_leg2").is_null()
            & reported_leg2
        )
        .select(
            pl.col("trade_id").cast(pl.String),
            pl.col("netting_set_id").cast(pl.String),
            pl.col("notional").cast(pl.Float64),
            pl.col("currency").cast(pl.String),
            pl.col("currency_leg2").cast(pl.String),
            pl.col("currency_leg2").is_not_null().alias("_leg2_stated"),
        )
        .join(
            _netting_set_counterparties(bundle.ccr.netting_sets.netting_sets),
            on="netting_set_id",
            how="left",
        )
        .sort("trade_id", nulls_last=True)
    )


def ccr_fx_second_leg_errors(findings: pl.DataFrame, sample_cap: int = 5) -> list[CalculationError]:
    """Turn the collected :func:`ccr_fx_second_leg_findings` frame into CCR036 / CCR037.

    Follows the input gate's sampling contract: up to ``sample_cap`` row-named
    entries per code, then one summary carrying the truthful count of the rows
    it omits — CCR036 a WARNING, CCR037 an ERROR.

    Args:
        findings: The collected findings frame.
        sample_cap: Maximum row-named entries per code.

    Returns:
        The errors, CCR036 first.
    """
    errors: list[CalculationError] = []
    for code, stated, severity, expected, citation in _FX_LEG_FINDINGS:
        rows = findings.filter(pl.col("_leg2_stated") == stated)
        errors.extend(
            _fx_second_leg_error(code, severity, expected, citation, row)
            for row in rows.head(sample_cap).iter_rows(named=True)
        )
        omitted = rows.height - min(rows.height, sample_cap)
        if omitted:
            errors.append(
                CalculationError(
                    code=code,
                    message=(
                        f"[ccr.trades] 'notional_leg2': {omitted} additional trade(s) with "
                        f"the same finding omitted beyond sample_cap={sample_cap}"
                    ),
                    severity=severity,
                    category=ErrorCategory.DATA_QUALITY,
                    regulatory_reference=citation,
                    field_name="notional_leg2",
                    expected_value=expected,
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


def _notional_limb_error(row: Mapping[str, object]) -> CalculationError:
    """One row-named CCR035 warning for the equity / commodity trade in ``row``."""
    price, units = row["market_price"], row["number_of_units"]
    shown_notional = _amount(row["notional"])
    return CalculationError(
        code=ERROR_CCR_NOTIONAL_LIMB_APPLIED,
        message=(
            f"[ccr.trades] {row['asset_class']} trade '{row['trade_id']}' (netting set "
            f"'{row['netting_set_id']}'): market_price {_shown(price)}, number_of_units "
            f"{_shown(units)} - no market price x number of units, so the trade is read "
            "as contractually expressed as a notional amount and its notional "
            f"{shown_notional} ({_shown(row['currency'])}) is the adjusted notional."
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        counterparty_reference=_optional_str(row.get("counterparty_reference")),
        regulatory_reference=_NOTIONAL_LIMB_CITATION,
        field_name="market_price" if price is None else "number_of_units",
        expected_value="market_price and number_of_units, or a notional-expressed contract",
        actual_value=f"market_price={_shown(price)}, number_of_units={_shown(units)}",
    )


def _no_adjusted_notional_error(row: Mapping[str, object]) -> CalculationError:
    """One row-named CCR038 error for the equity / commodity trade in ``row``."""
    price, units = row["market_price"], row["number_of_units"]
    shown_notional = _amount(row["notional"])
    return CalculationError(
        code=ERROR_CCR_NO_ADJUSTED_NOTIONAL,
        message=(
            f"[ccr.trades] {row['asset_class']} trade '{row['trade_id']}' (netting set "
            f"'{row['netting_set_id']}'): market_price {_shown(price)}, number_of_units "
            f"{_shown(units)} and notional {shown_notional} - neither market price x number "
            "of units nor a notional amount, so the trade has no Art. 279b(1)(c) adjusted "
            f"notional and adds nothing to the {row['asset_class']} add-on."
        ),
        severity=ErrorSeverity.ERROR,
        category=ErrorCategory.DATA_QUALITY,
        counterparty_reference=_optional_str(row.get("counterparty_reference")),
        regulatory_reference=_NOTIONAL_LIMB_CITATION,
        field_name="notional",
        expected_value="market_price and number_of_units, or a non-zero notional",
        actual_value=f"notional={shown_notional}",
    )


def _fx_second_leg_error(
    code: str,
    severity: ErrorSeverity,
    expected: str,
    citation: str,
    row: Mapping[str, object],
) -> CalculationError:
    """One row-named CCR036 / CCR037 entry for the FX trade in ``row``."""
    leg2 = row["currency_leg2"]
    first_leg = f"{_amount(row['notional'])} ({_shown(row['currency'])})"
    prefix = f"[ccr.trades] FX trade '{row['trade_id']}' (netting set '{row['netting_set_id']}'): "
    if leg2 is None:
        treatment = (
            "notional_leg2 and currency_leg2 null - no second payment leg, so the trade is "
            "read as a transaction of one payment leg (Art. 279b(1)(b)(i)) and its notional "
            f"{first_leg} is the adjusted notional; with no currency pair stated it is its "
            "own FX hedging set, offsetting none of the netting set's other FX trades."
        )
    else:
        treatment = (
            f"currency_leg2 {leg2} is stated but notional_leg2 is null - the Art. 279b(1)(b) "
            "adjusted notional needs the second payment leg's notional, which is unknown, so "
            f"the first leg's notional {first_leg}, at spot, stands in for it as an estimate "
            "and the trade is its own FX hedging set, offsetting none of the pair's other "
            "trades."
        )
    return CalculationError(
        code=code,
        message=prefix + treatment,
        severity=severity,
        category=ErrorCategory.DATA_QUALITY,
        counterparty_reference=_optional_str(row.get("counterparty_reference")),
        regulatory_reference=citation,
        field_name="notional_leg2",
        expected_value=expected,
        actual_value=f"notional_leg2=null, currency_leg2={_shown(leg2)}",
    )


def _netting_set_counterparties(netting_sets: pl.LazyFrame) -> pl.LazyFrame:
    """``(netting_set_id, counterparty_reference)``, one row per netting set."""
    return (
        ensure_columns(netting_sets, _NETTING_SET_READ_COLUMNS)
        .select(
            pl.col("netting_set_id").cast(pl.String),
            pl.col("counterparty_reference").cast(pl.String),
        )
        .unique(subset="netting_set_id", keep="first")
        .filter(pl.col("netting_set_id").is_not_null())
    )


def _amount(value: object) -> str:
    return f"{abs(value):,.2f}" if isinstance(value, int | float) else "null"


def _shown(value: object) -> str:
    return "null" if value is None else f"{value}"


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)
