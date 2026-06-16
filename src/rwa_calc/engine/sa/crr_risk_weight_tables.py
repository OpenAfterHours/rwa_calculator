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

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import TypedDict, cast

import polars as pl
from watchfire import cites

from rwa_calc.domain.enums import CQS
from rwa_calc.rulebook.resolve import ResolvedRulepack, resolve

# SA risk-weight values now live in the common/CRR rulepack packs. They are read
# back here as the canonical module-level dicts/scalars so this module stays a
# thin pack-binding shim with one source of truth (the pack); every builder /
# engine / guarantee consumer keeps indexing the same names unchanged.
_SA_RW_PACK = resolve("crr", date(2026, 1, 1))
# Basel-3.1 overlay — sources the B31 ECRA institution tables hosted in this
# module (their VALUES live in packs/b31.py; the bindings stay here for now).
_SA_RW_PACK_B31 = resolve("b31", date(2027, 1, 1))
_RETAIL_RISK_WEIGHT_DEC: Decimal = _SA_RW_PACK.scalar_param("retail_risk_weight").value
_OTHER_ITEMS_DEFAULT_RW_DEC: Decimal = _SA_RW_PACK.scalar_param("other_items_default_rw").value


def _cqs_rw_from_pack(name: str, pack: ResolvedRulepack = _SA_RW_PACK) -> dict[CQS, Decimal]:
    """Read a CQS-enum-keyed SA risk-weight LookupTable back from the rulepack.

    Returns the exact ``dict[CQS, Decimal]`` the former module-level literal
    held (the pack stores the same Decimals under the same CQS keys), so all
    downstream consumers are byte-identical. ``pack`` selects the regime overlay
    (CRR by default; pass ``_SA_RW_PACK_B31`` for the B31 ECRA tables).
    """
    return cast("dict[CQS, Decimal]", dict(pack.lookup(name).entries))


def _decimal_rw_from_pack(
    name: str, pack: ResolvedRulepack = _SA_RW_PACK
) -> dict[Decimal, Decimal]:
    """Read a Decimal-keyed RW-derivation LookupTable back from the rulepack.

    Used for the covered-bond unrated derivations (issuer-institution RW ->
    covered-bond RW). Returns the exact ``dict[Decimal, Decimal]`` the former
    literal held, so the derivation expressions stay byte-identical. ``pack``
    selects the regime overlay (CRR by default; pass ``_SA_RW_PACK_B31``).
    """
    return cast("dict[Decimal, Decimal]", dict(pack.lookup(name).entries))


def _scalar_dec(name: str, pack: ResolvedRulepack = _SA_RW_PACK) -> Decimal:
    """Read a cited SA risk-weight scalar's Decimal value back from the rulepack."""
    return pack.scalar_param(name).value


# =============================================================================
# INTERNAL DATAFRAME-BUILD HELPERS
#
# Each `_create_*_df` builder below derives its numeric values from the
# corresponding regulatory constant dict declared in this module. The helpers
# guarantee there is exactly one source of truth for every regulatory scalar —
# update the dict and the DataFrame tracks automatically.
# =============================================================================

_CQS_ORDER_WITH_UNRATED: tuple[CQS, ...] = (
    CQS.CQS1,
    CQS.CQS2,
    CQS.CQS3,
    CQS.CQS4,
    CQS.CQS5,
    CQS.CQS6,
    CQS.UNRATED,
)
_CQS_ORDER_RATED_ONLY: tuple[CQS, ...] = _CQS_ORDER_WITH_UNRATED[:-1]


def _cqs_to_int(c: CQS) -> int | None:
    """Map a CQS enum member to its DataFrame `cqs` column value.

    UNRATED maps to SQL NULL (``None``) so downstream joins can match
    unrated rows via null-safe joins.
    """
    return None if c is CQS.UNRATED else int(c.value)


def _build_cqs_rw_df(
    weights: dict[CQS, Decimal],
    exposure_class: str,
    order: tuple[CQS, ...] = _CQS_ORDER_WITH_UNRATED,
    extra_cols: dict[str, list[object]] | None = None,
) -> pl.DataFrame:
    """Build a CQS risk-weight lookup DataFrame from a CQS-keyed dict.

    Args:
        weights: CQS → risk weight (Decimal) mapping
        exposure_class: Value for the `exposure_class` column
        order: Iteration order controlling row order in the output DataFrame
        extra_cols: Optional additional columns (same length as ``order``)

    Returns:
        DataFrame with columns [cqs (Int8), risk_weight (Float64), exposure_class, ...]
    """
    data: dict[str, Sequence[object]] = {
        "cqs": [_cqs_to_int(c) for c in order],
        "risk_weight": [float(weights[c]) for c in order],
        "exposure_class": [exposure_class] * len(order),
    }
    if extra_cols:
        data.update(extra_cols)
    return pl.DataFrame(data).with_columns(
        [
            pl.col("cqs").cast(pl.Int8),
            pl.col("risk_weight").cast(pl.Float64),
        ]
    )


# =============================================================================
# CENTRAL GOVT / CENTRAL BANK RISK WEIGHTS (CRR Art. 114)
# =============================================================================

CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS: dict[CQS, Decimal] = _cqs_rw_from_pack("cgcb_risk_weights")


def _create_cgcb_df() -> pl.DataFrame:
    """Create central govt/central bank risk weight lookup DataFrame."""
    return _build_cqs_rw_df(
        CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
        "CENTRAL_GOVT_CENTRAL_BANK",
    )


# ECA / MEIP direct sovereign risk weights (CRR Art. 137(1)-(2) Table 9) moved
# to the common rulepack pack (eca_meip_risk_weights).


# =============================================================================
# INSTITUTION RISK WEIGHTS (CRR Art. 120 Table 3 / PRA PS1/26 Art. 120 ECRA)
# =============================================================================

INSTITUTION_RISK_WEIGHTS_CRR: dict[CQS, Decimal] = _cqs_rw_from_pack("institution_rw_crr")

INSTITUTION_RISK_WEIGHTS_B31_ECRA: dict[CQS, Decimal] = _cqs_rw_from_pack(
    "institution_rw_b31_ecra", _SA_RW_PACK_B31
)

# CRR Art. 120(2) Table 4: rated institution, residual maturity <= 3 months.
# Numerically identical to PRA PS1/26 Art. 120(2) Table 4 ECRA short-term;
# kept as a separate dict for symmetry with the long-term CRR/B31 split.
INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR: dict[CQS, Decimal] = _cqs_rw_from_pack(
    "institution_short_term_rw_crr"
)

# PRA PS1/26 Art. 120(2) Table 4: short-term ECRA rated institution
# (residual maturity <= 3 months). Numerically identical to CRR Table 4 across
# CQS 1-6; the unrated fallback maps to SCRA Grade A short-term (20%).
INSTITUTION_SHORT_TERM_RISK_WEIGHTS_B31_ECRA: dict[CQS, Decimal] = _cqs_rw_from_pack(
    "institution_short_term_rw_b31_ecra", _SA_RW_PACK_B31
)

# CRR Art. 121(3): unrated institution, original effective maturity <= 3 months.
# Overrides the Table 5 sovereign-derived fallback.
INSTITUTION_SHORT_TERM_UNRATED_RW_CRR = _scalar_dec("institution_short_term_unrated_rw_crr")

# CRR Art. 121 Table 5: sovereign-derived risk weights for unrated institutions.
# Maps the institution's home-jurisdiction sovereign CQS to the institution RW.
# Also reused for non-named MDBs under Art. 117(1) (institution treatment) when
# the MDB itself is unrated and a sovereign CQS is available for the MDB's
# country of incorporation. Numeric values match Art. 116(1) Table 2 / Art.
# 115(1)(a) Table 1A by design — the sovereign-derived shape is shared across
# institutions, PSEs and RGLAs in CRR.
INSTITUTION_RISK_WEIGHTS_SOVEREIGN_DERIVED: dict[CQS, Decimal] = _cqs_rw_from_pack(
    "institution_rw_sovereign_derived"
)


def _create_institution_df(is_basel_3_1: bool = False) -> pl.DataFrame:
    """Create institution risk weight lookup DataFrame.

    Args:
        is_basel_3_1: True for PRA PS1/26 ECRA values (CQS 2 = 30%),
            False for CRR Art. 120 Table 3 (CQS 2 = 50%).
    """
    weights = INSTITUTION_RISK_WEIGHTS_B31_ECRA if is_basel_3_1 else INSTITUTION_RISK_WEIGHTS_CRR
    return _build_cqs_rw_df(weights, "INSTITUTION")


# The institution / corporate guarantor risk-weight expression builders moved to
# ``engine/sa/guarantor_rw.py`` (engine logic reading the pack directly); this
# module keeps only the pack-bound risk-weight dicts they consume.


# =============================================================================
# PUBLIC SECTOR ENTITY RISK WEIGHTS (CRR Art. 116 / PRA PS1/26 Art. 116)
# =============================================================================

# Sovereign-derived treatment (Art. 116(1), Table 2):
# Applied to PSEs without their own ECAI rating — uses sovereign CQS.
PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED: dict[CQS, Decimal] = _cqs_rw_from_pack(
    "pse_risk_weights_sovereign_derived"
)

# Own-rating treatment (Art. 116(2), Table 2A):
# Applied to PSEs with their own ECAI rating — uses the PSE's own CQS.
# Note: CQS 3 = 50% here vs 100% in sovereign-derived (Table 2).
PSE_RISK_WEIGHTS_OWN_RATING: dict[CQS, Decimal] = _cqs_rw_from_pack("pse_risk_weights_own_rating")

# Art. 116(3): Short-term PSE exposures (original effective maturity <= 3 months)
# receive 20% risk weight. No domestic currency condition required.
PSE_SHORT_TERM_RW = _scalar_dec("pse_short_term_rw")

# Default for unrated PSE when sovereign CQS is unknown (conservative fallback)
PSE_UNRATED_DEFAULT_RW = _scalar_dec("pse_unrated_default_rw")


@cites("CRR Art. 116")
def _create_pse_df() -> pl.DataFrame:
    """Create PSE risk weight lookup DataFrame (Art. 116(2), Table 2A, own-rating).

    Rated PSEs join against this table via their own CQS.
    Unrated PSEs use sovereign-derived treatment handled in the SA calculator.
    """
    return _build_cqs_rw_df(
        PSE_RISK_WEIGHTS_OWN_RATING,
        "PSE",
        order=_CQS_ORDER_RATED_ONLY,
    )


# =============================================================================
# RGLA RISK WEIGHTS (CRR Art. 115 / PRA PS1/26 Art. 115)
# =============================================================================

# Sovereign-derived treatment (Art. 115(1)(a), Table 1A):
# Applied to RGLAs without their own ECAI rating — uses sovereign CQS.
# Values identical to PSE sovereign-derived (Table 2).
RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED: dict[CQS, Decimal] = _cqs_rw_from_pack(
    "rgla_risk_weights_sovereign_derived"
)

# Own-rating treatment (Art. 115(1)(b), Table 1B):
# Applied to RGLAs with their own ECAI rating — uses the RGLA's own CQS.
# Note: CQS 3 = 50% here vs 100% in sovereign-derived (Table 1A).
RGLA_RISK_WEIGHTS_OWN_RATING: dict[CQS, Decimal] = _cqs_rw_from_pack("rgla_risk_weights_own_rating")

# PRA designation: UK devolved administrations (Scotland, Wales, NI) → 0%
RGLA_UK_DEVOLVED_RW = _scalar_dec("rgla_uk_devolved_rw")

# PRA designation: UK local authorities → 20%
RGLA_UK_LOCAL_AUTH_RW = _scalar_dec("rgla_uk_local_auth_rw")

# Art. 115(5): Domestic-currency RGLA exposures → 20% regardless of CQS
RGLA_DOMESTIC_CURRENCY_RW = _scalar_dec("rgla_domestic_currency_rw")

# Default for unrated RGLA when sovereign CQS is unknown (conservative fallback)
RGLA_UNRATED_DEFAULT_RW = _scalar_dec("rgla_unrated_default_rw")


@cites("CRR Art. 115")
def _create_rgla_df() -> pl.DataFrame:
    """Create RGLA risk weight lookup DataFrame (Art. 115(1)(b), Table 1B, own-rating).

    Rated RGLAs join against this table via their own CQS.
    Unrated RGLAs use sovereign-derived treatment handled in the SA calculator.
    UK devolved govts (0%) and UK local authorities (20%) are overrides in the calculator.
    """
    return _build_cqs_rw_df(
        RGLA_RISK_WEIGHTS_OWN_RATING,
        "RGLA",
        order=_CQS_ORDER_RATED_ONLY,
    )


# =============================================================================
# MULTILATERAL DEVELOPMENT BANK RISK WEIGHTS (CRR Art. 117 / PRA PS1/26 Art. 117)
# =============================================================================

# PRA PS1/26 Art. 117(1)(a) Table 2B: Basel 3.1 dedicated MDB risk weights
# (own CQS). Used ONLY under the Basel 3.1 framework (is_basel_3_1=True).
#
# Under CRR Art. 117(1), non-named MDBs are treated as institutions and routed
# through INSTITUTION_RISK_WEIGHTS_CRR (rated) or
# INSTITUTION_RISK_WEIGHTS_SOVEREIGN_DERIVED / Art. 121 fallback (unrated) — this
# table is unreachable under CRR after the Art. 117(1) institution-routing fix.
#
# Differs from institution table: CQS 2 = 30% (vs CRR 50%), unrated = 50% (not 40%).
MDB_RISK_WEIGHTS_TABLE_2B: dict[CQS, Decimal] = _cqs_rw_from_pack("mdb_risk_weights_table_2b")

# Art. 117(2): Named MDBs receiving 0% risk weight unconditionally.
# These 16 MDBs get 0% regardless of CQS rating.
MDB_NAMED_ZERO_RW = _scalar_dec("mdb_named_zero_rw")

# Default for unrated non-named MDBs (Art. 117(1), Table 2B unrated row)
MDB_UNRATED_RW = _scalar_dec("mdb_unrated_rw")


@cites("CRR Art. 117")
def _create_mdb_df() -> pl.DataFrame:
    """Create MDB risk weight lookup DataFrame (Art. 117(1), Table 2B).

    Named MDBs (Art. 117(2)) get 0% regardless of CQS — handled in the SA calculator.
    Rated non-named MDBs join against this table via their own CQS.
    Unrated non-named MDBs get 50% (Table 2B unrated row).
    """
    return _build_cqs_rw_df(MDB_RISK_WEIGHTS_TABLE_2B, "MDB")


# =============================================================================
# INTERNATIONAL ORGANISATION RISK WEIGHTS (CRR Art. 118 / PRA PS1/26 Art. 118)
# =============================================================================

# Art. 118: Named international organisations receiving 0% risk weight.
# EU, IMF, BIS, EFSF, ESM — no rated table exists (all IOs in Art. 118 are 0%).
IO_ZERO_RW = _scalar_dec("io_zero_rw")

INTERNATIONAL_ORG_RISK_WEIGHTS: dict[CQS, Decimal] = {
    CQS.UNRATED: IO_ZERO_RW,
}


@cites("CRR Art. 118")
def _create_io_df() -> pl.DataFrame:
    """Create international organisation risk weight lookup DataFrame (Art. 118).

    Art. 118 names 16 IOs (EU, IMF, BIS, ECB, EFSF, ESM, IBRD, IFC, IADB,
    ADB, AfDB, CEB, NIB, CDB, EBRD, EFSI) that receive 0% unconditionally.
    Returns a single-row DataFrame keyed on the unrated CQS sentinel so the
    canonical risk-weight value lives alongside the other SA tables; the
    SA calculator's inline IO branch is the runtime consumer.
    """
    return _build_cqs_rw_df(
        INTERNATIONAL_ORG_RISK_WEIGHTS,
        "INTERNATIONAL_ORG",
        order=(CQS.UNRATED,),
    )


# =============================================================================
# CORPORATE RISK WEIGHTS (CRR Art. 122)
# =============================================================================

CORPORATE_RISK_WEIGHTS: dict[CQS, Decimal] = _cqs_rw_from_pack("corporate_risk_weights")


def _create_corporate_df() -> pl.DataFrame:
    """Create corporate risk weight lookup DataFrame."""
    return _build_cqs_rw_df(CORPORATE_RISK_WEIGHTS, "CORPORATE")


# =============================================================================
# RETAIL RISK WEIGHT (CRR Art. 123)
# =============================================================================

# RETAIL_RISK_WEIGHT (75% flat) moved to the common rulepack pack
# (retail_risk_weight).

# Art. 122: Corporate SME flat under CRR (Basel 3.1 reduces this to 85% via
# B31_CORPORATE_SME_RW). Named for the SA override chain — explicit beats magic.
CRR_CORPORATE_SME_RW: Decimal = _scalar_dec("crr_corporate_sme_rw")

# Art. 123: Non-regulatory retail (fails qualifying criteria) -> 100% under CRR.
# Mirrors B31_RETAIL_NON_REGULATORY_RW; named to remove the magic-1.0 from the
# SA override chain.
CRR_NON_REGULATORY_RETAIL_RW: Decimal = _scalar_dec("crr_non_regulatory_retail_rw")


# Qualifying-CCP trade-exposure RWs (CRR Art. 306 / CRE54.14-15), Other-items RWs
# (CRR Art. 134) and the high-risk-item RW (CRR Art. 128, 150% flat) moved to the
# common rulepack pack (qccp_proprietary_rw / qccp_client_cleared_rw /
# other_items_*_rw / high_risk_rw).


# =============================================================================
# DEFAULTED EXPOSURE RISK WEIGHTS (CRR Art. 127)
# =============================================================================

CRR_DEFAULTED_RW_HIGH_PROVISION = _scalar_dec(
    "crr_defaulted_rw_high_provision"
)  # Provisions >= 20% of unsecured EAD
CRR_DEFAULTED_RW_LOW_PROVISION = _scalar_dec(
    "crr_defaulted_rw_low_provision"
)  # Provisions < 20% of unsecured EAD
CRR_DEFAULTED_PROVISION_THRESHOLD = _scalar_dec(
    "crr_defaulted_provision_threshold"
)  # 20% threshold


def _create_retail_df() -> pl.DataFrame:
    """Create retail risk weight DataFrame (single row, no CQS dependency)."""
    return pl.DataFrame(
        {
            "cqs": [None],
            "risk_weight": [float(_RETAIL_RISK_WEIGHT_DEC)],
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


RESIDENTIAL_MORTGAGE_PARAMS: ResidentialMortgageParams = cast(
    "ResidentialMortgageParams", dict(_SA_RW_PACK.formula("residential_mortgage_params").params)
)


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
            "ltv_threshold": [float(RESIDENTIAL_MORTGAGE_PARAMS["ltv_threshold"])],
            "rw_low_ltv": [float(RESIDENTIAL_MORTGAGE_PARAMS["rw_low_ltv"])],
            "rw_high_ltv": [float(RESIDENTIAL_MORTGAGE_PARAMS["rw_high_ltv"])],
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


COMMERCIAL_RE_PARAMS: CommercialREParams = cast(
    "CommercialREParams", dict(_SA_RW_PACK.formula("commercial_re_params").params)
)


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
            "ltv_threshold": [float(COMMERCIAL_RE_PARAMS["ltv_threshold"])],
            "rw_low_ltv": [float(COMMERCIAL_RE_PARAMS["rw_low_ltv"])],
            "rw_standard": [float(COMMERCIAL_RE_PARAMS["rw_standard"])],
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

COVERED_BOND_RISK_WEIGHTS: dict[CQS, Decimal] = _cqs_rw_from_pack("covered_bond_risk_weights")

# Unrated covered bond derivation from issuer institution risk weight.
#
# CRR Art. 129(5)(a)-(d) enumerates exactly four sub-paragraphs and therefore
# admits only four institution-RW inputs {0.20, 0.50, 1.00, 1.50}. Crucially,
# CRR Art. 129(5)(b) maps 0.50 -> 0.20 — NOT 0.25 (the latter is the PRA
# PS1/26 value).
#
# PRA PS1/26 Art. 129(5)(a)/(aa)/(ab)/(b)/(ba)/(c)/(d) extends the table to
# seven inputs, adding 0.30 (ECRA CQS2), 0.40 (SCRA Grade A) and 0.75
# (SCRA Grade B), and changes (b) to 0.50 -> 0.25.
#
# The two regimes are stored as separate dicts so callers cannot accidentally
# pick up a B31-only key (or the wrong (b) value) under CRR — each consumer
# selects the regime-specific dict explicitly (no unsuffixed alias).
COVERED_BOND_UNRATED_DERIVATION_CRR: dict[Decimal, Decimal] = _decimal_rw_from_pack(
    "covered_bond_unrated_derivation_crr"
)

COVERED_BOND_UNRATED_DERIVATION_B31: dict[Decimal, Decimal] = _decimal_rw_from_pack(
    "covered_bond_unrated_derivation_b31", _SA_RW_PACK_B31
)


@cites("CRR Art. 129")
def _create_covered_bond_df() -> pl.DataFrame:
    """Create covered bond risk weight lookup DataFrame (CRR Art. 129)."""
    return _build_cqs_rw_df(
        COVERED_BOND_RISK_WEIGHTS,
        "COVERED_BOND",
        order=_CQS_ORDER_RATED_ONLY,
    )


# =============================================================================
# COMBINED RISK WEIGHT TABLE
# =============================================================================


def get_all_risk_weight_tables() -> dict[str, pl.DataFrame]:
    """
    Get all CRR SA risk weight tables.

    Institution table is the CRR Art. 120 Table 3 (CQS 2 = 50%); the Basel 3.1
    ECRA variant is selected via ``get_b31_combined_cqs_risk_weights``.

    Returns:
        Dictionary of DataFrames keyed by exposure class type
    """
    return {
        "central_govt_central_bank": _create_cgcb_df(),
        "rgla": _create_rgla_df(),
        "pse": _create_pse_df(),
        "mdb": _create_mdb_df(),
        "institution": _create_institution_df(is_basel_3_1=False),
        "corporate": _create_corporate_df(),
        "retail": _create_retail_df(),
        "residential_mortgage": _create_residential_mortgage_df(),
        "commercial_re": _create_commercial_re_df(),
        "covered_bond": _create_covered_bond_df(),
    }


def get_combined_cqs_risk_weights() -> pl.DataFrame:
    """
    Get combined CQS-based CRR risk weight table for joins.

    Uses CRR Art. 120 Table 3 institution weights (CQS 2 = 50%). For Basel 3.1
    ECRA values use ``get_b31_combined_cqs_risk_weights`` instead.

    Returns:
        Combined DataFrame with columns: exposure_class, cqs, risk_weight
    """
    return pl.concat(
        [
            _create_cgcb_df().select(["exposure_class", "cqs", "risk_weight"]),
            _create_rgla_df().select(["exposure_class", "cqs", "risk_weight"]),
            _create_pse_df().select(["exposure_class", "cqs", "risk_weight"]),
            _create_mdb_df().select(["exposure_class", "cqs", "risk_weight"]),
            _create_institution_df(is_basel_3_1=False).select(
                ["exposure_class", "cqs", "risk_weight"]
            ),
            _create_corporate_df().select(["exposure_class", "cqs", "risk_weight"]),
            _create_covered_bond_df().select(["exposure_class", "cqs", "risk_weight"]),
        ]
    )


def lookup_risk_weight(
    exposure_class: str,
    cqs: int | None,
    is_basel_3_1: bool = False,
) -> Decimal:
    """
    Look up risk weight for exposure class and CQS.

    This is a convenience function for single lookups. For bulk processing,
    use the DataFrame tables with joins.

    Args:
        exposure_class: Exposure class (CENTRAL_GOVT_CENTRAL_BANK, INSTITUTION, CORPORATE, RETAIL)
        cqs: Credit quality step (1-6 or None/0 for unrated)
        is_basel_3_1: True selects PRA PS1/26 ECRA institution weights
            (CQS 2 = 30%); False selects CRR Art. 120 Table 3 (CQS 2 = 50%).

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
        table = INSTITUTION_RISK_WEIGHTS_B31_ECRA if is_basel_3_1 else INSTITUTION_RISK_WEIGHTS_CRR
        cqs_enum = _get_cqs_enum(cqs)
        return table.get(cqs_enum, table[CQS.UNRATED])

    if exposure_upper == "CORPORATE":
        cqs_enum = _get_cqs_enum(cqs)
        return CORPORATE_RISK_WEIGHTS.get(cqs_enum, CORPORATE_RISK_WEIGHTS[CQS.UNRATED])

    if exposure_upper == "RETAIL":
        return _RETAIL_RISK_WEIGHT_DEC

    if exposure_upper == "OTHER":
        return _OTHER_ITEMS_DEFAULT_RW_DEC

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
