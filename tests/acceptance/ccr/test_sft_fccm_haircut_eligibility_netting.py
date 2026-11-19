"""
SFT FCCM review cluster (CC-12 / CC-13 / CC-14) through the real pipeline.

Each scenario runs ``PipelineOrchestrator.run_with_data`` on a full
``RawDataBundle`` (two GB institution counterparties + an SFT book) under BOTH
regimes and asserts the hand-calculated EAD and RWA of the synthetic
``CCR_SFT`` rows, plus the CCR027 / CCR028 / CCR029 diagnostics on the result's
error list. Risk weights: CP_INST_001 (CQS 2) 50% CRR / 30% PS1/26 ECRA;
the CQS 4 institution 100% in both.

- CC-12 (PS1/26 Art. 224(1) Table 3): cash lent 100m vs 120m listed equity.
  CRR HC = 25% x sqrt(0.5) -> E* = 1,213,203.44; PS1/26 HC = 30% x sqrt(0.5)
  -> E* = 5,455,844.12 (pre-fix the B31 run also gave 1,213,203.44).
- CC-13 (Art. 224(4); Art. 223(1)): an unrated corporate bond lent 100m vs 95m
  cash -> E* = 100m(1 + H x sqrt(0.5)) - 95m with H = 25% / 30%: 22,677,669.53 /
  26,213,203.44 (pre-fix 5,000,000). Cash lent 100m vs 100m property -> E* =
  100m (pre-fix 0) plus a CCR027 warning.
- CC-14 (Art. 220(1), 206, 220(4); PS1/26 Art. 111(2A)): two trades in one set
  with no eligible MNA, gilts linked to T1 -> split, total EAD 100m (pre-fix
  52,121,320.34) plus CCR028; the same set spanning two counterparties -> each
  leg on its own counterparty (pre-fix the CQS 4 leg took CP 1's weight) plus a
  CCR029 ERROR.

References:
    CRR / PS1/26 Art. 206, 220, 223, 224; PS1/26 Art. 111(2A); CRR Art. 120.
"""

from __future__ import annotations

import math

import polars as pl
import pytest

from rwa_calc.contracts.errors import (
    ERROR_SFT_COLLATERAL_NOT_RECOGNISED,
    ERROR_SFT_MULTI_COUNTERPARTY_NETTING_SET,
    ERROR_SFT_NETTING_NOT_RECOGNISED,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.sft_fccm_review_builder import (
    SFT_REVIEW_CP_CQS2,
    SFT_REVIEW_CP_CQS4,
    SFT_REVIEW_NOTIONAL,
    SFT_REVIEW_RISK_WEIGHT,
    build_raw_data_bundle_sft_review,
    build_sft_bundle,
    sft_collateral,
    sft_review_config,
    sft_trade,
)

_SQRT_HALF = math.sqrt(5 / 10)
_REL = 1e-9
_REGIMES = ["crr", "b31"]


def _run(regime: str, trades: list[dict], collateral: list[dict] | None):
    raw = build_raw_data_bundle_sft_review(build_sft_bundle(trades, collateral))
    result = PipelineOrchestrator().run_with_data(raw, sft_review_config(regime))
    rows = (
        result.results.collect().filter(pl.col("risk_type") == "CCR_SFT").sort("exposure_reference")
    )
    return rows, [e.code for e in result.errors]


@pytest.mark.parametrize(
    ("regime", "expected_ead"),
    [("crr", 1_213_203.4355964214), ("b31", 5_455_844.122715712)],
)
def test_cc12_equity_collateral_haircut_follows_the_run_regime(
    regime: str, expected_ead: float
) -> None:
    """Cash lent 100m vs 120m listed equity: EAD and RWA on the regime's Table 3."""
    # Arrange
    trades = [sft_trade("R1", "S1")]
    collateral = [sft_collateral("C1", "S1", "equity", 120_000_000.0)]
    rw = SFT_REVIEW_RISK_WEIGHT[regime][SFT_REVIEW_CP_CQS2]

    # Act
    rows, _codes = _run(regime, trades, collateral)

    # Assert
    assert rows.height == 1
    assert float(rows["ead_final"][0]) == pytest.approx(expected_ead, rel=_REL)
    assert float(rows["risk_weight"][0]) == pytest.approx(rw, rel=_REL)
    assert float(rows["rwa_final"][0]) == pytest.approx(expected_ead * rw, rel=_REL)


@pytest.mark.parametrize(
    ("regime", "expected_ead"),
    [("crr", 22_677_669.529663697), ("b31", 26_213_203.43559642)],
)
def test_cc13_ineligible_security_lent_takes_art_224_4_haircut(
    regime: str, expected_ead: float
) -> None:
    """Unrated corporate bond lent 100m vs 95m cash: HE = the non-main-index equity value."""
    # Arrange
    trades = [
        sft_trade(
            "R1",
            "S1",
            exposure_collateral_type="corp_bond",
            exposure_security_residual_maturity_years=3.0,
        )
    ]
    collateral = [sft_collateral("C1", "S1", "cash", 95_000_000.0)]
    rw = SFT_REVIEW_RISK_WEIGHT[regime][SFT_REVIEW_CP_CQS2]

    # Act
    rows, _codes = _run(regime, trades, collateral)

    # Assert
    assert float(rows["ead_final"][0]) == pytest.approx(expected_ead, rel=_REL)
    assert float(rows["rwa_final"][0]) == pytest.approx(expected_ead * rw, rel=_REL)


@pytest.mark.parametrize("regime", _REGIMES)
def test_cc13_property_collateral_is_not_recognised(regime: str) -> None:
    """Cash lent 100m vs 100m property: EAD 100m, RWA 100m x RW, CCR027 on the result."""
    # Arrange
    trades = [sft_trade("R1", "S1")]
    collateral = [sft_collateral("C_PROP", "S1", "real_estate", 100_000_000.0)]
    rw = SFT_REVIEW_RISK_WEIGHT[regime][SFT_REVIEW_CP_CQS2]

    # Act
    rows, codes = _run(regime, trades, collateral)

    # Assert
    assert float(rows["ead_final"][0]) == pytest.approx(SFT_REVIEW_NOTIONAL, rel=_REL)
    assert float(rows["rwa_final"][0]) == pytest.approx(SFT_REVIEW_NOTIONAL * rw, rel=_REL)
    assert codes.count(ERROR_SFT_COLLATERAL_NOT_RECOGNISED) == 1


@pytest.mark.parametrize("regime", _REGIMES)
def test_cc14_set_without_eligible_mna_is_priced_per_trade(regime: str) -> None:
    """T1 (150m gilts linked) + T2 unsecured, no MNA: EAD 0 + 100m, CCR028 on the result."""
    # Arrange
    trades = [sft_trade("R1", "S1"), sft_trade("R2", "S1")]
    collateral = [
        sft_collateral(
            "C_GILT",
            "S1",
            "gilt",
            150_000_000.0,
            issuer_cqs=1,
            residual_maturity_years=2.0,
            trade_id="R1",
        )
    ]
    rw = SFT_REVIEW_RISK_WEIGHT[regime][SFT_REVIEW_CP_CQS2]

    # Act
    rows, codes = _run(regime, trades, collateral)

    # Assert
    assert rows["exposure_reference"].to_list() == ["ccr__S1__split__R1", "ccr__S1__split__R2"]
    assert rows["ead_final"].to_list() == pytest.approx([0.0, SFT_REVIEW_NOTIONAL], abs=1e-6)
    assert float(rows["rwa_final"].sum()) == pytest.approx(SFT_REVIEW_NOTIONAL * rw, rel=_REL)
    assert codes.count(ERROR_SFT_NETTING_NOT_RECOGNISED) == 1


@pytest.mark.parametrize("regime", _REGIMES)
def test_cc14_multi_counterparty_set_books_each_leg_on_its_own_counterparty(
    regime: str,
) -> None:
    """One set id across CQS 2 and CQS 4 counterparties: RWA = 100m x (RW1 + RW4)."""
    # Arrange
    mna = {"under_master_netting_agreement": True, "is_legally_enforceable": True}
    trades = [
        sft_trade("R1", "S1", **mna),
        sft_trade("R2", "S1", counterparty_reference=SFT_REVIEW_CP_CQS4, **mna),
    ]
    weights = SFT_REVIEW_RISK_WEIGHT[regime]
    expected_rwa = SFT_REVIEW_NOTIONAL * (weights[SFT_REVIEW_CP_CQS2] + weights[SFT_REVIEW_CP_CQS4])

    # Act
    rows, codes = _run(regime, trades, None)

    # Assert
    assert rows["counterparty_reference"].to_list() == [SFT_REVIEW_CP_CQS2, SFT_REVIEW_CP_CQS4]
    assert float(rows["ead_final"].sum()) == pytest.approx(2 * SFT_REVIEW_NOTIONAL, rel=_REL)
    assert float(rows["rwa_final"].sum()) == pytest.approx(expected_rwa, rel=_REL)
    assert codes.count(ERROR_SFT_MULTI_COUNTERPARTY_NETTING_SET) == 1
