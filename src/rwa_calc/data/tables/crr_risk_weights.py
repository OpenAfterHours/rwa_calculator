"""
CRR SA risk weight tables (CRR Art. 112-134).

Provides risk weight lookup tables as Polars DataFrames for efficient joins
in the RWA calculation pipeline.

References:
    - CRR Art. 114: Central govt/central bank risk weights
    - CRR Art. 115: Regional govt/local authority risk weights
    - CRR Art. 116: Public sector entity risk weights
    - CRR Art. 117: Multilateral development bank risk weights
    - CRR Art. 118: International organisation risk weights
    - CRR Art. 120-121: Institution risk weights
    - CRR Art. 122: Corporate risk weights
    - CRR Art. 123: Retail risk weights
    - CRR Art. 125: Residential mortgage risk weights
    - CRR Art. 126: Commercial real estate risk weights
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

import polars as pl

from rwa_calc.domain.enums import CQS

# =============================================================================
# CENTRAL GOVT / CENTRAL BANK RISK WEIGHTS (CRR Art. 114)
# =============================================================================

CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS: dict[CQS, Decimal] = {
    CQS.CQS1: Decimal("0.00"),  # AAA to AA-
    CQS.CQS2: Decimal("0.20"),  # A+ to A-
    CQS.CQS3: Decimal("0.50"),  # BBB+ to BBB-
    CQS.CQS4: Decimal("1.00"),  # BB+ to BB-
    CQS.CQS5: Decimal("1.00"),  # B+ to B-
    CQS.CQS6: Decimal("1.50"),  # CCC+ and below
    CQS.UNRATED: Decimal("1.00"),  # Unrated
}


def _create_cgcb_df() -> pl.DataFrame:
    """Create central govt/central bank risk weight lookup DataFrame."""
    return pl.DataFrame(
        {
            "cqs": [1, 2, 3, 4, 5, 6, None],
            "risk_weight": [0.00, 0.20, 0.50, 1.00, 1.00, 1.50, 1.00],
            "exposure_class": ["CENTRAL_GOVT_CENTRAL_BANK"] * 7,
        }
    ).with_columns(
        [
            pl.col("cqs").cast(pl.Int8),
            pl.col("risk_weight").cast(pl.Float64),
        ]
    )


# =============================================================================
# INSTITUTION RISK WEIGHTS (CRR Art. 120-121)
# =============================================================================

# UK deviation: CQS 2 gets 30% instead of standard Basel 50%
INSTITUTION_RISK_WEIGHTS_UK: dict[CQS, Decimal] = {
    CQS.CQS1: Decimal("0.20"),  # AAA to AA-
    CQS.CQS2: Decimal("0.30"),  # A+ to A- (UK deviation)
    CQS.CQS3: Decimal("0.50"),  # BBB+ to BBB-
    CQS.CQS4: Decimal("1.00"),  # BB+ to BB-
    CQS.CQS5: Decimal("1.00"),  # B+ to B-
    CQS.CQS6: Decimal("1.50"),  # CCC+ and below
    CQS.UNRATED: Decimal("0.40"),  # Unrated (derived from sovereign CQS2)
}

INSTITUTION_RISK_WEIGHTS_STANDARD: dict[CQS, Decimal] = {
    CQS.CQS1: Decimal("0.20"),
    CQS.CQS2: Decimal("0.50"),  # Standard Basel
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

    return pl.DataFrame(
        {
            "cqs": [1, 2, 3, 4, 5, 6, None],
            "risk_weight": weights,
            "exposure_class": ["INSTITUTION"] * 7,
            "uk_deviation": [use_uk_deviation] * 7,
        }
    ).with_columns(
        [
            pl.col("cqs").cast(pl.Int8),
            pl.col("risk_weight").cast(pl.Float64),
        ]
    )


# =============================================================================
# PUBLIC SECTOR ENTITY RISK WEIGHTS (CRR Art. 116 / PRA PS1/26 Art. 116)
# =============================================================================

# Sovereign-derived treatment (Art. 116(1), Table 2):
# Applied to PSEs without their own ECAI rating — uses sovereign CQS.
PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED: dict[CQS, Decimal] = {
    CQS.CQS1: Decimal("0.20"),
    CQS.CQS2: Decimal("0.50"),
    CQS.CQS3: Decimal("1.00"),
    CQS.CQS4: Decimal("1.00"),
    CQS.CQS5: Decimal("1.00"),
    CQS.CQS6: Decimal("1.50"),
}

# Own-rating treatment (Art. 116(2), Table 2A):
# Applied to PSEs with their own ECAI rating — uses the PSE's own CQS.
# Note: CQS 3 = 50% here vs 100% in sovereign-derived (Table 2).
PSE_RISK_WEIGHTS_OWN_RATING: dict[CQS, Decimal] = {
    CQS.CQS1: Decimal("0.20"),
    CQS.CQS2: Decimal("0.50"),
    CQS.CQS3: Decimal("0.50"),
    CQS.CQS4: Decimal("1.00"),
    CQS.CQS5: Decimal("1.00"),
    CQS.CQS6: Decimal("1.50"),
}

# Art. 116(3): Short-term PSE exposures (original effective maturity <= 3 months)
# receive 20% risk weight. No domestic currency condition required.
PSE_SHORT_TERM_RW = Decimal("0.20")

# Default for unrated PSE when sovereign CQS is unknown (conservative fallback)
PSE_UNRATED_DEFAULT_RW = Decimal("1.00")


def _create_pse_df() -> pl.DataFrame:
    """Create PSE risk weight lookup DataFrame (Art. 116(2), Table 2A, own-rating).

    Rated PSEs join against this table via their own CQS.
    Unrated PSEs use sovereign-derived treatment handled in the SA calculator.
    """
    return pl.DataFrame(
        {
            "cqs": [1, 2, 3, 4, 5, 6],
            "risk_weight": [0.20, 0.50, 0.50, 1.00, 1.00, 1.50],
            "exposure_class": ["PSE"] * 6,
        }
    ).with_columns(
        [
            pl.col("cqs").cast(pl.Int8),
            pl.col("risk_weight").cast(pl.Float64),
        ]
    )


# =============================================================================
# RGLA RISK WEIGHTS (CRR Art. 115 / PRA PS1/26 Art. 115)
# =============================================================================

# Sovereign-derived treatment (Art. 115(1)(a), Table 1A):
# Applied to RGLAs without their own ECAI rating — uses sovereign CQS.
# Values identical to PSE sovereign-derived (Table 2).
RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED: dict[CQS, Decimal] = {
    CQS.CQS1: Decimal("0.20"),
    CQS.CQS2: Decimal("0.50"),
    CQS.CQS3: Decimal("1.00"),
    CQS.CQS4: Decimal("1.00"),
    CQS.CQS5: Decimal("1.00"),
    CQS.CQS6: Decimal("1.50"),
}

# Own-rating treatment (Art. 115(1)(b), Table 1B):
# Applied to RGLAs with their own ECAI rating — uses the RGLA's own CQS.
# Note: CQS 3 = 50% here vs 100% in sovereign-derived (Table 1A).
RGLA_RISK_WEIGHTS_OWN_RATING: dict[CQS, Decimal] = {
    CQS.CQS1: Decimal("0.20"),
    CQS.CQS2: Decimal("0.50"),
    CQS.CQS3: Decimal("0.50"),
    CQS.CQS4: Decimal("1.00"),
    CQS.CQS5: Decimal("1.00"),
    CQS.CQS6: Decimal("1.50"),
}

# PRA designation: UK devolved administrations (Scotland, Wales, NI) → 0%
RGLA_UK_DEVOLVED_RW = Decimal("0.00")

# PRA designation: UK local authorities → 20%
RGLA_UK_LOCAL_AUTH_RW = Decimal("0.20")

# Art. 115(5): Domestic-currency RGLA exposures → 20% regardless of CQS
RGLA_DOMESTIC_CURRENCY_RW = Decimal("0.20")

# Default for unrated RGLA when sovereign CQS is unknown (conservative fallback)
RGLA_UNRATED_DEFAULT_RW = Decimal("1.00")


def _create_rgla_df() -> pl.DataFrame:
    """Create RGLA risk weight lookup DataFrame (Art. 115(1)(b), Table 1B, own-rating).

    Rated RGLAs join against this table via their own CQS.
    Unrated RGLAs use sovereign-derived treatment handled in the SA calculator.
    UK devolved govts (0%) and UK local authorities (20%) are overrides in the calculator.
    """
    return pl.DataFrame(
        {
            "cqs": [1, 2, 3, 4, 5, 6],
            "risk_weight": [0.20, 0.50, 0.50, 1.00, 1.00, 1.50],
            "exposure_class": ["RGLA"] * 6,
        }
    ).with_columns(
        [
            pl.col("cqs").cast(pl.Int8),
            pl.col("risk_weight").cast(pl.Float64),
        ]
    )


# =============================================================================
# MULTILATERAL DEVELOPMENT BANK RISK WEIGHTS (CRR Art. 117 / PRA PS1/26 Art. 117)
# =============================================================================

# Art. 117(1), Table 2B: Rated MDB risk weights (own CQS).
# Differs from institution table: CQS 2 = 30% (same as UK inst), unrated = 50% (not 40%).
MDB_RISK_WEIGHTS_TABLE_2B: dict[CQS, Decimal] = {
    CQS.CQS1: Decimal("0.20"),
    CQS.CQS2: Decimal("0.30"),
    CQS.CQS3: Decimal("0.50"),
    CQS.CQS4: Decimal("1.00"),
    CQS.CQS5: Decimal("1.00"),
    CQS.CQS6: Decimal("1.50"),
    CQS.UNRATED: Decimal("0.50"),
}

# Art. 117(2): Named MDBs receiving 0% risk weight unconditionally.
# These 16 MDBs get 0% regardless of CQS rating.
MDB_NAMED_ZERO_RW = Decimal("0.00")

# Default for unrated non-named MDBs (Art. 117(1), Table 2B unrated row)
MDB_UNRATED_RW = Decimal("0.50")


def _create_mdb_df() -> pl.DataFrame:
    """Create MDB risk weight lookup DataFrame (Art. 117(1), Table 2B).

    Named MDBs (Art. 117(2)) get 0% regardless of CQS — handled in the SA calculator.
    Rated non-named MDBs join against this table via their own CQS.
    Unrated non-named MDBs get 50% (Table 2B unrated row).
    """
    return pl.DataFrame(
        {
            "cqs": [1, 2, 3, 4, 5, 6, None],
            "risk_weight": [0.20, 0.30, 0.50, 1.00, 1.00, 1.50, 0.50],
            "exposure_class": ["MDB"] * 7,
        }
    ).with_columns(
        [
            pl.col("cqs").cast(pl.Int8),
            pl.col("risk_weight").cast(pl.Float64),
        ]
    )


# =============================================================================
# INTERNATIONAL ORGANISATION RISK WEIGHTS (CRR Art. 118 / PRA PS1/26 Art. 118)
# =============================================================================

# Art. 118: Named international organisations receiving 0% risk weight.
# EU, IMF, BIS, EFSF, ESM — no rated table exists (all IOs in Art. 118 are 0%).
IO_ZERO_RW = Decimal("0.00")


# =============================================================================
# CORPORATE RISK WEIGHTS (CRR Art. 122)
# =============================================================================

CORPORATE_RISK_WEIGHTS: dict[CQS, Decimal] = {
    CQS.CQS1: Decimal("0.20"),  # AAA to AA-
    CQS.CQS2: Decimal("0.50"),  # A+ to A-
    CQS.CQS3: Decimal("1.00"),  # BBB+ to BBB-
    CQS.CQS4: Decimal("1.00"),  # BB+ to BB-
    CQS.CQS5: Decimal("1.50"),  # B+ to B-
    CQS.CQS6: Decimal("1.50"),  # CCC+ and below
    CQS.UNRATED: Decimal("1.00"),  # Unrated
}


def _create_corporate_df() -> pl.DataFrame:
    """Create corporate risk weight lookup DataFrame."""
    return pl.DataFrame(
        {
            "cqs": [1, 2, 3, 4, 5, 6, None],
            "risk_weight": [0.20, 0.50, 1.00, 1.00, 1.50, 1.50, 1.00],
            "exposure_class": ["CORPORATE"] * 7,
        }
    ).with_columns(
        [
            pl.col("cqs").cast(pl.Int8),
            pl.col("risk_weight").cast(pl.Float64),
        ]
    )


# =============================================================================
# RETAIL RISK WEIGHT (CRR Art. 123)
# =============================================================================

RETAIL_RISK_WEIGHT: Decimal = Decimal("0.75")


# =============================================================================
# QUALIFYING CCP RISK WEIGHTS (CRR Art. 306, CRE54.14-15)
# =============================================================================

QCCP_PROPRIETARY_RW: Decimal = Decimal("0.02")  # CRE54.14: clearing member's own trades
QCCP_CLIENT_CLEARED_RW: Decimal = Decimal("0.04")  # CRE54.15: client-cleared trades


# =============================================================================
# OTHER ITEMS RISK WEIGHTS (CRR Art. 134 / PRA PS1/26 Art. 134)
# =============================================================================

OTHER_ITEMS_CASH_RW: Decimal = Decimal("0.00")  # Art. 134(1): cash and equivalent
OTHER_ITEMS_GOLD_RW: Decimal = Decimal("0.00")  # Art. 134(4): gold bullion in own vaults
OTHER_ITEMS_COLLECTION_RW: Decimal = Decimal("0.20")  # Art. 134(3): items in course of collection
OTHER_ITEMS_TANGIBLE_RW: Decimal = Decimal("1.00")  # Art. 134(2): tangible assets, prepaid
OTHER_ITEMS_DEFAULT_RW: Decimal = Decimal("1.00")  # Art. 134(2): all other items

# =============================================================================
# HIGH-RISK EXPOSURE RISK WEIGHT (CRR Art. 128)
# Items associated with particularly high risk: venture capital, private equity,
# speculative immovable property financing, and other PRA-designated high-risk items.
# =============================================================================

HIGH_RISK_RW: Decimal = Decimal("1.50")  # Art. 128: 150% flat


# =============================================================================
# DEFAULTED EXPOSURE RISK WEIGHTS (CRR Art. 127)
# =============================================================================

CRR_DEFAULTED_RW_HIGH_PROVISION = Decimal("1.00")  # Provisions >= 20% of unsecured EAD
CRR_DEFAULTED_RW_LOW_PROVISION = Decimal("1.50")  # Provisions < 20% of unsecured EAD
CRR_DEFAULTED_PROVISION_THRESHOLD = Decimal("0.20")  # 20% threshold


def _create_retail_df() -> pl.DataFrame:
    """Create retail risk weight DataFrame (single row, no CQS dependency)."""
    return pl.DataFrame(
        {
            "cqs": [None],
            "risk_weight": [0.75],
            "exposure_class": ["RETAIL"],
        }
    ).with_columns(
        [
            pl.col("cqs").cast(pl.Int8),
            pl.col("risk_weight").cast(pl.Float64),
        ]
    )


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
    "rw_low_ltv": Decimal("0.35"),  # LTV <= 80%
    "rw_high_ltv": Decimal("0.75"),  # Portion above 80% LTV
}


def _create_residential_mortgage_df() -> pl.DataFrame:
    """
    Create residential mortgage risk weight lookup DataFrame.

    CRR Art. 125 treatment:
    - LTV <= 80%: 35% on whole exposure
    - LTV > 80%: Split treatment (35% on portion up to 80%, 75% on excess)

    The DataFrame provides parameters for the calculation engine.
    """
    return pl.DataFrame(
        {
            "exposure_class": ["RESIDENTIAL_MORTGAGE"],
            "ltv_threshold": [0.80],
            "rw_low_ltv": [0.35],
            "rw_high_ltv": [0.75],
        }
    ).with_columns(
        [
            pl.col("ltv_threshold").cast(pl.Float64),
            pl.col("rw_low_ltv").cast(pl.Float64),
            pl.col("rw_high_ltv").cast(pl.Float64),
        ]
    )


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
    "rw_low_ltv": Decimal("0.50"),  # LTV <= 50% with income cover
    "rw_standard": Decimal("1.00"),  # Otherwise
}


def _create_commercial_re_df() -> pl.DataFrame:
    """
    Create commercial real estate risk weight lookup DataFrame.

    CRR Art. 126 treatment:
    - LTV <= 50% AND rental income >= 1.5x interest: 50%
    - Otherwise: 100% (standard corporate treatment)
    """
    return pl.DataFrame(
        {
            "exposure_class": ["COMMERCIAL_RE"],
            "ltv_threshold": [0.50],
            "rw_low_ltv": [0.50],
            "rw_standard": [1.00],
            "income_cover_required": [True],
        }
    ).with_columns(
        [
            pl.col("ltv_threshold").cast(pl.Float64),
            pl.col("rw_low_ltv").cast(pl.Float64),
            pl.col("rw_standard").cast(pl.Float64),
        ]
    )


# =============================================================================
# COVERED BOND RISK WEIGHTS (CRR Art. 129)
# =============================================================================

COVERED_BOND_RISK_WEIGHTS: dict[CQS, Decimal] = {
    CQS.CQS1: Decimal("0.10"),  # AAA to AA-
    CQS.CQS2: Decimal("0.20"),  # A+ to A-
    CQS.CQS3: Decimal("0.20"),  # BBB+ to BBB-
    CQS.CQS4: Decimal("0.50"),  # BB+ to BB-
    CQS.CQS5: Decimal("0.50"),  # B+ to B-
    CQS.CQS6: Decimal("1.00"),  # CCC+ and below
}

# Unrated covered bond derivation from issuer institution risk weight
# (CRR Art. 129(5), PRA PS1/26 Art. 129)
COVERED_BOND_UNRATED_DERIVATION: dict[Decimal, Decimal] = {
    Decimal("0.20"): Decimal("0.10"),
    Decimal("0.30"): Decimal("0.15"),
    Decimal("0.40"): Decimal("0.20"),
    Decimal("0.50"): Decimal("0.25"),
    Decimal("0.75"): Decimal("0.35"),
    Decimal("1.00"): Decimal("0.50"),
    Decimal("1.50"): Decimal("1.00"),
}


def _create_covered_bond_df() -> pl.DataFrame:
    """Create covered bond risk weight lookup DataFrame (CRR Art. 129)."""
    return pl.DataFrame(
        {
            "cqs": [1, 2, 3, 4, 5, 6],
            "risk_weight": [0.10, 0.20, 0.20, 0.50, 0.50, 1.00],
            "exposure_class": ["COVERED_BOND"] * 6,
        }
    ).with_columns(
        [
            pl.col("cqs").cast(pl.Int8),
            pl.col("risk_weight").cast(pl.Float64),
        ]
    )


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
        "rgla": _create_rgla_df(),
        "pse": _create_pse_df(),
        "mdb": _create_mdb_df(),
        "institution": _create_institution_df(use_uk_deviation),
        "corporate": _create_corporate_df(),
        "retail": _create_retail_df(),
        "residential_mortgage": _create_residential_mortgage_df(),
        "commercial_re": _create_commercial_re_df(),
        "covered_bond": _create_covered_bond_df(),
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
    return pl.concat(
        [
            _create_cgcb_df().select(["exposure_class", "cqs", "risk_weight"]),
            _create_rgla_df().select(["exposure_class", "cqs", "risk_weight"]),
            _create_pse_df().select(["exposure_class", "cqs", "risk_weight"]),
            _create_mdb_df().select(["exposure_class", "cqs", "risk_weight"]),
            _create_institution_df(use_uk_deviation).select(
                ["exposure_class", "cqs", "risk_weight"]
            ),
            _create_corporate_df().select(["exposure_class", "cqs", "risk_weight"]),
            _create_covered_bond_df().select(["exposure_class", "cqs", "risk_weight"]),
        ]
    )


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
        return CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS.get(
            cqs_enum, CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.UNRATED]
        )

    if exposure_upper == "PSE":
        cqs_enum = _get_cqs_enum(cqs)
        if cqs_enum == CQS.UNRATED:
            # Unrated PSE: sovereign-derived treatment (Art. 116(1), Table 2)
            # Returns 100% as conservative default (caller should use sovereign CQS)
            return PSE_UNRATED_DEFAULT_RW
        return PSE_RISK_WEIGHTS_OWN_RATING.get(cqs_enum, PSE_UNRATED_DEFAULT_RW)

    if exposure_upper == "RGLA":
        cqs_enum = _get_cqs_enum(cqs)
        if cqs_enum == CQS.UNRATED:
            # Unrated RGLA: sovereign-derived treatment (Art. 115(1)(a), Table 1A)
            # Returns 100% as conservative default (caller should use sovereign CQS)
            return RGLA_UNRATED_DEFAULT_RW
        return RGLA_RISK_WEIGHTS_OWN_RATING.get(cqs_enum, RGLA_UNRATED_DEFAULT_RW)

    if exposure_upper == "MDB":
        cqs_enum = _get_cqs_enum(cqs)
        return MDB_RISK_WEIGHTS_TABLE_2B.get(cqs_enum, MDB_RISK_WEIGHTS_TABLE_2B[CQS.UNRATED])

    if exposure_upper == "INSTITUTION":
        table = (
            INSTITUTION_RISK_WEIGHTS_UK if use_uk_deviation else INSTITUTION_RISK_WEIGHTS_STANDARD
        )
        cqs_enum = _get_cqs_enum(cqs)
        return table.get(cqs_enum, table[CQS.UNRATED])

    if exposure_upper == "CORPORATE":
        cqs_enum = _get_cqs_enum(cqs)
        return CORPORATE_RISK_WEIGHTS.get(cqs_enum, CORPORATE_RISK_WEIGHTS[CQS.UNRATED])

    if exposure_upper == "RETAIL":
        return RETAIL_RISK_WEIGHT

    if exposure_upper == "OTHER":
        return OTHER_ITEMS_DEFAULT_RW

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
