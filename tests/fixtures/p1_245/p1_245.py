"""
P1.245 — group-consolidation revenue roll-up (PS1/26 Art. 147(4C)(b)(ii) w/ 147A(1)(e)).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (engine/stages/classify/attributes.py::with_group_annual_revenue +
     engine/stages/classify/approach.py large-corp F-IRB gate)

Key responsibilities:
- Provide a classify-level ``ResolvedHierarchyBundle`` builder
  (``make_classify_bundle``) whose two-counterparty lookup carries an explicit
  ``ultimate_parent_reference`` link, so the classifier's roll-up can be
  exercised WITHOUT the hierarchy stage (unit tests).
- Provide a full-pipeline ``RawDataBundle`` builder (``build_p1_245_raw_bundle``)
  whose ``org_mappings`` drive the hierarchy stage's ultimate-parent resolution,
  so the roll-up is proved end-to-end (loader -> hierarchy -> classifier -> ...).

The subclass test (Art. 147(4C)(b)(ii)): a corporate is F-IRB-only when annual
revenue > GBP 440m "taken at the highest level of consolidation". A small
subsidiary (own revenue < 440m) of a > 440m group is therefore F-IRB-only; the
same data under CRR has no such subclass, so A-IRB stays available (control).

References:
- PRA PS1/26 Art. 147(4C)(b)(ii): large-corporate revenue at highest consolidation.
- PRA PS1/26 Art. 147A(1)(e): financial/large-corporates subclass -> F-IRB only.
- IMPLEMENTATION_PLAN.md: P1.245.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.domain.enums import ApproachType
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.fixtures.resolved_bundle import make_counterparty_lookup, make_resolved_bundle

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

    from rwa_calc.contracts.bundles import RawDataBundle, ResolvedHierarchyBundle

# ---------------------------------------------------------------------------
# Scenario identity constants
# ---------------------------------------------------------------------------

MODEL_ID: str = "P1245_MODEL"

#: Subsidiary with own revenue below GBP 440m sitting under a > 440m group.
CP_SUB_LARGE: str = "P1245_SUB_LARGE"
#: Subsidiary with NULL own revenue under a > 440m group.
CP_SUB_NULL: str = "P1245_SUB_NULL"
#: Subsidiary with own revenue below GBP 440m under a small (< 440m) group.
CP_SUB_SMALL: str = "P1245_SUB_SMALL"
#: Standalone large corporate (own revenue > 440m, no parent) — the control.
CP_STANDALONE_LARGE: str = "P1245_STANDALONE_LARGE"

#: The > GBP 440m ultimate parent shared by the two large-group subsidiaries.
CP_PARENT_BIG: str = "P1245_PARENT_BIG"
#: The < GBP 440m ultimate parent of the small-group subsidiary.
CP_PARENT_SMALL: str = "P1245_PARENT_SMALL"

LOAN_SUB_LARGE: str = "P1245_LOAN_SUB_LARGE"
LOAN_SUB_NULL: str = "P1245_LOAN_SUB_NULL"
LOAN_SUB_SMALL: str = "P1245_LOAN_SUB_SMALL"
LOAN_STANDALONE: str = "P1245_LOAN_STANDALONE"

SUB_OWN_REVENUE: float = 50_000_000.0  # GBP 50m — below the 440m threshold
BIG_GROUP_REVENUE: float = 500_000_000.0  # GBP 500m — above the 440m threshold
SMALL_GROUP_REVENUE: float = 50_000_000.0  # GBP 50m — below the threshold

DRAWN_AMOUNT: float = 1_000_000.0
INTERNAL_PD: float = 0.01
OWN_LGD: float = 0.35  # modelled A-IRB LGD (below the 40% F-IRB supervisory LGD)

VALUE_DATE: date = date(2027, 1, 15)
MATURITY_DATE: date = date(2030, 1, 15)


# ---------------------------------------------------------------------------
# Classify-level bundle (unit tests — bypasses the hierarchy stage)
# ---------------------------------------------------------------------------

_CP_LOOKUP_SCHEMA: dict[str, PolarsDataType] = {
    "counterparty_reference": pl.String,
    "entity_type": pl.String,
    "country_code": pl.String,
    "annual_revenue": pl.Float64,
    "total_assets": pl.Float64,
    "default_status": pl.Boolean,
    "apply_fi_scalar": pl.Boolean,
    "is_financial_sector_entity": pl.Boolean,
    "counterparty_has_parent": pl.Boolean,
    "parent_counterparty_reference": pl.String,
    "ultimate_parent_reference": pl.String,
    "counterparty_hierarchy_depth": pl.Int32,
    "cqs": pl.Int8,
}

_EXPOSURE_SCHEMA: dict[str, PolarsDataType] = {
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
    "internal_pd": pl.Float64,
    "model_id": pl.String,
    "residential_collateral_value": pl.Float64,
    "exposure_for_retail_threshold": pl.Float64,
    "lending_group_adjusted_exposure": pl.Float64,
}


def _sub_and_parent_counterparties(
    *,
    sub_ref: str,
    sub_revenue: float | None,
    parent_ref: str | None,
    parent_revenue: float | None,
    sub_total_assets: float | None,
) -> pl.LazyFrame:
    """Two-row counterparty lookup: the subsidiary plus its ultimate parent.

    When ``parent_ref`` is None the subsidiary is a standalone corporate (its
    ``ultimate_parent_reference`` is null and only the subsidiary row is emitted).
    """
    refs = [sub_ref]
    entity = ["corporate"]
    revenue: list[float | None] = [sub_revenue]
    assets: list[float | None] = [sub_total_assets]
    has_parent = [parent_ref is not None]
    parent_col: list[str | None] = [parent_ref]
    ultimate_col: list[str | None] = [parent_ref]
    depth = [1 if parent_ref is not None else 0]

    if parent_ref is not None:
        refs.append(parent_ref)
        entity.append("corporate")
        revenue.append(parent_revenue)
        assets.append(None)
        has_parent.append(False)
        parent_col.append(None)
        ultimate_col.append(None)
        depth.append(0)

    n = len(refs)
    return pl.LazyFrame(
        {
            "counterparty_reference": refs,
            "entity_type": entity,
            "country_code": ["GB"] * n,
            "annual_revenue": revenue,
            "total_assets": assets,
            "default_status": [False] * n,
            "apply_fi_scalar": [False] * n,
            "is_financial_sector_entity": [False] * n,
            "counterparty_has_parent": has_parent,
            "parent_counterparty_reference": parent_col,
            "ultimate_parent_reference": ultimate_col,
            "counterparty_hierarchy_depth": depth,
            "cqs": [None] * n,
        },
        schema=_CP_LOOKUP_SCHEMA,
    )


def _sub_exposure(sub_ref: str) -> pl.LazyFrame:
    """One IRB-ready corporate loan on the subsidiary (PD + modelled LGD)."""
    return pl.LazyFrame(
        {
            "exposure_reference": [LOAN_SUB_LARGE],
            "exposure_type": ["loan"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": [sub_ref],
            "value_date": [VALUE_DATE],
            "maturity_date": [MATURITY_DATE],
            "currency": ["GBP"],
            "drawn_amount": [DRAWN_AMOUNT],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [OWN_LGD],
            "seniority": ["senior"],
            "internal_pd": [INTERNAL_PD],
            "model_id": [MODEL_ID],
            "residential_collateral_value": [0.0],
            "exposure_for_retail_threshold": [DRAWN_AMOUNT],
            "lending_group_adjusted_exposure": [DRAWN_AMOUNT],
        },
        schema=_EXPOSURE_SCHEMA,
    )


def _classify_model_permissions() -> pl.LazyFrame:
    """Grant corporate A-IRB AND F-IRB so only Art. 147A can force the choice."""
    return pl.LazyFrame(
        {
            "model_id": [MODEL_ID, MODEL_ID],
            "exposure_class": ["corporate", "corporate"],
            "approach": [ApproachType.AIRB.value, ApproachType.FIRB.value],
        },
        schema={
            "model_id": pl.String,
            "exposure_class": pl.String,
            "approach": pl.String,
        },
    )


def make_classify_bundle(
    *,
    sub_revenue: float | None,
    parent_revenue: float | None,
    parent_ref: str | None = CP_PARENT_BIG,
    sub_total_assets: float | None = None,
    sub_ref: str = CP_SUB_LARGE,
) -> ResolvedHierarchyBundle:
    """Return a classify-level bundle for one subsidiary + (optional) parent.

    The subsidiary carries an explicit ``ultimate_parent_reference`` so the
    classifier's ``with_group_annual_revenue`` roll-up runs without the
    hierarchy stage. ``parent_ref=None`` produces a standalone corporate.
    """
    counterparties = _sub_and_parent_counterparties(
        sub_ref=sub_ref,
        sub_revenue=sub_revenue,
        parent_ref=parent_ref,
        parent_revenue=parent_revenue,
        sub_total_assets=sub_total_assets,
    )
    return make_resolved_bundle(
        exposures=_sub_exposure(sub_ref),
        counterparty_lookup=make_counterparty_lookup(
            counterparties=counterparties,
            rating_inheritance=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "internal_pd": pl.Float64,
                    "internal_model_id": pl.String,
                    "external_cqs": pl.Int8,
                    "cqs": pl.Int8,
                    "pd": pl.Float64,
                }
            ),
        ),
        model_permissions=_classify_model_permissions(),
        lending_group_totals=pl.LazyFrame(
            schema={
                "lending_group_reference": pl.String,
                "total_exposure": pl.Float64,
            }
        ),
    )


# ---------------------------------------------------------------------------
# Full-pipeline raw bundle (acceptance twin — org_mappings drive the roll-up)
# ---------------------------------------------------------------------------

_RAW_CP_SCHEMA: dict[str, PolarsDataType] = {
    "counterparty_reference": pl.String,
    "counterparty_name": pl.String,
    "entity_type": pl.String,
    "country_code": pl.String,
    "annual_revenue": pl.Float64,
    "total_assets": pl.Float64,
    "default_status": pl.Boolean,
    "apply_fi_scalar": pl.Boolean,
    "is_managed_as_retail": pl.Boolean,
    "is_natural_person": pl.Boolean,
    "is_financial_sector_entity": pl.Boolean,
}

_RAW_LOAN_SCHEMA: dict[str, PolarsDataType] = {
    "loan_reference": pl.String,
    "counterparty_reference": pl.String,
    "product_type": pl.String,
    "book_code": pl.String,
    "currency": pl.String,
    "drawn_amount": pl.Float64,
    "lgd": pl.Float64,
    "seniority": pl.String,
    "value_date": pl.Date,
    "maturity_date": pl.Date,
}

_RAW_RATING_SCHEMA: dict[str, PolarsDataType] = {
    "rating_reference": pl.String,
    "counterparty_reference": pl.String,
    "rating_type": pl.String,
    "rating_agency": pl.String,
    "rating_value": pl.String,
    "cqs": pl.Int8,
    "pd": pl.Float64,
    "rating_date": pl.Date,
    "is_solicited": pl.Boolean,
    "model_id": pl.String,
}


def _raw_counterparty(ref: str, revenue: float | None) -> dict[str, object]:
    return {
        "counterparty_reference": ref,
        "counterparty_name": f"P1.245 {ref}",
        "entity_type": "corporate",
        "country_code": "GB",
        "annual_revenue": revenue,
        "total_assets": None,
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "is_natural_person": False,
        "is_financial_sector_entity": False,
    }


def _raw_loan(loan_ref: str, cp_ref: str) -> dict[str, object]:
    return {
        "loan_reference": loan_ref,
        "counterparty_reference": cp_ref,
        "product_type": "term_loan",
        "book_code": "MAIN",
        "currency": "GBP",
        "drawn_amount": DRAWN_AMOUNT,
        "lgd": OWN_LGD,
        "seniority": "senior",
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
    }


def _raw_rating(cp_ref: str) -> dict[str, object]:
    return {
        "rating_reference": f"RAT_{cp_ref}",
        "counterparty_reference": cp_ref,
        "rating_type": "internal",
        "rating_agency": "internal",
        "rating_value": "BB",
        "cqs": None,
        "pd": INTERNAL_PD,
        "rating_date": date(2026, 1, 1),
        "is_solicited": True,
        "model_id": MODEL_ID,
    }


def build_p1_245_raw_bundle() -> RawDataBundle:
    """Return the P1.245 RawDataBundle exercising the roll-up end-to-end.

    Four loan-bearing corporates, two revenue-carrier parents, and the
    ``org_mappings`` that the hierarchy stage resolves into ultimate parents:

    - SUB_LARGE  (own 50m) under PARENT_BIG (500m)   -> B31 F-IRB (roll-up flip)
    - SUB_NULL   (own null) under PARENT_BIG (500m)  -> B31 F-IRB (null-own case)
    - SUB_SMALL  (own 50m) under PARENT_SMALL (50m)  -> B31 A-IRB (small group)
    - STANDALONE (own 500m, no parent)               -> B31 F-IRB (own large)

    Under CRR none of these are F-IRB-restricted (no subclass), so all four are
    A-IRB — the control that proves the branch is B31-scoped.
    """
    counterparties = pl.LazyFrame(
        [
            _raw_counterparty(CP_SUB_LARGE, SUB_OWN_REVENUE),
            _raw_counterparty(CP_SUB_NULL, None),
            _raw_counterparty(CP_SUB_SMALL, SUB_OWN_REVENUE),
            _raw_counterparty(CP_STANDALONE_LARGE, BIG_GROUP_REVENUE),
            _raw_counterparty(CP_PARENT_BIG, BIG_GROUP_REVENUE),
            _raw_counterparty(CP_PARENT_SMALL, SMALL_GROUP_REVENUE),
        ],
        schema=_RAW_CP_SCHEMA,
    )
    loans = pl.LazyFrame(
        [
            _raw_loan(LOAN_SUB_LARGE, CP_SUB_LARGE),
            _raw_loan(LOAN_SUB_NULL, CP_SUB_NULL),
            _raw_loan(LOAN_SUB_SMALL, CP_SUB_SMALL),
            _raw_loan(LOAN_STANDALONE, CP_STANDALONE_LARGE),
        ],
        schema=_RAW_LOAN_SCHEMA,
    )
    ratings = pl.LazyFrame(
        [
            _raw_rating(CP_SUB_LARGE),
            _raw_rating(CP_SUB_NULL),
            _raw_rating(CP_SUB_SMALL),
            _raw_rating(CP_STANDALONE_LARGE),
        ],
        schema=_RAW_RATING_SCHEMA,
    )
    org_mappings = pl.LazyFrame(
        {
            "parent_counterparty_reference": [
                CP_PARENT_BIG,
                CP_PARENT_BIG,
                CP_PARENT_SMALL,
            ],
            "child_counterparty_reference": [
                CP_SUB_LARGE,
                CP_SUB_NULL,
                CP_SUB_SMALL,
            ],
        },
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        },
    )
    model_permissions = _classify_model_permissions()
    empty_fac_map = pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        }
    )
    return make_raw_bundle(
        facilities=None,
        loans=loans,
        counterparties=counterparties,
        facility_mappings=empty_fac_map,
        org_mappings=org_mappings,
        ratings=ratings,
        model_permissions=model_permissions,
    )
