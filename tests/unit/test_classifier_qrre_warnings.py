"""Unit tests for QRRE driver columns under the sealed hierarchy_exit edge.

The hierarchy_exit edge contract (contracts/edges.py) declares is_revolving,
facility_limit and is_qrre_transactor, so every constructible classifier
input carries them — absent at most as typed nulls, never as missing
columns. The historical CLS004 "QRRE columns missing" warning branch was
deleted as dead code; these tests pin the replacement invariant instead.

Tests cover:
- Sealed exposures frames always carry the QRRE driver columns
- CLS004 (ERROR_QRRE_COLUMNS_MISSING) is never emitted on sealed input
- QRRE classification works correctly with populated / null driver columns

References:
- CRR Art. 147(5): QRRE qualifying criteria
- contracts/edges.py: HIERARCHY_EXIT_EDGE (Phase 3 producer-sealed edge)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    CounterpartyLookup,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_QRRE_COLUMNS_MISSING
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.classifier import ExposureClassifier
from tests.fixtures.resolved_bundle import make_resolved_bundle

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def classifier() -> ExposureClassifier:
    return ExposureClassifier()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _retail_counterparties() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "counterparty_reference": ["RTL_001", "RTL_002"],
            "counterparty_name": ["Retail A", "Retail B"],
            "entity_type": ["individual", "individual"],
            "country_code": ["GB", "GB"],
            "annual_revenue": [0.0, 0.0],
            "total_assets": [0.0, 0.0],
            "default_status": [False, False],
            "sector_code": ["RETAIL", "RETAIL"],
            "apply_fi_scalar": [False, False],
            "is_managed_as_retail": [False, False],
        }
    ).lazy()


def _retail_exposures(
    *,
    include_is_revolving: bool = False,
    include_facility_limit: bool = False,
) -> pl.LazyFrame:
    """Create retail exposures with optional QRRE columns."""
    data: dict[str, list[object]] = {
        "exposure_reference": ["EXP_001", "EXP_002"],
        "exposure_type": ["loan", "loan"],
        "product_type": ["PERSONAL", "CREDIT_CARD"],
        "book_code": ["RETAIL", "RETAIL"],
        "counterparty_reference": ["RTL_001", "RTL_002"],
        "value_date": [date(2023, 1, 1), date(2023, 1, 1)],
        "maturity_date": [date(2028, 1, 1), date(2028, 1, 1)],
        "currency": ["GBP", "GBP"],
        "drawn_amount": [10000.0, 5000.0],
        "undrawn_amount": [0.0, 0.0],
        "nominal_amount": [0.0, 0.0],
        "lgd": [0.45, 0.45],
        "seniority": ["senior", "senior"],
        "exposure_has_parent": [False, False],
        "root_facility_reference": [None, None],
        "facility_hierarchy_depth": [1, 1],
        "counterparty_has_parent": [False, False],
        "parent_counterparty_reference": [None, None],
        "ultimate_parent_reference": [None, None],
        "counterparty_hierarchy_depth": [1, 1],
        "lending_group_reference": [None, None],
        "lending_group_total_exposure": [10000.0, 5000.0],
    }
    if include_is_revolving:
        data["is_revolving"] = [False, True]
    if include_facility_limit:
        data["facility_limit"] = [0.0, 50000.0]
    return pl.DataFrame(data).lazy()


def _make_bundle(
    exposures: pl.LazyFrame,
    counterparties: pl.LazyFrame,
) -> ResolvedHierarchyBundle:
    """Create a ResolvedHierarchyBundle for testing."""
    enriched_cp = counterparties.with_columns(
        [
            pl.lit(False).alias("counterparty_has_parent"),
            pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"),
            pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"),
            pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"),
            pl.lit(None).cast(pl.Int8).alias("cqs"),
        ]
    )

    # Add columns the classifier expects
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
        counterparty_lookup=CounterpartyLookup(
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
        model_permissions=None,
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
        hierarchy_errors=[],
    )


# =============================================================================
# Tests: sealed-edge invariant (QRRE driver columns are always present)
# =============================================================================
#
# The historical TestQRREMissingColumnWarnings class asserted that CLS004
# fired when is_revolving / facility_limit were absent from the exposures
# frame. Under the hierarchy_exit seal those states are unrepresentable
# (the seal injects declared-but-absent columns as typed nulls), so the
# absence-warning tests were deleted and replaced by the invariant below.


class TestQRRESealedFrameInvariant:
    """The sealed edge makes the QRRE column-absence state unrepresentable."""

    def test_sealed_frame_always_carries_qrre_driver_columns(
        self,
    ) -> None:
        """Exposures built without QRRE columns still carry them after the seal."""
        exposures = _retail_exposures(include_is_revolving=False, include_facility_limit=False)
        bundle = _make_bundle(exposures, _retail_counterparties())

        schema = bundle.exposures.collect_schema()
        assert schema.get("is_revolving") == pl.Boolean
        assert schema.get("facility_limit") == pl.Float64
        assert schema.get("is_qrre_transactor") == pl.Boolean

    @pytest.mark.parametrize("config_fixture", ["crr_config", "b31_config"])
    def test_no_qrre_column_warning_on_sealed_input(
        self,
        classifier: ExposureClassifier,
        config_fixture: str,
        request: pytest.FixtureRequest,
    ) -> None:
        """CLS004 is never emitted: the sealed input always has the columns.

        Other warnings may legitimately fire (e.g. CLS007 under Basel 3.1
        for the minimal counterparty schema), so filter by code.
        """
        config = request.getfixturevalue(config_fixture)
        exposures = _retail_exposures(include_is_revolving=False, include_facility_limit=False)
        bundle = _make_bundle(exposures, _retail_counterparties())
        result = classifier.classify(bundle, config)

        qrre_warnings = [
            e for e in result.classification_errors if e.code == ERROR_QRRE_COLUMNS_MISSING
        ]
        assert qrre_warnings == []


# =============================================================================
# Tests: Classification correctness with/without QRRE columns
# =============================================================================


class TestQRREClassificationBehavior:
    """Test that QRRE classification is correct when columns are present/absent."""

    def test_without_qrre_columns_all_retail_is_retail_other(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """Without QRRE columns, revolving retail classified as RETAIL_OTHER."""
        exposures = _retail_exposures(include_is_revolving=False, include_facility_limit=False)
        bundle = _make_bundle(exposures, _retail_counterparties())
        result = classifier.classify(bundle, crr_config)

        classes = (
            result.all_exposures.select("exposure_class").collect()["exposure_class"].to_list()
        )
        # All should be RETAIL_OTHER (or RETAIL_MORTGAGE) — none should be RETAIL_QRRE
        assert ExposureClass.RETAIL_QRRE.value not in classes

    def test_with_qrre_columns_revolving_classified_as_qrre(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """With QRRE columns, qualifying revolving retail classified as RETAIL_QRRE."""
        exposures = _retail_exposures(include_is_revolving=True, include_facility_limit=True)
        bundle = _make_bundle(exposures, _retail_counterparties())
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.select("exposure_reference", "exposure_class").collect()
        # EXP_002 has is_revolving=True and facility_limit=50000 (under QRRE max)
        exp_002_class = df.filter(pl.col("exposure_reference") == "EXP_002")[
            "exposure_class"
        ].item()
        assert exp_002_class == ExposureClass.RETAIL_QRRE.value

    def test_non_revolving_not_qrre_even_with_columns(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """Non-revolving retail should NOT be QRRE even when columns are present."""
        exposures = _retail_exposures(include_is_revolving=True, include_facility_limit=True)
        bundle = _make_bundle(exposures, _retail_counterparties())
        result = classifier.classify(bundle, crr_config)

        df = result.all_exposures.select("exposure_reference", "exposure_class").collect()
        # EXP_001 has is_revolving=False
        exp_001_class = df.filter(pl.col("exposure_reference") == "EXP_001")[
            "exposure_class"
        ].item()
        assert exp_001_class != ExposureClass.RETAIL_QRRE.value
