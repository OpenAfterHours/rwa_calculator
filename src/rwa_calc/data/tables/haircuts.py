"""
CRM supervisory haircuts — CRR Art. 224 and PRA PS1/26 Art. 224.

Canonical home for both the CRR and Basel 3.1 collateral haircut tables;
framework selection happens at the call site via ``CalculationConfig``.
Provides the haircut dicts plus Polars DataFrame views for efficient joins
in the RWA calculation pipeline.

All haircut values are the 10-business-day base haircuts (Art. 224(2)(b) default).
For other liquidation periods, use ``scale_haircut_for_liquidation_period()``:
- 5 days: repo-style transactions (Art. 224(2)(a))
- 10 days: other capital market transactions (Art. 224(2)(b))  [default]
- 20 days: secured lending (Art. 224(2)(c))

Key differences under Basel 3.1 (PRA PS1/26 Art. 224 Table 1):
- 5 maturity bands (0-1y, 1-3y, 3-5y, 5-10y, 10y+) instead of CRR's 3 (0-1y, 1-5y, 5y+)
- Corporate/institution CQS 1 10y+ steps up to 12% (CRR 5y+: 8%)
- Corporate/institution CQS 2-3 10y+ steps up to 20% (CRR 5y+: 12%)
- Higher equity haircuts (main index: 20%, other: 30%)  — CRR: 15%/25%
- Gold haircut increased to 20% (CRR: 15%)
- Sovereign CQS 2-3 caps at 6% even at 10y+ (same as CRR 5y+) — 5-band split
  is not a penal re-scale for well-rated sovereigns.

Reference:
    CRR Art. 224: Supervisory haircuts under the FCCM
    PRA PS1/26 Art. 224: Basel 3.1 supervisory haircuts (Tables 1-4)
    Art. 226: Scaling to different holding/liquidation periods
"""

from __future__ import annotations

import math
from decimal import Decimal

import polars as pl

# =============================================================================
# CRR SUPERVISORY HAIRCUTS (CRR Art. 224)
# =============================================================================
# CRR uses 3 maturity bands: 0-1y, 1-5y, 5y+

COLLATERAL_HAIRCUTS: dict[str, Decimal] = {
    # Cash and equivalents
    "cash": Decimal("0.00"),
    "gold": Decimal("0.15"),
    # Government bonds by CQS and maturity band
    "govt_bond_cqs1_0_1y": Decimal("0.005"),
    "govt_bond_cqs1_1_5y": Decimal("0.02"),
    "govt_bond_cqs1_5y_plus": Decimal("0.04"),
    "govt_bond_cqs2_3_0_1y": Decimal("0.01"),
    "govt_bond_cqs2_3_1_5y": Decimal("0.03"),
    "govt_bond_cqs2_3_5y_plus": Decimal("0.06"),
    # Government bonds CQS 4 (BB+ to BB-) — Art. 197(1)(b): eligible, Art. 224 Table 1: 15%
    "govt_bond_cqs4_0_1y": Decimal("0.15"),
    "govt_bond_cqs4_1_5y": Decimal("0.15"),
    "govt_bond_cqs4_5y_plus": Decimal("0.15"),
    # Corporate bonds by CQS and maturity band (CRR Art. 224 Table 1)
    # CQS 1 (AAA to AA-) — lower haircuts
    "corp_bond_cqs1_0_1y": Decimal("0.01"),
    "corp_bond_cqs1_1_5y": Decimal("0.04"),
    "corp_bond_cqs1_5y_plus": Decimal("0.08"),
    # CQS 2-3 (A+ to BBB-) — higher haircuts
    "corp_bond_cqs2_3_0_1y": Decimal("0.02"),
    "corp_bond_cqs2_3_1_5y": Decimal("0.06"),
    "corp_bond_cqs2_3_5y_plus": Decimal("0.12"),
    # Note: Corp/institution bonds CQS 4-6 are ineligible per Art. 197(1)(d)
    # Equity
    "equity_main_index": Decimal("0.15"),
    "equity_other": Decimal("0.25"),
    # Non-financial collateral
    # CRR Art. 230 uses C*/C** threshold mechanism (Table 5), not HC-based formula.
    # These values are ad-hoc approximations since the code applies haircuts uniformly.
    # Receivables: effective discount from 1.25x OC ratio ≈ 20%.
    "real_estate": Decimal("0.00"),
    "receivables": Decimal("0.20"),
    "other_physical": Decimal("0.40"),
}

# =============================================================================
# BASEL 3.1 SUPERVISORY HAIRCUTS (CRE22.52-53)
# =============================================================================
# Basel 3.1 uses 5 maturity bands: 0-1y, 1-3y, 3-5y, 5-10y, 10y+

BASEL31_COLLATERAL_HAIRCUTS: dict[str, Decimal] = {
    # Cash and equivalents (unchanged)
    "cash": Decimal("0.00"),
    # Gold — PRA PS1/26 Art. 224 Table 3: 20% at 10-day (CRR: 15%)
    "gold": Decimal("0.20"),
    # Government bonds CQS 1 — same as CRR for short/medium, split long-dated
    "govt_bond_cqs1_0_1y": Decimal("0.005"),
    "govt_bond_cqs1_1_3y": Decimal("0.02"),
    "govt_bond_cqs1_3_5y": Decimal("0.02"),
    "govt_bond_cqs1_5_10y": Decimal("0.04"),
    "govt_bond_cqs1_10y_plus": Decimal("0.04"),
    # Government bonds CQS 2-3 — PRA PS1/26 Art. 224 Table 1 (entity type (b))
    # CQS 2-3 sovereigns cap at 6% even at 10y+; the 5-band split is not a
    # penal re-scale for well-rated sovereigns. Verified against ps126app1.pdf p.203.
    "govt_bond_cqs2_3_0_1y": Decimal("0.01"),
    "govt_bond_cqs2_3_1_3y": Decimal("0.03"),
    "govt_bond_cqs2_3_3_5y": Decimal("0.03"),
    "govt_bond_cqs2_3_5_10y": Decimal("0.06"),
    "govt_bond_cqs2_3_10y_plus": Decimal("0.06"),
    # Government bonds CQS 4 (BB+ to BB-) — Art. 197(1)(b): eligible, 15% flat
    "govt_bond_cqs4_0_1y": Decimal("0.15"),
    "govt_bond_cqs4_1_3y": Decimal("0.15"),
    "govt_bond_cqs4_3_5y": Decimal("0.15"),
    "govt_bond_cqs4_5_10y": Decimal("0.15"),
    "govt_bond_cqs4_10y_plus": Decimal("0.15"),
    # Corporate bonds CQS 1 (AAA to AA-) — PRA PS1/26 Art. 224 Table 1 (entity types (c)/(d))
    # Verified against ps126app1.pdf p.203.
    "corp_bond_cqs1_0_1y": Decimal("0.01"),
    "corp_bond_cqs1_1_3y": Decimal("0.03"),
    "corp_bond_cqs1_3_5y": Decimal("0.04"),
    "corp_bond_cqs1_5_10y": Decimal("0.06"),
    "corp_bond_cqs1_10y_plus": Decimal("0.12"),
    # Corporate bonds CQS 2-3 (A+ to BBB-) — PRA PS1/26 Art. 224 Table 1 (entity types (c)/(d))
    # 10y+ is 20% (not 15%, the prior flat value); intermediate bands step up
    # 4% / 6% / 12% / 20% per Table 1.
    "corp_bond_cqs2_3_0_1y": Decimal("0.02"),
    "corp_bond_cqs2_3_1_3y": Decimal("0.04"),
    "corp_bond_cqs2_3_3_5y": Decimal("0.06"),
    "corp_bond_cqs2_3_5_10y": Decimal("0.12"),
    "corp_bond_cqs2_3_10y_plus": Decimal("0.20"),
    # Equity — PRA PS1/26 Art. 224 Table 3: 20%/30% at 10-day (CRR: 15%/25%)
    "equity_main_index": Decimal("0.20"),  # CRR: 15%
    "equity_other": Decimal("0.30"),  # CRR: 25%
    # Non-financial collateral — Art. 230(2) HC values (PRA PS1/26)
    # B31 Art. 230 uses HC in LGD* formula: ES = min(C(1-HC-Hfx), E(1+HE))
    # HC=40% for all non-financial types; only LGDS differs (20% rec/RE, 25% other)
    "real_estate": Decimal("0.00"),  # Handled via LTV, not HC haircut
    "receivables": Decimal("0.40"),  # Art. 230(2): HC=40% (not LGDS=20%)
    "other_physical": Decimal("0.40"),
}

# Currency mismatch haircut — 10-day base value (Art. 224 Table 4)
# 5-day: 5.657%, 10-day: 8%, 20-day: 11.314%
FX_HAIRCUT: Decimal = Decimal("0.08")

# CDS restructuring exclusion haircut (CRR Art. 233(2) / PRA PS1/26 Art. 233(2))
# If a credit derivative does not include restructuring as a credit event,
# protection value is reduced by 40% (capped at 60% of exposure value).
RESTRUCTURING_EXCLUSION_HAIRCUT: Decimal = Decimal("0.40")


# Standard liquidation periods per Art. 224(2)
LIQUIDATION_PERIOD_REPO: int = 5  # (a) Repo-style transactions
LIQUIDATION_PERIOD_CAPITAL_MARKET: int = 10  # (b) Other capital market transactions
LIQUIDATION_PERIOD_SECURED_LENDING: int = 20  # (c) Secured lending


def scale_haircut_for_liquidation_period(
    base_haircut_10day: float,
    liquidation_period_days: int = 10,
) -> float:
    """
    Scale a 10-day base supervisory haircut for a different liquidation period.

    Art. 226(2): H_m = H_10 × sqrt(T_m / 10)

    Standard periods per Art. 224(2):
    - 5 days: repo-style transactions → haircut × sqrt(0.5) ≈ ×0.7071
    - 10 days: capital market transactions → no scaling (default)
    - 20 days: secured lending → haircut × sqrt(2) ≈ ×1.4142

    Args:
        base_haircut_10day: Haircut at 10-business-day liquidation period
        liquidation_period_days: Target liquidation period in business days

    Returns:
        Scaled haircut for the target liquidation period
    """
    if liquidation_period_days == 10 or math.isclose(base_haircut_10day, 0.0, abs_tol=1e-10):
        return base_haircut_10day
    return base_haircut_10day * math.sqrt(liquidation_period_days / 10.0)


# =============================================================================
# DATAFRAME ROW SPECIFICATIONS
#
# Each tuple is (collateral_type, cqs, maturity_band, dict_key, is_main_index).
# The haircut value itself is NOT stored here — it is looked up from the
# authoritative haircut dict via ``dict_key`` when the DataFrame is built.
# Row ordering is part of the public DataFrame contract and must be preserved.
# =============================================================================

# Each spec tuple:
#   (collateral_type, cqs, maturity_band, dict_key, is_main_index)
_HaircutRowSpec = tuple[str, int | None, str | None, str, bool | None]

_CRR_HAIRCUT_ROW_SPECS: tuple[_HaircutRowSpec, ...] = (
    # Cash and gold
    ("cash", None, None, "cash", None),
    ("gold", None, None, "gold", None),
    # Government bonds CQS 1
    ("govt_bond", 1, "0_1y", "govt_bond_cqs1_0_1y", None),
    ("govt_bond", 1, "1_5y", "govt_bond_cqs1_1_5y", None),
    ("govt_bond", 1, "5y_plus", "govt_bond_cqs1_5y_plus", None),
    # Government bonds CQS 2-3 (shared dict key)
    ("govt_bond", 2, "0_1y", "govt_bond_cqs2_3_0_1y", None),
    ("govt_bond", 2, "1_5y", "govt_bond_cqs2_3_1_5y", None),
    ("govt_bond", 2, "5y_plus", "govt_bond_cqs2_3_5y_plus", None),
    ("govt_bond", 3, "0_1y", "govt_bond_cqs2_3_0_1y", None),
    ("govt_bond", 3, "1_5y", "govt_bond_cqs2_3_1_5y", None),
    ("govt_bond", 3, "5y_plus", "govt_bond_cqs2_3_5y_plus", None),
    # Government bonds CQS 4 (BB+ to BB-)
    ("govt_bond", 4, "0_1y", "govt_bond_cqs4_0_1y", None),
    ("govt_bond", 4, "1_5y", "govt_bond_cqs4_1_5y", None),
    ("govt_bond", 4, "5y_plus", "govt_bond_cqs4_5y_plus", None),
    # Corporate bonds CQS 1 (AAA to AA-)
    ("corp_bond", 1, "0_1y", "corp_bond_cqs1_0_1y", None),
    ("corp_bond", 1, "1_5y", "corp_bond_cqs1_1_5y", None),
    ("corp_bond", 1, "5y_plus", "corp_bond_cqs1_5y_plus", None),
    # Corporate bonds CQS 2-3 (shared dict key)
    ("corp_bond", 2, "0_1y", "corp_bond_cqs2_3_0_1y", None),
    ("corp_bond", 2, "1_5y", "corp_bond_cqs2_3_1_5y", None),
    ("corp_bond", 2, "5y_plus", "corp_bond_cqs2_3_5y_plus", None),
    ("corp_bond", 3, "0_1y", "corp_bond_cqs2_3_0_1y", None),
    ("corp_bond", 3, "1_5y", "corp_bond_cqs2_3_1_5y", None),
    ("corp_bond", 3, "5y_plus", "corp_bond_cqs2_3_5y_plus", None),
    # Equity
    ("equity", None, None, "equity_main_index", True),
    ("equity", None, None, "equity_other", False),
    # Other
    ("real_estate", None, None, "real_estate", None),
    ("receivables", None, None, "receivables", None),
    ("other_physical", None, None, "other_physical", None),
)

_B31_HAIRCUT_ROW_SPECS: tuple[_HaircutRowSpec, ...] = (
    # Cash and gold
    ("cash", None, None, "cash", None),
    ("gold", None, None, "gold", None),
    # Government bonds CQS 1
    ("govt_bond", 1, "0_1y", "govt_bond_cqs1_0_1y", None),
    ("govt_bond", 1, "1_3y", "govt_bond_cqs1_1_3y", None),
    ("govt_bond", 1, "3_5y", "govt_bond_cqs1_3_5y", None),
    ("govt_bond", 1, "5_10y", "govt_bond_cqs1_5_10y", None),
    ("govt_bond", 1, "10y_plus", "govt_bond_cqs1_10y_plus", None),
    # Government bonds CQS 2-3 (shared dict key)
    ("govt_bond", 2, "0_1y", "govt_bond_cqs2_3_0_1y", None),
    ("govt_bond", 2, "1_3y", "govt_bond_cqs2_3_1_3y", None),
    ("govt_bond", 2, "3_5y", "govt_bond_cqs2_3_3_5y", None),
    ("govt_bond", 2, "5_10y", "govt_bond_cqs2_3_5_10y", None),
    ("govt_bond", 2, "10y_plus", "govt_bond_cqs2_3_10y_plus", None),
    ("govt_bond", 3, "0_1y", "govt_bond_cqs2_3_0_1y", None),
    ("govt_bond", 3, "1_3y", "govt_bond_cqs2_3_1_3y", None),
    ("govt_bond", 3, "3_5y", "govt_bond_cqs2_3_3_5y", None),
    ("govt_bond", 3, "5_10y", "govt_bond_cqs2_3_5_10y", None),
    ("govt_bond", 3, "10y_plus", "govt_bond_cqs2_3_10y_plus", None),
    # Government bonds CQS 4 (BB+ to BB-)
    ("govt_bond", 4, "0_1y", "govt_bond_cqs4_0_1y", None),
    ("govt_bond", 4, "1_3y", "govt_bond_cqs4_1_3y", None),
    ("govt_bond", 4, "3_5y", "govt_bond_cqs4_3_5y", None),
    ("govt_bond", 4, "5_10y", "govt_bond_cqs4_5_10y", None),
    ("govt_bond", 4, "10y_plus", "govt_bond_cqs4_10y_plus", None),
    # Corporate bonds CQS 1 (AAA to AA-)
    ("corp_bond", 1, "0_1y", "corp_bond_cqs1_0_1y", None),
    ("corp_bond", 1, "1_3y", "corp_bond_cqs1_1_3y", None),
    ("corp_bond", 1, "3_5y", "corp_bond_cqs1_3_5y", None),
    ("corp_bond", 1, "5_10y", "corp_bond_cqs1_5_10y", None),
    ("corp_bond", 1, "10y_plus", "corp_bond_cqs1_10y_plus", None),
    # Corporate bonds CQS 2-3 (shared dict key)
    ("corp_bond", 2, "0_1y", "corp_bond_cqs2_3_0_1y", None),
    ("corp_bond", 2, "1_3y", "corp_bond_cqs2_3_1_3y", None),
    ("corp_bond", 2, "3_5y", "corp_bond_cqs2_3_3_5y", None),
    ("corp_bond", 2, "5_10y", "corp_bond_cqs2_3_5_10y", None),
    ("corp_bond", 2, "10y_plus", "corp_bond_cqs2_3_10y_plus", None),
    ("corp_bond", 3, "0_1y", "corp_bond_cqs2_3_0_1y", None),
    ("corp_bond", 3, "1_3y", "corp_bond_cqs2_3_1_3y", None),
    ("corp_bond", 3, "3_5y", "corp_bond_cqs2_3_3_5y", None),
    ("corp_bond", 3, "5_10y", "corp_bond_cqs2_3_5_10y", None),
    ("corp_bond", 3, "10y_plus", "corp_bond_cqs2_3_10y_plus", None),
    # Equity
    ("equity", None, None, "equity_main_index", True),
    ("equity", None, None, "equity_other", False),
    # Other
    ("real_estate", None, None, "real_estate", None),
    ("receivables", None, None, "receivables", None),
    ("other_physical", None, None, "other_physical", None),
)


def _build_haircut_df(
    row_specs: tuple[_HaircutRowSpec, ...],
    haircut_dict: dict[str, Decimal],
) -> pl.DataFrame:
    """Build a haircut lookup DataFrame from row specs + authoritative dict."""
    return pl.DataFrame(
        {
            "collateral_type": [spec[0] for spec in row_specs],
            "cqs": [spec[1] for spec in row_specs],
            "maturity_band": [spec[2] for spec in row_specs],
            "haircut": [float(haircut_dict[spec[3]]) for spec in row_specs],
            "is_main_index": [spec[4] for spec in row_specs],
        }
    ).with_columns(
        [
            pl.col("cqs").cast(pl.Int8),
            pl.col("haircut").cast(pl.Float64),
        ]
    )


def _create_haircut_df(is_basel_3_1: bool = False) -> pl.DataFrame:
    """Create haircut lookup DataFrame for the specified framework."""
    if is_basel_3_1:
        return _create_basel31_haircut_df()
    return _create_crr_haircut_df()


def _create_crr_haircut_df() -> pl.DataFrame:
    """Create CRR haircut lookup DataFrame (3 maturity bands).

    Values are sourced from ``COLLATERAL_HAIRCUTS``; ``_CRR_HAIRCUT_ROW_SPECS``
    defines row order and the dict keys used for lookup.
    """
    return _build_haircut_df(_CRR_HAIRCUT_ROW_SPECS, COLLATERAL_HAIRCUTS)


def _create_basel31_haircut_df() -> pl.DataFrame:
    """Create Basel 3.1 haircut lookup DataFrame (5 maturity bands per CRE22.52-53).

    Values are sourced from ``BASEL31_COLLATERAL_HAIRCUTS``;
    ``_B31_HAIRCUT_ROW_SPECS`` defines row order and dict keys used for lookup.
    """
    return _build_haircut_df(_B31_HAIRCUT_ROW_SPECS, BASEL31_COLLATERAL_HAIRCUTS)


def get_haircut_table(is_basel_3_1: bool = False) -> pl.DataFrame:
    """
    Get collateral haircut lookup table for the given framework.

    Args:
        is_basel_3_1: True for Basel 3.1 haircuts (CRE22.52-53), False for CRR (Art. 224)

    Returns:
        DataFrame with columns: collateral_type, cqs, maturity_band, haircut, is_main_index
    """
    return _create_haircut_df(is_basel_3_1=is_basel_3_1)


def get_maturity_band(residual_maturity_years: float, is_basel_3_1: bool = False) -> str:
    """
    Determine maturity band from residual maturity.

    CRR uses 3 bands: 0-1y, 1-5y, 5y+
    Basel 3.1 uses 5 bands: 0-1y, 1-3y, 3-5y, 5-10y, 10y+

    Args:
        residual_maturity_years: Residual maturity in years
        is_basel_3_1: True for Basel 3.1 maturity bands

    Returns:
        Maturity band string
    """
    if is_basel_3_1:
        if residual_maturity_years <= 1.0:
            return "0_1y"
        elif residual_maturity_years <= 3.0:
            return "1_3y"
        elif residual_maturity_years <= 5.0:
            return "3_5y"
        elif residual_maturity_years <= 10.0:
            return "5_10y"
        else:
            return "10y_plus"
    else:
        if residual_maturity_years <= 1.0:
            return "0_1y"
        elif residual_maturity_years <= 5.0:
            return "1_5y"
        else:
            return "5y_plus"


def is_bond_eligible_as_financial_collateral(
    collateral_type: str,
    cqs: int | None,
) -> bool:
    """
    Check if a bond is eligible as financial collateral per CRR Art. 197.

    Eligibility rules:
    - Art. 197(1)(b): Government/central bank bonds — CQS 1-4 eligible
    - Art. 197(1)(d): Institution/corporate bonds — CQS 1-3 eligible
    - Unrated bonds (cqs=None) are ineligible under both categories
    - Non-bond collateral types are not subject to these rules (returns True)

    Args:
        collateral_type: Canonical collateral type ('govt_bond' or 'corp_bond')
        cqs: Credit quality step of issuer (1-6), or None if unrated

    Returns:
        True if eligible, False if ineligible
    """
    coll_lower = collateral_type.lower()

    if coll_lower in ("govt_bond", "sovereign_bond", "government_bond", "gilt"):
        return cqs is not None and 1 <= cqs <= 4
    if coll_lower in ("corp_bond", "corporate_bond"):
        return cqs is not None and 1 <= cqs <= 3

    # Non-bond collateral types are not subject to bond eligibility rules
    return True


def lookup_collateral_haircut(
    collateral_type: str,
    cqs: int | None = None,
    residual_maturity_years: float | None = None,
    is_main_index: bool = False,
    is_basel_3_1: bool = False,
    liquidation_period_days: int = 10,
) -> Decimal | None:
    """
    Look up supervisory haircut for collateral, scaled for liquidation period.

    This is a convenience function for single lookups. For bulk processing,
    use the DataFrame tables with joins.

    Args:
        collateral_type: Type of collateral
        cqs: Credit quality step of issuer (for debt securities)
        residual_maturity_years: Remaining maturity in years
        is_main_index: For equity, whether it's on a main index
        is_basel_3_1: Whether to use Basel 3.1 haircuts
        liquidation_period_days: Liquidation period in business days (default 10)

    Returns:
        Haircut as Decimal scaled for liquidation period,
        or None if collateral is ineligible per Art. 197
    """
    table = BASEL31_COLLATERAL_HAIRCUTS if is_basel_3_1 else COLLATERAL_HAIRCUTS
    coll_lower = collateral_type.lower()

    def _scale(h: Decimal) -> Decimal:
        """Scale 10-day base haircut if liquidation period differs."""
        if liquidation_period_days == 10 or h == Decimal("0"):
            return h
        scaled = scale_haircut_for_liquidation_period(float(h), liquidation_period_days)
        return Decimal(str(round(scaled, 6)))

    # Cash - 0%
    if coll_lower in ("cash", "deposit"):
        return table["cash"]

    # Gold
    if coll_lower == "gold":
        return _scale(table["gold"])

    # Government bonds — Art. 197(1)(b): CQS 1-4 eligible, CQS 5-6/unrated ineligible
    if coll_lower in ("govt_bond", "sovereign_bond", "government_bond", "gilt"):
        if not is_bond_eligible_as_financial_collateral("govt_bond", cqs):
            return None

        maturity = residual_maturity_years or 5.0
        maturity_band = get_maturity_band(maturity, is_basel_3_1=is_basel_3_1)

        if cqs == 1:
            key = f"govt_bond_cqs1_{maturity_band}"
        elif cqs in (2, 3):
            key = f"govt_bond_cqs2_3_{maturity_band}"
        elif cqs == 4:
            key = f"govt_bond_cqs4_{maturity_band}"
        else:
            return None  # Should not reach here after eligibility check

        return _scale(table.get(key, Decimal("0.15")))

    # Corporate/institution bonds — Art. 197(1)(d): CQS 1-3 eligible, CQS 4-6/unrated ineligible
    if coll_lower in ("corp_bond", "corporate_bond"):
        if not is_bond_eligible_as_financial_collateral("corp_bond", cqs):
            return None

        maturity = residual_maturity_years or 5.0
        maturity_band = get_maturity_band(maturity, is_basel_3_1=is_basel_3_1)

        if cqs == 1:
            key = f"corp_bond_cqs1_{maturity_band}"
        elif cqs in (2, 3):
            key = f"corp_bond_cqs2_3_{maturity_band}"
        else:
            return None  # Should not reach here after eligibility check

        return _scale(table.get(key, Decimal("0.20")))

    # Equity
    if coll_lower in ("equity", "shares", "stock"):
        if is_main_index:
            return _scale(table["equity_main_index"])
        return _scale(table["equity_other"])

    # Receivables — not subject to Art. 224 liquidation period scaling
    # (Art. 230 non-financial collateral HC, not Art. 224 Tables)
    if coll_lower in ("receivables", "trade_receivables"):
        return table["receivables"]

    # Real estate (not typically haircut-based in CRM)
    if coll_lower in ("real_estate", "property", "rre", "cre"):
        return Decimal("0.00")

    # Other physical collateral — not subject to Art. 224 scaling
    return table["other_physical"]


def lookup_fx_haircut(
    exposure_currency: str,
    collateral_currency: str,
    liquidation_period_days: int = 10,
) -> Decimal:
    """
    Get FX mismatch haircut, scaled for liquidation period.

    Art. 224 Table 4 base (10-day): 8%
    Scaled by Art. 226(2): H_m = 8% × sqrt(T_m / 10)

    Args:
        exposure_currency: Currency of exposure
        collateral_currency: Currency of collateral
        liquidation_period_days: Liquidation period in business days (default 10)

    Returns:
        FX haircut (0% if same currency, scaled 8% if different)
    """
    if exposure_currency.upper() == collateral_currency.upper():
        return Decimal("0.00")
    if liquidation_period_days == 10:
        return FX_HAIRCUT
    scaled = scale_haircut_for_liquidation_period(float(FX_HAIRCUT), liquidation_period_days)
    return Decimal(str(round(scaled, 6)))


def calculate_adjusted_collateral_value(
    collateral_value: Decimal,
    collateral_haircut: Decimal,
    fx_haircut: Decimal = Decimal("0.00"),
) -> Decimal:
    """
    Calculate adjusted collateral value after haircuts.

    CRR Art. 223 formula: C_adjusted = C x (1 - Hc - Hfx)

    Args:
        collateral_value: Market value of collateral
        collateral_haircut: Collateral-specific haircut
        fx_haircut: FX mismatch haircut (default 0%)

    Returns:
        Adjusted collateral value
    """
    total_haircut = collateral_haircut + fx_haircut
    return collateral_value * (Decimal("1") - total_haircut)


def calculate_maturity_mismatch_adjustment(
    collateral_value: Decimal,
    collateral_maturity_years: float,
    exposure_maturity_years: float,
    minimum_maturity_years: float = 0.25,
    original_maturity_years: float | None = None,
    has_one_day_maturity_floor: bool = False,
) -> tuple[Decimal, str]:
    """
    Apply maturity mismatch adjustment (CRR Art. 237-238).

    Art. 237(2) ineligibility conditions (applied when mismatch exists):
    - (a) Residual maturity < 3 months → no protection
    - (b) Original maturity of protection < 1 year → no protection
    - Art. 162(3) 1-day M floor exposures → any mismatch makes protection ineligible

    Args:
        collateral_value: Adjusted collateral value
        collateral_maturity_years: Residual maturity of collateral
        exposure_maturity_years: Residual maturity of exposure
        minimum_maturity_years: Minimum maturity threshold (default 3 months)
        original_maturity_years: Original contract term of protection (Art. 237(2))
        has_one_day_maturity_floor: Art. 162(3) 1-day M floor exposure

    Returns:
        Tuple of (adjusted_value, description)

    Formula:
        If t < T: Adjusted = C x (t - 0.25) / (T - 0.25)
        Where t = collateral maturity, T = exposure maturity (capped at 5y)
    """
    # If collateral maturity >= exposure maturity, no adjustment
    if collateral_maturity_years >= exposure_maturity_years:
        return collateral_value, "No maturity mismatch adjustment"

    # --- Mismatch exists: apply Art. 237(2) ineligibility conditions ---

    # Art. 237(2)(a): collateral maturity < 3 months → no protection
    if collateral_maturity_years < minimum_maturity_years:
        return Decimal("0"), "Collateral maturity < 3 months, no protection (Art. 237(2))"

    # Art. 237(2): original maturity of protection < 1 year → ineligible
    if original_maturity_years is not None and original_maturity_years < 1.0:
        return Decimal("0"), ("Original maturity < 1 year, protection ineligible (Art. 237(2))")

    # Art. 162(3)/237(2): 1-day M floor exposure → any mismatch → ineligible
    if has_one_day_maturity_floor:
        return Decimal("0"), (
            "1-day maturity floor exposure, mismatch makes protection ineligible "
            "(Art. 237(2)/162(3))"
        )

    # Apply CVAM adjustment (Art. 238)
    t = max(collateral_maturity_years, minimum_maturity_years)
    T = min(max(exposure_maturity_years, minimum_maturity_years), 5.0)

    adjustment_factor = Decimal(str((t - 0.25) / (T - 0.25)))
    adjusted_value = collateral_value * adjustment_factor

    description = f"Maturity adj: {adjustment_factor:.3f} (t={t:.1f}y, T={T:.1f}y)"
    return adjusted_value, description
