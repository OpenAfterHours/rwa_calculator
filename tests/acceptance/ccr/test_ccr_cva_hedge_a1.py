"""
P8.62 / CVA-HEDGE-A1: BA-CVA full-K with eligible single-name CDS hedge — acceptance test.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator -> OutputAggregator -> BA-CVA stage (engine/cva/ba_cva.py)

Key responsibilities:
- Extend the P8.60 CVA-A1 baseline with a single eligible single-name CDS hedge
  (H_SN_CVA_001) referencing CP_CVA_001 with IDENTICAL correlation (r_hc = 1.00).
- Materialise ead_ccr from the CCR synthetic row for NS_CVA_001 (3-year GBP IR swap).
- Construct a perfect single-name hedge notional = ead_ccr / CVA_ALPHA (1.4) such
  that SNH_c == SCVA_c exactly, K_hedged == 0, and K_full == beta * K_reduced == 0.25 * K_reduced.
- Assert AggregatedResultBundle.cva_rwa == approx(golden["rwea_cva_full"]).
- Assert the ratio cva_rwa / rwea_cva_reduced == approx(0.25) — the strongest
  invariant, robust to the absolute EAD value.

CRITICAL FORMULA DIFFERENCE — SNH_c does NOT carry a (1/alpha) factor:
    SCVA_c = (1/alpha) * RW_c * M_NS * EAD_NS * DF_NS   [section 4.3, carries 1/alpha]
    SNH_c  = r_hc * RW_h * M_h * B_h * DF_h              [section 4.7, NO 1/alpha]

    Therefore for the perfect hedge (r_hc=1.0, matching RW/M/DF):
        B_h = EAD_NS / alpha = ead_ccr / CVA_ALPHA  (NOT ead_ccr itself)

Input / Output contract the engine-implementer must satisfy:
    NEW FIELD on RawDataBundle:
        cva_hedges: pl.LazyFrame | None = None
        Schema (CVA_HEDGE_SCHEMA) — columns:
            cva_hedge_reference            String   PK
            cva_hedge_type                 String   SINGLE_NAME | INDEX
            counterparty_reference         String   FK to cva_counterparties (null for INDEX)
            cva_hedge_correlation_band     String   IDENTICAL | LEGALLY_RELATED | SAME_SECTOR_REGION
            cva_hedge_rw_sector            String   sector key
            cva_hedge_rw_rating_band       String   IG | HY_NR
            cva_hedge_residual_maturity_years Float64  M_h (years)
            cva_hedge_notional             Float64  B_h
            cva_hedge_eligible             Boolean

    UPDATED AggregatedResultBundle.cva_rwa:
        Must use the full BA-CVA path when cva_hedges is present:
            K_full = beta * K_reduced + (1 - beta) * K_hedged   [section 4.5]
            SNH_c  = r_hc * RW_h * M_h * B_h * DF_h             [section 4.7, NO 1/alpha]
            OFR_full = DS_BA_CVA * K_full
            RWEA_full = OFR_full * 12.5

HOW THE HEDGE FRAME REACHES THE PIPELINE (fail-first guard):
    This test attaches the CVA hedge frame to the bundle using two guarded
    dataclasses.replace() calls:

      1. cva_counterparties — already shipped in P8.60.  Guard fires today;
         the CVA counterparty frame is attached and the engine computes the REDUCED
         cva_rwa (= P8.60 golden).

      2. cva_hedges — does NOT yet exist on RawDataBundle.  Guard is skipped today;
         pipeline runs without hedges; engine returns the REDUCED cva_rwa.

    PRIMARY assertion compares cva_rwa against the FULL (hedged) golden = 0.25 * reduced.
    Since reduced != 0.25 * reduced, the test fails with AssertionError today.
    Once the engine-implementer adds RawDataBundle.cva_hedges and the K_full path,
    the guard fires, the full-BA-CVA path runs, and all three tests pass.

References:
    - PS1/26 App.1 CVA Part 4.2  (K_reduced, DS_BA_CVA=0.65, rho=50%)
    - PS1/26 App.1 CVA Part 4.3  (SCVA_c formula with 1/alpha, page 400)
    - PS1/26 App.1 CVA Part 4.4  (RW table — Financials IG = 5.0%)
    - PS1/26 App.1 CVA Part 4.5  (full BA-CVA, beta=0.25, K_full formula, page 401)
    - PS1/26 App.1 CVA Part 4.6  (K_hedged formula)
    - PS1/26 App.1 CVA Part 4.7  (SNH_c formula — NO 1/alpha, page 402)
    - PS1/26 App.1 CVA Part 4.9  (HMA_c formula)
    - PS1/26 App.1 CVA Part 4.10 (r_hc table: IDENTICAL=1.00, page 403)
    - PS1/26 App.1 Own Funds Part 4(b) (x12.5 multiplier, page 15)
    - CRR Art. 274(2): EAD = alpha * (RC + PFE)
    - tests/fixtures/p8_60/cva_a1_builder.py
    - tests/fixtures/p8_62/cva_hedge_a1_builder.py
"""

from __future__ import annotations

import dataclasses
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p8_60.cva_a1_builder import (
    CVA_A1_NETTING_SET_ID,
    CVA_ALPHA,
    build_raw_data_bundle_cva_a1,
    compute_cva_a1_golden,
    create_cva_a1_counterparty_frame,
)
from tests.fixtures.p8_62.cva_hedge_a1_builder import (
    CVA_BA_BETA,
    compute_cva_full_golden,
    create_perfect_single_name_hedge_frame,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Basel 3.1 effective date (PS1/26 — 1 Jan 2027).
_REPORTING_DATE = date(2027, 1, 15)

# Synthetic exposure reference for NS_CVA_001 produced by the CCR adapter.
_CCR_EXPOSURE_REF = f"ccr__{CVA_A1_NETTING_SET_ID}"  # "ccr__NS_CVA_001"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cva_hedge_a1_pipeline_result() -> tuple[object, float]:
    """
    Run the CVA-HEDGE-A1 bundle through the Basel 3.1 SA+CCR pipeline.

    Returns a 2-tuple: (AggregatedResultBundle, ead_ccr) where ead_ccr is the
    materialised EAD for NS_CVA_001 from the CCR synthetic row (3-year GBP IR swap).

    Two field-presence guards are applied in sequence:

    Guard 1 — cva_counterparties (shipped in P8.60, fires today):
        If RawDataBundle.cva_counterparties exists, attach the CVA counterparty
        frame so the engine can compute cva_rwa via the reduced-K path.

    Guard 2 — cva_hedges (NOT YET SHIPPED, fails today):
        If RawDataBundle.cva_hedges exists, attach the single-name CDS hedge
        frame with perfect-hedge notional B_h = ead_ccr / CVA_ALPHA.
        This guard is skipped today → engine returns REDUCED cva_rwa.
        Once engine-implementer adds the field, this fires → full-K path runs.

    NOTE on hedge notional:
        The perfect-hedge condition requires B_h = EAD_NS / alpha (NOT EAD_NS),
        because SNH_c formula (section 4.7) carries NO (1/alpha) factor while
        SCVA_c (section 4.3) does.  Setting B_h = EAD_NS / alpha makes
        SNH_c == SCVA_c exactly, so K_hedged == 0 and K_full == beta * K_reduced.

    Arrange:
        - P8.60 base bundle (1 trade, 1 netting set, 1 counterparty, CCR inputs)
        - CVA counterparty frame (guard 1): CP_CVA_001, FINANCIAL, IG, M=3.0
        - CVA hedge frame (guard 2): H_SN_CVA_001, SINGLE_NAME, IDENTICAL,
          B_h = ead_ccr / CVA_ALPHA
        - Basel 3.1 config, STANDARDISED permission mode
    """
    # Arrange — base bundle from P8.60 (cva_hedges absent today)
    bundle = build_raw_data_bundle_cva_a1()

    # Guard 1: attach CVA counterparty frame (field shipped in P8.60).
    # Fires today — reduced-K path runs.
    if "cva_counterparties" in {f.name for f in dataclasses.fields(bundle)}:
        bundle = dataclasses.replace(
            bundle,
            cva_counterparties=create_cva_a1_counterparty_frame().lazy(),
        )

    config = CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act — run the full Basel 3.1 pipeline (reduced-K today; full-K post-impl)
    result = PipelineOrchestrator().run_with_data(bundle, config)

    # Materialise ead_ccr from the CCR synthetic row for NS_CVA_001.
    df = result.results.collect()
    ccr_rows = df.filter(pl.col("exposure_reference") == _CCR_EXPOSURE_REF).to_dicts()
    assert len(ccr_rows) == 1, (
        f"CVA-HEDGE-A1: expected exactly 1 CCR synthetic row for "
        f"exposure_reference={_CCR_EXPOSURE_REF!r}, got {len(ccr_rows)}. "
        "The CCR adapter must emit one synthetic row per netting set."
    )
    ead_ccr: float = ccr_rows[0]["ead_final"]

    # Guard 2: attach CVA hedge frame only when RawDataBundle.cva_hedges exists
    # (added by engine-implementer).  Today this guard is SKIPPED — the pipeline
    # already ran above without hedges.  Once the field is added the guard fires
    # and we need to re-run with the hedge attached.
    #
    # Implementation note: we re-run inside the guard so the hedge-notional is
    # computed from the materialised ead_ccr (not a hard-coded placeholder).
    if "cva_hedges" in {f.name for f in dataclasses.fields(bundle)}:
        # Perfect-hedge notional: B_h = ead_ccr / alpha (see module docstring).
        hedge_notional = ead_ccr / CVA_ALPHA
        hedge_frame = create_perfect_single_name_hedge_frame(hedge_notional)
        bundle_with_hedges = dataclasses.replace(bundle, cva_hedges=hedge_frame.lazy())
        result = PipelineOrchestrator().run_with_data(bundle_with_hedges, config)

    return result, ead_ccr


# ---------------------------------------------------------------------------
# CVA-HEDGE-A1 acceptance tests
# ---------------------------------------------------------------------------


class TestCVAHedgeA1FullBACVA:
    """
    CVA-HEDGE-A1: full BA-CVA RWEA with a single perfect single-name CDS hedge.

    Three tests:
      1. PRIMARY: cva_rwa == approx(golden["rwea_cva_full"])
         Verifies the full BA-CVA formula with perfect hedge:
             K_full = beta * K_reduced + (1 - beta) * 0 = 0.25 * K_reduced
             RWEA_full = DS_BA_CVA * K_full * 12.5
         FAILS TODAY: pipeline returns REDUCED cva_rwa (no cva_hedges field yet).

      2. INVARIANT: cva_rwa / rwea_cva_reduced == approx(beta=0.25)
         The strongest pin — beta-ratio is exact for a perfect hedge and
         cancels the absolute EAD. Verifies the hedge disallowance weight.
         FAILS TODAY: ratio is 1.0 (reduced / reduced) instead of 0.25.

      3. CONTROL: ead_ccr > 0 (CCR pipeline is healthy).
         PASSES TODAY: confirms the CCR pipeline produces a valid EAD.

    References:
        - PS1/26 App.1 CVA Part 4.2-4.10 (full BA-CVA formula)
        - PS1/26 App.1 Own Funds Part 4(b) (x12.5 multiplier)
        - tests/fixtures/p8_62/cva_hedge_a1_builder.py (compute_cva_full_golden)
    """

    def test_cva_hedge_a1_full_ba_cva_rwea(
        self,
        cva_hedge_a1_pipeline_result: tuple[object, float],
    ) -> None:
        """
        RWEA_full = DS_BA_CVA * beta * K_reduced * 12.5 matches the full-K golden.

        Arrange:
            - CVA-HEDGE-A1 fixture: CP_CVA_001 (FINANCIAL, IG) + NS_CVA_001
              (3y GBP IR swap) + H_SN_CVA_001 (perfect single-name CDS,
              B_h = ead_ccr / CVA_ALPHA, IDENTICAL correlation r_hc = 1.00).
            - Perfect-hedge condition: SNH_c == SCVA_c → K_hedged == 0.
            - Full-K golden derived from materialised ead_ccr via
              compute_cva_full_golden(ead_ccr).
        Act:
            Full Basel 3.1 SA+CCR+CVA pipeline with cva_hedges attached.
        Assert:
            AggregatedResultBundle.cva_rwa == approx(golden["rwea_cva_full"], rel=1e-6).

        Expected formula trace (M=3.0, EAD from pipeline, B_h = EAD/alpha):
            DF_NS     = (1 - e^(-0.05*3.0)) / (0.05*3.0) = 0.928613...
            SCVA_c    = (1/1.4) * 0.05 * 3.0 * ead_ccr * DF_NS
            SNH_c     = 1.0 * 0.05 * 3.0 * (ead_ccr/1.4) * DF_NS  = SCVA_c
            K_hedged  = 0.0  (perfect hedge, net_c = SCVA_c - SNH_c = 0, HMA_c = 0)
            K_full    = 0.25 * K_reduced + 0.75 * 0.0 = 0.25 * K_reduced
            OFR_full  = 0.65 * K_full
            RWEA_full = OFR_full * 12.5

        FAILS TODAY because:
            - RawDataBundle.cva_hedges does not exist → guard 2 skipped.
            - Engine returns REDUCED cva_rwa (= K_reduced path).
            - REDUCED != 0.25 * REDUCED → AssertionError.

        Engine-implementer must add:
            (1) RawDataBundle.cva_hedges: pl.LazyFrame | None = None
            (2) CVA_HEDGE_SCHEMA + loader edge for cva_hedges
            (3) engine/cva/ba_cva.py: accept cva_hedges, compute SNH_c WITHOUT
                (1/alpha), compute K_hedged, K_full = beta*K_reduced + (1-beta)*K_hedged
            (4) engine/stages/aggregate.py::_ba_cva_roll_up: pass data.cva_hedges
            (5) pack entries in packs/b31.py: cva_ba_beta=0.25, r_hc table

        References:
            - PS1/26 App.1 CVA Part 4.5  (K_full, beta=0.25, page 401)
            - PS1/26 App.1 CVA Part 4.6  (K_hedged formula)
            - PS1/26 App.1 CVA Part 4.7  (SNH_c — NO 1/alpha, page 402)
            - PS1/26 App.1 CVA Part 4.9  (HMA_c formula)
            - PS1/26 App.1 CVA Part 4.10 (r_hc=1.00 for IDENTICAL, page 403)
        """
        # Arrange
        result, ead_ccr = cva_hedge_a1_pipeline_result
        golden = compute_cva_full_golden(ead_ccr)
        expected_rwea = golden["rwea_cva_full"]

        # Act — read cva_rwa defensively so a missing field yields None
        # (AssertionError) rather than AttributeError (wrong failure mode).
        cva_rwa = getattr(result, "cva_rwa", None)

        # Assert
        assert cva_rwa == pytest.approx(expected_rwea, rel=1e-6), (
            f"CVA-HEDGE-A1: expected cva_rwa={expected_rwea:,.4f} "
            f"(DS_BA_CVA=0.65 * beta={CVA_BA_BETA} * K_reduced={golden['k_reduced']:,.4f} * 12.5), "
            f"got {cva_rwa!r}. "
            f"Materialised ead_ccr={ead_ccr:,.4f} for NS_CVA_001 (3y GBP IR swap). "
            f"Perfect-hedge notional B_h = ead_ccr / 1.4 = {ead_ccr / CVA_ALPHA:,.4f}. "
            f"Intermediate: DF_NS={golden['df_ns']:.10f}, SCVA_c={golden['scva_c']:,.4f}, "
            f"SNH_c={golden['snh_c']:,.4f}, K_hedged={golden['k_hedged']:.2e}, "
            f"K_full={golden['k_full']:,.4f}, OFR_full={golden['ofr_cva_full']:,.4f}. "
            "Engine-implementer must add: "
            "(1) RawDataBundle.cva_hedges: pl.LazyFrame | None = None, "
            "(2) CVA_HEDGE_SCHEMA + loader edge, "
            "(3) engine/cva/ba_cva.py extended with full-K path (SNH_c NO 1/alpha, "
            "K_full = beta*K_reduced + (1-beta)*K_hedged), "
            "(4) engine/stages/aggregate.py::_ba_cva_roll_up passing data.cva_hedges, "
            "(5) pack entries cva_ba_beta=0.25 and r_hc table in packs/b31.py."
        )

    def test_cva_hedge_a1_perfect_hedge_collapses_to_beta(
        self,
        cva_hedge_a1_pipeline_result: tuple[object, float],
    ) -> None:
        """
        Ratio invariant: cva_rwa / rwea_cva_reduced == approx(beta=0.25, rel=1e-9).

        This is the strongest pin — it is exact for a perfect hedge and cancels
        the absolute EAD.  Verifies the hedge disallowance weight beta = 0.25.

        Arrange:
            - Same CVA-HEDGE-A1 fixture as the primary test.
            - Reduced RWEA derived from materialised ead_ccr via
              compute_cva_a1_golden(ead_ccr)["rwea_cva"].
        Act:
            Full Basel 3.1 SA+CCR+CVA pipeline (full-K path with hedge).
        Assert:
            cva_rwa / reduced_rwea == approx(0.25, rel=1e-9).

        Perfect-hedge identity derivation:
            K_hedged = 0  (SNH_c == SCVA_c, net_c = 0, HMA_c = 0, IH = 0)
            K_full   = beta * K_reduced = 0.25 * K_reduced
            RWEA_full = DS_BA_CVA * 0.25 * K_reduced * 12.5
            RWEA_red  = DS_BA_CVA * 1.00 * K_reduced * 12.5
            Ratio     = 0.25 / 1.00 = beta = 0.25  (exact, EAD cancels)

        FAILS TODAY because engine returns REDUCED cva_rwa → ratio = 1.0 != 0.25.

        References:
            - PS1/26 App.1 CVA Part 4.5  (beta=0.25, K_full formula, page 401)
            - PS1/26 App.1 CVA Part 4.6  (K_hedged = 0 for perfect hedge)
        """
        # Arrange
        result, ead_ccr = cva_hedge_a1_pipeline_result
        reduced_golden = compute_cva_a1_golden(ead_ccr)
        reduced_rwea = reduced_golden["rwea_cva"]

        # Act — read cva_rwa defensively
        cva_rwa = getattr(result, "cva_rwa", None)

        # Guard: if cva_rwa is None we still produce a clear AssertionError.
        actual_ratio = (cva_rwa / reduced_rwea) if cva_rwa is not None else None

        # Assert
        assert actual_ratio == pytest.approx(CVA_BA_BETA, rel=1e-9), (
            f"CVA-HEDGE-A1: expected cva_rwa / rwea_cva_reduced == beta={CVA_BA_BETA}, "
            f"got ratio={actual_ratio!r} "
            f"(cva_rwa={cva_rwa!r}, reduced_rwea={reduced_rwea:,.4f}, ead_ccr={ead_ccr:,.4f}). "
            f"Perfect hedge (B_h = ead_ccr/alpha = {ead_ccr / CVA_ALPHA:,.4f}) must give "
            f"K_hedged=0 and K_full=beta*K_reduced. "
            "Engine-implementer: SNH_c formula (section 4.7) carries NO (1/alpha). "
            "K_full = beta * K_reduced + (1-beta) * K_hedged with beta=0.25."
        )

    def test_cva_hedge_a1_ead_ccr_positive(
        self,
        cva_hedge_a1_pipeline_result: tuple[object, float],
    ) -> None:
        """
        Control: the CCR pipeline produces a positive EAD for NS_CVA_001.

        Arrange: 3y GBP IR swap, GBP 100m notional, unmargined, MtM=0.
        Act:     full Basel 3.1 SA+CCR pipeline.
        Assert:  ead_ccr > 0  (SA-CCR EAD formula produces a positive value).

        This control test passes today and confirms the CCR pipeline is healthy;
        the EAD it pins is the input to both the CVA golden and the hedge notional.

        References:
            - CRR Art. 274(2): EAD = alpha * (RC + PFE) > 0 for any live trade
              with a non-zero PFE add-on.
            - CRR Art. 279b(1)(a): IR supervisory factor SF_IR = 0.5% > 0.
        """
        # Arrange
        _result, ead_ccr = cva_hedge_a1_pipeline_result

        # Assert
        assert ead_ccr > 0, (
            f"CVA-HEDGE-A1: ead_ccr must be positive for the 3-year GBP IR swap, "
            f"got {ead_ccr}. "
            "CRR Art. 274(2): EAD = alpha * (RC + PFE) where PFE > 0 for any "
            "live IR trade (supervisory factor SF_IR = 0.5%)."
        )
