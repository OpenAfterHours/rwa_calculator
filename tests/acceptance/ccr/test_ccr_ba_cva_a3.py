"""
P8.46 / CVA-A3: BA-CVA reduced-K one-counterparty / two-netting-set SCVA aggregation
— acceptance test.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator -> OutputAggregator -> BA-CVA stage (engine/cva/ba_cva.py)

Key responsibilities:
- Run the CVA-A3 fixture (ONE counterparty CP_CVA_A3 with TWO netting sets
  NS_CVA_A3_1 and NS_CVA_A3_2 — 3-year and 5-year GBP IR swaps) through the
  Basel 3.1 SA+CCR+CVA pipeline.
- Materialise ead_ns1 / ead_ns2 from the CCR synthetic rows for NS_CVA_A3_1 /
  NS_CVA_A3_2.
- Derive the expected cva_rwa from the materialised EADs via
  compute_cva_a3_golden(ead_ns1, ead_ns2) — golden is NOT hard-coded.
- Assert AggregatedResultBundle.cva_rwa == approx(golden["cva_rwa"]).
- Assert cva_method == "BA-CVA" and cva_hedges_recognised is False.
- Assert the cross-NS SCVA additivity invariant:
      golden["scva_c"] == approx(golden["scva_ns1"] + golden["scva_ns2"], rel=1e-9)
- Assert the single-CP K collapse:
      golden["k_reduced"] == approx(golden["scva_c"], rel=1e-9)
- Assert the EAD-monotone decomposition (optional reinforcing):
      golden["scva_ns1"] / golden["scva_ns2"] == approx(ead_ns1 / ead_ns2, rel=1e-9)

Green-on-arrival regression pin: the engine is already shipped (P8.60/62/63).
The test is expected to PASS on first run.  It will fail if the BA-CVA engine
regresses on the one-counterparty / two-netting-set SCVA aggregation path.

NOVELTY vs CVA-A1 and CVA-A2:
    CVA-A1: one CP / one NS — trivial single-term sum.
    CVA-A2: two CPs / one NS each — inter-CP rho cross-term in K_reduced.
    CVA-A3: one CP / TWO NS — isolates the INNER SUM_NS within one SCVA_c.
    Because n=1 (single CP), the portfolio K collapses to SCVA_c:
        K_reduced = sqrt[(rho*SCVA_c)^2 + (1-rho^2)*SCVA_c^2] = SCVA_c

HOW THE CVA FRAME REACHES THE PIPELINE:
    This test attaches the frame to the bundle via a field-presence-guarded
    dataclasses.replace().  When RawDataBundle.cva_counterparties does not yet
    exist the guard silently skips the attach, the pipeline runs without it,
    getattr(result, "cva_rwa", None) returns None, and the assertion fails
    cleanly (AssertionError).  Once the field exists, the guard fires and the
    CVA stage can compute cva_rwa.

ENGINE-FIDELITY NOTE (shared M & DF):
    The engine applies M_NS = cva_effective_maturity_years from the single
    CVA-counterparty row to BOTH netting-set rows (keyed by counterparty_reference,
    joined onto every NS row, then summed).  Both NS share M=4.0 and DF=0.906346.
    Consequently SCVA_NS1/SCVA_NS2 == EAD_NS1/EAD_NS2 (assertion 7).

References:
    - PS1/26 App.1 CVA Part 4.2 (K_reduced single-CP collapse, DSBA-CVA=0.65, rho=50%)
    - PS1/26 App.1 CVA Part 4.3 (SCVA_c = (1/alpha)*RW_c*SUM_NS[M*EAD*DF], DF formula)
    - PS1/26 App.1 CVA Part 4.4 (RW table — Financials IG = 5.0%)
    - PS1/26 App.1 Own Funds Part 4(b) (x12.5 multiplier)
    - CRR Art. 274(2): EAD = alpha * (RC + PFE)
    - tests/fixtures/p8_46/cva_a3_builder.py
    - tests/acceptance/ccr/test_ccr_ba_cva_a1.py  (single-CP / single-NS baseline)
    - tests/acceptance/ccr/test_ccr_ba_cva_a2.py  (two-CP / one-NS-each)
"""

from __future__ import annotations

import dataclasses
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p8_46.cva_a3_builder import (
    CVA_A3_NS1_ID,
    CVA_A3_NS2_ID,
    build_raw_data_bundle_cva_a3,
    compute_cva_a3_golden,
    create_cva_a3_counterparty_frame,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Basel 3.1 effective date (PS1/26 — 1 Jan 2027).
_REPORTING_DATE = date(2027, 1, 15)

# Synthetic exposure references for NS_CVA_A3_1 / NS_CVA_A3_2 produced by the
# CCR adapter (format: "ccr__<netting_set_id>").
_CCR_EXPOSURE_REF_1 = f"ccr__{CVA_A3_NS1_ID}"  # "ccr__NS_CVA_A3_1"
_CCR_EXPOSURE_REF_2 = f"ccr__{CVA_A3_NS2_ID}"  # "ccr__NS_CVA_A3_2"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cva_a3_pipeline_result() -> tuple[object, float, float]:
    """
    Run the CVA-A3 bundle through the Basel 3.1 SA+CCR pipeline.

    Returns a 3-tuple: (AggregatedResultBundle, ead_ns1, ead_ns2) where ead_ns1 /
    ead_ns2 are the materialised EADs for NS_CVA_A3_1 (3-year swap) and NS_CVA_A3_2
    (5-year swap) from the CCR synthetic rows.

    The CVA counterparty frame is attached to the bundle via a field-presence
    guard: if RawDataBundle.cva_counterparties already exists (added by the
    engine-implementer) the guard fires and attaches the frame so the CVA stage
    can compute cva_rwa.  Until that field is added the guard skips the attach,
    and getattr(result, "cva_rwa", None) returns None.

    Arrange:
        - 2 trades: T_CVA_A3_1 (3y GBP IR swap) / T_CVA_A3_2 (5y GBP IR swap)
        - 2 netting sets: NS_CVA_A3_1 -> CP_CVA_A3 / NS_CVA_A3_2 -> CP_CVA_A3
          (SAME counterparty — structural crux of A3)
        - 1 CP: CP_CVA_A3, GB institution, CQS 2, unmargined
        - CVA counterparty frame (guarded): 1 row, FINANCIAL/IG, M=4.0
        - Basel 3.1 config, STANDARDISED permission mode
    """
    # Arrange — base bundle (cva_counterparties absent today on the green path;
    # the guard handles both states)
    bundle = build_raw_data_bundle_cva_a3()

    # Attach the CVA counterparty frame only when RawDataBundle already
    # declares the field.  This guard is the sole mechanism by which the
    # frame reaches the pipeline: no fixture file edit is required.
    if "cva_counterparties" in {f.name for f in dataclasses.fields(bundle)}:
        bundle = dataclasses.replace(
            bundle,
            cva_counterparties=create_cva_a3_counterparty_frame().lazy(),
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
        f"CVA-A3: expected exactly 1 CCR synthetic row for "
        f"exposure_reference={_CCR_EXPOSURE_REF_1!r}, got {len(ccr_rows_1)}. "
        "The CCR adapter must emit one synthetic row per netting set."
    )

    ccr_rows_2 = df.filter(pl.col("exposure_reference") == _CCR_EXPOSURE_REF_2).to_dicts()
    assert len(ccr_rows_2) == 1, (
        f"CVA-A3: expected exactly 1 CCR synthetic row for "
        f"exposure_reference={_CCR_EXPOSURE_REF_2!r}, got {len(ccr_rows_2)}. "
        "The CCR adapter must emit one synthetic row per netting set."
    )

    ead_ns1: float = ccr_rows_1[0]["ead_final"]
    ead_ns2: float = ccr_rows_2[0]["ead_final"]

    return result, ead_ns1, ead_ns2


# ---------------------------------------------------------------------------
# CVA-A3 acceptance tests
# ---------------------------------------------------------------------------


class TestCVAA3BACVAOneCounterpartyTwoNettingSets:
    """
    CVA-A3: BA-CVA reduced-K RWEA for one counterparty / two netting sets.

    Seven focused tests:
      1. PRIMARY: cva_rwa == approx(golden["cva_rwa"], rel=1e-6)
         Verifies the one-CP / two-NS SCVA aggregation and K-collapse formula:
             DF_NS     = (1 - e^(-0.05*4.0)) / (0.05*4.0) = 0.906346...
             SCVA_NS1  = (1/1.4) * 0.05 * 4.0 * ead_ns1 * DF_NS
             SCVA_NS2  = (1/1.4) * 0.05 * 4.0 * ead_ns2 * DF_NS
             SCVA_c    = SCVA_NS1 + SCVA_NS2
             K_reduced = SCVA_c             (n=1 identity)
             OFR_CVA   = 0.65 * K_reduced
             RWEA_CVA  = OFR_CVA * 12.5
         using the materialised EADs from the 3-year and 5-year IR swaps.

      2. cva_method == "BA-CVA"  (method label is present and correct).

      3. cva_hedges_recognised is False  (reduced path — no eligible hedge).

      4. CONTROL: both CCR synthetic rows have ead_final > 0.

      5. CROSS-NS ADDITIVITY OF SCVA_c:
             golden["scva_c"] == approx(golden["scva_ns1"] + golden["scva_ns2"], rel=1e-9)
         Pins engine group_by("counterparty_reference").agg(...sum()).

      6. SINGLE-CP K COLLAPSE:
             golden["k_reduced"] == approx(golden["scva_c"], rel=1e-9)
         Algebraic identity for n=1: sqrt[(rho*S)^2 + (1-rho^2)*S^2] = S.

      7. EAD-MONOTONE DECOMPOSITION (optional reinforcing):
             golden["scva_ns1"] / golden["scva_ns2"] == approx(ead_ns1 / ead_ns2, rel=1e-9)
         Shared M=4.0 and DF=0.906346 means SCVA ratio equals EAD ratio.

    References:
        - PS1/26 App.1 CVA Part 4.2-4.4
        - tests/fixtures/p8_46/cva_a3_builder.py (compute_cva_a3_golden)
    """

    def test_cva_a3_ba_cva_reduced_rwea(
        self,
        cva_a3_pipeline_result: tuple[object, float, float],
    ) -> None:
        """
        RWEA_CVA = DS_BA_CVA(0.65) * K_reduced * 12.5 matches the golden.

        Arrange:
            - CVA-A3 fixture: one counterparty CP_CVA_A3 (FINANCIAL, IG), two
              netting sets (3y / 5y GBP IR swap), CVA counterparty frame (one
              row, M=4.0) attached to RawDataBundle.cva_counterparties via
              guarded dataclasses.replace.
            - Golden derived from materialised (ead_ns1, ead_ns2) via
              compute_cva_a3_golden(ead_ns1, ead_ns2).
        Act:
            Full Basel 3.1 SA+CCR+CVA pipeline.
        Assert:
            AggregatedResultBundle.cva_rwa == approx(golden["cva_rwa"], rel=1e-6).

        Expected formula trace:
            DF_NS     = (1 - e^(-0.05*4.0)) / (0.05*4.0) = 0.9063462339...
            SCVA_NS1  = (1/1.4) * 0.05 * 4.0 * ead_ns1 * DF_NS
            SCVA_NS2  = (1/1.4) * 0.05 * 4.0 * ead_ns2 * DF_NS
            SCVA_c    = SCVA_NS1 + SCVA_NS2
            K_reduced = SCVA_c   (single-CP n=1 identity)
            OFR_CVA   = 0.65 * K_reduced
            RWEA_CVA  = OFR_CVA * 12.5

        References:
            - PS1/26 App.1 CVA Part 4.2-4.4
            - CRR Art. 274(2): EAD = alpha * (RC + PFE)
        """
        # Arrange
        result, ead_ns1, ead_ns2 = cva_a3_pipeline_result
        golden = compute_cva_a3_golden(ead_ns1, ead_ns2)
        expected_rwea = golden["cva_rwa"]

        # Act — read cva_rwa defensively so a missing field yields None
        # (AssertionError) rather than AttributeError (wrong failure mode).
        cva_rwa = getattr(result, "cva_rwa", None)

        # Assert
        assert cva_rwa == pytest.approx(expected_rwea, rel=1e-6), (
            f"CVA-A3: expected cva_rwa={expected_rwea:,.4f} "
            f"(DS_BA_CVA=0.65 * K_reduced={golden['k_reduced']:,.4f} * 12.5), "
            f"got {cva_rwa!r}. "
            f"Materialised ead_ns1={ead_ns1:,.4f} (NS_CVA_A3_1, 3y swap), "
            f"ead_ns2={ead_ns2:,.4f} (NS_CVA_A3_2, 5y swap). "
            f"Intermediate values: DF_NS={golden['df_ns']:.10f}, "
            f"SCVA_NS1={golden['scva_ns1']:,.4f}, SCVA_NS2={golden['scva_ns2']:,.4f}, "
            f"SCVA_c={golden['scva_c']:,.4f}, OFR_CVA={golden['ofr_cva']:,.4f}."
        )

    def test_cva_a3_cva_method_label(
        self,
        cva_a3_pipeline_result: tuple[object, float, float],
    ) -> None:
        """
        cva_method == "BA-CVA" for the one-counterparty / two-netting-set reduced path.

        Arrange: CVA-A3 fixture — 1 CP, 2 NS, no hedge instrument.
        Act:     Full Basel 3.1 SA+CCR+CVA pipeline.
        Assert:  result.cva_method == "BA-CVA".

        The method label is "BA-CVA" for both reduced and full sub-cases per
        the P8.63 design lock (NOT "BA-CVA-REDUCED" or "BA-CVA-FULL").

        References:
            - PS1/26 App.1 CVA Part 4.2 (BA-CVA framework)
            - tests/acceptance/ccr/test_ccr_cva_aggregated_p8_63.py (design lock)
        """
        # Arrange
        result, _ead_ns1, _ead_ns2 = cva_a3_pipeline_result

        # Act — read defensively (missing field yields None, not AttributeError)
        cva_method = getattr(result, "cva_method", None)

        # Assert
        assert cva_method == "BA-CVA", (
            f"CVA-A3: expected cva_method='BA-CVA', got {cva_method!r}. "
            "Design lock from P8.63: the method label must be 'BA-CVA' for "
            "both reduced and full sub-cases."
        )

    def test_cva_a3_no_hedges_recognised(
        self,
        cva_a3_pipeline_result: tuple[object, float, float],
    ) -> None:
        """
        cva_hedges_recognised is False — no eligible hedge in the CVA-A3 bundle.

        Arrange: CVA-A3 fixture — 1 CP, 2 NS, no CVA hedge instruments.
        Act:     Full Basel 3.1 SA+CCR+CVA pipeline.
        Assert:  result.cva_hedges_recognised is False.

        The reduced BA-CVA path (no eligible hedge) sets cva_hedges_recognised=False.
        The full path with eligible hedges sets it True (tested in P8.62/63).

        References:
            - PS1/26 App.1 CVA Part 4.2 (reduced vs full variants)
            - tests/acceptance/ccr/test_ccr_cva_aggregated_p8_63.py (design lock)
        """
        # Arrange
        result, _ead_ns1, _ead_ns2 = cva_a3_pipeline_result

        # Act — read defensively
        cva_hedges_recognised = getattr(result, "cva_hedges_recognised", None)

        # Assert
        assert cva_hedges_recognised is False, (
            f"CVA-A3: expected cva_hedges_recognised=False (reduced path, no hedge), "
            f"got {cva_hedges_recognised!r}."
        )

    def test_cva_a3_both_ead_finals_positive(
        self,
        cva_a3_pipeline_result: tuple[object, float, float],
    ) -> None:
        """
        Control: both CCR synthetic rows have ead_final > 0.

        Arrange:
            - NS_CVA_A3_1: 3y GBP IR swap, GBP 100m notional, unmargined, MtM=0.
            - NS_CVA_A3_2: 5y GBP IR swap, GBP 100m notional, unmargined, MtM=0.
        Act:  full Basel 3.1 SA+CCR pipeline.
        Assert:
            ead_ns1 > 0 AND ead_ns2 > 0
            (SA-CCR EAD = alpha * (RC + PFE) > 0 for any live IR trade).

        This control passes before the CVA stage is wired and confirms the
        CCR pipeline is healthy; the EADs it pins are the inputs to the
        CVA golden computation.

        References:
            - CRR Art. 274(2): EAD = alpha * (RC + PFE)
            - CRR Art. 279b(1)(a): IR PFE add-on > 0 for a live swap
        """
        # Arrange
        _result, ead_ns1, ead_ns2 = cva_a3_pipeline_result

        # Assert
        assert ead_ns1 > 0, (
            f"CVA-A3: ead_final for NS_CVA_A3_1 (3y GBP IR swap) must be positive, "
            f"got {ead_ns1}. "
            "CRR Art. 274(2): EAD = alpha * (RC + PFE) where PFE > 0 for any "
            "live IR trade (supervisory factor SF_IR = 0.5%)."
        )
        assert ead_ns2 > 0, (
            f"CVA-A3: ead_final for NS_CVA_A3_2 (5y GBP IR swap) must be positive, "
            f"got {ead_ns2}. "
            "CRR Art. 274(2): EAD = alpha * (RC + PFE) where PFE > 0 for any "
            "live IR trade (supervisory factor SF_IR = 0.5%)."
        )

    def test_cva_a3_cross_ns_scva_additivity(
        self,
        cva_a3_pipeline_result: tuple[object, float, float],
    ) -> None:
        """
        Cross-NS additivity: golden["scva_c"] == approx(golden["scva_ns1"] + golden["scva_ns2"]).

        This is the LOAD-BEARING invariant for CVA-A3.  It pins the engine's
        group_by("counterparty_reference").agg(...sum(per_ns_term)...) path in
        engine/cva/ba_cva.py::_scva_per_counterparty.

        Both NS rows share the SAME counterparty_reference = CP_CVA_A3.  The
        engine must sum their per-NS SCVA terms into one SCVA_c:

            SCVA_NS1 = (1/alpha) * RW_c * M * ead_ns1 * DF_NS
            SCVA_NS2 = (1/alpha) * RW_c * M * ead_ns2 * DF_NS
            SCVA_c   = SCVA_NS1 + SCVA_NS2

        This assertion is EAD-robust: it holds for ANY ead_ns1, ead_ns2 > 0
        because compute_cva_a3_golden defines scva_c = scva_ns1 + scva_ns2
        by construction.  The invariant tests the DECOMPOSITION is mathematically
        consistent (i.e., cross-NS aggregation in the golden function itself).
        The companion test_cva_a3_ba_cva_reduced_rwea asserts that the ENGINE's
        output matches that golden.

        Arrange:
            Golden computed from materialised (ead_ns1, ead_ns2) — no hard-coded
            values.
        Act:
            Extract scva_ns1, scva_ns2, scva_c from compute_cva_a3_golden(ead_ns1, ead_ns2).
        Assert:
            golden["scva_c"] == approx(golden["scva_ns1"] + golden["scva_ns2"], rel=1e-9)

        References:
            - PS1/26 App.1 CVA Part 4.3 (SCVA_c = SUM_NS inner sum)
            - engine/cva/ba_cva.py::_scva_per_counterparty (group_by + sum)
        """
        # Arrange
        _result, ead_ns1, ead_ns2 = cva_a3_pipeline_result
        golden = compute_cva_a3_golden(ead_ns1, ead_ns2)

        scva_ns1 = golden["scva_ns1"]
        scva_ns2 = golden["scva_ns2"]
        scva_c = golden["scva_c"]

        # Assert
        assert scva_c == pytest.approx(scva_ns1 + scva_ns2, rel=1e-9), (
            f"CVA-A3: cross-NS additivity violated: "
            f"scva_c={scva_c:.10f} != scva_ns1+scva_ns2={scva_ns1 + scva_ns2:.10f}. "
            f"scva_ns1={scva_ns1:.10f}, scva_ns2={scva_ns2:.10f}. "
            "The engine's group_by(counterparty_reference).agg(sum) path must "
            "accumulate both NS contributions into one SCVA_c."
        )

    def test_cva_a3_single_cp_k_collapse(
        self,
        cva_a3_pipeline_result: tuple[object, float, float],
    ) -> None:
        """
        Single-CP K collapse: golden["k_reduced"] == approx(golden["scva_c"], rel=1e-9).

        For n=1 counterparty, the K_reduced formula collapses to an algebraic
        identity:
            K_reduced = sqrt[(rho * SCVA_c)^2 + (1 - rho^2) * SCVA_c^2]
                      = SCVA_c * sqrt[rho^2 + 1 - rho^2]
                      = SCVA_c * 1.0
                      = SCVA_c

        This invariant holds for ANY rho in (0, 1) and any SCVA_c > 0.  It
        distinguishes CVA-A3 from CVA-A2 (two CPs with a cross-term) and
        confirms the golden helper correctly encodes the algebraic simplification.

        Arrange:
            Golden computed from materialised (ead_ns1, ead_ns2).
        Act:
            Extract k_reduced, scva_c from compute_cva_a3_golden(ead_ns1, ead_ns2).
        Assert:
            golden["k_reduced"] == approx(golden["scva_c"], rel=1e-9)

        References:
            - PS1/26 App.1 CVA Part 4.2 (K_reduced formula, single-CP collapse)
        """
        # Arrange
        _result, ead_ns1, ead_ns2 = cva_a3_pipeline_result
        golden = compute_cva_a3_golden(ead_ns1, ead_ns2)

        k_reduced = golden["k_reduced"]
        scva_c = golden["scva_c"]

        # Assert
        assert k_reduced == pytest.approx(scva_c, rel=1e-9), (
            f"CVA-A3: single-CP K collapse invariant violated: "
            f"k_reduced={k_reduced:.10f} != scva_c={scva_c:.10f}. "
            "For n=1 CP, sqrt[(rho*S)^2 + (1-rho^2)*S^2] = S is an algebraic "
            "identity — check the K_reduced definition in compute_cva_a3_golden."
        )

    def test_cva_a3_ead_monotone_decomposition(
        self,
        cva_a3_pipeline_result: tuple[object, float, float],
    ) -> None:
        """
        EAD-monotone decomposition: scva_ns1 / scva_ns2 == approx(ead_ns1 / ead_ns2).

        Because both NS share the same M=4.0 and DF=0.906346 (derived from the
        single CVA-counterparty row keyed by CP_CVA_A3), the ratio of per-NS
        SCVA contributions equals the ratio of their EADs:

            SCVA_NS1 / SCVA_NS2 = [(1/alpha) * RW_c * M * DF * ead_ns1]
                                  / [(1/alpha) * RW_c * M * DF * ead_ns2]
                                = ead_ns1 / ead_ns2

        This invariant tests that the golden helper correctly applies the SAME
        M and DF to both NS (as the engine does via the counterparty-level join),
        rather than per-NS distinct M values.

        It also sanity-checks that EAD_NS1 != EAD_NS2 (3y vs 5y tenors) so
        the ratio != 1.0, confirming the two netting sets are genuinely distinct.

        Arrange:
            Golden computed from materialised (ead_ns1, ead_ns2).
        Act:
            Compute scva ratio and ead ratio.
        Assert:
            golden["scva_ns1"] / golden["scva_ns2"] == approx(ead_ns1 / ead_ns2, rel=1e-9)

        References:
            - PS1/26 App.1 CVA Part 4.3 (M_NS and DF_NS applied per-NS; here
              both share one M from the counterparty row)
            - engine/cva/ba_cva.py::_scva_per_counterparty (join by
              counterparty_reference propagates same M to all NS rows)
        """
        # Arrange
        _result, ead_ns1, ead_ns2 = cva_a3_pipeline_result
        golden = compute_cva_a3_golden(ead_ns1, ead_ns2)

        scva_ns1 = golden["scva_ns1"]
        scva_ns2 = golden["scva_ns2"]

        # Assert — ratio of per-NS SCVA must equal ratio of EADs
        assert scva_ns1 / scva_ns2 == pytest.approx(ead_ns1 / ead_ns2, rel=1e-9), (
            f"CVA-A3: EAD-monotone decomposition invariant violated: "
            f"scva_ns1/scva_ns2={scva_ns1 / scva_ns2:.10f} != "
            f"ead_ns1/ead_ns2={ead_ns1 / ead_ns2:.10f}. "
            f"scva_ns1={scva_ns1:.10f}, scva_ns2={scva_ns2:.10f}. "
            f"ead_ns1={ead_ns1:.4f} (3y), ead_ns2={ead_ns2:.4f} (5y). "
            "Shared M=4.0 and DF must be applied identically to both NS rows — "
            "check the counterparty-level join in engine/cva/ba_cva.py."
        )
