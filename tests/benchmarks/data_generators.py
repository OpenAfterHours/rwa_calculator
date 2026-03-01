"""
Synthetic data generators for benchmark testing.

Generates large-scale test data with:
- Counterparty hierarchies with depth >= 2
- Facility/exposure hierarchies with depth >= 2
- At least half of entity types covered

Uses numpy vectorized operations for efficient generation at scale.

Entity Type Coverage (minimum 50%):
- Counterparty: corporate, retail, institution, sovereign, specialised_lending
  Covered: corporate (40%), retail (35%), institution (15%), sovereign (10%)

- Exposure Products: term_loan, rcf_drawing, mortgage, interbank_loan, etc.
  Covered: term_loan (40%), mortgage (25%), rcf_drawing (20%), interbank_loan (15%)

Hierarchy Requirements:
- Counterparty: org_mapping with depth >= 2 (parent -> child -> grandchild)
- Facility: facility_mapping with depth >= 2 (facility -> sub-facility -> loan)

Parquet Caching:
- Datasets are cached to parquet files by default for fast benchmark runs
- Use get_or_create_dataset() to load from cache or generate
- Set force_regenerate=True to regenerate cached datasets
- Default cache location: tests/benchmarks/data/
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

# Configure logger for benchmark data generation
logger = logging.getLogger("rwa_calc.benchmarks")

# Default directory for cached benchmark data
BENCHMARK_DATA_DIR = Path(__file__).parent / "data"

from rwa_calc.data.schemas import (  # noqa: E402
    COLLATERAL_SCHEMA,
    CONTINGENTS_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    ORG_MAPPING_SCHEMA,
    RATINGS_SCHEMA,
)


@dataclass(frozen=True)
class BenchmarkDataConfig:
    """Configuration for benchmark data generation."""

    n_counterparties: int
    hierarchy_depth: int = 3  # Minimum depth for hierarchies
    loans_per_counterparty: int = 3
    rated_percentage: float = 0.7
    seed: int = 42

    # Entity type distribution (must sum to 1.0)
    # Covers: corporate, individual (retail), institution, sovereign, specialised_lending
    corporate_pct: float = 0.35
    retail_pct: float = 0.30
    institution_pct: float = 0.15
    sovereign_pct: float = 0.10
    specialised_lending_pct: float = 0.10  # For slotting approach

    # Hierarchy configuration
    # Percentage of counterparties that have a parent (i.e., are children)
    hierarchy_percentage: float = 0.60
    # For those in hierarchies, distribution across depths
    depth_2_pct: float = 0.50  # Direct children of roots
    depth_3_pct: float = 0.35  # Grandchildren
    depth_4_pct: float = 0.15  # Great-grandchildren

    # Facility hierarchy configuration
    facility_hierarchy_pct: float = 0.40  # Loans under facilities
    sub_facility_pct: float = 0.25  # Facilities that are sub-facilities

    # Slotting category distribution for specialised lending
    slotting_strong_pct: float = 0.20
    slotting_good_pct: float = 0.35
    slotting_satisfactory_pct: float = 0.30
    slotting_weak_pct: float = 0.10
    slotting_default_pct: float = 0.05


def generate_counterparties(config: BenchmarkDataConfig) -> pl.LazyFrame:
    """
    Generate synthetic counterparty data with specified entity type distribution.

    Covers at least 50% of entity types with realistic distributions:
    - Corporate: 40% (large corps, SMEs)
    - Retail: 35% (individuals, SME retail)
    - Institution: 15% (banks, CCPs)
    - Sovereign: 10% (governments, PSEs)

    Args:
        config: Benchmark data configuration

    Returns:
        LazyFrame of counterparties matching COUNTERPARTY_SCHEMA
    """
    rng = np.random.default_rng(config.seed)
    n = config.n_counterparties

    # Assign entity types based on distribution (vectorized)
    # Includes specialised_lending for slotting approach testing
    entity_probs = [
        config.corporate_pct,
        config.retail_pct,
        config.institution_pct,
        config.sovereign_pct,
        config.specialised_lending_pct,
    ]
    entity_types_arr = np.array(
        ["corporate", "individual", "institution", "sovereign", "specialised_lending"]
    )
    entity_indices = rng.choice(5, size=n, p=entity_probs)
    entities = entity_types_arr[entity_indices]

    # Country codes - weighted towards UK (vectorized)
    countries = rng.choice(
        ["GB", "US", "DE", "FR", "JP", "XX"],
        size=n,
        p=[0.60, 0.15, 0.10, 0.08, 0.05, 0.02],
    )

    # Revenue - vectorized by entity type
    revenues = np.zeros(n)
    corp_mask = entities == "corporate"
    ind_mask = entities == "individual"
    inst_mask = entities == "institution"
    sov_mask = entities == "sovereign"
    sl_mask = entities == "specialised_lending"

    revenues[corp_mask] = rng.uniform(1_000_000, 500_000_000, size=corp_mask.sum())
    revenues[ind_mask] = rng.uniform(0, 2_000_000, size=ind_mask.sum())
    revenues[inst_mask] = rng.uniform(1_000_000_000, 100_000_000_000, size=inst_mask.sum())
    revenues[sov_mask] = rng.uniform(10_000_000_000, 1_000_000_000_000, size=sov_mask.sum())
    # Specialised lending - project finance SPVs typically have lower direct revenue
    revenues[sl_mask] = rng.uniform(10_000_000, 1_000_000_000, size=sl_mask.sum())

    # Total assets (typically 1.2-2x revenue)
    assets = revenues * rng.uniform(1.2, 2.0, size=n)

    # Default status - small percentage defaulted
    defaults = rng.random(n) < 0.02

    # Sector codes
    sector_codes = rng.choice(
        ["64.19", "64.20", "47.11", "25.11", "42.21", "70.22"],
        size=n,
    )

    # Entity flags - vectorized
    is_fi = inst_mask
    is_regulated = inst_mask | sov_mask
    pse_rand = rng.random(n) < 0.3
    is_pse = sov_mask & pse_rand
    ccp_rand = rng.random(n) < 0.05
    is_ccp = inst_mask & ccp_rand
    rgla_rand = rng.random(n) < 0.2
    is_rgla = sov_mask & rgla_rand

    # Build DataFrame using Polars native operations
    return (
        pl.DataFrame(
            {
                "counterparty_reference": pl.Series([f"CP_{i:08d}" for i in range(n)]),
                "counterparty_name": pl.Series([f"Entity_{i}" for i in range(n)]),
                "entity_type": pl.Series(entities),
                "country_code": pl.Series(countries),
                "annual_revenue": pl.Series(revenues),
                "total_assets": pl.Series(assets),
                "default_status": pl.Series(defaults),
                "sector_code": pl.Series(sector_codes),
                "is_financial_institution": pl.Series(is_fi),
                "is_regulated": pl.Series(is_regulated),
                "is_pse": pl.Series(is_pse),
                "is_mdb": pl.Series(np.zeros(n, dtype=bool)),
                "is_international_org": pl.Series(np.zeros(n, dtype=bool)),
                "is_central_counterparty": pl.Series(is_ccp),
                "is_regional_govt_local_auth": pl.Series(is_rgla),
                "is_managed_as_retail": pl.Series(np.zeros(n, dtype=bool)),
                "scra_grade": pl.Series([None] * n, dtype=pl.String),
                "is_investment_grade": pl.Series(np.zeros(n, dtype=bool)),
            }
        )
        .cast(COUNTERPARTY_SCHEMA)
        .lazy()
    )


def generate_org_mappings(
    counterparties: pl.LazyFrame,
    config: BenchmarkDataConfig,
) -> pl.LazyFrame:
    """
    Generate organisation hierarchy mappings with depth >= 2.

    Creates parent-child relationships to build multi-level hierarchies:
    - Root level: ~40% of counterparties (no parent)
    - Depth 2: ~30% (direct children of roots)
    - Depth 3: ~21% (grandchildren)
    - Depth 4+: ~9% (great-grandchildren)

    Args:
        counterparties: LazyFrame of counterparties
        config: Benchmark data configuration

    Returns:
        LazyFrame of org_mappings matching ORG_MAPPING_SCHEMA
    """
    rng = np.random.default_rng(config.seed + 1)

    # Get counterparty references as numpy array (fast)
    cp_refs = counterparties.select("counterparty_reference").collect()
    refs_arr = cp_refs["counterparty_reference"].to_numpy()
    n = len(refs_arr)

    # Determine which counterparties are in hierarchies
    n_in_hierarchy = int(n * config.hierarchy_percentage)

    # Shuffle to randomize which are in hierarchies
    hierarchy_indices = rng.permutation(n)[:n_in_hierarchy]

    # Split into depth levels
    n_depth_2 = int(n_in_hierarchy * config.depth_2_pct)
    n_depth_3 = int(n_in_hierarchy * config.depth_3_pct)

    # Counterparties not in hierarchy are potential roots
    hierarchy_set = set(hierarchy_indices)
    root_indices = np.array([i for i in range(n) if i not in hierarchy_set])

    # Depth level children
    depth_2_children = hierarchy_indices[:n_depth_2]
    depth_3_children = hierarchy_indices[n_depth_2 : n_depth_2 + n_depth_3]
    depth_4_children = hierarchy_indices[n_depth_2 + n_depth_3 :]

    # VECTORIZED: Generate all parent assignments at once
    # Depth 2: parents from roots
    depth_2_parents = (
        rng.choice(root_indices, size=len(depth_2_children))
        if len(root_indices) > 0
        else np.zeros(len(depth_2_children), dtype=int)
    )

    # Depth 3: parents from depth 2
    depth_3_parents = (
        rng.choice(depth_2_children, size=len(depth_3_children))
        if len(depth_2_children) > 0
        else np.zeros(len(depth_3_children), dtype=int)
    )

    # Depth 4: parents from depth 3
    depth_4_parents = (
        rng.choice(depth_3_children, size=len(depth_4_children))
        if len(depth_3_children) > 0
        else np.zeros(len(depth_4_children), dtype=int)
    )

    # Concatenate all mappings
    all_parents = np.concatenate([depth_2_parents, depth_3_parents, depth_4_parents])
    all_children = np.concatenate([depth_2_children, depth_3_children, depth_4_children])

    # Convert indices to references using numpy indexing (fast)
    parent_refs = refs_arr[all_parents]
    child_refs = refs_arr[all_children]

    return (
        pl.DataFrame(
            {
                "parent_counterparty_reference": parent_refs,
                "child_counterparty_reference": child_refs,
            }
        )
        .cast(ORG_MAPPING_SCHEMA)
        .lazy()
    )


def generate_facilities(
    counterparties: pl.LazyFrame,
    config: BenchmarkDataConfig,
) -> pl.LazyFrame:
    """
    Generate facility data for benchmark testing.

    Creates facilities linked to counterparties with:
    - Mix of revolving and term facilities
    - Various commitment types for CCF testing
    - Realistic limit ranges based on counterparty size

    Args:
        counterparties: LazyFrame of counterparties
        config: Benchmark data configuration

    Returns:
        LazyFrame of facilities matching FACILITY_SCHEMA
    """
    rng = np.random.default_rng(config.seed + 2)

    # Collect counterparty data as numpy arrays (fast)
    cp_data = counterparties.select(
        "counterparty_reference", "entity_type", "annual_revenue"
    ).collect()
    cp_refs_arr = cp_data["counterparty_reference"].to_numpy()
    revenues_arr = cp_data["annual_revenue"].to_numpy()
    n_cp = len(cp_refs_arr)

    # Number of facilities - approximately 1 facility per counterparty
    n_facilities = n_cp

    # VECTORIZED: Assign to counterparties
    cp_assignments = rng.choice(n_cp, size=n_facilities)

    # VECTORIZED: Product types for facilities
    product_types = rng.choice(
        ["RCF", "TERM_FACILITY", "MORTGAGE_FACILITY", "TRADE_FACILITY"],
        size=n_facilities,
        p=[0.35, 0.35, 0.20, 0.10],
    )

    # VECTORIZED: Book codes
    book_codes = rng.choice(
        ["CORP_LENDING", "RETAIL_LENDING", "FI_LENDING", "TRADE_FINANCE"],
        size=n_facilities,
        p=[0.45, 0.35, 0.15, 0.05],
    )

    # VECTORIZED: Generate maturity dates
    base_date = date(2026, 1, 1)
    maturity_days = rng.integers(365, 365 * 10, size=n_facilities)
    maturity_dates = [base_date + timedelta(days=int(d)) for d in maturity_days]

    # VECTORIZED: Currency
    currencies = rng.choice(
        ["GBP", "USD", "EUR"],
        size=n_facilities,
        p=[0.70, 0.20, 0.10],
    )

    # VECTORIZED: Limits based on counterparty revenue (1-10% of revenue)
    cp_revenues = revenues_arr[cp_assignments]
    limit_multiplier = rng.uniform(0.01, 0.10, size=n_facilities)
    limits = np.maximum(cp_revenues * limit_multiplier, 100_000)  # Min £100k

    # VECTORIZED: Committed flag (90% committed)
    committed = rng.random(n_facilities) > 0.1

    # VECTORIZED: Is revolving
    is_revolving = product_types == "RCF"

    # VECTORIZED: Seniority
    seniority = rng.choice(
        ["senior", "subordinated"],
        size=n_facilities,
        p=[0.90, 0.10],
    )

    # VECTORIZED: Risk type based on product type and commitment
    # RCF = MR (medium risk), uncommitted = LR (low risk), others mostly MR
    # 30% are uncommitted (LR), rest are committed
    is_uncommitted = rng.random(n_facilities) < 0.30
    risk_types = np.where(
        is_uncommitted,
        "LR",  # Low risk = unconditionally cancellable (0% CCF)
        np.where(
            product_types == "RCF",
            "MR",  # Revolving credit = medium risk (50% SA, 75% F-IRB)
            rng.choice(["MR", "MLR"], size=n_facilities, p=[0.70, 0.30]),
        ),
    )

    # Build DataFrame using numpy arrays
    return (
        pl.DataFrame(
            {
                "facility_reference": [f"FAC_{i:08d}" for i in range(n_facilities)],
                "product_type": product_types,
                "book_code": book_codes,
                "counterparty_reference": cp_refs_arr[cp_assignments],
                "value_date": [base_date] * n_facilities,
                "maturity_date": maturity_dates,
                "currency": currencies,
                "limit": limits,
                "committed": committed,
                "lgd": np.full(n_facilities, 0.45),
                "beel": np.zeros(n_facilities),
                "is_revolving": is_revolving,
                "seniority": seniority,
                "risk_type": risk_types,
                "ccf_modelled": np.full(n_facilities, None),  # No modelled CCF for benchmarks
                "is_short_term_trade_lc": np.full(n_facilities, None),  # N/A for facilities
                "is_buy_to_let": np.full(n_facilities, None),  # BTL flag for SME supporting factor
            }
        )
        .cast(FACILITY_SCHEMA)
        .lazy()
    )


def generate_loans(
    counterparties: pl.LazyFrame,
    config: BenchmarkDataConfig,
) -> pl.LazyFrame:
    """
    Generate loan data for benchmark testing.

    Creates loans with:
    - Product type distribution: term_loan (40%), mortgage (25%), rcf_drawing (20%), interbank (15%)
    - Realistic drawn amounts based on counterparty size
    - Mix of seniorities

    Args:
        counterparties: LazyFrame of counterparties
        config: Benchmark data configuration

    Returns:
        LazyFrame of loans matching LOAN_SCHEMA
    """
    rng = np.random.default_rng(config.seed + 3)

    # Collect counterparty data as numpy arrays (fast)
    cp_data = counterparties.select(
        "counterparty_reference", "entity_type", "annual_revenue"
    ).collect()
    cp_refs_arr = cp_data["counterparty_reference"].to_numpy()
    entity_types_arr = cp_data["entity_type"].to_numpy()
    revenues_arr = cp_data["annual_revenue"].to_numpy()
    n_cp = len(cp_refs_arr)

    # Number of loans
    n_loans = n_cp * config.loans_per_counterparty

    # Assign to counterparties (vectorized)
    cp_assignments = np.tile(np.arange(n_cp), config.loans_per_counterparty)
    rng.shuffle(cp_assignments)

    # Get entity types for each loan
    loan_entities = entity_types_arr[cp_assignments]

    # VECTORIZED: Product types based on entity type
    product_types = np.empty(n_loans, dtype=object)
    product_types[:] = "TERM_LOAN"  # Default

    ind_mask = loan_entities == "individual"
    inst_mask = loan_entities == "institution"
    sov_mask = loan_entities == "sovereign"
    corp_mask = loan_entities == "corporate"
    sl_mask = loan_entities == "specialised_lending"

    n_ind = ind_mask.sum()
    if n_ind > 0:
        product_types[ind_mask] = rng.choice(
            ["PERSONAL_LOAN", "RESIDENTIAL_MORTGAGE", "CREDIT_CARD"],
            size=n_ind,
            p=[0.30, 0.50, 0.20],
        )

    n_inst = inst_mask.sum()
    if n_inst > 0:
        product_types[inst_mask] = rng.choice(
            ["INTERBANK_LOAN", "TERM_LOAN"], size=n_inst, p=[0.70, 0.30]
        )

    product_types[sov_mask] = "SOVEREIGN_LOAN"

    n_corp = corp_mask.sum()
    if n_corp > 0:
        product_types[corp_mask] = rng.choice(
            ["TERM_LOAN", "RCF_DRAWING", "TRADE_LOAN"], size=n_corp, p=[0.50, 0.35, 0.15]
        )

    # Specialised lending - slotting product types
    n_sl = sl_mask.sum()
    if n_sl > 0:
        product_types[sl_mask] = rng.choice(
            ["PROJECT_FINANCE", "OBJECT_FINANCE", "COMMODITIES_FINANCE", "IPRE", "HVCRE"],
            size=n_sl,
            p=[0.30, 0.20, 0.15, 0.25, 0.10],
        )

    # VECTORIZED: Book codes using numpy where/select
    book_codes = np.select(
        [
            product_types == "TERM_LOAN",
            product_types == "RCF_DRAWING",
            product_types == "TRADE_LOAN",
            product_types == "INTERBANK_LOAN",
            product_types == "SOVEREIGN_LOAN",
            product_types == "PERSONAL_LOAN",
            product_types == "RESIDENTIAL_MORTGAGE",
            product_types == "CREDIT_CARD",
            product_types == "PROJECT_FINANCE",
            product_types == "OBJECT_FINANCE",
            product_types == "COMMODITIES_FINANCE",
            product_types == "IPRE",
            product_types == "HVCRE",
        ],
        [
            "CORP_LENDING",
            "CORP_LENDING",
            "TRADE_FINANCE",
            "FI_LENDING",
            "SOVEREIGN",
            "RETAIL_UNSECURED",
            "RETAIL_MORTGAGES",
            "RETAIL_CARDS",
            "SPECIALISED_LENDING",
            "SPECIALISED_LENDING",
            "SPECIALISED_LENDING",
            "SPECIALISED_LENDING",
            "SPECIALISED_LENDING",
        ],
        default="CORP_LENDING",
    )

    # Generate slotting categories for specialised lending loans
    # These are embedded in the loan reference for classifier to derive
    slotting_categories = np.empty(n_loans, dtype=object)
    slotting_categories[:] = ""  # Default empty for non-SL loans
    if n_sl > 0:
        sl_cat_probs = [
            config.slotting_strong_pct,
            config.slotting_good_pct,
            config.slotting_satisfactory_pct,
            config.slotting_weak_pct,
            config.slotting_default_pct,
        ]
        sl_categories = rng.choice(
            ["STRONG", "GOOD", "SATISFACTORY", "WEAK", "DEFAULT"], size=n_sl, p=sl_cat_probs
        )
        slotting_categories[sl_mask] = sl_categories

    # VECTORIZED: Dates using polars date_range
    base_date = date(2026, 1, 1)
    maturity_days = rng.integers(365, 365 * 7, size=n_loans)

    # Currency
    currencies = rng.choice(["GBP", "USD", "EUR"], size=n_loans, p=[0.70, 0.20, 0.10])

    # VECTORIZED: Drawn amounts
    cp_revenues = revenues_arr[cp_assignments]
    drawn_multiplier = rng.uniform(0.001, 0.05, size=n_loans)
    drawn_amounts = np.maximum(cp_revenues * drawn_multiplier, 10_000)

    # VECTORIZED: LGD
    lgd = np.full(n_loans, 0.45)
    lgd[product_types == "RESIDENTIAL_MORTGAGE"] = 0.10
    lgd[product_types == "CREDIT_CARD"] = 0.85

    # Seniority
    seniority = rng.choice(["senior", "subordinated"], size=n_loans, p=[0.92, 0.08])

    # Generate loan references - include slotting category for SL loans
    # Format: SL_STRONG_00000001 for specialised lending, LOAN_00000001 for others
    loan_refs = []
    for i in range(n_loans):
        if sl_mask[i] and slotting_categories[i]:
            loan_refs.append(f"SL_{slotting_categories[i]}_{i:08d}")
        else:
            loan_refs.append(f"LOAN_{i:08d}")

    # Build DataFrame - use polars for date arithmetic
    df = pl.DataFrame(
        {
            "loan_reference": loan_refs,
            "product_type": product_types,
            "book_code": book_codes,
            "counterparty_reference": cp_refs_arr[cp_assignments],
            "value_date": pl.Series([base_date] * n_loans),
            "maturity_date": pl.Series([base_date] * n_loans).dt.offset_by(
                pl.Series([f"{d}d" for d in maturity_days])
            )
            if False
            else [base_date + timedelta(days=int(d)) for d in maturity_days],
            "currency": currencies,
            "drawn_amount": drawn_amounts,
            "interest": np.zeros(n_loans),  # Accrued interest
            "lgd": lgd,
            "beel": np.zeros(n_loans),
            "seniority": seniority,
            "is_buy_to_let": np.full(n_loans, None),  # BTL flag for SME supporting factor
        }
    ).cast(LOAN_SCHEMA)

    return df.lazy()


def generate_facility_mappings(
    facilities: pl.LazyFrame,
    loans: pl.LazyFrame,
    config: BenchmarkDataConfig,
) -> pl.LazyFrame:
    """
    Generate facility-to-loan/sub-facility mappings with hierarchy depth >= 2.

    Creates multi-level facility hierarchies:
    - Level 1: Root facilities
    - Level 2: Sub-facilities (children of root facilities)
    - Level 3: Loans (children of sub-facilities or root facilities)

    Args:
        facilities: LazyFrame of facilities
        loans: LazyFrame of loans
        config: Benchmark data configuration

    Returns:
        LazyFrame of facility_mappings matching FACILITY_MAPPING_SCHEMA
    """
    rng = np.random.default_rng(config.seed + 4)

    # Collect references as numpy arrays (fast)
    fac_data = facilities.select("facility_reference").collect()
    fac_refs_arr = fac_data["facility_reference"].to_numpy()
    n_fac = len(fac_refs_arr)

    loan_data = loans.select("loan_reference").collect()
    loan_refs_arr = loan_data["loan_reference"].to_numpy()
    n_loans = len(loan_refs_arr)

    # Determine which facilities are sub-facilities (have parents)
    n_sub_facilities = int(n_fac * config.sub_facility_pct)
    sub_fac_indices = rng.permutation(n_fac)[:n_sub_facilities]
    sub_fac_set = set(sub_fac_indices)
    root_fac_indices = np.array([i for i in range(n_fac) if i not in sub_fac_set])

    # VECTORIZED: Create facility -> sub-facility mappings (depth 2)
    if len(root_fac_indices) > 0 and len(sub_fac_indices) > 0:
        fac_parent_indices = rng.choice(root_fac_indices, size=len(sub_fac_indices))
        fac_parents = fac_refs_arr[fac_parent_indices]
        fac_children = fac_refs_arr[sub_fac_indices]
        fac_types = np.full(len(sub_fac_indices), "facility", dtype=object)
    else:
        fac_parents = np.array([], dtype=object)
        fac_children = np.array([], dtype=object)
        fac_types = np.array([], dtype=object)

    # Determine which loans are under facilities
    n_loans_with_facility = int(n_loans * config.facility_hierarchy_pct)
    loan_indices_with_fac = rng.permutation(n_loans)[:n_loans_with_facility]

    # Split loans between root facilities and sub-facilities
    n_under_sub = int(n_loans_with_facility * 0.4)  # 40% under sub-facilities
    n_under_root = n_loans_with_facility - n_under_sub

    # VECTORIZED: Loans under sub-facilities (depth 3 from root)
    if len(sub_fac_indices) > 0 and n_under_sub > 0:
        sub_loan_parent_indices = rng.choice(sub_fac_indices, size=n_under_sub)
        sub_loan_parents = fac_refs_arr[sub_loan_parent_indices]
        sub_loan_children = loan_refs_arr[loan_indices_with_fac[:n_under_sub]]
        sub_loan_types = np.full(n_under_sub, "loan", dtype=object)
    else:
        sub_loan_parents = np.array([], dtype=object)
        sub_loan_children = np.array([], dtype=object)
        sub_loan_types = np.array([], dtype=object)

    # VECTORIZED: Loans under root facilities (depth 2)
    if len(root_fac_indices) > 0 and n_under_root > 0:
        root_loan_parent_indices = rng.choice(root_fac_indices, size=n_under_root)
        root_loan_parents = fac_refs_arr[root_loan_parent_indices]
        root_loan_children = loan_refs_arr[loan_indices_with_fac[n_under_sub:]]
        root_loan_types = np.full(n_under_root, "loan", dtype=object)
    else:
        root_loan_parents = np.array([], dtype=object)
        root_loan_children = np.array([], dtype=object)
        root_loan_types = np.array([], dtype=object)

    # Concatenate all mappings
    all_parents = np.concatenate([fac_parents, sub_loan_parents, root_loan_parents])
    all_children = np.concatenate([fac_children, sub_loan_children, root_loan_children])
    all_types = np.concatenate([fac_types, sub_loan_types, root_loan_types])

    return (
        pl.DataFrame(
            {
                "parent_facility_reference": all_parents,
                "child_reference": all_children,
                "child_type": all_types,
            }
        )
        .cast(FACILITY_MAPPING_SCHEMA)
        .lazy()
    )


def generate_ratings(
    counterparties: pl.LazyFrame,
    config: BenchmarkDataConfig,
) -> pl.LazyFrame:
    """
    Generate rating data for counterparties.

    Creates mix of internal and external ratings with:
    - ~70% of counterparties rated (configurable)
    - Mix of rating agencies (S&P, Moody's, Fitch, internal)
    - Realistic CQS distribution

    Args:
        counterparties: LazyFrame of counterparties
        config: Benchmark data configuration

    Returns:
        LazyFrame of ratings matching RATINGS_SCHEMA
    """
    rng = np.random.default_rng(config.seed + 5)

    # Collect counterparty data as numpy arrays (fast)
    cp_data = counterparties.select("counterparty_reference", "entity_type").collect()
    cp_refs_arr = cp_data["counterparty_reference"].to_numpy()
    entity_types_arr = cp_data["entity_type"].to_numpy()
    n_cp = len(cp_refs_arr)

    # Determine which counterparties are rated
    n_rated = int(n_cp * config.rated_percentage)
    rated_indices = rng.permutation(n_cp)[:n_rated]

    # Get entity types for rated counterparties
    rated_entities = entity_types_arr[rated_indices]
    rated_refs = cp_refs_arr[rated_indices]

    # VECTORIZED: Rating type - 60% external
    is_external = rng.random(n_rated) < 0.6
    is_internal = ~is_external

    # VECTORIZED: Initialize arrays
    agencies = np.empty(n_rated, dtype=object)
    cqs_arr = np.zeros(n_rated, dtype=int)
    pds_arr = np.zeros(n_rated, dtype=float)
    values = np.empty(n_rated, dtype=object)
    solicited = np.zeros(n_rated, dtype=bool)

    # VECTORIZED: External ratings
    ext_mask = is_external
    n_ext = ext_mask.sum()
    if n_ext > 0:
        # Agencies for external
        agencies[ext_mask] = rng.choice(["S&P", "Moodys", "Fitch"], size=n_ext)
        solicited[ext_mask] = True

        # CQS by entity type for external ratings
        ext_entities = rated_entities[ext_mask]

        # Sovereign CQS
        sov_ext_mask = ext_entities == "sovereign"
        n_sov = sov_ext_mask.sum()
        if n_sov > 0:
            sov_cqs = rng.choice(
                [1, 2, 3, 4, 5, 6], size=n_sov, p=[0.30, 0.25, 0.20, 0.15, 0.07, 0.03]
            )
            ext_indices = np.where(ext_mask)[0]
            cqs_arr[ext_indices[sov_ext_mask]] = sov_cqs

        # Institution CQS
        inst_ext_mask = ext_entities == "institution"
        n_inst = inst_ext_mask.sum()
        if n_inst > 0:
            inst_cqs = rng.choice(
                [1, 2, 3, 4, 5, 6], size=n_inst, p=[0.15, 0.35, 0.30, 0.12, 0.06, 0.02]
            )
            ext_indices = np.where(ext_mask)[0]
            cqs_arr[ext_indices[inst_ext_mask]] = inst_cqs

        # Other (corporate/individual) CQS
        other_ext_mask = ~sov_ext_mask & ~inst_ext_mask
        n_other = other_ext_mask.sum()
        if n_other > 0:
            other_cqs = rng.choice(
                [1, 2, 3, 4, 5, 6], size=n_other, p=[0.05, 0.20, 0.35, 0.25, 0.10, 0.05]
            )
            ext_indices = np.where(ext_mask)[0]
            cqs_arr[ext_indices[other_ext_mask]] = other_cqs

        # Map CQS to rating values and PDs for external
        sp_ratings = np.array(["", "AAA", "AA", "A", "BBB", "BB", "B"])
        pd_values = np.array([0.0, 0.0003, 0.001, 0.005, 0.02, 0.05, 0.15])
        values[ext_mask] = sp_ratings[cqs_arr[ext_mask]]
        pds_arr[ext_mask] = pd_values[cqs_arr[ext_mask]]

    # VECTORIZED: Internal ratings
    int_mask = is_internal
    n_int = int_mask.sum()
    if n_int > 0:
        agencies[int_mask] = "internal"
        solicited[int_mask] = False

        # Generate PDs uniformly
        internal_pds = rng.uniform(0.0003, 0.20, size=n_int)
        pds_arr[int_mask] = internal_pds

        # Map PD to CQS using vectorized digitize
        pd_bins = [0.001, 0.005, 0.02, 0.05, 0.15]
        internal_cqs = np.digitize(internal_pds, pd_bins) + 1  # CQS 1-6
        cqs_arr[int_mask] = internal_cqs

        # Generate rating values
        int_indices = np.where(int_mask)[0]
        for cqs_val in range(1, 7):
            cqs_mask = cqs_arr[int_mask] == cqs_val
            values[int_indices[cqs_mask]] = f"INT_{cqs_val}"

    # VECTORIZED: Rating dates - within last year
    base_date = date(2026, 1, 1)
    days_ago = rng.integers(0, 365, size=n_rated)
    rating_dates = [base_date - timedelta(days=int(d)) for d in days_ago]

    # Build DataFrame
    return (
        pl.DataFrame(
            {
                "rating_reference": [f"RAT_{i:08d}" for i in range(n_rated)],
                "counterparty_reference": rated_refs,
                "rating_type": np.where(is_external, "external", "internal"),
                "rating_agency": agencies,
                "rating_value": values,
                "cqs": cqs_arr,
                "pd": pds_arr,
                "rating_date": rating_dates,
                "is_solicited": solicited,
            }
        )
        .cast(RATINGS_SCHEMA)
        .lazy()
    )


def generate_contingents(
    counterparties: pl.LazyFrame,
    config: BenchmarkDataConfig,
) -> pl.LazyFrame:
    """
    Generate contingent (off-balance sheet) exposures.

    Creates mix of:
    - Letters of credit
    - Guarantees
    - Undrawn commitments

    Args:
        counterparties: LazyFrame of counterparties
        config: Benchmark data configuration

    Returns:
        LazyFrame of contingents matching CONTINGENTS_SCHEMA
    """
    rng = np.random.default_rng(config.seed + 6)

    # Collect counterparty data as numpy arrays (fast)
    cp_data = counterparties.select("counterparty_reference", "annual_revenue").collect()
    cp_refs_arr = cp_data["counterparty_reference"].to_numpy()
    revenues_arr = cp_data["annual_revenue"].to_numpy()
    n_cp = len(cp_refs_arr)

    # ~20% of counterparties have contingents
    n_contingents = int(n_cp * 0.20)

    # VECTORIZED: Assign to counterparties
    cp_assignments = rng.choice(n_cp, size=n_contingents)

    # VECTORIZED: Product types
    product_types = rng.choice(
        ["TRADE_LC", "FINANCIAL_GUARANTEE", "UNDRAWN_COMMITMENT"],
        size=n_contingents,
        p=[0.30, 0.30, 0.40],
    )

    # VECTORIZED: Maturity dates
    base_date = date(2026, 1, 1)
    maturity_days = rng.integers(90, 365 * 3, size=n_contingents)
    maturity_dates = [base_date + timedelta(days=int(d)) for d in maturity_days]

    # VECTORIZED: Currencies
    currencies = rng.choice(["GBP", "USD", "EUR"], size=n_contingents, p=[0.70, 0.20, 0.10])

    # VECTORIZED: Nominal amounts based on counterparty revenue
    cp_revenues = revenues_arr[cp_assignments]
    nominal_multiplier = rng.uniform(0.005, 0.02, size=n_contingents)
    nominal_amounts = np.maximum(cp_revenues * nominal_multiplier, 50_000)

    # VECTORIZED: Risk types based on product type
    # MLR for trade LCs, FR for guarantees, MR for commitments
    risk_types = np.select(
        [
            product_types == "TRADE_LC",
            product_types == "FINANCIAL_GUARANTEE",
            product_types == "UNDRAWN_COMMITMENT",
        ],
        [
            "MLR",
            "FR",
            "MR",
        ],  # Medium-low risk for trade, full risk for guarantees, medium for commitments
        default="MR",
    )

    # VECTORIZED: Short-term trade LC flag (True for LCs)
    is_short_term_trade_lc = product_types == "TRADE_LC"

    # Build DataFrame using numpy arrays
    return (
        pl.DataFrame(
            {
                "contingent_reference": [f"CONT_{i:08d}" for i in range(n_contingents)],
                "product_type": product_types,
                "book_code": np.full(n_contingents, "CONTINGENT"),
                "counterparty_reference": cp_refs_arr[cp_assignments],
                "value_date": [base_date] * n_contingents,
                "maturity_date": maturity_dates,
                "currency": currencies,
                "nominal_amount": nominal_amounts,
                "lgd": np.full(n_contingents, 0.45),
                "beel": np.zeros(n_contingents),
                "seniority": np.full(n_contingents, "senior"),
                "risk_type": risk_types,
                "ccf_modelled": np.full(n_contingents, None),  # No modelled CCF for benchmarks
                "is_short_term_trade_lc": is_short_term_trade_lc,  # True for LCs
                "bs_type": np.full(n_contingents, "OFB"),  # Off-balance-sheet by default
            }
        )
        .cast(CONTINGENTS_SCHEMA)
        .lazy()
    )


def generate_collateral(
    counterparties: pl.LazyFrame,
    loans: pl.LazyFrame,
    config: BenchmarkDataConfig,
) -> pl.LazyFrame:
    """
    Generate collateral data for benchmark testing.

    Creates mix of collateral types:
    - Cash (20%)
    - Real estate (40%)
    - Bonds (25%)
    - Equity (15%)

    Args:
        counterparties: LazyFrame of counterparties
        loans: LazyFrame of loans
        config: Benchmark data configuration

    Returns:
        LazyFrame of collateral matching COLLATERAL_SCHEMA
    """
    rng = np.random.default_rng(config.seed + 7)

    # Collect loan data as numpy arrays (fast)
    loan_data = loans.select("loan_reference", "drawn_amount").collect()
    loan_refs_arr = loan_data["loan_reference"].to_numpy()
    loan_amounts_arr = loan_data["drawn_amount"].to_numpy()
    n_loans = len(loan_refs_arr)

    # ~30% of loans have collateral
    n_collateral = int(n_loans * 0.30)
    loan_assignments = rng.permutation(n_loans)[:n_collateral]

    # VECTORIZED: Collateral types
    coll_types = rng.choice(
        ["cash", "real_estate", "bond", "equity"],
        size=n_collateral,
        p=[0.20, 0.40, 0.25, 0.15],
    )

    # VECTORIZED: Currencies
    currencies = rng.choice(["GBP", "USD", "EUR"], size=n_collateral, p=[0.75, 0.15, 0.10])

    # VECTORIZED: Maturity dates
    base_date = date(2026, 1, 1)
    maturity_days = rng.integers(365, 365 * 10, size=n_collateral)
    maturity_dates = [base_date + timedelta(days=int(d)) for d in maturity_days]

    # VECTORIZED: Market values (50-150% of loan amount)
    assigned_loan_amounts = loan_amounts_arr[loan_assignments]
    coverage = rng.uniform(0.50, 1.50, size=n_collateral)
    market_values = assigned_loan_amounts * coverage
    nominal_values = market_values * rng.uniform(0.95, 1.05, size=n_collateral)

    # VECTORIZED: Beneficiary references
    beneficiary_refs = loan_refs_arr[loan_assignments]

    # VECTORIZED: Create masks for collateral types
    bond_mask = coll_types == "bond"
    equity_mask = coll_types == "equity"
    real_estate_mask = coll_types == "real_estate"
    cash_mask = coll_types == "cash"

    # VECTORIZED: Issuer CQS (only for bonds) - use NaN for missing, convert later
    issuer_cqs = np.full(n_collateral, np.nan, dtype=float)
    n_bonds = bond_mask.sum()
    if n_bonds > 0:
        bond_cqs = rng.choice([1, 2, 3, 4], size=n_bonds, p=[0.30, 0.40, 0.20, 0.10]).astype(float)
        issuer_cqs[bond_mask] = bond_cqs

    # VECTORIZED: Issuer types - use empty string for missing
    issuer_types = np.full(n_collateral, "", dtype="<U20")
    if n_bonds > 0:
        issuer_types[bond_mask] = rng.choice(
            ["sovereign", "corporate"], size=n_bonds, p=[0.60, 0.40]
        )
    issuer_types[equity_mask] = "corporate"

    # VECTORIZED: Residual maturities (only for bonds)
    residual_maturities = np.full(n_collateral, np.nan, dtype=float)
    if n_bonds > 0:
        residual_maturities[bond_mask] = rng.uniform(1, 10, size=n_bonds)

    # VECTORIZED: Eligibility flags
    is_eligible_fc = cash_mask | bond_mask | equity_mask
    is_eligible_irb = np.ones(n_collateral, dtype=bool)

    # VECTORIZED: Valuation dates
    val_days_ago = rng.integers(0, 90, size=n_collateral)
    valuation_dates = [base_date - timedelta(days=int(d)) for d in val_days_ago]

    # VECTORIZED: Valuation types
    valuation_types = np.where(real_estate_mask, "independent", "market")

    # VECTORIZED: Property types (only for real estate)
    property_types = np.full(n_collateral, "", dtype="<U20")
    n_re = real_estate_mask.sum()
    if n_re > 0:
        re_prop_types = np.where(rng.random(n_re) < 0.6, "residential", "commercial")
        property_types[real_estate_mask] = re_prop_types

    # VECTORIZED: Property LTVs (only for real estate)
    property_ltvs = np.full(n_collateral, np.nan, dtype=float)
    if n_re > 0:
        property_ltvs[real_estate_mask] = rng.uniform(0.3, 0.9, size=n_re)

    # VECTORIZED: Real estate flags
    is_income_producing = np.zeros(n_collateral, dtype=bool)
    is_adc = np.zeros(n_collateral, dtype=bool)
    is_presold = np.zeros(n_collateral, dtype=bool)
    if n_re > 0:
        is_income_producing[real_estate_mask] = rng.random(n_re) < 0.3
        is_adc[real_estate_mask] = rng.random(n_re) < 0.1
        # Presold only applies to ADC
        adc_indices = np.where(is_adc)[0]
        if len(adc_indices) > 0:
            is_presold[adc_indices] = rng.random(len(adc_indices)) < 0.5

    # Build DataFrame with proper null handling for nullable columns
    df = pl.DataFrame(
        {
            "collateral_reference": [f"COLL_{i:08d}" for i in range(n_collateral)],
            "collateral_type": coll_types,
            "currency": currencies,
            "maturity_date": maturity_dates,
            "market_value": market_values,
            "nominal_value": nominal_values,
            "pledge_percentage": np.full(n_collateral, None),  # Not used in benchmarks
            "beneficiary_type": np.full(n_collateral, "loan"),
            "beneficiary_reference": beneficiary_refs,
            "issuer_cqs": issuer_cqs,
            "issuer_type": issuer_types,
            "residual_maturity_years": residual_maturities,
            "is_eligible_financial_collateral": is_eligible_fc,
            "is_eligible_irb_collateral": is_eligible_irb,
            "valuation_date": valuation_dates,
            "valuation_type": valuation_types,
            "property_type": property_types,
            "property_ltv": property_ltvs,
            "is_income_producing": is_income_producing,
            "is_adc": is_adc,
            "is_presold": is_presold,
        }
    )

    # Replace NaN/empty with proper null values before casting
    return (
        df.with_columns(
            [
                # issuer_cqs: NaN -> null, then cast to Int8
                pl.when(pl.col("issuer_cqs").is_nan())
                .then(None)
                .otherwise(pl.col("issuer_cqs"))
                .cast(pl.Int8)
                .alias("issuer_cqs"),
                # issuer_type: empty string -> null
                pl.when(pl.col("issuer_type") == "")
                .then(None)
                .otherwise(pl.col("issuer_type"))
                .alias("issuer_type"),
                # residual_maturity_years: NaN -> null
                pl.when(pl.col("residual_maturity_years").is_nan())
                .then(None)
                .otherwise(pl.col("residual_maturity_years"))
                .alias("residual_maturity_years"),
                # property_type: empty string -> null
                pl.when(pl.col("property_type") == "")
                .then(None)
                .otherwise(pl.col("property_type"))
                .alias("property_type"),
                # property_ltv: NaN -> null
                pl.when(pl.col("property_ltv").is_nan())
                .then(None)
                .otherwise(pl.col("property_ltv"))
                .alias("property_ltv"),
            ]
        )
        .cast(COLLATERAL_SCHEMA)
        .lazy()
    )


def generate_benchmark_dataset(
    n_counterparties: int,
    hierarchy_depth: int = 3,
    seed: int = 42,
) -> dict[str, pl.LazyFrame]:
    """
    Generate a complete benchmark dataset.

    Creates all required data for RWA calculation with:
    - Counterparty hierarchies with specified depth
    - Facility/exposure hierarchies with specified depth
    - At least 50% entity type coverage
    - Realistic data distributions

    Args:
        n_counterparties: Number of counterparties to generate
        hierarchy_depth: Minimum hierarchy depth (default 3)
        seed: Random seed for reproducibility

    Returns:
        Dictionary of LazyFrames keyed by data type
    """
    config = BenchmarkDataConfig(
        n_counterparties=n_counterparties,
        hierarchy_depth=hierarchy_depth,
        seed=seed,
    )

    # Generate data in dependency order
    counterparties = generate_counterparties(config)
    org_mappings = generate_org_mappings(counterparties, config)
    facilities = generate_facilities(counterparties, config)
    loans = generate_loans(counterparties, config)
    facility_mappings = generate_facility_mappings(facilities, loans, config)
    ratings = generate_ratings(counterparties, config)
    contingents = generate_contingents(counterparties, config)
    collateral = generate_collateral(counterparties, loans, config)

    return {
        "counterparties": counterparties,
        "org_mappings": org_mappings,
        "facilities": facilities,
        "loans": loans,
        "facility_mappings": facility_mappings,
        "ratings": ratings,
        "contingents": contingents,
        "collateral": collateral,
    }


def get_dataset_statistics(dataset: dict[str, pl.LazyFrame]) -> dict:
    """
    Calculate statistics for a generated dataset.

    Args:
        dataset: Dictionary of LazyFrames from generate_benchmark_dataset

    Returns:
        Dictionary of statistics
    """
    stats = {}

    for name, lf in dataset.items():
        df = lf.collect()
        stats[name] = {
            "count": len(df),
            "columns": df.columns,
        }

    # Entity type distribution
    cp_df = dataset["counterparties"].collect()
    entity_counts = cp_df.group_by("entity_type").len().sort("entity_type")
    stats["entity_distribution"] = dict(
        zip(
            entity_counts["entity_type"].to_list(),
            entity_counts["len"].to_list(),
            strict=True,
        )
    )

    # Hierarchy depth analysis
    org_df = dataset["org_mappings"].collect()
    if len(org_df) > 0:
        # Count children per parent
        children_per_parent = org_df.group_by("parent_counterparty_reference").len()
        stats["org_hierarchy"] = {
            "total_mappings": len(org_df),
            "unique_parents": children_per_parent.height,
            "avg_children_per_parent": children_per_parent["len"].mean(),
        }

    fac_df = dataset["facility_mappings"].collect()
    if len(fac_df) > 0:
        child_type_counts = fac_df.group_by("child_type").len()
        stats["facility_hierarchy"] = {
            "total_mappings": len(fac_df),
            "by_child_type": dict(
                zip(
                    child_type_counts["child_type"].to_list(),
                    child_type_counts["len"].to_list(),
                    strict=True,
                )
            ),
        }

    return stats


# =============================================================================
# PARQUET CACHING FUNCTIONS
# =============================================================================


def get_dataset_path(scale: str, data_dir: Path | None = None) -> Path:
    """
    Get the path for a cached dataset.

    Args:
        scale: Scale identifier (e.g., "10k", "100k", "1m", "10m")
        data_dir: Optional custom data directory

    Returns:
        Path to the dataset directory
    """
    base_dir = data_dir or BENCHMARK_DATA_DIR
    return base_dir / f"benchmark_{scale}"


def save_benchmark_dataset(
    dataset: dict[str, pl.LazyFrame],
    scale: str,
    data_dir: Path | None = None,
) -> Path:
    """
    Save a benchmark dataset to parquet files.

    Args:
        dataset: Dictionary of LazyFrames from generate_benchmark_dataset
        scale: Scale identifier (e.g., "10k", "100k", "1m", "10m")
        data_dir: Optional custom data directory

    Returns:
        Path to the saved dataset directory
    """
    dataset_path = get_dataset_path(scale, data_dir)
    dataset_path.mkdir(parents=True, exist_ok=True)

    for name, lf in dataset.items():
        file_path = dataset_path / f"{name}.parquet"
        lf.collect().write_parquet(file_path)
        logger.debug(f"Saved {name} to {file_path}")

    logger.info(f"Benchmark dataset '{scale}' saved to {dataset_path}")
    return dataset_path


def load_benchmark_dataset(
    scale: str,
    data_dir: Path | None = None,
) -> dict[str, pl.LazyFrame] | None:
    """
    Load a benchmark dataset from parquet files.

    Args:
        scale: Scale identifier (e.g., "10k", "100k", "1m", "10m")
        data_dir: Optional custom data directory

    Returns:
        Dictionary of LazyFrames, or None if dataset doesn't exist
    """
    dataset_path = get_dataset_path(scale, data_dir)

    if not dataset_path.exists():
        logger.debug(f"Cache directory {dataset_path} does not exist")
        return None

    expected_files = [
        "counterparties",
        "org_mappings",
        "facilities",
        "loans",
        "facility_mappings",
        "ratings",
        "contingents",
        "collateral",
    ]

    # Check all files exist
    for name in expected_files:
        file_path = dataset_path / f"{name}.parquet"
        if not file_path.exists():
            logger.debug(f"Missing {file_path}, will regenerate dataset")
            return None

    # Load all files as LazyFrames
    dataset = {}
    for name in expected_files:
        file_path = dataset_path / f"{name}.parquet"
        dataset[name] = pl.scan_parquet(file_path)

    logger.debug(f"Loaded benchmark dataset '{scale}' from cache")
    return dataset


def get_or_create_dataset(
    scale: str,
    n_counterparties: int,
    hierarchy_depth: int = 3,
    seed: int = 42,
    data_dir: Path | None = None,
    force_regenerate: bool = False,
) -> dict[str, pl.LazyFrame]:
    """
    Load dataset from cache or generate if not available.

    This is the primary function for benchmark tests. By default, it loads
    cached datasets for fast test runs. Use force_regenerate=True to update
    the cached datasets when the data generation logic changes.

    Args:
        scale: Scale identifier (e.g., "10k", "100k", "1m", "10m")
        n_counterparties: Number of counterparties (used if generating)
        hierarchy_depth: Hierarchy depth (used if generating)
        seed: Random seed (used if generating)
        data_dir: Optional custom data directory
        force_regenerate: If True, regenerate even if cache exists

    Returns:
        Dictionary of LazyFrames
    """
    if not force_regenerate:
        dataset = load_benchmark_dataset(scale, data_dir)
        if dataset is not None:
            logger.debug(f"Using cached '{scale}' dataset")
            return dataset

    logger.info(f"Generating '{scale}' dataset ({n_counterparties:,} counterparties)...")
    dataset = generate_benchmark_dataset(
        n_counterparties=n_counterparties,
        hierarchy_depth=hierarchy_depth,
        seed=seed,
    )

    logger.info(f"Caching '{scale}' dataset...")
    save_benchmark_dataset(dataset, scale, data_dir)

    return dataset


def clear_cached_datasets(data_dir: Path | None = None) -> None:
    """
    Remove all cached benchmark datasets.

    Args:
        data_dir: Optional custom data directory
    """
    import shutil

    base_dir = data_dir or BENCHMARK_DATA_DIR
    if base_dir.exists():
        shutil.rmtree(base_dir)
        logger.info(f"Cleared cached datasets from {base_dir}")
    else:
        logger.debug(f"No cached datasets found at {base_dir}")
