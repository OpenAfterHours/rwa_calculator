"""
P5.15 / RE-04 — the optional 0.2% retail granularity test, and its default (off).

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor → SACalculator → Aggregator

Premise correction (RE-04, 2026-11). P5.15 added the 0.2%-of-portfolio test as "the
second limb of Art. 123A(1)(b)(ii)". PS1/26 has no such limb. Art. 123A(1)(b) reads,
verbatim:

    "(ii) the total amount (including defaulted exposures) owed to the institution,
    its parent undertakings, its subsidiaries and subsidiaries of its parent
    undertakings by the obligor or group of connected clients, excluding all
    residential real estate exposures, does not exceed GBP 880,000;
    (iii) the exposure is one of a significant number of exposures with similar
    characteristics such that the risks associated with such exposures are
    substantially reduced."

A text search of PS1/26 Appendix 1 finds no retail "0.2%" or "granular" limb — the
0.2% test is BCBS CRE20.66, which the PRA did not adopt. So the engine default is
``enforce_retail_granularity=False``; a firm may still ELECT the 0.2% test as its
method of evidencing the qualitative (iii). This change LOWERS Basel 3.1 RWA for any
natural person the 0.2% test used to exclude (for a portfolio under 500 obligors,
every one of them). And under RE-03 an obligor failing the elected test is a
non-regulatory retail exposure (Art. 123(3)(c) 100%), not a corporate.

Portfolio (502 obligors, Basel 3.1, SA-only, all natural persons, managed as retail,
all far below GBP 880k):
    - 500 control obligors: GBP 1,000 each
    - RETAIL-BREACH:       GBP 2,000
    - RETAIL-CONTROL-PASS: GBP 1,000
    portfolio_total = 503,000; 0.2% limit = 1,006.00

Elected method (``enforce_retail_granularity=True``):
    RETAIL-BREACH: 2,000 / 503,000 = 0.003976 > 0.002 → not regulatory retail
        → RETAIL_OTHER (Art. 123(1)(a)) at 100% (Art. 123(3)(c)) → RWA 2,000
    RETAIL-CONTROL-PASS: 0.001988 < 0.002 → regulatory retail 75% → RWA 750
Default config (no 0.2% test):
    RETAIL-BREACH: regulatory retail 75% → RWA 1,500 (was 2,000 under the old default)

Regulatory references:
    - PRA PS1/26 Art. 123(1)(a), 123(3)(b)/(c), 123A(1)(b)(ii)/(iii)
    - BCBS CRE20.66: the 0.2% criterion (not adopted by the PRA)
    - engine/classify/attributes.py: _build_qualifies_as_retail_expr
    - tests/fixtures/p5_15/p5_15.py: portfolio constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p5_15.p5_15 import (
    BREACH_DRAWN,
    EXPECTED_RW_NON_REGULATORY_RETAIL,
    EXPECTED_RW_RETAIL,
    EXPECTED_RWA_BREACH,
    EXPECTED_RWA_BREACH_DEFAULT,
    EXPECTED_RWA_PASS,
    GRANULARITY_LIMIT,
    LOAN_BREACH,
    LOAN_CONTROL_PASS,
    NUM_CTRL_OBLIGORS,
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

# GBP 880k aggregate threshold (Art. 123A(1)(b)(ii) — its only limb)
_RETAIL_THRESHOLD_GBP = 880_000.0

# Values for RETAIL-BREACH when the 0.2% test is NOT applied (the default)
_LIMB_OFF_RW_BREACH = EXPECTED_RW_RETAIL
_LIMB_OFF_RWA_BREACH = EXPECTED_RWA_BREACH_DEFAULT  # 1,500.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b31_sa_config(*, enforce_retail_granularity: bool) -> CalculationConfig:
    """Basel 3.1 SA-only config with 2027 reporting date (post-effective date)."""
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
        enforce_retail_granularity=enforce_retail_granularity,
    )


def _run_b31_pipeline(*, enforce_retail_granularity: bool = True) -> pl.DataFrame:
    """
    Run the P5.15 fixture portfolio through the Basel 3.1 SA pipeline.

    Arrange: 502-obligor portfolio (500 control + RETAIL-BREACH + RETAIL-CONTROL-PASS).
             All natural persons, all managed-as-retail, all below GBP 880k threshold.
             Basel 3.1 SA-only, 2027-01-04 reporting date.
    Act:     PipelineOrchestrator.run_with_data → sa_results.
    Return:  Collected SA results DataFrame.
    """
    bundle = build_p5_15_bundle(fixtures_dir=_FIXTURES_DIR)
    config = _b31_sa_config(enforce_retail_granularity=enforce_retail_granularity)
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None, (
        "P5.15: SA results should not be None under PermissionMode.STANDARDISED. "
        "Check CalculationConfig.basel_3_1() factory."
    )
    return results.sa_results.collect()


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
# RETAIL-BREACH tests — the 0.2% test ELECTED (optional firm method)
# ===========================================================================


class TestP515RetailBreachElectedGranularity:
    """
    RETAIL-BREACH with ``enforce_retail_granularity=True``: a natural-person obligor
    whose single exposure (GBP 2,000) exceeds 0.2% of the retail portfolio (1,006).

    The elected test treats the obligor as failing Art. 123A(1)(b)(iii), so it is
    not regulatory retail. Under PS1/26 Art. 123(1)(a) it is still a retail exposure
    and Art. 123(3)(c) weights it at 100% (RE-03) — the class is RETAIL_OTHER, not
    CORPORATE as the pre-RE-03 engine had it. The RWA (2,000) is unchanged by RE-03
    because the unrated corporate weight was also 100%.
    """

    def test_p5_15_breach_stays_retail_other(self, breach_row: dict) -> None:
        """RETAIL-BREACH: exposure_class = "retail_other" (Art. 123(1)(a), RE-03)."""
        actual_class = breach_row["exposure_class"]
        assert actual_class == "retail_other", (
            f"P5.15 BREACH: a natural person failing the elected 0.2% test is a "
            f"non-regulatory RETAIL exposure under PS1/26 Art. 123(1)(a); got {actual_class!r}."
        )

    def test_p5_15_breach_qualifies_as_retail_is_false(self, breach_row: dict) -> None:
        """RETAIL-BREACH: qualifies_as_retail = False (elected 0.2% test fails)."""
        actual = breach_row["qualifies_as_retail"]
        assert actual is False, (
            f"P5.15 BREACH: qualifies_as_retail should be False "
            f"({BREACH_DRAWN:,.0f} / {PORTFOLIO_TOTAL:,.0f} > 0.002). Got {actual!r}."
        )

    def test_p5_15_breach_risk_weight_is_100_pct(self, breach_row: dict) -> None:
        """RETAIL-BREACH: risk_weight = 1.00 (PS1/26 Art. 123(3)(c) non-regulatory retail)."""
        rw = float(breach_row["risk_weight"])
        assert rw == pytest.approx(EXPECTED_RW_NON_REGULATORY_RETAIL, abs=_RW_TOL), (
            f"P5.15 BREACH: risk_weight should be {EXPECTED_RW_NON_REGULATORY_RETAIL:.2f} "
            f"(Art. 123(3)(c)). Got {rw:.6f}. Default-config value would be "
            f"{_LIMB_OFF_RW_BREACH:.2f}."
        )

    def test_p5_15_breach_rwa_is_2000(self, breach_row: dict) -> None:
        """RETAIL-BREACH: rwa_final = 2,000 (EAD 2,000 x RW 100%)."""
        rwa = float(breach_row["rwa_final"])
        assert rwa == pytest.approx(EXPECTED_RWA_BREACH, abs=_RWA_TOL), (
            f"P5.15 BREACH: rwa_final should be {EXPECTED_RWA_BREACH:,.2f}. Got {rwa:,.2f}. "
            f"Default-config value would be {_LIMB_OFF_RWA_BREACH:,.2f}."
        )

    # -------------------------------------------------------------------------
    # ANTI-CONFOUND: threshold limb must NOT have fired
    # -------------------------------------------------------------------------

    def test_p5_15_breach_lending_group_adjusted_exposure_below_880k(
        self, breach_row: dict
    ) -> None:
        """
        RETAIL-BREACH: lending_group_adjusted_exposure < 880,000.

        Proves the failure is attributable to the elected 0.2% test alone, not the
        Art. 123A(1)(b)(ii) GBP 880k aggregate test.
        """
        lgae = float(breach_row["lending_group_adjusted_exposure"])
        assert lgae < _RETAIL_THRESHOLD_GBP, (
            f"P5.15 BREACH anti-confound: lending_group_adjusted_exposure "
            f"{lgae:,.2f} should be < {_RETAIL_THRESHOLD_GBP:,.0f}."
        )

    def test_p5_15_breach_supporting_factor_is_1(self, breach_row: dict) -> None:
        """RETAIL-BREACH: supporting_factor = 1.0 (no SME supporting factor under B31)."""
        sf = float(breach_row["supporting_factor"])
        assert sf == pytest.approx(1.0, abs=_RW_TOL), (
            f"P5.15 BREACH: supporting_factor should be 1.0. Got {sf:.6f}."
        )

    def test_p5_15_breach_ead_is_2000(self, breach_row: dict) -> None:
        """RETAIL-BREACH: ead_final = 2,000 (drawn 2,000, undrawn 0, interest 0, no CRM)."""
        ead = float(breach_row["ead_final"])
        assert ead == pytest.approx(BREACH_DRAWN, abs=_RWA_TOL), (
            f"P5.15 BREACH: ead_final should be {BREACH_DRAWN:,.0f}. Got {ead:,.2f}."
        )


# ===========================================================================
# RE-04 — the DEFAULT config applies no 0.2% test (PS1/26 has no such limb)
# ===========================================================================


@pytest.fixture(scope="module")
def p5_15_default_config_results() -> pl.DataFrame:
    """The same 502-obligor portfolio under the default Basel 3.1 config."""
    bundle = build_p5_15_bundle(fixtures_dir=_FIXTURES_DIR)
    config = CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
    )
    assert config.enforce_retail_granularity is False, (
        "RE-04: the default must not apply a 0.2% limb PS1/26 Art. 123A does not contain"
    )
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None
    return results.sa_results.collect()


class TestP515DefaultConfigHasNoGranularityLimb:
    """RE-04: under the default config the breaching obligor is regulatory retail.

    Hand calculation: 2,000 x 75% (Art. 123(3)(b)) = 1,500 — down from 2,000 under
    the old default, which applied a limb PS1/26 Art. 123A does not contain.
    """

    def test_breach_qualifies_as_regulatory_retail(
        self, p5_15_default_config_results: pl.DataFrame
    ) -> None:
        row = _get_row(p5_15_default_config_results, LOAN_BREACH)
        assert row["qualifies_as_retail"] is True
        assert row["exposure_class"] == "retail_other"

    def test_breach_rwa_is_1500(self, p5_15_default_config_results: pl.DataFrame) -> None:
        row = _get_row(p5_15_default_config_results, LOAN_BREACH)
        assert float(row["risk_weight"]) == pytest.approx(EXPECTED_RW_RETAIL, abs=_RW_TOL)
        assert float(row["rwa_final"]) == pytest.approx(EXPECTED_RWA_BREACH_DEFAULT, abs=_RWA_TOL)

    def test_whole_portfolio_is_regulatory_retail(
        self, p5_15_default_config_results: pl.DataFrame
    ) -> None:
        """Every one of the 502 obligors is regulatory retail at 75%."""
        assert p5_15_default_config_results.height == NUM_CTRL_OBLIGORS + 2
        assert p5_15_default_config_results["qualifies_as_retail"].all()
        assert p5_15_default_config_results["rwa_final"].sum() == pytest.approx(
            PORTFOLIO_TOTAL * EXPECTED_RW_RETAIL, abs=1.0
        )


# ===========================================================================
# RETAIL-CONTROL-PASS tests — the 0.2% test elected, obligor below it
# ===========================================================================


class TestP515ControlPassGranularityPasses:
    """
    RETAIL-CONTROL-PASS: a natural-person obligor whose single exposure (GBP 1,000)
    is below the 0.2% granularity limit (1,006 GBP).

    Both the threshold limb (1,000 << 880,000) and the granularity limb
    (1,000 / 503,000 = 0.001988 < 0.002) are satisfied.
    qualifies_as_retail=True → stays RETAIL_OTHER → RW=0.75 → RWA=750.

    These pinned the original P5.15 implementation and are unchanged by RE-04.
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
# Cross-arm invariant: the elected test discriminates between breach and pass
# ===========================================================================


class TestP515GranularityDiscriminates:
    """
    With the 0.2% test elected, exactly one arm (RETAIL-BREACH) is non-regulatory;
    both arms stay in the retail class (PS1/26 Art. 123(1)(a), RE-03).
    """

    def test_p5_15_exactly_one_arm_non_regulatory(self, breach_row: dict, pass_row: dict) -> None:
        """RETAIL-BREACH fails the elected test, RETAIL-CONTROL-PASS passes it."""
        assert breach_row["qualifies_as_retail"] is False
        assert pass_row["qualifies_as_retail"] is True
        assert breach_row["exposure_class"] == "retail_other"
        assert pass_row["exposure_class"] == "retail_other"

    def test_p5_15_rwa_delta_between_breach_and_pass(
        self, breach_row: dict, pass_row: dict
    ) -> None:
        """
        RWA delta: 2,000 (non-regulatory 100%) - 750 (regulatory 75%) = 1,250.
        """
        rwa_breach = float(breach_row["rwa_final"])
        rwa_pass = float(pass_row["rwa_final"])
        expected_delta = EXPECTED_RWA_BREACH - EXPECTED_RWA_PASS  # 2,000 - 750 = 1,250
        assert rwa_breach - rwa_pass == pytest.approx(expected_delta, abs=1.0), (
            f"P5.15 cross-arm: rwa_final delta should be {expected_delta:,.0f}. "
            f"Got breach={rwa_breach:,.2f}, pass={rwa_pass:,.2f}."
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
