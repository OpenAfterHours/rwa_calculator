"""
Large-financial-sector-entity (LFSE) 1.25x correlation-multiplier fixtures.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (engine/stages/classify/subtypes.py, engine/stages/classify/audit.py)

Key responsibilities:
- Provide ``ResolvedHierarchyBundle`` builders that exercise the mandatory,
  size-DERIVED FI-scalar (CRR Art. 142(1)(4) / Art. 153(2); PS1/26 IRB Part
  glossary + Art. 153(2)). The multiplier must no longer depend solely on the
  user-supplied ``apply_fi_scalar`` election:

    (A) FSE, total_assets = GBP 100bn -> large under BOTH regimes (CRR EUR 70bn
        x rate ~= GBP 61bn; PS1/26 GBP 79bn) -> requires_fi_scalar True.
    (B) FSE, total_assets = GBP 65bn  -> large under CRR only (> ~GBP 61bn) but
        below the PS1/26 GBP 79bn threshold -> True under CRR, False under B31.
    (C) FSE, total_assets = GBP 50bn  -> below BOTH thresholds -> False.
    (D) FSE, total_assets = null      -> size undetermined -> scalar NOT applied
        (False), CLS009 fires (never a silent under-statement).
    (E) NON-FSE, total_assets = GBP 100bn -> False (size alone does not qualify).
    (F) NON-FSE (sub-threshold) + apply_fi_scalar = True -> True: the explicit
        election is an authoritative OVERRIDE and can never be suppressed.

All counterparties are ``entity_type="corporate"`` financial-sector entities so
the exposure keeps the CORPORATE IRB class (the FSE flag drives the correlation
multiplier, not the class) and routes through the IRB correlation formula.

References:
- CRR Art. 142(1)(4): large FSE = FSE with total assets (individual or
  consolidated) >= EUR 70bn, most recent audited financial statements.
- CRR Art. 142(1)(5): unregulated FSE (size-independent limb; not modelled here).
- CRR Art. 153(2): 1.25x correlation multiplier for large / unregulated FSEs.
- PRA PS1/26 IRB Part glossary "large financial sector entity" (GBP 79bn at the
  highest level of consolidation) read with PS1/26 Art. 153(2) ("shall multiply
  ... by 1.25" — mandatory, not an election).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from tests.fixtures.resolved_bundle import make_counterparty_lookup, make_resolved_bundle

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

    from rwa_calc.contracts.bundles import ResolvedHierarchyBundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

CP_LARGE_FSE: str = "CP_LARGE_FSE"
CP_MID_FSE: str = "CP_MID_FSE"
CP_SMALL_FSE: str = "CP_SMALL_FSE"
CP_NULL_FSE: str = "CP_NULL_FSE"
CP_NON_FSE_LARGE: str = "CP_NON_FSE_LARGE"
CP_OVERRIDE: str = "CP_OVERRIDE"

LOAN_REF: str = "LN_CORP_FSE"
MODEL_ID: str = "M_CORP_FIRB"

VALUE_DATE: date = date(2027, 1, 15)
MATURITY_DATE: date = date(2030, 1, 15)

DRAWN_AMOUNT: float = 1_000_000.0
EXPOSURE_PD: float = 0.005

# Total-assets values chosen to straddle the CRR (EUR 70bn x 0.8732 ~= GBP
# 61.1bn) and PS1/26 (GBP 79bn) LFSE thresholds.
ASSETS_LARGE_BOTH: float = 100_000_000_000.0  # > both -> large under CRR & B31
ASSETS_MID: float = 65_000_000_000.0  # > CRR (~61.1bn), < B31 (79bn)
ASSETS_SMALL: float = 50_000_000_000.0  # < both thresholds


# ---------------------------------------------------------------------------
# Counterparty builder
# ---------------------------------------------------------------------------

_CP_SCHEMA: dict[str, PolarsDataType] = {
    "counterparty_reference": pl.String,
    "entity_type": pl.String,
    "country_code": pl.String,
    "annual_revenue": pl.Float64,
    "total_assets": pl.Float64,
    "default_status": pl.Boolean,
    "apply_fi_scalar": pl.Boolean,
    "is_financial_sector_entity": pl.Boolean,
}


def _make_fse_cp(
    counterparty_reference: str,
    *,
    total_assets: float | None,
    is_financial_sector_entity: bool,
    apply_fi_scalar: bool = False,
) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "counterparty_reference": [counterparty_reference],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            # annual_revenue null so total_assets is the only size signal and
            # the row is unambiguously non-SME (assets >> SME threshold).
            "annual_revenue": [None],
            "total_assets": [total_assets],
            "default_status": [False],
            "apply_fi_scalar": [apply_fi_scalar],
            "is_financial_sector_entity": [is_financial_sector_entity],
        },
        schema=_CP_SCHEMA,
    )


# ---------------------------------------------------------------------------
# Exposure / model_permissions / rating builders
# ---------------------------------------------------------------------------


def _make_exposure(counterparty_reference: str) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "exposure_reference": [LOAN_REF],
            "exposure_type": ["loan"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": [counterparty_reference],
            "value_date": [VALUE_DATE],
            "maturity_date": [MATURITY_DATE],
            "currency": ["GBP"],
            "drawn_amount": [DRAWN_AMOUNT],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [DRAWN_AMOUNT],
            "residential_collateral_value": [0.0],
            "exposure_for_retail_threshold": [DRAWN_AMOUNT],
            "lending_group_adjusted_exposure": [DRAWN_AMOUNT],
            "model_id": [MODEL_ID],
        },
        schema={
            "exposure_reference": pl.String,
            "exposure_type": pl.String,
            "product_type": pl.String,
            "book_code": pl.String,
            "counterparty_reference": pl.String,
            "value_date": pl.Date,
            "maturity_date": pl.Date,
            "currency": pl.String,
            "drawn_amount": pl.Float64,
            "undrawn_amount": pl.Float64,
            "nominal_amount": pl.Float64,
            "lgd": pl.Float64,
            "seniority": pl.String,
            "exposure_has_parent": pl.Boolean,
            "root_facility_reference": pl.String,
            "facility_hierarchy_depth": pl.Int32,
            "counterparty_has_parent": pl.Boolean,
            "parent_counterparty_reference": pl.String,
            "ultimate_parent_reference": pl.String,
            "counterparty_hierarchy_depth": pl.Int32,
            "lending_group_reference": pl.String,
            "lending_group_total_exposure": pl.Float64,
            "residential_collateral_value": pl.Float64,
            "exposure_for_retail_threshold": pl.Float64,
            "lending_group_adjusted_exposure": pl.Float64,
            "model_id": pl.String,
        },
    )


def _make_model_permissions() -> pl.LazyFrame:
    # Grant both AIRB and FIRB for corporate so approach assignment is driven
    # by the regime restrictions (B31 forces an FSE corporate to F-IRB), not by
    # permission availability. requires_fi_scalar is set independently of the
    # approach in classify_exposure_subtypes.
    return pl.LazyFrame(
        {
            "model_id": [MODEL_ID, MODEL_ID],
            "exposure_class": ["corporate", "corporate"],
            "approach": ["advanced_irb", "foundation_irb"],
            "country_codes": [None, None],
            "excluded_book_codes": [None, None],
        },
        schema={
            "model_id": pl.String,
            "exposure_class": pl.String,
            "approach": pl.String,
            "country_codes": pl.String,
            "excluded_book_codes": pl.String,
        },
    )


def _make_rating_inheritance(counterparty_reference: str) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "counterparty_reference": [counterparty_reference],
            "internal_pd": [EXPOSURE_PD],
            "internal_model_id": [MODEL_ID],
            "external_cqs": [4],
            "cqs": [4],
            "pd": [EXPOSURE_PD],
        },
        schema={
            "counterparty_reference": pl.String,
            "internal_pd": pl.Float64,
            "internal_model_id": pl.String,
            "external_cqs": pl.Int8,
            "cqs": pl.Int8,
            "pd": pl.Float64,
        },
    )


def _enrich_counterparty(counterparties: pl.LazyFrame) -> pl.LazyFrame:
    schema_names = counterparties.collect_schema().names()
    cols: list[pl.Expr] = []
    if "counterparty_has_parent" not in schema_names:
        cols.append(pl.lit(False).alias("counterparty_has_parent"))
    if "parent_counterparty_reference" not in schema_names:
        cols.append(pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"))
    if "ultimate_parent_reference" not in schema_names:
        cols.append(pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"))
    if "counterparty_hierarchy_depth" not in schema_names:
        cols.append(pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"))
    if "cqs" not in schema_names:
        cols.append(pl.lit(None).cast(pl.Int8).alias("cqs"))
    return counterparties.with_columns(cols) if cols else counterparties


def _empty_schema_lf(schema: dict[str, PolarsDataType]) -> pl.LazyFrame:
    return pl.LazyFrame(schema=schema)


def _make_bundle(
    counterparties: pl.LazyFrame,
    counterparty_reference: str,
) -> ResolvedHierarchyBundle:
    return make_resolved_bundle(
        exposures=_make_exposure(counterparty_reference),
        counterparty_lookup=make_counterparty_lookup(
            counterparties=_enrich_counterparty(counterparties),
            parent_mappings=_empty_schema_lf(
                {
                    "child_counterparty_reference": pl.String,
                    "parent_counterparty_reference": pl.String,
                }
            ),
            ultimate_parent_mappings=_empty_schema_lf(
                {
                    "counterparty_reference": pl.String,
                    "ultimate_parent_reference": pl.String,
                    "hierarchy_depth": pl.Int32,
                }
            ),
            rating_inheritance=_make_rating_inheritance(counterparty_reference),
        ),
        lending_group_totals=_empty_schema_lf(
            {
                "lending_group_reference": pl.String,
                "total_exposure": pl.Float64,
            }
        ),
        model_permissions=_make_model_permissions(),
        hierarchy_errors=[],
    )


# ---------------------------------------------------------------------------
# Named scenario bundles
# ---------------------------------------------------------------------------


def make_large_fse_bundle() -> ResolvedHierarchyBundle:
    """(A) FSE, total_assets = GBP 100bn -> large under both regimes."""
    return _make_bundle(
        _make_fse_cp(CP_LARGE_FSE, total_assets=ASSETS_LARGE_BOTH, is_financial_sector_entity=True),
        CP_LARGE_FSE,
    )


def make_mid_fse_bundle() -> ResolvedHierarchyBundle:
    """(B) FSE, total_assets = GBP 65bn -> large under CRR only (< B31 79bn)."""
    return _make_bundle(
        _make_fse_cp(CP_MID_FSE, total_assets=ASSETS_MID, is_financial_sector_entity=True),
        CP_MID_FSE,
    )


def make_small_fse_bundle() -> ResolvedHierarchyBundle:
    """(C) FSE, total_assets = GBP 50bn -> below both thresholds."""
    return _make_bundle(
        _make_fse_cp(CP_SMALL_FSE, total_assets=ASSETS_SMALL, is_financial_sector_entity=True),
        CP_SMALL_FSE,
    )


def make_null_assets_fse_bundle() -> ResolvedHierarchyBundle:
    """(D) FSE, total_assets = null -> undetermined; no scalar, CLS009 fires."""
    return _make_bundle(
        _make_fse_cp(CP_NULL_FSE, total_assets=None, is_financial_sector_entity=True),
        CP_NULL_FSE,
    )


def make_non_fse_large_bundle() -> ResolvedHierarchyBundle:
    """(E) NON-FSE, total_assets = GBP 100bn -> size alone does not qualify."""
    return _make_bundle(
        _make_fse_cp(
            CP_NON_FSE_LARGE, total_assets=ASSETS_LARGE_BOTH, is_financial_sector_entity=False
        ),
        CP_NON_FSE_LARGE,
    )


def make_override_bundle() -> ResolvedHierarchyBundle:
    """(F) NON-FSE, sub-threshold, apply_fi_scalar=True -> authoritative override."""
    return _make_bundle(
        _make_fse_cp(
            CP_OVERRIDE,
            total_assets=ASSETS_SMALL,
            is_financial_sector_entity=False,
            apply_fi_scalar=True,
        ),
        CP_OVERRIDE,
    )
