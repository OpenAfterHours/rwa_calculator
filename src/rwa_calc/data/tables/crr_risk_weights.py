"""
CRR SA risk weight tables (CRR Art. 112-134).

Provides risk weight lookup tables as Polars DataFrames for efficient joins
in the RWA calculation pipeline.

References:
    - CRR Art. 114: Central govt/central bank risk weights
    - CRR Art. 120-121: Institution risk weights
    - CRR Art. 122: Corporate risk weights
    - CRR Art. 123: Retail risk weights
    - CRR Art. 125: Residential mortgage risk weights
    - CRR Art. 126: Commercial real estate risk weights
"""

from decimal import Decimal
from typing import TypedDict

import polars as pl

from rwa_calc.domain.enums import CQS, ExposureClass


# =============================================================================
# CENTRAL GOVT / CENTRAL BANK RISK WEIGHTS (CRR Art. 114)
# =============================================================================

CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS: dict[CQS, Decimal] = {
    CQS.CQS1: Decimal("0.00"),     # AAA to AA-
    CQS.CQS2: Decimal("0.20"),     # A+ to A-
    CQS.CQS3: Decimal("0.50"),     # BBB+ to BBB-
    CQS.CQS4: Decimal("1.00"),     # BB+ to BB-
    CQS.CQS5: Decimal("1.00"),     # B+ to B-
    CQS.CQS6: Decimal("1.50"),     # CCC+ and below
    CQS.UNRATED: Decimal("1.00"),  # Unrated
}


def _create_cgcb_df() -> pl.DataFrame:
    """Create central govt/central bank risk weight lookup DataFrame."""
    return pl.DataFrame({
        "cqs": [1, 2, 3, 4, 5, 6, None],
        "risk_weight": [0.00, 0.20, 0.50, 1.00, 1.00, 1.50, 1.00],
        "exposure_class": ["CENTRAL_GOVT_CENTRAL_BANK"] * 7,
    }).with_columns([
        pl.col("cqs").cast(pl.Int8),
        pl.col("risk_weight").cast(pl.Float64),
    ])


# =============================================================================
# INSTITUTION RISK WEIGHTS (CRR Art. 120-121)
# =============================================================================

# UK deviation: CQS 2 gets 30% instead of standard Basel 50%
INSTITUTION_RISK_WEIGHTS_UK: dict[CQS, Decimal] = {
    CQS.CQS1: Decimal("0.20"),     # AAA to AA-
    CQS.CQS2: Decimal("0.30"),     # A+ to A- (UK deviation)
    CQS.CQS3: Decimal("0.50"),     # BBB+ to BBB-
    CQS.CQS4: Decimal("1.00"),     # BB+ to BB-
    CQS.CQS5: Decimal("1.00"),     # B+ to B-
    CQS.CQS6: Decimal("1.50"),     # CCC+ and below
    CQS.UNRATED: Decimal("0.40"),  # Unrated (derived from sovereign CQS2)
}

INSTITUTION_RISK_WEIGHTS_STANDARD: dict[CQS, Decimal] = {
    CQS.CQS1: Decimal("0.20"),
    CQS.CQS2: Decimal("0.50"),     # Standard Basel
    CQS.CQS3: Decimal("0.50"),
    CQS.CQS4: Decimal("1.00"),
    CQS.CQS5: Decimal("1.00"),
    CQS.CQS6: Decimal("1.50"),
    CQS.UNRATED: Decimal("0.40"),
}


def _create_institution_df(use_uk_deviation: bool = True) -> pl.DataFrame:
    """Create institution risk weight lookup DataFrame."""
    if use_uk_deviation:
        weights = [0.20, 0.30, 0.50, 1.00, 1.00, 1.50, 0.40]
    else:
        weights = [0.20, 0.50, 0.50, 1.00, 1.00, 1.50, 0.40]

    return pl.DataFrame({
        "cqs": [1, 2, 3, 4, 5, 6, None],
        "risk_weight": weights,
        "exposure_class": ["INSTITUTION"] * 7,
        "uk_deviation": [use_uk_deviation] * 7,
    }).with_columns([
        pl.col("cqs").cast(pl.Int8),
        pl.col("risk_weight").cast(pl.Float64),
    ])


# =============================================================================
# CORPORATE RISK WEIGHTS (CRR Art. 122)
# =============================================================================

CORPORATE_RISK_WEIGHTS: dict[CQS, Decimal] = {
    CQS.CQS1: Decimal("0.20"),     # AAA to AA-
    CQS.CQS2: Decimal("0.50"),     # A+ to A-
    CQS.CQS3: Decimal("1.00"),     # BBB+ to BBB-
    CQS.CQS4: Decimal("1.00"),     # BB+ to BB-
    CQS.CQS5: Decimal("1.50"),     # B+ to B-
    CQS.CQS6: Decimal("1.50"),     # CCC+ and below
    CQS.UNRATED: Decimal("1.00"),  # Unrated
}


def _create_corporate_df() -> pl.DataFrame:
    """Create corporate risk weight lookup DataFrame."""
    return pl.DataFrame({
        "cqs": [1, 2, 3, 4, 5, 6, None],
        "risk_weight": [0.20, 0.50, 1.00, 1.00, 1.50, 1.50, 1.00],
        "exposure_class": ["CORPORATE"] * 7,
    }).with_columns([
        pl.col("cqs").cast(pl.Int8),
        pl.col("risk_weight").cast(pl.Float64),
    ])


# =============================================================================
# RETAIL RISK WEIGHT (CRR Art. 123)
# =============================================================================

RETAIL_RISK_WEIGHT: Decimal = Decimal("0.75")


def _create_retail_df() -> pl.DataFrame:
    """Create retail risk weight DataFrame (single row, no CQS dependency)."""
    return pl.DataFrame({
        "cqs": [None],
        "risk_weight": [0.75],
        "exposure_class": ["RETAIL"],
    }).with_columns([
        pl.col("cqs").cast(pl.Int8),
        pl.col("risk_weight").cast(pl.Float64),
    ])


# =============================================================================
# RESIDENTIAL MORTGAGE RISK WEIGHTS (CRR Art. 125)
# =============================================================================

class ResidentialMortgageParams(TypedDict):
    """Parameters for residential mortgage risk weighting."""
    ltv_threshold: Decimal
    rw_low_ltv: Decimal
    rw_high_ltv: Decimal


RESIDENTIAL_MORTGAGE_PARAMS: ResidentialMortgageParams = {
    "ltv_threshold": Decimal("0.80"),
    "rw_low_ltv": Decimal("0.35"),      # LTV <= 80%
    "rw_high_ltv": Decimal("0.75"),     # Portion above 80% LTV
}


def _create_residential_mortgage_df() -> pl.DataFrame:
    """
    Create residential mortgage risk weight lookup DataFrame.

    CRR Art. 125 treatment:
    - LTV <= 80%: 35% on whole exposure
    - LTV > 80%: Split treatment (35% on portion up to 80%, 75% on excess)

    The DataFrame provides parameters for the calculation engine.
    """
    return pl.DataFrame({
        "exposure_class": ["RESIDENTIAL_MORTGAGE"],
        "ltv_threshold": [0.80],
        "rw_low_ltv": [0.35],
        "rw_high_ltv": [0.75],
    }).with_columns([
        pl.col("ltv_threshold").cast(pl.Float64),
        pl.col("rw_low_ltv").cast(pl.Float64),
        pl.col("rw_high_ltv").cast(pl.Float64),
    ])


# =============================================================================
# COMMERCIAL REAL ESTATE RISK WEIGHTS (CRR Art. 126)
# =============================================================================

class CommercialREParams(TypedDict):
    """Parameters for commercial real estate risk weighting."""
    ltv_threshold: Decimal
    rw_low_ltv: Decimal
    rw_standard: Decimal


COMMERCIAL_RE_PARAMS: CommercialREParams = {
    "ltv_threshold": Decimal("0.50"),
    "rw_low_ltv": Decimal("0.50"),       # LTV <= 50% with income cover
    "rw_standard": Decimal("1.00"),       # Otherwise
}


def _create_commercial_re_df() -> pl.DataFrame:
    """
    Create commercial real estate risk weight lookup DataFrame.

    CRR Art. 126 treatment:
    - LTV <= 50% AND rental income >= 1.5x interest: 50%
    - Otherwise: 100% (standard corporate treatment)
    """
    return pl.DataFrame({
        "exposure_class": ["COMMERCIAL_RE"],
        "ltv_threshold": [0.50],
        "rw_low_ltv": [0.50],
        "rw_standard": [1.00],
        "income_cover_required": [True],
    }).with_columns([
        pl.col("ltv_threshold").cast(pl.Float64),
        pl.col("rw_low_ltv").cast(pl.Float64),
        pl.col("rw_standard").cast(pl.Float64),
    ])


# =============================================================================
# COMBINED RISK WEIGHT TABLE
# =============================================================================

def get_all_risk_weight_tables(use_uk_deviation: bool = True) -> dict[str, pl.DataFrame]:
    """
    Get all CRR SA risk weight tables.

    Args:
        use_uk_deviation: Whether to use UK-specific institution weights (30% for CQS2)

    Returns:
        Dictionary of DataFrames keyed by exposure class type
    """
    return {
        "central_govt_central_bank": _create_cgcb_df(),
        "institution": _create_institution_df(use_uk_deviation),
        "corporate": _create_corporate_df(),
        "retail": _create_retail_df(),
        "residential_mortgage": _create_residential_mortgage_df(),
        "commercial_re": _create_commercial_re_df(),
    }


def get_combined_cqs_risk_weights(use_uk_deviation: bool = True) -> pl.DataFrame:
    """
    Get combined CQS-based risk weight table for joins.

    Returns a single DataFrame with all CQS-based risk weights for
    sovereign, institution, and corporate exposure classes.

    Args:
        use_uk_deviation: Whether to use UK-specific institution weights

    Returns:
        Combined DataFrame with columns: exposure_class, cqs, risk_weight
    """
    return pl.concat([
        _create_cgcb_df().select(["exposure_class", "cqs", "risk_weight"]),
        _create_institution_df(use_uk_deviation).select(["exposure_class", "cqs", "risk_weight"]),
        _create_corporate_df().select(["exposure_class", "cqs", "risk_weight"]),
    ])


def lookup_risk_weight(
    exposure_class: str,
    cqs: int | None,
    use_uk_deviation: bool = True,
) -> Decimal:
    """
    Look up risk weight for exposure class and CQS.

    This is a convenience function for single lookups. For bulk processing,
    use the DataFrame tables with joins.

    Args:
        exposure_class: Exposure class (CENTRAL_GOVT_CENTRAL_BANK, INSTITUTION, CORPORATE, RETAIL)
        cqs: Credit quality step (1-6 or None/0 for unrated)
        use_uk_deviation: Whether to use UK-specific institution weights

    Returns:
        Risk weight as Decimal
    """
    exposure_upper = exposure_class.upper()

    # Convert cqs to CQS enum (None or 0 -> UNRATED)
    def _get_cqs_enum(cqs_val: int | None) -> CQS:
        if cqs_val is None or cqs_val == 0:
            return CQS.UNRATED
        return CQS(cqs_val)

    if exposure_upper == "CENTRAL_GOVT_CENTRAL_BANK":
        cqs_enum = _get_cqs_enum(cqs)
        return CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS.get(cqs_enum, CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.UNRATED])

    if exposure_upper == "INSTITUTION":
        table = INSTITUTION_RISK_WEIGHTS_UK if use_uk_deviation else INSTITUTION_RISK_WEIGHTS_STANDARD
        cqs_enum = _get_cqs_enum(cqs)
        return table.get(cqs_enum, table[CQS.UNRATED])

    if exposure_upper == "CORPORATE":
        cqs_enum = _get_cqs_enum(cqs)
        return CORPORATE_RISK_WEIGHTS.get(cqs_enum, CORPORATE_RISK_WEIGHTS[CQS.UNRATED])

    if exposure_upper == "RETAIL":
        return RETAIL_RISK_WEIGHT

    # Default to 100% for unrecognized classes
    return Decimal("1.00")


def calculate_residential_mortgage_rw(ltv: Decimal) -> tuple[Decimal, str]:
    """
    Calculate risk weight for residential mortgage based on LTV.

    CRR Art. 125 treatment:
    - LTV <= 80%: 35% on whole exposure
    - LTV > 80%: Split treatment (35% up to 80%, 75% on excess)

    Args:
        ltv: Loan-to-value ratio as Decimal

    Returns:
        Tuple of (risk_weight, description)
    """
    params = RESIDENTIAL_MORTGAGE_PARAMS
    threshold = params["ltv_threshold"]
    rw_low = params["rw_low_ltv"]
    rw_high = params["rw_high_ltv"]

    if ltv <= threshold:
        return rw_low, f"35% RW (LTV {ltv:.0%} <= 80%)"

    # Split treatment for high LTV
    portion_low = threshold / ltv
    portion_high = (ltv - threshold) / ltv
    avg_rw = rw_low * portion_low + rw_high * portion_high

    return avg_rw, f"Split RW ({ltv:.0%} LTV): {avg_rw:.1%}"


def calculate_commercial_re_rw(
    ltv: Decimal,
    has_income_cover: bool = True,
) -> tuple[Decimal, str]:
    """
    Calculate risk weight for commercial real estate.

    CRR Art. 126 treatment:
    - LTV <= 50% AND income cover: 50%
    - Otherwise: 100%

    Args:
        ltv: Loan-to-value ratio as Decimal
        has_income_cover: Whether rental income >= 1.5x interest payments

    Returns:
        Tuple of (risk_weight, description)
    """
    params = COMMERCIAL_RE_PARAMS
    threshold = params["ltv_threshold"]
    rw_low = params["rw_low_ltv"]
    rw_standard = params["rw_standard"]

    if ltv <= threshold and has_income_cover:
        return rw_low, f"50% RW (LTV {ltv:.0%} <= 50% with income cover)"

    return rw_standard, "100% RW (standard treatment)"
