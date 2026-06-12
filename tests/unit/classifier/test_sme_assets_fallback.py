"""Unit tests for the SME assets-fallback classification path.

Covers CRR Art. 4(1)(128D) / Commission Recommendation 2003/361/EC Art. 2 (the
"medium-sized" tier: turnover <= EUR 50m OR balance-sheet total <= EUR 43m) and
PRA PS1/26 Art. 153(4) third subparagraph (substitute total assets for total
annual sales when sales are not a meaningful indicator).

Scope assertions:
- Corporate with annual_revenue=null and total_assets=GBP 20m is classified
  CORPORATE_SME under both CRR and Basel 3.1 via the assets fallback.
- Sme_size_source on the exposure frame distinguishes turnover- vs assets-driven
  SME identification.
- Large-by-assets (revenue=null, assets=GBP 500m) is NOT SME and trips the
  Art. 147A(1)(d) F-IRB restriction under B3.1; CLS008 fires.
- Both-null preserves the prior conservative-large behaviour with CLS008.
- Turnover-only regression: when revenue is populated the classifier behaves
  exactly as before (assets do not alter sme_size_source).

References:
- CRR Art. 4(1)(128D), Art. 153(4), Art. 501(2)(c)
- PRA PS1/26 Art. 147A(1)(d), Art. 153(4)
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import ResolvedHierarchyBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.classifier import ExposureClassifier
from tests.fixtures.resolved_bundle import seal_hierarchy_exit
from tests.fixtures.sme_assets_fallback.sme_assets_fallback import (
    LOAN_REF,
    make_large_by_assets_bundle,
    make_null_both_bundle,
    make_sme_by_assets_bundle,
    make_sme_by_turnover_bundle,
)


def _add_internal_pd(bundle: ResolvedHierarchyBundle) -> ResolvedHierarchyBundle:
    """Ensure exposures carry internal_pd for the model-permissions diagnostic."""
    enriched = bundle.exposures.with_columns(pl.lit(0.005).alias("internal_pd"))
    return replace(bundle, exposures=seal_hierarchy_exit(enriched))


@pytest.fixture
def classifier() -> ExposureClassifier:
    return ExposureClassifier()


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2026, 12, 31))


# =============================================================================
# (A) Corporate SME identified via the assets fallback
# =============================================================================


class TestSMEByAssets:
    """Corporate with null annual_revenue and total_assets=GBP 20m."""

    def test_b31_classified_as_corporate_sme(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        bundle = _add_internal_pd(make_sme_by_assets_bundle())
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["exposure_class"][0] == ExposureClass.CORPORATE_SME.value

    def test_b31_is_sme_flag_true(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        bundle = _add_internal_pd(make_sme_by_assets_bundle())
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["is_sme"][0] is True

    def test_sme_size_source_is_assets(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        bundle = _add_internal_pd(make_sme_by_assets_bundle())
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["sme_size_source"][0] == "assets"

    def test_no_cls008_when_assets_resolve_sme(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """CLS008 must NOT fire when assets resolve the size question definitively."""
        bundle = _add_internal_pd(make_sme_by_assets_bundle())
        result = classifier.classify(bundle, b31_config)
        cls008 = [e for e in result.classification_errors if e.code == "CLS008"]
        assert len(cls008) == 0

    def test_b31_approach_not_forced_to_firb(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """SME-by-assets is not "large" under Art. 147A(1)(d) -> A-IRB remains permitted."""
        bundle = _add_internal_pd(make_sme_by_assets_bundle())
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["approach"][0] == ApproachType.AIRB.value

    def test_crr_classified_as_corporate_sme(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        bundle = _add_internal_pd(make_sme_by_assets_bundle())
        result = classifier.classify(bundle, crr_config)
        df = result.all_exposures.collect()
        assert df["exposure_class"][0] == ExposureClass.CORPORATE_SME.value


# =============================================================================
# (B) Corporate "large" via assets above the SME threshold
# =============================================================================


class TestLargeByAssets:
    """Corporate with null annual_revenue and total_assets=GBP 500m."""

    def test_b31_classified_as_corporate(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        bundle = _add_internal_pd(make_large_by_assets_bundle())
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["exposure_class"][0] == ExposureClass.CORPORATE.value

    def test_b31_is_sme_flag_false(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        bundle = _add_internal_pd(make_large_by_assets_bundle())
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["is_sme"][0] is False

    def test_b31_approach_forced_to_firb(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """Assets above the SME threshold cannot rule out large-corp -> F-IRB."""
        bundle = _add_internal_pd(make_large_by_assets_bundle())
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["approach"][0] == ApproachType.FIRB.value

    def test_b31_cls008_emitted(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """CLS008 fires: assets above SME threshold do not confirm size."""
        bundle = _add_internal_pd(make_large_by_assets_bundle())
        result = classifier.classify(bundle, b31_config)
        cls008 = [e for e in result.classification_errors if e.code == "CLS008"]
        assert len(cls008) == 1


# =============================================================================
# (C) Both turnover and assets null
# =============================================================================


class TestBothNull:
    """Corporate with null annual_revenue and null total_assets."""

    def test_b31_classified_as_corporate(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        bundle = _add_internal_pd(make_null_both_bundle())
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["exposure_class"][0] == ExposureClass.CORPORATE.value

    def test_b31_is_sme_flag_not_true(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """is_sme is null when both fields are null — Polars null-propagation
        through the SME size test. Downstream gates treat null as falsy."""
        bundle = _add_internal_pd(make_null_both_bundle())
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["is_sme"][0] is not True

    def test_sme_size_source_is_null(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        bundle = _add_internal_pd(make_null_both_bundle())
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["sme_size_source"][0] is None

    def test_b31_approach_forced_to_firb(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        bundle = _add_internal_pd(make_null_both_bundle())
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert df["approach"][0] == ApproachType.FIRB.value

    def test_b31_cls008_emitted(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        bundle = _add_internal_pd(make_null_both_bundle())
        result = classifier.classify(bundle, b31_config)
        cls008 = [e for e in result.classification_errors if e.code == "CLS008"]
        assert len(cls008) == 1


# =============================================================================
# (E) Turnover-only regression guard
# =============================================================================


class TestTurnoverOnlyRegression:
    """Counterparty with both fields populated must continue to key off turnover."""

    def test_sme_size_source_is_turnover(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        bundle = _add_internal_pd(make_sme_by_turnover_bundle())
        result = classifier.classify(bundle, crr_config)
        df = result.all_exposures.collect()
        assert df["sme_size_source"][0] == "turnover"

    def test_classified_as_corporate_sme(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        bundle = _add_internal_pd(make_sme_by_turnover_bundle())
        result = classifier.classify(bundle, crr_config)
        df = result.all_exposures.collect()
        assert df["exposure_class"][0] == ExposureClass.CORPORATE_SME.value


# =============================================================================
# Loan-reference sanity check
# =============================================================================


def test_loan_reference_present_across_scenarios(
    classifier: ExposureClassifier, b31_config: CalculationConfig
) -> None:
    """Smoke check: every fixture bundle yields exactly one row keyed on LOAN_REF."""
    for builder in (
        make_sme_by_assets_bundle,
        make_large_by_assets_bundle,
        make_null_both_bundle,
    ):
        bundle = _add_internal_pd(builder())
        result = classifier.classify(bundle, b31_config)
        df = result.all_exposures.collect()
        assert len(df) == 1
        assert df["exposure_reference"][0] == LOAN_REF
