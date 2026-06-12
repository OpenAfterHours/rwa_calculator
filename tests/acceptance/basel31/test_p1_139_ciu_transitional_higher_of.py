"""
P1.139 Acceptance Test: CIU look-through equity transitional Rule 4.7-4.8 higher-of.

Tests that EQUITY holdings inside a CIU look-through receive the correct
higher-of treatment under PRA Rules 4.7-4.8 during the transitional period.

Scenario:
    CIU wrapper: CIU-P1139-LT (equity_type="ciu", ciu_approach="look_through")
    Fund: FUND-P1139 (fund_nav=1,000,000)
    H1-EQ : exposure_class="EQUITY",    cqs=None, holding_value=600,000
    H2-CORP: exposure_class="CORPORATE", cqs=3,    holding_value=400,000
    reporting_date=2027-06-30 (transitional Year 1)

Bug under test (pre-fix):
    _apply_transitional_floor sets is_ciu_non_fallback=True for look_through CIUs
    and zeroes the transitional floor for the WRAPPER row — but the EQUITY underlying
    inside the look-through also gets no higher-of applied in _resolve_look_through_rw.
    H1-EQ falls back to _DEFAULT_HOLDING_RW=1.00 (no IRB simple / higher-of applied).
    Buggy weighted_sum: 600,000 × 1.00 + 400,000 × 0.75 = 900,000
    Buggy ciu_look_through_rw: 0.90
    Buggy RWA: 900,000

Post-fix expected:
    Each EQUITY underlying gets max(Art.155(2) IRB simple 370%, Rule 4.2 2027 band 160%)
    = 370% applied as the holding_rw.  H2-CORP (not equity) is unaffected (75%).
    Corrected weighted_sum: 600,000 × 3.70 + 400,000 × 0.75 = 2,520,000
    Corrected ciu_look_through_rw: 2.52
    Corrected RWA: 2,520,000

Note — new fields NOT set:
    The engine-implementer will add had_irb_permission_2026 and opted_out to
    EquityTransitionalConfig in a later wave.  This test does NOT set those fields —
    it constructs CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30)) with
    no extra kwargs.  The engine must make this scenario pass as configured: the
    higher-of Rule 4.7-4.8 must apply to equity look-through holdings under an
    enabled Basel 3.1 transitional schedule without the caller setting any new fields.

Regulatory references:
    - PRA PS1/26 Rule 4.7: transitional floor applies to equity held under
      Art. 155(2) IRB simple method when firm had IRB equity permission 31 Dec 2026.
    - PRA PS1/26 Rule 4.8: higher-of(Art.155(2) simple RW, Rule 4.2/4.3 transitional).
    - PRA PS1/26 Rule 4.2: 2027 standard band = 160%, 2028 = 200%, 2029 = 250%.
    - CRR Art. 155(2): IRB simple method equity risk weights (other = 370%).
    - PRA PS1/26 Art. 132a: CIU look-through — wrapper itself NOT floored.
    - src/rwa_calc/engine/equity/calculator.py: _resolve_look_through_rw
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.equity.calculator import EquityCalculator
from tests.fixtures.p1_139.p1_139 import (
    EXPECTED_CIU_LT_RW,
    EXPECTED_RWA,
    EXPOSURE_REF,
    create_p1139_ciu_holdings,
    create_p1139_equity_exposure,
)
from tests.fixtures.resolved_bundle import make_crm_bundle

# ---------------------------------------------------------------------------
# Scenario config
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2027, 6, 30)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def b31_2027_config() -> CalculationConfig:
    """
    Basel 3.1 config, reporting_date=2027-06-30.

    Equity transitional enabled by default (EquityTransitionalConfig.basel_3_1()
    is the default for CalculationConfig.basel_3_1()).
    No new fields (had_irb_permission_2026, opted_out) are set — they do not
    exist yet; the engine must satisfy this test without them.
    """
    return CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE)


@pytest.fixture(scope="module")
def equity_calculator() -> EquityCalculator:
    """Standard equity calculator instance."""
    return EquityCalculator()


@pytest.fixture(scope="module")
def ciu_bundle() -> CRMAdjustedBundle:
    """
    Minimal CRMAdjustedBundle for P1.139.

    equity_exposures: one CIU wrapper row (CIU-P1139-LT, look_through)
    ciu_holdings: two underlying rows (H1-EQ EQUITY, H2-CORP CORPORATE CQS 3)
    All other bundle fields are empty LazyFrames.
    """
    empty = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})
    equity_exposures = create_p1139_equity_exposure().lazy()
    ciu_holdings = create_p1139_ciu_holdings().lazy()

    return make_crm_bundle(
        exposures=empty,
        equity_exposures=equity_exposures,
        ciu_holdings=ciu_holdings,
    )


# ---------------------------------------------------------------------------
# P1.139: CIU look-through equity transitional higher-of (Rules 4.7-4.8)
# ---------------------------------------------------------------------------


class TestP1139CiuTransitionalHigherOf:
    """
    P1.139: EQUITY holdings inside a CIU look-through must receive the higher-of
    treatment (Art. 155(2) IRB simple RW vs. Rule 4.2/4.3 transitional band)
    during the Basel 3.1 transitional period.

    The wrapper row (CIU-P1139-LT) itself is NOT floored — Rule 4.7 derogation
    to Art. 132a means the transitional floor applies to the EQUITY UNDERLYING,
    not to the aggregated fund RW.

    Bug: _apply_transitional_floor correctly excludes the CIU wrapper from the
    floor via is_ciu_non_fallback, but _resolve_look_through_rw uses a plain CQS
    table lookup for holding_rw and never applies the higher-of to EQUITY class
    holdings — they fall back to _DEFAULT_HOLDING_RW=1.00 (100%).

    Post-fix: EQUITY holdings inside look-through CIUs receive
    max(Art.155(2) other=370%, Rule 4.2 2027 band=160%) = 370%.
    """

    def test_p1_139_ciu_look_through_rw_post_fix(
        self,
        equity_calculator: EquityCalculator,
        ciu_bundle: CRMAdjustedBundle,
        b31_2027_config: CalculationConfig,
    ) -> None:
        """
        P1.139 primary: ciu_look_through_rw == 2.52 after higher-of applied to equity holding.

        Arrange: CIU wrapper with EQUITY (600k) + CORPORATE CQS 3 (400k) holdings,
                 fund_nav=1,000,000, reporting_date=2027-06-30 (transitional Year 1).
        Act: get_equity_result_bundle under Basel 3.1 config.
        Assert: ciu_look_through_rw == EXPECTED_CIU_LT_RW == 2.52.

        Buggy value (pre-fix): ciu_look_through_rw == 0.90
        (EQUITY holding falls back to _DEFAULT_HOLDING_RW=1.00, no higher-of applied)
        """
        # Arrange
        # (bundle and config constructed via fixtures)

        # Act
        bundle_result = equity_calculator.get_equity_result_bundle(ciu_bundle, b31_2027_config)
        result_df = bundle_result.results.collect()
        row = result_df.filter(pl.col("exposure_reference") == EXPOSURE_REF)

        # Assert
        assert len(row) == 1, (
            f"Expected exactly 1 row for exposure_reference={EXPOSURE_REF!r}, got {len(row)}"
        )
        actual_lt_rw = row["ciu_look_through_rw"][0]
        assert actual_lt_rw == pytest.approx(EXPECTED_CIU_LT_RW, abs=1e-4), (
            f"P1.139: ciu_look_through_rw should be {EXPECTED_CIU_LT_RW:.4f} "
            f"(higher-of Rule 4.7-4.8 applied to EQUITY holding: "
            f"max(Art.155(2)=3.70, Rule 4.2 2027=1.60)=3.70; "
            f"CORPORATE CQS 3=0.75; weighted_sum/fund_nav=2.52), "
            f"got {actual_lt_rw:.4f}. "
            f"Pre-fix: EQUITY holding gets _DEFAULT_HOLDING_RW=1.00 → "
            f"ciu_look_through_rw=0.90."
        )

    def test_p1_139_rwa_post_fix(
        self,
        equity_calculator: EquityCalculator,
        ciu_bundle: CRMAdjustedBundle,
        b31_2027_config: CalculationConfig,
    ) -> None:
        """
        P1.139 primary: rwa == 2_520_000 after higher-of applied to equity holding.

        Arrange: CIU wrapper EAD=1,000,000, ciu_look_through_rw=2.52 (post-fix).
        Act: get_equity_result_bundle under Basel 3.1 config.
        Assert: rwa == EXPECTED_RWA == 2_520_000.

        Buggy value (pre-fix): rwa == 900_000
        (ciu_look_through_rw=0.90 × EAD=1,000,000 = 900,000)
        """
        # Arrange
        # (bundle and config constructed via fixtures)

        # Act
        bundle_result = equity_calculator.get_equity_result_bundle(ciu_bundle, b31_2027_config)
        result_df = bundle_result.results.collect()
        row = result_df.filter(pl.col("exposure_reference") == EXPOSURE_REF)

        # Assert
        assert len(row) == 1
        actual_rwa = row["rwa"][0]
        assert actual_rwa == pytest.approx(EXPECTED_RWA, rel=1e-4), (
            f"P1.139: rwa should be {EXPECTED_RWA:,.0f} "
            f"(EAD=1,000,000 × ciu_look_through_rw=2.52 = 2,520,000), "
            f"got {actual_rwa:,.0f}. "
            f"Pre-fix: rwa == 900,000 (EAD × 0.90) because EQUITY holding "
            f"_DEFAULT_HOLDING_RW=1.00 not replaced by higher-of 3.70."
        )

    def test_p1_139_wrapper_not_transitionally_floored(
        self,
        equity_calculator: EquityCalculator,
        ciu_bundle: CRMAdjustedBundle,
        b31_2027_config: CalculationConfig,
    ) -> None:
        """
        P1.139 negative: the CIU wrapper risk_weight is NOT directly floored by Rule 4.1.

        The wrapper's risk_weight == ciu_look_through_rw (the aggregated fund RW)
        because _apply_transitional_floor correctly excludes look_through CIUs.
        The floor instead applies to the EQUITY UNDERLYING inside the fund.

        Post-fix: risk_weight == ciu_look_through_rw == 2.52 (no additional wrapper floor).
        """
        # Arrange
        # (bundle and config constructed via fixtures)

        # Act
        bundle_result = equity_calculator.get_equity_result_bundle(ciu_bundle, b31_2027_config)
        result_df = bundle_result.results.collect()
        row = result_df.filter(pl.col("exposure_reference") == EXPOSURE_REF)

        # Assert
        assert len(row) == 1
        actual_rw = row["risk_weight"][0]
        # Wrapper risk_weight should equal ciu_look_through_rw (2.52),
        # not a transitionally-floored value (e.g. 1.60 standard band).
        assert actual_rw == pytest.approx(EXPECTED_CIU_LT_RW, abs=1e-4), (
            f"P1.139: wrapper risk_weight should equal ciu_look_through_rw="
            f"{EXPECTED_CIU_LT_RW:.4f} (no direct wrapper floor under Rule 4.3 "
            f"exclusion for look-through CIUs), got {actual_rw:.4f}."
        )
