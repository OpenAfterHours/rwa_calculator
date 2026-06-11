"""
P2.15 Acceptance Test: Equity transitional irrevocable opt-out (PRA Rules 4.9-4.10).

Tests that when EquityTransitionalConfig.opt_out=True both transitional gates are
suppressed for the firm irrevocably opting out of the transitional schedule:
  - _equity_holding_higher_of_rw (CIU look-through): holding_rw reverts to
    _DEFAULT_HOLDING_RW=1.00 (100%) — i.e. the 370% higher-of path is not applied.
  - _apply_transitional_floor (direct equity): end-state RW is used directly,
    the floor comparison is skipped.

Scenario (reporting_date=2027-06-30, transitional window live):

  EQ-OPTOUT-CIU-001 (load-bearing — CIU look-through):
    Single EQUITY holding, fund_nav=1,000,000, null CQS.
    opted_out=False: holding_rw = max(3.70, 1.60) = 3.70  → RWA = 3,700,000
    opted_out=True:  holding_rw = 1.00 (_DEFAULT_HOLDING_RW) → RWA = 1,000,000

  EQ-CONTROL-001 (control — direct LISTED equity):
    B31 Art. 133(3) 250% end-state. Transitional floor 2027 = 160% < 250% → no uplift.
    Both opted_out configs → risk_weight = 2.50, RWA = 2,500,000 (invariant).

Config knob under test:
    EquityTransitionalConfig.opt_out (bool) — NOT YET ADDED by engine-implementer.
    Constructing dataclasses.replace(cfg.equity_transitional, opt_out=True) will raise
    TypeError until the engine-implementer adds the field.

Regulatory references:
    - PRA PS1/26 Rule 4.9: irrevocable opt-out from equity transitional regime.
    - PRA PS1/26 Rule 4.10: when opted out, higher-of(Art.155(2), transitional) suppressed.
    - PRA PS1/26 Rule 4.8: higher-of(Art.155(2) simple RW, Rule 4.2/4.3 transitional band).
    - PRA PS1/26 Rule 4.2: 2027 standard band = 160%.
    - CRR Art. 155(2): IRB simple method "other" equity RW = 370%.
    - PRA PS1/26 Art. 132a: CIU look-through — equity underlying gets higher-of.
    - PRA PS1/26 Art. 133(3): standard equity = 250%.
    - src/rwa_calc/contracts/config.py: EquityTransitionalConfig
    - src/rwa_calc/engine/equity/calculator.py: _equity_holding_higher_of_rw,
      _resolve_look_through_rw, _apply_transitional_floor
"""

from __future__ import annotations

import dataclasses
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.equity.calculator import EquityCalculator
from tests.fixtures.p2_15.p2_15 import (
    EXPECTED_CIU_LT_RW_OPT_OUT_FALSE,
    EXPECTED_CIU_LT_RW_OPT_OUT_TRUE,
    EXPECTED_RW_CONTROL,
    EXPECTED_RWA_CIU_OPT_OUT_FALSE,
    EXPECTED_RWA_CIU_OPT_OUT_TRUE,
    EXPECTED_RWA_CONTROL,
    EXPOSURE_REF_CIU,
    EXPOSURE_REF_CONTROL,
    create_p215_ciu_holdings,
    create_p215_equity_exposures,
)

# ---------------------------------------------------------------------------
# Scenario config
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2027, 6, 30)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def base_b31_config() -> CalculationConfig:
    """
    Basel 3.1 base config, reporting_date=2027-06-30, permission_mode=IRB.

    Equity transitional enabled by default via EquityTransitionalConfig.basel_3_1().
    opt_out field not yet set — serves as the Config A (opted_out=False) baseline.
    """
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture(scope="module")
def config_opt_out_false(base_b31_config: CalculationConfig) -> CalculationConfig:
    """
    Config A: opted_out=False — higher-of path active, transitional floor applied.

    Uses dataclasses.replace on the equity_transitional sub-config to set opt_out=False
    explicitly. This will raise TypeError until engine-implementer adds the field.
    """
    updated_equity_transitional = dataclasses.replace(
        base_b31_config.equity_transitional,
        opt_out=False,
    )
    return dataclasses.replace(
        base_b31_config,
        equity_transitional=updated_equity_transitional,
    )


@pytest.fixture(scope="module")
def config_opt_out_true(base_b31_config: CalculationConfig) -> CalculationConfig:
    """
    Config B: opted_out=True — BOTH transitional gates suppressed.

    The firm irrevocably opts out of the transitional schedule (PRA Rules 4.9-4.10).
    CIU look-through equity holding reverts to _DEFAULT_HOLDING_RW=1.00 (100%).
    Direct equity keeps end-state assigned RW without transitional floor comparison.

    This will raise TypeError until engine-implementer adds the field.
    """
    updated_equity_transitional = dataclasses.replace(
        base_b31_config.equity_transitional,
        opt_out=True,
    )
    return dataclasses.replace(
        base_b31_config,
        equity_transitional=updated_equity_transitional,
    )


@pytest.fixture(scope="module")
def equity_calculator() -> EquityCalculator:
    """Standard equity calculator instance."""
    return EquityCalculator()


@pytest.fixture(scope="module")
def p215_bundle() -> CRMAdjustedBundle:
    """
    Minimal CRMAdjustedBundle for P2.15.

    equity_exposures: two rows (EQ-OPTOUT-CIU-001 CIU look-through, EQ-CONTROL-001 listed)
    ciu_holdings: one row (H1-EQ-P215 EQUITY null-CQS holding_value=1,000,000)
    All other bundle fields are empty LazyFrames.
    """
    empty = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})
    equity_exposures = create_p215_equity_exposures().lazy()
    ciu_holdings = create_p215_ciu_holdings().lazy()

    return CRMAdjustedBundle(
        exposures=empty,
        equity_exposures=equity_exposures,
        ciu_holdings=ciu_holdings,
    )


# ---------------------------------------------------------------------------
# P2.15: opted_out=False — higher-of path active (baseline / regression guard)
# ---------------------------------------------------------------------------


class TestP215OptOutFalseHigherOfActive:
    """
    P2.15 (Config A — opted_out=False): The higher-of Rule 4.7-4.8 path must be
    active for the CIU look-through EQUITY holding. This is the baseline behaviour
    that Rules 4.9-4.10 opt-out suppresses.

    EQ-OPTOUT-CIU-001:
        Single EQUITY holding, null CQS, holding_value=1,000,000.
        higher-of: max(Art.155(2) other=3.70, Rule 4.2 2027=1.60) = 3.70
        ciu_look_through_rw = (1,000,000 x 3.70) / 1,000,000 = 3.70
        risk_weight = 3.70,  RWA = 3,700,000
    """

    def test_p2_15_ciu_risk_weight_opt_out_false(
        self,
        equity_calculator: EquityCalculator,
        p215_bundle: CRMAdjustedBundle,
        config_opt_out_false: CalculationConfig,
    ) -> None:
        """
        P2.15 Config A: CIU look-through risk_weight == 3.70 when opted_out=False.

        Arrange: CIU wrapper EQ-OPTOUT-CIU-001, single EQUITY holding null CQS,
                 reporting_date=2027-06-30 (Rule 4.2 standard band=160%).
        Act: get_equity_result_bundle with opted_out=False config.
        Assert: risk_weight == EXPECTED_CIU_LT_RW_OPT_OUT_FALSE == 3.70
                (higher-of: max(Art.155(2)=3.70, transitional=1.60) = 3.70).
        """
        # Arrange
        # (bundle and config constructed via fixtures)

        # Act
        bundle_result = equity_calculator.get_equity_result_bundle(
            p215_bundle, config_opt_out_false
        )
        result_df = bundle_result.results.collect()
        row = result_df.filter(pl.col("exposure_reference") == EXPOSURE_REF_CIU)

        # Assert
        assert len(row) == 1, (
            f"Expected exactly 1 row for exposure_reference={EXPOSURE_REF_CIU!r}, got {len(row)}"
        )
        actual_rw = row["risk_weight"][0]
        assert actual_rw == pytest.approx(EXPECTED_CIU_LT_RW_OPT_OUT_FALSE, abs=1e-4), (
            f"P2.15 (opted_out=False): CIU look-through risk_weight should be "
            f"{EXPECTED_CIU_LT_RW_OPT_OUT_FALSE:.4f} "
            f"(higher-of Rule 4.7-4.8: max(Art.155(2) other=3.70, Rule 4.2 2027=1.60)=3.70), "
            f"got {actual_rw:.4f}."
        )

    def test_p2_15_ciu_rwa_opt_out_false(
        self,
        equity_calculator: EquityCalculator,
        p215_bundle: CRMAdjustedBundle,
        config_opt_out_false: CalculationConfig,
    ) -> None:
        """
        P2.15 Config A: CIU look-through rwa == 3_700_000 when opted_out=False.

        Arrange: EAD=1,000,000, risk_weight=3.70 (higher-of active).
        Act: get_equity_result_bundle with opted_out=False config.
        Assert: rwa == EXPECTED_RWA_CIU_OPT_OUT_FALSE == 3_700_000.
        """
        # Arrange
        # (bundle and config constructed via fixtures)

        # Act
        bundle_result = equity_calculator.get_equity_result_bundle(
            p215_bundle, config_opt_out_false
        )
        result_df = bundle_result.results.collect()
        row = result_df.filter(pl.col("exposure_reference") == EXPOSURE_REF_CIU)

        # Assert
        assert len(row) == 1
        actual_rwa = row["rwa"][0]
        assert actual_rwa == pytest.approx(EXPECTED_RWA_CIU_OPT_OUT_FALSE, rel=1e-4), (
            f"P2.15 (opted_out=False): CIU rwa should be {EXPECTED_RWA_CIU_OPT_OUT_FALSE:,.0f} "
            f"(EAD=1,000,000 x risk_weight=3.70), got {actual_rwa:,.0f}."
        )


# ---------------------------------------------------------------------------
# P2.15: opted_out=True — BOTH gates suppressed (LOAD-BEARING assertions)
# ---------------------------------------------------------------------------


class TestP215OptOutTrueBothGatesSuppressed:
    """
    P2.15 (Config B — opted_out=True): BOTH transitional gates must be suppressed
    when the firm irrevocably opts out (PRA Rules 4.9-4.10).

    Gate 1 (_equity_holding_higher_of_rw, Rule 4.8):
        CIU look-through EQUITY holding_rw reverts from 3.70 to 1.00
        (_DEFAULT_HOLDING_RW=100%; higher-of suppressed).
        ciu_look_through_rw = (1,000,000 x 1.00) / 1,000,000 = 1.00
        risk_weight = 1.00,  RWA = 1,000,000  (load-bearing)

    Gate 2 (_apply_transitional_floor, Rule 4.1):
        Direct equity keeps end-state assigned RW without floor comparison.
        EQ-CONTROL-001: B31 Art. 133(3) 250%; floor 160% < 250% → floor inert regardless.
        risk_weight = 2.50,  RWA = 2,500,000  (invariant — same under both configs)
    """

    def test_p2_15_ciu_risk_weight_opt_out_true(
        self,
        equity_calculator: EquityCalculator,
        p215_bundle: CRMAdjustedBundle,
        config_opt_out_true: CalculationConfig,
    ) -> None:
        """
        P2.15 Config B LOAD-BEARING: CIU look-through risk_weight == 1.00 when opted_out=True.

        Arrange: CIU wrapper EQ-OPTOUT-CIU-001, single EQUITY holding null CQS,
                 reporting_date=2027-06-30, opted_out=True.
        Act: get_equity_result_bundle with opted_out=True config.
        Assert: risk_weight == EXPECTED_CIU_LT_RW_OPT_OUT_TRUE == 1.00
                (_equity_holding_higher_of_rw suppressed; holding reverts to _DEFAULT_HOLDING_RW).

        This is the primary assertion that distinguishes pre- and post-implementation:
          opted_out=False → risk_weight=3.70   (higher-of Rule 4.7-4.8)
          opted_out=True  → risk_weight=1.00   (Rule 4.9-4.10 opt-out)
        """
        # Arrange
        # (bundle and config constructed via fixtures)

        # Act
        bundle_result = equity_calculator.get_equity_result_bundle(p215_bundle, config_opt_out_true)
        result_df = bundle_result.results.collect()
        row = result_df.filter(pl.col("exposure_reference") == EXPOSURE_REF_CIU)

        # Assert
        assert len(row) == 1, (
            f"Expected exactly 1 row for exposure_reference={EXPOSURE_REF_CIU!r}, got {len(row)}"
        )
        actual_rw = row["risk_weight"][0]
        assert actual_rw == pytest.approx(EXPECTED_CIU_LT_RW_OPT_OUT_TRUE, abs=1e-4), (
            f"P2.15 (opted_out=True): CIU look-through risk_weight should be "
            f"{EXPECTED_CIU_LT_RW_OPT_OUT_TRUE:.4f} "
            f"(_equity_holding_higher_of_rw suppressed by Rules 4.9-4.10 opt-out; "
            f"holding_rw reverts to _DEFAULT_HOLDING_RW=1.00 → "
            f"ciu_look_through_rw = 1,000,000 x 1.00 / 1,000,000 = 1.00), "
            f"got {actual_rw:.4f}. "
            f"opted_out=False gives {EXPECTED_CIU_LT_RW_OPT_OUT_FALSE:.2f} — "
            f"the 3.70 -> 1.00 swing is the load-bearing opt-out assertion."
        )

    def test_p2_15_ciu_rwa_opt_out_true(
        self,
        equity_calculator: EquityCalculator,
        p215_bundle: CRMAdjustedBundle,
        config_opt_out_true: CalculationConfig,
    ) -> None:
        """
        P2.15 Config B LOAD-BEARING: CIU rwa == 1_000_000 when opted_out=True.

        Arrange: EAD=1,000,000, risk_weight=1.00 (opt-out suppresses higher-of).
        Act: get_equity_result_bundle with opted_out=True config.
        Assert: rwa == EXPECTED_RWA_CIU_OPT_OUT_TRUE == 1_000_000.

        opted_out=False rwa = 3,700,000 (3.70 x EAD).
        opted_out=True  rwa = 1,000,000 (1.00 x EAD) — the 2.7M RWA swing is the opt-out effect.
        """
        # Arrange
        # (bundle and config constructed via fixtures)

        # Act
        bundle_result = equity_calculator.get_equity_result_bundle(p215_bundle, config_opt_out_true)
        result_df = bundle_result.results.collect()
        row = result_df.filter(pl.col("exposure_reference") == EXPOSURE_REF_CIU)

        # Assert
        assert len(row) == 1
        actual_rwa = row["rwa"][0]
        assert actual_rwa == pytest.approx(EXPECTED_RWA_CIU_OPT_OUT_TRUE, rel=1e-4), (
            f"P2.15 (opted_out=True): CIU rwa should be {EXPECTED_RWA_CIU_OPT_OUT_TRUE:,.0f} "
            f"(EAD=1,000,000 x risk_weight=1.00; opt-out suppresses higher-of 3.70), "
            f"got {actual_rwa:,.0f}. "
            f"opted_out=False rwa={EXPECTED_RWA_CIU_OPT_OUT_FALSE:,.0f}; "
            f"opt-out effect = -2,700,000."
        )


# ---------------------------------------------------------------------------
# P2.15: control — direct LISTED equity invariant under both configs
# ---------------------------------------------------------------------------


class TestP215ControlDirectEquityInvariant:
    """
    P2.15 (control — EQ-CONTROL-001): Direct LISTED equity risk_weight and RWA must
    be identical under BOTH opted_out configs.

    B31 Art. 133(3): standard equity = 250%.
    Transitional floor 2027 = 160% < 250% end-state → transitional floor does not bind.
    The opted_out flag does not change the outcome because the floor is inert.

    risk_weight = 2.50,  RWA = 2,500,000  (invariant across both configs).
    """

    @pytest.mark.parametrize(
        "config_fixture",
        ["config_opt_out_false", "config_opt_out_true"],
    )
    def test_p2_15_control_risk_weight_invariant(
        self,
        request: pytest.FixtureRequest,
        equity_calculator: EquityCalculator,
        p215_bundle: CRMAdjustedBundle,
        config_fixture: str,
    ) -> None:
        """
        P2.15 control: direct LISTED equity risk_weight == 2.50 under both opted_out configs.

        Arrange: EQ-CONTROL-001 (equity_type="listed", is_exchange_traded=True,
                 is_speculative=False, business_age_years=10.0), EAD=1,000,000.
        Act: get_equity_result_bundle with config (opted_out=False / True).
        Assert: risk_weight == EXPECTED_RW_CONTROL == 2.50 for both.

        Proves the opted_out flag does NOT regress the direct equity path.
        """
        # Arrange
        config: CalculationConfig = request.getfixturevalue(config_fixture)

        # Act
        bundle_result = equity_calculator.get_equity_result_bundle(p215_bundle, config)
        result_df = bundle_result.results.collect()
        row = result_df.filter(pl.col("exposure_reference") == EXPOSURE_REF_CONTROL)

        # Assert
        assert len(row) == 1, (
            f"Expected exactly 1 row for exposure_reference={EXPOSURE_REF_CONTROL!r}, "
            f"got {len(row)}"
        )
        actual_rw = row["risk_weight"][0]
        assert actual_rw == pytest.approx(EXPECTED_RW_CONTROL, abs=1e-4), (
            f"P2.15 control ({config_fixture}): direct LISTED equity risk_weight should be "
            f"{EXPECTED_RW_CONTROL:.4f} (B31 Art. 133(3) 250%); "
            f"opted_out flag must NOT regress direct equity path. Got {actual_rw:.4f}."
        )

    @pytest.mark.parametrize(
        "config_fixture",
        ["config_opt_out_false", "config_opt_out_true"],
    )
    def test_p2_15_control_rwa_invariant(
        self,
        request: pytest.FixtureRequest,
        equity_calculator: EquityCalculator,
        p215_bundle: CRMAdjustedBundle,
        config_fixture: str,
    ) -> None:
        """
        P2.15 control: direct LISTED equity rwa == 2_500_000 under both opted_out configs.

        Arrange: EAD=1,000,000, risk_weight=2.50 (Art. 133(3) standard; floor inert).
        Act: get_equity_result_bundle with config (opted_out=False / True).
        Assert: rwa == EXPECTED_RWA_CONTROL == 2_500_000 for both.
        """
        # Arrange
        config: CalculationConfig = request.getfixturevalue(config_fixture)

        # Act
        bundle_result = equity_calculator.get_equity_result_bundle(p215_bundle, config)
        result_df = bundle_result.results.collect()
        row = result_df.filter(pl.col("exposure_reference") == EXPOSURE_REF_CONTROL)

        # Assert
        assert len(row) == 1
        actual_rwa = row["rwa"][0]
        assert actual_rwa == pytest.approx(EXPECTED_RWA_CONTROL, rel=1e-4), (
            f"P2.15 control ({config_fixture}): direct LISTED equity rwa should be "
            f"{EXPECTED_RWA_CONTROL:,.0f} (EAD=1,000,000 x 2.50), got {actual_rwa:,.0f}."
        )
