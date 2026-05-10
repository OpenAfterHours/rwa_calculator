"""
P1.120 — B31 Art. 127(1) provision-ratio denominator bug: gross outstanding vs unsecured EAD.

Acceptance scenario: a GBP 100,000 defaulted corporate loan (CP_K13) is partially
collateralised by GBP 60,000 cash via FCCM.  The exposure carries a GBP 8,000 SCRA
Stage-3 provision.

Under PRA PS1/26 Art. 127(1) the denominator for the 20% provision-threshold test
is "the outstanding amount of the item or facility" — i.e. the gross outstanding
(pre-CRM, pre-provision) exposure = 100,000.

Correct calculation (post-fix):
    gross_outstanding         = drawn_amount           = 100,000
    provision_amount          = 8,000
    provision_ratio           = 8,000 / 100,000        = 8.0%  < 20%  → RW = 150%
    ead_final (post-FCCM)     = 92,000 − 60,000        = 32,000
    rwa_final                 = 32,000 × 1.50          = 48,000

Engine bug (pre-fix, D3.19):
    The B31 branch of sa/namespace.py uses ``ead_final`` (post-CRM) as the
    denominator for the provision-ratio test instead of the gross outstanding:
        denominator  = ead_final                       = 32,000
        provision_ratio = 8,000 / 32,000              = 25.0%  ≥ 20%  → buggy RW = 100%
        buggy rwa_final = 32,000 × 1.00               = 32,000  (understates by 16,000)

Impact on existing test B31-K8 (TestB31K8_ProvisionDenominatorDifference):
    The test at tests/acceptance/basel31/test_scenario_b31_k_defaulted.py (lines 449-506)
    was written against the buggy B31 semantics, where the denominator is the
    post-CRM EAD (ead_final), not the gross outstanding.  Its inputs are:
        ead=80,000, provision_deducted=20,000, provision_allocated=16,500
    Under the post-fix denominator (gross = ead + provision_deducted = 100,000):
        16,500 / 100,000 = 16.5%  <  20%  →  RW = 150%,  RWA = 120,000
    The B31-K8 expected values (RW=100%, RWA=80,000) will therefore FAIL once the
    engine-implementer applies this fix.  The engine-implementer MUST update B31-K8's
    expected values as part of the same fix: B31 RW 100% → 150%, RWA 80,000 → 120,000.
    The CRR contrast test (test_b31_k8_crr_contrast_would_give_150pct) is correct
    and must continue to pass unchanged.

References:
    - PRA PS1/26 Art. 127(1): defaulted SA RW threshold denominator = "outstanding
      amount of the item or facility" (gross, pre-CRM, pre-provision)
    - BCBS CRE20.88-90: defaulted exposure provision threshold mechanics
    - src/rwa_calc/engine/sa/namespace.py: B31 defaulted branch (bug site D3.19)
    - tests/fixtures/p1_120/p1_120.py: fixture constants (GROSS_OUTSTANDING, etc.)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p1_120.p1_120 import (
    BUGGY_PROVISION_RATIO,
    BUGGY_RWA,
    EAD_FINAL,
    EAD_PRE_CRM,
    EXPECTED_RISK_WEIGHT,
    EXPECTED_RWA,
    GROSS_OUTSTANDING,
    LOAN_REF,
    PROVISION_AMOUNT,
    PROVISION_RATIO,
)

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_120"

# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------

_ABS_TOL_MONEY = 0.50  # ±£0.50 on 6-figure monetary values
_ABS_TOL_RW = 1e-6  # exact risk-weight comparison

# ---------------------------------------------------------------------------
# Pipeline runner — module-scoped for single pipeline execution
# ---------------------------------------------------------------------------


def _run_pipeline_p1120() -> object:
    """Run the Basel 3.1 SA pipeline with P1.120 scenario inputs.

    Loads counterparty, loan, provision, and collateral from the p1_120 parquet
    fixtures.  Empty facilities / facility_mappings / lending_mappings are
    provided with the minimum schema required by the loader.

    Returns the AggregatedResultBundle from PipelineOrchestrator.run_with_data().
    """
    lending_mappings = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )
    facility_mappings = pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        }
    )
    facilities = pl.LazyFrame(
        schema={
            "facility_reference": pl.String,
            "counterparty_reference": pl.String,
        }
    )

    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet")
    loans = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet")
    collateral = pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet")
    provisions = pl.scan_parquet(_FIXTURES_DIR / "provision.parquet")

    bundle = RawDataBundle(
        facilities=facilities,
        loans=loans,
        counterparties=counterparties,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        collateral=collateral,
        provisions=provisions,
    )
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _find_row(results: object, loan_ref: str) -> dict:
    """Return the single result row for *loan_ref* from SA results.

    Asserts that exactly one row matches — test-fails with a descriptive
    message if the exposure is missing (fixture or pipeline loading issue).
    """
    assert results.sa_results is not None, "SA results must not be None for SA-only config"
    df = results.sa_results.collect()
    rows = df.filter(pl.col("exposure_reference") == loan_ref).to_dicts()
    assert len(rows) == 1, (
        f"Expected exactly 1 SA result row for {loan_ref!r}, got {len(rows)}. "
        f"All exposure_references: {df['exposure_reference'].to_list()}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# P1.120 acceptance tests
# ---------------------------------------------------------------------------


class TestP1120Art1271ProvisionRatioDenominator:
    """
    P1.120: B31 Art. 127(1) denominator must be gross outstanding (100,000), not ead_final (32,000).

    Scenario: defaulted UK corporate (CP_K13), GBP 100,000 drawn, GBP 8,000 SCRA Stage-3
    provision, GBP 60,000 cash collateral (0% haircut, FCCM-eligible).

    Post-fix expected values:
        gross_outstanding  = 100,000  (drawn_amount, pre-CRM, pre-provision)
        provision_ratio    = 8,000 / 100,000 = 8.0%  <  20%  → RW = 150%
        ead_gross          = 92,000   (post-provision, pre-FCCM)
        ead_final          = 32,000   (post-FCCM cash collateral deduction)
        rwa_final          = 48,000   (32,000 × 1.50)

    Pre-fix buggy values (what the engine currently produces):
        buggy denominator  = ead_final = 32,000
        buggy ratio        = 8,000 / 32,000 = 25.0%  ≥  20%  → buggy RW = 100%
        buggy rwa_final    = 32,000   (32,000 × 1.00, understates by 16,000)

    B31-K8 migration note:
        TestB31K8_ProvisionDenominatorDifference in test_scenario_b31_k_defaulted.py
        will fail after the fix because its expected B31 values pin the buggy
        denominator.  The engine-implementer must update B31-K8 B31 expectations:
        RW 100% → 150%, RWA 80,000 → 120,000 (the CRR contrast test is unaffected).
    """

    @pytest.fixture(scope="class")
    def result(self) -> dict:
        """Run the B31 SA pipeline once and return the CP_K13 / B31_K13 result row."""
        return _find_row(_run_pipeline_p1120(), LOAN_REF)

    # ------------------------------------------------------------------
    # Primary assertion: risk weight must be 150% (post-fix)
    # ------------------------------------------------------------------

    def test_p1_120_risk_weight_is_150_pct(self, result: dict) -> None:
        """
        Art. 127(1) B31 denominator = gross outstanding → provision ratio 8% < 20% → RW = 150%.

        Arrange: defaulted corporate, drawn=100,000, provision=8,000, cash collateral=60,000.
        Act:     Basel 3.1 SA pipeline (CalculationConfig.basel_3_1()).
        Assert:  risk_weight == 1.50.

        Pre-fix failure mode:
            Engine uses ead_final (32,000) as denominator:
            8,000 / 32,000 = 25% ≥ 20% → RW = 100% (buggy).
            This test fails with risk_weight ≈ 1.00 before the fix.

        References:
            PRA PS1/26 Art. 127(1): denominator = "outstanding amount of the item
            or facility" (gross, pre-CRM, pre-provision = 100,000).
        """
        # Arrange
        row = result

        # Assert
        assert row["risk_weight"] == pytest.approx(EXPECTED_RISK_WEIGHT, abs=_ABS_TOL_RW), (
            f"P1.120 Art. 127(1): expected risk_weight={EXPECTED_RISK_WEIGHT:.2f} "
            f"(provision ratio {PROVISION_RATIO:.1%} < 20% using gross denominator 100,000), "
            f"got {row['risk_weight']:.6f}. "
            f"If risk_weight ≈ 1.00 the engine is using ead_final ({EAD_FINAL:,.0f}) as "
            f"denominator: {PROVISION_AMOUNT:,.0f} / {EAD_FINAL:,.0f} = "
            f"{BUGGY_PROVISION_RATIO:.1%} ≥ 20% (D3.19 bug). "
            f"Fix: denominator must be gross_outstanding = {GROSS_OUTSTANDING:,.0f}."
        )

    # ------------------------------------------------------------------
    # RWA assertion: 48,000 (post-fix), not 32,000 (pre-fix)
    # ------------------------------------------------------------------

    def test_p1_120_rwa_final_is_48k(self, result: dict) -> None:
        """
        RWA = ead_final × risk_weight = 32,000 × 1.50 = 48,000.

        Pre-fix failure mode:
            buggy RWA = 32,000 × 1.00 = 32,000.  The test fails with
            rwa_final ≈ 32,000 before the fix.

        Arrange: ead_final=32,000, expected risk_weight=1.50 (Art. 127(1) post-fix).
        Act:     Basel 3.1 SA pipeline.
        Assert:  rwa_final == 48,000 (±£0.50).
        """
        # Arrange
        row = result

        # Assert
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA, abs=_ABS_TOL_MONEY), (
            f"P1.120: expected rwa_final={EXPECTED_RWA:,.0f} "
            f"(= ead_final {EAD_FINAL:,.0f} × RW {EXPECTED_RISK_WEIGHT:.0%}), "
            f"got {row['rwa_final']:,.2f}. "
            f"Buggy result would be {BUGGY_RWA:,.0f} (ead_final × 100%, D3.19 denominator bug)."
        )

    # ------------------------------------------------------------------
    # ead_final assertion: 32,000 (FCCM reduces 92k by 60k cash)
    # ------------------------------------------------------------------

    def test_p1_120_ead_final_is_32k(self, result: dict) -> None:
        """
        ead_final = max(0, ead_gross − C*) = 92,000 − 60,000 = 32,000.

        C* = 60,000 cash × (1 − H_collateral − H_FX) = 60,000 × (1 − 0 − 0) = 60,000.
        Same-currency cash FCCM: zero collateral haircut and zero FX haircut.

        Arrange: drawn=100,000, provision=8,000, cash collateral=60,000 (GBP, same ccy).
        Act:     Basel 3.1 SA pipeline.
        Assert:  ead_final == 32,000 (±£0.50).
        """
        # Arrange
        row = result

        # Assert
        assert row["ead_final"] == pytest.approx(EAD_FINAL, abs=_ABS_TOL_MONEY), (
            f"P1.120: expected ead_final={EAD_FINAL:,.0f} "
            f"(drawn {GROSS_OUTSTANDING:,.0f} − provision {PROVISION_AMOUNT:,.0f} "
            f"− cash collateral 60,000), "
            f"got {row['ead_final']:,.2f}."
        )

    # ------------------------------------------------------------------
    # provision_allocated assertion: 8,000
    # ------------------------------------------------------------------

    def test_p1_120_provision_allocated_is_8k(self, result: dict) -> None:
        """
        The pipeline must allocate the full GBP 8,000 SCRA Stage-3 provision to this loan.

        Arrange: one provision row (PROV_K13_001, amount=8,000, beneficiary=LOAN_REF).
        Act:     Basel 3.1 SA pipeline.
        Assert:  provision_allocated == 8,000 (±£0.50).
        """
        # Arrange
        row = result

        # Assert
        assert row["provision_allocated"] == pytest.approx(PROVISION_AMOUNT, abs=_ABS_TOL_MONEY), (
            f"P1.120: expected provision_allocated={PROVISION_AMOUNT:,.0f}, "
            f"got {row['provision_allocated']:,.2f}. "
            f"The SCRA Stage-3 provision (PROV_K13_001) must be fully allocated "
            f"to {LOAN_REF!r} via the beneficiary_reference join."
        )

    # ------------------------------------------------------------------
    # ead_gross assertion: 92,000 (post-provision, pre-FCCM)
    # ------------------------------------------------------------------

    def test_p1_120_ead_gross_is_92k(self, result: dict) -> None:
        """
        ead_gross (ead_pre_crm) = drawn_amount − provision_deducted = 100,000 − 8,000 = 92,000.

        The CRM processor sets ead_gross = ead_pre_crm before FCCM.  This column
        is the starting point for the Art. 127(1) denominator reconstruction (gross =
        ead_gross + provision_deducted = 92,000 + 8,000 = 100,000).

        Arrange: drawn=100,000, provision deducted=8,000.
        Act:     Basel 3.1 SA pipeline.
        Assert:  ead_gross == 92,000 (±£0.50).
        """
        # Arrange
        row = result

        # Assert
        assert row["ead_gross"] == pytest.approx(EAD_PRE_CRM, abs=_ABS_TOL_MONEY), (
            f"P1.120: expected ead_gross={EAD_PRE_CRM:,.0f} "
            f"(= drawn {GROSS_OUTSTANDING:,.0f} − provision {PROVISION_AMOUNT:,.0f}), "
            f"got {row['ead_gross']:,.2f}."
        )

    # ------------------------------------------------------------------
    # Approach guard
    # ------------------------------------------------------------------

    def test_p1_120_approach_is_standardised(self, result: dict) -> None:
        """
        Exposure routes to 'standardised' approach under SA-only config.

        Regression guard: confirms the corporate is not misclassified and the
        SA-only PermissionMode is respected.

        Arrange: entity_type=corporate, CalculationConfig.basel_3_1(SA-only).
        Act:     Basel 3.1 SA pipeline.
        Assert:  approach_applied == 'standardised'.
        """
        # Arrange
        row = result

        # Assert
        assert row["approach_applied"] == "standardised", (
            f"P1.120: expected approach_applied='standardised', "
            f"got {row['approach_applied']!r}. "
            f"entity_type=corporate under PermissionMode.STANDARDISED must route to SA."
        )

    # ------------------------------------------------------------------
    # Directional sanity: rwa must be greater than buggy pre-fix value
    # ------------------------------------------------------------------

    def test_p1_120_rwa_exceeds_buggy_pre_fix_value(self, result: dict) -> None:
        """
        Post-fix RWA (48,000) must strictly exceed the pre-fix buggy RWA (32,000).

        Under the correct denominator 8% < 20% → 150% RW → RWA = 48,000.
        Under the buggy denominator 25% ≥ 20% → 100% RW → RWA = 32,000.

        This directional test acts as a regression guard once the fix lands:
        any re-introduction of the bug produces RWA ≤ 32,000.

        Arrange/Act: as above.
        Assert: rwa_final > BUGGY_RWA (32,000).
        """
        # Arrange
        row = result

        # Assert
        assert row["rwa_final"] > BUGGY_RWA, (
            f"P1.120: rwa_final {row['rwa_final']:,.2f} must exceed buggy pre-fix RWA "
            f"{BUGGY_RWA:,.0f}. Expected post-fix RWA = {EXPECTED_RWA:,.0f}."
        )
