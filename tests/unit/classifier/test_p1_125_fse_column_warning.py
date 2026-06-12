"""Unit tests for the is_financial_sector_entity sealed-lookup invariant.

The counterparty lookup is sealed against ``CP_LOOKUP_COUNTERPARTIES_EDGE``
(contracts/edges.py), which declares ``is_financial_sector_entity`` — every
constructible classifier input carries the column, absent at most as typed
nulls, never as a missing column. The historical CLS007 "FSE column missing"
warning branch was deleted as dead code; these tests pin the replacement
invariant instead.

Tests cover:
- Sealed lookups always carry is_financial_sector_entity (typed Boolean)
- CLS007 is never emitted on sealed input (column present or omitted at
  build time, B31 or CRR)

References:
- PRA PS1/26 Art. 147A(1)(e): Financial Sector Entities restricted to F-IRB under Basel 3.1
- contracts/edges.py: CP_LOOKUP_COUNTERPARTIES_EDGE (Phase 3 producer-sealed edge)
- tests/unit/test_classifier_qrre_warnings.py: analogous CLS004 sealed-invariant pattern
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import ResolvedHierarchyBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.classifier import ExposureClassifier
from tests.fixtures.p1_125.p1_125 import (
    make_corporate_exposure,
    make_counterparty_with_fse_column,
    make_counterparty_without_fse_column,
)
from tests.fixtures.resolved_bundle import make_counterparty_lookup, make_resolved_bundle

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

    return make_resolved_bundle(
        exposures=make_corporate_exposure(),
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
# Sealed-edge invariant: the FSE column-absence state is unrepresentable
# =============================================================================
#
# The historical TestScenarioA_B31ColumnAbsent class asserted that CLS007
# fired when is_financial_sector_entity was absent from the counterparty
# schema. Under the CP_LOOKUP_COUNTERPARTIES_EDGE seal that state is
# unrepresentable (the seal injects declared-but-absent columns as typed
# nulls), so the absence-warning tests were deleted and replaced by the
# invariant below.


class TestFSESealedFrameInvariant:
    """The sealed lookup makes the FSE column-absence state unrepresentable."""

    def test_sealed_lookup_always_carries_fse_column(self) -> None:
        """A lookup built without the FSE column still carries it after the seal."""
        bundle = _make_bundle(make_counterparty_without_fse_column())

        schema = bundle.counterparty_lookup.counterparties.collect_schema()
        assert schema.get("is_financial_sector_entity") == pl.Boolean

    @pytest.mark.parametrize("config_fixture", ["b31_config", "crr_config"])
    def test_no_cls007_on_sealed_input_when_column_omitted_at_build(
        self,
        classifier: ExposureClassifier,
        config_fixture: str,
        request: pytest.FixtureRequest,
    ) -> None:
        """CLS007 is never emitted: the sealed lookup always has the column."""
        config = request.getfixturevalue(config_fixture)
        bundle = _make_bundle(make_counterparty_without_fse_column())

        result = classifier.classify(bundle, config)

        cls007_errors = [e for e in result.classification_errors if e.code == "CLS007"]
        assert cls007_errors == []


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
