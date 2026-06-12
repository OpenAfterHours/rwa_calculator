"""
Unit test for P1.114: null book_code must not be treated as excluded by the book-code filter.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (defect site) -> CRMProcessor

Defect (pre-fix):
    classifier.py line 1016-1018:
        book_not_excluded = pl.col("mp_excluded_book_codes").is_null() | ~(
            pl.col("mp_excluded_book_codes").str.contains(pl.col("book_code"))
        )
    When book_code is null, str.contains returns null instead of False.
    null AND-ed into permission_valid yields null, so the row falls through to SA.

Post-fix assertion:
    A null book_code is NOT in {"TRADE_FINANCE"}, therefore book_not_excluded=True,
    permission_valid=True, model_firb_permitted=True, and approach="foundation_irb".

References:
    - src/rwa_calc/engine/classifier.py (defect site)
    - CRR Art. 143: use of IRB models (scope conditions)
    - tests/unit/test_classifier.py: TestModelPermissions (pattern reference)
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.classifier import ExposureClassifier
from tests.fixtures.resolved_bundle import make_counterparty_lookup, make_resolved_bundle

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL_ID = "UK_CORP_PD_01"
_LOAN_REF = "LN_NULL_BOOK_001"
_CP_REF = "CP_NULL_GEO_001"


# ---------------------------------------------------------------------------
# Helpers (copied/adapted from tests/unit/test_classifier.py pattern)
# ---------------------------------------------------------------------------


def _make_resolved_bundle(
    exposures: pl.LazyFrame,
    counterparties: pl.LazyFrame,
    model_permissions: pl.LazyFrame | None = None,
) -> ResolvedHierarchyBundle:
    """Build a minimal ResolvedHierarchyBundle for classifier unit tests."""
    enriched_cp = counterparties.with_columns(
        [
            pl.lit(False).alias("counterparty_has_parent"),
            pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"),
            pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"),
            pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"),
            pl.lit(None).cast(pl.Int8).alias("cqs"),
        ]
    )

    exp_schema = exposures.collect_schema()
    if "residential_collateral_value" not in exp_schema.names():
        exposures = exposures.with_columns(
            pl.lit(0.0).alias("residential_collateral_value"),
        )
    if "exposure_for_retail_threshold" not in exp_schema.names():
        exposures = exposures.with_columns(
            (
                pl.col("drawn_amount")
                + pl.col("nominal_amount")
                - pl.col("residential_collateral_value")
            ).alias("exposure_for_retail_threshold"),
        )
    if "lending_group_adjusted_exposure" not in exp_schema.names():
        exposures = exposures.with_columns(
            pl.col("lending_group_total_exposure").alias("lending_group_adjusted_exposure"),
        )

    return make_resolved_bundle(
        exposures=exposures,
        counterparty_lookup=make_counterparty_lookup(
            counterparties=enriched_cp,
            parent_mappings=pl.LazyFrame(
                schema={
                    "child_counterparty_reference": pl.String,
                    "parent_counterparty_reference": pl.String,
                }
            ),
            ultimate_parent_mappings=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "ultimate_parent_reference": pl.String,
                    "hierarchy_depth": pl.Int32,
                }
            ),
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
        collateral=pl.LazyFrame(),
        guarantees=pl.LazyFrame(),
        provisions=pl.LazyFrame(),
        specialised_lending=None,
        model_permissions=model_permissions,
        lending_group_totals=pl.LazyFrame(
            schema={
                "lending_group_reference": pl.String,
                "total_drawn": pl.Float64,
                "total_nominal": pl.Float64,
                "total_exposure": pl.Float64,
                "adjusted_exposure": pl.Float64,
                "total_residential_coverage": pl.Float64,
                "exposure_count": pl.UInt32,
            }
        ),
    )


def _make_null_book_code_exposure() -> tuple[pl.LazyFrame, pl.LazyFrame]:
    """
    Return (exposures, counterparties) for the P1.114 null-book-code scenario.

    Counterparty: corporate, country_code=null, large (not SME).
    Exposure: book_code=null, internal_pd=0.01, lgd=None (FIRB uses regulatory LGD floor).
    model_id links to the P1.114 permission row.
    """
    counterparties = pl.DataFrame(
        {
            "counterparty_reference": [_CP_REF],
            "counterparty_name": ["Null Geo Corp"],
            "entity_type": ["corporate"],
            "country_code": [None],  # null — no geographic home
            "annual_revenue": [5_000_000_000.0],  # GBP 5bn — large corporate
            "total_assets": [10_000_000_000.0],
            "default_status": [False],
            "sector_code": ["MANU"],
            "apply_fi_scalar": [False],
            "is_managed_as_retail": [False],
        },
        schema={
            "counterparty_reference": pl.String,
            "counterparty_name": pl.String,
            "entity_type": pl.String,
            "country_code": pl.String,  # nullable
            "annual_revenue": pl.Float64,
            "total_assets": pl.Float64,
            "default_status": pl.Boolean,
            "sector_code": pl.String,
            "apply_fi_scalar": pl.Boolean,
            "is_managed_as_retail": pl.Boolean,
        },
    ).lazy()

    exposures = pl.DataFrame(
        {
            "exposure_reference": [_LOAN_REF],
            "exposure_type": ["loan"],
            "product_type": ["TERM_LOAN"],
            "book_code": [None],  # null — exercises the null-propagation defect
            "counterparty_reference": [_CP_REF],
            "value_date": [date(2024, 1, 1)],
            "maturity_date": [date(2027, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [1_000_000.0],
            "undrawn_amount": [0.0],
            "nominal_amount": [0.0],
            "lgd": [None],  # null LGD -> FIRB uses regulatory floor
            "seniority": ["senior"],
            "exposure_has_parent": [False],
            "root_facility_reference": [None],
            "facility_hierarchy_depth": [1],
            "counterparty_has_parent": [False],
            "parent_counterparty_reference": [None],
            "ultimate_parent_reference": [None],
            "counterparty_hierarchy_depth": [1],
            "lending_group_reference": [None],
            "lending_group_total_exposure": [0.0],
            "model_id": [_MODEL_ID],
            "internal_pd": [0.01],
        },
        schema={
            "exposure_reference": pl.String,
            "exposure_type": pl.String,
            "product_type": pl.String,
            "book_code": pl.String,  # nullable
            "counterparty_reference": pl.String,
            "value_date": pl.Date,
            "maturity_date": pl.Date,
            "currency": pl.String,
            "drawn_amount": pl.Float64,
            "undrawn_amount": pl.Float64,
            "nominal_amount": pl.Float64,
            "lgd": pl.Float64,  # nullable — FIRB will use regulatory floor
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
            "model_id": pl.String,
            "internal_pd": pl.Float64,
        },
    ).lazy()

    return exposures, counterparties


def _make_trade_finance_excluded_permissions() -> pl.LazyFrame:
    """
    Return a model_permissions LazyFrame matching the P1.114 scenario:
      - model_id="UK_CORP_PD_01"
      - exposure_class="corporate"
      - approach="foundation_irb"
      - country_codes=null   (no geographic restriction)
      - excluded_book_codes="TRADE_FINANCE"  (non-null exclusion list)

    The exposure's book_code is null, which is NOT in the exclusion list.
    Post-fix: permission is valid; pre-fix: null propagates and blocks permission.
    """
    return pl.DataFrame(
        {
            "model_id": [_MODEL_ID],
            "exposure_class": [ExposureClass.CORPORATE.value],
            "approach": [ApproachType.FIRB.value],
            "country_codes": [None],
            "excluded_book_codes": ["TRADE_FINANCE"],
        },
        schema={
            "model_id": pl.String,
            "exposure_class": pl.String,
            "approach": pl.String,
            "country_codes": pl.String,
            "excluded_book_codes": pl.String,
        },
    ).lazy()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def classifier() -> ExposureClassifier:
    """Return an ExposureClassifier instance."""
    return ExposureClassifier()


@pytest.fixture
def crr_irb_config() -> CalculationConfig:
    """CRR config with IRB permission mode enabled."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestModelPermissionsNullBookCode:
    """
    P1.114 — null book_code must not trigger the book-code exclusion filter.

    Scenario:
        model_permission.excluded_book_codes = "TRADE_FINANCE"
        model_permission.country_codes       = null  (no geo restriction)
        exposure.book_code                   = null

    A null book_code is not in the exclusion list, so book_not_excluded must be
    True (not null), permission_valid must be True, and the exposure must route to
    FIRB — not silently fall back to SA.
    """

    def test_null_book_code_not_treated_as_excluded_approach_is_firb(
        self,
        classifier: ExposureClassifier,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """
        Null book_code with non-null excluded_book_codes -> FIRB (not SA fallback).

        This is the primary regression assertion for P1.114. Pre-fix, the exposure
        routes to SA because str.contains(null) propagates null into permission_valid.
        Post-fix, the null-safe logic treats null book_code as "not excluded" -> FIRB.
        """
        # Arrange
        exposures, counterparties = _make_null_book_code_exposure()
        model_perms = _make_trade_finance_excluded_permissions()
        bundle = _make_resolved_bundle(exposures, counterparties, model_permissions=model_perms)

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, crr_irb_config)

        # Assert
        df = result.all_exposures.collect()
        row = df.filter(pl.col("exposure_reference") == _LOAN_REF)
        assert len(row) == 1, f"Expected exactly one row for {_LOAN_REF!r}, got {len(row)}"

        actual_approach = row["approach"][0]
        assert actual_approach == ApproachType.FIRB.value, (
            f"Expected approach={ApproachType.FIRB.value!r} for null book_code exposure "
            f"(model has excluded_book_codes='TRADE_FINANCE', not null), "
            f"but got {actual_approach!r}. "
            f"Pre-fix bug: str.contains(null) propagates null -> permission_valid=null -> SA."
        )

    def test_null_book_code_model_firb_permitted_is_true(
        self,
        classifier: ExposureClassifier,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """
        model_firb_permitted must be True when book_code is null and excluded list is non-null.

        The null-propagation bug causes model_firb_permitted=False (null coerced to False),
        making this assertion fail pre-fix.
        """
        # Arrange
        exposures, counterparties = _make_null_book_code_exposure()
        model_perms = _make_trade_finance_excluded_permissions()
        bundle = _make_resolved_bundle(exposures, counterparties, model_permissions=model_perms)

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, crr_irb_config)

        # Assert
        df = result.all_exposures.collect()
        row = df.filter(pl.col("exposure_reference") == _LOAN_REF)
        assert len(row) == 1

        actual_firb_permitted = row["model_firb_permitted"][0]
        assert actual_firb_permitted is True, (
            f"Expected model_firb_permitted=True for null book_code with "
            f"excluded_book_codes='TRADE_FINANCE', but got {actual_firb_permitted!r}. "
            f"Pre-fix bug: null propagation sets permission_valid=null -> firb_match=null/False."
        )

    def test_null_book_code_no_filter_rejected_diagnostic(
        self,
        classifier: ExposureClassifier,
        crr_irb_config: CalculationConfig,
    ) -> None:
        """
        No CLS006 'filter_rejected' error should appear for the null-book-code exposure.

        Pre-fix, permission_valid=null means no IRB approach is granted, which the
        diagnostic pipeline interprets as 'filter_rejected' and emits a CLS006 warning.
        Post-fix, the exposure IS granted FIRB and no diagnostic warning is emitted.
        """
        # Arrange
        exposures, counterparties = _make_null_book_code_exposure()
        model_perms = _make_trade_finance_excluded_permissions()
        bundle = _make_resolved_bundle(exposures, counterparties, model_permissions=model_perms)

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, crr_irb_config)

        # Assert: no CLS006 errors should appear
        cls006_errors = [e for e in result.classification_errors if e.code == "CLS006"]
        assert cls006_errors == [], (
            f"Expected no CLS006 'filter_rejected' warning for null book_code exposure, "
            f"but got: {cls006_errors}. "
            f"Pre-fix bug: permission falls through to SA and CLS006 is emitted."
        )
