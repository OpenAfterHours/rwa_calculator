"""
P5.15 — Basel 3.1 Art. 123A(1)(b)(ii): 0.2% retail portfolio granularity sub-condition.

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor → SACalculator → Aggregator

Scenario design:
    The current ``_build_qualifies_as_retail_expr`` enforces only the GBP 880k
    aggregate-threshold limb of Art. 123A(1)(b)(ii).  It omits the *second* limb of
    the same sub-paragraph: "no single exposure may exceed 0.2% of the total retail
    portfolio."  This scenario adds that cross-row granularity test as a self-contained
    Polars window expression inside the classifier.

    All obligors in the fixture are:
        - cp_entity_type="individual" (natural-person → Art. 123A(1)(b) path)
        - cp_is_managed_as_retail=True (pool-management limb already satisfied)
        - sme_size_metric_gbp=null (SME auto-qualify branch does NOT fire)
        - drawn ≤ GBP 2,000 (well below GBP 880k — threshold limb cannot trip)

    Portfolio (502 obligors, Basel 3.1, SA-only):
        - 500 control obligors: GBP 1,000 each
        - RETAIL-BREACH:       GBP 2,000
        - RETAIL-CONTROL-PASS: GBP 1,000
        portfolio_total = 503,000 GBP
        0.2% limit      = 0.002 × 503,000 = 1,006.00 GBP

    RETAIL-BREACH:        2,000 / 503,000 = 0.003976 > 0.002 → FAIL (granularity)
        → qualifies_as_retail = False → CORPORATE → RW = 100% → RWA = 2,000
    RETAIL-CONTROL-PASS:  1,000 / 503,000 = 0.001988 < 0.002 → PASS
        → qualifies_as_retail = True  → RETAIL_OTHER → RW = 75%  → RWA = 750

    Anti-confound: assert lending_group_adjusted_exposure(BREACH) < 880,000 to
    confirm the threshold limb (GBP 880k) is NOT what drives the re-route.

Pre-fix failure mode (current engine, Wave 3 target):
    RETAIL-BREACH lands in retail_other (RW=0.75, RWA=1,500) because the
    granularity limb is not implemented.  The primary assertion
        assert exposure_class == "corporate"
    FAILS with:
        AssertionError: assert 'retail_other' == 'corporate'

Post-fix expected behaviour (Wave 4):
    RETAIL-BREACH: exposure_class=corporate, risk_weight=1.00, rwa_final=2,000.
    RETAIL-CONTROL-PASS: exposure_class=retail_other, risk_weight=0.75, rwa_final=750.

Regulatory references:
    - PRA PS1/26 Art. 123A(1)(b)(ii): retail granularity sub-condition (0.2%)
    - PRA PS1/26 Art. 122 Table 6: unrated corporate SA RW = 100%
    - PRA PS1/26 Art. 123(3)(b): regulatory retail SA RW = 75%
    - BCBS CRE20.66: granularity criterion
    - src/rwa_calc/engine/classifier.py: _build_qualifies_as_retail_expr (insertion point)
    - tests/fixtures/p5_15/p5_15.py: portfolio constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p5_15.p5_15 import (
    BREACH_DRAWN,
    EXPECTED_RW_CORPORATE,
    EXPECTED_RW_RETAIL,
    EXPECTED_RWA_BREACH,
    EXPECTED_RWA_PASS,
    GRANULARITY_LIMIT,
    LOAN_BREACH,
    LOAN_CONTROL_PASS,
    PASS_DRAWN,
    PORTFOLIO_TOTAL,
    build_p5_15_bundle,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2027, 1, 4)
_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p5_15"

# Absolute tolerances
_RW_TOL = 1e-6
_RWA_TOL = 0.50  # 50p

# GBP 880k aggregate threshold (Art. 123A(1)(b)(ii) first limb)
_RETAIL_THRESHOLD_GBP = 880_000.0

# Pre-fix (current engine) values for RETAIL-BREACH
# Engine does not implement the granularity limb → breach stays retail
_PRE_FIX_EXPOSURE_CLASS_BREACH = "retail_other"
_PRE_FIX_RW_BREACH = 0.75
_PRE_FIX_RWA_BREACH = BREACH_DRAWN * _PRE_FIX_RW_BREACH  # 1,500.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b31_sa_config() -> CalculationConfig:
    """Basel 3.1 SA-only config with 2027 reporting date (post-effective date)."""
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


def _run_b31_pipeline() -> pl.DataFrame:
    """
    Run the P5.15 fixture portfolio through the Basel 3.1 SA pipeline.

    Arrange: 502-obligor portfolio (500 control + RETAIL-BREACH + RETAIL-CONTROL-PASS).
             All natural persons, all managed-as-retail, all below GBP 880k threshold.
             Basel 3.1 SA-only, 2027-01-04 reporting date.
    Act:     PipelineOrchestrator.run_with_data → sa_results.
    Return:  Collected SA results DataFrame.
    """
    bundle = build_p5_15_bundle(fixtures_dir=_FIXTURES_DIR)
    config = _b31_sa_config()
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None, (
        "P5.15: SA results should not be None under PermissionMode.STANDARDISED. "
        "Check CalculationConfig.basel_3_1() factory."
    )
    return cast(pl.DataFrame, results.sa_results.collect())


def _get_row(df: pl.DataFrame, loan_ref: str) -> dict:
    """Return the single SA result row for the given loan reference."""
    rows = df.filter(pl.col("exposure_reference") == loan_ref).to_dicts()
    assert len(rows) == 1, (
        f"P5.15: expected exactly 1 SA result row for loan_ref={loan_ref!r}. "
        f"Got {len(rows)}. Exposure references present: "
        f"{df['exposure_reference'].to_list()[:10]} ..."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture (run once per test session for this file)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p5_15_b31_sa_results() -> pl.DataFrame:
    """
    Run P5.15 portfolio through Basel 3.1 SA pipeline and return collected SA results.

    Module-scoped so the 502-row pipeline runs exactly once for this test file.

    Arrange: build_p5_15_bundle() — 502 personal loans, Basel 3.1 SA-only.
    Act:     PipelineOrchestrator().run_with_data(bundle, config).sa_results.collect().
    Return:  Collected SA DataFrame (one row per loan, ≥ 502 rows).
    """
    return _run_b31_pipeline()


@pytest.fixture(scope="module")
def breach_row(p5_15_b31_sa_results: pl.DataFrame) -> dict:
    """Return the SA result dict for RETAIL-BREACH (LOAN-RETAIL-BREACH)."""
    return _get_row(p5_15_b31_sa_results, LOAN_BREACH)


@pytest.fixture(scope="module")
def pass_row(p5_15_b31_sa_results: pl.DataFrame) -> dict:
    """Return the SA result dict for RETAIL-CONTROL-PASS (LOAN-RETAIL-CTRL-PASS)."""
    return _get_row(p5_15_b31_sa_results, LOAN_CONTROL_PASS)


# ===========================================================================
# RETAIL-BREACH tests (load-bearing — FAIL pre-fix)
# ===========================================================================


class TestP515RetailBreachGranularityFires:
    """
    RETAIL-BREACH: a natural-person obligor whose single exposure (GBP 2,000)
    exceeds 0.2% of the total retail portfolio (1,006 GBP limit at this scale).

    Pre-fix (current engine): granularity limb absent → obligor stays in
    retail_other (qualifies_as_retail=True, RW=0.75, RWA=1,500).

    Post-fix: the engine adds the 0.2% window expression to
    _build_qualifies_as_retail_expr.  RETAIL-BREACH fails the granularity limb
    → qualifies_as_retail=False → re-routes to CORPORATE (Art. 123(3)(c) /
    classifier.py L896-901) → RW=1.00 (Art. 122 Table 6) → RWA=2,000.

    The load-bearing assertion is exposure_class == "corporate".  All other
    assertions in this class follow from that classification decision.
    """

    # -------------------------------------------------------------------------
    # LOAD-BEARING: exposure_class re-route (FAILS pre-fix)
    # -------------------------------------------------------------------------

    def test_p5_15_breach_exposure_class_is_corporate(self, breach_row: dict) -> None:
        """
        RETAIL-BREACH: exposure_class = "corporate" after granularity re-route.

        Art. 123A(1)(b)(ii): a retail candidate whose single exposure exceeds
        0.2% of the total retail portfolio does not qualify as retail.
        Art. 123(3)(c) / classifier re-route: qualifies_as_retail=False on a
        natural-person retail_other row → re-classed to CORPORATE.

        Arrange: RETAIL-BREACH drawn=2,000, portfolio_total=503,000.
                 granularity_ratio = 2,000 / 503,000 = 0.003976 > 0.002 → FAIL.
                 All conditions other than the granularity limb pass
                 (threshold < 880k, managed-as-retail=True, non-SME).
        Act:     Basel 3.1 SA pipeline → exposure_class.
        Assert:  exposure_class == "corporate".

        Pre-fix failure:
            Current engine does not implement the granularity limb.
            exposure_class == "retail_other" (qualifies_as_retail stays True).
            assert 'retail_other' == 'corporate'  →  FAILS.
        """
        # Assert — LOAD-BEARING, FAILS pre-fix
        actual_class = breach_row["exposure_class"]
        assert actual_class == "corporate", (
            f"P5.15 BREACH: exposure_class should be 'corporate' after "
            f"Art. 123A(1)(b)(ii) granularity re-route. "
            f"Got {actual_class!r}. "
            f"granularity_ratio = {BREACH_DRAWN:,.0f} / {PORTFOLIO_TOTAL:,.0f} "
            f"= {BREACH_DRAWN / PORTFOLIO_TOTAL:.6f} > 0.002 → qualifies_as_retail must be False. "
            f"Pre-fix: granularity limb absent → exposure stays retail_other "
            f"(qualifies_as_retail=True, RW={_PRE_FIX_RW_BREACH:.2f}, "
            f"RWA={_PRE_FIX_RWA_BREACH:,.0f})."
        )

    def test_p5_15_breach_qualifies_as_retail_is_false(self, breach_row: dict) -> None:
        """
        RETAIL-BREACH: qualifies_as_retail = False (granularity limb fails).

        Arrange/Act: as above.
        Assert:  qualifies_as_retail == False.

        Pre-fix failure:
            qualifies_as_retail == True (granularity limb not implemented).
        """
        actual = breach_row["qualifies_as_retail"]
        assert actual is False, (
            f"P5.15 BREACH: qualifies_as_retail should be False "
            f"(Art. 123A(1)(b)(ii) granularity limb breached: "
            f"{BREACH_DRAWN:,.0f} / {PORTFOLIO_TOTAL:,.0f} > 0.002). "
            f"Got qualifies_as_retail={actual!r}. "
            f"Pre-fix: True (granularity limb absent)."
        )

    def test_p5_15_breach_risk_weight_is_100_pct(self, breach_row: dict) -> None:
        """
        RETAIL-BREACH: risk_weight = 1.00 (Art. 122 Table 6, unrated corporate, Basel 3.1).

        Post-fix: exposure_class=corporate, unrated → RW=1.00.
        Pre-fix:  exposure_class=retail_other → RW=0.75.

        Arrange/Act: as above.
        Assert:  risk_weight ≈ 1.00 (abs=1e-6).

        Pre-fix failure: assert 0.75 == pytest.approx(1.00).
        """
        rw = float(breach_row["risk_weight"])
        assert rw == pytest.approx(EXPECTED_RW_CORPORATE, abs=_RW_TOL), (
            f"P5.15 BREACH: risk_weight should be {EXPECTED_RW_CORPORATE:.2f} "
            f"(Art. 122 Table 6 unrated corporate, Basel 3.1). "
            f"Got {rw:.6f}. "
            f"Pre-fix value: {_PRE_FIX_RW_BREACH:.2f} "
            f"(retail_other RW — granularity limb not applied)."
        )

    def test_p5_15_breach_rwa_is_2000(self, breach_row: dict) -> None:
        """
        RETAIL-BREACH: rwa_final = 2,000 (EAD 2,000 × RW 100%, no SME factor under B31).

        Post-fix: 2,000 × 1.00 = 2,000.
        Pre-fix:  2,000 × 0.75 = 1,500.

        Arrange/Act: as above.
        Assert:  rwa_final ≈ 2,000 (abs=0.50).

        Pre-fix failure: assert 1,500 == pytest.approx(2,000).
        """
        rwa = float(breach_row["rwa_final"])
        assert rwa == pytest.approx(EXPECTED_RWA_BREACH, abs=_RWA_TOL), (
            f"P5.15 BREACH: rwa_final should be {EXPECTED_RWA_BREACH:,.2f} "
            f"(EAD {BREACH_DRAWN:,.0f} × RW {EXPECTED_RW_CORPORATE:.2f}). "
            f"Got {rwa:,.2f}. "
            f"Pre-fix value: {_PRE_FIX_RWA_BREACH:,.2f} "
            f"(retail RW still applied — granularity branch absent)."
        )

    # -------------------------------------------------------------------------
    # ANTI-CONFOUND: threshold limb must NOT have fired
    # -------------------------------------------------------------------------

    def test_p5_15_breach_lending_group_adjusted_exposure_below_880k(
        self, breach_row: dict
    ) -> None:
        """
        RETAIL-BREACH: lending_group_adjusted_exposure < 880,000 (threshold limb did NOT fire).

        If the GBP 880k threshold (Art. 123A(1)(b)(ii) first limb) fired, the
        re-route would also produce qualifies_as_retail=False, but for a different
        reason.  This assertion proves the failure is attributable solely to the
        new 0.2% granularity limb — not the threshold limb.

        Arrange: RETAIL-BREACH drawn=2,000 (max across all 502 loans is 2,000).
        Act:     lending_group_adjusted_exposure from SA result.
        Assert:  lending_group_adjusted_exposure < 880,000.
        """
        lgae = float(breach_row["lending_group_adjusted_exposure"])
        assert lgae < _RETAIL_THRESHOLD_GBP, (
            f"P5.15 BREACH anti-confound: lending_group_adjusted_exposure "
            f"{lgae:,.2f} should be < {_RETAIL_THRESHOLD_GBP:,.0f} "
            f"(GBP 880k threshold must NOT have fired — the granularity limb alone "
            f"drives the re-route). "
            f"Got {lgae:,.2f}."
        )

    def test_p5_15_breach_supporting_factor_is_1(self, breach_row: dict) -> None:
        """
        RETAIL-BREACH: supporting_factor = 1.0 (SME supporting factor removed under B31).

        Basel 3.1 removes the CRR Art. 501 SME supporting factor (0.7619).
        A corporate exposure under B31 has supporting_factor = 1.0.

        Arrange/Act: as above.
        Assert:  supporting_factor ≈ 1.0 (abs=1e-6).
        """
        sf = float(breach_row["supporting_factor"])
        assert sf == pytest.approx(1.0, abs=_RW_TOL), (
            f"P5.15 BREACH: supporting_factor should be 1.0 "
            f"(Basel 3.1 removes the SME supporting factor). "
            f"Got {sf:.6f}."
        )

    def test_p5_15_breach_ead_is_2000(self, breach_row: dict) -> None:
        """
        RETAIL-BREACH: ead_final = 2,000 (drawn 2,000, undrawn 0, interest 0, no CRM).

        Arrange/Act: as above.
        Assert:  ead_final ≈ 2,000 (abs=0.50).
        """
        ead = float(breach_row["ead_final"])
        assert ead == pytest.approx(BREACH_DRAWN, abs=_RWA_TOL), (
            f"P5.15 BREACH: ead_final should be {BREACH_DRAWN:,.0f}. Got {ead:,.2f}."
        )


# ===========================================================================
# RETAIL-CONTROL-PASS tests (GREEN now, must stay green post-fix)
# ===========================================================================


class TestP515ControlPassGranularityPasses:
    """
    RETAIL-CONTROL-PASS: a natural-person obligor whose single exposure (GBP 1,000)
    is below the 0.2% granularity limit (1,006 GBP).

    Both the threshold limb (1,000 << 880,000) and the granularity limb
    (1,000 / 503,000 = 0.001988 < 0.002) are satisfied.
    qualifies_as_retail=True → stays RETAIL_OTHER → RW=0.75 → RWA=750.

    These tests pass today (pre-fix) and must remain green post-fix.
    They verify the granularity implementation does not incorrectly re-route
    exposures that are comfortably within the 0.2% limit.
    """

    def test_p5_15_pass_exposure_class_is_retail_other(self, pass_row: dict) -> None:
        """
        RETAIL-CONTROL-PASS: exposure_class = "retail_other" (granularity limb passes).

        1,000 / 503,000 = 0.001988 < 0.002 → qualifies_as_retail=True → stays retail.

        Arrange: RETAIL-CONTROL-PASS drawn=1,000, portfolio_total=503,000.
                 granularity_ratio = 0.001988 < 0.002 → PASS.
        Act:     Basel 3.1 SA pipeline → exposure_class.
        Assert:  exposure_class == "retail_other".
        """
        actual_class = pass_row["exposure_class"]
        assert actual_class == "retail_other", (
            f"P5.15 PASS: exposure_class should be 'retail_other' "
            f"(granularity_ratio = {PASS_DRAWN:,.0f} / {PORTFOLIO_TOTAL:,.0f} "
            f"= {PASS_DRAWN / PORTFOLIO_TOTAL:.6f} < 0.002 → PASS). "
            f"Got {actual_class!r}. "
            f"Post-fix regression: the granularity branch must not fire for "
            f"exposures comfortably below the 0.2% limit."
        )

    def test_p5_15_pass_qualifies_as_retail_is_true(self, pass_row: dict) -> None:
        """
        RETAIL-CONTROL-PASS: qualifies_as_retail = True.

        Arrange/Act: as above.
        Assert:  qualifies_as_retail == True.
        """
        actual = pass_row["qualifies_as_retail"]
        assert actual is True, (
            f"P5.15 PASS: qualifies_as_retail should be True "
            f"(granularity_ratio = {PASS_DRAWN / PORTFOLIO_TOTAL:.6f} < 0.002). "
            f"Got {actual!r}."
        )

    def test_p5_15_pass_risk_weight_is_75_pct(self, pass_row: dict) -> None:
        """
        RETAIL-CONTROL-PASS: risk_weight = 0.75 (Art. 123(3)(b) regulatory retail).

        Arrange/Act: as above.
        Assert:  risk_weight ≈ 0.75 (abs=1e-6).
        """
        rw = float(pass_row["risk_weight"])
        assert rw == pytest.approx(EXPECTED_RW_RETAIL, abs=_RW_TOL), (
            f"P5.15 PASS: risk_weight should be {EXPECTED_RW_RETAIL:.2f} "
            f"(Art. 123(3)(b) regulatory retail). "
            f"Got {rw:.6f}."
        )

    def test_p5_15_pass_rwa_is_750(self, pass_row: dict) -> None:
        """
        RETAIL-CONTROL-PASS: rwa_final = 750 (EAD 1,000 × RW 0.75).

        Arrange/Act: as above.
        Assert:  rwa_final ≈ 750 (abs=0.50).
        """
        rwa = float(pass_row["rwa_final"])
        assert rwa == pytest.approx(EXPECTED_RWA_PASS, abs=_RWA_TOL), (
            f"P5.15 PASS: rwa_final should be {EXPECTED_RWA_PASS:,.2f} "
            f"(EAD {PASS_DRAWN:,.0f} × RW {EXPECTED_RW_RETAIL:.2f}). "
            f"Got {rwa:,.2f}."
        )

    def test_p5_15_pass_ead_is_1000(self, pass_row: dict) -> None:
        """
        RETAIL-CONTROL-PASS: ead_final = 1,000 (drawn 1,000, undrawn 0, interest 0).

        Arrange/Act: as above.
        Assert:  ead_final ≈ 1,000 (abs=0.50).
        """
        ead = float(pass_row["ead_final"])
        assert ead == pytest.approx(PASS_DRAWN, abs=_RWA_TOL), (
            f"P5.15 PASS: ead_final should be {PASS_DRAWN:,.0f}. Got {ead:,.2f}."
        )


# ===========================================================================
# Cross-arm invariant: granularity discriminates correctly between breach and pass
# ===========================================================================


class TestP515GranularityDiscriminates:
    """
    Cross-arm invariant: the granularity branch re-routes RETAIL-BREACH to
    corporate but leaves RETAIL-CONTROL-PASS in retail_other.

    Pre-fix: both arms have exposure_class=retail_other (granularity absent).
    Post-fix: exactly one arm (RETAIL-BREACH) is corporate.

    This guard catches regression in both directions after Wave 4:
    - Over-broad: granularity fires for the passing arm.
    - Under-narrow: granularity still does not fire for the breaching arm.
    """

    def test_p5_15_exactly_one_arm_reclassed_to_corporate(
        self, breach_row: dict, pass_row: dict
    ) -> None:
        """
        Exactly one arm has exposure_class == "corporate": RETAIL-BREACH only.

        Pre-fix: zero arms have corporate (granularity absent).
        Post-fix: exactly one arm (RETAIL-BREACH) is corporate.

        Arrange: breach_row (loan_ref=LOAN_BREACH) and pass_row (loan_ref=LOAN_CONTROL_PASS).
        Act:     exposure_class from each result row.
        Assert:  breach exposure_class=corporate, pass exposure_class=retail_other.

        The primary failure mode is the same as the load-bearing test:
            breach_row["exposure_class"] == "retail_other"  →  FAILS.
        """
        breach_class = breach_row["exposure_class"]
        pass_class = pass_row["exposure_class"]

        assert breach_class == "corporate", (
            f"P5.15 cross-arm: RETAIL-BREACH (loan={LOAN_BREACH!r}) should be 'corporate' "
            f"post-fix. Got {breach_class!r}. "
            f"granularity_ratio_breach={BREACH_DRAWN / PORTFOLIO_TOTAL:.6f} > 0.002 → must re-route. "
            f"Pre-fix: both arms are 'retail_other' (granularity limb absent)."
        )
        assert pass_class == "retail_other", (
            f"P5.15 cross-arm: RETAIL-CONTROL-PASS (loan={LOAN_CONTROL_PASS!r}) should "
            f"stay 'retail_other'. Got {pass_class!r}. "
            f"granularity_ratio_pass={PASS_DRAWN / PORTFOLIO_TOTAL:.6f} < 0.002 → must NOT re-route."
        )

    def test_p5_15_rwa_delta_between_breach_and_pass(
        self, breach_row: dict, pass_row: dict
    ) -> None:
        """
        RWA delta: breach obligor pays GBP 1,250 more than it would as retail.

        Post-fix:
            rwa_final(BREACH) = 2,000 (CORPORATE 100%)
            rwa_final(PASS)   = 750   (RETAIL 75%)
            delta = 2,000 - 750 = 1,250
        Pre-fix:
            rwa_final(BREACH) = 1,500 (retail, no granularity)
            rwa_final(PASS)   = 750
            delta = 750

        Arrange: both rows.
        Act:     rwa_final(breach) - rwa_final(pass).
        Assert:  delta ≈ 1,250 (abs=1.00).

        Pre-fix failure: delta = 750 ≠ 1,250.
        """
        rwa_breach = float(breach_row["rwa_final"])
        rwa_pass = float(pass_row["rwa_final"])
        delta = rwa_breach - rwa_pass
        expected_delta = EXPECTED_RWA_BREACH - EXPECTED_RWA_PASS  # 2,000 - 750 = 1,250

        assert delta == pytest.approx(expected_delta, abs=1.0), (
            f"P5.15 cross-arm: rwa_final delta should be {expected_delta:,.0f} "
            f"(breach={EXPECTED_RWA_BREACH:,.0f} - pass={EXPECTED_RWA_PASS:,.0f}). "
            f"Got breach={rwa_breach:,.2f}, pass={rwa_pass:,.2f}, "
            f"delta={delta:,.2f}. "
            f"Pre-fix delta={_PRE_FIX_RWA_BREACH - EXPECTED_RWA_PASS:,.0f} "
            f"(breach stays retail at RW={_PRE_FIX_RW_BREACH:.2f})."
        )


# ===========================================================================
# Portfolio arithmetic constants (static invariant, always passes)
# ===========================================================================


class TestP515PortfolioArithmetic:
    """
    Verify that the fixture-builder arithmetic constants are internally consistent.

    These assertions are purely mathematical — no pipeline invocation.
    They are a fast sanity check that the constants imported from p5_15.py
    match the scenario proposal's worked example and the 0.2% limit.
    """

    def test_p5_15_portfolio_total_is_503000(self) -> None:
        """PORTFOLIO_TOTAL == 503,000 GBP (500×1,000 + 2,000 + 1,000)."""
        assert pytest.approx(503_000.0, abs=0.01) == PORTFOLIO_TOTAL, (
            f"PORTFOLIO_TOTAL should be 503,000. Got {PORTFOLIO_TOTAL:,.2f}."
        )

    def test_p5_15_granularity_limit_is_1006(self) -> None:
        """GRANULARITY_LIMIT == 1,006.00 GBP (0.2% × 503,000)."""
        assert pytest.approx(1_006.0, abs=0.01) == GRANULARITY_LIMIT, (
            f"GRANULARITY_LIMIT should be 1,006.00. Got {GRANULARITY_LIMIT:,.2f}."
        )

    def test_p5_15_breach_exceeds_granularity_limit(self) -> None:
        """BREACH_DRAWN (2,000) > GRANULARITY_LIMIT (1,006) → the limit bites."""
        assert BREACH_DRAWN > GRANULARITY_LIMIT, (
            f"BREACH_DRAWN {BREACH_DRAWN:,.0f} must exceed GRANULARITY_LIMIT "
            f"{GRANULARITY_LIMIT:,.2f} for the scenario to be discriminating."
        )

    def test_p5_15_pass_is_below_granularity_limit(self) -> None:
        """PASS_DRAWN (1,000) < GRANULARITY_LIMIT (1,006) → the limit does not bite."""
        assert PASS_DRAWN < GRANULARITY_LIMIT, (
            f"PASS_DRAWN {PASS_DRAWN:,.0f} must be below GRANULARITY_LIMIT "
            f"{GRANULARITY_LIMIT:,.2f} for the control arm to pass."
        )

    def test_p5_15_breach_and_pass_below_880k_threshold(self) -> None:
        """Both breach (2,000) and pass (1,000) are well below GBP 880k threshold."""
        assert BREACH_DRAWN < _RETAIL_THRESHOLD_GBP, (
            f"BREACH_DRAWN {BREACH_DRAWN:,.0f} must be < {_RETAIL_THRESHOLD_GBP:,.0f} "
            f"so the 880k threshold limb cannot fire."
        )
        assert PASS_DRAWN < _RETAIL_THRESHOLD_GBP, (
            f"PASS_DRAWN {PASS_DRAWN:,.0f} must be < {_RETAIL_THRESHOLD_GBP:,.0f}."
        )
