"""
P1.127: CRR Art. 159 Pool B EL shortfall — AVA + other_OFR no double-count.

Regression-guard acceptance test: verifies that AVA and other_own_funds_reductions
enter Pool B exactly once, are never double-counted, are never silently dropped, and
— on the defaulted loan too — sit in 'B', not 'D' (PS1/26 Art. 159(1)).

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

Art. 159(1) pools (PS1/26 wording; UK CRR Art. 159 is the same ring-fence):
    'A' = 3,375; 'C' = 450,000
    'B' = nd SCRA 30,000 + ALL AVA 65,000 + ALL other_OFR 15,000 = 110,000
    'D' = defaulted SCRA only = 120,000

Art. 159(3): the two-branch split needs 'A' > 'B' AND 'D' > 'C'; here 'A' <= 'B',
so "in all other cases" (c) applies — ONE net figure:
    (B + D) - (A + C) = 230,000 - 453,375 = -223,375 -> total_el_shortfall = 223,375.

P1.210 re-pinned this from 300,000. That figure was the defaulted pool's gross
shortfall (EL_D - pool_b_D) reported beside a separate 76,625 non-defaulted excess,
and its pool_b_D counted the defaulted loan's AVA and other_OFR in 'D'. The old
Guard 2 asserted the rule's answer (223,375) was a bug; it now guards the old figure.

Regulatory References:
    - CRR Art. 158(5): defaulted EL = BEEL × EAD
    - PS1/26 Art. 159(1): 'B' / 'D' composition (UK CRR Art. 159)
    - PS1/26 Art. 159(3)(c): the all-other-cases net
    - CRR Art. 34 / Art. 105: Additional value adjustments (AVA)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, ELPortfolioSummary
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
    EXPECTED_ART159_B,
    EXPECTED_ART159_D,
    EXPECTED_EL_D,
    EXPECTED_EL_ND,
    EXPECTED_POOL_B_D,
    EXPECTED_POOL_B_ND,
    EXPECTED_TOTAL_AVA,
    EXPECTED_TOTAL_EL,
    EXPECTED_TOTAL_EXCESS,
    EXPECTED_TOTAL_OTHER_OFR,
    EXPECTED_TOTAL_POOL_B,
    EXPECTED_TOTAL_PROV,
    EXPECTED_TOTAL_SHORTFALL,
)
from tests.fixtures.raw_bundle import make_raw_bundle  # noqa: E402

# ---------------------------------------------------------------------------
# Regression sentinel values
# ---------------------------------------------------------------------------

# The pre-P1.210 answer: the defaulted pool's gross shortfall EL_D - pool_b_D
# = 450,000 - 150,000, reported beside a separate non-defaulted excess (no
# Art. 159(3)(c) net) with the defaulted AVA / other_OFR counted in 'D'.
_BUGGY_SHORTFALL_UNNETTED = Decimal("300000.00")

# Pool composition fixed but the all-other-cases net still missing:
#     C - D = 450,000 - 120,000 = 330,000 (gross defaulted shortfall)
_BUGGY_SHORTFALL_COMPOSITION_WITHOUT_NET = Decimal("330000.00")

# If the defaulted loan's AVA (25,000) is silently dropped from Pool B:
#     (B - 25,000 + D) - (A + C) = 205,000 - 453,375 = -248,375
_BUGGY_SHORTFALL_AVA_DROPPED = Decimal("248375.00")

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
    bundle = make_raw_bundle(
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

    1. test_total_el_shortfall_is_the_art_159_3_c_net
       Confirms total_el_shortfall = 223,375, the single Art. 159(3)(c) net
       (B + D) - (A + C), and no excess beside it.

    2. test_total_pool_b_memo_totals
       Confirms all five portfolio-level memo totals — EL, provisions_allocated,
       ava_amount, other_own_funds_reductions, pool_b — match EXPECTED_* constants.

    3. test_double_count_guards
       Four sentinel assertions:
         (a) total_el_shortfall == 223,375     ← the Art. 159(3)(c) net
         (b) total_el_shortfall != 300,000     ← rules out the pre-P1.210 unnetted figure
         (c) total_el_shortfall != 330,000     ← rules out composition-fixed-but-unnetted
         (d) total_el_shortfall != 248,375     ← rules out the AVA-dropped-from-Pool-B bug

    Regulatory References:
        - CRR Art. 158(5): defaulted EL = BEEL × EAD
        - PS1/26 Art. 159(1): 'B' / 'D' composition
        - PS1/26 Art. 159(3)(c): the all-other-cases net
    """

    def test_total_el_shortfall_is_the_art_159_3_c_net(
        self,
        p1_127_el_summary: ELPortfolioSummary,
    ) -> None:
        """
        P1.127: total_el_shortfall is the single Art. 159(3)(c) net, with no excess.

        Arrange: 'A' = 3,375, 'B' = 110,000 (AVA / other_OFR of BOTH loans),
                 'C' = 450,000, 'D' = 120,000 (defaulted SCRA only).
        Act:     full CRR AIRB pipeline.
        Assert:  'A' <= 'B', so no two-branch split; total_el_shortfall ==
                 (A + C) - (B + D) = 223,375.00 and total_el_excess == 0.
        """
        # Arrange
        summary = p1_127_el_summary
        expected = Decimal(str(EXPECTED_TOTAL_SHORTFALL))

        # Assert
        assert summary.art_159_3_applies is False
        assert summary.total_el_shortfall == pytest.approx(expected, abs=Decimal("0.01")), (
            f"P1.127: total_el_shortfall should be {expected:,.2f} = (A + C) - (B + D) with "
            f"B={EXPECTED_ART159_B:,.0f}, D={EXPECTED_ART159_D:,.0f} (PS1/26 Art. 159(3)(c)). "
            f"Got {summary.total_el_shortfall:,.2f}."
        )
        assert summary.total_el_excess == pytest.approx(
            Decimal(str(EXPECTED_TOTAL_EXCESS)), abs=Decimal("0.01")
        ), "P1.127: one net figure under Art. 159(3)(c) — no excess beside the shortfall"

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
        P1.127: the correct net, and sentinels for three known wrong answers.

        Arrange: same as test_total_el_shortfall_is_the_art_159_3_c_net.
        Act:     full CRR AIRB pipeline.
        Assert (one concept each):

          Guard 1 — CORRECT value:
              total_el_shortfall == 223,375.00 (PS1/26 Art. 159(3)(c) net)

          Guard 2 — pre-P1.210 unnetted figure:
              total_el_shortfall != 300,000.00
              (the defaulted pool's gross shortfall with its AVA / other_OFR in
               'D', reported beside a separate non-defaulted excess)

          Guard 3 — pools fixed, net missing:
              total_el_shortfall != 330,000.00 ('C' - 'D' reported gross)

          Guard 4 — AVA dropped from Pool B:
              total_el_shortfall != 248,375.00
              (the defaulted loan's AVA = 25,000 missing from 'B')
        """
        # Arrange
        summary = p1_127_el_summary
        shortfall = summary.total_el_shortfall

        # Guard 1 — the Art. 159(3)(c) net
        assert shortfall == pytest.approx(Decimal("223375.00"), abs=Decimal("0.01")), (
            f"P1.127 Guard 1: total_el_shortfall must be 223,375.00 "
            f"((A + C) - (B + D), PS1/26 Art. 159(3)(c)). Got {shortfall:,.2f}."
        )

        # Guard 2 — the pre-P1.210 unnetted figure
        assert shortfall != pytest.approx(_BUGGY_SHORTFALL_UNNETTED, abs=Decimal("0.01")), (
            f"P1.127 Guard 2 REGRESSION: total_el_shortfall == {_BUGGY_SHORTFALL_UNNETTED} "
            f"is the defaulted pool's gross shortfall: the Art. 159(3)(c) net is missing "
            f"and the defaulted AVA / other_OFR were counted in 'D'. Got {shortfall:,.2f}."
        )

        # Guard 3 — composition fixed, all-other-cases net missing
        assert shortfall != pytest.approx(
            _BUGGY_SHORTFALL_COMPOSITION_WITHOUT_NET, abs=Decimal("0.01")
        ), (
            f"P1.127 Guard 3 REGRESSION: total_el_shortfall == "
            f"{_BUGGY_SHORTFALL_COMPOSITION_WITHOUT_NET} is 'C' - 'D' reported gross — "
            f"the Art. 159(3)(c) net is missing. Got {shortfall:,.2f}."
        )

        # Guard 4 — AVA dropped from Pool B
        assert shortfall != pytest.approx(_BUGGY_SHORTFALL_AVA_DROPPED, abs=Decimal("0.01")), (
            f"P1.127 Guard 4 REGRESSION: total_el_shortfall == {_BUGGY_SHORTFALL_AVA_DROPPED} "
            f"indicates the defaulted loan's AVA (25,000) was dropped from Pool B. "
            f"Got {shortfall:,.2f}."
        )
