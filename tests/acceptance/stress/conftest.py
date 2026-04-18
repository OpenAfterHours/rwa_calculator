"""
Stress test fixtures: synthetic data generators and pipeline runners.

Generates large-scale test data with realistic entity type distributions
and runs the full pipeline for correctness validation.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np
import polars as pl
import pytest
from tests.fixtures.irb_test_helpers import (
    create_full_irb_model_permissions,
    enrich_ratings_with_model_id,
)

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CONTINGENTS_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    ORG_MAPPING_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Use 2028 so Basel 3.1 output floor is active (PRA transitional starts 2027)
STRESS_REPORTING_DATE = date(2028, 1, 1)

ENTITY_TYPES = ["corporate", "individual", "institution", "sovereign", "specialised_lending"]
ENTITY_PROBS = [0.35, 0.30, 0.15, 0.10, 0.10]

PRODUCT_MAP = {
    "corporate": ["TERM_LOAN", "RCF_DRAWING", "TRADE_LOAN"],
    "individual": ["PERSONAL_LOAN", "RESIDENTIAL_MORTGAGE", "CREDIT_CARD"],
    "institution": ["INTERBANK_LOAN", "TERM_LOAN"],
    "sovereign": ["SOVEREIGN_LOAN"],
    "specialised_lending": ["PROJECT_FINANCE", "OBJECT_FINANCE", "IPRE", "HVCRE"],
}

BOOK_MAP = {
    "TERM_LOAN": "CORP_LENDING",
    "RCF_DRAWING": "CORP_LENDING",
    "TRADE_LOAN": "TRADE_FINANCE",
    "INTERBANK_LOAN": "FI_LENDING",
    "SOVEREIGN_LOAN": "SOVEREIGN",
    "PERSONAL_LOAN": "RETAIL_UNSECURED",
    "RESIDENTIAL_MORTGAGE": "RETAIL_MORTGAGES",
    "CREDIT_CARD": "RETAIL_CARDS",
    "PROJECT_FINANCE": "SPECIALISED_LENDING",
    "OBJECT_FINANCE": "SPECIALISED_LENDING",
    "IPRE": "SPECIALISED_LENDING",
    "HVCRE": "SPECIALISED_LENDING",
}


# ---------------------------------------------------------------------------
# Data generators
# ---------------------------------------------------------------------------


def generate_stress_counterparties(n: int, seed: int = 42) -> pl.LazyFrame:
    """Generate n counterparties with mixed entity types."""
    rng = np.random.default_rng(seed)

    entities = np.array(ENTITY_TYPES)[rng.choice(len(ENTITY_TYPES), size=n, p=ENTITY_PROBS)]

    countries = rng.choice(
        ["GB", "US", "DE", "FR", "JP"],
        size=n,
        p=[0.60, 0.15, 0.10, 0.10, 0.05],
    )

    revenues = np.zeros(n)
    corp_mask = entities == "corporate"
    ind_mask = entities == "individual"
    inst_mask = entities == "institution"
    sov_mask = entities == "sovereign"
    sl_mask = entities == "specialised_lending"

    revenues[corp_mask] = rng.uniform(1e6, 5e8, size=corp_mask.sum())
    revenues[ind_mask] = rng.uniform(0, 2e6, size=ind_mask.sum())
    revenues[inst_mask] = rng.uniform(1e9, 1e11, size=inst_mask.sum())
    revenues[sov_mask] = rng.uniform(1e10, 1e12, size=sov_mask.sum())
    revenues[sl_mask] = rng.uniform(1e7, 1e9, size=sl_mask.sum())

    assets = revenues * rng.uniform(1.2, 2.0, size=n)
    defaults = rng.random(n) < 0.02

    country_to_ccy = {"GB": "GBP", "US": "USD", "DE": "EUR", "FR": "EUR", "JP": "JPY"}
    income_currencies = [
        country_to_ccy.get(c) if is_ind else None
        for c, is_ind in zip(countries, ind_mask, strict=False)
    ]

    return (
        pl.DataFrame(
            {
                "counterparty_reference": [f"CP_{i:08d}" for i in range(n)],
                "counterparty_name": [f"Entity_{i}" for i in range(n)],
                "entity_type": entities,
                "country_code": countries,
                "annual_revenue": revenues,
                "total_assets": assets,
                "default_status": defaults,
                "sector_code": rng.choice(["64.19", "47.11", "25.11", "42.21"], size=n),
                "apply_fi_scalar": np.zeros(n, dtype=bool),
                "is_financial_sector_entity": np.zeros(n, dtype=bool),
                "is_managed_as_retail": np.zeros(n, dtype=bool),
                "scra_grade": pl.Series([None] * n, dtype=pl.String),
                "is_investment_grade": np.zeros(n, dtype=bool),
                "is_ccp_client_cleared": pl.Series([None] * n, dtype=pl.Boolean),
                "borrower_income_currency": pl.Series(income_currencies, dtype=pl.String),
                "is_natural_person": ind_mask,
                "is_social_housing": np.zeros(n, dtype=bool),
                "sovereign_cqs": pl.Series([None] * n, dtype=pl.Int32),
                "local_currency": pl.Series([None] * n, dtype=pl.String),
                "institution_cqs": pl.Series([None] * n, dtype=pl.Int8),
            }
        )
        .cast(dtypes_of(COUNTERPARTY_SCHEMA))
        .lazy()
    )


def generate_stress_loans(
    counterparties: pl.LazyFrame,
    loans_per_cp: int = 3,
    seed: int = 42,
) -> pl.LazyFrame:
    """Generate loans linked to counterparties with entity-appropriate products."""
    rng = np.random.default_rng(seed + 10)

    cp_data = counterparties.select(
        "counterparty_reference", "entity_type", "annual_revenue"
    ).collect()
    cp_refs = cp_data["counterparty_reference"].to_numpy()
    entity_types = cp_data["entity_type"].to_numpy()
    revenues = cp_data["annual_revenue"].to_numpy()
    n_cp = len(cp_refs)
    n_loans = n_cp * loans_per_cp

    # Assign loans to counterparties round-robin then shuffle
    cp_assignments = np.tile(np.arange(n_cp), loans_per_cp)
    rng.shuffle(cp_assignments)

    loan_entities = entity_types[cp_assignments]
    loan_revenues = revenues[cp_assignments]

    # Assign product types based on entity type
    product_types = np.empty(n_loans, dtype=object)
    for etype, products in PRODUCT_MAP.items():
        mask = loan_entities == etype
        n_match = mask.sum()
        if n_match > 0:
            product_types[mask] = rng.choice(products, size=n_match)

    book_codes = np.array([BOOK_MAP.get(p, "CORP_LENDING") for p in product_types])

    base_date = date(2026, 1, 1)
    maturity_days = rng.integers(365, 365 * 7, size=n_loans)

    drawn_amounts = np.maximum(loan_revenues * rng.uniform(0.001, 0.05, size=n_loans), 10_000)

    lgd = np.full(n_loans, 0.45)
    lgd[product_types == "RESIDENTIAL_MORTGAGE"] = 0.10
    lgd[product_types == "CREDIT_CARD"] = 0.85

    seniority = rng.choice(["senior", "subordinated"], size=n_loans, p=[0.92, 0.08])

    # Slotting loans get SL_ prefix for classifier
    sl_mask = loan_entities == "specialised_lending"
    sl_cats = ["STRONG", "GOOD", "SATISFACTORY", "WEAK", "DEFAULT"]
    sl_probs = [0.20, 0.35, 0.30, 0.10, 0.05]
    loan_refs = []
    for i in range(n_loans):
        if sl_mask[i]:
            cat = rng.choice(sl_cats, p=sl_probs)
            loan_refs.append(f"SL_{cat}_{i:08d}")
        else:
            loan_refs.append(f"LOAN_{i:08d}")

    return (
        pl.DataFrame(
            {
                "loan_reference": loan_refs,
                "product_type": product_types,
                "book_code": book_codes,
                "counterparty_reference": cp_refs[cp_assignments],
                "value_date": [base_date] * n_loans,
                "maturity_date": [base_date + timedelta(days=int(d)) for d in maturity_days],
                "currency": rng.choice(["GBP", "USD", "EUR"], size=n_loans, p=[0.70, 0.20, 0.10]),
                "drawn_amount": drawn_amounts,
                "interest": np.zeros(n_loans),
                "lgd": lgd,
                "beel": np.zeros(n_loans),
                "seniority": seniority,
                "lgd_unsecured": np.full(n_loans, None),
                "has_sufficient_collateral_data": np.full(n_loans, None),
                "is_payroll_loan": np.full(n_loans, None),
                "is_buy_to_let": np.full(n_loans, None),
                "has_one_day_maturity_floor": np.full(n_loans, None),
                "has_netting_agreement": np.full(n_loans, None),
                "netting_facility_reference": np.full(n_loans, None),
                "due_diligence_performed": np.full(n_loans, None),
                "due_diligence_override_rw": np.full(n_loans, None),
                "is_sft": np.full(n_loans, None),
            }
        )
        .cast(dtypes_of(LOAN_SCHEMA))
        .lazy()
    )


def generate_stress_facilities(
    counterparties: pl.LazyFrame,
    seed: int = 42,
) -> pl.LazyFrame:
    """Generate one facility per counterparty."""
    rng = np.random.default_rng(seed + 20)

    cp_data = counterparties.select("counterparty_reference", "annual_revenue").collect()
    cp_refs = cp_data["counterparty_reference"].to_numpy()
    revenues = cp_data["annual_revenue"].to_numpy()
    n = len(cp_refs)

    base_date = date(2026, 1, 1)
    limits = np.maximum(revenues * rng.uniform(0.01, 0.10, size=n), 100_000)
    risk_types = rng.choice(["MR", "LR", "MLR"], size=n, p=[0.50, 0.30, 0.20])

    return (
        pl.DataFrame(
            {
                "facility_reference": [f"FAC_{i:08d}" for i in range(n)],
                "product_type": rng.choice(["RCF", "TERM_FACILITY"], size=n, p=[0.50, 0.50]),
                "book_code": rng.choice(["CORP_LENDING", "RETAIL_LENDING"], size=n, p=[0.60, 0.40]),
                "counterparty_reference": cp_refs,
                "value_date": [base_date] * n,
                "maturity_date": [
                    base_date + timedelta(days=int(d)) for d in rng.integers(365, 3650, size=n)
                ],
                "currency": rng.choice(["GBP", "USD", "EUR"], size=n, p=[0.70, 0.20, 0.10]),
                "limit": limits,
                "committed": rng.random(n) > 0.1,
                "lgd": np.full(n, 0.45),
                "beel": np.zeros(n),
                "is_revolving": rng.random(n) > 0.5,
                "is_qrre_transactor": np.full(n, False),
                "seniority": rng.choice(["senior", "subordinated"], size=n, p=[0.90, 0.10]),
                "risk_type": risk_types,
                "ccf_modelled": np.full(n, None),
                "ead_modelled": np.full(n, None),
                "is_short_term_trade_lc": np.full(n, None),
                "is_payroll_loan": np.full(n, None),
                "is_buy_to_let": np.full(n, None),
                "has_one_day_maturity_floor": np.full(n, None),
                "facility_termination_date": pl.Series([None] * n, dtype=pl.Date),
                "underlying_risk_type": pl.Series([None] * n, dtype=pl.String),
                "lgd_unsecured": np.full(n, None),
                "has_sufficient_collateral_data": np.full(n, None),
                "is_sft": np.full(n, None),
            }
        )
        .cast(dtypes_of(FACILITY_SCHEMA))
        .lazy()
    )


def generate_stress_ratings(
    counterparties: pl.LazyFrame,
    rated_pct: float = 0.7,
    seed: int = 42,
) -> pl.LazyFrame:
    """Generate ratings for a percentage of counterparties."""
    rng = np.random.default_rng(seed + 30)

    cp_data = counterparties.select("counterparty_reference", "entity_type").collect()
    cp_refs = cp_data["counterparty_reference"].to_numpy()
    n_cp = len(cp_refs)
    n_rated = int(n_cp * rated_pct)

    rated_idx = rng.permutation(n_cp)[:n_rated]
    rated_refs = cp_refs[rated_idx]

    cqs = rng.choice([1, 2, 3, 4, 5, 6], size=n_rated, p=[0.10, 0.25, 0.30, 0.20, 0.10, 0.05])
    pds = np.array([0.0003, 0.001, 0.005, 0.02, 0.05, 0.15])[cqs - 1]

    cqs_to_rating = {1: "AAA", 2: "AA", 3: "A", 4: "BBB", 5: "BB", 6: "B"}
    rating_values = [cqs_to_rating[c] for c in cqs]

    return (
        pl.DataFrame(
            {
                "rating_reference": [f"RTG_{i:08d}" for i in range(n_rated)],
                "counterparty_reference": rated_refs,
                "rating_type": rng.choice(["external", "internal"], size=n_rated, p=[0.6, 0.4]),
                "rating_agency": rng.choice(["S&P", "Moodys", "Fitch"], size=n_rated),
                "rating_value": rating_values,
                "cqs": cqs.astype(np.int8),
                "pd": pds,
                "rating_date": [date(2025, 12, 1)] * n_rated,
                "is_solicited": np.full(n_rated, True),
                "model_id": pl.Series([None] * n_rated, dtype=pl.String),
            }
        )
        .cast(dtypes_of(RATINGS_SCHEMA))
        .lazy()
    )


def generate_stress_org_mappings(
    counterparties: pl.LazyFrame,
    hierarchy_pct: float = 0.4,
    seed: int = 42,
) -> pl.LazyFrame:
    """Generate org hierarchy mappings."""
    rng = np.random.default_rng(seed + 40)

    cp_refs = (
        counterparties.select("counterparty_reference")
        .collect()["counterparty_reference"]
        .to_numpy()
    )
    n = len(cp_refs)
    n_children = int(n * hierarchy_pct)

    # First n_children are children, rest are potential parents
    child_indices = rng.permutation(n)[:n_children]
    parent_pool = np.array([i for i in range(n) if i not in set(child_indices)])

    if len(parent_pool) == 0:
        return pl.LazyFrame(schema=dtypes_of(ORG_MAPPING_SCHEMA))

    parent_indices = rng.choice(parent_pool, size=n_children)

    return (
        pl.DataFrame(
            {
                "parent_counterparty_reference": cp_refs[parent_indices],
                "child_counterparty_reference": cp_refs[child_indices],
            }
        )
        .cast(dtypes_of(ORG_MAPPING_SCHEMA))
        .lazy()
    )


def generate_stress_facility_mappings(
    facilities: pl.LazyFrame,
    loans: pl.LazyFrame,
    mapping_pct: float = 0.3,
    seed: int = 42,
) -> pl.LazyFrame:
    """Generate facility-to-loan mappings for a percentage of loans."""
    rng = np.random.default_rng(seed + 50)

    fac_refs = facilities.select("facility_reference").collect()["facility_reference"].to_numpy()
    loan_refs = loans.select("loan_reference").collect()["loan_reference"].to_numpy()

    if len(fac_refs) == 0 or len(loan_refs) == 0:
        return pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))

    n_mapped = int(len(loan_refs) * mapping_pct)
    mapped_loans = rng.choice(loan_refs, size=n_mapped, replace=False)
    assigned_facs = rng.choice(fac_refs, size=n_mapped)

    return (
        pl.DataFrame(
            {
                "parent_facility_reference": assigned_facs,
                "child_reference": mapped_loans,
                "child_type": ["loan"] * n_mapped,
            }
        )
        .cast(dtypes_of(FACILITY_MAPPING_SCHEMA))
        .lazy()
    )


def generate_stress_contingents(
    counterparties: pl.LazyFrame,
    n_per_cp: float = 0.5,
    seed: int = 42,
) -> pl.LazyFrame:
    """Generate contingent (off-balance-sheet) items."""
    rng = np.random.default_rng(seed + 60)

    cp_data = counterparties.select("counterparty_reference", "annual_revenue").collect()
    cp_refs = cp_data["counterparty_reference"].to_numpy()
    revenues = cp_data["annual_revenue"].to_numpy()
    n_cp = len(cp_refs)
    n_cont = int(n_cp * n_per_cp)

    cp_assignments = rng.choice(n_cp, size=n_cont)
    base_date = date(2026, 1, 1)

    return (
        pl.DataFrame(
            {
                "contingent_reference": [f"CONT_{i:08d}" for i in range(n_cont)],
                "product_type": rng.choice(
                    ["GUARANTEE_ISSUED", "LC", "COMMITMENT"], size=n_cont, p=[0.3, 0.3, 0.4]
                ),
                "book_code": ["CORP_LENDING"] * n_cont,
                "counterparty_reference": cp_refs[cp_assignments],
                "value_date": [base_date] * n_cont,
                "maturity_date": [
                    base_date + timedelta(days=int(d)) for d in rng.integers(180, 1825, size=n_cont)
                ],
                "currency": rng.choice(["GBP", "USD", "EUR"], size=n_cont, p=[0.70, 0.20, 0.10]),
                "nominal_amount": np.maximum(
                    revenues[cp_assignments] * rng.uniform(0.005, 0.03, size=n_cont), 5_000
                ),
                "lgd": np.full(n_cont, 0.45),
                "lgd_unsecured": np.full(n_cont, None),
                "has_sufficient_collateral_data": np.full(n_cont, None),
                "beel": np.zeros(n_cont),
                "seniority": rng.choice(["senior", "subordinated"], size=n_cont, p=[0.95, 0.05]),
                "risk_type": rng.choice(["MR", "FR", "LR"], size=n_cont, p=[0.50, 0.20, 0.30]),
                "bs_type": ["OFB"] * n_cont,
                "ccf_modelled": np.full(n_cont, None),
                "ead_modelled": np.full(n_cont, None),
                "underlying_risk_type": pl.Series([None] * n_cont, dtype=pl.String),
                "is_short_term_trade_lc": np.full(n_cont, None),
                "is_payroll_loan": np.full(n_cont, None),
                "is_buy_to_let": np.full(n_cont, None),
                "has_one_day_maturity_floor": np.full(n_cont, None),
                "due_diligence_performed": np.full(n_cont, None),
                "due_diligence_override_rw": np.full(n_cont, None),
                "is_sft": np.full(n_cont, None),
            }
        )
        .cast(dtypes_of(CONTINGENTS_SCHEMA))
        .lazy()
    )


# ---------------------------------------------------------------------------
# Dataset builder
# ---------------------------------------------------------------------------


def build_stress_dataset(n_counterparties: int, seed: int = 42) -> dict[str, pl.LazyFrame]:
    """Build a complete stress test dataset with n counterparties."""
    counterparties = generate_stress_counterparties(n_counterparties, seed=seed)
    facilities = generate_stress_facilities(counterparties, seed=seed)
    loans = generate_stress_loans(counterparties, loans_per_cp=3, seed=seed)
    contingents = generate_stress_contingents(counterparties, n_per_cp=0.5, seed=seed)
    ratings = generate_stress_ratings(counterparties, rated_pct=0.7, seed=seed)
    org_mappings = generate_stress_org_mappings(counterparties, hierarchy_pct=0.4, seed=seed)
    facility_mappings = generate_stress_facility_mappings(
        facilities, loans, mapping_pct=0.3, seed=seed
    )

    return {
        "counterparties": counterparties,
        "facilities": facilities,
        "loans": loans,
        "contingents": contingents,
        "ratings": ratings,
        "org_mappings": org_mappings,
        "facility_mappings": facility_mappings,
    }


def create_raw_bundle(
    dataset: dict[str, pl.LazyFrame],
    *,
    irb: bool = False,
) -> RawDataBundle:
    """Create a RawDataBundle from a stress dataset.

    Args:
        dataset: Generated stress dataset.
        irb: If True, enrich ratings with model_id and attach model_permissions
             so the classifier can route exposures to IRB approaches.
    """
    ratings = dataset["ratings"]
    model_permissions = None

    if irb:
        ratings = enrich_ratings_with_model_id(ratings)
        model_permissions = create_full_irb_model_permissions()

    return RawDataBundle(
        counterparties=dataset["counterparties"],
        facilities=dataset["facilities"],
        loans=dataset["loans"],
        contingents=dataset["contingents"],
        collateral=None,
        guarantees=None,
        provisions=None,
        ratings=ratings,
        facility_mappings=dataset["facility_mappings"],
        org_mappings=dataset["org_mappings"],
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        model_permissions=model_permissions,
    )


def run_pipeline(
    dataset: dict[str, pl.LazyFrame],
    config: CalculationConfig,
) -> AggregatedResultBundle:
    """Run the full pipeline on a stress dataset."""
    irb = config.permission_mode == PermissionMode.IRB
    bundle = create_raw_bundle(dataset, irb=irb)
    pipeline = PipelineOrchestrator()
    return pipeline.run_with_data(bundle, config)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def stress_dataset_10k() -> dict[str, pl.LazyFrame]:
    """10K counterparty dataset (~30K loans, ~5K contingents)."""
    return build_stress_dataset(10_000, seed=42)


@pytest.fixture(scope="session")
def stress_dataset_100k() -> dict[str, pl.LazyFrame]:
    """100K counterparty dataset (~300K loans, ~50K contingents)."""
    return build_stress_dataset(100_000, seed=99)


@pytest.fixture(scope="session")
def crr_sa_config() -> CalculationConfig:
    """CRR framework, SA-only permission."""
    return CalculationConfig.crr(
        reporting_date=STRESS_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


@pytest.fixture(scope="session")
def crr_irb_config() -> CalculationConfig:
    """CRR framework, IRB permission."""
    return CalculationConfig.crr(
        reporting_date=STRESS_REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture(scope="session")
def b31_sa_config() -> CalculationConfig:
    """Basel 3.1 framework, SA-only permission."""
    return CalculationConfig.basel_3_1(
        reporting_date=STRESS_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


@pytest.fixture(scope="session")
def b31_irb_config() -> CalculationConfig:
    """Basel 3.1 framework, IRB permission."""
    return CalculationConfig.basel_3_1(
        reporting_date=STRESS_REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )


# Cache pipeline results at session scope to avoid re-running expensive pipelines
@pytest.fixture(scope="session")
def crr_sa_result_10k(
    stress_dataset_10k: dict[str, pl.LazyFrame],
    crr_sa_config: CalculationConfig,
) -> AggregatedResultBundle:
    """CRR SA pipeline result at 10K scale."""
    return run_pipeline(stress_dataset_10k, crr_sa_config)


@pytest.fixture(scope="session")
def crr_irb_result_10k(
    stress_dataset_10k: dict[str, pl.LazyFrame],
    crr_irb_config: CalculationConfig,
) -> AggregatedResultBundle:
    """CRR IRB pipeline result at 10K scale."""
    return run_pipeline(stress_dataset_10k, crr_irb_config)


@pytest.fixture(scope="session")
def b31_sa_result_10k(
    stress_dataset_10k: dict[str, pl.LazyFrame],
    b31_sa_config: CalculationConfig,
) -> AggregatedResultBundle:
    """Basel 3.1 SA pipeline result at 10K scale."""
    return run_pipeline(stress_dataset_10k, b31_sa_config)


@pytest.fixture(scope="session")
def b31_irb_result_10k(
    stress_dataset_10k: dict[str, pl.LazyFrame],
    b31_irb_config: CalculationConfig,
) -> AggregatedResultBundle:
    """Basel 3.1 IRB pipeline result at 10K scale."""
    return run_pipeline(stress_dataset_10k, b31_irb_config)
