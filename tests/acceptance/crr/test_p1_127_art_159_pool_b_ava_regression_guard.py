"""
P1.127: CRR Art. 159 Pool B EL shortfall — AVA + other_OFR no double-count.

Regression-guard acceptance test: verifies that AVA and other_own_funds_reductions
enter Pool B exactly once at the per-exposure level, are never double-counted by
a portfolio-level recompute, and are never silently dropped from per-exposure Pool B.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> IRBCalculator
        -> Aggregator (compute_el_portfolio_summary) -> AggregatedResultBundle.el_summary

Two AIRB exposures under counterparty CP-P1127-A:
    LN-P1127-ND: non-defaulted, EAD=1,500,000, PD=0.005, LGD=0.45, M=2.5y
        EL = PD × LGD × EAD = 3,375
        pool_b = prov(30,000) + AVA(40,000) + other_OFR(10,000) = 80,000
        shortfall = 0 (excess = 76,625)
    LN-P1127-D:  defaulted, EAD=1,000,000, BEEL=0.45, M=1.0y
        EL = BEEL × EAD = 450,000  (CRR Art. 158(5))
        pool_b = prov(120,000) + AVA(25,000) + other_OFR(5,000) = 150,000
        shortfall = 300,000

Art. 159(3) two-branch rule: non-defaulted pool has excess, defaulted pool has shortfall.
No cross-offset: total_el_shortfall = 300,000 (defaulted pool only).

Regulatory References:
    - CRR Art. 158(5): defaulted EL = BEEL × EAD
    - CRR Art. 159(1): Pool B = SCRA + GCRA + AVA + other own funds reductions
    - CRR Art. 159(3): two-branch no-cross-offset rule
    - CRR Art. 34 / Art. 105: Additional value adjustments (AVA)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, ELPortfolioSummary, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths — parquets sit directly in the p1_127 package directory
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_127"

# ---------------------------------------------------------------------------
# Expected values — single source of truth from the fixture module
# ---------------------------------------------------------------------------

from tests.fixtures.p1_127.p1_127 import (  # noqa: E402
    EXPECTED_EL_D,
    EXPECTED_EL_ND,
    EXPECTED_POOL_B_D,
    EXPECTED_POOL_B_ND,
    EXPECTED_SHORTFALL_D,
    EXPECTED_SHORTFALL_ND,
    EXPECTED_TOTAL_AVA,
    EXPECTED_TOTAL_EL,
    EXPECTED_TOTAL_OTHER_OFR,
    EXPECTED_TOTAL_POOL_B,
    EXPECTED_TOTAL_PROV,
    EXPECTED_TOTAL_SHORTFALL,
)

# ---------------------------------------------------------------------------
# Double-count sentinel values
# ---------------------------------------------------------------------------

# If the aggregator regresses to portfolio-level recompute (EL − pool_b):
#     453,375 − 230,000 = 223,375  ← must NOT appear as total_el_shortfall
_BUGGY_SHORTFALL_PORTFOLIO_RECOMPUTE = Decimal("223375.00")

# If AVA is silently dropped from per-exposure pool_b for the defaulted exposure:
#     pool_b_D would become 125,000 → shortfall_D = 325,000
_BUGGY_SHORTFALL_AVA_DROPPED = Decimal("325000.00")

# Reporting date
_REPORTING_DATE = date(2026, 1, 1)


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_127_pipeline_results() -> AggregatedResultBundle:
    """
    Run the P1.127 scenario through the CRR AIRB pipeline.

    Module-scoped: pipeline runs once; results are shared across all test methods.

    Arrange:
        - 1 corporate counterparty (CP-P1127-A, GB, GBP)
        - 2 AIRB loans: LN-P1127-ND (non-defaulted) and LN-P1127-D (defaulted)
        - 2 SCRA provisions: 30,000 for ND, 120,000 for D
        - 1 model permission: CORP-AIRB-V1 → corporate, advanced_irb
        - 1 rating row: PD=0.005 for CP-P1127-A
        - ava_amount and other_own_funds_reductions columns on loan parquet

    Act: PipelineOrchestrator().run_with_data(bundle, CRR-IRB config)

    Returns: AggregatedResultBundle with el_summary populated.
    """
    # Arrange
    bundle = RawDataBundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        provisions=pl.scan_parquet(_FIXTURES_DIR / "provision.parquet"),
        model_permissions=pl.scan_parquet(_FIXTURES_DIR / "model_permission.parquet"),
    )

    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )

    # Act
    results = PipelineOrchestrator().run_with_data(bundle, config)
    return results


@pytest.fixture(scope="module")
def p1_127_el_summary(p1_127_pipeline_results: AggregatedResultBundle) -> ELPortfolioSummary:
    """
    Extract and validate the EL summary from the P1.127 pipeline results.

    Fails fast if el_summary is None — all three test methods depend on it.
    """
    summary = p1_127_pipeline_results.el_summary
    assert summary is not None, (
        "P1.127: el_summary must not be None when AIRB exposures are present. "
        "The aggregator failed to produce a portfolio EL summary."
    )
    return summary


# ---------------------------------------------------------------------------
# P1.127 regression-guard acceptance tests
# ---------------------------------------------------------------------------


class TestP1127Art159PoolBAVARegressionGuard:
    """
    P1.127: CRR Art. 159 Pool B — AVA + other_OFR no double-count regression guard.

    Three test methods pin distinct aspects of the per-exposure Pool B accumulation:

    1. test_total_el_shortfall_is_per_exposure_sum
       Confirms total_el_shortfall = 300,000 (the sum of per-exposure shortfalls,
       not a portfolio-level recompute of EL - pool_b).

    2. test_total_pool_b_memo_totals
       Confirms all five portfolio-level memo totals — EL, provisions_allocated,
       ava_amount, other_own_funds_reductions, pool_b — match EXPECTED_* constants.

    3. test_double_count_guards
       Three sentinel assertions:
         (a) total_el_shortfall == 300,000     ← correct per-exposure-sum path
         (b) total_el_shortfall != 223,375     ← rules out portfolio-level recompute
         (c) total_el_shortfall != 325,000     ← rules out AVA-dropped-from-pool-b bug

    Regulatory References:
        - CRR Art. 158(5): defaulted EL = BEEL × EAD
        - CRR Art. 159(1): Pool B = SCRA + AVA + other own funds reductions
        - CRR Art. 159(3): two-branch no-cross-offset rule
    """

    def test_total_el_shortfall_is_per_exposure_sum(
        self,
        p1_127_el_summary: ELPortfolioSummary,
    ) -> None:
        """
        P1.127: total_el_shortfall must be the sum of per-exposure shortfalls.

        Arrange: LN-P1127-ND (shortfall=0) + LN-P1127-D (shortfall=300,000).
        Act:     full CRR AIRB pipeline with Art. 159(3) two-branch rule.
        Assert:  total_el_shortfall == 300,000.00

        Under Art. 159(3) the defaulted pool shortfall is not offset by the
        non-defaulted pool excess, so only the defaulted 300,000 appears here.
        """
        # Arrange
        summary = p1_127_el_summary
        expected = Decimal(str(EXPECTED_TOTAL_SHORTFALL))

        # Assert
        assert summary.total_el_shortfall == pytest.approx(expected, abs=Decimal("0.01")), (
            f"P1.127: total_el_shortfall should be {expected:,.2f} (per-exposure sum of "
            f"shortfall_ND={EXPECTED_SHORTFALL_ND:,.0f} + shortfall_D={EXPECTED_SHORTFALL_D:,.0f}). "
            f"Got {summary.total_el_shortfall:,.2f}."
        )

    def test_total_pool_b_memo_totals(
        self,
        p1_127_el_summary: ELPortfolioSummary,
    ) -> None:
        """
        P1.127: all five portfolio-level Pool B memo totals must match EXPECTED_* constants.

        Arrange:
            LN-P1127-ND: EL=3,375,  prov=30,000, AVA=40,000, other_OFR=10,000, pool_b=80,000
            LN-P1127-D:  EL=450,000, prov=120,000, AVA=25,000, other_OFR=5,000, pool_b=150,000
        Act:     full CRR AIRB pipeline.
        Assert (five sub-assertions — one logical concept each):
            total_expected_loss          == 453,375
            total_provisions_allocated   == 150,000  (SCRA provisions only)
            total_ava_amount             == 65,000
            total_other_own_funds_reductions == 15,000
            total_pool_b                 == 230,000
        """
        # Arrange
        summary = p1_127_el_summary

        # Assert — total expected loss
        assert summary.total_expected_loss == pytest.approx(
            Decimal(str(EXPECTED_TOTAL_EL)), abs=Decimal("0.01")
        ), (
            f"P1.127: total_expected_loss should be {EXPECTED_TOTAL_EL:,.2f} "
            f"(EL_ND={EXPECTED_EL_ND:,.2f} + EL_D={EXPECTED_EL_D:,.2f}). "
            f"Got {summary.total_expected_loss:,.2f}."
        )

        # Assert — provisions allocated
        assert summary.total_provisions_allocated == pytest.approx(
            Decimal(str(EXPECTED_TOTAL_PROV)), abs=Decimal("0.01")
        ), (
            f"P1.127: total_provisions_allocated should be {EXPECTED_TOTAL_PROV:,.2f} "
            f"(prov_ND=30,000 + prov_D=120,000). "
            f"Got {summary.total_provisions_allocated:,.2f}."
        )

        # Assert — AVA amount
        assert summary.total_ava_amount == pytest.approx(
            Decimal(str(EXPECTED_TOTAL_AVA)), abs=Decimal("0.01")
        ), (
            f"P1.127: total_ava_amount should be {EXPECTED_TOTAL_AVA:,.2f} "
            f"(AVA_ND=40,000 + AVA_D=25,000). "
            f"Got {summary.total_ava_amount:,.2f}."
        )

        # Assert — other own funds reductions
        assert summary.total_other_own_funds_reductions == pytest.approx(
            Decimal(str(EXPECTED_TOTAL_OTHER_OFR)), abs=Decimal("0.01")
        ), (
            f"P1.127: total_other_own_funds_reductions should be {EXPECTED_TOTAL_OTHER_OFR:,.2f} "
            f"(other_OFR_ND=10,000 + other_OFR_D=5,000). "
            f"Got {summary.total_other_own_funds_reductions:,.2f}."
        )

        # Assert — total pool B
        assert summary.total_pool_b == pytest.approx(
            Decimal(str(EXPECTED_TOTAL_POOL_B)), abs=Decimal("0.01")
        ), (
            f"P1.127: total_pool_b should be {EXPECTED_TOTAL_POOL_B:,.2f} "
            f"(pool_b_ND={EXPECTED_POOL_B_ND:,.0f} + pool_b_D={EXPECTED_POOL_B_D:,.0f}). "
            f"Got {summary.total_pool_b:,.2f}."
        )

    def test_double_count_guards(
        self,
        p1_127_el_summary: ELPortfolioSummary,
    ) -> None:
        """
        P1.127: three sentinel assertions guard against two known double-count regressions.

        Arrange: same as test_total_el_shortfall_is_per_exposure_sum.
        Act:     full CRR AIRB pipeline.
        Assert (three sub-assertions — one double-count concept each):

          Guard 1 — CORRECT value:
              total_el_shortfall == 300,000.00
              (per-exposure-sum path; Art. 159(3) correctly applied)

          Guard 2 — BUGGY portfolio-level recompute:
              total_el_shortfall != 223,375.00
              (would appear if aggregator computed EL_total − pool_b_total
               = 453,375 − 230,000 instead of summing per-exposure shortfalls)

          Guard 3 — BUGGY AVA dropped from defaulted pool_b:
              total_el_shortfall != 325,000.00
              (would appear if AVA=25,000 were missing from pool_b_D,
               making pool_b_D = 125,000 and shortfall_D = 325,000)
        """
        # Arrange
        summary = p1_127_el_summary
        shortfall = summary.total_el_shortfall

        # Guard 1 — correct per-exposure-sum value
        assert shortfall == pytest.approx(Decimal("300000.00"), abs=Decimal("0.01")), (
            f"P1.127 Guard 1: total_el_shortfall must be 300,000.00 "
            f"(Art. 159(3) defaulted-pool shortfall only). Got {shortfall:,.2f}."
        )

        # Guard 2 — portfolio-level recompute bug (453,375 − 230,000 = 223,375)
        assert shortfall != pytest.approx(
            _BUGGY_SHORTFALL_PORTFOLIO_RECOMPUTE, abs=Decimal("0.01")
        ), (
            f"P1.127 Guard 2 REGRESSION: total_el_shortfall == {_BUGGY_SHORTFALL_PORTFOLIO_RECOMPUTE} "
            f"indicates the aggregator is computing EL_total − pool_b_total "
            f"(portfolio-level recompute) instead of summing per-exposure shortfalls. "
            f"Got {shortfall:,.2f}."
        )

        # Guard 3 — AVA dropped from defaulted pool_b bug (pool_b_D = 125,000 → shortfall = 325,000)
        assert shortfall != pytest.approx(_BUGGY_SHORTFALL_AVA_DROPPED, abs=Decimal("0.01")), (
            f"P1.127 Guard 3 REGRESSION: total_el_shortfall == {_BUGGY_SHORTFALL_AVA_DROPPED} "
            f"indicates AVA was dropped from the defaulted exposure's Pool B "
            f"(expected pool_b_D=150,000 with AVA, got 125,000 without AVA). "
            f"Got {shortfall:,.2f}."
        )
