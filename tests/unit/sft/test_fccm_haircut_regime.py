"""
CC-12: the FCCM SFT engine prices haircuts from the RUN regime's Art. 224 table.

Before the fix ``engine/sft/fccm.py`` passed ``is_basel_3_1=False`` to the
haircut lookup for both HE and HC, so a Basel 3.1 run priced every SFT on the
CRR table (equity 15%/25%, gold 15%, three maturity bands). Measured pre-fix:
cash lent 100m against 120m non-main-index equity gave E* = 1,213,203.44 in
BOTH regimes.

Rule text (PS1/26 Appendix 1, Credit Risk Mitigation (CRR) Part, Art. 224(1),
p.203-204): "An institution using the Financial Collateral Comprehensive Method
shall, where there is daily revaluation, apply the volatility adjustments set
out in Tables 1 to 4 of this paragraph." Table 3, 10-day column: "Main Index
Equities, Main Index Convertible Bonds 20"; "Other Equities or Convertible Bonds
listed on a recognised exchange 30"; "Gold 20". Table 1, 10-day column, debt
securities issued by entities in points (c) and (d) of Art. 197(1), CQS 1:
"> 5 <= 10 years 6"; "> 10 years 12". CRR Art. 224(1) Table 1 has only three
bands for the same column, CQS 1: "> 5 years 8"; Table 3: other listed equities
25, gold 15.

Art. 224(2)(b) (both regimes): repos and securities lending use a five-business-
day liquidation period, so H = H_10 x sqrt(5/10).

The 5-10y corporate case LOWERS the Basel 3.1 E* (6% < CRR 8%); it is the rule
text above, not a relaxation (LESSONS A2). The 10y+ case raises it (12% > 8%).

References:
    CRR / PS1/26 Art. 223(5), 224(1) Tables 1 and 3, 224(2)(b).
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from rwa_calc.engine.sft.fccm import sft_bundle_to_exposures
from rwa_calc.rulebook.resolve import resolve
from tests.fixtures.ccr.sft_fccm_review_builder import (
    SFT_REVIEW_NOTIONAL,
    build_sft_bundle,
    sft_collateral,
    sft_trade,
)

_PACKS = {
    "crr": resolve("crr", date(2026, 6, 30)),
    "b31": resolve("b31", date(2027, 6, 30)),
}
_REPORTING_DATE = {"crr": date(2026, 6, 30), "b31": date(2027, 6, 30)}
_SQRT_HALF = math.sqrt(5 / 10)  # Art. 224(2)(b) 5-BD repo liquidation period
_REL = 1e-12


def _estar(regime: str, trades: list[dict], collateral: list[dict] | None) -> float:
    rows, _errors = sft_bundle_to_exposures(
        build_sft_bundle(trades, collateral), _REPORTING_DATE[regime], rulepack=_PACKS[regime]
    )
    frame = rows.collect()
    assert frame.height == 1, "one netting set in, one synthetic row out"
    return float(frame["ead_ccr"][0])


@pytest.mark.parametrize(
    ("regime", "h10", "expected"),
    [
        ("crr", 0.25, 1_213_203.4355964214),
        ("b31", 0.30, 5_455_844.122715712),
    ],
)
def test_non_main_index_equity_collateral_haircut_follows_regime(
    regime: str, h10: float, expected: float
) -> None:
    """Cash lent 100m vs 120m listed equity: HC = Table 3 other-equity H_10 x sqrt(0.5)."""
    # Arrange
    trades = [sft_trade("R1", "S1")]
    collateral = [sft_collateral("C1", "S1", "equity", 120_000_000.0)]
    hand = SFT_REVIEW_NOTIONAL - 120_000_000.0 * (1 - h10 * _SQRT_HALF)
    assert hand == pytest.approx(expected, rel=_REL)

    # Act
    estar = _estar(regime, trades, collateral)

    # Assert
    assert estar == pytest.approx(expected, rel=_REL)


@pytest.mark.parametrize(
    ("regime", "h10"),
    [("crr", 0.15), ("b31", 0.20)],
)
def test_gold_collateral_haircut_follows_regime(regime: str, h10: float) -> None:
    """Cash lent 100m vs 100m gold: Table 3 gold 15% (CRR) / 20% (PS1/26)."""
    # Arrange
    trades = [sft_trade("R1", "S1")]
    collateral = [sft_collateral("C1", "S1", "gold", 100_000_000.0)]

    # Act
    estar = _estar(regime, trades, collateral)

    # Assert
    assert estar == pytest.approx(100_000_000.0 * h10 * _SQRT_HALF, rel=_REL)


@pytest.mark.parametrize(
    ("regime", "residual_years", "h10"),
    [
        ("crr", 7.0, 0.08),  # CRR 5y+ band
        ("b31", 7.0, 0.06),  # PS1/26 >5<=10y band
        ("crr", 12.0, 0.08),  # CRR 5y+ band
        ("b31", 12.0, 0.12),  # PS1/26 >10y band
    ],
)
def test_lent_corporate_bond_haircut_uses_regime_maturity_bands(
    regime: str, residual_years: float, h10: float
) -> None:
    """CQS 1 corporate bond lent 100m, uncollateralised: E* = E x (1 + HE)."""
    # Arrange
    trades = [
        sft_trade(
            "R1",
            "S1",
            exposure_collateral_type="corp_bond",
            exposure_security_cqs=1,
            exposure_security_residual_maturity_years=residual_years,
        )
    ]

    # Act
    estar = _estar(regime, trades, None)

    # Assert
    assert estar == pytest.approx(SFT_REVIEW_NOTIONAL * (1 + h10 * _SQRT_HALF), rel=_REL)


def test_no_run_pack_falls_back_to_crr_table() -> None:
    """A direct call without a run pack keeps the module-level CRR pack (documented default)."""
    # Arrange
    bundle = build_sft_bundle(
        [sft_trade("R1", "S1")], [sft_collateral("C1", "S1", "equity", 120_000_000.0)]
    )

    # Act
    rows, _errors = sft_bundle_to_exposures(bundle, date(2026, 6, 30))

    # Assert
    assert float(rows.collect()["ead_ccr"][0]) == pytest.approx(1_213_203.4355964214, rel=_REL)
