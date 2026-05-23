"""
SA-CCR supervisory factor, correlation, and maturity-factor constants.

Pipeline position:
    Consumed by ``engine/ccr/`` namespaces when computing PFE add-ons,
    asset-class aggregation, and maturity adjustments under the SA-CCR
    approach (CRR Part Three Title II Chapter 6 Section 3).

Key responsibilities:
- Expose every regulatory scalar required by SA-CCR as a ``Decimal``
  constant in this single module, so ``engine/**`` modules never embed
  numerical regulatory values directly.
- Provide ``_build_*_df()`` helpers that materialise the supervisory-factor
  and correlation tables as Polars DataFrames for use in LazyFrame joins,
  mirroring the ``_build_cqs_rw_df`` precedent in ``crr_risk_weights``.

Regulatory references:
- CRR Art. 280 Table 1: supervisory factors per asset class / sub-class.
- CRR Art. 280a: credit-class correlations (single-name 0.50, index 0.80).
- CRR Art. 280b: equity-class correlations (single-name 0.50, index 0.80).
- CRR Art. 280c: commodity-class correlation (0.40 — NOT 0.80).
- CRR Art. 279c: maturity-factor formulae (unmargined 1-year cap, margined
  3/2 scalar applied to sqrt(MPOR/250) once MPOR is expressed in business
  days).
- CRR Art. 285(2)-(3): MPOR floors — 5 BD for repo/SFT, 10 BD for standard
  OTC, 20 BD for large or illiquid netting sets.
- CRR Art. 278(3): PFE multiplier floor F = 0.05.
- PRA PS1/26 Counterparty Credit Risk (CRR) Part: UK-onshored equivalents
  of the above CRR articles; numerical values match.
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl
from watchfire import cites

# =============================================================================
# SUPERVISORY FACTOR CONSTANTS (CRR Art. 280 Table 1)
# =============================================================================

SA_CCR_SUPERVISORY_FACTOR_IR: Decimal = Decimal("0.005")
SA_CCR_SUPERVISORY_FACTOR_FX: Decimal = Decimal("0.04")

SA_CCR_SUPERVISORY_FACTORS_CREDIT_SN: dict[str, Decimal] = {
    "IG": Decimal("0.0046"),
    "HY": Decimal("0.013"),
    "NON_RATED": Decimal("0.06"),
}

SA_CCR_SUPERVISORY_FACTORS_CREDIT_IDX: dict[str, Decimal] = {
    "IG": Decimal("0.0038"),
    "HY": Decimal("0.0106"),
}

SA_CCR_SUPERVISORY_FACTOR_EQUITY_SN: Decimal = Decimal("0.32")
SA_CCR_SUPERVISORY_FACTOR_EQUITY_IDX: Decimal = Decimal("0.20")

SA_CCR_SUPERVISORY_FACTORS_COMMODITY: dict[str, Decimal] = {
    "ELECTRICITY": Decimal("0.40"),
    "OIL_GAS": Decimal("0.18"),
    "METALS": Decimal("0.18"),
    "AGRICULTURAL": Decimal("0.18"),
    "OTHER": Decimal("0.18"),
}


# =============================================================================
# CORRELATION CONSTANTS (CRR Art. 280a / Art. 280b / Art. 280c)
#
# CRITICAL: COMMODITY correlation per Art. 280c is 0.40, NOT 0.80.
# =============================================================================

SA_CCR_CORRELATION_CREDIT_SN: Decimal = Decimal("0.50")
SA_CCR_CORRELATION_CREDIT_IDX: Decimal = Decimal("0.80")
SA_CCR_CORRELATION_EQUITY_SN: Decimal = Decimal("0.50")
SA_CCR_CORRELATION_EQUITY_IDX: Decimal = Decimal("0.80")
SA_CCR_CORRELATION_COMMODITY: Decimal = Decimal("0.40")

# CRR Art. 277a(1)(a): cross-bucket correlations for the IR asset class.
# Buckets are LT_1Y (B1), 1Y_5Y (B2), GT_5Y (B3). Adjacent buckets correlate
# at 0.70; non-adjacent (B1, B3) correlate at 0.30.
SA_CCR_IR_BUCKET_CORRELATION_12: Decimal = Decimal("0.7")
SA_CCR_IR_BUCKET_CORRELATION_23: Decimal = Decimal("0.7")
SA_CCR_IR_BUCKET_CORRELATION_13: Decimal = Decimal("0.3")


# =============================================================================
# MATURITY FACTOR CONSTANTS (CRR Art. 279c, Art. 285(2)-(3))
# =============================================================================

MF_UNMARGINED_CAP_YEARS: Decimal = Decimal("1.0")
MF_UNMARGINED_DENOM_YEARS: Decimal = Decimal("1.0")
MF_MARGINED_SCALAR: Decimal = Decimal("1.5")

MF_MARGINED_FLOOR_DAYS_REPO_SFT: int = 5
MF_MARGINED_FLOOR_DAYS_OTC: int = 10
MF_MARGINED_FLOOR_DAYS_LARGE_OR_ILLIQUID: int = 20

# CRR Art. 285(3)(a): >5000 trades in netting set triggers 20-BD MPOR floor.
MF_MARGINED_LARGE_NETTING_SET_TRADE_COUNT: int = 5000

# CRR Art. 285(4): more than two disputes in the prior two quarters doubles
# the MPOR base period.
MF_MARGINED_DISPUTE_THRESHOLD: int = 2
MF_MARGINED_DISPUTE_MULTIPLIER: int = 2


# =============================================================================
# PFE MULTIPLIER FLOOR (CRR Art. 278(3))
# =============================================================================

PFE_MULTIPLIER_FLOOR_F: Decimal = Decimal("0.05")


# =============================================================================
# SUPERVISORY OPTION VOLATILITY (CRR Art. 279a(2) / BCBS CRE52.47 Table 3)
#
# Used by the Black-Scholes Phi(d1) supervisory delta for European options:
#     d1 = (ln(P/K) + 0.5 * sigma^2 * T) / (sigma * sqrt(T))
# =============================================================================

SA_CCR_OPTION_VOLATILITY_IR: Decimal = Decimal("0.50")
SA_CCR_OPTION_VOLATILITY_FX: Decimal = Decimal("0.15")
SA_CCR_OPTION_VOLATILITY_CREDIT_SN: Decimal = Decimal("1.00")
SA_CCR_OPTION_VOLATILITY_CREDIT_IDX: Decimal = Decimal("0.80")
SA_CCR_OPTION_VOLATILITY_EQUITY_SN: Decimal = Decimal("1.20")
SA_CCR_OPTION_VOLATILITY_EQUITY_IDX: Decimal = Decimal("0.75")
SA_CCR_OPTION_VOLATILITY_COMMODITY_ELECTRICITY: Decimal = Decimal("1.50")
SA_CCR_OPTION_VOLATILITY_COMMODITY_OTHER: Decimal = Decimal("0.70")


# =============================================================================
# CDO TRANCHE SUPERVISORY DELTA (CRR Art. 279a(3) / BCBS CRE52.43)
#
# Closed-form |delta| = 15 / ((1 + 14 * A) * (1 + 14 * D)) where A and D are
# the tranche attachment and detachment points respectively.
# =============================================================================

# CRR Art. 279a(3) / BCBS CRE52.43 — CDO tranche supervisory delta closed-form
SA_CCR_CDO_TRANCHE_NUMERATOR: Decimal = Decimal("15")
SA_CCR_CDO_TRANCHE_COEFFICIENT: Decimal = Decimal("14")


# =============================================================================
# ADJUSTED NOTIONAL — IR SUPERVISORY DURATION (CRR Art. 279b(1)(a))
#
# Supervisory duration SD(S, E) = (exp(-0.05*S) - exp(-0.05*E)) / 0.05
# with start date S floored at 10 business days under the 250-business-day
# year convention (BCBS CRE52.40 footnote).
# =============================================================================

# CRR Art. 279b(1)(a) supervisory duration rate: SD(S,E) = (exp(-0.05*S) - exp(-0.05*E))/0.05
SA_CCR_SUPERVISORY_DURATION_RATE: Decimal = Decimal("0.05")

# CRR Art. 279b(1)(a): start-date S floored at 10 business days
SA_CCR_START_FLOOR_BD: int = 10

# BCBS CRE52.40 footnote: 250-business-day year convention
SA_CCR_BUSINESS_DAYS_PER_YEAR: int = 250

# Derived: 10/250 = 0.04 year fraction floor for S
SA_CCR_START_FLOOR_YEARS: Decimal = Decimal("10") / Decimal("250")


# =============================================================================
# INTERNAL DATAFRAME-BUILD HELPERS
#
# Each ``_build_*_df`` helper derives its numeric values from the constant
# dicts/scalars above so there is exactly one source of truth for every
# regulatory scalar. Engine namespaces consume these DataFrames via
# LazyFrame joins (asset_class, sub_class) -> supervisory_factor / correlation.
# =============================================================================


@cites("CRR Art. 280")
def _build_sa_ccr_supervisory_factors_df() -> pl.DataFrame:
    """Build SA-CCR supervisory factor lookup DataFrame (CRR Art. 280 Table 1).

    Returns a 14-row DataFrame with columns
    ``["asset_class", "sub_class", "supervisory_factor"]`` covering every
    asset-class / sub-class combination in Art. 280 Table 1:

    - IR (1 row, sub_class=None) — 0.5%
    - FX (1 row, sub_class=None) — 4%
    - CREDIT_SN (3 rows: IG / HY / NON_RATED) — 0.46% / 1.3% / 6%
    - CREDIT_IDX (2 rows: IG / HY) — 0.38% / 1.06%
    - EQUITY_SN (1 row, sub_class=None) — 32%
    - EQUITY_IDX (1 row, sub_class=None) — 20%
    - COMMODITY (5 rows: ELECTRICITY / OIL_GAS / METALS / AGRICULTURAL /
      OTHER) — 40% / 18% / 18% / 18% / 18%

    Returns:
        DataFrame with columns
        ``[asset_class (Utf8), sub_class (Utf8 nullable), supervisory_factor (Float64)]``.
    """
    asset_classes: list[str] = []
    sub_classes: list[str | None] = []
    factors: list[float] = []

    # IR
    asset_classes.append("IR")
    sub_classes.append(None)
    factors.append(float(SA_CCR_SUPERVISORY_FACTOR_IR))

    # FX
    asset_classes.append("FX")
    sub_classes.append(None)
    factors.append(float(SA_CCR_SUPERVISORY_FACTOR_FX))

    # CREDIT_SN (IG, HY, NON_RATED)
    for sub in ("IG", "HY", "NON_RATED"):
        asset_classes.append("CREDIT_SN")
        sub_classes.append(sub)
        factors.append(float(SA_CCR_SUPERVISORY_FACTORS_CREDIT_SN[sub]))

    # CREDIT_IDX (IG, HY)
    for sub in ("IG", "HY"):
        asset_classes.append("CREDIT_IDX")
        sub_classes.append(sub)
        factors.append(float(SA_CCR_SUPERVISORY_FACTORS_CREDIT_IDX[sub]))

    # EQUITY_SN
    asset_classes.append("EQUITY_SN")
    sub_classes.append(None)
    factors.append(float(SA_CCR_SUPERVISORY_FACTOR_EQUITY_SN))

    # EQUITY_IDX
    asset_classes.append("EQUITY_IDX")
    sub_classes.append(None)
    factors.append(float(SA_CCR_SUPERVISORY_FACTOR_EQUITY_IDX))

    # COMMODITY (ELECTRICITY, OIL_GAS, METALS, AGRICULTURAL, OTHER)
    for sub in ("ELECTRICITY", "OIL_GAS", "METALS", "AGRICULTURAL", "OTHER"):
        asset_classes.append("COMMODITY")
        sub_classes.append(sub)
        factors.append(float(SA_CCR_SUPERVISORY_FACTORS_COMMODITY[sub]))

    return pl.DataFrame(
        {
            "asset_class": asset_classes,
            "sub_class": sub_classes,
            "supervisory_factor": factors,
        }
    ).with_columns(
        [
            pl.col("asset_class").cast(pl.Utf8),
            pl.col("sub_class").cast(pl.Utf8),
            pl.col("supervisory_factor").cast(pl.Float64),
        ]
    )


@cites("CRR Art. 280")
def _build_sa_ccr_correlations_df() -> pl.DataFrame:
    """Build SA-CCR correlation lookup DataFrame (CRR Art. 280a / 280b / 280c).

    The @cites decorator points at the parent Art. 280; the sub-articles
    280a/b/c are not yet in watchfire's bundled CRR index (tracked for the
    follow-up batch). Per-row article attribution is preserved below.

    Returns a 5-row DataFrame with columns
    ``["asset_class", "sub_class", "correlation"]``:

    - CREDIT_SN  -> 0.50 (Art. 280a)
    - CREDIT_IDX -> 0.80 (Art. 280a)
    - EQUITY_SN  -> 0.50 (Art. 280b)
    - EQUITY_IDX -> 0.80 (Art. 280b)
    - COMMODITY  -> 0.40 (Art. 280c — NOT 0.80)

    Returns:
        DataFrame with columns
        ``[asset_class (Utf8), sub_class (Utf8 nullable), correlation (Float64)]``.
    """
    return pl.DataFrame(
        {
            "asset_class": [
                "CREDIT_SN",
                "CREDIT_IDX",
                "EQUITY_SN",
                "EQUITY_IDX",
                "COMMODITY",
            ],
            "sub_class": [None, None, None, None, None],
            "correlation": [
                float(SA_CCR_CORRELATION_CREDIT_SN),
                float(SA_CCR_CORRELATION_CREDIT_IDX),
                float(SA_CCR_CORRELATION_EQUITY_SN),
                float(SA_CCR_CORRELATION_EQUITY_IDX),
                float(SA_CCR_CORRELATION_COMMODITY),
            ],
        }
    ).with_columns(
        [
            pl.col("asset_class").cast(pl.Utf8),
            pl.col("sub_class").cast(pl.Utf8),
            pl.col("correlation").cast(pl.Float64),
        ]
    )
