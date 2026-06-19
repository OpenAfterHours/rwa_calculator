"""
P8.60 / CVA-A1: BA-CVA reduced-K vertical slice — acceptance test.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator -> OutputAggregator -> BA-CVA stage (engine/cva/ba_cva.py)

Key responsibilities:
- Run the CVA-A1 fixture (single counterparty CP_CVA_001 / netting set
  NS_CVA_001, one 3-year GBP IR swap) through the Basel 3.1 SA+CCR pipeline.
- Materialise ead_ccr from the CCR synthetic row for NS_CVA_001.
- Derive the expected cva_rwa from the materialised ead_ccr via
  compute_cva_a1_golden(ead_ccr) — golden is NOT hard-coded.
- Assert AggregatedResultBundle.cva_rwa == approx(golden["rwea_cva"]).
- Assert no-CVA-input control: cva_rwa is None or 0.0 when no CVA
  counterparties are supplied.

Input / Output contract the engine-implementer must satisfy:
    INPUT:
        - RawDataBundle gains a new optional field:
              cva_counterparties: pl.LazyFrame | None = None
          Schema (CVA_COUNTERPARTY_SCHEMA) — columns:
              counterparty_reference        String   FK to netting set's
                                                      counterparty_reference
              cva_rw_sector                 String   sector key (e.g. "FINANCIAL")
              cva_rw_rating_band            String   "IG" or "HY_NR"
              cva_effective_maturity_years  Float64  M_NS in years
              cva_in_scope                  Boolean  flags BA-CVA scope

    OUTPUT:
        - AggregatedResultBundle gains a new optional field:
              cva_rwa: float | None = None
          Semantics: RWEA_CVA = DS_BA_CVA(0.65) * K_reduced * 12.5
              where K_reduced collapses to SCVA_c for a single counterparty.

    FORMULA (PS1/26 App.1 CVA Part):
        DF_NS     = (1 - exp(-0.05 * M)) / (0.05 * M)
        SCVA_c    = (1/1.4) * RW_c * M_NS * EAD_NS * DF_NS
        K_reduced = sqrt[(0.5 * SCVA_c)^2 + (1 - 0.5^2) * SCVA_c^2]
                  = SCVA_c  (collapses to identity for n=1)
        OFR_CVA   = 0.65 * K_reduced
        RWEA_CVA  = OFR_CVA * 12.5

    HOW THE CVA FRAME REACHES THE PIPELINE:
        This test attaches the frame to the bundle itself using a
        field-presence-guarded dataclasses.replace().  When
        RawDataBundle.cva_counterparties does not yet exist the guard
        silently skips the attach, the pipeline runs without it,
        getattr(result, "cva_rwa", None) returns None, and the assertion
        fails cleanly (AssertionError).  Once the engine-implementer adds
        RawDataBundle.cva_counterparties in src/, the guard fires, the
        frame is attached, and the CVA stage can compute cva_rwa.

References:
    - PS1/26 App.1 CVA Part 4.2 (K_reduced, DS_BA_CVA=0.65, rho=50%)
    - PS1/26 App.1 CVA Part 4.3 (SCVA_c, DF formula, alpha=1.4)
    - PS1/26 App.1 CVA Part 4.4 (RW table — Financials IG = 5.0%)
    - PS1/26 App.1 Own Funds Part 4(b) (x12.5 multiplier)
    - CRR Art. 274(2): EAD = alpha * (RC + PFE)
    - tests/fixtures/p8_60/cva_a1_builder.py
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
    build_raw_data_bundle_cva_a1,
    compute_cva_a1_golden,
    create_cva_a1_counterparty_frame,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Basel 3.1 effective date (PS1/26 — 1 Jan 2027).
_REPORTING_DATE = date(2027, 1, 15)

# Synthetic exposure reference for NS_CVA_001 produced by the CCR adapter.
_CCR_EXPOSURE_REF = f"ccr__{CVA_A1_NETTING_SET_ID}"  # "ccr__NS_CVA_001"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cva_a1_pipeline_result() -> tuple[object, float]:
    """
    Run the CVA-A1 bundle through the Basel 3.1 SA+CCR pipeline.

    Returns a 2-tuple: (AggregatedResultBundle, ead_ccr) where ead_ccr is the
    materialised EAD for NS_CVA_001 from the CCR synthetic row.

    The CVA counterparty frame is attached to the bundle via a field-presence
    guard: if RawDataBundle.cva_counterparties already exists (added by the
    engine-implementer in src/) the guard fires and attaches the frame so the
    CVA stage can compute cva_rwa.  Until that field is added the guard skips
    the attach, the pipeline runs without CVA input, and getattr(result,
    "cva_rwa", None) returns None — causing the primary assertion to fail
    cleanly with AssertionError.

    Arrange:
        - 1 trade T_CVA_001: 3y GBP IR swap, notional GBP 100m, MtM=0, delta=1
        - 1 netting set NS_CVA_001: CP_CVA_001, enforceable, unmargined
        - CP_CVA_001: GB institution, CQS 2
        - External rating: S&P "A" = CQS 2
        - CVA counterparty frame (guarded): CP_CVA_001, FINANCIAL, IG, M=3.0, in_scope=True
        - Basel 3.1 config, STANDARDISED permission mode
    """
    # Arrange — base bundle (cva_counterparties absent today)
    bundle = build_raw_data_bundle_cva_a1()

    # Attach the CVA counterparty frame only when RawDataBundle already
    # declares the field.  This guard is the sole mechanism by which the
    # frame reaches the pipeline: no fixture file edit is required.
    if "cva_counterparties" in {f.name for f in dataclasses.fields(bundle)}:
        bundle = dataclasses.replace(
            bundle,
            cva_counterparties=create_cva_a1_counterparty_frame().lazy(),
        )

    config = CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act — run the full Basel 3.1 pipeline
    result = PipelineOrchestrator().run_with_data(bundle, config)

    # Materialise ead_ccr from the CCR synthetic row for NS_CVA_001
    df = result.results.collect()
    ccr_rows = df.filter(pl.col("exposure_reference") == _CCR_EXPOSURE_REF).to_dicts()
    assert len(ccr_rows) == 1, (
        f"CVA-A1: expected exactly 1 CCR synthetic row for "
        f"exposure_reference={_CCR_EXPOSURE_REF!r}, got {len(ccr_rows)}. "
        "The CCR adapter must emit one synthetic row per netting set."
    )
    ead_ccr: float = ccr_rows[0]["ead_final"]

    return result, ead_ccr


# ---------------------------------------------------------------------------
# CVA-A1 acceptance tests
# ---------------------------------------------------------------------------


class TestCVAA1BACVAReducedRWEA:
    """
    CVA-A1: BA-CVA reduced-K RWEA for a single counterparty.

    Two tests:
      1. PRIMARY: cva_rwa == approx(golden["rwea_cva"])
         Verifies the full BA-CVA reduced formula:
             RWEA_CVA = DS_BA_CVA * K_reduced * 12.5
         using the materialised ead_ccr from the 3-year IR swap.
         FAILS TODAY: AggregatedResultBundle has no cva_rwa field.

      2. CONTROL: ead_ccr is positive (SA-CCR pipeline is healthy).
         PASSES TODAY: confirms the CCR pipeline produces a valid EAD.

    References:
        - PS1/26 App.1 CVA Part 4.2-4.4 (BA-CVA reduced formula)
        - tests/fixtures/p8_60/cva_a1_builder.py (compute_cva_a1_golden)
    """

    def test_cva_a1_ba_cva_reduced_rwea(
        self,
        cva_a1_pipeline_result: tuple[object, float],
    ) -> None:
        """
        RWEA_CVA = DS_BA_CVA(0.65) * K_reduced * 12.5 matches the golden.

        Arrange:
            - CVA-A1 fixture: CP_CVA_001 (FINANCIAL, IG), NS_CVA_001
              (3y GBP IR swap), BA-CVA counterparty frame attached to
              RawDataBundle.cva_counterparties via guarded dataclasses.replace.
            - Golden derived from materialised ead_ccr via
              compute_cva_a1_golden(ead_ccr).
        Act:
            Full Basel 3.1 SA+CCR+CVA pipeline.
        Assert:
            AggregatedResultBundle.cva_rwa == approx(golden["rwea_cva"], rel=1e-6).

        Expected formula trace (M=3.0, EAD from pipeline):
            DF_NS     = (1 - e^(-0.05*3.0)) / (0.05*3.0) = 0.928613...
            SCVA_c    = (1/1.4) * 0.05 * 3.0 * ead_ccr * DF_NS
            K_reduced = SCVA_c  (single-CP identity: sqrt[rho^2 + 1 - rho^2] = 1)
            OFR_CVA   = 0.65 * K_reduced
            RWEA_CVA  = OFR_CVA * 12.5

        References:
            - PS1/26 App.1 CVA Part 4.2-4.4
            - CRR Art. 274(2): EAD = alpha * (RC + PFE)
        """
        # Arrange
        result, ead_ccr = cva_a1_pipeline_result
        golden = compute_cva_a1_golden(ead_ccr)
        expected_rwea = golden["rwea_cva"]

        # Act — read cva_rwa defensively so a missing field yields None
        # (AssertionError) rather than AttributeError (wrong failure mode).
        cva_rwa = getattr(result, "cva_rwa", None)

        # Assert
        assert cva_rwa == pytest.approx(expected_rwea, rel=1e-6), (
            f"CVA-A1: expected cva_rwa={expected_rwea:,.4f} "
            f"(DS_BA_CVA=0.65 * K_reduced={golden['k_reduced']:,.4f} * 12.5), "
            f"got {cva_rwa!r}. "
            f"Materialised ead_ccr={ead_ccr:,.4f} for NS_CVA_001 (3y GBP IR swap). "
            f"Intermediate values: DF_NS={golden['df_ns']:.10f}, "
            f"SCVA_c={golden['scva_c']:,.4f}, OFR_CVA={golden['ofr_cva']:,.4f}. "
            "Engine-implementer must add: "
            "(1) RawDataBundle.cva_counterparties: pl.LazyFrame | None = None, "
            "(2) AggregatedResultBundle.cva_rwa: float | None = None, "
            "(3) engine/cva/ba_cva.py implementing the BA-CVA reduced formula, "
            "(4) pack scalars DS_BA_CVA/rho/rate in packs/b31.py."
        )

    def test_cva_a1_ead_ccr_positive(
        self,
        cva_a1_pipeline_result: tuple[object, float],
    ) -> None:
        """
        Control: the CCR pipeline produces a positive EAD for NS_CVA_001.

        Arrange: 3y GBP IR swap, GBP 100m notional, unmargined, MtM=0.
        Act:     full Basel 3.1 SA+CCR pipeline.
        Assert:  ead_ccr > 0  (SA-CCR EAD formula produces a positive value).

        This control test passes today and confirms the CCR pipeline is
        healthy; the EAD it pins is the input to the CVA golden computation.

        References:
            - CRR Art. 274(2): EAD = alpha * (RC + PFE) > 0 for any live trade
              with a non-zero PFE add-on.
        """
        # Arrange
        _result, ead_ccr = cva_a1_pipeline_result

        # Assert
        assert ead_ccr > 0, (
            f"CVA-A1: ead_ccr must be positive for the 3-year GBP IR swap, "
            f"got {ead_ccr}. "
            "CRR Art. 274(2): EAD = alpha * (RC + PFE) where PFE > 0 for any "
            "live IR trade (supervisory factor SF_IR = 0.5%)."
        )
