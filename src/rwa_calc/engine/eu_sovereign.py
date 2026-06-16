"""
EU member-state sovereign domestic-currency expression helpers.

Pipeline position:
    Consumed by the SA risk-weight + guarantee-substitution paths
    (``sa/risk_weights.py``, ``sa/rw_adjustments.py``), the IRB guarantee path
    (``irb/guarantee.py``), the CRM guarantee path (``crm/guarantees.py``) and
    the approach classifier (``stages/classify/approach.py``) to identify EU
    domestic-currency central-government / central-bank exposures eligible for
    the Art. 114(4)/(7) 0% risk weight.

Key responsibilities:
- Rebind the cited ``eu_country_domestic_currency`` rulepack ``CategoryMap``
  (country -> domestic currency, CRR Art. 114(4)/(7)) into a plain ``dict`` for
  ``Expr.replace_strict`` — the rulepack is the value home; this module is the
  consumer-side binding so the engine never imports ``data/tables``.
- Build the domestic-currency-match / domestic-CGCB-guarantor boolean
  expressions and the pre-FX denomination-currency selector.

References:
- CRR Art. 114(4)/(7): 0% RW for EU CGCB in a member state's domestic currency
- CRR Art. 141: domestic-currency denomination matching
- CRE20.9: Basel 3.1 equivalent domestic sovereign treatment
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl
from watchfire import cites

from rwa_calc.rulebook.resolve import resolve

logger = logging.getLogger(__name__)

# Country -> domestic currency map, rebound from the common pack once at module
# load (regime-invariant — resolve against "crr"; b31 inherits the same entry).
_PACK = resolve("crr", date(2026, 1, 1))
_EU_COUNTRY_DOMESTIC_CURRENCY: dict[str, str] = dict(
    _PACK.category_map("eu_country_domestic_currency").entries
)


@cites("CRR Art. 114")
@cites("CRR Art. 141")
def build_eu_domestic_currency_expr(
    country_col: str,
    currency_col: str | pl.Expr = "currency",
) -> pl.Expr:
    """
    Build a Polars expression that checks if an exposure is to an EU member
    state's central government/central bank denominated in that state's
    domestic currency.

    Uses replace_strict to map country code → domestic currency, then compares
    with the exposure denomination currency.

    Args:
        country_col: Column name containing the ISO country code
        currency_col: Column name (str) or Polars expression for the
            exposure's denomination currency. A string is wrapped in
            ``pl.col(...)``. Callers operating on a post-FX-conversion
            LazyFrame should pass ``denomination_currency_expr(...)`` so the
            original (pre-conversion) currency is compared — not the reporting
            currency.

    Returns:
        Boolean Polars expression: True when country is EU and currency matches
        that country's domestic currency.
    """
    currency_expr = pl.col(currency_col) if isinstance(currency_col, str) else currency_col
    return (
        pl.col(country_col)
        .fill_null("")
        .replace_strict(_EU_COUNTRY_DOMESTIC_CURRENCY, default=None)
        .eq(currency_expr)
    )


@cites("CRR Art. 114")
def build_domestic_cgcb_guarantor_expr(
    country_col: str,
    currency_col: str | pl.Expr,
) -> pl.Expr:
    """
    Build a Polars expression that identifies a domestic-currency CGCB guarantor
    under CRR Art. 114(4) and Art. 114(7) (Basel 3.1 preservation).

    Combines the UK (GB/GBP) and EU (member state / member-state-domestic-currency)
    branches into a single boolean expression.

    Callers pass the guarantor's country code column and the currency column to
    test against. For guarantee substitution (Art. 215-217) the currency column
    should be the **guarantee** currency — the Art. 233(3) 8% FX haircut handles
    any mismatch between the guarantee and the underlying exposure separately.

    Args:
        country_col: Column name containing the guarantor's ISO country code.
        currency_col: Column name (str) or Polars expression for the currency
            to test against the guarantor's domestic currency.

    Returns:
        Boolean Polars expression: True when the guarantor is UK CGCB in GBP or
        an EU-member CGCB in that member state's domestic currency.
    """
    currency_expr = pl.col(currency_col) if isinstance(currency_col, str) else currency_col
    is_uk_domestic = (pl.col(country_col).fill_null("") == "GB") & (currency_expr == "GBP")
    is_eu_domestic = build_eu_domestic_currency_expr(country_col, currency_expr)
    return is_uk_domestic | is_eu_domestic


def denomination_currency_expr(schema_names: list[str] | set[str]) -> pl.Expr:
    """
    Return the expression for an exposure's denomination (pre-FX) currency.

    The pipeline's FX converter (``engine/fx_converter.py``) overwrites
    ``currency`` with the reporting currency and stores the original
    denomination in ``original_currency``. Every check that compares the
    exposure's currency against a regulatory domestic currency (CRR Art. 114(4)
    /(7), Art. 115(5)) must use the pre-conversion denomination — the
    reporting currency is irrelevant to Art. 114(4).

    This helper returns ``pl.col("original_currency")`` if it exists in the
    schema, else falls back to ``pl.col("currency")`` (matches unit tests and
    pipelines where FX conversion is skipped).

    Args:
        schema_names: Column names from ``lf.collect_schema().names()``.

    Returns:
        Polars expression yielding the denomination currency per row.
    """
    names = set(schema_names)
    if "original_currency" in names:
        return pl.col("original_currency")
    return pl.col("currency")
