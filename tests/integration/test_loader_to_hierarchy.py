"""
Integration tests: Loader → HierarchyResolver.

Validates that loaded data (parquet files) produces correct hierarchy
resolution — schema conformance, parent-child mappings, lending group
aggregation, and edge cases with minimal/empty data.

Why Priority 3: This boundary is where raw files first enter the pipeline.
Schema mismatches or missing columns here silently propagate through every
downstream stage. Lower priority than P1/P2 because acceptance tests also
cover this path end-to-end, but targeted tests isolate loader↔hierarchy
issues that acceptance tests cannot pinpoint.

Components wired: ParquetLoader (real) → HierarchyResolver (real)
No mocking. Parquet files written to temp dirs, loaded by ParquetLoader.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    ORG_MAPPING_SCHEMA,
)
from rwa_calc.engine.hierarchy import HierarchyResolver
from rwa_calc.engine.loader import DataSourceConfig, ParquetLoader

# =============================================================================
# HELPERS
# =============================================================================

_REPORTING_DATE = date(2024, 12, 31)
_VALUE_DATE = date(2024, 1, 1)
_MATURITY_DATE = date(2029, 12, 31)


def _write_parquet(df: pl.DataFrame, path: Path) -> None:
    """Write a Polars DataFrame to a parquet file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def _make_counterparty_df(**overrides: Any) -> pl.DataFrame:
    """Build a single-row counterparties DataFrame with schema-conforming defaults."""
    defaults: dict[str, Any] = {
        "counterparty_reference": "CP001",
        "counterparty_name": "Test Corp",
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
    defaults.update(overrides)
    df = pl.DataFrame([defaults])
    cast_exprs = []
    for col_name, col_type in COUNTERPARTY_SCHEMA.items():
        if col_name in df.columns:
            cast_exprs.append(pl.col(col_name).cast(col_type, strict=False))
        else:
            cast_exprs.append(pl.lit(None).cast(col_type).alias(col_name))
    return df.select(cast_exprs)


def _make_loan_df(**overrides: Any) -> pl.DataFrame:
    """Build a single-row loans DataFrame."""
    defaults: dict[str, Any] = {
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
    defaults.update(overrides)
    df = pl.DataFrame([defaults])
    cast_exprs = []
    for col_name, col_type in LOAN_SCHEMA.items():
        if col_name in df.columns:
            cast_exprs.append(pl.col(col_name).cast(col_type, strict=False))
        else:
            cast_exprs.append(pl.lit(None).cast(col_type).alias(col_name))
    return df.select(cast_exprs)


def _make_facility_df(**overrides: Any) -> pl.DataFrame:
    """Build a single-row facilities DataFrame."""
    defaults: dict[str, Any] = {
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
    defaults.update(overrides)
    df = pl.DataFrame([defaults])
    cast_exprs = []
    for col_name, col_type in FACILITY_SCHEMA.items():
        if col_name in df.columns:
            cast_exprs.append(pl.col(col_name).cast(col_type, strict=False))
        else:
            cast_exprs.append(pl.lit(None).cast(col_type).alias(col_name))
    return df.select(cast_exprs)


def _make_facility_mappings_df(
    rows: list[dict[str, Any]] | None = None,
) -> pl.DataFrame:
    """Build facility mappings DataFrame."""
    if not rows:
        rows = [
            {
                "parent_facility_reference": "FAC001",
                "child_reference": "LN001",
                "child_type": "loan",
            }
        ]
    df = pl.DataFrame(rows)
    cast_exprs = []
    for col_name, col_type in FACILITY_MAPPING_SCHEMA.items():
        if col_name in df.columns:
            cast_exprs.append(pl.col(col_name).cast(col_type, strict=False))
        else:
            cast_exprs.append(pl.lit(None).cast(col_type).alias(col_name))
    return df.select(cast_exprs)


def _make_lending_mappings_df(
    rows: list[dict[str, Any]] | None = None,
) -> pl.DataFrame:
    """Build lending mappings DataFrame (empty by default)."""
    if not rows:
        return pl.DataFrame(schema=LENDING_MAPPING_SCHEMA)
    df = pl.DataFrame(rows)
    cast_exprs = []
    for col_name, col_type in LENDING_MAPPING_SCHEMA.items():
        if col_name in df.columns:
            cast_exprs.append(pl.col(col_name).cast(col_type, strict=False))
        else:
            cast_exprs.append(pl.lit(None).cast(col_type).alias(col_name))
    return df.select(cast_exprs)


def _write_minimal_dataset(
    base_dir: Path,
    counterparties: pl.DataFrame | None = None,
    loans: pl.DataFrame | None = None,
    facilities: pl.DataFrame | None = None,
    facility_mappings: pl.DataFrame | None = None,
    lending_mappings: pl.DataFrame | None = None,
    org_mappings: pl.DataFrame | None = None,
) -> DataSourceConfig:
    """Write parquet files to base_dir and return a DataSourceConfig pointing at them."""
    cp_df = counterparties if counterparties is not None else _make_counterparty_df()
    ln_df = loans if loans is not None else _make_loan_df()
    fac_df = facilities if facilities is not None else _make_facility_df()
    fm_df = facility_mappings if facility_mappings is not None else _make_facility_mappings_df()
    lm_df = lending_mappings if lending_mappings is not None else _make_lending_mappings_df()

    cp_path = base_dir / "counterparties.parquet"
    ln_path = base_dir / "loans.parquet"
    fac_path = base_dir / "facilities.parquet"
    fm_path = base_dir / "facility_mappings.parquet"
    lm_path = base_dir / "lending_mappings.parquet"

    _write_parquet(cp_df, cp_path)
    _write_parquet(ln_df, ln_path)
    _write_parquet(fac_df, fac_path)
    _write_parquet(fm_df, fm_path)
    _write_parquet(lm_df, lm_path)

    config = DataSourceConfig(
        counterparties_file=cp_path,
        facilities_file=fac_path,
        loans_file=ln_path,
        facility_mappings_file=fm_path,
        lending_mappings_file=lm_path,
    )

    if org_mappings is not None:
        org_path = base_dir / "org_mappings.parquet"
        _write_parquet(org_mappings, org_path)
        config.org_mappings_file = org_path

    return config


# =============================================================================
# Schema conformance (3 tests)
# =============================================================================


class TestSchemaConformance:
    """Verify loader output matches hierarchy resolver's input contract."""

    def test_loaded_counterparties_have_all_hierarchy_columns(
        self, hierarchy_resolver, crr_config, tmp_path
    ):
        """Loader output for counterparties contains all columns needed by hierarchy resolver."""
        ds_config = _write_minimal_dataset(tmp_path)
        loader = ParquetLoader(tmp_path, config=ds_config)
        bundle = loader.load()

        cp_cols = set(bundle.counterparties.collect_schema().names())
        required = {"counterparty_reference", "entity_type", "country_code"}
        missing = required - cp_cols
        assert not missing, f"Loaded counterparties missing hierarchy columns: {missing}"

    def test_loaded_facilities_have_mapping_columns(
        self, hierarchy_resolver, crr_config, tmp_path
    ):
        """Loaded facilities have facility_reference and counterparty_reference for mapping."""
        ds_config = _write_minimal_dataset(tmp_path)
        loader = ParquetLoader(tmp_path, config=ds_config)
        bundle = loader.load()

        fac_cols = set(bundle.facilities.collect_schema().names())
        assert "facility_reference" in fac_cols
        assert "counterparty_reference" in fac_cols

    def test_loaded_loans_have_counterparty_reference(
        self, hierarchy_resolver, crr_config, tmp_path
    ):
        """Loaded loans contain counterparty_reference for hierarchy linkage."""
        ds_config = _write_minimal_dataset(tmp_path)
        loader = ParquetLoader(tmp_path, config=ds_config)
        bundle = loader.load()

        loan_cols = set(bundle.loans.collect_schema().names())
        assert "counterparty_reference" in loan_cols
        assert "loan_reference" in loan_cols


# =============================================================================
# Data integrity (3 tests)
# =============================================================================


class TestDataIntegrity:
    """Verify loaded data produces correct hierarchy resolution results."""

    def test_parent_child_mappings_resolve_hierarchy(
        self, hierarchy_resolver, crr_config, tmp_path
    ):
        """org_mappings → correct parent_reference in resolved hierarchy."""
        parent_df = _make_counterparty_df(
            counterparty_reference="PARENT",
            counterparty_name="Parent Corp",
        )
        child_df = _make_counterparty_df(
            counterparty_reference="CHILD",
            counterparty_name="Child Corp",
        )
        cp_df = pl.concat([parent_df, child_df])

        ln_df = _make_loan_df(
            loan_reference="LN_CHILD",
            counterparty_reference="CHILD",
        )
        fac_df = _make_facility_df(
            facility_reference="FAC_CHILD",
            counterparty_reference="CHILD",
        )
        fm_df = _make_facility_mappings_df([
            {
                "parent_facility_reference": "FAC_CHILD",
                "child_reference": "LN_CHILD",
                "child_type": "loan",
            }
        ])

        org_df = pl.DataFrame([{
            "parent_counterparty_reference": "PARENT",
            "child_counterparty_reference": "CHILD",
        }])
        org_cast = []
        for col_name, col_type in ORG_MAPPING_SCHEMA.items():
            if col_name in org_df.columns:
                org_cast.append(pl.col(col_name).cast(col_type, strict=False))
            else:
                org_cast.append(pl.lit(None).cast(col_type).alias(col_name))
        org_df = org_df.select(org_cast)

        ds_config = _write_minimal_dataset(
            tmp_path,
            counterparties=cp_df,
            loans=ln_df,
            facilities=fac_df,
            facility_mappings=fm_df,
            org_mappings=org_df,
        )
        loader = ParquetLoader(tmp_path, config=ds_config)
        bundle = loader.load()
        resolved = hierarchy_resolver.resolve(bundle, crr_config)

        # Parent mappings should contain the CHILD → PARENT relationship
        parent_mappings = resolved.counterparty_lookup.parent_mappings.collect()
        assert parent_mappings.height >= 1

    def test_lending_group_totals_aggregated(
        self, hierarchy_resolver, crr_config, tmp_path
    ):
        """Lending group with two counterparties → aggregated exposure totals."""
        cp1 = _make_counterparty_df(
            counterparty_reference="CP_A",
            counterparty_name="Corp A",
        )
        cp2 = _make_counterparty_df(
            counterparty_reference="CP_B",
            counterparty_name="Corp B",
        )
        cp_df = pl.concat([cp1, cp2])

        ln1 = _make_loan_df(
            loan_reference="LN_A",
            counterparty_reference="CP_A",
            drawn_amount=500_000.0,
        )
        ln2 = _make_loan_df(
            loan_reference="LN_B",
            counterparty_reference="CP_B",
            drawn_amount=300_000.0,
        )
        ln_df = pl.concat([ln1, ln2])

        fac1 = _make_facility_df(
            facility_reference="FAC_A",
            counterparty_reference="CP_A",
            limit=1_000_000.0,
        )
        fac2 = _make_facility_df(
            facility_reference="FAC_B",
            counterparty_reference="CP_B",
            limit=800_000.0,
        )
        fac_df = pl.concat([fac1, fac2])

        fm_df = _make_facility_mappings_df([
            {
                "parent_facility_reference": "FAC_A",
                "child_reference": "LN_A",
                "child_type": "loan",
            },
            {
                "parent_facility_reference": "FAC_B",
                "child_reference": "LN_B",
                "child_type": "loan",
            },
        ])

        lm_df = _make_lending_mappings_df([
            {
                "parent_counterparty_reference": "CP_A",
                "child_counterparty_reference": "CP_B",
            },
        ])

        ds_config = _write_minimal_dataset(
            tmp_path,
            counterparties=cp_df,
            loans=ln_df,
            facilities=fac_df,
            facility_mappings=fm_df,
            lending_mappings=lm_df,
        )
        loader = ParquetLoader(tmp_path, config=ds_config)
        bundle = loader.load()
        resolved = hierarchy_resolver.resolve(bundle, crr_config)

        # Lending group totals should aggregate exposures across the group
        lg_totals = resolved.lending_group_totals.collect()
        assert lg_totals.height >= 1

    def test_loaded_data_resolves_to_valid_exposures(
        self, hierarchy_resolver, crr_config, tmp_path
    ):
        """Loaded data produces a ResolvedHierarchyBundle with non-empty exposures."""
        ds_config = _write_minimal_dataset(tmp_path)
        loader = ParquetLoader(tmp_path, config=ds_config)
        bundle = loader.load()
        resolved = hierarchy_resolver.resolve(bundle, crr_config)

        exposures = resolved.exposures.collect()
        assert exposures.height >= 1
        # Should have both loan and facility_undrawn exposure types
        types = set(exposures["exposure_type"].unique().to_list())
        assert "loan" in types


# =============================================================================
# Edge cases (2 tests)
# =============================================================================


class TestEdgeCases:
    """Verify loader handles edge cases correctly."""

    def test_empty_optional_tables_produce_valid_bundle(
        self, hierarchy_resolver, crr_config, tmp_path
    ):
        """No contingents/collateral/guarantees → still valid bundle and hierarchy."""
        # Only write required files (no contingents, collateral, etc.)
        ds_config = _write_minimal_dataset(tmp_path)
        loader = ParquetLoader(tmp_path, config=ds_config)
        bundle = loader.load()

        # Optional tables should be None
        assert bundle.contingents is None
        assert bundle.collateral is None
        assert bundle.guarantees is None

        # Should still resolve hierarchy successfully
        resolved = hierarchy_resolver.resolve(bundle, crr_config)
        exposures = resolved.exposures.collect()
        assert exposures.height >= 1

    def test_minimal_dataset_loads_and_resolves(
        self, hierarchy_resolver, crr_config, tmp_path
    ):
        """Just counterparties + loans + facility → valid hierarchy resolution."""
        ds_config = _write_minimal_dataset(tmp_path)
        loader = ParquetLoader(tmp_path, config=ds_config)
        bundle = loader.load()
        resolved = hierarchy_resolver.resolve(bundle, crr_config)

        exposures = resolved.exposures.collect()
        assert exposures.height >= 1

        # Counterparty lookup should be populated
        cp_lookup = resolved.counterparty_lookup.counterparties.collect()
        assert cp_lookup.height >= 1
