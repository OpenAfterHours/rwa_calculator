"""
P8.52 — AggregatedResultBundle CCR reporting roll-up columns.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator -> OutputAggregator

Key responsibilities:
- Verify four new scalar roll-up fields on AggregatedResultBundle:
      ead_ccr_total:       float | None  — sum of ead_final over ccr__ rows
      rwa_ccr_default:     float | None  — sum of rwa_final over non-QCCP ccr__ rows
      rwa_ccr_qccp_trade:  float | None  — sum of rwa_final over QCCP ccr__ rows
      failed_trades_rwa:   float | None  — sum of rwa_final over SETTLEMENT_FAILED_TRADE rows

- Case CCR-E1 (CRR institution): ead_ccr_total and rwa_ccr_default populated;
  rwa_ccr_qccp_trade and failed_trades_rwa are None (no QCCP / failed-trade rows).

- Case CCR-CCP-1 (QCCP proprietary, is_client_cleared=False):
  rwa_ccr_qccp_trade populated; rwa_ccr_default is None (all ccr__ rows are QCCP).

- Case CCR-CCP-2 (QCCP client-cleared, is_client_cleared=True):
  rwa_ccr_qccp_trade populated at 4% (vs 2% proprietary).

- Case CCR-C (failed trades, three DvP rows):
  failed_trades_rwa populated; ead_ccr_total and rwa_ccr_default are None.

- Reconciliation invariant: (rwa_ccr_default or 0) + (rwa_ccr_qccp_trade or 0)
  == Σ rwa_final over all ccr__ rows.

- Empty-portfolio regression: non-CCR SA bundle gives all four fields None.

Fail-first signals:
    The four new fields do NOT yet exist on AggregatedResultBundle.
    Direct attribute access would raise AttributeError; we use getattr with
    a sentinel default to produce a clean AssertionError on the first test.
    Once the engine-implementer adds the fields and populates them, the
    attribute guards pass and the value assertions drive the next failure.

References:
    - CRR Art. 274(2) — SA-CCR EAD = alpha * (RC + PFE) (ead_ccr_total source)
    - CRR Art. 107(2)(a), Art. 114/120/122 — SA RW on CCR EAD (rwa_ccr_default)
    - CRR Art. 306(1)(a)/(c), Art. 306(4) — 2%/4% QCCP trade-leg RW (rwa_ccr_qccp_trade)
    - CRR Art. 378 + Table 1, Art. 92(3)(ca) — failed-trade own-funds × 12.5 (failed_trades_rwa)
    - tests/fixtures/ccr/p845_e1_e5_builder.py — CCR-E1 bundle / CRR config
    - tests/fixtures/ccr/p839_ccp_builder.py — QCCP bundles (CCP-1 / CCP-2)
    - tests/fixtures/ccr/p843_failed_trade_builder.py — failed-trade CCR-C bundle
    - tests/fixtures/reporting_portfolio.py — empty-portfolio regression
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
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.p843_failed_trade_builder import (
    PORTFOLIO_TOTAL_RWA as FT_PORTFOLIO_TOTAL_RWA,
    make_c_failed_trades_frame,
    make_minimal_counterparties_frame as make_ft_counterparties_frame,
)
from tests.fixtures.ccr.p845_e1_e5_builder import (
    build_raw_data_bundle_ccr_e1,
    make_crr_config,
)
from tests.fixtures.ccr.p839_ccp_builder import (
    P839_RW_CLIENT_CLEARED,
    P839_RW_PROPRIETARY,
    build_p839_bundle,
)
from tests.fixtures.raw_bundle import make_raw_bundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    MARGIN_AGREEMENT_SCHEMA,
    NETTING_SET_SCHEMA,
    TRADE_SCHEMA,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from tests.fixtures.reporting_portfolio import build_reporting_bundle

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: CRR era reporting date — used for E1, CCP-1, CCP-2 (CRR SA risk weights).
_CRR_REPORTING_DATE: date = date(2026, 1, 15)

#: Basel 3.1 era reporting date — used for the failed-trade CCR-C bundle.
#: Art. 378 numerics are regime-invariant, but we keep a B3.1 date consistent
#: with the existing test_ccr_c1_c3_failed_trades.py pattern.
_FT_REPORTING_DATE: date = date(2027, 1, 15)

#: Sentinel returned by getattr when a field is absent — distinct from None
#: so we can tell "field missing" from "field present but None".
_MISSING = object()

#: QCCP roll-up discriminator constants (mirrors aggregator.py filter logic).
_CP_ENTITY_TYPE_CCP: str = "ccp"


# ---------------------------------------------------------------------------
# Helpers for failed-trade bundle construction
# (mirrors _build_ccr_bundle_with_failed_trades in test_ccr_c1_c3_failed_trades.py)
# ---------------------------------------------------------------------------


def _build_empty_trades_lf() -> pl.LazyFrame:
    """Return a zero-row trades LazyFrame."""
    return pl.LazyFrame(schema=dtypes_of(TRADE_SCHEMA))


def _build_empty_netting_sets_lf() -> pl.LazyFrame:
    """Return a zero-row netting-sets LazyFrame."""
    return pl.LazyFrame(schema=dtypes_of(NETTING_SET_SCHEMA))


def _build_empty_margin_agreements_lf() -> pl.LazyFrame:
    """Return a zero-row margin-agreements LazyFrame."""
    return pl.LazyFrame(schema=dtypes_of(MARGIN_AGREEMENT_SCHEMA))


def _build_empty_ccr_collateral_lf() -> pl.LazyFrame:
    """Return a zero-row CCR-collateral LazyFrame."""
    return pl.LazyFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


def _build_ccr_bundle_with_failed_trades() -> RawCCRBundle:
    """
    Assemble a RawCCRBundle with failed_trades populated and empty SA-CCR frames.

    Three DvP failed-trade rows (FT_C1/C2/C3) from the P8.43 builder.
    No derivative trades, netting sets, margin agreements, or CCR collateral.
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=_build_empty_trades_lf()),
        netting_sets=NettingSetBundle(netting_sets=_build_empty_netting_sets_lf()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=_build_empty_margin_agreements_lf()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=_build_empty_ccr_collateral_lf()),
        failed_trades=FailedTradesBundle(failed_trades=make_c_failed_trades_frame()),
    )


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def e1_result():
    """
    Run CCR-E1 (CRR institution, CQS 2) through the full CRR SA pipeline.

    Returns the AggregatedResultBundle.

    Arrange:
        - build_raw_data_bundle_ccr_e1(): institution CP_E1, CQS 2, CRR.
        - Config: CRR, 2026-01-15, STANDARDISED.
    Act:
        Full CRR pipeline via PipelineOrchestrator.
    """
    bundle = build_raw_data_bundle_ccr_e1()
    config = make_crr_config()
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def e1_results_df(e1_result) -> pl.DataFrame:
    """Materialised results DataFrame for CCR-E1."""
    return e1_result.results.collect()


@pytest.fixture(scope="module")
def ccp1_result():
    """
    Run CCR-CCP-1 (QCCP proprietary, is_client_cleared=False) through CRR pipeline.

    Returns the AggregatedResultBundle.

    Arrange:
        - build_p839_bundle(is_client_cleared=False): QCCP counterparty, CRR.
        - Config: CRR, 2026-01-15, STANDARDISED.
    Act:
        Full CRR pipeline via PipelineOrchestrator.
    """
    bundle = build_p839_bundle(is_client_cleared=False)
    config = CalculationConfig.crr(
        reporting_date=_CRR_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def ccp1_results_df(ccp1_result) -> pl.DataFrame:
    """Materialised results DataFrame for CCR-CCP-1."""
    return ccp1_result.results.collect()


@pytest.fixture(scope="module")
def ccp2_result():
    """
    Run CCR-CCP-2 (QCCP client-cleared, is_client_cleared=True) through CRR pipeline.

    Returns the AggregatedResultBundle.

    Arrange:
        - build_p839_bundle(is_client_cleared=True): QCCP counterparty, CRR.
        - Config: CRR, 2026-01-15, STANDARDISED.
    Act:
        Full CRR pipeline via PipelineOrchestrator.
    """
    bundle = build_p839_bundle(is_client_cleared=True)
    config = CalculationConfig.crr(
        reporting_date=_CRR_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def ccp2_results_df(ccp2_result) -> pl.DataFrame:
    """Materialised results DataFrame for CCR-CCP-2."""
    return ccp2_result.results.collect()


@pytest.fixture(scope="module")
def ft_result():
    """
    Run failed-trades bundle (CCR-C1/C2/C3) through Basel 3.1 pipeline.

    Returns the AggregatedResultBundle.

    Arrange:
        - 3 DvP failed trades (FT_C1 t+6, FT_C2 t+35, FT_C3 t+46).
        - Corporate counterparties CP_FT_C1/C2/C3.
        - No SA-CCR derivative trades or netting sets.
        - Config: Basel 3.1, 2027-01-15, STANDARDISED.
    Act:
        Full Basel 3.1 pipeline via PipelineOrchestrator.
    """
    bundle = make_raw_bundle(
        counterparties=make_ft_counterparties_frame(),
        ccr=_build_ccr_bundle_with_failed_trades(),
    )
    config = CalculationConfig.basel_3_1(
        reporting_date=_FT_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def ft_results_df(ft_result) -> pl.DataFrame:
    """Materialised results DataFrame for the failed-trades run."""
    return ft_result.results.collect()


@pytest.fixture(scope="module")
def empty_portfolio_result():
    """
    Run a non-CCR SA portfolio (ccr=None) through the CRR pipeline.

    Returns the AggregatedResultBundle.

    Arrange:
        - build_reporting_bundle(): rich SA/IRB/SL portfolio, ccr=None.
        - Config: CRR, 2025-12-31, STANDARDISED.
    Act:
        Full CRR pipeline via PipelineOrchestrator.
    """
    bundle = build_reporting_bundle()
    config = CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


# ---------------------------------------------------------------------------
# Case 1: CCR-E1 — institution, no QCCP / failed trades
# ---------------------------------------------------------------------------


class TestP852CCRE1RollUps:
    """
    P8.52 / CCR-E1: ead_ccr_total and rwa_ccr_default populated for a plain institution run.

    Four assertions:
      1. ead_ccr_total is not None (field must exist and be populated).
      2. ead_ccr_total == sum of ead_final over ccr__ rows (self-derived).
      3. rwa_ccr_default == sum of rwa_final over non-QCCP ccr__ rows (self-derived).
      4. rwa_ccr_qccp_trade is None (no QCCP rows in E1).
      5. failed_trades_rwa is None (no failed-trade rows in E1).

    All assertions use getattr(result, field_name, _MISSING) to produce a clean
    AssertionError when the field is absent rather than an AttributeError.

    References:
        - CRR Art. 274(2): SA-CCR EAD = alpha * (RC + PFE) — source of ead_ccr_total.
        - CRR Art. 120(1) Table 3: institution CQS 2 -> 50% (source of rwa_ccr_default).
    """

    def test_p852_ccr_e1_ead_ccr_total_not_none(
        self,
        e1_result,
    ) -> None:
        """
        ead_ccr_total must be populated (not None) for CCR-E1 (institution, one netting set).

        Arrange:
            CCR-E1 run: 1 institution CP, 1 netting set, 1 trade.
        Act:
            Full CRR pipeline; read ead_ccr_total from AggregatedResultBundle.
        Assert:
            ead_ccr_total is not None.

        FAILS TODAY: ead_ccr_total does not yet exist on AggregatedResultBundle.
        The getattr sentinel guard produces AssertionError (not AttributeError).

        Engine-implementer must:
            (1) Add ead_ccr_total: float | None = None to AggregatedResultBundle.
            (2) Populate it in aggregator.py as Σ ead_final over ccr__-prefixed rows.

        References:
            CRR Art. 274(2) — SA-CCR EAD = alpha * (RC + PFE).
        """
        # Arrange
        result = e1_result

        # Act — use sentinel guard to produce AssertionError rather than AttributeError
        val = getattr(result, "ead_ccr_total", _MISSING)

        # Assert
        assert val is not _MISSING, (
            "AggregatedResultBundle.ead_ccr_total does not exist (P8.52 not yet implemented). "
            "Engine-implementer: add 'ead_ccr_total: float | None = None' to the dataclass "
            "and populate it in aggregator.py as Σ ead_final over rows where "
            "exposure_reference.str.starts_with('ccr__')."
        )
        assert val is not None, (
            "P8.52 CCR-E1: ead_ccr_total must be populated (not None) for a run "
            "that contains CCR derivative rows (ccr__ prefixed). "
            "The aggregator must set ead_ccr_total = Σ ead_final where "
            "exposure_reference.str.starts_with('ccr__')."
        )

    def test_p852_ccr_e1_ead_ccr_total_equals_row_sum(
        self,
        e1_result,
        e1_results_df: pl.DataFrame,
    ) -> None:
        """
        ead_ccr_total == sum of ead_final over ccr__ rows (self-deriving assertion).

        Arrange:
            CCR-E1 result; ccr_rows filtered from materialised results DataFrame.
        Act:
            Compute expected_ead_total = ccr_rows["ead_final"].sum().
            Read ead_ccr_total from AggregatedResultBundle.
        Assert:
            ead_ccr_total == pytest.approx(expected_ead_total, rel=1e-9).

        Self-deriving: we never transcribe a literal; we rely on what the engine
        produced as the per-row EAD and assert the bundle-level roll-up matches
        the sum we compute ourselves from the same result frame.

        References:
            CRR Art. 274(2): EAD = alpha * (RC + PFE); ead_ccr_total is the sum.
        """
        # Arrange
        df = e1_results_df
        ccr_rows = df.filter(pl.col("exposure_reference").str.starts_with("ccr__"))
        expected_ead_total = ccr_rows["ead_final"].sum()

        # Act
        val = getattr(e1_result, "ead_ccr_total", _MISSING)

        # Assert
        assert val is not _MISSING, (
            "AggregatedResultBundle.ead_ccr_total does not exist (P8.52 not yet implemented)."
        )
        assert val == pytest.approx(expected_ead_total, rel=1e-9), (
            f"P8.52 CCR-E1: expected ead_ccr_total == {expected_ead_total:,.6f} "
            f"(sum of ead_final over ccr__ rows), got {val!r}. "
            "The aggregator must roll up Σ ead_final over rows where "
            "exposure_reference.str.starts_with('ccr__') (risk_type='CCR_DERIVATIVE'). "
            "CRR Art. 274(2): ead_ccr_total = Σ alpha*(RC+PFE) per netting set."
        )

    def test_p852_ccr_e1_rwa_ccr_default_equals_non_qccp_sum(
        self,
        e1_result,
        e1_results_df: pl.DataFrame,
    ) -> None:
        """
        rwa_ccr_default == sum of rwa_final over non-QCCP ccr__ rows (self-deriving).

        Non-QCCP discriminator: NOT (cp_entity_type == "ccp" AND cp_is_qccp.fill_null(True)).
        For CCR-E1 (institution counterparty) all ccr__ rows are non-QCCP, so this
        equals the full sum of rwa_final over ccr__ rows.

        Arrange:
            CCR-E1 result; filter by ccr__ prefix and QCCP discriminator.
        Act:
            Compute expected via Polars; read rwa_ccr_default from bundle.
        Assert:
            rwa_ccr_default == pytest.approx(expected_non_qccp_rwa, rel=1e-9).

        References:
            CRR Art. 107(2)(a), Art. 120(1) Table 3: institution CQS 2 -> 50% SA RW.
        """
        # Arrange
        df = e1_results_df
        # Mirror the aggregator's filter: ccr__ rows that are NOT QCCP trade-leg rows
        ccr_rows = df.filter(pl.col("exposure_reference").str.starts_with("ccr__"))
        # QCCP discriminator: cp_entity_type=="ccp" AND cp_is_qccp.fill_null(True)
        if "cp_entity_type" in ccr_rows.columns and "cp_is_qccp" in ccr_rows.columns:
            non_qccp_rows = ccr_rows.filter(
                ~(
                    (pl.col("cp_entity_type") == _CP_ENTITY_TYPE_CCP)
                    & pl.col("cp_is_qccp").fill_null(True)
                )
            )
        else:
            # Columns not on result frame yet — fall back to all ccr__ rows
            non_qccp_rows = ccr_rows
        expected_rwa_default = non_qccp_rows["rwa_final"].sum()

        # Act
        val = getattr(e1_result, "rwa_ccr_default", _MISSING)

        # Assert
        assert val is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_default does not exist (P8.52 not yet implemented). "
            "Engine-implementer: add 'rwa_ccr_default: float | None = None' to the dataclass "
            "and populate it in aggregator.py as Σ rwa_final over ccr__ rows that are NOT "
            "QCCP trade-leg rows (cp_entity_type=='ccp' AND cp_is_qccp.fill_null(True))."
        )
        assert val == pytest.approx(expected_rwa_default, rel=1e-9), (
            f"P8.52 CCR-E1: expected rwa_ccr_default == {expected_rwa_default:,.6f} "
            f"(Σ rwa_final over non-QCCP ccr__ rows), got {val!r}. "
            "Institution (not a CCP) so all ccr__ rows are non-QCCP. "
            "CRR Art. 107(2)(a), Art. 120(1) Table 3."
        )

    def test_p852_ccr_e1_rwa_ccr_qccp_trade_is_none(
        self,
        e1_result,
    ) -> None:
        """
        rwa_ccr_qccp_trade must be None for CCR-E1 (no QCCP rows).

        Arrange:
            CCR-E1: institution counterparty (is_qccp not set / False).
        Act:
            Read rwa_ccr_qccp_trade from AggregatedResultBundle.
        Assert:
            rwa_ccr_qccp_trade is None (no QCCP rows to sum).

        References:
            CRR Art. 306(1)(a)/(c): QCCP 2%/4% weights only apply when cp_is_qccp=True.
        """
        # Arrange / Act
        val = getattr(e1_result, "rwa_ccr_qccp_trade", _MISSING)

        # Assert
        assert val is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_qccp_trade does not exist (P8.52 not yet implemented). "
            "Engine-implementer: add 'rwa_ccr_qccp_trade: float | None = None' to the dataclass."
        )
        assert val is None, (
            f"P8.52 CCR-E1: expected rwa_ccr_qccp_trade=None (no QCCP trade-leg rows "
            f"in the E1 institution run), got {val!r}. "
            "rwa_ccr_qccp_trade must be None (not 0.0) when the filtered frame is empty. "
            "CRR Art. 306(1): QCCP RW pins only apply to cp_is_qccp=True rows."
        )

    def test_p852_ccr_e1_failed_trades_rwa_is_none(
        self,
        e1_result,
    ) -> None:
        """
        failed_trades_rwa must be None for CCR-E1 (no failed-trade rows).

        Arrange:
            CCR-E1: derivative trades only, no failed_trades bundle.
        Act:
            Read failed_trades_rwa from AggregatedResultBundle.
        Assert:
            failed_trades_rwa is None.

        References:
            CRR Art. 378 + Table 1: only applies when failed_trades frame is present.
        """
        # Arrange / Act
        val = getattr(e1_result, "failed_trades_rwa", _MISSING)

        # Assert
        assert val is not _MISSING, (
            "AggregatedResultBundle.failed_trades_rwa does not exist (P8.52 not yet implemented). "
            "Engine-implementer: add 'failed_trades_rwa: float | None = None' to the dataclass."
        )
        assert val is None, (
            f"P8.52 CCR-E1: expected failed_trades_rwa=None (no SETTLEMENT_FAILED_TRADE rows "
            f"in the E1 run), got {val!r}. "
            "failed_trades_rwa must be None (not 0.0) when risk_type='SETTLEMENT_FAILED_TRADE' "
            "rows are absent from the result frame. "
            "CRR Art. 378: only applies when a failed_trades bundle is provided."
        )


# ---------------------------------------------------------------------------
# Case 2: CCR-CCP-1 — QCCP proprietary (2%)
# ---------------------------------------------------------------------------


class TestP852CCRCcp1QccpProprietaryRollUp:
    """
    P8.52 / CCR-CCP-1: rwa_ccr_qccp_trade populated for QCCP proprietary run.

    The entire ccr__ row set is QCCP (cp_is_qccp=True), so:
      - rwa_ccr_qccp_trade == Σ rwa_final over qccp ccr__ rows == ead_ccr_total * 0.02
      - rwa_ccr_default is None (no non-QCCP ccr__ rows)

    References:
        - CRR Art. 306(1)(a): 2% RW for proprietary QCCP trade exposures.
        - CRR Art. 306(4): RWA = EAD * RW.
    """

    def test_p852_ccp1_rwa_ccr_qccp_trade_not_none(
        self,
        ccp1_result,
    ) -> None:
        """
        rwa_ccr_qccp_trade must be populated (not None) for CCR-CCP-1.

        Arrange:
            QCCP proprietary run: cp_is_qccp=True, is_client_cleared=False.
        Act:
            Read rwa_ccr_qccp_trade from AggregatedResultBundle.
        Assert:
            rwa_ccr_qccp_trade is not None.

        FAILS TODAY: field does not exist on AggregatedResultBundle.
        Sentinel guard produces AssertionError (not AttributeError).
        """
        # Arrange / Act
        val = getattr(ccp1_result, "rwa_ccr_qccp_trade", _MISSING)

        # Assert
        assert val is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_qccp_trade does not exist (P8.52 not yet implemented)."
        )
        assert val is not None, (
            "P8.52 CCR-CCP-1: rwa_ccr_qccp_trade must be populated (not None) for a run "
            "that contains QCCP trade-leg rows (cp_is_qccp=True). "
            "CRR Art. 306(1)(a): proprietary QCCP trade exposure -> 2% RW."
        )

    def test_p852_ccp1_rwa_ccr_qccp_trade_equals_row_sum(
        self,
        ccp1_result,
        ccp1_results_df: pl.DataFrame,
    ) -> None:
        """
        rwa_ccr_qccp_trade == sum of rwa_final over QCCP ccr__ rows (self-deriving).

        For CCR-CCP-1 this must also equal ead_ccr_total * 0.02 (proprietary weight).

        Arrange:
            CCP-1 result; filter ccr__ rows where cp_entity_type=="ccp" AND cp_is_qccp=True.
        Act:
            Compute expected Σ rwa_final; read rwa_ccr_qccp_trade from bundle.
        Assert:
            rwa_ccr_qccp_trade == pytest.approx(expected, rel=1e-9).

        References:
            CRR Art. 306(1)(a): proprietary QCCP 2% risk weight.
        """
        # Arrange
        df = ccp1_results_df
        ccr_rows = df.filter(pl.col("exposure_reference").str.starts_with("ccr__"))
        if "cp_entity_type" in ccr_rows.columns and "cp_is_qccp" in ccr_rows.columns:
            qccp_rows = ccr_rows.filter(
                (pl.col("cp_entity_type") == _CP_ENTITY_TYPE_CCP)
                & pl.col("cp_is_qccp").fill_null(True)
            )
        else:
            qccp_rows = ccr_rows  # fallback: use all ccr__ rows
        expected_qccp_rwa = qccp_rows["rwa_final"].sum()

        # Act
        val = getattr(ccp1_result, "rwa_ccr_qccp_trade", _MISSING)

        # Assert
        assert val is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_qccp_trade does not exist (P8.52 not yet implemented)."
        )
        assert val == pytest.approx(expected_qccp_rwa, rel=1e-9), (
            f"P8.52 CCR-CCP-1: expected rwa_ccr_qccp_trade == {expected_qccp_rwa:,.6f} "
            f"(Σ rwa_final over QCCP ccr__ rows), got {val!r}. "
            "QCCP discriminator: cp_entity_type=='ccp' AND cp_is_qccp.fill_null(True). "
            "CRR Art. 306(1)(a): proprietary QCCP 2% -> rwa_final = ead_final * 0.02."
        )

    def test_p852_ccp1_rwa_ccr_qccp_trade_equals_ead_times_002(
        self,
        ccp1_result,
    ) -> None:
        """
        rwa_ccr_qccp_trade == pytest.approx(ead_ccr_total * 0.02, rel=1e-9).

        The QCCP proprietary weight is 2% (CRR Art. 306(1)(a)), so rwa_ccr_qccp_trade
        must equal the total QCCP EAD * 0.02.

        Arrange:
            CCP-1 result; ead_ccr_total and rwa_ccr_qccp_trade read from bundle.
        Act:
            Compute expected = ead_ccr_total * P839_RW_PROPRIETARY (0.02).
        Assert:
            rwa_ccr_qccp_trade == pytest.approx(expected, rel=1e-9).

        References:
            CRR Art. 306(1)(a): 2% RW; CRR Art. 306(4): RWA = EAD * RW.
        """
        # Arrange
        ead_total = getattr(ccp1_result, "ead_ccr_total", _MISSING)
        rwa_qccp = getattr(ccp1_result, "rwa_ccr_qccp_trade", _MISSING)

        # Guard: both fields must exist
        assert ead_total is not _MISSING, (
            "AggregatedResultBundle.ead_ccr_total does not exist (P8.52 not yet implemented)."
        )
        assert rwa_qccp is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_qccp_trade does not exist (P8.52 not yet implemented)."
        )

        if ead_total is None or rwa_qccp is None:
            pytest.skip("ead_ccr_total or rwa_ccr_qccp_trade is None — covered by other tests")

        expected = ead_total * P839_RW_PROPRIETARY  # EAD * 0.02

        # Assert
        assert rwa_qccp == pytest.approx(expected, rel=1e-9), (
            f"P8.52 CCR-CCP-1: expected rwa_ccr_qccp_trade == ead_ccr_total * 0.02 "
            f"= {expected:,.6f}, got {rwa_qccp!r}. "
            f"ead_ccr_total={ead_total!r}. "
            "CRR Art. 306(1)(a): QCCP proprietary trade-leg risk weight is 2%. "
            "CRR Art. 274(2): EAD = alpha * (RC + PFE)."
        )

    def test_p852_ccp1_rwa_ccr_default_is_none(
        self,
        ccp1_result,
    ) -> None:
        """
        rwa_ccr_default must be None for CCR-CCP-1 (all ccr__ rows are QCCP).

        The entire run is one QCCP netting set; no non-QCCP ccr__ rows exist.

        Arrange:
            CCP-1 result: cp_is_qccp=True for the single counterparty.
        Act:
            Read rwa_ccr_default from AggregatedResultBundle.
        Assert:
            rwa_ccr_default is None (empty non-QCCP partition).

        References:
            CRR Art. 306(1)(a): QCCP rows excluded from rwa_ccr_default.
        """
        # Arrange / Act
        val = getattr(ccp1_result, "rwa_ccr_default", _MISSING)

        # Assert
        assert val is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_default does not exist (P8.52 not yet implemented)."
        )
        assert val is None, (
            f"P8.52 CCR-CCP-1: expected rwa_ccr_default=None (all ccr__ rows are QCCP, "
            f"so the non-QCCP partition is empty), got {val!r}. "
            "When the non-QCCP ccr__ filtered frame is empty the roll-up must return None "
            "(not 0.0), consistent with rwa_ccr_default_fund semantics. "
            "CRR Art. 306(1)(a): QCCP trade-leg rows are excluded from the default-risk partition."
        )


# ---------------------------------------------------------------------------
# Case 3: CCR-CCP-2 — QCCP client-cleared (4%)
# ---------------------------------------------------------------------------


class TestP852CCRCcp2QccpClientClearedRollUp:
    """
    P8.52 / CCR-CCP-2: rwa_ccr_qccp_trade uses 4% weight for client-cleared.

    rwa_ccr_qccp_trade == ead_ccr_total * 0.04 (CRR Art. 306(1)(c)).

    References:
        - CRR Art. 306(1)(c): 4% RW for client-cleared QCCP trade exposures.
        - CRR Art. 306(4): RWA = EAD * RW.
    """

    def test_p852_ccp2_rwa_ccr_qccp_trade_equals_ead_times_004(
        self,
        ccp2_result,
    ) -> None:
        """
        rwa_ccr_qccp_trade == pytest.approx(ead_ccr_total * 0.04, rel=1e-9).

        The client-cleared weight is 4% (CRR Art. 306(1)(c)).

        Arrange:
            CCP-2 result; is_client_cleared=True on the trade.
        Act:
            Read ead_ccr_total and rwa_ccr_qccp_trade from bundle.
        Assert:
            rwa_ccr_qccp_trade == approx(ead_ccr_total * 0.04, rel=1e-9).

        FAILS TODAY: field does not exist on AggregatedResultBundle.

        References:
            CRR Art. 306(1)(c): client-cleared QCCP trade-leg 4% RW.
        """
        # Arrange
        ead_total = getattr(ccp2_result, "ead_ccr_total", _MISSING)
        rwa_qccp = getattr(ccp2_result, "rwa_ccr_qccp_trade", _MISSING)

        # Guard
        assert ead_total is not _MISSING, (
            "AggregatedResultBundle.ead_ccr_total does not exist (P8.52 not yet implemented)."
        )
        assert rwa_qccp is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_qccp_trade does not exist (P8.52 not yet implemented)."
        )

        if ead_total is None or rwa_qccp is None:
            pytest.skip("ead_ccr_total or rwa_ccr_qccp_trade is None — covered by other tests")

        expected = ead_total * P839_RW_CLIENT_CLEARED  # EAD * 0.04

        # Assert
        assert rwa_qccp == pytest.approx(expected, rel=1e-9), (
            f"P8.52 CCR-CCP-2: expected rwa_ccr_qccp_trade == ead_ccr_total * 0.04 "
            f"= {expected:,.6f}, got {rwa_qccp!r}. "
            f"ead_ccr_total={ead_total!r}, P839_RW_CLIENT_CLEARED={P839_RW_CLIENT_CLEARED}. "
            "CRR Art. 306(1)(c): client-cleared QCCP trade-leg risk weight is 4%."
        )

    def test_p852_ccp2_rwa_ccr_qccp_trade_equals_row_sum(
        self,
        ccp2_result,
        ccp2_results_df: pl.DataFrame,
    ) -> None:
        """
        rwa_ccr_qccp_trade == sum of rwa_final over QCCP ccr__ rows (self-deriving).

        Arrange:
            CCP-2 result; filter ccr__ rows where cp_is_qccp=True.
        Act:
            Compute expected; read rwa_ccr_qccp_trade from bundle.
        Assert:
            rwa_ccr_qccp_trade == pytest.approx(expected, rel=1e-9).
        """
        # Arrange
        df = ccp2_results_df
        ccr_rows = df.filter(pl.col("exposure_reference").str.starts_with("ccr__"))
        if "cp_entity_type" in ccr_rows.columns and "cp_is_qccp" in ccr_rows.columns:
            qccp_rows = ccr_rows.filter(
                (pl.col("cp_entity_type") == _CP_ENTITY_TYPE_CCP)
                & pl.col("cp_is_qccp").fill_null(True)
            )
        else:
            qccp_rows = ccr_rows
        expected_qccp_rwa = qccp_rows["rwa_final"].sum()

        # Act
        val = getattr(ccp2_result, "rwa_ccr_qccp_trade", _MISSING)

        # Assert
        assert val is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_qccp_trade does not exist (P8.52 not yet implemented)."
        )
        assert val == pytest.approx(expected_qccp_rwa, rel=1e-9), (
            f"P8.52 CCR-CCP-2: expected rwa_ccr_qccp_trade == {expected_qccp_rwa:,.6f} "
            f"(Σ rwa_final over QCCP ccr__ rows), got {val!r}. "
            "CRR Art. 306(1)(c): client-cleared QCCP 4% -> rwa_final = ead_final * 0.04."
        )


# ---------------------------------------------------------------------------
# Case 4: Failed trades (CCR-C1/C2/C3)
# ---------------------------------------------------------------------------


class TestP852FailedTradesRwaRollUp:
    """
    P8.52 / CCR-C: failed_trades_rwa populated for a failed-trade run.

    The three DvP trades (FT_C1/C2/C3) sum to PORTFOLIO_TOTAL_RWA = 13,850,000.

    References:
        - CRR Art. 378 + Table 1: DvP multiplier ladder.
        - CRR Art. 92(3)(ca): own_funds * 12.5 = RWA (own_funds_to_rwa_factor=12.5).
    """

    def test_p852_ft_failed_trades_rwa_not_none(
        self,
        ft_result,
    ) -> None:
        """
        failed_trades_rwa must be populated (not None) for a failed-trade run.

        Arrange:
            Failed-trade bundle: 3 DvP rows (FT_C1 t+6, FT_C2 t+35, FT_C3 t+46).
        Act:
            Read failed_trades_rwa from AggregatedResultBundle.
        Assert:
            failed_trades_rwa is not None.

        FAILS TODAY: field does not exist on AggregatedResultBundle.
        Sentinel guard produces AssertionError (not AttributeError).

        References:
            CRR Art. 378 + Table 1: DvP multiplier bands; CRR Art. 92(3)(ca).
        """
        # Arrange / Act
        val = getattr(ft_result, "failed_trades_rwa", _MISSING)

        # Assert
        assert val is not _MISSING, (
            "AggregatedResultBundle.failed_trades_rwa does not exist (P8.52 not yet implemented). "
            "Engine-implementer: add 'failed_trades_rwa: float | None = None' to the dataclass "
            "and populate it in aggregator.py as Σ rwa_final over rows where "
            "risk_type='SETTLEMENT_FAILED_TRADE'."
        )
        assert val is not None, (
            "P8.52 CCR-C: failed_trades_rwa must be populated (not None) for a run "
            "that contains SETTLEMENT_FAILED_TRADE rows (FT_C1/C2/C3). "
            "CRR Art. 378 Table 1: failed trades produce synthetic rows with "
            "risk_type='SETTLEMENT_FAILED_TRADE'."
        )

    def test_p852_ft_failed_trades_rwa_equals_row_sum(
        self,
        ft_result,
        ft_results_df: pl.DataFrame,
    ) -> None:
        """
        failed_trades_rwa == sum of rwa_final over SETTLEMENT_FAILED_TRADE rows (self-deriving).

        Arrange:
            Failed-trade result; filter ft__ rows by risk_type.
        Act:
            Compute expected Σ rwa_final; read failed_trades_rwa from bundle.
        Assert:
            failed_trades_rwa == pytest.approx(expected, rel=1e-9).

        References:
            CRR Art. 378 + Table 1; CRR Art. 92(3)(ca): RWA = own_funds * 12.5.
        """
        # Arrange
        df = ft_results_df
        ft_rows = df.filter(pl.col("risk_type") == "SETTLEMENT_FAILED_TRADE")
        expected_ft_rwa = ft_rows["rwa_final"].sum()

        # Act
        val = getattr(ft_result, "failed_trades_rwa", _MISSING)

        # Assert
        assert val is not _MISSING, (
            "AggregatedResultBundle.failed_trades_rwa does not exist (P8.52 not yet implemented)."
        )
        assert val == pytest.approx(expected_ft_rwa, rel=1e-9), (
            f"P8.52 CCR-C: expected failed_trades_rwa == {expected_ft_rwa:,.6f} "
            f"(Σ rwa_final over risk_type='SETTLEMENT_FAILED_TRADE' rows), got {val!r}. "
            f"Portfolio total (FT_C1+FT_C2+FT_C3): {FT_PORTFOLIO_TOTAL_RWA:,.0f}. "
            "CRR Art. 378 Table 1: bands dvp_5_15(8%), dvp_31_45(75%), dvp_46_plus(100%). "
            "CRR Art. 92(3)(ca): own_funds_requirement * 12.5 = rwa_final."
        )


# ---------------------------------------------------------------------------
# Case 5: Reconciliation invariant
# ---------------------------------------------------------------------------


class TestP852ReconciliationInvariant:
    """
    P8.52 reconciliation invariant: (rwa_ccr_default or 0) + (rwa_ccr_qccp_trade or 0)
    == Σ rwa_final over all ccr__ rows within a single run.

    This is the load-bearing additive decomposition pin.  We test:
      (a) CCR-E1 run: only rwa_ccr_default side (all non-QCCP).
      (b) CCR-CCP-1 run: only rwa_ccr_qccp_trade side (all QCCP).

    Together they exercise both sides of the partition without needing a mixed-portfolio run.

    References:
        - CRR Art. 107(2)(a): non-QCCP CCR -> SA rwa_ccr_default partition.
        - CRR Art. 306(1)(a): QCCP trade-leg -> rwa_ccr_qccp_trade partition.
        - Mathematical: rwa_ccr_default + rwa_ccr_qccp_trade == total CCR RWA.
    """

    def test_p852_e1_reconciliation_invariant(
        self,
        e1_result,
        e1_results_df: pl.DataFrame,
    ) -> None:
        """
        E1 run: rwa_ccr_default (all non-QCCP) == Σ rwa_final over ccr__ rows.

        Arrange:
            CCR-E1 result; materialised ccr__ rows.
        Act:
            ccr_total = ccr_rows["rwa_final"].sum().
            composed = (rwa_ccr_default or 0) + (rwa_ccr_qccp_trade or 0).
        Assert:
            composed == pytest.approx(ccr_total, rel=1e-9).

        The invariant is load-bearing: if the aggregator's filter logic
        double-counts or misses rows, this assertion fails even if individual
        roll-ups look correct.

        References:
            Mathematical partition identity for the ccr__ row set.
        """
        # Arrange
        df = e1_results_df
        ccr_rows = df.filter(pl.col("exposure_reference").str.starts_with("ccr__"))
        ccr_total = ccr_rows["rwa_final"].sum() or 0.0

        rwa_ccr_default = getattr(e1_result, "rwa_ccr_default", _MISSING)
        rwa_ccr_qccp = getattr(e1_result, "rwa_ccr_qccp_trade", _MISSING)

        assert rwa_ccr_default is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_default does not exist (P8.52 not yet implemented)."
        )
        assert rwa_ccr_qccp is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_qccp_trade does not exist (P8.52 not yet implemented)."
        )

        composed = (rwa_ccr_default or 0.0) + (rwa_ccr_qccp or 0.0)

        # Assert
        assert composed == pytest.approx(ccr_total, rel=1e-9), (
            f"P8.52 reconciliation invariant (E1): "
            f"(rwa_ccr_default or 0) + (rwa_ccr_qccp_trade or 0) must equal "
            f"Σ rwa_final over ccr__ rows. "
            f"Expected {ccr_total:,.6f}, got composed={composed:,.6f} "
            f"(rwa_ccr_default={rwa_ccr_default!r}, rwa_ccr_qccp_trade={rwa_ccr_qccp!r}). "
            "The partition QCCP vs non-QCCP must cover the full ccr__ set with no overlap."
        )

    def test_p852_ccp1_reconciliation_invariant(
        self,
        ccp1_result,
        ccp1_results_df: pl.DataFrame,
    ) -> None:
        """
        CCP-1 run: rwa_ccr_qccp_trade (all QCCP) == Σ rwa_final over ccr__ rows.

        Arrange:
            CCR-CCP-1 result; materialised ccr__ rows (all QCCP).
        Act:
            ccr_total = ccr_rows["rwa_final"].sum().
            composed = (rwa_ccr_default or 0) + (rwa_ccr_qccp_trade or 0).
        Assert:
            composed == pytest.approx(ccr_total, rel=1e-9).

        References:
            CRR Art. 306(1)(a): all ccr__ rows in this run are QCCP proprietary.
        """
        # Arrange
        df = ccp1_results_df
        ccr_rows = df.filter(pl.col("exposure_reference").str.starts_with("ccr__"))
        ccr_total = ccr_rows["rwa_final"].sum() or 0.0

        rwa_ccr_default = getattr(ccp1_result, "rwa_ccr_default", _MISSING)
        rwa_ccr_qccp = getattr(ccp1_result, "rwa_ccr_qccp_trade", _MISSING)

        assert rwa_ccr_default is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_default does not exist (P8.52 not yet implemented)."
        )
        assert rwa_ccr_qccp is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_qccp_trade does not exist (P8.52 not yet implemented)."
        )

        composed = (rwa_ccr_default or 0.0) + (rwa_ccr_qccp or 0.0)

        # Assert
        assert composed == pytest.approx(ccr_total, rel=1e-9), (
            f"P8.52 reconciliation invariant (CCP-1): "
            f"(rwa_ccr_default or 0) + (rwa_ccr_qccp_trade or 0) must equal "
            f"Σ rwa_final over ccr__ rows. "
            f"Expected {ccr_total:,.6f}, got composed={composed:,.6f} "
            f"(rwa_ccr_default={rwa_ccr_default!r}, rwa_ccr_qccp_trade={rwa_ccr_qccp!r}). "
            "The partition QCCP vs non-QCCP must cover the full ccr__ set with no overlap."
        )


# ---------------------------------------------------------------------------
# Case 6: Empty-portfolio regression
# ---------------------------------------------------------------------------


class TestP852EmptyPortfolioRegression:
    """
    P8.52 / empty-portfolio regression: all four new fields are None when ccr=None.

    The non-CCR reporting portfolio (build_reporting_bundle, ccr=None) must not
    raise when the aggregator tries to read ccr__-prefixed rows — there are none.
    The column-presence guard must catch this and return None for all four fields.

    References:
        - P8.52 §3: "Column-presence-guard each (if {'exposure_reference','rwa_final'}
          <= set(combined_df.columns): ...)".
    """

    def test_p852_empty_portfolio_all_four_fields_none(
        self,
        empty_portfolio_result,
    ) -> None:
        """
        All four new P8.52 fields are None for a non-CCR SA portfolio.

        Arrange:
            build_reporting_bundle(): SA/IRB/SL loans, ccr=None.
            Config: CRR, 2025-12-31, STANDARDISED.
        Act:
            Full CRR pipeline; read four new fields via getattr (sentinel guard).
        Assert:
            ead_ccr_total is None.
            rwa_ccr_default is None.
            rwa_ccr_qccp_trade is None.
            failed_trades_rwa is None.

        This test is expected to PASS once the fields exist on the bundle and
        the aggregator's column-presence guard returns None for empty ccr__ sets.
        It FAILS TODAY because the fields don't exist yet (sentinel guard catches it).

        References:
            P8.52 §3: None (not 0.0) default for CCR-free portfolio, consistent with
            rwa_ccr_default_fund semantics.
        """
        # Arrange
        result = empty_portfolio_result

        # Act — read all four new fields with sentinel guard
        ead_ccr_total = getattr(result, "ead_ccr_total", _MISSING)
        rwa_ccr_default = getattr(result, "rwa_ccr_default", _MISSING)
        rwa_ccr_qccp_trade = getattr(result, "rwa_ccr_qccp_trade", _MISSING)
        failed_trades_rwa = getattr(result, "failed_trades_rwa", _MISSING)

        # Assert each field exists on the bundle
        assert ead_ccr_total is not _MISSING, (
            "AggregatedResultBundle.ead_ccr_total does not exist (P8.52 not yet implemented). "
            "Engine-implementer: add 'ead_ccr_total: float | None = None' to the dataclass."
        )
        assert rwa_ccr_default is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_default does not exist (P8.52 not yet implemented). "
            "Engine-implementer: add 'rwa_ccr_default: float | None = None' to the dataclass."
        )
        assert rwa_ccr_qccp_trade is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_qccp_trade does not exist (P8.52 not yet implemented). "
            "Engine-implementer: add 'rwa_ccr_qccp_trade: float | None = None' to the dataclass."
        )
        assert failed_trades_rwa is not _MISSING, (
            "AggregatedResultBundle.failed_trades_rwa does not exist (P8.52 not yet implemented). "
            "Engine-implementer: add 'failed_trades_rwa: float | None = None' to the dataclass."
        )

        # Assert all fields are None for a non-CCR portfolio
        assert ead_ccr_total is None, (
            f"P8.52 empty-portfolio: expected ead_ccr_total=None (no ccr__ rows "
            f"in a non-CCR SA portfolio), got {ead_ccr_total!r}. "
            "The column-presence guard must return None when no ccr__-prefixed rows exist."
        )
        assert rwa_ccr_default is None, (
            f"P8.52 empty-portfolio: expected rwa_ccr_default=None (no ccr__ rows), "
            f"got {rwa_ccr_default!r}."
        )
        assert rwa_ccr_qccp_trade is None, (
            f"P8.52 empty-portfolio: expected rwa_ccr_qccp_trade=None (no ccr__ rows), "
            f"got {rwa_ccr_qccp_trade!r}."
        )
        assert failed_trades_rwa is None, (
            f"P8.52 empty-portfolio: expected failed_trades_rwa=None (no SETTLEMENT_FAILED_TRADE "
            f"rows in a non-CCR SA portfolio), got {failed_trades_rwa!r}."
        )
