"""Unit tests for CLS007: FSE column absent → classifier warning under Basel 3.1.

Tests cover:
- Scenario A: B31 + counterparty schema OMITS is_financial_sector_entity → CLS007 emitted
- Scenario B: B31 + counterparty schema INCLUDES is_financial_sector_entity → no CLS007
- Scenario C: CRR + counterparty schema OMITS is_financial_sector_entity → no CLS007 (gating)
- CLS007 attributes: code, severity (WARNING), category (CLASSIFICATION),
  regulatory_reference (PRA PS1/26 Art. 147A(1)(e)), message contains column name

References:
- PRA PS1/26 Art. 147A(1)(e): Financial Sector Entities restricted to F-IRB under Basel 3.1
- P1.125: FSE column missing → CLS007 warning under B31
- tests/unit/test_classifier_qrre_warnings.py: analogous CLS004 pattern
- tests/unit/test_art123a_retail_criteria.py: analogous CLS005 pattern
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CounterpartyLookup, ResolvedHierarchyBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.engine.classifier import ExposureClassifier
from tests.fixtures.p1_125.p1_125 import (
    make_counterparty_with_fse_column,
    make_counterparty_without_fse_column,
    make_corporate_exposure,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def classifier() -> ExposureClassifier:
    return ExposureClassifier()


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


def _make_bundle(counterparties: pl.LazyFrame) -> ResolvedHierarchyBundle:
    """Build a minimal ResolvedHierarchyBundle for P1.125 FSE-column tests.

    Uses the counterparty LazyFrame as supplied; the column presence/absence of
    is_financial_sector_entity is what determines whether CLS007 fires.

    No model_permissions are included so the classifier does not attempt IRB
    routing (which would require internal_pd from the HierarchyResolver pipeline).
    This matches the pattern used in test_classifier_qrre_warnings.py and
    test_art123a_retail_criteria.py.
    """
    # Enrich counterparty with hierarchy columns the classifier expects
    cp_schema = counterparties.collect_schema().names()
    cp_additions: list[pl.Expr] = []
    if "counterparty_has_parent" not in cp_schema:
        cp_additions.append(pl.lit(False).alias("counterparty_has_parent"))
    if "parent_counterparty_reference" not in cp_schema:
        cp_additions.append(pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"))
    if "ultimate_parent_reference" not in cp_schema:
        cp_additions.append(pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"))
    if "counterparty_hierarchy_depth" not in cp_schema:
        cp_additions.append(pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"))
    if "cqs" not in cp_schema:
        cp_additions.append(pl.lit(None).cast(pl.Int8).alias("cqs"))
    enriched_cp = counterparties.with_columns(cp_additions) if cp_additions else counterparties

    empty_rating_inheritance = pl.LazyFrame(
        schema={
            "counterparty_reference": pl.String,
            "internal_pd": pl.Float64,
            "internal_model_id": pl.String,
            "external_cqs": pl.Int8,
            "cqs": pl.Int8,
            "pd": pl.Float64,
        }
    )

    return ResolvedHierarchyBundle(
        exposures=make_corporate_exposure(),
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
            rating_inheritance=empty_rating_inheritance,
        ),
        lending_group_totals=pl.LazyFrame(
            schema={
                "lending_group_reference": pl.String,
                "total_exposure": pl.Float64,
            }
        ),
        model_permissions=None,
        hierarchy_errors=[],
    )


# =============================================================================
# Scenario A: B31 + column absent → CLS007
# =============================================================================


class TestScenarioA_B31ColumnAbsent:
    """B31 framework: CLS007 warning is emitted when is_financial_sector_entity is absent."""

    def test_cls007_emitted_when_fse_column_absent_under_b31(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """Scenario A: exactly one CLS007 warning when counterparty omits FSE column."""
        # Arrange
        bundle = _make_bundle(make_counterparty_without_fse_column())

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        cls007_errors = [e for e in result.classification_errors if e.code == "CLS007"]
        assert len(cls007_errors) == 1

    def test_cls007_has_warning_severity(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """CLS007 must be WARNING severity, not ERROR."""
        # Arrange
        bundle = _make_bundle(make_counterparty_without_fse_column())

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        cls007_errors = [e for e in result.classification_errors if e.code == "CLS007"]
        assert len(cls007_errors) == 1
        assert cls007_errors[0].severity == ErrorSeverity.WARNING

    def test_cls007_has_classification_category(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """CLS007 must carry CLASSIFICATION error category."""
        # Arrange
        bundle = _make_bundle(make_counterparty_without_fse_column())

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        cls007_errors = [e for e in result.classification_errors if e.code == "CLS007"]
        assert len(cls007_errors) == 1
        assert cls007_errors[0].category == ErrorCategory.CLASSIFICATION

    def test_cls007_regulatory_reference_cites_art_147a(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """CLS007 regulatory_reference must cite PRA PS1/26 Art. 147A(1)(e)."""
        # Arrange
        bundle = _make_bundle(make_counterparty_without_fse_column())

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        cls007_errors = [e for e in result.classification_errors if e.code == "CLS007"]
        assert len(cls007_errors) == 1
        assert cls007_errors[0].regulatory_reference == "PRA PS1/26 Art. 147A(1)(e)"

    def test_cls007_message_mentions_fse_column(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """CLS007 message must mention the missing column name is_financial_sector_entity."""
        # Arrange
        bundle = _make_bundle(make_counterparty_without_fse_column())

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        cls007_errors = [e for e in result.classification_errors if e.code == "CLS007"]
        assert len(cls007_errors) == 1
        assert "is_financial_sector_entity" in cls007_errors[0].message


# =============================================================================
# Scenario B: B31 + column present → no CLS007
# =============================================================================


class TestScenarioB_B31ColumnPresent:
    """B31 framework: no CLS007 when is_financial_sector_entity is present."""

    def test_no_cls007_when_fse_column_present_under_b31(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """Scenario B: no CLS007 warning when counterparty includes FSE column."""
        # Arrange
        bundle = _make_bundle(make_counterparty_with_fse_column(is_financial_sector_entity=False))

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        cls007_errors = [e for e in result.classification_errors if e.code == "CLS007"]
        assert len(cls007_errors) == 0

    def test_no_cls007_when_fse_column_present_with_true_value(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """No CLS007 even when is_financial_sector_entity=True (column is present)."""
        # Arrange
        bundle = _make_bundle(make_counterparty_with_fse_column(is_financial_sector_entity=True))

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        cls007_errors = [e for e in result.classification_errors if e.code == "CLS007"]
        assert len(cls007_errors) == 0


# =============================================================================
# Scenario C: CRR + column absent → no CLS007 (framework gating)
# =============================================================================


class TestScenarioC_CRRColumnAbsent:
    """CRR framework: CLS007 is never emitted regardless of FSE column presence."""

    def test_no_cls007_under_crr_when_fse_column_absent(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """Scenario C: no CLS007 under CRR even when FSE column is absent."""
        # Arrange
        bundle = _make_bundle(make_counterparty_without_fse_column())

        # Act
        result = classifier.classify(bundle, crr_config)

        # Assert
        cls007_errors = [e for e in result.classification_errors if e.code == "CLS007"]
        assert len(cls007_errors) == 0
