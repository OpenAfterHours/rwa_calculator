"""
P1.126 fixtures: classifier null-revenue conservative-large default warning (CLS008).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (classifier.py)

Key responsibilities:
- Provide three in-memory LazyFrame scenario builders for the classifier
  null-revenue conservative-large default warning test.
- All three scenarios share a common corporate exposure and model permission
  configuration.  The variation is in annual_revenue and the calculation regime:

    (A) B31 + CP_NULL_REV (annual_revenue=None)   → CLS008 warning + approach="firb"
    (B) B31 + CP_LARGE   (annual_revenue=500_000_000) → no warning, approach="firb"
    (C) CRR + CP_NULL_REV (annual_revenue=None)   → no warning, approach="airb"

Why Python builder, not parquet:
    This fixture controls null vs. non-null Float64 values and the exact schema
    of the annual_revenue column.  A Python builder provides direct control over
    Polars LazyFrame schemas and makes null behaviour explicit, matching the
    analogous P1.125 CLS007 pattern.

Scenario constants:
    COUNTERPARTY_REF_NULL_REV = "CP_NULL_REV_P1126"
    COUNTERPARTY_REF_LARGE    = "CP_LARGE_P1126"
    LOAN_REF                  = "LN_CORP_P1126"
    MODEL_ID                  = "M_CORP_AIRB"

    annual_revenue (null-rev)  = None  (null Float64 — triggers conservative-large logic)
    annual_revenue (large)     = 500_000_000.0  (GBP 500m — provably above 440m threshold)
    entity_type                = "corporate"
    drawn_amount               = 1_000_000.0 GBP
    pd                         = 0.005
    lgd                        = 0.30
    cqs                        = 4

The CLS008 warning fires under Basel 3.1 when annual_revenue is null for a corporate
exposure that has A-IRB permission.  The engine conservatively assumes the counterparty
may qualify as a large corporate (>GBP 440m) and forces F-IRB, emitting CLS008 to
signal that the restriction was applied without confirming revenue data.

Under CRR (Scenario C) the large-corp A-IRB restriction (Art. 147A(1)(d)) does not
apply, so null revenue is irrelevant and approach remains "airb".

References:
    - PRA PS1/26 Art. 147A(1)(d): Large corporate revenue GBP 440m → F-IRB only
    - src/rwa_calc/engine/classifier.py: _is_large_corp expression, _resolve_approach()
    - tests/fixtures/p1_125/p1_125.py: analogous CLS007 pattern
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import ResolvedHierarchyBundle
from tests.fixtures.resolved_bundle import make_counterparty_lookup, make_resolved_bundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF_NULL_REV: str = "CP_NULL_REV_P1126"
COUNTERPARTY_REF_LARGE: str = "CP_LARGE_P1126"
LOAN_REF: str = "LN_CORP_P1126"
MODEL_ID: str = "M_CORP_AIRB"

VALUE_DATE: date = date(2027, 1, 15)
MATURITY_DATE: date = date(2030, 1, 15)  # ~3 years

# GBP 500m — provably above the Art. 147A(1)(d) GBP 440m large-corp threshold.
# Used in Scenario B where revenue data is present and explicit.
LARGE_ANNUAL_REVENUE: float = 500_000_000.0

DRAWN_AMOUNT: float = 1_000_000.0


# ---------------------------------------------------------------------------
# Counterparty builders — null-revenue vs. explicit-large variants
# ---------------------------------------------------------------------------


def make_counterparty_null_revenue(
    counterparty_reference: str = COUNTERPARTY_REF_NULL_REV,
) -> pl.LazyFrame:
    """
    Return a corporate counterparty LazyFrame with annual_revenue=null.

    The annual_revenue column is PRESENT in the schema but carries a null value.
    Under Basel 3.1, null revenue for a corporate with A-IRB permission triggers
    the CLS008 warning: the engine cannot confirm the counterparty is below the
    GBP 440m large-corp threshold, so it conservatively applies the F-IRB
    restriction (Art. 147A(1)(d)).

    Scenarios (A) and (C) use this builder.  The CQS of 4 is provided so the
    classifier has SA fallback data available (not strictly required for the
    CLS008 path but matches the scenario proposal).

    Args:
        counterparty_reference: Override the counterparty ID (default CP_NULL_REV_P1126).
    """
    # total_assets is None so the SME assets-fallback (CRR Art. 4(1)(128D))
    # cannot resolve the size question — both turnover and assets are missing,
    # preserving the original CLS008 scenario where the conservative large-corp
    # default fires under PS1/26 Art. 147A(1)(d).
    return pl.LazyFrame(
        {
            "counterparty_reference": [counterparty_reference],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [None],
            "total_assets": [None],
            "default_status": [False],
            "apply_fi_scalar": [False],
            "is_financial_sector_entity": [False],
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


def make_counterparty_large_revenue(
    counterparty_reference: str = COUNTERPARTY_REF_LARGE,
) -> pl.LazyFrame:
    """
    Return a corporate counterparty LazyFrame with annual_revenue=GBP 500m.

    The annual_revenue column is present and explicitly above the GBP 440m
    Art. 147A(1)(d) large-corp threshold.  Under Basel 3.1 this triggers the
    normal large-corp F-IRB restriction without emitting CLS008 — no ambiguity
    about the revenue figure.

    Scenario (B) uses this builder.

    Args:
        counterparty_reference: Override the counterparty ID (default CP_LARGE_P1126).
    """
    return pl.LazyFrame(
        {
            "counterparty_reference": [counterparty_reference],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [LARGE_ANNUAL_REVENUE],
            "total_assets": [10_000_000.0],
            "default_status": [False],
            "apply_fi_scalar": [False],
            "is_financial_sector_entity": [False],
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
# Exposure builder — parametrised by counterparty reference
# ---------------------------------------------------------------------------


def make_corporate_exposure(
    counterparty_reference: str = COUNTERPARTY_REF_NULL_REV,
) -> pl.LazyFrame:
    """
    Return a single corporate loan exposure for P1.126.

    The exposure is a GBP 1m drawn loan with:
    - exposure_type="loan", seniority="senior"
    - model_id=M_CORP_AIRB (pre-propagated, bypassing the hierarchy resolver)
    - lgd=0.30 (per scenario proposal; within normal corporate FIRB LGD range)
    - lending_group columns populated so _make_bundle() does not need to add them.

    The model_id is included directly on the exposure frame because the fixture
    bypasses the HierarchyResolver stage (which normally propagates
    internal_model_id → model_id from rating_inheritance).  This matches the
    approach used in P1.125 where model_id is surfaced via rating_inheritance
    rather than the exposure frame, but here we include it explicitly so the
    classifier's _apply_model_permissions() method can join on it.

    Args:
        counterparty_reference: Which counterparty this exposure belongs to.
    """
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


# ---------------------------------------------------------------------------
# Model permissions builder — grants both AIRB and FIRB for corporate
# ---------------------------------------------------------------------------


def make_corporate_airb_model_permissions() -> pl.LazyFrame:
    """
    Return model permissions granting AIRB and FIRB for corporate exposures.

    Two rows for M_CORP_AIRB: one granting advanced_irb and one granting
    foundation_irb for the corporate exposure class.  This matches the proposal
    (M_CORP_AIRB grants both AIRB and FIRB for corporate) and gives the classifier
    an A-IRB grant to potentially block under the large-corp restriction.

    The permissions are unconditional (no country_codes, no excluded_book_codes).
    """
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


# ---------------------------------------------------------------------------
# Rating inheritance builder — parametrised by counterparty reference
# ---------------------------------------------------------------------------


def make_rating_inheritance(
    counterparty_reference: str = COUNTERPARTY_REF_NULL_REV,
) -> pl.LazyFrame:
    """
    Return a rating_inheritance LazyFrame for P1.126.

    Provides internal PD of 0.005 (0.5%), CQS=4 (external SA rating), and
    references MODEL_ID so the classifier can attempt A-IRB routing and then
    evaluate the large-corp restriction.

    Args:
        counterparty_reference: The counterparty this rating belongs to.
    """
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


# ---------------------------------------------------------------------------
# ResolvedHierarchyBundle factory
# ---------------------------------------------------------------------------


def _enrich_counterparty(counterparties: pl.LazyFrame) -> pl.LazyFrame:
    """Add hierarchy columns required by CounterpartyLookup if absent."""
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


def make_bundle(
    counterparties: pl.LazyFrame,
    counterparty_reference: str,
) -> ResolvedHierarchyBundle:
    """
    Build a ResolvedHierarchyBundle from the supplied counterparty LazyFrame.

    The exposure, model permissions, and rating inheritance are parametrised by
    counterparty_reference to match the counterparty row.

    Args:
        counterparties: Output of one of the make_counterparty_*() builders.
            The annual_revenue value (null vs. non-null) determines whether CLS008 fires.
        counterparty_reference: The counterparty_reference value used in this scenario.
            Must match the reference in the counterparties LazyFrame.

    Returns:
        A ResolvedHierarchyBundle ready to pass to ExposureClassifier.classify().
    """
    enriched_cp = _enrich_counterparty(counterparties)

    return make_resolved_bundle(
        exposures=make_corporate_exposure(counterparty_reference),
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
            rating_inheritance=make_rating_inheritance(counterparty_reference),
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
# Named scenario bundles — public API used by the test-writer
# ---------------------------------------------------------------------------


def make_scenario_a_bundle() -> ResolvedHierarchyBundle:
    """
    Scenario (A): B31 + CP_NULL_REV (annual_revenue=None) → CLS008 + approach="firb".

    The test-writer should pass this bundle with CalculationConfig.basel_3_1()
    and assert that:
    - Exactly one CLS008 warning appears in classification_errors.
    - The exposure is classified with approach="firb" (conservative large-corp default).

    The null annual_revenue prevents the classifier from confirming whether the
    counterparty is above or below the GBP 440m large-corp threshold.  Under B31
    Art. 147A(1)(d) the conservative assumption is that it IS large corp, blocking
    A-IRB and emitting CLS008.
    """
    return make_bundle(
        make_counterparty_null_revenue(COUNTERPARTY_REF_NULL_REV),
        COUNTERPARTY_REF_NULL_REV,
    )


def make_scenario_b_bundle() -> ResolvedHierarchyBundle:
    """
    Scenario (B): B31 + CP_LARGE (annual_revenue=GBP 500m) → no CLS008, approach="firb".

    The test-writer should pass this bundle with CalculationConfig.basel_3_1()
    and assert that:
    - No CLS008 warning appears in classification_errors.
    - The exposure is classified with approach="firb" (confirmed large corp).

    With an explicit GBP 500m revenue the classifier can determine that the
    counterparty is provably above the 440m threshold.  No ambiguity → no CLS008.
    The large-corp restriction still blocks A-IRB, so approach is "firb".
    """
    return make_bundle(
        make_counterparty_large_revenue(COUNTERPARTY_REF_LARGE),
        COUNTERPARTY_REF_LARGE,
    )


def make_scenario_c_bundle() -> ResolvedHierarchyBundle:
    """
    Scenario (C): CRR + CP_NULL_REV (annual_revenue=None) → no CLS008, approach="airb".

    The test-writer should pass this bundle with CalculationConfig.crr() and
    assert that:
    - No CLS008 warning appears — the CLS008 check is B31-only (Art. 147A is
      a Basel 3.1 restriction; CRR has no equivalent large-corp A-IRB block).
    - The exposure is classified with approach="airb" (A-IRB remains permitted
      under CRR regardless of revenue level).

    Same counterparty data as Scenario A; only the calculation config changes.
    """
    return make_bundle(
        make_counterparty_null_revenue(COUNTERPARTY_REF_NULL_REV),
        COUNTERPARTY_REF_NULL_REV,
    )
