"""
SME assets-fallback fixtures: CRR Art. 4(1)(128D) / Art. 153(4) third subparagraph.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (classifier.py,
    irb/namespace.py, sa/supporting_factors.py)

Key responsibilities:
- Provide ResolvedHierarchyBundle builders that exercise the assets fallback
  in every SME classification gate when annual_revenue is null:

    (A) B31  + assets=GBP 20m  -> SME via assets, IRB correlation reduced
                                  (S=total_assets/1e6), no SF, no CLS008.
    (B) B31  + assets=GBP 500m -> NOT SME, conservatively large under Art.
                                  147A(1)(d), CLS008 fires.
    (C) B31  + assets=null     -> NOT SME, conservatively large, CLS008 fires.
    (D) CRR  + assets=GBP 20m  -> SME via assets, IRB correlation reduced,
                                  no SF (Art. 501(2)(c) turnover-only).
    (E) Turnover-only regression guard: revenue=GBP 30m, assets=GBP 25m
        under CRR -> SME via turnover, SF applies (existing behaviour).

References:
- CRR Art. 4(1)(128D) / Commission Rec 2003/361/EC Art. 2: turnover <= EUR 50m
  OR balance-sheet total <= EUR 43m defines SME.
- CRR Art. 153(4) third subparagraph: substitute total assets for total
  annual sales when sales are not a meaningful indicator of firm size.
- CRR Art. 501(2)(c): only annual turnover is taken into account for the
  Art. 501 supporting factor.
- PRA PS1/26 Art. 147A(1)(d): large corporate (revenue > GBP 440m) -> F-IRB.
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import ResolvedHierarchyBundle
from tests.fixtures.resolved_bundle import make_counterparty_lookup, make_resolved_bundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

CP_SME_BY_ASSETS: str = "CP_SME_BY_ASSETS"
CP_LARGE_BY_ASSETS: str = "CP_LARGE_BY_ASSETS"
CP_NULL_BOTH: str = "CP_NULL_BOTH"
CP_SME_BY_TURNOVER: str = "CP_SME_BY_TURNOVER"

LOAN_REF: str = "LN_CORP_SME_ASSETS"
MODEL_ID: str = "M_CORP_AIRB"

VALUE_DATE: date = date(2027, 1, 15)
MATURITY_DATE: date = date(2030, 1, 15)

DRAWN_AMOUNT: float = 1_000_000.0

# Total-assets values chosen to straddle the EUR 43m / ~GBP 37.6m
# sme_balance_sheet_threshold and the PS1/26 GBP 440m large-corp threshold.
ASSETS_SME: float = 20_000_000.0  # below EUR 43m -> SME via assets
ASSETS_LARGE: float = 500_000_000.0  # above EUR 43m -> not SME, conservatively large
TURNOVER_SME: float = 30_000_000.0  # below GBP 44m -> SME via turnover
TURNOVER_ASSETS_NON_SME: float = 25_000_000.0  # immaterial when turnover is present


# ---------------------------------------------------------------------------
# Counterparty builders
# ---------------------------------------------------------------------------

_CP_SCHEMA: dict[str, pl.PolarsDataType] = {
    "counterparty_reference": pl.String,
    "entity_type": pl.String,
    "country_code": pl.String,
    "annual_revenue": pl.Float64,
    "total_assets": pl.Float64,
    "default_status": pl.Boolean,
    "apply_fi_scalar": pl.Boolean,
    "is_financial_sector_entity": pl.Boolean,
}


def _make_corporate_cp(
    counterparty_reference: str,
    annual_revenue: float | None,
    total_assets: float | None,
) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "counterparty_reference": [counterparty_reference],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [annual_revenue],
            "total_assets": [total_assets],
            "default_status": [False],
            "apply_fi_scalar": [False],
            "is_financial_sector_entity": [False],
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
            "lgd": [0.30],
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
    # Grant both AIRB and FIRB for both corporate and corporate_sme so the
    # decision is driven by the Art. 147A(1)(d) large-corp gate rather than
    # by permission availability when the assets fallback flips a row's
    # exposure_class to CORPORATE_SME.
    return pl.LazyFrame(
        {
            "model_id": [MODEL_ID, MODEL_ID, MODEL_ID, MODEL_ID],
            "exposure_class": [
                "corporate",
                "corporate",
                "corporate_sme",
                "corporate_sme",
            ],
            "approach": [
                "advanced_irb",
                "foundation_irb",
                "advanced_irb",
                "foundation_irb",
            ],
            "country_codes": [None, None, None, None],
            "excluded_book_codes": [None, None, None, None],
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
            "internal_pd": [0.005],
            "internal_model_id": [MODEL_ID],
            "external_cqs": [4],
            "cqs": [4],
            "pd": [0.005],
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


def _empty_schema_lf(schema: dict[str, pl.PolarsDataType]) -> pl.LazyFrame:
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


def make_sme_by_assets_bundle() -> ResolvedHierarchyBundle:
    """(A) Corporate, annual_revenue=null, total_assets=GBP 20m.

    Expected: classified as CORPORATE_SME via the assets fallback, IRB
    correlation reduced with S=20.0 (EUR-m via FX), CLS008 NOT emitted (assets
    resolves the size question definitively).
    """
    return _make_bundle(
        _make_corporate_cp(CP_SME_BY_ASSETS, annual_revenue=None, total_assets=ASSETS_SME),
        CP_SME_BY_ASSETS,
    )


def make_large_by_assets_bundle() -> ResolvedHierarchyBundle:
    """(B) Corporate, annual_revenue=null, total_assets=GBP 500m.

    Expected: classified as CORPORATE (not SME — assets exceed EUR 43m),
    F-IRB forced under PS1/26 Art. 147A(1)(d), CLS008 fires (assets above
    SME threshold do not resolve whether the firm is large or mid-sized).
    """
    return _make_bundle(
        _make_corporate_cp(CP_LARGE_BY_ASSETS, annual_revenue=None, total_assets=ASSETS_LARGE),
        CP_LARGE_BY_ASSETS,
    )


def make_null_both_bundle() -> ResolvedHierarchyBundle:
    """(C) Corporate, annual_revenue=null, total_assets=null.

    Expected: classified as CORPORATE (not SME), F-IRB forced, CLS008 fires.
    Both fields null preserves the pre-fallback conservative behaviour.
    """
    return _make_bundle(
        _make_corporate_cp(CP_NULL_BOTH, annual_revenue=None, total_assets=None),
        CP_NULL_BOTH,
    )


def make_sme_by_turnover_bundle() -> ResolvedHierarchyBundle:
    """(E) Regression guard — turnover-only SME (existing pre-fallback behaviour).

    Expected: classified as CORPORATE_SME via turnover, IRB correlation
    reduced with S=30.0 (turnover), CLS008 NOT emitted. Under CRR the SA
    supporting factor applies (turnover non-null AND SME-sized).
    """
    return _make_bundle(
        _make_corporate_cp(
            CP_SME_BY_TURNOVER,
            annual_revenue=TURNOVER_SME,
            total_assets=TURNOVER_ASSETS_NON_SME,
        ),
        CP_SME_BY_TURNOVER,
    )
