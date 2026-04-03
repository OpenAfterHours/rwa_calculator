"""
Shared test infrastructure for integration tests.

Provides:
- Config factory fixtures (CRR, Basel 3.1, with various IRB permissions)
- Data builder functions (make_counterparty, make_loan, make_facility, etc.)
- make_raw_data_bundle() to assemble builders into a RawDataBundle
- Component fixtures (hierarchy_resolver, classifier, crm_processor, etc.)

All builders return dicts with sensible defaults, overridable via kwargs.
make_raw_data_bundle() converts row dicts into typed LazyFrames matching
the production schemas, then wraps them in a RawDataBundle.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.schemas import (
    CONTINGENTS_SCHEMA,
    COUNTERPARTY_SCHEMA,
    EQUITY_EXPOSURE_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    ORG_MAPPING_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.equity.calculator import EquityCalculator
from rwa_calc.engine.hierarchy import HierarchyResolver
from rwa_calc.engine.irb.calculator import IRBCalculator
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.engine.slotting.calculator import SlottingCalculator

# =============================================================================
# CONFIG FACTORIES
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def crr_firb_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def crr_full_irb_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def basel31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2028, 1, 15))


@pytest.fixture
def basel31_full_irb_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(
        reporting_date=date(2028, 1, 15),
        permission_mode=PermissionMode.IRB,
    )


# =============================================================================
# DATA BUILDERS
# =============================================================================

_REPORTING_DATE = date(2024, 12, 31)
_VALUE_DATE = date(2024, 1, 1)
_MATURITY_DATE = date(2029, 12, 31)

_COUNTERPARTY_DEFAULTS: dict[str, Any] = {
    "counterparty_reference": "CP001",
    "counterparty_name": "Test Counterparty",
    "entity_type": "corporate",
    "country_code": "GB",
    "annual_revenue": 100_000_000.0,
    "total_assets": 500_000_000.0,
    "default_status": False,
    "sector_code": "6200",
    "apply_fi_scalar": False,
    "is_managed_as_retail": False,
    "scra_grade": None,
    "is_investment_grade": False,
}

_LOAN_DEFAULTS: dict[str, Any] = {
    "loan_reference": "LN001",
    "product_type": "TERM_LOAN",
    "book_code": "MAIN",
    "counterparty_reference": "CP001",
    "value_date": _VALUE_DATE,
    "maturity_date": _MATURITY_DATE,
    "currency": "GBP",
    "drawn_amount": 1_000_000.0,
    "interest": 5_000.0,
    "lgd": None,
    "beel": 0.0,
    "seniority": "senior",
    "is_buy_to_let": False,
    "has_netting_agreement": False,
    "netting_facility_reference": None,
}

_FACILITY_DEFAULTS: dict[str, Any] = {
    "facility_reference": "FAC001",
    "product_type": "REVOLVING_CREDIT",
    "book_code": "MAIN",
    "counterparty_reference": "CP001",
    "value_date": _VALUE_DATE,
    "maturity_date": _MATURITY_DATE,
    "currency": "GBP",
    "limit": 2_000_000.0,
    "committed": True,
    "lgd": None,
    "beel": 0.0,
    "is_revolving": True,
    "is_qrre_transactor": False,
    "seniority": "senior",
    "risk_type": "medium_risk",
    "ccf_modelled": None,
    "is_short_term_trade_lc": False,
    "is_buy_to_let": False,
}

_CONTINGENT_DEFAULTS: dict[str, Any] = {
    "contingent_reference": "CT001",
    "product_type": "GUARANTEE",
    "book_code": "MAIN",
    "counterparty_reference": "CP001",
    "value_date": _VALUE_DATE,
    "maturity_date": _MATURITY_DATE,
    "currency": "GBP",
    "nominal_amount": 500_000.0,
    "lgd": None,
    "beel": 0.0,
    "seniority": "senior",
    "risk_type": "full_risk",
    "ccf_modelled": None,
    "is_short_term_trade_lc": False,
    "bs_type": "OFB",
}

_EQUITY_EXPOSURE_DEFAULTS: dict[str, Any] = {
    "exposure_reference": "EQ001",
    "counterparty_reference": "CP001",
    "equity_type": "listed",
    "currency": "GBP",
    "carrying_value": 500_000.0,
    "fair_value": 500_000.0,
    "is_speculative": False,
    "is_exchange_traded": False,
    "is_government_supported": False,
    "is_significant_investment": False,
}

_MODEL_PERMISSION_DEFAULTS: dict[str, Any] = {
    "model_id": "MODEL_01",
    "exposure_class": "corporate",
    "approach": "foundation_irb",
    "country_codes": None,
    "excluded_book_codes": None,
}

_RATING_DEFAULTS: dict[str, Any] = {
    "rating_reference": "RAT001",
    "counterparty_reference": "CP001",
    "rating_type": "internal",
    "rating_agency": "internal",
    "rating_value": "BB",
    "cqs": None,
    "pd": 0.02,
    "rating_date": _REPORTING_DATE,
    "is_solicited": True,
    "model_id": None,
}


def make_counterparty(**overrides: Any) -> dict[str, Any]:
    """Single counterparty row with defaults."""
    return {**_COUNTERPARTY_DEFAULTS, **overrides}


def make_loan(**overrides: Any) -> dict[str, Any]:
    """Single loan row with defaults."""
    return {**_LOAN_DEFAULTS, **overrides}


def make_facility(**overrides: Any) -> dict[str, Any]:
    """Single facility row with defaults."""
    return {**_FACILITY_DEFAULTS, **overrides}


def make_contingent(**overrides: Any) -> dict[str, Any]:
    """Single contingent row with defaults."""
    return {**_CONTINGENT_DEFAULTS, **overrides}


def make_equity_exposure(**overrides: Any) -> dict[str, Any]:
    """Single equity exposure row with defaults."""
    return {**_EQUITY_EXPOSURE_DEFAULTS, **overrides}


def make_model_permission(**overrides: Any) -> dict[str, Any]:
    """Single model permission row with defaults."""
    return {**_MODEL_PERMISSION_DEFAULTS, **overrides}


def make_rating(**overrides: Any) -> dict[str, Any]:
    """Single rating row with defaults."""
    return {**_RATING_DEFAULTS, **overrides}


def _rows_to_lazyframe(rows: list[dict[str, Any]], schema: dict[str, Any]) -> pl.LazyFrame:
    """Convert row dicts to a LazyFrame, casting to the target schema."""
    if not rows:
        return pl.LazyFrame(schema=schema)
    df = pl.DataFrame(rows)
    # Cast columns to match schema types, adding missing columns with nulls
    cast_exprs = []
    for col_name, col_type in schema.items():
        if col_name in df.columns:
            cast_exprs.append(pl.col(col_name).cast(col_type, strict=False))
        else:
            cast_exprs.append(pl.lit(None).cast(col_type).alias(col_name))
    return df.lazy().select(cast_exprs)


def make_raw_data_bundle(
    counterparties: list[dict[str, Any]] | None = None,
    loans: list[dict[str, Any]] | None = None,
    facilities: list[dict[str, Any]] | None = None,
    contingents: list[dict[str, Any]] | None = None,
    model_permissions: list[dict[str, Any]] | None = None,
    facility_mappings: list[dict[str, Any]] | None = None,
    lending_mappings: list[dict[str, Any]] | None = None,
    org_mappings: list[dict[str, Any]] | None = None,
    equity_exposures: list[dict[str, Any]] | None = None,
    ratings: list[dict[str, Any]] | None = None,
) -> RawDataBundle:
    """Build a RawDataBundle from row dicts, applying schema defaults.

    Automatically generates facility_mappings from loans/contingents/facilities
    if not explicitly provided. Same for lending_mappings (empty by default).
    """
    cp_rows = counterparties or [make_counterparty()]
    loan_rows = loans or [make_loan()]
    fac_rows = facilities or [make_facility()]
    cont_rows = contingents or []

    # Auto-generate facility mappings: each loan/contingent → its counterparty's facility
    if facility_mappings is None:
        fm_rows: list[dict[str, Any]] = []
        # Map loans to facilities
        for loan in loan_rows:
            # Find matching facility for same counterparty
            matching_fac = next(
                (
                    f
                    for f in fac_rows
                    if f.get("counterparty_reference") == loan.get("counterparty_reference")
                ),
                fac_rows[0] if fac_rows else None,
            )
            if matching_fac:
                fm_rows.append(
                    {
                        "parent_facility_reference": matching_fac["facility_reference"],
                        "child_reference": loan["loan_reference"],
                        "child_type": "loan",
                    }
                )
        # Map contingents to facilities
        for cont in cont_rows:
            matching_fac = next(
                (
                    f
                    for f in fac_rows
                    if f.get("counterparty_reference") == cont.get("counterparty_reference")
                ),
                fac_rows[0] if fac_rows else None,
            )
            if matching_fac:
                fm_rows.append(
                    {
                        "parent_facility_reference": matching_fac["facility_reference"],
                        "child_reference": cont["contingent_reference"],
                        "child_type": "contingent",
                    }
                )
        # Note: Do NOT add facility self-reference entries (child_type=facility).
        # Those are only for multi-level facility hierarchies where sub-facilities
        # reference parent facilities. Adding them for standalone facilities causes
        # the hierarchy resolver to treat them as sub-facilities and exclude them
        # from undrawn exposure generation.
    else:
        fm_rows = facility_mappings

    lm_rows = lending_mappings or []

    bundle_kwargs: dict[str, Any] = {
        "counterparties": _rows_to_lazyframe(cp_rows, COUNTERPARTY_SCHEMA),
        "loans": _rows_to_lazyframe(loan_rows, LOAN_SCHEMA),
        "facilities": _rows_to_lazyframe(fac_rows, FACILITY_SCHEMA),
        "facility_mappings": _rows_to_lazyframe(fm_rows, FACILITY_MAPPING_SCHEMA),
        "lending_mappings": _rows_to_lazyframe(lm_rows, LENDING_MAPPING_SCHEMA),
    }
    if cont_rows:
        bundle_kwargs["contingents"] = _rows_to_lazyframe(cont_rows, CONTINGENTS_SCHEMA)
    if model_permissions is not None:
        bundle_kwargs["model_permissions"] = _rows_to_lazyframe(
            model_permissions, MODEL_PERMISSIONS_SCHEMA
        )
    if org_mappings is not None:
        bundle_kwargs["org_mappings"] = _rows_to_lazyframe(org_mappings, ORG_MAPPING_SCHEMA)
    if equity_exposures is not None:
        bundle_kwargs["equity_exposures"] = _rows_to_lazyframe(
            equity_exposures, EQUITY_EXPOSURE_SCHEMA
        )
    if ratings is not None:
        bundle_kwargs["ratings"] = _rows_to_lazyframe(ratings, RATINGS_SCHEMA)

    return RawDataBundle(**bundle_kwargs)


# =============================================================================
# COMPONENT FIXTURES
# =============================================================================


@pytest.fixture
def hierarchy_resolver() -> HierarchyResolver:
    return HierarchyResolver()


@pytest.fixture
def classifier() -> ExposureClassifier:
    return ExposureClassifier()


@pytest.fixture
def crm_processor() -> CRMProcessor:
    return CRMProcessor()


@pytest.fixture
def crm_processor_b31() -> CRMProcessor:
    return CRMProcessor(is_basel_3_1=True)


@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def irb_calculator() -> IRBCalculator:
    return IRBCalculator()


@pytest.fixture
def slotting_calculator() -> SlottingCalculator:
    return SlottingCalculator()


@pytest.fixture
def equity_calculator() -> EquityCalculator:
    return EquityCalculator()
