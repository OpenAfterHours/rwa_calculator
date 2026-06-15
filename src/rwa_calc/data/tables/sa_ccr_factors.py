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

# MF_UNMARGINED_CAP_YEARS (1.0) / MF_UNMARGINED_DENOM_YEARS (1.0) /
# MF_MARGINED_SCALAR (1.5) — CRR Art. 279c — moved to packs/common.py
# (mf_unmargined_cap_years / mf_unmargined_denom_years / mf_margined_scalar).
# The MPOR floor day counts below stay as int constants.

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
# SUPERVISORY ALPHA — moved to the rulepack (CRR Art. 274(2))
#
# EAD = alpha * (RC + PFE). The default supervisory alpha (1.4, BCBS CRE52.1) and
# the alpha = 1.0 carve-out for non-financial / pension-scheme counterparties
# (CRR Art. 274(2) second sub-paragraph; EMIR Art. 2(9) / 2(10)) now live in
# packs/common.py (``sa_ccr_alpha`` / ``sa_ccr_alpha_carve_out``). The per-row
# discriminator remains the COUNTERPARTY_SCHEMA ``counterparty_type`` column;
# engine/ccr/pipeline_adapter.py resolves the pack values and selects
# ``alpha_applied`` before compute_pfe.
# =============================================================================


# =============================================================================
# TRANSITIONAL ALPHA ADD-ON (PRA PS1/26 Art. 274(2A)-(2B)) — Basel 3.1 only
#
# Art. 274(2A): for netting sets whose trades were entered into prior to
# 1 Jan 2027 with a counterparty listed in the CVA Risk Part 7.1(1)(a)/(b)
# (the legacy CVA-exempt cohort, flagged via TRADE_SCHEMA.is_legacy_cva_exempt),
# the firm must add a phased fraction of the alpha add-on to the exposure value.
# The full alpha add-on is the difference between EAD computed with α=1.4 and
# EAD computed with α=1.0:
#     alpha_add_on = (SA_CCR_ALPHA − SA_CCR_ALPHA_CARVE_OUT) × (RC + PFE)
#                  = 0.4 × (RC + PFE)
# The transitional fraction phases out across the first three years and is zero
# from 1 Jan 2030: 60% (2027) / 40% (2028) / 20% (2029) / 0% (2030+). Years not
# present in the map resolve to 0 (no add-on). This provision is Basel 3.1 only;
# CRR has no Art. 274(2A) equivalent so the add-on must never fire under CRR.
#
# Art. 274(2B): the transitional add-on is excluded from the leverage-ratio
# exposure measure. Moot here — this engine exposes no leverage-ratio EAD path,
# so there is nothing to bifurcate.
# =============================================================================

#: PRA PS1/26 Art. 274(2A) — transitional alpha add-on phase fractions keyed by
#: reporting year. Years absent from the map (e.g. 2030+) resolve to 0.
SA_CCR_TRANSITIONAL_ADDON_PHASE: dict[int, Decimal] = {
    2027: Decimal("0.60"),
    2028: Decimal("0.40"),
    2029: Decimal("0.20"),
}


# =============================================================================
# PFE MULTIPLIER FLOOR (CRR Art. 278(3))
# =============================================================================

PFE_MULTIPLIER_FLOOR_F: Decimal = Decimal("0.05")

# CRR Art. 278(3): the ``2`` in the denominator ``2 × (1 − F) × AddOn_aggregate``
# of the PFE multiplier exponent.
PFE_AGGREGATE_DENOM_COEFF: Decimal = Decimal("2")


# =============================================================================
# WRONG-WAY RISK LGD OVERRIDE (CRR Art. 291(5)(c))
#
# Specific wrong-way risk: when the trade-level connection of Art. 291(1)(b)
# is present, the synthetic single-trade netting set carved out by
# ``engine/ccr/wwr.py::apply_wwr_gate`` carries an LGD = 100% override that
# feeds downstream IRB consumption (Art. 153) — replacing the bank's own LGD
# estimate for that exposure.
# =============================================================================

CCR_WWR_SPECIFIC_LGD_OVERRIDE: Decimal = Decimal("1.0")


# =============================================================================
# SUPERVISORY OPTION VOLATILITY (Art. 279a(2)) + CDO TRANCHE DELTA (Art. 279a(3))
# — moved to the rulepack
#
# The Black-Scholes Phi(d1) supervisory option volatilities (CRR Art. 279a(2) /
# BCBS CRE52.47 Table 3) and the CDO tranche supervisory-delta closed-form
# coefficients (Art. 279a(3) / CRE52.43, |delta| = 15 / ((1 + 14*A)*(1 + 14*D)))
# now live in packs/common.py (``sa_ccr_option_volatility_*`` /
# ``sa_ccr_cdo_tranche_*``); resolved in engine/ccr/supervisory_delta.py.
# =============================================================================


# =============================================================================
# ADJUSTED NOTIONAL — IR SUPERVISORY DURATION (CRR Art. 279b(1)(a))
#
# Supervisory duration SD(S, E) = (exp(-0.05*S) - exp(-0.05*E)) / 0.05
# with start date S floored at 10 business days under the 250-business-day
# year convention (BCBS CRE52.40 footnote).
# =============================================================================

# CRR Art. 279b(1)(a) supervisory duration rate (0.05) — moved to packs/common.py
# (sa_ccr_supervisory_duration_rate). The 10-BD start-date floor expressed as a
# 0.04 year fraction (10/250) is sa_ccr_start_floor_years in the pack.

# BCBS CRE52.40 footnote: 250-business-day year convention (still consumed by
# engine/ccr/maturity_factor.py for the margined MPOR sqrt term).
SA_CCR_BUSINESS_DAYS_PER_YEAR: int = 250


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
