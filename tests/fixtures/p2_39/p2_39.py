"""
P2.39 fixtures: equity SA-only enforcement — Art. 147A classifier guard.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (classifier.py)

Key responsibilities:
- Provide two named scenario bundles for the classifier equity SA-only gate test:

    (A) B31 config with misconfigured IRBPermissions granting AIRB to EQUITY.
        Expected classifier output:
            exposure_class     = "equity"
            approach_permitted = "standardised"  (classifier enforces SA-only)
            approach_applied   = "standardised"

    (B) CRR control row — same counterparty and equity exposure, CRR config.
        Expected classifier output:
            exposure_class     = "equity"
            approach_permitted = "standardised"  (equity is SA-only under both frameworks)
            approach_applied   = "standardised"

Why Python builder, not parquet:
    This fixture exercises the classifier's IRBPermissions guard that must
    reject AIRB for equity regardless of what IRBPermissions says.  The
    critical assertion is on the classifier-output columns (approach_permitted,
    approach_applied), not on RWA arithmetic.  A Python builder provides direct
    control over the ResolvedHierarchyBundle schema — the same pattern used by
    the analogous P1.125 (CLS007) and P1.126 (CLS008) classifier fixtures.

Scenario design:
    The counterparty is an equity-type entity (entity_type="equity") with
    annual_revenue=50_000_000 to confirm it is below any Art. 147A corporate
    revenue threshold (the large-corp GBP 440m threshold applies only to
    corporate entity types, not equity).  is_financial_sector_entity=False
    avoids the FSE-scalar branch.

    The equity exposure (EX_EQ_147A_H) carries exposure_class="equity",
    exposure_class_irb="equity", product_type="equity_holding", ead=1_000_000
    GBP, lgd=0.45, and a 5-year maturity.  It is placed on the MAIN
    ``exposures`` LazyFrame (bundle.exposures), NOT on the equity_exposures
    field.  This routes the row through _build_approach_expr()
    (classifier.py lines 1570-1652) so the equity SA-only guard can be
    exercised.  The equity_exposures= field is set to None.

    A companion corporate exposure (LN_CORP_P239) is concatenated with the
    equity row on bundle.exposures so that the IRBPermissions map for the
    CORPORATE class has an exposure to bind to.

    The IRBPermissions config passed in the test (not in this fixture) is
    deliberately misconfigured:
        {ExposureClass.EQUITY: {ApproachType.SA, ApproachType.AIRB}, ...}
    The correct engine behaviour is to ignore the AIRB grant for equity
    and return approach="standardised" (or ApproachType.EQUITY.value).

References:
    - Basel 3.1 CRE60 / PRA PS1/26 Art. 155: equity exposures are SA-only
      (IRB approaches for equity withdrawn from 1 Jan 2027).
    - CRR Art. 155: simple risk weight method and PD/LGD method for equity
      (permitted under CRR — test uses CRR as a control, not to exercise IRB).
    - docs/specifications/crr/sa-risk-weights.md: Equity section.
    - src/rwa_calc/engine/classifier.py: _build_approach_expr() (lines 1570-1652).

Usage:
    uv run python tests/fixtures/p2_39/p2_39.py
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import CounterpartyLookup, ResolvedHierarchyBundle
from tests.fixtures.resolved_bundle import make_resolved_bundle

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

COUNTERPARTY_REF: str = "CP_EQ_147A_H"
EQUITY_EXPOSURE_REF: str = "EX_EQ_147A_H"
LOAN_REF: str = "LN_CORP_P239"

VALUE_DATE: date = date(2027, 1, 15)
MATURITY_DATE: date = date(2032, 1, 15)  # ~5 years

# Revenue set at GBP 50m — well below any revenue threshold; the large-corp
# Art. 147A(1)(d) restriction applies to entity_type="corporate" only, but
# we set a low revenue on the counterparty for completeness.
ANNUAL_REVENUE: float = 50_000_000.0

EQUITY_EAD: float = 1_000_000.0
DRAWN_AMOUNT: float = 500_000.0  # companion corporate loan

# ---------------------------------------------------------------------------
# Expected outputs — used by test-writer for assertions
# ---------------------------------------------------------------------------

#: Both B31 and CRR runs: equity is always SA-only.
EXPECTED_EXPOSURE_CLASS: str = "equity"
EXPECTED_APPROACH: str = "standardised"


# ---------------------------------------------------------------------------
# Counterparty builder
# ---------------------------------------------------------------------------


def make_counterparty() -> pl.LazyFrame:
    """
    Return the P2.39 counterparty as a single-row LazyFrame.

    entity_type="equity": maps to ExposureClass.EQUITY via
        ENTITY_TYPE_TO_SA_CLASS / ENTITY_TYPE_TO_IRB_CLASS so the classifier
        derives exposure_class="equity" from this counterparty.
    annual_revenue=50_000_000: well below any revenue threshold.
    is_financial_sector_entity=False: avoids FSE 1.25x scalar branch.
    default_status=False: standard non-defaulted path.
    """
    return pl.LazyFrame(
        {
            "counterparty_reference": [COUNTERPARTY_REF],
            "entity_type": ["equity"],
            "country_code": ["GB"],
            "annual_revenue": [ANNUAL_REVENUE],
            "total_assets": [30_000_000.0],
            "default_status": [False],
            "apply_fi_scalar": [False],
            "is_financial_sector_entity": [False],
            "is_managed_as_retail": [False],
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
            "is_managed_as_retail": pl.Boolean,
        },
    )


# ---------------------------------------------------------------------------
# Equity exposure builder — EXPOSURE_SCHEMA path (main exposures LazyFrame)
# ---------------------------------------------------------------------------


def make_equity_exposure_row() -> pl.LazyFrame:
    """
    Return the P2.39 equity exposure as a single-row EXPOSURE_SCHEMA LazyFrame.

    This row sits on the MAIN bundle.exposures LazyFrame (alongside the
    companion corporate loan), NOT on bundle.equity_exposures.  This routes
    EX_EQ_147A_H through the standard classifier path — specifically through
    _build_approach_expr() — so the equity SA-only guard can be exercised.

    Key columns:
    - exposure_class="equity", exposure_class_irb="equity": pre-populated to
      document the expected classifier assignment; the classifier derives the
      same values from counterparty entity_type="equity" via
      ENTITY_TYPE_TO_SA_CLASS / ENTITY_TYPE_TO_IRB_CLASS.
    - product_type="equity_holding": marks this as an equity holding.
    - drawn_amount=1_000_000 GBP: EAD source (equity uses drawn_amount as EAD
      in the absence of a separate equity_exposures fair_value column).
    - lgd=0.45: present on the row; ignored by the SA equity path but
      relevant if the IRB path were accidentally exercised.
    - maturity_date=2032-01-15: ~5y maturity from value_date.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [EQUITY_EXPOSURE_REF],
            "exposure_type": ["loan"],
            "product_type": ["equity_holding"],
            "book_code": ["EQ"],
            "counterparty_reference": [COUNTERPARTY_REF],
            "value_date": [VALUE_DATE],
            "maturity_date": [MATURITY_DATE],
            "currency": ["GBP"],
            "drawn_amount": [EQUITY_EAD],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "exposure_class": ["equity"],
            "exposure_class_irb": ["equity"],
            "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [EQUITY_EAD],
            "residential_collateral_value": [0.0],
            "exposure_for_retail_threshold": [EQUITY_EAD],
            "lending_group_adjusted_exposure": [EQUITY_EAD],
            "model_id": [None],
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
            "exposure_class": pl.String,
            "exposure_class_irb": pl.String,
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
# Companion corporate exposure (keeps IRBPermissions CORPORATE map active)
# ---------------------------------------------------------------------------


def make_corporate_exposure() -> pl.LazyFrame:
    """
    Return a minimal corporate loan exposure for P2.39.

    This companion exposure ensures the bundle's main exposures LazyFrame is
    non-empty and that the CORPORATE class in the IRBPermissions map has a
    binding exposure.  It is NOT the exposure under assertion.

    product_type="TERM_LOAN", drawn_amount=500_000 GBP, seniority="senior".
    No model_id: falls back to SA for the corporate row (irrelevant to the
    equity gate test).
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
            "model_id": [None],
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
# Rating inheritance builder
# ---------------------------------------------------------------------------


def make_rating_inheritance() -> pl.LazyFrame:
    """
    Return a rating_inheritance LazyFrame for CP_EQ_147A_H.

    internal_rating="BBB" maps to CQS 3 per standard ECRA table.
    pd=0.02: internal PD for the equity counterparty.  This makes
    has_internal_rating=True in the classifier, which is required for
    airb_expr to evaluate True when IRBPermissions mistakenly grants AIRB
    to equity — the scenario under test.

    No internal_model_id: the equity gate test exercises org-wide
    IRBPermissions (config-side), not model-level permissions.
    """
    return pl.LazyFrame(
        {
            "counterparty_reference": [COUNTERPARTY_REF],
            "internal_pd": [0.02],
            "internal_model_id": [None],
            "external_cqs": [3],
            "cqs": [3],
            "pd": [0.02],
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
# Internal helpers
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


# ---------------------------------------------------------------------------
# Bundle factory — shared by both scenario variants
# ---------------------------------------------------------------------------


def make_bundle() -> ResolvedHierarchyBundle:
    """
    Build a ResolvedHierarchyBundle for the P2.39 equity SA-only gate test.

    The bundle contains:
    - One counterparty: CP_EQ_147A_H (entity_type="equity", GB,
        annual_revenue=50m).
    - Two exposures on the MAIN exposures LazyFrame (bundle.exposures):
        - EX_EQ_147A_H (equity exposure, exposure_class="equity",
            ead=1m GBP, lgd=0.45, 5y maturity).
        - LN_CORP_P239 (corporate companion loan, keeps exposures non-empty
            and the CORPORATE IRBPermissions binding active).
    - equity_exposures=None: the equity row is on the standard path.
    - No model permissions on the bundle (model-level permissions are absent;
        the test config's IRBPermissions carries the misconfigured AIRB grant).

    Both scenario variants (A: B31, B: CRR) use the same bundle — the only
    difference is the CalculationConfig passed by the test-writer.

    Returns:
        ResolvedHierarchyBundle ready to pass to ExposureClassifier.classify().
    """
    enriched_cp = _enrich_counterparty(make_counterparty())

    # Concatenate equity row and companion corporate loan on the main exposures
    # frame.  The equity row has additional pre-populated exposure_class /
    # exposure_class_irb columns; pl.concat with how="diagonal_relaxed" fills
    # the missing columns on the corporate row with null.
    combined_exposures = pl.concat(
        [make_equity_exposure_row(), make_corporate_exposure()],
        how="diagonal_relaxed",
    )

    return make_resolved_bundle(
        exposures=combined_exposures,
        counterparty_lookup=CounterpartyLookup(
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
        equity_exposures=None,
        model_permissions=None,
        hierarchy_errors=[],
    )


# ---------------------------------------------------------------------------
# Named scenario bundles — public API for test-writer
# ---------------------------------------------------------------------------


def make_scenario_b31_bundle() -> ResolvedHierarchyBundle:
    """
    Scenario A — Basel 3.1 with misconfigured IRBPermissions granting AIRB to equity.

    The test-writer should pass this bundle with:
        CalculationConfig.basel_3_1(
            irb_permissions=IRBPermissions(permissions={
                ExposureClass.EQUITY: {ApproachType.SA, ApproachType.AIRB},
                ExposureClass.CORPORATE: {ApproachType.SA, ApproachType.FIRB, ApproachType.AIRB},
                ...  # other classes per full_irb_b31 defaults
            })
        )

    Expected assertions on EX_EQ_147A_H:
    - exposure_class="equity"
    - approach NOT "advanced_irb" (the misconfigured AIRB grant must be ignored)
    - approach == "standardised" or ApproachType.EQUITY (equity SA-only path)

    Under PRA PS1/26 (Basel 3.1), Art. 155 IRB equity approaches are withdrawn.
    The classifier must enforce SA-only for equity regardless of IRBPermissions.

    Returns:
        ResolvedHierarchyBundle with equity exposure on main exposures LazyFrame.
    """
    return make_bundle()


def make_scenario_crr_bundle() -> ResolvedHierarchyBundle:
    """
    Scenario B — CRR control row.

    The test-writer should pass this bundle with CalculationConfig.crr()
    and assert that equity is still classified as SA-only.

    Under CRR, Art. 155 permits IRB simple risk weight and PD/LGD methods for
    equity.  The control assertion verifies that under CRR the classifier
    routes equity to the EQUITY approach (SA equity RW logic), not AIRB, when
    equity IRB is not explicitly configured in the engine's default CRR
    permissions.

    Returns:
        ResolvedHierarchyBundle with equity exposure on main exposures LazyFrame.
    """
    return make_bundle()
