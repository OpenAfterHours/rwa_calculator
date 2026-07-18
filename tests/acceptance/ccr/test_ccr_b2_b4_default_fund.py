"""
CCR-B2 / CCR-B3 / CCR-B4: default-fund-contribution capital stack (CRR Art. 308 / 309).

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator -> OutputAggregator

Key responsibilities:
- Validate that default-fund-contribution (DFC) RWEA is wired into the full
  pipeline output, producing one synthetic SA exposure row per contribution
  via the Art. 308/309 K_CM × 12.5 formula.
- Validate per-row RWA against three Art. 308/309 branches (QCCP pre-funded,
  non-QCCP pre-funded, non-QCCP unfunded) using the P8.49 fixture constants.
- Validate portfolio-total RWA delta (with vs without default_fund_contributions)
  == 26,875,000.
- Validate the bundle-level roll-up field ``rwa_ccr_default_fund``.

Scenario (three independent DFC rows):
    CCR-B2: DFC_B2, QCCP pre-funded  (Art. 308), K_CM=1,000,000  -> RWEA  12,500,000
    CCR-B3: DFC_B3, non-QCCP prefund (Art. 309), K_CM=750,000    -> RWEA   9,375,000
    CCR-B4: DFC_B4, non-QCCP unfunded(Art. 309), K_CM=400,000    -> RWEA   5,000,000
    Portfolio total RWEA = 26,875,000.

Expected synthetic row provenance contract (agreed with engine-implementer):
    exposure_reference = 'dfc__' + contribution_id   (e.g. 'dfc__DFC_B2')
    risk_type          = 'CCR_DEFAULT_FUND'
    ccr_method         = 'default_fund'
    drawn_amount       = k_cm (EAD = own-funds; RW pin makes RWEA = K_CM × 12.5)
    risk_weight        = 12.5
    rwa_final          = dfc_rwea (per-row)
    regulatory_band    = regulatory band string (per-scenario)

EXPECTED FAILURE MODE (pre-implementation):
    The field ``default_fund_contributions`` does NOT yet exist on ``RawCCRBundle``
    (it is a P8.49 deliverable; the engine-implementer adds it in Wave 4 by editing
    ``src/rwa_calc/contracts/bundles.py``).

    Constructing ``RawCCRBundle(..., default_fund_contributions=make_b2_frame())``
    with the not-yet-existing keyword argument will raise:

        TypeError: RawCCRBundle.__init__() got an unexpected keyword argument
        'default_fund_contributions'

    This is the new-dataclass-field analogue of the P8.43 clean AssertionError — a
    deterministic, fully-expected fail-first signal that the bundle field is the first
    thing the engine-implementer must add.  It is NOT an import error or fixture bug.

    Once the field lands (and the engine is wired), the bundle constructs cleanly and
    the PRIMARY assertion (delta == 26,875,000) fires if the DFC sub-stage is not yet
    wired into ``engine/stages/ccr.py``.

References:
    - CRR Art. 308(2) (K_CCP + K_CM clearing-member allocation)
    - CRR Art. 308(3) (QCCP pre-funded own-funds: RWEA = K_CM × 12.5)
    - CRR Art. 309(1)/(2) (non-QCCP / unfunded treatment; same arithmetic)
    - CRR Art. 92(3)(ca) (own_funds_to_rwa_factor = 12.5; pack value reused)
    - BCBS CRE54.18-54.32
    - tests/fixtures/ccr/p849_default_fund_builder.py: fixture builder + expected constants
    - src/rwa_calc/engine/ccr/default_fund.py: compute_dfc_capital (engine Wave 4 target)
    - src/rwa_calc/engine/stages/ccr.py: CCR pipeline stage (wiring target)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
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
from tests.fixtures.ccr.p849_default_fund_builder import (
    DFC_B2_EAD,
    DFC_B2_ID,
    DFC_B2_REGULATORY_BAND,
    DFC_B2_RWEA,
    DFC_B3_EAD,
    DFC_B3_ID,
    DFC_B3_REGULATORY_BAND,
    DFC_B3_RWEA,
    DFC_B4_EAD,
    DFC_B4_ID,
    DFC_B4_REGULATORY_BAND,
    DFC_B4_RWEA,
    OWN_FUNDS_TO_RWA_FACTOR,
    PORTFOLIO_TOTAL_RWEA,
    make_b2_frame,
    make_combined_b2_b3_b4_frame,
    make_minimal_counterparties_frame,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2027, 1, 15)

# Provenance contract — synthetic SA exposure row columns the engine must emit.
_SYNTHETIC_RISK_TYPE: str = "CCR_DEFAULT_FUND"
_SYNTHETIC_CCR_METHOD: str = "default_fund"
_SYNTHETIC_RW: float = OWN_FUNDS_TO_RWA_FACTOR  # 12.5

# Synthetic exposure_reference prefix (engine: "dfc__" + contribution_id).
_DFC_B2_EXPOSURE_REF: str = f"dfc__{DFC_B2_ID}"
_DFC_B3_EXPOSURE_REF: str = f"dfc__{DFC_B3_ID}"
_DFC_B4_EXPOSURE_REF: str = f"dfc__{DFC_B4_ID}"

# B2-only bundle-level RWEA (single-contribution run).
_B2_ONLY_BUNDLE_RWEA: float = DFC_B2_RWEA  # 12,500,000


# ---------------------------------------------------------------------------
# Bundle helpers
# ---------------------------------------------------------------------------


def _build_empty_trades() -> pl.LazyFrame:
    """Return a zero-row trades LazyFrame (P8.49 has no SA-CCR derivative trades)."""
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


def _build_base_ccr_bundle_kwargs() -> dict:
    """
    Return the four mandatory leaf-bundle kwargs shared by all CCR bundle variants.

    The caller adds ``default_fund_contributions=...`` (or omits it for the
    baseline run).  Not inlined so the two helpers below share identical leaf
    frames without risk of drift.
    """
    return {
        "trades": TradeBundle(trades=_build_empty_trades()),
        "netting_sets": NettingSetBundle(netting_sets=_build_empty_netting_sets()),
        "margin_agreements": MarginAgreementBundle(
            margin_agreements=_build_empty_margin_agreements()
        ),
        "ccr_collateral": CCRCollateralBundle(ccr_collateral=_build_empty_ccr_collateral()),
        "failed_trades": None,
    }


def _build_ccr_bundle_combined() -> RawCCRBundle:
    """
    Assemble a RawCCRBundle with the B2+B3+B4 combined DFC frame.

    PRE-IMPLEMENTATION NOTE:
        This call will raise ``TypeError: RawCCRBundle.__init__() got an unexpected
        keyword argument 'default_fund_contributions'`` until the engine-implementer
        adds the field to ``contracts/bundles.py``.  That TypeError IS the expected
        pre-implementation failure signal for this test module.

    References:
        CRR Art. 308(2)/(3), 309(1)/(2) — three DFC branches, all three scenarios.
    """
    return RawCCRBundle(
        **_build_base_ccr_bundle_kwargs(),
        default_fund_contributions=make_combined_b2_b3_b4_frame(),
    )


def _build_ccr_bundle_b2_only() -> RawCCRBundle:
    """
    Assemble a RawCCRBundle with only the CCR-B2 (QCCP) DFC row.

    Used for the secondary bundle-level roll-up assertion (B2 only -> 12,500,000).

    PRE-IMPLEMENTATION NOTE:
        Same pre-implementation TypeError as _build_ccr_bundle_combined().

    References:
        CRR Art. 308(2)/(3) — QCCP pre-funded branch only.
    """
    return RawCCRBundle(
        **_build_base_ccr_bundle_kwargs(),
        default_fund_contributions=make_b2_frame(),
    )


def _build_ccr_bundle_no_dfc() -> RawCCRBundle:
    """
    Assemble a RawCCRBundle with default_fund_contributions=None (baseline run).

    Structurally identical to _build_ccr_bundle_combined() but with
    default_fund_contributions=None so the DFC sub-stage is skipped.
    Used for the primary delta assertion.

    PRE-IMPLEMENTATION NOTE:
        This call also raises TypeError pre-implementation (``default_fund_contributions``
        does not yet exist).  Once the field lands, passing ``None`` skips the sub-stage
        and produces zero DFC RWA — the baseline for the delta assertion.
    """
    return RawCCRBundle(
        **_build_base_ccr_bundle_kwargs(),
        default_fund_contributions=None,
    )


def _build_config() -> CalculationConfig:
    """
    Basel 3.1 config for CCR-B2/B3/B4 (regime-invariant Art. 308/309 numerics).

    Default-fund-contribution RWA is regime-invariant (CRR Art. 308/309 carried
    into PS1/26 unchanged), so Basel 3.1 config is used per scenario specification
    and consistent with the P8.43 precedent.
    """
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_b234_combined_results() -> pl.DataFrame:
    """
    Run the combined B2+B3+B4 bundle (default_fund_contributions populated)
    through the Basel 3.1 pipeline and return the collected results DataFrame.

    Arrange:
        - 3 DFC rows: DFC_B2 (QCCP), DFC_B3 (non-QCCP pre-funded), DFC_B4 (unfunded)
        - CCP counterparties CP_CCP_B2/B3/B4 (entity_type='ccp')
        - No SA-CCR derivative trades / netting sets
        - Basel 3.1 config, STANDARDISED permission mode
    Act:
        Full Basel 3.1 pipeline via PipelineOrchestrator.
    Returns:
        Collected results DataFrame from AggregatedResultBundle.results.
    """
    # Arrange
    bundle = make_raw_bundle(
        counterparties=make_minimal_counterparties_frame(scenario="all"),
        ccr=_build_ccr_bundle_combined(),
    )
    config = _build_config()

    # Act
    result = PipelineOrchestrator().run_with_data(bundle, config)
    return result.results.collect()


@pytest.fixture(scope="module")
def ccr_b234_no_dfc_results() -> pl.DataFrame:
    """
    Run the baseline bundle (default_fund_contributions=None) through the
    Basel 3.1 pipeline and return the collected results DataFrame.

    Identical input to ccr_b234_combined_results() except
    default_fund_contributions=None — the pipeline skips the DFC sub-stage.
    Used for the primary delta assertion.
    """
    # Arrange
    bundle = make_raw_bundle(
        counterparties=make_minimal_counterparties_frame(scenario="all"),
        ccr=_build_ccr_bundle_no_dfc(),
    )
    config = _build_config()

    # Act
    result = PipelineOrchestrator().run_with_data(bundle, config)
    return result.results.collect()


@pytest.fixture(scope="module")
def ccr_b2_only_result():
    """
    Run a B2-only bundle (single QCCP DFC contribution) through the pipeline.

    Returns the full ``AggregatedResultBundle`` (not just the DataFrame) so the
    secondary bundle-level ``rwa_ccr_default_fund`` field can be asserted.
    """
    # Arrange
    bundle = make_raw_bundle(
        counterparties=make_minimal_counterparties_frame(scenario="b2"),
        ccr=_build_ccr_bundle_b2_only(),
    )
    config = _build_config()

    # Act
    return PipelineOrchestrator().run_with_data(bundle, config)


# ---------------------------------------------------------------------------
# CCR-B2/B3/B4 acceptance tests
# ---------------------------------------------------------------------------


class TestCCRB2B4DefaultFund:
    """
    CCR-B2/B3/B4: default-fund-contribution capital stack, three Art. 308/309 branches.

    Tests verify:
      1. PRIMARY (robust): firm-total RWA delta (with vs without DFC frame)
         == 26,875,000.  PRE-IMPLEMENTATION: TypeError at bundle construction
         (``default_fund_contributions`` field missing from RawCCRBundle).
      2. B2 per-row RWEA == 12,500,000 (QCCP, Art. 308).
      3. B3 per-row RWEA == 9,375,000 (non-QCCP pre-funded, Art. 309).
      4. B4 per-row RWEA == 5,000,000 (non-QCCP unfunded, Art. 309).
      5. Synthetic risk_weight == 12.5 for each of B2/B3/B4.
      6. Provenance contract: exposure_reference, ccr_method, drawn_amount,
         regulatory_band for each of B2/B3/B4.
      7. Bundle-level rwa_ccr_default_fund:
         B2-only run -> 12,500,000; combined run -> 26,875,000.
    """

    def test_ccr_b2_b4_portfolio_rwa_delta(
        self,
        ccr_b234_combined_results: pl.DataFrame,
        ccr_b234_no_dfc_results: pl.DataFrame,
    ) -> None:
        """
        PRIMARY: firm-total RWA with DFC frame MINUS firm-total RWA without == 26,875,000.

        Arrange: two pipeline runs — one with combined B2+B3+B4 default_fund_contributions,
                 one with default_fund_contributions=None; otherwise identical.
        Act:     sum rwa_final across all rows in each run's results.
        Assert:  delta == 26,875,000 exactly (abs tol 1.0).

        PRE-IMPLEMENTATION: TypeError at bundle construction because
        ``default_fund_contributions`` is not yet a field on ``RawCCRBundle``.
        Once the field lands but the DFC sub-stage is unwired, delta == 0, not
        26,875,000 — the secondary AssertionError becomes the TDD red signal.

        References:
            CRR Art. 308(3): QCCP  K_CM × 12.5 = 1,000,000 × 12.5 = 12,500,000
            CRR Art. 309(2): non-QCCP K_CM × 12.5 = 750,000 × 12.5 = 9,375,000
            CRR Art. 309(2): unfunded K_CM × 12.5 = 400,000 × 12.5 = 5,000,000
            CRR Art. 92(3)(ca): own_funds_to_rwa_factor = 12.5
        """
        # Arrange
        df_with = ccr_b234_combined_results
        df_without = ccr_b234_no_dfc_results

        total_with = float(df_with["rwa_final"].sum() or 0.0)
        total_without = float(df_without["rwa_final"].sum() or 0.0)
        delta = total_with - total_without

        # Assert
        assert delta == pytest.approx(PORTFOLIO_TOTAL_RWEA, abs=1.0), (
            f"CCR-B2/B3/B4: expected firm-total RWA delta (with - without DFC frame) "
            f"== {PORTFOLIO_TOTAL_RWEA:,.0f}, "
            f"got {delta:,.0f} "
            f"(with={total_with:,.0f}, without={total_without:,.0f}). "
            "The DFC sub-stage (compute_dfc_capital) must be wired into "
            "engine/stages/ccr.py and its synthetic rows appended to the aggregated results. "
            "CRR Art. 308(3)/309(2): 12,500,000 + 9,375,000 + 5,000,000 = 26,875,000."
        )

    def test_ccr_b2_rwa(
        self,
        ccr_b234_combined_results: pl.DataFrame,
    ) -> None:
        """
        CCR-B2 (QCCP pre-funded, Art. 308): rwa_final == 12,500,000.

        Arrange: DFC_B2, K_CCP=50m, DF_i=2m, DF_CM=100m.
                 K_CM = 50,000,000 × (2,000,000 / 100,000,000) = 1,000,000
                 RWEA = 1,000,000 × 12.5 = 12,500,000
        Act:     full Basel 3.1 pipeline; filter synthetic row for DFC_B2.
        Assert:  rwa_final == 12,500,000 (abs tol 1.0).

        References:
            CRR Art. 308(2): K_CM = K_CCP × (DF_i / DF_CM)
            CRR Art. 308(3): RWEA = K_CM × 12.5 (QCCP pre-funded)
        """
        # Arrange
        df = ccr_b234_combined_results
        dfc_rows = df.filter(pl.col("exposure_reference") == _DFC_B2_EXPOSURE_REF)

        assert len(dfc_rows) == 1, (
            f"CCR-B2: expected exactly 1 synthetic row with "
            f"exposure_reference={_DFC_B2_EXPOSURE_REF!r}, "
            f"got {len(dfc_rows)}. "
            "engine/stages/ccr.py must emit one synthetic exposure row per DFC contribution "
            "with exposure_reference='dfc__' + contribution_id."
        )

        row = dfc_rows.to_dicts()[0]

        # Assert
        assert row["rwa_final"] == pytest.approx(DFC_B2_RWEA, abs=1.0), (
            f"CCR-B2: expected rwa_final=={DFC_B2_RWEA:,.0f} "
            f"(K_CM=1,000,000 × 12.5), got {row['rwa_final']:,.0f}. "
            "CRR Art. 308(3): QCCP pre-funded RWEA = K_CM × 12.5."
        )

    def test_ccr_b3_rwa(
        self,
        ccr_b234_combined_results: pl.DataFrame,
    ) -> None:
        """
        CCR-B3 (non-QCCP pre-funded, Art. 309): rwa_final == 9,375,000.

        Arrange: DFC_B3, K_CCP=30m, DF_i=1.5m, DF_CM=60m.
                 K_CM = 30,000,000 × (1,500,000 / 60,000,000) = 750,000
                 RWEA = 750,000 × 12.5 = 9,375,000
        Act:     full Basel 3.1 pipeline; filter synthetic row for DFC_B3.
        Assert:  rwa_final == 9,375,000 (abs tol 1.0).

        References:
            CRR Art. 308(2): K_CM = K_CCP × (DF_i / DF_CM)
            CRR Art. 309(2): RWEA = K_CM × 12.5 (non-QCCP pre-funded)
        """
        # Arrange
        df = ccr_b234_combined_results
        dfc_rows = df.filter(pl.col("exposure_reference") == _DFC_B3_EXPOSURE_REF)

        assert len(dfc_rows) == 1, (
            f"CCR-B3: expected exactly 1 synthetic row with "
            f"exposure_reference={_DFC_B3_EXPOSURE_REF!r}, "
            f"got {len(dfc_rows)}. "
            "engine/stages/ccr.py must emit one synthetic exposure row per DFC contribution."
        )

        row = dfc_rows.to_dicts()[0]

        # Assert
        assert row["rwa_final"] == pytest.approx(DFC_B3_RWEA, abs=1.0), (
            f"CCR-B3: expected rwa_final=={DFC_B3_RWEA:,.0f} "
            f"(K_CM=750,000 × 12.5), got {row['rwa_final']:,.0f}. "
            "CRR Art. 309(2): non-QCCP pre-funded RWEA = K_CM × 12.5."
        )

    def test_ccr_b4_rwa(
        self,
        ccr_b234_combined_results: pl.DataFrame,
    ) -> None:
        """
        CCR-B4 (non-QCCP unfunded, Art. 309 unfunded): rwa_final == 5,000,000.

        Arrange: DFC_B4, K_CCP=20m, DF_i=0.8m, DF_CM=40m.
                 K_CM = 20,000,000 × (800,000 / 40,000,000) = 400,000
                 RWEA = 400,000 × 12.5 = 5,000,000
        Act:     full Basel 3.1 pipeline; filter synthetic row for DFC_B4.
        Assert:  rwa_final == 5,000,000 (abs tol 1.0).

        References:
            CRR Art. 308(2): K_CM = K_CCP × (DF_i / DF_CM)
            CRR Art. 309(2): RWEA = K_CM × 12.5 (non-QCCP unfunded)
        """
        # Arrange
        df = ccr_b234_combined_results
        dfc_rows = df.filter(pl.col("exposure_reference") == _DFC_B4_EXPOSURE_REF)

        assert len(dfc_rows) == 1, (
            f"CCR-B4: expected exactly 1 synthetic row with "
            f"exposure_reference={_DFC_B4_EXPOSURE_REF!r}, "
            f"got {len(dfc_rows)}. "
            "engine/stages/ccr.py must emit one synthetic exposure row per DFC contribution."
        )

        row = dfc_rows.to_dicts()[0]

        # Assert
        assert row["rwa_final"] == pytest.approx(DFC_B4_RWEA, abs=1.0), (
            f"CCR-B4: expected rwa_final=={DFC_B4_RWEA:,.0f} "
            f"(K_CM=400,000 × 12.5), got {row['rwa_final']:,.0f}. "
            "CRR Art. 309(2): non-QCCP unfunded RWEA = K_CM × 12.5."
        )

    def test_ccr_b2_provenance_contract(
        self,
        ccr_b234_combined_results: pl.DataFrame,
    ) -> None:
        """
        CCR-B2 synthetic row provenance: exposure_reference, risk_type, ccr_method,
        risk_weight, drawn_amount (EAD = K_CM), regulatory_band.

        Arrange: DFC_B2 combined-run results; filter to exposure_reference='dfc__DFC_B2'.
        Act:     full Basel 3.1 pipeline.
        Assert:  row carries the full provenance contract expected by engine-implementer.

        References:
            Scenario proposal §3 (synthetic row columns).
            P8.43 precedent: 'ft__' + failed_trade_id pattern.
        """
        # Arrange
        df = ccr_b234_combined_results
        dfc_rows = df.filter(pl.col("exposure_reference") == _DFC_B2_EXPOSURE_REF)

        assert len(dfc_rows) == 1, (
            f"CCR-B2 provenance: expected 1 row with "
            f"exposure_reference={_DFC_B2_EXPOSURE_REF!r}, got {len(dfc_rows)}."
        )

        row = dfc_rows.to_dicts()[0]

        # Assert — provenance contract columns
        assert row["risk_type"] == _SYNTHETIC_RISK_TYPE, (
            f"CCR-B2: expected risk_type=={_SYNTHETIC_RISK_TYPE!r}, got {row.get('risk_type')!r}."
        )
        assert row["ccr_method"] == _SYNTHETIC_CCR_METHOD, (
            f"CCR-B2: expected ccr_method=={_SYNTHETIC_CCR_METHOD!r}, "
            f"got {row.get('ccr_method')!r}."
        )
        assert row["risk_weight"] == pytest.approx(_SYNTHETIC_RW, abs=1e-6), (
            f"CCR-B2: expected risk_weight=={_SYNTHETIC_RW} (12.5 = 1/0.08 per Art. 92(3)(ca)), "
            f"got {row.get('risk_weight')}."
        )
        assert row["drawn_amount"] == pytest.approx(DFC_B2_EAD, abs=1.0), (
            f"CCR-B2: expected drawn_amount=={DFC_B2_EAD:,.0f} (= K_CM per Art. 308(2)), "
            f"got {row.get('drawn_amount')}. "
            "Engine sets drawn_amount = k_cm on the synthetic row."
        )
        assert row["regulatory_band"] == DFC_B2_REGULATORY_BAND, (
            f"CCR-B2: expected regulatory_band=={DFC_B2_REGULATORY_BAND!r}, "
            f"got {row.get('regulatory_band')!r}."
        )

    def test_ccr_b3_provenance_contract(
        self,
        ccr_b234_combined_results: pl.DataFrame,
    ) -> None:
        """
        CCR-B3 synthetic row provenance: exposure_reference, risk_type, ccr_method,
        risk_weight, drawn_amount (EAD = K_CM), regulatory_band.

        Arrange: DFC_B3 combined-run results; filter to exposure_reference='dfc__DFC_B3'.
        Act:     full Basel 3.1 pipeline.
        Assert:  row carries the full provenance contract.

        References:
            Scenario proposal §3 (synthetic row columns).
        """
        # Arrange
        df = ccr_b234_combined_results
        dfc_rows = df.filter(pl.col("exposure_reference") == _DFC_B3_EXPOSURE_REF)

        assert len(dfc_rows) == 1, (
            f"CCR-B3 provenance: expected 1 row with "
            f"exposure_reference={_DFC_B3_EXPOSURE_REF!r}, got {len(dfc_rows)}."
        )

        row = dfc_rows.to_dicts()[0]

        # Assert
        assert row["risk_type"] == _SYNTHETIC_RISK_TYPE, (
            f"CCR-B3: expected risk_type=={_SYNTHETIC_RISK_TYPE!r}, got {row.get('risk_type')!r}."
        )
        assert row["ccr_method"] == _SYNTHETIC_CCR_METHOD, (
            f"CCR-B3: expected ccr_method=={_SYNTHETIC_CCR_METHOD!r}, "
            f"got {row.get('ccr_method')!r}."
        )
        assert row["risk_weight"] == pytest.approx(_SYNTHETIC_RW, abs=1e-6), (
            f"CCR-B3: expected risk_weight=={_SYNTHETIC_RW}, got {row.get('risk_weight')}."
        )
        assert row["drawn_amount"] == pytest.approx(DFC_B3_EAD, abs=1.0), (
            f"CCR-B3: expected drawn_amount=={DFC_B3_EAD:,.0f} (= K_CM), "
            f"got {row.get('drawn_amount')}."
        )
        assert row["regulatory_band"] == DFC_B3_REGULATORY_BAND, (
            f"CCR-B3: expected regulatory_band=={DFC_B3_REGULATORY_BAND!r}, "
            f"got {row.get('regulatory_band')!r}."
        )

    def test_ccr_b4_provenance_contract(
        self,
        ccr_b234_combined_results: pl.DataFrame,
    ) -> None:
        """
        CCR-B4 synthetic row provenance: exposure_reference, risk_type, ccr_method,
        risk_weight, drawn_amount (EAD = K_CM), regulatory_band.

        Arrange: DFC_B4 combined-run results; filter to exposure_reference='dfc__DFC_B4'.
        Act:     full Basel 3.1 pipeline.
        Assert:  row carries the full provenance contract (unfunded branch).

        References:
            Scenario proposal §3 (synthetic row columns).
        """
        # Arrange
        df = ccr_b234_combined_results
        dfc_rows = df.filter(pl.col("exposure_reference") == _DFC_B4_EXPOSURE_REF)

        assert len(dfc_rows) == 1, (
            f"CCR-B4 provenance: expected 1 row with "
            f"exposure_reference={_DFC_B4_EXPOSURE_REF!r}, got {len(dfc_rows)}."
        )

        row = dfc_rows.to_dicts()[0]

        # Assert
        assert row["risk_type"] == _SYNTHETIC_RISK_TYPE, (
            f"CCR-B4: expected risk_type=={_SYNTHETIC_RISK_TYPE!r}, got {row.get('risk_type')!r}."
        )
        assert row["ccr_method"] == _SYNTHETIC_CCR_METHOD, (
            f"CCR-B4: expected ccr_method=={_SYNTHETIC_CCR_METHOD!r}, "
            f"got {row.get('ccr_method')!r}."
        )
        assert row["risk_weight"] == pytest.approx(_SYNTHETIC_RW, abs=1e-6), (
            f"CCR-B4: expected risk_weight=={_SYNTHETIC_RW}, got {row.get('risk_weight')}."
        )
        assert row["drawn_amount"] == pytest.approx(DFC_B4_EAD, abs=1.0), (
            f"CCR-B4: expected drawn_amount=={DFC_B4_EAD:,.0f} (= K_CM), "
            f"got {row.get('drawn_amount')}."
        )
        assert row["regulatory_band"] == DFC_B4_REGULATORY_BAND, (
            f"CCR-B4: expected regulatory_band=={DFC_B4_REGULATORY_BAND!r} (unfunded), "
            f"got {row.get('regulatory_band')!r}."
        )

    def test_ccr_b2_only_bundle_level_rwa_ccr_default_fund(
        self,
        ccr_b2_only_result,
    ) -> None:
        """
        Bundle-level roll-up: B2-only run -> rwa_ccr_default_fund == 12,500,000.

        Arrange: B2-only bundle (single QCCP DFC contribution), full pipeline.
        Act:     full Basel 3.1 pipeline via PipelineOrchestrator.
        Assert:  AggregatedResultBundle.rwa_ccr_default_fund == 12,500,000 (abs tol 1.0).
                 Uses getattr(result, 'rwa_ccr_default_fund', None) so the test fails
                 with AssertionError (not AttributeError) pre-implementation.

        References:
            Scenario proposal §2, D2: rwa_ccr_default_fund = sum of DFC RWEA rows.
        """
        # Arrange
        result = ccr_b2_only_result
        bundle_field_value = getattr(result, "rwa_ccr_default_fund", None)

        # Assert
        assert bundle_field_value is not None, (
            "AggregatedResultBundle.rwa_ccr_default_fund is None (field absent or not set). "
            "The engine-implementer must add rwa_ccr_default_fund to AggregatedResultBundle "
            "and populate it in aggregator.py by summing rwa_final for risk_type == "
            "'CCR_DEFAULT_FUND' rows. (P8.49 D2)"
        )
        assert float(bundle_field_value) == pytest.approx(_B2_ONLY_BUNDLE_RWEA, abs=1.0), (
            f"B2-only run: expected rwa_ccr_default_fund=={_B2_ONLY_BUNDLE_RWEA:,.0f} "
            f"(= DFC_B2_RWEA = K_CM × 12.5 = 1,000,000 × 12.5), "
            f"got {bundle_field_value:,.0f}. "
            "CRR Art. 308(3): QCCP pre-funded RWEA = K_CM × 12.5."
        )

    def test_ccr_b234_combined_bundle_level_rwa_ccr_default_fund(
        self,
        ccr_b234_combined_results: pl.DataFrame,
        ccr_b2_only_result,
    ) -> None:
        """
        Bundle-level roll-up: combined B2+B3+B4 run -> rwa_ccr_default_fund == 26,875,000.

        NOTE: This test re-runs a combined bundle through PipelineOrchestrator to access
        the full AggregatedResultBundle.  The ccr_b234_combined_results fixture exposes
        only result.results.collect() — here we need the bundle itself.

        Arrange: Combined B2+B3+B4 bundle, full pipeline.
        Act:     full Basel 3.1 pipeline via PipelineOrchestrator (inline run).
        Assert:  AggregatedResultBundle.rwa_ccr_default_fund == 26,875,000 (abs tol 1.0).

        References:
            Scenario proposal §5: combined rwa_ccr_default_fund = 26,875,000.
        """
        # Arrange
        bundle = make_raw_bundle(
            counterparties=make_minimal_counterparties_frame(scenario="all"),
            ccr=_build_ccr_bundle_combined(),
        )
        config = _build_config()

        # Act
        result = PipelineOrchestrator().run_with_data(bundle, config)
        bundle_field_value = getattr(result, "rwa_ccr_default_fund", None)

        # Assert
        assert bundle_field_value is not None, (
            "AggregatedResultBundle.rwa_ccr_default_fund is None (field absent or not set). "
            "The engine-implementer must populate it in aggregator.py. (P8.49 D2)"
        )
        assert float(bundle_field_value) == pytest.approx(PORTFOLIO_TOTAL_RWEA, abs=1.0), (
            f"Combined B2+B3+B4 run: expected rwa_ccr_default_fund=={PORTFOLIO_TOTAL_RWEA:,.0f} "
            f"(= 12,500,000 + 9,375,000 + 5,000,000), "
            f"got {bundle_field_value:,.0f}. "
            "CRR Art. 308(3)/309(2): sum of K_CM × 12.5 across all DFC rows."
        )
