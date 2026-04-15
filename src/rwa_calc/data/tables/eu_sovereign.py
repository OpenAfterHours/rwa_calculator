"""
EU member state sovereign treatment constants.

Provides EU member state country codes and domestic currency mappings
for the Art. 114(4) 0% risk weight treatment of central government
and central bank exposures denominated in domestic currency.

Pipeline position:
    Used by SA Calculator, IRB Namespace, and Classifier to identify
    EU domestic sovereign exposures eligible for preferential treatment.

Key responsibilities:
- EU member state ISO country code set
- Country-to-domestic-currency mapping (EUR for eurozone, local for others)
- Polars expression helper for domestic currency matching

References:
- CRR Art. 114(4): 0% RW for EU CGCB in domestic currency of any member state
- CRE20.9: Basel 3.1 equivalent domestic sovereign treatment
"""

from __future__ import annotations

import polars as pl

# =============================================================================
# EU MEMBER STATES (ISO 3166-1 alpha-2 codes)
# 27 member states as of 2025
# =============================================================================

EU_MEMBER_STATES: frozenset[str] = frozenset(
    {
        "AT",  # Austria
        "BE",  # Belgium
        "BG",  # Bulgaria
        "HR",  # Croatia
        "CY",  # Cyprus
        "CZ",  # Czechia
        "DK",  # Denmark
        "EE",  # Estonia
        "FI",  # Finland
        "FR",  # France
        "DE",  # Germany
        "GR",  # Greece
        "HU",  # Hungary
        "IE",  # Ireland
        "IT",  # Italy
        "LV",  # Latvia
        "LT",  # Lithuania
        "LU",  # Luxembourg
        "MT",  # Malta
        "NL",  # Netherlands
        "PL",  # Poland
        "PT",  # Portugal
        "RO",  # Romania
        "SK",  # Slovakia
        "SI",  # Slovenia
        "ES",  # Spain
        "SE",  # Sweden
    }
)

# =============================================================================
# DOMESTIC CURRENCY PER EU MEMBER STATE
# Eurozone members use EUR; non-euro members use their national currency.
# =============================================================================

EU_COUNTRY_DOMESTIC_CURRENCY: dict[str, str] = {
    # Eurozone members (EUR)
    "AT": "EUR",
    "BE": "EUR",
    "HR": "EUR",
    "CY": "EUR",
    "EE": "EUR",
    "FI": "EUR",
    "FR": "EUR",
    "DE": "EUR",
    "GR": "EUR",
    "IE": "EUR",
    "IT": "EUR",
    "LV": "EUR",
    "LT": "EUR",
    "LU": "EUR",
    "MT": "EUR",
    "NL": "EUR",
    "PT": "EUR",
    "SK": "EUR",
    "SI": "EUR",
    "ES": "EUR",
    # Non-euro EU members
    "BG": "BGN",  # Bulgarian lev
    "CZ": "CZK",  # Czech koruna
    "DK": "DKK",  # Danish krone
    "HU": "HUF",  # Hungarian forint
    "PL": "PLN",  # Polish zloty
    "RO": "RON",  # Romanian leu
    "SE": "SEK",  # Swedish krona
}


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
        .replace_strict(EU_COUNTRY_DOMESTIC_CURRENCY, default=None)
        .eq(currency_expr)
    )


def build_domestic_cgcb_guarantor_expr(
    country_col: str,
    currency_col: str | pl.Expr,
) -> pl.Expr:
    """
    Build a Polars expression that identifies a domestic-currency CGCB guarantor
    under CRR Art. 114(3)/(4) and Art. 114(7) (Basel 3.1 preservation).

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
    exposure's currency against a regulatory domestic currency (CRR Art. 114(3)
    /(4), Art. 115(5)) must use the pre-conversion denomination — the
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
