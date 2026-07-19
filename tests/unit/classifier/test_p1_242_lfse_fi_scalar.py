"""Unit tests for the derived LFSE 1.25x correlation multiplier (P1.242 / P1.246).

The 1.25x asset-value-correlation multiplier for large financial sector
entities (LFSEs) is a MANDATORY treatment (CRR Art. 153(2) / PS1/26 Art. 153(2):
"shall multiply ... by 1.25"), not a user election. ``requires_fi_scalar`` must
therefore be DERIVED from the entity-type flag and total assets against the
regime threshold (CRR Art. 142(1)(4): EUR 70bn on an individual/consolidated
basis; PS1/26 IRB Part glossary: GBP 79bn at the highest consolidation level),
with the user-supplied ``apply_fi_scalar`` retained only as an authoritative
True-OVERRIDE that can never suppress a derived True.

Scope assertions:
- FSE with total_assets >= threshold -> requires_fi_scalar True (both regimes).
- The CRR threshold (EUR 70bn x rate ~= GBP 61bn) is lower than the B31 GBP 79bn
  threshold, so a GBP 65bn FSE is large under CRR but not under B31.
- Sub-threshold / non-FSE / null-assets FSE -> requires_fi_scalar False.
- Null total_assets on a flagged FSE emits CLS009 (never a silent pass-through).
- apply_fi_scalar=True is an authoritative override (flag can never be suppressed).
- The applied multiplier is exactly 1.25x on the base correlation (both regimes).

References:
- CRR Art. 142(1)(4) / Art. 153(2); PRA PS1/26 IRB Part glossary + Art. 153(2).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import ResolvedHierarchyBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.irb.formulas import calculate_correlation
from tests.fixtures.lfse_fi_scalar.lfse_fi_scalar import (
    make_large_fse_bundle,
    make_mid_fse_bundle,
    make_non_fse_large_bundle,
    make_null_assets_fse_bundle,
    make_override_bundle,
    make_small_fse_bundle,
)
from tests.fixtures.resolved_bundle import seal_hierarchy_exit


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


def _requires_fi_scalar(
    classifier: ExposureClassifier,
    config: CalculationConfig,
    bundle: ResolvedHierarchyBundle,
) -> bool:
    result = classifier.classify(_add_internal_pd(bundle), config)
    df = result.all_exposures.collect()
    return bool(df["requires_fi_scalar"][0])


# =============================================================================
# (A) Large FSE above the threshold -> scalar derived True (both regimes)
# =============================================================================


class TestLargeFSEDerivesScalar:
    def test_crr_large_fse_requires_scalar(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        assert _requires_fi_scalar(classifier, crr_config, make_large_fse_bundle()) is True

    def test_b31_large_fse_requires_scalar(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        assert _requires_fi_scalar(classifier, b31_config, make_large_fse_bundle()) is True


# =============================================================================
# (B) Regime-divergent threshold: GBP 65bn is large under CRR only
# =============================================================================


class TestRegimeThresholdDivergence:
    def test_crr_mid_fse_requires_scalar(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """GBP 65bn > CRR EUR 70bn x 0.8732 (~GBP 61.1bn) -> large under CRR."""
        assert _requires_fi_scalar(classifier, crr_config, make_mid_fse_bundle()) is True

    def test_b31_mid_fse_no_scalar(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        """GBP 65bn < PS1/26 GBP 79bn -> NOT large under Basel 3.1."""
        assert _requires_fi_scalar(classifier, b31_config, make_mid_fse_bundle()) is False


# =============================================================================
# (C)/(E) Sub-threshold and non-FSE -> no scalar
# =============================================================================


class TestNoScalarPaths:
    def test_crr_small_fse_no_scalar(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        assert _requires_fi_scalar(classifier, crr_config, make_small_fse_bundle()) is False

    def test_b31_small_fse_no_scalar(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        assert _requires_fi_scalar(classifier, b31_config, make_small_fse_bundle()) is False

    def test_crr_non_fse_large_no_scalar(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """Large total assets alone (is_financial_sector_entity=False) never qualifies."""
        assert _requires_fi_scalar(classifier, crr_config, make_non_fse_large_bundle()) is False


# =============================================================================
# (D) Null total_assets -> no scalar, CLS009 warning fires (both regimes)
# =============================================================================


class TestNullAssetsWarns:
    def test_crr_null_assets_no_scalar(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        assert _requires_fi_scalar(classifier, crr_config, make_null_assets_fse_bundle()) is False

    def test_crr_null_assets_emits_cls009(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        result = classifier.classify(_add_internal_pd(make_null_assets_fse_bundle()), crr_config)
        cls009 = [e for e in result.classification_errors if e.code == "CLS009"]
        assert len(cls009) == 1

    def test_b31_null_assets_emits_cls009(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        result = classifier.classify(_add_internal_pd(make_null_assets_fse_bundle()), b31_config)
        cls009 = [e for e in result.classification_errors if e.code == "CLS009"]
        assert len(cls009) == 1

    def test_large_fse_does_not_emit_cls009(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """A resolved (non-null) total_assets never trips the CLS009 gap warning."""
        result = classifier.classify(_add_internal_pd(make_large_fse_bundle()), crr_config)
        cls009 = [e for e in result.classification_errors if e.code == "CLS009"]
        assert len(cls009) == 0


# =============================================================================
# (F) Explicit apply_fi_scalar is an authoritative override
# =============================================================================


class TestUserOverride:
    def test_crr_override_forces_scalar(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """apply_fi_scalar=True forces the scalar even for a sub-threshold non-FSE."""
        assert _requires_fi_scalar(classifier, crr_config, make_override_bundle()) is True

    def test_b31_override_forces_scalar(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        assert _requires_fi_scalar(classifier, b31_config, make_override_bundle()) is True

    def test_override_does_not_emit_cls009(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """An explicit election suppresses the size-gap warning (non-FSE anyway)."""
        result = classifier.classify(_add_internal_pd(make_override_bundle()), crr_config)
        cls009 = [e for e in result.classification_errors if e.code == "CLS009"]
        assert len(cls009) == 0


# =============================================================================
# Correlation hand-calc: the applied multiplier is exactly 1.25x
# =============================================================================


class TestCorrelationMultiplier:
    """The FI scalar multiplies the base asset correlation R by exactly 1.25."""

    def test_crr_scalar_is_1_25x_base(self) -> None:
        base = calculate_correlation(pd=0.005, exposure_class="corporate", apply_fi_scalar=False)
        scaled = calculate_correlation(pd=0.005, exposure_class="corporate", apply_fi_scalar=True)
        assert scaled == pytest.approx(base * 1.25, rel=1e-9)

    def test_b31_scalar_is_1_25x_base(self) -> None:
        base = calculate_correlation(
            pd=0.005, exposure_class="corporate", apply_fi_scalar=False, is_b31=True
        )
        scaled = calculate_correlation(
            pd=0.005, exposure_class="corporate", apply_fi_scalar=True, is_b31=True
        )
        assert scaled == pytest.approx(base * 1.25, rel=1e-9)

    def test_base_correlation_value_pinned(self) -> None:
        """Corporate R at PD=0.5% = 0.12 f + 0.24 (1-f), f=(1-e^-0.25)/(1-e^-50)."""
        base = calculate_correlation(pd=0.005, exposure_class="corporate", apply_fi_scalar=False)
        assert base == pytest.approx(0.21345609396856858, rel=1e-9)
