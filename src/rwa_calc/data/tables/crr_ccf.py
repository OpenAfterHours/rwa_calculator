"""
CRR Credit Conversion Factors (CRR Art. 111 and Art. 166).

Provides CCF lookup tables as Polars DataFrames for efficient joins
in the RWA calculation pipeline.

Reference:
    CRR Art. 111: Off-balance sheet items (Standardised Approach)
    CRR Art. 166(8): CCFs for F-IRB (75% for undrawn commitments)
"""

from decimal import Decimal

import polars as pl


# =============================================================================
# SA CCF BY CATEGORY (CRR Art. 111)
# =============================================================================

# CRR SA uses four CCF categories: 0%, 20%, 50%, 100%
CCF_TABLE: dict[str, Decimal] = {
    # 0% CCF - Low risk
    "low_risk": Decimal("0.00"),
    "unconditionally_cancellable": Decimal("0.00"),

    # 20% CCF - Medium-low risk
    "medium_low_risk": Decimal("0.20"),
    "documentary_credit": Decimal("0.20"),
    "short_term_lc": Decimal("0.20"),
    "undrawn_short_term": Decimal("0.20"),     # <= 1 year original maturity

    # 50% CCF - Medium risk
    "medium_risk": Decimal("0.50"),
    "undrawn_long_term": Decimal("0.50"),      # > 1 year original maturity
    "performance_guarantee": Decimal("0.50"),
    "bid_bond": Decimal("0.50"),
    "nif_ruf": Decimal("0.50"),
    "standby_lc": Decimal("0.50"),

    # 100% CCF - Full risk
    "full_risk": Decimal("1.00"),
    "guarantee_given": Decimal("1.00"),
    "acceptance": Decimal("1.00"),
    "credit_derivative": Decimal("1.00"),
    "forward_purchase": Decimal("1.00"),
}


# Mapping of common commitment types to CCF categories
CCF_TYPE_MAPPING: dict[str, str] = {
    # 0% CCF types
    "unconditionally_cancellable": "low_risk",
    "revocable": "low_risk",

    # 20% CCF types
    "documentary_lc": "documentary_credit",
    "trade_lc": "documentary_credit",
    "short_term_lc": "short_term_lc",
    "undrawn_revolver_short": "undrawn_short_term",

    # 50% CCF types
    "undrawn_revolver_long": "undrawn_long_term",
    "committed_undrawn": "undrawn_long_term",
    "rcf_undrawn": "undrawn_long_term",
    "performance_bond": "performance_guarantee",
    "warranty": "performance_guarantee",
    "nif": "nif_ruf",
    "ruf": "nif_ruf",
    "standby_letter_of_credit": "standby_lc",

    # 100% CCF types
    "guarantee": "guarantee_given",
    "financial_guarantee": "guarantee_given",
    "acceptance": "acceptance",
    "credit_derivative": "credit_derivative",
    "forward_asset_purchase": "forward_purchase",
}


# =============================================================================
# F-IRB CCF (CRR Art. 166(8))
# =============================================================================

# Under F-IRB, undrawn commitments use 75% CCF (except unconditionally cancellable)
FIRB_CCF_TABLE: dict[str, Decimal] = {
    # 0% CCF - Unconditionally cancellable (same as SA)
    "unconditionally_cancellable": Decimal("0.00"),
    "low_risk": Decimal("0.00"),

    # 75% CCF - All other undrawn commitments under F-IRB
    "undrawn_commitment": Decimal("0.75"),
    "undrawn_short_term": Decimal("0.75"),
    "undrawn_long_term": Decimal("0.75"),
    "committed_undrawn": Decimal("0.75"),
    "rcf_undrawn": Decimal("0.75"),
    "medium_risk": Decimal("0.75"),
    "medium_low_risk": Decimal("0.75"),

    # 100% CCF - Direct credit substitutes (same as SA)
    "full_risk": Decimal("1.00"),
    "guarantee_given": Decimal("1.00"),
    "acceptance": Decimal("1.00"),
    "credit_derivative": Decimal("1.00"),
    "forward_purchase": Decimal("1.00"),

    # Other items follow SA treatment
    "documentary_credit": Decimal("0.20"),
    "short_term_lc": Decimal("0.20"),
    "performance_guarantee": Decimal("0.50"),
    "bid_bond": Decimal("0.50"),
    "nif_ruf": Decimal("0.50"),
    "standby_lc": Decimal("0.50"),
}


def get_firb_ccf_table() -> pl.DataFrame:
    """
    Get F-IRB CCF lookup table as DataFrame.

    Under CRR Art. 166(8), F-IRB uses 75% CCF for undrawn commitments
    (except unconditionally cancellable which remain 0%).

    Returns:
        DataFrame with columns: ccf_category, ccf, description
    """
    rows = [
        ("unconditionally_cancellable", 0.00, "Unconditionally cancellable - 0%"),
        ("low_risk", 0.00, "Low risk - unconditionally cancellable"),
        ("undrawn_commitment", 0.75, "F-IRB undrawn commitment - 75%"),
        ("undrawn_short_term", 0.75, "F-IRB undrawn short-term - 75%"),
        ("undrawn_long_term", 0.75, "F-IRB undrawn long-term - 75%"),
        ("committed_undrawn", 0.75, "F-IRB committed undrawn - 75%"),
        ("rcf_undrawn", 0.75, "F-IRB RCF undrawn - 75%"),
        ("medium_risk", 0.75, "F-IRB medium risk - 75%"),
        ("medium_low_risk", 0.75, "F-IRB medium-low risk - 75%"),
        ("full_risk", 1.00, "Full risk - 100%"),
        ("guarantee_given", 1.00, "Guarantees given - 100%"),
        ("acceptance", 1.00, "Acceptances - 100%"),
        ("credit_derivative", 1.00, "Credit derivatives - 100%"),
        ("forward_purchase", 1.00, "Forward purchases - 100%"),
        ("documentary_credit", 0.20, "Documentary credits - 20%"),
        ("short_term_lc", 0.20, "Short-term LCs - 20%"),
        ("performance_guarantee", 0.50, "Performance guarantees - 50%"),
        ("bid_bond", 0.50, "Bid bonds - 50%"),
        ("nif_ruf", 0.50, "NIF/RUF - 50%"),
        ("standby_lc", 0.50, "Standby LCs - 50%"),
    ]

    return pl.DataFrame([
        {"ccf_category": cat, "ccf": ccf, "description": desc}
        for cat, ccf, desc in rows
    ]).with_columns([
        pl.col("ccf").cast(pl.Float64),
    ])


def _create_ccf_df() -> pl.DataFrame:
    """Create CCF lookup DataFrame."""
    rows = []

    # Add all CCF categories with their values
    ccf_categories = [
        # Category, CCF value, Description
        ("low_risk", 0.00, "Low risk - unconditionally cancellable"),
        ("unconditionally_cancellable", 0.00, "Unconditionally cancellable commitments"),
        ("medium_low_risk", 0.20, "Medium-low risk"),
        ("documentary_credit", 0.20, "Documentary letters of credit"),
        ("short_term_lc", 0.20, "Short-term letters of credit"),
        ("undrawn_short_term", 0.20, "Undrawn facilities <= 1 year"),
        ("medium_risk", 0.50, "Medium risk"),
        ("undrawn_long_term", 0.50, "Undrawn facilities > 1 year"),
        ("performance_guarantee", 0.50, "Performance guarantees"),
        ("bid_bond", 0.50, "Bid bonds"),
        ("nif_ruf", 0.50, "Note issuance / revolving underwriting facilities"),
        ("standby_lc", 0.50, "Standby letters of credit"),
        ("full_risk", 1.00, "Full risk"),
        ("guarantee_given", 1.00, "Guarantees given"),
        ("acceptance", 1.00, "Acceptances"),
        ("credit_derivative", 1.00, "Credit derivatives"),
        ("forward_purchase", 1.00, "Forward purchases"),
    ]

    for category, ccf, description in ccf_categories:
        rows.append({
            "ccf_category": category,
            "ccf": ccf,
            "description": description,
        })

    return pl.DataFrame(rows).with_columns([
        pl.col("ccf").cast(pl.Float64),
    ])


def get_ccf_table() -> pl.DataFrame:
    """
    Get CCF lookup table as DataFrame.

    Returns:
        DataFrame with columns: ccf_category, ccf, description
    """
    return _create_ccf_df()


def get_ccf_by_maturity_table() -> pl.DataFrame:
    """
    Get simplified CCF table based on original maturity.

    This is useful for joining when only maturity information is available.

    Returns:
        DataFrame with columns: maturity_bucket, ccf
    """
    return pl.DataFrame({
        "maturity_bucket": ["short_term", "long_term", "unconditionally_cancellable"],
        "ccf": [0.20, 0.50, 0.00],
        "maturity_threshold_years": [1.0, None, None],
        "description": [
            "Original maturity <= 1 year",
            "Original maturity > 1 year",
            "Can be cancelled without conditions",
        ],
    }).with_columns([
        pl.col("ccf").cast(pl.Float64),
        pl.col("maturity_threshold_years").cast(pl.Float64),
    ])


