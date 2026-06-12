"""Unit tests for CLS008: null annual_revenue → conservative large-corp default + warning (B31).

Tests cover:
- Scenario A: B31 + null annual_revenue for corporate with A-IRB permission → CLS008 emitted
  and approach forced to "foundation_irb" (conservative large-corp block).
- Scenario B: B31 + GBP 500m revenue (provably large) → no CLS008, approach="foundation_irb".
- Scenario C: CRR + null annual_revenue → no CLS008 (framework-gated), approach="advanced_irb".
- CLS008 attributes: code, severity (WARNING), category (CLASSIFICATION),
  regulatory_reference (PRA PS1/26 Art. 147A(1)(d)), message contains "annual_revenue"
  and "large" or "440".

References:
- PRA PS1/26 Art. 147A(1)(d): Large corporate (revenue > GBP 440m) restricted to F-IRB
- P1.126: null annual_revenue → CLS008 warning + conservative F-IRB under Basel 3.1
- tests/unit/classifier/test_p1_125_fse_column_warning.py: analogous CLS007 pattern
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import ResolvedHierarchyBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ErrorCategory, ErrorSeverity
from rwa_calc.engine.classifier import ExposureClassifier
from tests.fixtures.p1_126.p1_126 import (
    make_scenario_a_bundle,
    make_scenario_b_bundle,
    make_scenario_c_bundle,
)
from tests.fixtures.resolved_bundle import seal_hierarchy_exit

# =============================================================================
# Helpers
# =============================================================================


def _add_internal_pd_to_bundle(
    bundle: ResolvedHierarchyBundle, internal_pd: float = 0.005
) -> ResolvedHierarchyBundle:
    """Enrich the bundle's exposures frame with an internal_pd column.

    The classifier's model-permissions diagnostic roll-up filters on
    ``internal_pd`` when model_permissions is not None.  The HierarchyResolver
    normally joins this from rating_inheritance onto the exposures frame; when
    calling the classifier directly (bypassing HierarchyResolver), the column
    must be provided explicitly.

    The fixture's exposures do not carry internal_pd; we add it here in the
    Arrange phase before passing to the Act step.
    """
    enriched_exposures = bundle.exposures.with_columns(pl.lit(internal_pd).alias("internal_pd"))
    return replace(bundle, exposures=seal_hierarchy_exit(enriched_exposures))


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


# =============================================================================
# Scenario A: B31 + null annual_revenue → CLS008 + approach="firb"
# =============================================================================


class TestScenarioA_B31NullRevenue:
    """B31 framework: CLS008 warning and FIRB forced when annual_revenue is null."""

    def test_cls008_emitted_when_annual_revenue_null_under_b31(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """Scenario A: exactly one CLS008 warning when corporate revenue is null under B31."""
        # Arrange
        bundle = _add_internal_pd_to_bundle(make_scenario_a_bundle())

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        cls008_errors = [e for e in result.classification_errors if e.code == "CLS008"]
        assert len(cls008_errors) == 1

    def test_cls008_has_warning_severity(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """CLS008 must be WARNING severity, not ERROR."""
        # Arrange
        bundle = _add_internal_pd_to_bundle(make_scenario_a_bundle())

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        cls008_errors = [e for e in result.classification_errors if e.code == "CLS008"]
        assert len(cls008_errors) == 1
        assert cls008_errors[0].severity == ErrorSeverity.WARNING

    def test_cls008_has_classification_category(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """CLS008 must carry CLASSIFICATION error category."""
        # Arrange
        bundle = _add_internal_pd_to_bundle(make_scenario_a_bundle())

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        cls008_errors = [e for e in result.classification_errors if e.code == "CLS008"]
        assert len(cls008_errors) == 1
        assert cls008_errors[0].category == ErrorCategory.CLASSIFICATION

    def test_cls008_regulatory_reference_cites_art_147a_1d(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """CLS008 regulatory_reference must cite PRA PS1/26 Art. 147A(1)(d)."""
        # Arrange
        bundle = _add_internal_pd_to_bundle(make_scenario_a_bundle())

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        cls008_errors = [e for e in result.classification_errors if e.code == "CLS008"]
        assert len(cls008_errors) == 1
        assert cls008_errors[0].regulatory_reference == "PRA PS1/26 Art. 147A(1)(d)"

    def test_cls008_message_mentions_annual_revenue(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """CLS008 message must mention 'annual_revenue' to identify the missing datum."""
        # Arrange
        bundle = _add_internal_pd_to_bundle(make_scenario_a_bundle())

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        cls008_errors = [e for e in result.classification_errors if e.code == "CLS008"]
        assert len(cls008_errors) == 1
        assert "annual_revenue" in cls008_errors[0].message

    def test_cls008_message_mentions_large_or_440_threshold(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """CLS008 message must mention 'large' or '440' to cite the threshold."""
        # Arrange
        bundle = _add_internal_pd_to_bundle(make_scenario_a_bundle())

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        cls008_errors = [e for e in result.classification_errors if e.code == "CLS008"]
        assert len(cls008_errors) == 1
        message = cls008_errors[0].message
        assert "large" in message.lower() or "440" in message

    def test_approach_forced_to_firb_when_annual_revenue_null_under_b31(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """Scenario A: null revenue → conservative large-corp → approach must be 'foundation_irb'.

        This is the core regression guard for P1.126: the classifier previously
        used .fill_null(False) on the large-corp predicate, causing null revenue
        to be treated as 'not large corp' instead of applying the conservative
        assumption that the counterparty IS large corp (and thus restricted to FIRB).
        """
        # Arrange
        bundle = _add_internal_pd_to_bundle(make_scenario_a_bundle())

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        df = result.all_exposures.collect()
        assert len(df) == 1
        assert df["approach"][0] == ApproachType.FIRB.value


# =============================================================================
# Scenario B: B31 + GBP 500m revenue → no CLS008, approach="firb"
# =============================================================================


class TestScenarioB_B31LargeRevenue:
    """B31 framework: no CLS008 when revenue is explicit and above 440m threshold."""

    def test_no_cls008_when_annual_revenue_is_large_under_b31(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """Scenario B: no CLS008 when revenue is explicitly GBP 500m (unambiguous large)."""
        # Arrange
        bundle = _add_internal_pd_to_bundle(make_scenario_b_bundle())

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        cls008_errors = [e for e in result.classification_errors if e.code == "CLS008"]
        assert len(cls008_errors) == 0

    def test_approach_is_firb_when_large_revenue_confirmed_under_b31(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """Scenario B: confirmed large-corp → approach is 'foundation_irb' (no CLS008)."""
        # Arrange
        bundle = _add_internal_pd_to_bundle(make_scenario_b_bundle())

        # Act
        result = classifier.classify(bundle, b31_config)

        # Assert
        df = result.all_exposures.collect()
        assert len(df) == 1
        assert df["approach"][0] == ApproachType.FIRB.value


# =============================================================================
# Scenario C: CRR + null annual_revenue → no CLS008, approach="airb"
# =============================================================================


class TestScenarioC_CRRNullRevenue:
    """CRR framework: CLS008 is never emitted; null revenue leaves approach as 'advanced_irb'."""

    def test_no_cls008_under_crr_when_annual_revenue_null(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """Scenario C: no CLS008 under CRR — Art. 147A is B31-only."""
        # Arrange
        bundle = _add_internal_pd_to_bundle(make_scenario_c_bundle())

        # Act
        result = classifier.classify(bundle, crr_config)

        # Assert
        cls008_errors = [e for e in result.classification_errors if e.code == "CLS008"]
        assert len(cls008_errors) == 0

    def test_approach_is_airb_under_crr_with_null_revenue(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """Scenario C: null revenue under CRR → A-IRB still permitted (no large-corp block)."""
        # Arrange
        bundle = _add_internal_pd_to_bundle(make_scenario_c_bundle())

        # Act
        result = classifier.classify(bundle, crr_config)

        # Assert
        df = result.all_exposures.collect()
        assert len(df) == 1
        assert df["approach"][0] == ApproachType.AIRB.value
