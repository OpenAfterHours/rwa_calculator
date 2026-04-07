"""Unit tests for QRRE classification warning when columns are missing.

Tests cover:
- Warning emitted when is_revolving column is missing
- Warning emitted when facility_limit column is missing
- Warning emitted when both columns are missing
- No warning when both columns are present
- Warning attributes (code, severity, category, regulatory reference)
- QRRE classification works correctly when columns are present

References:
- CRR Art. 147(5): QRRE qualifying criteria
- P6.12: QRRE classification silently disabled when columns absent
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
from rwa_calc.domain.enums import (
    ErrorCategory,
    ErrorSeverity,
    ExposureClass,
)
from rwa_calc.engine.classifier import ExposureClassifier

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

    return ResolvedHierarchyBundle(
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
# Tests: Missing column warnings
# =============================================================================


class TestQRREMissingColumnWarnings:
    """Test that classifier emits warnings when QRRE columns are absent."""

    def test_both_columns_missing_emits_warning(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """When both is_revolving and facility_limit are missing, emit one warning."""
        exposures = _retail_exposures(include_is_revolving=False, include_facility_limit=False)
        bundle = _make_bundle(exposures, _retail_counterparties())
        result = classifier.classify(bundle, crr_config)

        assert len(result.classification_errors) == 1
        error = result.classification_errors[0]
        assert error.code == ERROR_QRRE_COLUMNS_MISSING
        assert "is_revolving" in error.message
        assert "facility_limit" in error.message

    def test_only_is_revolving_missing(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """When only is_revolving is missing, warning mentions only that column."""
        exposures = _retail_exposures(include_is_revolving=False, include_facility_limit=True)
        bundle = _make_bundle(exposures, _retail_counterparties())
        result = classifier.classify(bundle, crr_config)

        assert len(result.classification_errors) == 1
        error = result.classification_errors[0]
        assert "is_revolving" in error.message
        assert "facility_limit" not in error.message

    def test_only_facility_limit_missing(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """When only facility_limit is missing, warning mentions only that column."""
        exposures = _retail_exposures(include_is_revolving=True, include_facility_limit=False)
        bundle = _make_bundle(exposures, _retail_counterparties())
        result = classifier.classify(bundle, crr_config)

        assert len(result.classification_errors) == 1
        error = result.classification_errors[0]
        assert "facility_limit" in error.message
        assert "is_revolving" not in error.message

    def test_both_columns_present_no_warning(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """When both columns are present, no QRRE warning should be emitted."""
        exposures = _retail_exposures(include_is_revolving=True, include_facility_limit=True)
        bundle = _make_bundle(exposures, _retail_counterparties())
        result = classifier.classify(bundle, crr_config)

        qrre_warnings = [e for e in result.classification_errors if e.code == "CLS004"]
        assert len(qrre_warnings) == 0

    def test_warning_severity_is_warning(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """QRRE missing column warning should be WARNING severity, not ERROR."""
        exposures = _retail_exposures()
        bundle = _make_bundle(exposures, _retail_counterparties())
        result = classifier.classify(bundle, crr_config)

        error = result.classification_errors[0]
        assert error.severity == ErrorSeverity.WARNING

    def test_warning_category_is_classification(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """QRRE warning should use CLASSIFICATION error category."""
        exposures = _retail_exposures()
        bundle = _make_bundle(exposures, _retail_counterparties())
        result = classifier.classify(bundle, crr_config)

        error = result.classification_errors[0]
        assert error.category == ErrorCategory.CLASSIFICATION

    def test_warning_regulatory_reference(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """Warning should reference CRR Art. 147(5) for QRRE criteria."""
        exposures = _retail_exposures()
        bundle = _make_bundle(exposures, _retail_counterparties())
        result = classifier.classify(bundle, crr_config)

        error = result.classification_errors[0]
        assert error.regulatory_reference == "CRR Art. 147(5)"

    def test_warning_fires_for_basel_3_1_too(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """QRRE column warning fires under Basel 3.1 as well as CRR."""
        exposures = _retail_exposures()
        bundle = _make_bundle(exposures, _retail_counterparties())
        result = classifier.classify(bundle, b31_config)

        assert len(result.classification_errors) == 1
        assert result.classification_errors[0].code == ERROR_QRRE_COLUMNS_MISSING


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
