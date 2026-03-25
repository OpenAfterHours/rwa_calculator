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

EU_MEMBER_STATES: frozenset[str] = frozenset({
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
})

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
    currency_col: str = "currency",
) -> pl.Expr:
    """
    Build a Polars expression that checks if an exposure is to an EU member
    state's central government/central bank denominated in that state's
    domestic currency.

    Uses replace_strict to map country code → domestic currency, then compares
    with the exposure currency column.

    Args:
        country_col: Column name containing the ISO country code
        currency_col: Column name containing the exposure currency

    Returns:
        Boolean Polars expression: True when country is EU and currency matches
        that country's domestic currency.
    """
    return (
        pl.col(country_col)
        .fill_null("")
        .replace_strict(EU_COUNTRY_DOMESTIC_CURRENCY, default=None)
        .eq(pl.col(currency_col))
    )
