"""
P1.125 fixtures: classifier FSE-column-missing warning (CLS007).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (classifier.py)

Key responsibilities:
- Provide three in-memory LazyFrame scenario builders for the classifier
  FSE-column-absent warning test.
- All three scenarios share a single corporate counterparty and a single
  corporate loan exposure.  The only variation is:
    (A) B31 + counterparty schema OMITS is_financial_sector_entity  → CLS007
    (B) B31 + counterparty schema INCLUDES is_financial_sector_entity → no CLS007
    (C) CRR + counterparty schema OMITS is_financial_sector_entity   → no CLS007

Why Python builder, not parquet:
    Parquet round-trips preserve all declared columns.  When `is_financial_sector_entity`
    is optional and absent from the input dict, most writers coerce it to null rather
    than omitting the column from the file schema.  The CLS007 warning fires only when
    `"is_financial_sector_entity" not in counterparties.collect_schema().names()` —
    i.e. the column must be wholly absent, not merely null-valued.  A Python builder
    can construct a LazyFrame with a controlled schema that omits the column, exactly
    as `test_art123a_retail_criteria.py` does for `is_managed_as_retail` / CLS005.

Scenario constants:
    COUNTERPARTY_REF = "CP_CORP_FSE_P1125"
    LOAN_REF         = "LN_CORP_FSE_P1125"
    MODEL_ID         = "CORP_AIRB_P1125"

    annual_revenue   = 5_000_000  (GBP 5m — well below Art. 147A(1)(d) GBP 440m
                                   large-corp threshold; prevents that restriction
                                   from firing alongside CLS007)
    entity_type      = "corporate"
    drawn_amount     = 1_000_000 GBP

References:
    - PRA PS1/26 Art. 147A(1)(e): FSE restriction to F-IRB (Basel 3.1 only)
    - src/rwa_calc/engine/classifier.py line ~427: FSE column propagation guard
    - tests/unit/test_art123a_retail_criteria.py: analogous CLS005 pattern
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import ResolvedHierarchyBundle
from tests.fixtures.resolved_bundle import make_counterparty_lookup, make_resolved_bundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF: str = "CP_CORP_FSE_P1125"
LOAN_REF: str = "LN_CORP_FSE_P1125"
MODEL_ID: str = "CORP_AIRB_P1125"

VALUE_DATE: date = date(2027, 1, 15)
MATURITY_DATE: date = date(2030, 1, 15)  # ~3 years

# annual_revenue=5_000_000 GBP — well below Art. 147A(1)(d) GBP 440m threshold.
# Keeps the large-corp A-IRB restriction from firing alongside CLS007.
ANNUAL_REVENUE: float = 5_000_000.0

DRAWN_AMOUNT: float = 1_000_000.0


# ---------------------------------------------------------------------------
# Counterparty builders — three controlled schema variants
# ---------------------------------------------------------------------------


def make_counterparty_without_fse_column() -> pl.LazyFrame:
    """
    Return a corporate counterparty LazyFrame with is_financial_sector_entity absent.

    Scenarios (A) and (C) use this builder.  The column is not in the LazyFrame
    schema at all — this is what triggers the CLS007 warning under Basel 3.1.
    """
    return pl.LazyFrame(
        {
            "counterparty_reference": [COUNTERPARTY_REF],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [ANNUAL_REVENUE],
            "total_assets": [10_000_000.0],
            "default_status": [False],
            "apply_fi_scalar": [False],
            # is_financial_sector_entity intentionally omitted — column must be absent
        },
        schema={
            "counterparty_reference": pl.String,
            "entity_type": pl.String,
            "country_code": pl.String,
            "annual_revenue": pl.Float64,
            "total_assets": pl.Float64,
            "default_status": pl.Boolean,
            "apply_fi_scalar": pl.Boolean,
        },
    )


def make_counterparty_with_fse_column(
    is_financial_sector_entity: bool | None = False,
) -> pl.LazyFrame:
    """
    Return a corporate counterparty LazyFrame with is_financial_sector_entity present.

    Scenario (B) uses this builder.  The column EXISTS in the schema (value may be
    False, True, or None) — no CLS007 warning should fire under Basel 3.1.

    Args:
        is_financial_sector_entity: Value for the column.  Defaults to False (non-FSE).
            Pass None to test that a null-valued-but-present column also suppresses CLS007.
    """
    return pl.LazyFrame(
        {
            "counterparty_reference": [COUNTERPARTY_REF],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [ANNUAL_REVENUE],
            "total_assets": [10_000_000.0],
            "default_status": [False],
            "apply_fi_scalar": [False],
            "is_financial_sector_entity": [is_financial_sector_entity],
        },
        schema={
            "counterparty_reference": pl.String,
            "entity_type": pl.String,
            "country_code": pl.String,
            "annual_revenue": pl.Float64,
            "total_assets": pl.Float64,
            "default_status": pl.Boolean,
            "apply_fi_scalar": pl.Boolean,
            "is_financial_sector_entity": pl.Boolean,
        },
    )


# ---------------------------------------------------------------------------
# Exposure builder — shared across all three scenarios
# ---------------------------------------------------------------------------


def make_corporate_exposure() -> pl.LazyFrame:
    """
    Return a single corporate loan exposure for P1.125.

    The exposure is a simple GBP 1m drawn loan with:
    - exposure_type="loan", seniority="senior"
    - An internal PD rating (lgd=0.45, pd implicitly sourced via model_id in
      rating_inheritance — the classifier only needs to confirm approach routing).
    - lending_group_total_exposure and lending_group_adjusted_exposure included so
      _make_bundle() does not need to add them separately.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [LOAN_REF],
            "exposure_type": ["loan"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": [COUNTERPARTY_REF],
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
        },
    )


# ---------------------------------------------------------------------------
# A-IRB model permissions builder (shared across all three scenarios)
# ---------------------------------------------------------------------------


def make_corporate_airb_model_permissions() -> pl.LazyFrame:
    """
    Return model permissions granting A-IRB for corporate exposures.

    A single row grants advanced_irb for the CORP_AIRB_P1125 model across
    the corporate exposure class.  This permission is referenced by the rating
    returned from make_rating_inheritance().

    The permission is unconditional (no country_codes, no excluded_book_codes),
    ensuring the classifier can see an A-IRB grant and apply the FSE restriction
    check (Art. 147A(1)(e)) — which is the trigger for the CLS007 warning.
    """
    return pl.LazyFrame(
        {
            "model_id": [MODEL_ID],
            "exposure_class": ["corporate"],
            "approach": ["advanced_irb"],
            "country_codes": [None],
            "excluded_book_codes": [None],
        },
        schema={
            "model_id": pl.String,
            "exposure_class": pl.String,
            "approach": pl.String,
            "country_codes": pl.String,
            "excluded_book_codes": pl.String,
        },
    )


# ---------------------------------------------------------------------------
# Rating inheritance builder (shared across all three scenarios)
# ---------------------------------------------------------------------------


def make_rating_inheritance() -> pl.LazyFrame:
    """
    Return a rating_inheritance LazyFrame for the P1.125 counterparty.

    Provides an internal PD of 0.005 (0.5%) and references MODEL_ID so the
    classifier can attempt A-IRB routing and then evaluate the FSE restriction.
    """
    return pl.LazyFrame(
        {
            "counterparty_reference": [COUNTERPARTY_REF],
            "internal_pd": [0.005],
            "internal_model_id": [MODEL_ID],
            "external_cqs": [None],
            "cqs": [None],
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


# ---------------------------------------------------------------------------
# ResolvedHierarchyBundle factory — one per scenario
# ---------------------------------------------------------------------------


def _enrich_counterparty(counterparties: pl.LazyFrame) -> pl.LazyFrame:
    """Add hierarchy columns required by CounterpartyLookup."""
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
    if cols:
        return counterparties.with_columns(cols)
    return counterparties


def _empty_schema_lf(schema: dict[str, pl.PolarsDataType]) -> pl.LazyFrame:
    """Return an empty LazyFrame with the given schema."""
    return pl.LazyFrame(schema=schema)


def make_bundle(counterparties: pl.LazyFrame) -> ResolvedHierarchyBundle:
    """
    Build a ResolvedHierarchyBundle from the supplied counterparty LazyFrame.

    The exposure, model permissions, and rating inheritance are fixed (shared
    across all three scenarios); only the counterparty LazyFrame varies.

    Args:
        counterparties: Output of one of the make_counterparty_*() builders.
            The column schema of this frame determines whether CLS007 fires.

    Returns:
        A ResolvedHierarchyBundle ready to pass to ExposureClassifier.classify().
    """
    enriched_cp = _enrich_counterparty(counterparties)

    return make_resolved_bundle(
        exposures=make_corporate_exposure(),
        counterparty_lookup=make_counterparty_lookup(
            counterparties=enriched_cp,
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
            rating_inheritance=make_rating_inheritance(),
        ),
        lending_group_totals=_empty_schema_lf(
            {
                "lending_group_reference": pl.String,
                "total_exposure": pl.Float64,
            }
        ),
        model_permissions=make_corporate_airb_model_permissions(),
        hierarchy_errors=[],
    )


# ---------------------------------------------------------------------------
# Named scenario bundles — convenience aliases used by the test-writer
# ---------------------------------------------------------------------------


def make_scenario_a_bundle() -> ResolvedHierarchyBundle:
    """
    Scenario (A): B31 + counterparty omits is_financial_sector_entity → CLS007.

    The test-writer should pass this bundle with CalculationConfig.basel_3_1()
    and assert that exactly one CLS007 warning appears in classification_errors.
    """
    return make_bundle(make_counterparty_without_fse_column())


def make_scenario_b_bundle() -> ResolvedHierarchyBundle:
    """
    Scenario (B): B31 + counterparty includes is_financial_sector_entity → no CLS007.

    The test-writer should pass this bundle with CalculationConfig.basel_3_1()
    and assert that no CLS007 warning appears in classification_errors.

    Column is present with value False (non-FSE counterparty) by default.
    """
    return make_bundle(make_counterparty_with_fse_column(is_financial_sector_entity=False))


def make_scenario_c_bundle() -> ResolvedHierarchyBundle:
    """
    Scenario (C): CRR + counterparty omits is_financial_sector_entity → no CLS007.

    The test-writer should pass this bundle with CalculationConfig.crr() and
    assert that no CLS007 warning appears — the warning is gated to Basel 3.1.
    """
    return make_bundle(make_counterparty_without_fse_column())
