"""
Unit tests for P2.39: Basel 3.1 Art. 155 equity SA-only enforcement.

The classifier must never route equity exposures to AIRB regardless of what
IRBPermissions says, under Basel 3.1.  Under CRR, the same misconfigured
IRBPermissions DOES route equity to AIRB (control case confirming the guard
is B31-only and does not regress CRR).

Pipeline position:
    HierarchyResolver -> ExposureClassifier (_apply_b31_approach_restrictions) -> CRMProcessor

Defect (pre-fix):
    classifier.py _apply_b31_approach_restrictions() has no guard for
    exposure_class == EQUITY.  A misconfigured IRBPermissions that grants AIRB
    to ExposureClass.EQUITY causes the equity exposure to fall through the
    AIRB branch (branch 7) of _build_approach_expr() instead of the EQUITY
    branch (branch 9).  Result: approach="advanced_irb" for an equity row.

Post-fix assertion:
    Under Basel 3.1 with misconfigured IRBPermissions granting AIRB to equity:
    - approach == "equity"  (NOT "advanced_irb")
    - exposure_class == "equity"  (sanity)
    - exposure_class_irb == "equity"  (sanity)

CRR control assertion:
    Under CRR with the same misconfigured IRBPermissions:
    - approach == "advanced_irb"
    This confirms that the fix introduces a B31-only guard and does NOT
    alter CRR behaviour (CRR Art. 155 permits equity IRB approaches).

References:
    - Basel 3.1 CRE60 / PRA PS1/26 Art. 155: equity SA-only from 1 Jan 2027
    - src/rwa_calc/engine/classifier.py: _apply_b31_approach_restrictions()
    - src/rwa_calc/engine/classifier.py: _build_approach_expr()
    - tests/fixtures/p2_39/p2_39.py: fixture builders and scenario constants
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import ClassifiedExposuresBundle
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.classifier import ExposureClassifier
from tests.fixtures.p2_39.p2_39 import (
    EQUITY_EXPOSURE_REF,
    EXPECTED_APPROACH,
    EXPECTED_EXPOSURE_CLASS,
    make_scenario_b31_bundle,
    make_scenario_crr_bundle,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2027, 1, 15)

# Deliberately misconfigured IRBPermissions: EQUITY incorrectly granted AIRB.
# The classifier's B31 guard must block this and return approach="equity".
_MISCONFIGURED_IRB_PERMISSIONS = IRBPermissions(
    permissions={
        ExposureClass.EQUITY: {ApproachType.SA, ApproachType.AIRB},
        ExposureClass.CORPORATE: {ApproachType.SA, ApproachType.FIRB, ApproachType.AIRB},
        ExposureClass.CORPORATE_SME: {ApproachType.SA, ApproachType.FIRB, ApproachType.AIRB},
        ExposureClass.INSTITUTION: {ApproachType.SA, ApproachType.FIRB},
        ExposureClass.RETAIL_MORTGAGE: {ApproachType.SA, ApproachType.AIRB},
        ExposureClass.RETAIL_QRRE: {ApproachType.SA, ApproachType.AIRB},
        ExposureClass.RETAIL_OTHER: {ApproachType.SA, ApproachType.AIRB},
    }
)


# ---------------------------------------------------------------------------
# Config builders (inject misconfigured IRBPermissions into frozen dataclass)
# ---------------------------------------------------------------------------


def _make_b31_config_with_misconfigured_irb() -> CalculationConfig:
    """
    Return a Basel 3.1 CalculationConfig whose irb_permissions incorrectly
    grants AIRB to ExposureClass.EQUITY.

    CalculationConfig is a frozen dataclass with irb_permissions as an
    init=False field derived in __post_init__.  To inject a custom
    IRBPermissions we bypass the frozen invariant using object.__setattr__
    after construction — the same technique the dataclass itself uses in
    __post_init__.
    """
    config = CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE)
    object.__setattr__(config, "irb_permissions", _MISCONFIGURED_IRB_PERMISSIONS)
    return config


def _make_crr_config_with_misconfigured_irb() -> CalculationConfig:
    """
    Return a CRR CalculationConfig whose irb_permissions incorrectly
    grants AIRB to ExposureClass.EQUITY.

    Under CRR, _apply_b31_approach_restrictions returns early (not B31),
    so the equity row falls through to the AIRB branch and gets
    approach="advanced_irb".  This is the EXPECTED CRR outcome used as
    the control assertion.
    """
    config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))
    object.__setattr__(config, "irb_permissions", _MISCONFIGURED_IRB_PERMISSIONS)
    return config


# ---------------------------------------------------------------------------
# Bundle enrichment — inject internal_pd so has_internal_rating=True
# ---------------------------------------------------------------------------


def _add_internal_pd(bundle_exposures: pl.LazyFrame, internal_pd: float = 0.02) -> pl.LazyFrame:
    """
    Add internal_pd to the exposures LazyFrame.

    In the full pipeline, internal_pd is propagated from rating_inheritance
    by the HierarchyResolver.  In this unit test we inject it directly to
    ensure has_internal_rating=True for the equity row — without this the
    airb_expr evaluates to False and the bug is not triggered.

    This mirrors the pattern in tests/unit/classifier/test_p1_145_model_permissions_dedup_determinism.py
    (pl.lit(INTERNAL_PD).alias("internal_pd")).
    """
    return bundle_exposures.with_columns(
        pl.lit(internal_pd).alias("internal_pd"),
    )


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def classifier() -> ExposureClassifier:
    """Return an ExposureClassifier instance."""
    return ExposureClassifier()


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Basel 3.1 config with misconfigured IRBPermissions granting AIRB to equity."""
    return _make_b31_config_with_misconfigured_irb()


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR config with misconfigured IRBPermissions granting AIRB to equity."""
    return _make_crr_config_with_misconfigured_irb()


# ---------------------------------------------------------------------------
# Tests: B31 equity SA-only guard
# ---------------------------------------------------------------------------


class TestB31EquitySaOnlyGuard:
    """
    P2.39 — Basel 3.1 Art. 155 equity SA-only enforcement.

    Pre-fix: the equity row gets approach="advanced_irb" because
    _apply_b31_approach_restrictions() has no guard for exposure_class=EQUITY,
    so the misconfigured AIRB permission flows through to the AIRB branch.

    Post-fix: _apply_b31_approach_restrictions() adds an EQUITY guard that
    blocks AIRB for equity rows, so the equity branch (9) fires and returns
    approach="equity".
    """

    def test_b31_equity_approach_is_not_advanced_irb(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """
        Equity exposure must NOT receive approach='advanced_irb' under Basel 3.1.

        Pre-fix: approach="advanced_irb" (AIRB branch fires before equity branch).
        Post-fix: approach="equity" (EQUITY guard in B31 restrictions blocks AIRB).

        This is the PRIMARY failing assertion — it catches the missing guard.
        """
        # Arrange
        bundle = make_scenario_b31_bundle()
        # Inject internal_pd so has_internal_rating=True; without it airb_expr
        # is False for all rows and the bug is never triggered.
        enriched_bundle_exposures = _add_internal_pd(bundle.exposures)
        import dataclasses

        bundle = dataclasses.replace(bundle, exposures=enriched_bundle_exposures)

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, b31_config)

        # Assert
        df = result.all_exposures.collect()
        row = df.filter(pl.col("exposure_reference") == EQUITY_EXPOSURE_REF)
        assert len(row) == 1, (
            f"Expected exactly one row for {EQUITY_EXPOSURE_REF!r}, got {len(row)}"
        )

        actual_approach = row["approach"][0]
        assert actual_approach != ApproachType.AIRB.value, (
            f"Equity exposure {EQUITY_EXPOSURE_REF!r} must NOT be routed to "
            f"approach={ApproachType.AIRB.value!r} under Basel 3.1 "
            f"(Art. 155 withdraws IRB equity approaches from 1 Jan 2027). "
            f"Got approach={actual_approach!r}. "
            f"This indicates _apply_b31_approach_restrictions() lacks an EQUITY guard."
        )

    def test_b31_equity_approach_is_equity(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """
        Equity exposure must receive approach='equity' under Basel 3.1.

        Pre-fix: approach="advanced_irb".
        Post-fix: approach="equity" (branch 9 of _build_approach_expr fires).

        This assertion pins the expected post-fix value.
        """
        # Arrange
        bundle = make_scenario_b31_bundle()
        enriched_bundle_exposures = _add_internal_pd(bundle.exposures)
        import dataclasses

        bundle = dataclasses.replace(bundle, exposures=enriched_bundle_exposures)

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, b31_config)

        # Assert
        df = result.all_exposures.collect()
        row = df.filter(pl.col("exposure_reference") == EQUITY_EXPOSURE_REF)
        assert len(row) == 1

        actual_approach = row["approach"][0]
        assert actual_approach == ApproachType.EQUITY.value, (
            f"Expected approach={ApproachType.EQUITY.value!r} for equity exposure "
            f"{EQUITY_EXPOSURE_REF!r} under Basel 3.1 "
            f"(equity class falls to branch 9 of _build_approach_expr after AIRB guard blocks). "
            f"Got approach={actual_approach!r}. "
            f"Pre-fix value is {ApproachType.AIRB.value!r}."
        )

    def test_b31_equity_exposure_class_is_equity(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """
        Sanity: exposure_class must be 'equity' for EX_EQ_147A_H under Basel 3.1.

        This confirms the classifier correctly derives exposure_class from
        entity_type='equity' — independent of the AIRB routing bug.
        """
        # Arrange
        bundle = make_scenario_b31_bundle()
        enriched_bundle_exposures = _add_internal_pd(bundle.exposures)
        import dataclasses

        bundle = dataclasses.replace(bundle, exposures=enriched_bundle_exposures)

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, b31_config)

        # Assert
        df = result.all_exposures.collect()
        row = df.filter(pl.col("exposure_reference") == EQUITY_EXPOSURE_REF)
        assert len(row) == 1

        actual_class = row["exposure_class"][0]
        assert actual_class == EXPECTED_EXPOSURE_CLASS, (
            f"Expected exposure_class={EXPECTED_EXPOSURE_CLASS!r} for "
            f"{EQUITY_EXPOSURE_REF!r}, got {actual_class!r}."
        )

    def test_b31_equity_exposure_class_irb_is_equity(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
    ) -> None:
        """
        Sanity: exposure_class_irb must be 'equity' for EX_EQ_147A_H under Basel 3.1.
        """
        # Arrange
        bundle = make_scenario_b31_bundle()
        enriched_bundle_exposures = _add_internal_pd(bundle.exposures)
        import dataclasses

        bundle = dataclasses.replace(bundle, exposures=enriched_bundle_exposures)

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, b31_config)

        # Assert
        df = result.all_exposures.collect()
        row = df.filter(pl.col("exposure_reference") == EQUITY_EXPOSURE_REF)
        assert len(row) == 1

        actual_irb_class = row["exposure_class_irb"][0]
        assert actual_irb_class == EXPECTED_EXPOSURE_CLASS, (
            f"Expected exposure_class_irb={EXPECTED_EXPOSURE_CLASS!r} for "
            f"{EQUITY_EXPOSURE_REF!r}, got {actual_irb_class!r}."
        )


# ---------------------------------------------------------------------------
# Tests: CRR control — misconfigured AIRB DOES route equity to AIRB (no B31 guard)
# ---------------------------------------------------------------------------


class TestCrrEquityControlNoB31Guard:
    """
    P2.39 — CRR control: under CRR, the same misconfigured IRBPermissions
    DOES route equity to AIRB because _apply_b31_approach_restrictions()
    returns early (not Basel 3.1) and the EQUITY guard is not applied.

    This confirms that the fix introduces a B31-only guard and does NOT
    change CRR behaviour (CRR Art. 155 permitted equity IRB approaches).
    Both pre-fix and post-fix this assertion should pass.
    """

    def test_crr_equity_approach_is_advanced_irb_with_misconfigured_permissions(
        self,
        classifier: ExposureClassifier,
        crr_config: CalculationConfig,
    ) -> None:
        """
        Under CRR, misconfigured IRBPermissions granting AIRB to equity DOES
        route equity to approach='advanced_irb'.

        This is the control case: CRR has no Art. 147A guard, so the AIRB
        branch fires before the equity branch (branch order 7 < 9).

        If this assertion fails after the fix, the fix has accidentally
        broken CRR behaviour.
        """
        # Arrange
        bundle = make_scenario_crr_bundle()
        enriched_bundle_exposures = _add_internal_pd(bundle.exposures)
        import dataclasses

        bundle = dataclasses.replace(bundle, exposures=enriched_bundle_exposures)

        # Act
        result: ClassifiedExposuresBundle = classifier.classify(bundle, crr_config)

        # Assert
        df = result.all_exposures.collect()
        row = df.filter(pl.col("exposure_reference") == EQUITY_EXPOSURE_REF)
        assert len(row) == 1, (
            f"Expected exactly one row for {EQUITY_EXPOSURE_REF!r}, got {len(row)}"
        )

        actual_approach = row["approach"][0]
        assert actual_approach == ApproachType.AIRB.value, (
            f"Under CRR with misconfigured IRBPermissions granting AIRB to equity, "
            f"expected approach={ApproachType.AIRB.value!r} (CRR has no Art. 147A guard). "
            f"Got approach={actual_approach!r}. "
            f"This may indicate the B31 equity guard was incorrectly applied under CRR."
        )


# ---------------------------------------------------------------------------
# Fixture constant integration test
# ---------------------------------------------------------------------------


class TestFixtureConstants:
    """
    Confirm that the fixture's public constants are consistent with the
    expected outputs the engine-implementer must achieve.

    EXPECTED_APPROACH is the nominal 'standardised' value from the fixture
    (equity SA-only concept); the actual classified value for equity is
    'equity' (ApproachType.EQUITY), which also routes to the SA calculator.
    Both values are SA-family and the primary fix assertion (not-AIRB) holds
    for both.
    """

    def test_expected_exposure_class_constant_is_equity(self) -> None:
        """EXPECTED_EXPOSURE_CLASS must be 'equity' per fixture constant."""
        # Arrange / Act — just check the constant
        # Assert
        assert EXPECTED_EXPOSURE_CLASS == "equity", (
            f"Fixture constant EXPECTED_EXPOSURE_CLASS={EXPECTED_EXPOSURE_CLASS!r} "
            f"must be 'equity'."
        )

    def test_expected_approach_constant_is_standardised(self) -> None:
        """EXPECTED_APPROACH must be 'standardised' per fixture constant."""
        # Arrange / Act
        # Assert
        assert EXPECTED_APPROACH == "standardised", (
            f"Fixture constant EXPECTED_APPROACH={EXPECTED_APPROACH!r} "
            f"must be 'standardised' (SA-family approach for equity)."
        )
