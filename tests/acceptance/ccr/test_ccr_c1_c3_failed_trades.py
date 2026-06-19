"""
CCR-C1 / CCR-C2 / CCR-C3: failed-trade (DvP) settlement risk — three Art. 378 bands.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator -> OutputAggregator

Key responsibilities:
- Validate that failed-trade DvP RWA is wired into the full pipeline output,
  producing synthetic SA exposure rows per Art. 378.
- Validate per-row RWA against the three Art. 378 Table 1 multiplier bands
  (t+5-15, t+31-45, t+46+) using the P8.43 fixture-builder constants.
- Validate portfolio-total RWA delta (with vs without failed_trades) == 13,850,000.

Scenario (three independent DvP rows):
    CCR-C1: FT_C1, t+6  days, band dvp_5_15,   mult 8%   -> RWA   100,000
    CCR-C2: FT_C2, t+35 days, band dvp_31_45,  mult 75%  -> RWA 7,500,000
    CCR-C3: FT_C3, t+46 days, band dvp_46_plus, mult 100% -> RWA 6,250,000
    Portfolio total RWA = 13,850,000.

Expected synthetic row provenance contract (agreed with engine-implementer):
    exposure_reference = 'ft__' + failed_trade_id   (e.g. 'ft__FT_C1')
    risk_type          = 'SETTLEMENT_FAILED_TRADE'
    ccr_method         = 'failed_trade'
    drawn_amount       = own_funds_requirement
    risk_weight        = 12.5
    rwa                = failed_trade_rwa   (or rwa_final in the aggregated frame)

EXPECTED FAILURE MODE (pre-implementation):
    The failed-trade calculator (P8.24) is not yet wired into the CCR stage
    (engine/stages/ccr.py). The pipeline emits zero synthetic FT rows, so the
    firm-total RWA delta (with vs without failed_trades) is 0, not 13,850,000.
    The PRIMARY assertion (delta == 13,850,000) fails first with AssertionError.

References:
    - CRR Art. 378 + Table 1 (DvP price-difference × multiplier ladder)
    - CRR Art. 92(3)(ca) (own-funds × 12.5 = RWA)
    - tests/fixtures/ccr/p843_failed_trade_builder.py: fixture builder
    - src/rwa_calc/engine/ccr/failed_trades.py: compute_failed_trade_rwa (P8.24)
    - src/rwa_calc/engine/stages/ccr.py: CCR pipeline stage (wiring target)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    FailedTradesBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    MARGIN_AGREEMENT_SCHEMA,
    NETTING_SET_SCHEMA,
    TRADE_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.p843_failed_trade_builder import (
    FT_C1_ID,
    FT_C1_RWA,
    FT_C2_ID,
    FT_C2_RWA,
    FT_C3_ID,
    FT_C3_RWA,
    PORTFOLIO_TOTAL_RWA,
    make_c_failed_trades_frame,
    make_minimal_counterparties_frame,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2027, 1, 15)

# Provenance contract — the engine-implementer will produce exactly these values
# on synthetic SA exposure rows emitted for each failed trade.
_SYNTHETIC_RISK_TYPE: str = "SETTLEMENT_FAILED_TRADE"
_SYNTHETIC_CCR_METHOD: str = "failed_trade"
_SYNTHETIC_RW: float = 12.5

_FT_C1_EXPOSURE_REF: str = f"ft__{FT_C1_ID}"
_FT_C2_EXPOSURE_REF: str = f"ft__{FT_C2_ID}"
_FT_C3_EXPOSURE_REF: str = f"ft__{FT_C3_ID}"


# ---------------------------------------------------------------------------
# Bundle helpers
# ---------------------------------------------------------------------------


def _build_empty_trades() -> pl.LazyFrame:
    """Return a zero-row trades LazyFrame (P8.43 has no SA-CCR derivative trades)."""
    return pl.LazyFrame(schema=dtypes_of(TRADE_SCHEMA))


def _build_empty_netting_sets() -> pl.LazyFrame:
    """Return a zero-row netting-sets LazyFrame (no derivative netting sets)."""
    return pl.LazyFrame(schema=dtypes_of(NETTING_SET_SCHEMA))


def _build_empty_margin_agreements() -> pl.LazyFrame:
    """Return a zero-row margin-agreements LazyFrame (no CSA)."""
    return pl.LazyFrame(schema=dtypes_of(MARGIN_AGREEMENT_SCHEMA))


def _build_empty_ccr_collateral() -> pl.LazyFrame:
    """Return a zero-row CCR-collateral LazyFrame (no CCR collateral)."""
    return pl.LazyFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


def _build_ccr_bundle_with_failed_trades() -> RawCCRBundle:
    """
    Assemble a RawCCRBundle with failed_trades populated and empty SA-CCR frames.

    The three FT rows (FT_C1/C2/C3) are the only CCR content — no derivative
    trades, netting sets, margin agreements, or CCR collateral.
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=_build_empty_trades()),
        netting_sets=NettingSetBundle(netting_sets=_build_empty_netting_sets()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=_build_empty_margin_agreements()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=_build_empty_ccr_collateral()),
        failed_trades=FailedTradesBundle(failed_trades=make_c_failed_trades_frame()),
    )


def _build_ccr_bundle_no_failed_trades() -> RawCCRBundle:
    """
    Assemble a RawCCRBundle with failed_trades=None (baseline — no failed trades).

    Structurally identical to _build_ccr_bundle_with_failed_trades() but
    with failed_trades=None so the failed-trade pipeline sub-stage is skipped.
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=_build_empty_trades()),
        netting_sets=NettingSetBundle(netting_sets=_build_empty_netting_sets()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=_build_empty_margin_agreements()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=_build_empty_ccr_collateral()),
        failed_trades=None,
    )


def _build_config() -> CalculationConfig:
    """
    Basel 3.1 config for CCR-C1/C2/C3 (regime-invariant Art. 378 numerics).

    Failed-trade RWA is regime-invariant (CRR Art. 378 carried into PS1/26
    unchanged), so Basel 3.1 config is used per scenario specification.
    """
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_c123_with_failed_trades_results() -> pl.DataFrame:
    """
    Run the CCR-C1/C2/C3 bundle (with failed_trades) through the Basel 3.1
    pipeline and return the collected results DataFrame.

    Arrange:
        - 3 failed DvP trades (FT_C1 t+6, FT_C2 t+35, FT_C3 t+46)
        - Corporate counterparties CP_FT_C1/C2/C3 (entity_type='corporate')
        - No SA-CCR derivative trades / netting sets
        - Basel 3.1 config, STANDARDISED permission mode
    Act:
        Full Basel 3.1 pipeline via PipelineOrchestrator.
    Returns:
        Collected results DataFrame from AggregatedResultBundle.results.
    """
    # Arrange
    bundle = make_raw_bundle(
        counterparties=make_minimal_counterparties_frame(),
        ccr=_build_ccr_bundle_with_failed_trades(),
    )
    config = _build_config()

    # Act
    result = PipelineOrchestrator().run_with_data(bundle, config)
    return result.results.collect()


@pytest.fixture(scope="module")
def ccr_c123_no_failed_trades_results() -> pl.DataFrame:
    """
    Run the baseline bundle (no failed_trades) through the Basel 3.1 pipeline
    and return the collected results DataFrame.

    Identical input to ccr_c123_with_failed_trades_results() except
    failed_trades=None — the pipeline skips the failed-trade sub-stage.
    Used for the primary delta assertion.
    """
    # Arrange
    bundle = make_raw_bundle(
        counterparties=make_minimal_counterparties_frame(),
        ccr=_build_ccr_bundle_no_failed_trades(),
    )
    config = _build_config()

    # Act
    result = PipelineOrchestrator().run_with_data(bundle, config)
    return result.results.collect()


# ---------------------------------------------------------------------------
# CCR-C1/C2/C3 acceptance tests
# ---------------------------------------------------------------------------


class TestCCRC1C3FailedTrades:
    """
    CCR-C1/C2/C3: DvP failed trades, three Art. 378 Table 1 bands.

    Tests verify:
      1. PRIMARY (robust): firm-total RWA delta (with vs without failed_trades)
         == 13,850,000. TODAY: 0 (not wired) → AssertionError.
      2. Per-row RWA for FT_C1 == 100,000.
      3. Per-row RWA for FT_C2 == 7,500,000.
      4. Per-row RWA for FT_C3 == 6,250,000.
      5. Per-row risk_weight for FT_C1 == 12.5.

    The per-row tests (2-5) filter by exposure_reference ('ft__FT_C1' etc) or
    risk_type ('SETTLEMENT_FAILED_TRADE'). Until the engine wires compute_failed_trade_rwa
    into the CCR stage, these rows are absent and the per-row asserts each raise
    AssertionError (0 synthetic rows found).
    """

    def test_ccr_c1_c3_portfolio_rwa_delta(
        self,
        ccr_c123_with_failed_trades_results: pl.DataFrame,
        ccr_c123_no_failed_trades_results: pl.DataFrame,
    ) -> None:
        """
        PRIMARY: firm-total RWA with failed_trades MINUS firm-total RWA without == 13,850,000.

        Arrange: two pipeline runs — one with FailedTradesBundle (FT_C1/C2/C3),
                 one with failed_trades=None; otherwise identical.
        Act:     sum rwa_final across all rows in each run's results.
        Assert:  delta == 13,850,000 exactly.

        TODAY: the failed-trade sub-stage is unwired from the CCR pipeline stage.
               Both runs produce zero failed-trade RWA, so delta == 0, not 13,850,000.
               This assertion FAILS first and is the primary TDD red signal.

        References:
            CRR Art. 378 + Table 1 (DvP multiplier ladder);
            CRR Art. 92(3)(ca) (own_funds × 12.5 = RWA).
        """
        # Arrange
        df_with = ccr_c123_with_failed_trades_results
        df_without = ccr_c123_no_failed_trades_results

        total_with = df_with["rwa_final"].sum() or 0.0
        total_without = df_without["rwa_final"].sum() or 0.0
        delta = total_with - total_without

        # Assert
        assert delta == pytest.approx(PORTFOLIO_TOTAL_RWA, abs=1.0), (
            f"CCR-C1/C2/C3: expected firm-total RWA delta (with - without failed_trades) "
            f"== {PORTFOLIO_TOTAL_RWA:,.0f}, "
            f"got {delta:,.0f} (with={total_with:,.0f}, without={total_without:,.0f}). "
            "The failed-trade sub-stage (compute_failed_trade_rwa) must be wired into "
            "engine/stages/ccr.py and its synthetic rows appended to the aggregated results. "
            "CRR Art. 378 Table 1: 100,000 + 7,500,000 + 6,250,000 = 13,850,000."
        )

    def test_ccr_c1_rwa(
        self,
        ccr_c123_with_failed_trades_results: pl.DataFrame,
    ) -> None:
        """
        FT_C1 (t+6, dvp_5_15 band, mult 8%): rwa_final == 100,000.

        Arrange: FT_C1, agreed=1,000,000, mv=900,000, days=6 → band dvp_5_15.
                 price_difference = 100,000; own_funds = 100,000 × 0.08 = 8,000;
                 RWA = 8,000 × 12.5 = 100,000.
        Act:     full Basel 3.1 pipeline; filter synthetic row for FT_C1.
        Assert:  rwa_final == 100,000 (abs tol 1.0).

        References:
            CRR Art. 378 Table 1: 5-15 working days overdue → multiplier 8%.
            CRR Art. 92(3)(ca): own_funds × 12.5 = RWA.
        """
        # Arrange
        df = ccr_c123_with_failed_trades_results
        ft_rows = df.filter(pl.col("exposure_reference") == _FT_C1_EXPOSURE_REF)

        assert len(ft_rows) == 1, (
            f"CCR-C1: expected exactly 1 synthetic row with "
            f"exposure_reference={_FT_C1_EXPOSURE_REF!r}, "
            f"got {len(ft_rows)}. "
            "engine/stages/ccr.py must emit one synthetic exposure row per failed trade "
            "with exposure_reference='ft__' + failed_trade_id."
        )

        row = ft_rows.to_dicts()[0]

        # Assert
        assert row["rwa_final"] == pytest.approx(FT_C1_RWA, abs=1.0), (
            f"CCR-C1: expected rwa_final=={FT_C1_RWA:,.0f} "
            f"(price_diff=100,000 × mult=0.08 × 12.5), "
            f"got {row['rwa_final']:,.0f}. "
            "CRR Art. 378 Table 1: 5-15 days overdue → 8% multiplier."
        )

    def test_ccr_c2_rwa(
        self,
        ccr_c123_with_failed_trades_results: pl.DataFrame,
    ) -> None:
        """
        FT_C2 (t+35, dvp_31_45 band, mult 75%): rwa_final == 7,500,000.

        Arrange: FT_C2, agreed=4,000,000, mv=3,200,000, days=35 → band dvp_31_45.
                 price_difference = 800,000; own_funds = 800,000 × 0.75 = 600,000;
                 RWA = 600,000 × 12.5 = 7,500,000.
        Act:     full Basel 3.1 pipeline; filter synthetic row for FT_C2.
        Assert:  rwa_final == 7,500,000 (abs tol 1.0).

        References:
            CRR Art. 378 Table 1: 31-45 working days overdue → multiplier 75%.
            CRR Art. 92(3)(ca): own_funds × 12.5 = RWA.
        """
        # Arrange
        df = ccr_c123_with_failed_trades_results
        ft_rows = df.filter(pl.col("exposure_reference") == _FT_C2_EXPOSURE_REF)

        assert len(ft_rows) == 1, (
            f"CCR-C2: expected exactly 1 synthetic row with "
            f"exposure_reference={_FT_C2_EXPOSURE_REF!r}, "
            f"got {len(ft_rows)}. "
            "engine/stages/ccr.py must emit one synthetic exposure row per failed trade."
        )

        row = ft_rows.to_dicts()[0]

        # Assert
        assert row["rwa_final"] == pytest.approx(FT_C2_RWA, abs=1.0), (
            f"CCR-C2: expected rwa_final=={FT_C2_RWA:,.0f} "
            f"(price_diff=800,000 × mult=0.75 × 12.5), "
            f"got {row['rwa_final']:,.0f}. "
            "CRR Art. 378 Table 1: 31-45 days overdue → 75% multiplier."
        )

    def test_ccr_c3_rwa(
        self,
        ccr_c123_with_failed_trades_results: pl.DataFrame,
    ) -> None:
        """
        FT_C3 (t+46, dvp_46_plus band, mult 100%): rwa_final == 6,250,000.

        Arrange: FT_C3, agreed=2,000,000, mv=1,500,000, days=46 → band dvp_46_plus.
                 price_difference = 500,000; own_funds = 500,000 × 1.00 = 500,000;
                 RWA = 500,000 × 12.5 = 6,250,000.
        Act:     full Basel 3.1 pipeline; filter synthetic row for FT_C3.
        Assert:  rwa_final == 6,250,000 (abs tol 1.0).

        References:
            CRR Art. 378 Table 1: 46+ working days overdue → multiplier 100%.
            CRR Art. 92(3)(ca): own_funds × 12.5 = RWA.
        """
        # Arrange
        df = ccr_c123_with_failed_trades_results
        ft_rows = df.filter(pl.col("exposure_reference") == _FT_C3_EXPOSURE_REF)

        assert len(ft_rows) == 1, (
            f"CCR-C3: expected exactly 1 synthetic row with "
            f"exposure_reference={_FT_C3_EXPOSURE_REF!r}, "
            f"got {len(ft_rows)}. "
            "engine/stages/ccr.py must emit one synthetic exposure row per failed trade."
        )

        row = ft_rows.to_dicts()[0]

        # Assert
        assert row["rwa_final"] == pytest.approx(FT_C3_RWA, abs=1.0), (
            f"CCR-C3: expected rwa_final=={FT_C3_RWA:,.0f} "
            f"(price_diff=500,000 × mult=1.00 × 12.5), "
            f"got {row['rwa_final']:,.0f}. "
            "CRR Art. 378 Table 1: 46+ days overdue → 100% multiplier."
        )

    def test_ccr_c1_risk_weight(
        self,
        ccr_c123_with_failed_trades_results: pl.DataFrame,
    ) -> None:
        """
        Synthetic FT_C1 row carries risk_weight == 12.5 (1250% Art. 378 capital charge).

        Arrange: FT_C1 synthetic row, exposure_reference='ft__FT_C1'.
        Act:     full Basel 3.1 pipeline; filter synthetic row for FT_C1.
        Assert:  risk_weight == 12.5 (1250% expressed as a multiplier per Art. 92(3)(ca)).

        References:
            CRR Art. 378 + Table 1: own_funds × 12.5 maps back to a 1250% SA risk weight.
        """
        # Arrange
        df = ccr_c123_with_failed_trades_results
        ft_rows = df.filter(pl.col("exposure_reference") == _FT_C1_EXPOSURE_REF)

        assert len(ft_rows) == 1, (
            f"CCR-C1 risk_weight: expected exactly 1 synthetic row with "
            f"exposure_reference={_FT_C1_EXPOSURE_REF!r}, got {len(ft_rows)}."
        )

        row = ft_rows.to_dicts()[0]

        # Assert
        assert row["risk_weight"] == pytest.approx(_SYNTHETIC_RW, abs=1e-6), (
            f"CCR-C1: expected risk_weight=={_SYNTHETIC_RW} (1250% as multiplier "
            f"per Art. 92(3)(ca)), got {row['risk_weight']}."
        )
