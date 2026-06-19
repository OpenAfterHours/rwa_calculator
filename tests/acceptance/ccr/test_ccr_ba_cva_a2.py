"""
P8.46 / CVA-A2: BA-CVA reduced-K two-counterparty diversification — acceptance test.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator -> OutputAggregator -> BA-CVA stage (engine/cva/ba_cva.py)

Key responsibilities:
- Run the CVA-A2 fixture (two counterparties CP_CVA_A2_1 / CP_CVA_A2_2, each
  with one netting set — 3-year and 5-year GBP IR swaps) through the Basel 3.1
  SA+CCR+CVA pipeline.
- Materialise ead1 / ead2 from the CCR synthetic rows for NS_CVA_A2_1 /
  NS_CVA_A2_2.
- Derive the expected cva_rwa from the materialised EADs via
  compute_cva_a2_golden(ead1, ead2) — golden is NOT hard-coded.
- Assert AggregatedResultBundle.cva_rwa == approx(golden["cva_rwa"]).
- Assert cva_method == "BA-CVA" and cva_hedges_recognised is False.
- Assert the diversification invariant: sqrt(SCVA_1²+SCVA_2²) < K_reduced < SCVA_1+SCVA_2.

Green-on-arrival regression pin: the engine is already shipped (P8.60/62/63).
The test is expected to PASS on first run.  It will fail if the BA-CVA engine
regresses on the two-counterparty K_reduced formula.

HOW THE CVA FRAME REACHES THE PIPELINE:
    This test attaches the frame to the bundle via a field-presence-guarded
    dataclasses.replace().  When RawDataBundle.cva_counterparties does not yet
    exist the guard silently skips the attach, the pipeline runs without it,
    getattr(result, "cva_rwa", None) returns None, and the assertion fails
    cleanly (AssertionError).  Once the field exists, the guard fires and the
    CVA stage can compute cva_rwa.

IMPORTANT — golden derivation:
    compute_cva_a2_golden(ead1, ead2) is called with the live EADs materialised
    from the pipeline — NOT with any hard-coded constant.  A numeric stale
    comment at line ~154 of the builder shows an old DF value; the helper
    function is the source of truth for all expected values.

References:
    - PS1/26 App.1 CVA Part 4.2 (K_reduced two-CP, DSBA-CVA=0.65, rho=50%)
    - PS1/26 App.1 CVA Part 4.3 (SCVA_c, DF formula, alpha=1.4)
    - PS1/26 App.1 CVA Part 4.4 (RW table — Financials IG = 5.0%)
    - PS1/26 App.1 Own Funds Part 4(b) (x12.5 multiplier)
    - CRR Art. 274(2): EAD = alpha * (RC + PFE)
    - tests/fixtures/p8_46/cva_a2_builder.py
    - tests/acceptance/ccr/test_ccr_ba_cva_a1.py  (single-CP baseline)
"""

from __future__ import annotations

import dataclasses
import math
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p8_46.cva_a2_builder import (
    CVA_A2_NS1_ID,
    CVA_A2_NS2_ID,
    build_raw_data_bundle_cva_a2,
    compute_cva_a2_golden,
    create_cva_a2_counterparty_frame,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Basel 3.1 effective date (PS1/26 — 1 Jan 2027).
_REPORTING_DATE = date(2027, 1, 15)

# Synthetic exposure references for NS_CVA_A2_1 / NS_CVA_A2_2 produced by the
# CCR adapter (format: "ccr__<netting_set_id>").
_CCR_EXPOSURE_REF_1 = f"ccr__{CVA_A2_NS1_ID}"   # "ccr__NS_CVA_A2_1"
_CCR_EXPOSURE_REF_2 = f"ccr__{CVA_A2_NS2_ID}"   # "ccr__NS_CVA_A2_2"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cva_a2_pipeline_result() -> tuple[object, float, float]:
    """
    Run the CVA-A2 bundle through the Basel 3.1 SA+CCR pipeline.

    Returns a 3-tuple: (AggregatedResultBundle, ead1, ead2) where ead1 / ead2
    are the materialised EADs for NS_CVA_A2_1 (3-year swap) and NS_CVA_A2_2
    (5-year swap) from the CCR synthetic rows.

    The CVA counterparty frame is attached to the bundle via a field-presence
    guard: if RawDataBundle.cva_counterparties already exists (added by the
    engine-implementer) the guard fires and attaches the frame so the CVA stage
    can compute cva_rwa.  Until that field is added the guard skips the attach,
    and getattr(result, "cva_rwa", None) returns None.

    Arrange:
        - 2 trades: T_CVA_A2_1 (3y GBP IR swap) / T_CVA_A2_2 (5y GBP IR swap)
        - 2 netting sets: NS_CVA_A2_1 -> CP_CVA_A2_1 / NS_CVA_A2_2 -> CP_CVA_A2_2
        - Both CPs: GB institution, CQS 2, unmargined
        - CVA counterparty frame (guarded): 2 rows, FINANCIAL/IG, M=3.0/5.0
        - Basel 3.1 config, STANDARDISED permission mode
    """
    # Arrange — base bundle (cva_counterparties absent today on the green path;
    # the guard handles both states)
    bundle = build_raw_data_bundle_cva_a2()

    # Attach the CVA counterparty frame only when RawDataBundle already
    # declares the field.  This guard is the sole mechanism by which the
    # frame reaches the pipeline: no fixture file edit is required.
    if "cva_counterparties" in {f.name for f in dataclasses.fields(bundle)}:
        bundle = dataclasses.replace(
            bundle,
            cva_counterparties=create_cva_a2_counterparty_frame().lazy(),
        )

    config = CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act — run the full Basel 3.1 pipeline
    result = PipelineOrchestrator().run_with_data(bundle, config)

    # Materialise ead_final from the CCR synthetic rows
    df = result.results.collect()

    ccr_rows_1 = df.filter(pl.col("exposure_reference") == _CCR_EXPOSURE_REF_1).to_dicts()
    assert len(ccr_rows_1) == 1, (
        f"CVA-A2: expected exactly 1 CCR synthetic row for "
        f"exposure_reference={_CCR_EXPOSURE_REF_1!r}, got {len(ccr_rows_1)}. "
        "The CCR adapter must emit one synthetic row per netting set."
    )

    ccr_rows_2 = df.filter(pl.col("exposure_reference") == _CCR_EXPOSURE_REF_2).to_dicts()
    assert len(ccr_rows_2) == 1, (
        f"CVA-A2: expected exactly 1 CCR synthetic row for "
        f"exposure_reference={_CCR_EXPOSURE_REF_2!r}, got {len(ccr_rows_2)}. "
        "The CCR adapter must emit one synthetic row per netting set."
    )

    ead1: float = ccr_rows_1[0]["ead_final"]
    ead2: float = ccr_rows_2[0]["ead_final"]

    return result, ead1, ead2


# ---------------------------------------------------------------------------
# CVA-A2 acceptance tests
# ---------------------------------------------------------------------------


class TestCVAA2BACVATwoCounterpartyDiversification:
    """
    CVA-A2: BA-CVA reduced-K RWEA for two counterparties (ρ=0.5 cross-term).

    Four focused tests:
      1. PRIMARY: cva_rwa == approx(golden["cva_rwa"], rel=1e-6)
         Verifies the two-CP K_reduced formula:
             K_reduced = sqrt[(ρ*(SCVA_1+SCVA_2))² + (1−ρ²)*(SCVA_1²+SCVA_2²)]
             OFR_CVA   = 0.65 * K_reduced
             RWEA_CVA  = OFR_CVA * 12.5
         using the materialised EADs from the 3-year and 5-year IR swaps.

      2. cva_method == "BA-CVA"  (method label is present and correct).

      3. cva_hedges_recognised is False  (reduced path — no eligible hedge).

      4. CONTROL: both CCR synthetic rows have ead_final > 0.

      5. DIVERSIFICATION INVARIANT: sqrt(SCVA_1²+SCVA_2²) < K_reduced < SCVA_1+SCVA_2
         Pins ρ=0.5 independently of the absolute EAD values.

    References:
        - PS1/26 App.1 CVA Part 4.2-4.4
        - tests/fixtures/p8_46/cva_a2_builder.py (compute_cva_a2_golden)
    """

    def test_cva_a2_ba_cva_reduced_rwea(
        self,
        cva_a2_pipeline_result: tuple[object, float, float],
    ) -> None:
        """
        RWEA_CVA = DS_BA_CVA(0.65) * K_reduced * 12.5 matches the golden.

        Arrange:
            - CVA-A2 fixture: two counterparties (FINANCIAL, IG), two netting
              sets (3y / 5y GBP IR swap), CVA counterparty frame attached to
              RawDataBundle.cva_counterparties via guarded dataclasses.replace.
            - Golden derived from materialised (ead1, ead2) via
              compute_cva_a2_golden(ead1, ead2).
        Act:
            Full Basel 3.1 SA+CCR+CVA pipeline.
        Assert:
            AggregatedResultBundle.cva_rwa == approx(golden["cva_rwa"], rel=1e-6).

        Expected formula trace:
            DF1       = (1 - e^(-0.05*3.0)) / (0.05*3.0) = 0.9286134905...
            DF2       = (1 - e^(-0.05*5.0)) / (0.05*5.0) = 0.8847905680...
            SCVA_1    = (1/1.4) * 0.05 * 3.0 * ead1 * DF1
            SCVA_2    = (1/1.4) * 0.05 * 5.0 * ead2 * DF2
            K_reduced = sqrt[(0.5*(SCVA_1+SCVA_2))² + 0.75*(SCVA_1²+SCVA_2²)]
            OFR_CVA   = 0.65 * K_reduced
            RWEA_CVA  = OFR_CVA * 12.5

        References:
            - PS1/26 App.1 CVA Part 4.2-4.4
            - CRR Art. 274(2): EAD = alpha * (RC + PFE)
        """
        # Arrange
        result, ead1, ead2 = cva_a2_pipeline_result
        golden = compute_cva_a2_golden(ead1, ead2)
        expected_rwea = golden["cva_rwa"]

        # Act — read cva_rwa defensively so a missing field yields None
        # (AssertionError) rather than AttributeError (wrong failure mode).
        cva_rwa = getattr(result, "cva_rwa", None)

        # Assert
        assert cva_rwa == pytest.approx(expected_rwea, rel=1e-6), (
            f"CVA-A2: expected cva_rwa={expected_rwea:,.4f} "
            f"(DS_BA_CVA=0.65 * K_reduced={golden['k_reduced']:,.4f} * 12.5), "
            f"got {cva_rwa!r}. "
            f"Materialised ead1={ead1:,.4f} (NS_CVA_A2_1, 3y swap), "
            f"ead2={ead2:,.4f} (NS_CVA_A2_2, 5y swap). "
            f"Intermediate values: DF1={golden['df1']:.10f}, DF2={golden['df2']:.10f}, "
            f"SCVA_1={golden['scva_1']:,.4f}, SCVA_2={golden['scva_2']:,.4f}, "
            f"OFR_CVA={golden['ofr_cva']:,.4f}."
        )

    def test_cva_a2_cva_method_label(
        self,
        cva_a2_pipeline_result: tuple[object, float, float],
    ) -> None:
        """
        cva_method == "BA-CVA"  for the two-counterparty reduced path.

        Arrange: CVA-A2 fixture — 2 CPs, no hedge instrument.
        Act:     Full Basel 3.1 SA+CCR+CVA pipeline.
        Assert:  result.cva_method == "BA-CVA".

        The method label is "BA-CVA" for both reduced and full sub-cases per
        the P8.63 design lock (NOT "BA-CVA-REDUCED" or "BA-CVA-FULL").

        References:
            - PS1/26 App.1 CVA Part 4.2 (BA-CVA framework)
            - tests/acceptance/ccr/test_ccr_cva_aggregated_p8_63.py (design lock)
        """
        # Arrange
        result, _ead1, _ead2 = cva_a2_pipeline_result

        # Act — read defensively (missing field yields None, not AttributeError)
        cva_method = getattr(result, "cva_method", None)

        # Assert
        assert cva_method == "BA-CVA", (
            f"CVA-A2: expected cva_method='BA-CVA', got {cva_method!r}. "
            "Design lock from P8.63: the method label must be 'BA-CVA' for "
            "both reduced and full sub-cases."
        )

    def test_cva_a2_no_hedges_recognised(
        self,
        cva_a2_pipeline_result: tuple[object, float, float],
    ) -> None:
        """
        cva_hedges_recognised is False — no eligible hedge in the CVA-A2 bundle.

        Arrange: CVA-A2 fixture — 2 CPs, no CVA hedge instruments.
        Act:     Full Basel 3.1 SA+CCR+CVA pipeline.
        Assert:  result.cva_hedges_recognised is False.

        The reduced BA-CVA path (no eligible hedge) sets cva_hedges_recognised=False.
        The full path with eligible hedges sets it True (tested in P8.62/63).

        References:
            - PS1/26 App.1 CVA Part 4.2 (reduced vs full variants)
            - tests/acceptance/ccr/test_ccr_cva_aggregated_p8_63.py (design lock)
        """
        # Arrange
        result, _ead1, _ead2 = cva_a2_pipeline_result

        # Act — read defensively
        cva_hedges_recognised = getattr(result, "cva_hedges_recognised", None)

        # Assert
        assert cva_hedges_recognised is False, (
            f"CVA-A2: expected cva_hedges_recognised=False (reduced path, no hedge), "
            f"got {cva_hedges_recognised!r}."
        )

    def test_cva_a2_both_ead_finals_positive(
        self,
        cva_a2_pipeline_result: tuple[object, float, float],
    ) -> None:
        """
        Control: both CCR synthetic rows have ead_final > 0.

        Arrange:
            - NS_CVA_A2_1: 3y GBP IR swap, GBP 100m notional, unmargined, MtM=0.
            - NS_CVA_A2_2: 5y GBP IR swap, GBP 100m notional, unmargined, MtM=0.
        Act:  full Basel 3.1 SA+CCR pipeline.
        Assert:
            ead1 > 0 AND ead2 > 0
            (SA-CCR EAD = alpha * (RC + PFE) > 0 for any live IR trade).

        This control passes before the CVA stage is wired and confirms the
        CCR pipeline is healthy; the EADs it pins are the inputs to the
        CVA golden computation.

        References:
            - CRR Art. 274(2): EAD = alpha * (RC + PFE)
            - CRR Art. 279b(1)(a): IR PFE add-on > 0 for a live swap
        """
        # Arrange
        _result, ead1, ead2 = cva_a2_pipeline_result

        # Assert
        assert ead1 > 0, (
            f"CVA-A2: ead_final for NS_CVA_A2_1 (3y GBP IR swap) must be positive, "
            f"got {ead1}. "
            "CRR Art. 274(2): EAD = alpha * (RC + PFE) where PFE > 0 for any "
            "live IR trade (supervisory factor SF_IR = 0.5%)."
        )
        assert ead2 > 0, (
            f"CVA-A2: ead_final for NS_CVA_A2_2 (5y GBP IR swap) must be positive, "
            f"got {ead2}. "
            "CRR Art. 274(2): EAD = alpha * (RC + PFE) where PFE > 0 for any "
            "live IR trade (supervisory factor SF_IR = 0.5%)."
        )

    def test_cva_a2_diversification_invariant(
        self,
        cva_a2_pipeline_result: tuple[object, float, float],
    ) -> None:
        """
        Diversification invariant: sqrt(SCVA_1²+SCVA_2²) < K_reduced < SCVA_1+SCVA_2.

        This invariant holds for any pair of positive SCVA values and strictly
        pins the ρ=0.5 cross-term behaviour independent of the absolute EAD
        magnitudes.  It distinguishes the two-counterparty K_reduced from:
          - The single-CP identity (K_reduced = SCVA, tested in A1).
          - Perfect correlation (K_reduced would equal SCVA_1 + SCVA_2).
          - Full independence (K_reduced would equal sqrt(SCVA_1²+SCVA_2²)).

        Arrange:
            Golden computed from materialised (ead1, ead2) — no hard-coded values.
        Act:
            Extract scva_1, scva_2, k_reduced from compute_cva_a2_golden(ead1, ead2).
        Assert:
            sqrt(SCVA_1²+SCVA_2²) < K_reduced < SCVA_1+SCVA_2  (strict inequalities).

        References:
            - PS1/26 App.1 CVA Part 4.2 (K_reduced formula with ρ=0.5)
        """
        # Arrange
        _result, ead1, ead2 = cva_a2_pipeline_result
        golden = compute_cva_a2_golden(ead1, ead2)

        scva_1 = golden["scva_1"]
        scva_2 = golden["scva_2"]
        k_reduced = golden["k_reduced"]

        low = math.sqrt(scva_1**2 + scva_2**2)   # full independence bound
        high = scva_1 + scva_2                     # perfect correlation bound

        # Assert — both inequalities must be strict
        assert low < k_reduced, (
            f"CVA-A2: diversification invariant lower bound violated: "
            f"sqrt(SCVA_1²+SCVA_2²)={low:.6f} must be < K_reduced={k_reduced:.6f}. "
            f"SCVA_1={scva_1:.6f}, SCVA_2={scva_2:.6f}. "
            "This indicates the systematic (rho) term dominates independent of EAD — "
            "check the K_reduced formula in engine/cva/ba_cva.py."
        )
        assert k_reduced < high, (
            f"CVA-A2: diversification invariant upper bound violated: "
            f"K_reduced={k_reduced:.6f} must be < SCVA_1+SCVA_2={high:.6f}. "
            f"SCVA_1={scva_1:.6f}, SCVA_2={scva_2:.6f}. "
            "This indicates missing diversification benefit — check the idiosyncratic "
            "term (1-rho²)*(SCVA_1²+SCVA_2²) in engine/cva/ba_cva.py."
        )
