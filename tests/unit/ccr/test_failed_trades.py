"""
Unit tests for compute_failed_trade_rwa (P8.24 — Failed trades, DvP / non-DvP).

Pins the expected per-row and aggregate output of the failed-trade settlement
risk engine per CRR Art. 378 (DvP) and Art. 379(1) (non-DvP):

    DvP:      own_funds = max(0, agreed_price - market_value) × multiplier
              RWA = own_funds × 12.5

    non-DvP:  exposure = value_transferred + current_positive_exposure
              RWA = exposure × risk_weight_factor   (Col 4: × 12.5)

Scenario (5 rows, matching P8.24 fixture-builder constants):
    FT001  DvP  t+5   band dvp_5_15        mult 0.08   own_funds    4,000   RWA     50,000
    FT002  DvP  t+20  band dvp_16_30       mult 0.50   own_funds  100,000   RWA  1,250,000
    FT003  DvP  t+35  band dvp_31_45       mult 0.75   own_funds   75,000   RWA    937,500
    FT004  DvP  t+50  band dvp_46_plus     mult 1.00   own_funds  150,000   RWA  1,875,000
    FT005  non-DvP t+6 band non_dvp_col4_t5_plus  RW×12.5  own_funds 2,050,000  RWA 25,625,000

Portfolio total RWA = 29,737,500.

EXPECTED FAILURE MODE:
    ``ImportError: No module named 'rwa_calc.engine.ccr.failed_trades'``
    (or ``cannot import name 'compute_failed_trade_rwa'``).
    The module does not exist until engine-implementer lands P8.24.
    Per operator relaxation in reviewer-fixture_builder-r0 feedback, this
    ImportError is the accepted TDD red signal for this item.

References:
    - CRR Art. 378 + Table 1: DvP multiplier ladder (5-15d→8%, 16-30d→50%,
      31-45d→75%, 46+d→100%)
    - CRR Art. 379(1) + Table 2: non-DvP three-column structure; Col 4
      (t+5 onwards) → 1250% RW, RWA multiplier = 12.5
    - CRR Art. 379(2): IRB PD inference + immateriality carve-out (OOS)
    - CRR Art. 379(3): CET1 deduction alternative (flag default False, OOS)
    - CRR Art. 380: system-wide failure waiver (flag default False, OOS)
    - PRA PS1/26 Art. 92(3)(a), 92(3)(ca): UK onshoring, unchanged numerics
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
from rwa_calc.contracts.config import CalculationConfig

# ---------------------------------------------------------------------------
# Subject under test — option 1 (direct import, no try/except).
# Pytest collection will fail with ImportError until engine-implementer adds
# src/rwa_calc/engine/ccr/failed_trades.py.  This is the intended TDD signal.
# ---------------------------------------------------------------------------
from rwa_calc.engine.ccr.failed_trades import compute_failed_trade_rwa

# ---------------------------------------------------------------------------
# Fixture constants — single source of truth (fixture-builder owns these).
# ---------------------------------------------------------------------------
from tests.fixtures.ccr.failed_trade_builder import (
    FT001_BAND,
    FT001_ID,
    FT001_OWN_FUNDS,
    FT001_RWA,
    FT002_BAND,
    FT002_ID,
    FT002_OWN_FUNDS,
    FT002_RWA,
    FT003_BAND,
    FT003_ID,
    FT003_OWN_FUNDS,
    FT003_RWA,
    FT004_BAND,
    FT004_ID,
    FT004_OWN_FUNDS,
    FT004_RWA,
    FT005_BAND,
    FT005_ID,
    FT005_OWN_FUNDS,
    FT005_RWA,
    PORTFOLIO_TOTAL_RWA,
    make_failed_trades_frame,
)

# ---------------------------------------------------------------------------
# Shared config instance — CRR framework (Art. 378/379 apply under CRR and
# identically under PRA PS1/26; no numeral changes).
# ---------------------------------------------------------------------------
_CONFIG: CalculationConfig = CalculationConfig.crr(reporting_date=date(2026, 1, 15))


# ===========================================================================
# 1. FT001 — DvP, t+5, band dvp_5_15, multiplier 8%
# ===========================================================================


def test_p8_24_dvp_ft001_rwa() -> None:
    """FT001: DvP t+5 -> band dvp_5_15, RWA = 4,000 × 12.5 = 50,000.

    Arrange:
        FT001: agreed=1_000_000, mv=950_000, price_diff=50_000.
        Art. 378 Table 1: 5-15 working days -> multiplier 0.08.
        own_funds = 50_000 × 0.08 = 4_000; RWA = 4_000 × 12.5 = 50_000.

    Act: compute_failed_trade_rwa(lf, config).collect(), filter to FT001.

    Assert:
        failed_trade_rwa == 50_000.0
        regulatory_band  == "dvp_5_15"
        own_funds_requirement == 4_000.0

    References: CRR Art. 378 + Table 1.
    """
    # Arrange
    lf = make_failed_trades_frame()

    # Act
    result = compute_failed_trade_rwa(lf, _CONFIG).collect()
    row = result.filter(pl.col("failed_trade_id") == FT001_ID)

    # Assert
    assert row["failed_trade_rwa"][0] == pytest.approx(FT001_RWA, abs=1e-6), (
        f"FT001 RWA: expected {FT001_RWA}, got {row['failed_trade_rwa'][0]!r}. "
        "DvP t+5: price_diff=50_000, mult=0.08, own_funds=4_000, RWA=50_000. "
        "CRR Art. 378 Table 1."
    )
    assert row["regulatory_band"][0] == FT001_BAND, (
        f"FT001 band: expected {FT001_BAND!r}, got {row['regulatory_band'][0]!r}. "
        "5 working days -> dvp_5_15 band."
    )
    assert row["own_funds_requirement"][0] == pytest.approx(FT001_OWN_FUNDS, abs=1e-6), (
        f"FT001 own_funds: expected {FT001_OWN_FUNDS}, got {row['own_funds_requirement'][0]!r}. "
        "50_000 × 0.08 = 4_000. CRR Art. 378."
    )


# ===========================================================================
# 2. FT002 — DvP, t+20, band dvp_16_30, multiplier 50%
# ===========================================================================


def test_p8_24_dvp_ft002_rwa() -> None:
    """FT002: DvP t+20 -> band dvp_16_30, RWA = 100,000 × 12.5 = 1,250,000.

    Arrange:
        FT002: agreed=2_000_000, mv=1_800_000, price_diff=200_000.
        Art. 378 Table 1: 16-30 working days -> multiplier 0.50.
        own_funds = 200_000 × 0.50 = 100_000; RWA = 100_000 × 12.5 = 1_250_000.

    Act: compute_failed_trade_rwa(lf, config).collect(), filter to FT002.

    Assert:
        failed_trade_rwa == 1_250_000.0
        regulatory_band  == "dvp_16_30"
        own_funds_requirement == 100_000.0

    References: CRR Art. 378 + Table 1.
    """
    # Arrange
    lf = make_failed_trades_frame()

    # Act
    result = compute_failed_trade_rwa(lf, _CONFIG).collect()
    row = result.filter(pl.col("failed_trade_id") == FT002_ID)

    # Assert
    assert row["failed_trade_rwa"][0] == pytest.approx(FT002_RWA, abs=1e-6), (
        f"FT002 RWA: expected {FT002_RWA}, got {row['failed_trade_rwa'][0]!r}. "
        "DvP t+20: price_diff=200_000, mult=0.50, own_funds=100_000, RWA=1_250_000. "
        "CRR Art. 378 Table 1."
    )
    assert row["regulatory_band"][0] == FT002_BAND, (
        f"FT002 band: expected {FT002_BAND!r}, got {row['regulatory_band'][0]!r}. "
        "20 working days -> dvp_16_30 band."
    )
    assert row["own_funds_requirement"][0] == pytest.approx(FT002_OWN_FUNDS, abs=1e-6), (
        f"FT002 own_funds: expected {FT002_OWN_FUNDS}, got {row['own_funds_requirement'][0]!r}. "
        "200_000 × 0.50 = 100_000. CRR Art. 378."
    )


# ===========================================================================
# 3. FT003 — DvP, t+35, band dvp_31_45, multiplier 75%
# ===========================================================================


def test_p8_24_dvp_ft003_rwa() -> None:
    """FT003: DvP t+35 -> band dvp_31_45, RWA = 75,000 × 12.5 = 937,500.

    Arrange:
        FT003: agreed=500_000, mv=400_000, price_diff=100_000.
        Art. 378 Table 1: 31-45 working days -> multiplier 0.75.
        own_funds = 100_000 × 0.75 = 75_000; RWA = 75_000 × 12.5 = 937_500.

    Act: compute_failed_trade_rwa(lf, config).collect(), filter to FT003.

    Assert:
        failed_trade_rwa == 937_500.0
        regulatory_band  == "dvp_31_45"
        own_funds_requirement == 75_000.0

    References: CRR Art. 378 + Table 1.
    """
    # Arrange
    lf = make_failed_trades_frame()

    # Act
    result = compute_failed_trade_rwa(lf, _CONFIG).collect()
    row = result.filter(pl.col("failed_trade_id") == FT003_ID)

    # Assert
    assert row["failed_trade_rwa"][0] == pytest.approx(FT003_RWA, abs=1e-6), (
        f"FT003 RWA: expected {FT003_RWA}, got {row['failed_trade_rwa'][0]!r}. "
        "DvP t+35: price_diff=100_000, mult=0.75, own_funds=75_000, RWA=937_500. "
        "CRR Art. 378 Table 1."
    )
    assert row["regulatory_band"][0] == FT003_BAND, (
        f"FT003 band: expected {FT003_BAND!r}, got {row['regulatory_band'][0]!r}. "
        "35 working days -> dvp_31_45 band."
    )
    assert row["own_funds_requirement"][0] == pytest.approx(FT003_OWN_FUNDS, abs=1e-6), (
        f"FT003 own_funds: expected {FT003_OWN_FUNDS}, got {row['own_funds_requirement'][0]!r}. "
        "100_000 × 0.75 = 75_000. CRR Art. 378."
    )


# ===========================================================================
# 4. FT004 — DvP, t+50, band dvp_46_plus, multiplier 100%
# ===========================================================================


def test_p8_24_dvp_ft004_rwa() -> None:
    """FT004: DvP t+50 -> band dvp_46_plus, RWA = 150,000 × 12.5 = 1,875,000.

    Arrange:
        FT004: agreed=750_000, mv=600_000, price_diff=150_000.
        Art. 378 Table 1: 46+ working days -> multiplier 1.00.
        own_funds = 150_000 × 1.00 = 150_000; RWA = 150_000 × 12.5 = 1_875_000.

    Act: compute_failed_trade_rwa(lf, config).collect(), filter to FT004.

    Assert:
        failed_trade_rwa == 1_875_000.0
        regulatory_band  == "dvp_46_plus"
        own_funds_requirement == 150_000.0

    References: CRR Art. 378 + Table 1.
    """
    # Arrange
    lf = make_failed_trades_frame()

    # Act
    result = compute_failed_trade_rwa(lf, _CONFIG).collect()
    row = result.filter(pl.col("failed_trade_id") == FT004_ID)

    # Assert
    assert row["failed_trade_rwa"][0] == pytest.approx(FT004_RWA, abs=1e-6), (
        f"FT004 RWA: expected {FT004_RWA}, got {row['failed_trade_rwa'][0]!r}. "
        "DvP t+50: price_diff=150_000, mult=1.00, own_funds=150_000, RWA=1_875_000. "
        "CRR Art. 378 Table 1."
    )
    assert row["regulatory_band"][0] == FT004_BAND, (
        f"FT004 band: expected {FT004_BAND!r}, got {row['regulatory_band'][0]!r}. "
        "50 working days -> dvp_46_plus band."
    )
    assert row["own_funds_requirement"][0] == pytest.approx(FT004_OWN_FUNDS, abs=1e-6), (
        f"FT004 own_funds: expected {FT004_OWN_FUNDS}, got {row['own_funds_requirement'][0]!r}. "
        "150_000 × 1.00 = 150_000. CRR Art. 378."
    )


# ===========================================================================
# 5. FT005 — non-DvP free delivery, t+6, Col 4 (1250% RW)
# ===========================================================================


def test_p8_24_non_dvp_ft005_rwa() -> None:
    """FT005: non-DvP t+6 -> band non_dvp_col4_t5_plus, RWA = 2,050,000 × 12.5 = 25,625,000.

    Arrange:
        FT005: value_transferred=1_000_000, current_positive_exposure=1_050_000.
        Art. 379(1) Table 2 Col 4 (t+5 onwards): exposure = 1M + 1.05M = 2_050_000.
        RW = 1250% -> RWA multiplier = 12.5; own_funds = exposure = 2_050_000.
        RWA = 2_050_000 × 12.5 = 25_625_000.

    Act: compute_failed_trade_rwa(lf, config).collect(), filter to FT005.

    Assert:
        failed_trade_rwa == 25_625_000.0
        regulatory_band  == "non_dvp_col4_t5_plus"
        own_funds_requirement == 2_050_000.0

    References: CRR Art. 379(1) + Table 2.
    """
    # Arrange
    lf = make_failed_trades_frame()

    # Act
    result = compute_failed_trade_rwa(lf, _CONFIG).collect()
    row = result.filter(pl.col("failed_trade_id") == FT005_ID)

    # Assert
    assert row["failed_trade_rwa"][0] == pytest.approx(FT005_RWA, abs=1e-6), (
        f"FT005 RWA: expected {FT005_RWA}, got {row['failed_trade_rwa'][0]!r}. "
        "non-DvP t+6: exposure=2_050_000, Col 4 multiplier=12.5, RWA=25_625_000. "
        "CRR Art. 379(1) Table 2."
    )
    assert row["regulatory_band"][0] == FT005_BAND, (
        f"FT005 band: expected {FT005_BAND!r}, got {row['regulatory_band'][0]!r}. "
        "6 working days non-DvP -> non_dvp_col4_t5_plus (t+5 onwards column 4)."
    )
    assert row["own_funds_requirement"][0] == pytest.approx(FT005_OWN_FUNDS, abs=1e-6), (
        f"FT005 own_funds: expected {FT005_OWN_FUNDS}, got {row['own_funds_requirement'][0]!r}. "
        "Art. 379(1): own_funds = full exposure amount = 2_050_000."
    )


# ===========================================================================
# 6. Portfolio aggregate — sum of all 5 rows = 29,737,500
# ===========================================================================


def test_p8_24_portfolio_total_rwa() -> None:
    """Portfolio total: sum of 5 rows = 29,737,500.

    Arrange:
        FT001 RWA     50,000
        FT002 RWA  1,250,000
        FT003 RWA    937,500
        FT004 RWA  1,875,000
        FT005 RWA 25,625,000
        -----------------------
        Total     29,737,500

    Act: compute_failed_trade_rwa(lf, config).collect(), sum failed_trade_rwa.

    Assert: sum(failed_trade_rwa) == 29_737_500.0 (abs tolerance 1e-3).

    References: CRR Art. 378 + Art. 379(1).
    """
    # Arrange
    lf = make_failed_trades_frame()

    # Act
    result = compute_failed_trade_rwa(lf, _CONFIG).collect()
    total = result["failed_trade_rwa"].sum()

    # Assert
    assert total == pytest.approx(PORTFOLIO_TOTAL_RWA, abs=1e-3), (
        f"Portfolio total RWA: expected {PORTFOLIO_TOTAL_RWA}, got {total!r}. "
        "FT001(50k)+FT002(1.25M)+FT003(937.5k)+FT004(1.875M)+FT005(25.625M)=29.7375M. "
        "CRR Art. 378 + Art. 379(1)."
    )
