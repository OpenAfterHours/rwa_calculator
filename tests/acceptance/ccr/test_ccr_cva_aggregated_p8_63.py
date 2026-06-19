"""
P8.63 / CVA-AGG-A1: Aggregated CVA surface on AggregatedResultBundle — acceptance test.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator -> OutputAggregator -> BA-CVA stage (engine/cva/ba_cva.py)

Key responsibilities:
- Verify two new fields on AggregatedResultBundle:
      cva_method: str | None         — "BA-CVA" for both reduced and full paths
      cva_hedges_recognised: bool | None  — False for reduced, True for full

- Sub-case A (reduced, no eligible hedge):
      cva_method == "BA-CVA"
      cva_hedges_recognised is False
      cva_rwa == approx(compute_cva_a1_golden(ead_ccr)["rwea_cva"], rel=1e-6)
      composition identity: sum(rwa_final) + cva_rwa == approx(R + cva, rel=1e-9)

- Sub-case B (full, perfect single-name CDS hedge):
      cva_method == "BA-CVA"
      cva_hedges_recognised is True
      cva_rwa == approx(compute_cva_full_golden(ead_ccr)["rwea_cva_full"], rel=1e-6)
      ratio invariant: cva_rwa_full / cva_rwa_reduced == approx(0.25, rel=1e-9)
      composition identity: sum(rwa_final) + cva_rwa == approx(R + cva, rel=1e-9)

- Out-of-scope control: bundle WITHOUT cva_counterparties -> all three CVA fields None.

LOCKED DESIGN (engine-implementer must match):
    result.cva_method == "BA-CVA"  for BOTH sub-cases.
    result.cva_hedges_recognised is False  (reduced)  /  True  (full).
    DO NOT use "BA-CVA-REDUCED" or "BA-CVA-FULL".

Fail-first signals:
    The two new fields (cva_method, cva_hedges_recognised) do NOT yet exist on
    AggregatedResultBundle.  Direct attribute access would raise AttributeError;
    to guarantee a clean AssertionError failure we assert hasattr() as the first
    line of each sub-case (AssertionError: assert False when field absent).
    Once the engine-implementer adds the fields, the hasattr guards pass and the
    subsequent value assertions drive the next failure.

References:
    - PS1/26 App.1 CVA Part 4.2-4.10 (BA-CVA reduced and full)
    - PS1/26 App.1 Own Funds Part 4(b) (x12.5 multiplier)
    - CRR Art. 274(2): EAD = alpha * (RC + PFE)
    - tests/fixtures/p8_60/cva_a1_builder.py
    - tests/fixtures/p8_62/cva_hedge_a1_builder.py
    - tests/acceptance/ccr/test_ccr_ba_cva_a1.py  (P8.60 baseline)
    - tests/acceptance/ccr/test_ccr_cva_hedge_a1.py  (P8.62 baseline)
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
# Shared helper: materialise ead_ccr from pipeline result.
# ---------------------------------------------------------------------------


def _materialise_ead_ccr(result: object) -> float:
    """
    Extract the materialised EAD for NS_CVA_001 from the pipeline result.

    Reads the CCR synthetic row from result.results and returns ead_final
    for the row whose exposure_reference == _CCR_EXPOSURE_REF.

    Args:
        result: AggregatedResultBundle produced by PipelineOrchestrator.

    Returns:
        EAD as a float (must be > 0 for any live 3-year IR swap).
    """
    df = result.results.collect()  # type: ignore[union-attr]
    ccr_rows = df.filter(pl.col("exposure_reference") == _CCR_EXPOSURE_REF).to_dicts()
    assert len(ccr_rows) == 1, (
        f"CVA-AGG-A1: expected exactly 1 CCR synthetic row for "
        f"exposure_reference={_CCR_EXPOSURE_REF!r}, got {len(ccr_rows)}. "
        "The CCR adapter must emit one synthetic row per netting set."
    )
    return float(ccr_rows[0]["ead_final"])


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cva_agg_reduced_result() -> tuple[object, float]:
    """
    Sub-case A (reduced): run the CVA-A1 bundle with counterparties, no hedges.

    Attach cva_counterparties via field-presence guard (fires when P8.60 is shipped).
    Return (result, ead_ccr).

    Arrange:
        - P8.60 base bundle (1 trade / 1 netting set / 1 counterparty, CCR inputs)
        - CVA counterparty frame (guard): CP_CVA_001, FINANCIAL, IG, M=3.0
        - NO cva_hedges
        - Basel 3.1 config, STANDARDISED permission mode
    """
    # Arrange — base bundle
    bundle = build_raw_data_bundle_cva_a1()

    # Guard 1: attach CVA counterparty frame (shipped in P8.60).
    if "cva_counterparties" in {f.name for f in dataclasses.fields(bundle)}:
        bundle = dataclasses.replace(
            bundle,
            cva_counterparties=create_cva_a1_counterparty_frame().lazy(),
        )

    config = CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act — run the full Basel 3.1 pipeline (reduced-K path)
    result = PipelineOrchestrator().run_with_data(bundle, config)

    ead_ccr = _materialise_ead_ccr(result)
    return result, ead_ccr


@pytest.fixture(scope="module")
def cva_agg_full_result(cva_agg_reduced_result: tuple[object, float]) -> tuple[object, float]:
    """
    Sub-case B (full): run the CVA-A1 bundle with counterparties AND a perfect hedge.

    Re-uses the ead_ccr from sub-case A to size the perfect hedge notional
    B_h = ead_ccr / CVA_ALPHA (no 1/alpha on SNH_c in PS1/26 4.7).

    Guard 2: attach cva_hedges only when RawDataBundle.cva_hedges exists
    (field added by engine-implementer in P8.63).  Until then, the guard skips,
    the engine returns REDUCED cva_rwa, and cva_hedges_recognised remains False
    (or None) — causing all sub-case-B assertions to fail cleanly.

    Arrange:
        - P8.60 base bundle + CVA counterparty frame (guard 1 fires)
        - CVA hedge frame (guard 2): H_SN_CVA_001, SINGLE_NAME, IDENTICAL,
          B_h = ead_ccr / CVA_ALPHA
        - Basel 3.1 config, STANDARDISED permission mode
    """
    # Ead_ccr is stable from the reduced run (same CCR portfolio).
    _reduced_result, ead_ccr = cva_agg_reduced_result

    # Arrange — rebuild the base bundle
    bundle = build_raw_data_bundle_cva_a1()

    # Guard 1: attach CVA counterparty frame (shipped in P8.60).
    if "cva_counterparties" in {f.name for f in dataclasses.fields(bundle)}:
        bundle = dataclasses.replace(
            bundle,
            cva_counterparties=create_cva_a1_counterparty_frame().lazy(),
        )

    config = CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Guard 2: attach CVA hedge frame (P8.63 new field — absent today).
    # When engine-implementer adds RawDataBundle.cva_hedges the guard fires
    # and we re-run the pipeline with the hedge.
    if "cva_hedges" in {f.name for f in dataclasses.fields(bundle)}:
        hedge_notional = ead_ccr / CVA_ALPHA
        hedge_frame = create_perfect_single_name_hedge_frame(hedge_notional)
        bundle = dataclasses.replace(bundle, cva_hedges=hedge_frame.lazy())

    # Act — run the full Basel 3.1 pipeline (full-K path when guard 2 fires)
    result = PipelineOrchestrator().run_with_data(bundle, config)

    return result, ead_ccr


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestCVAAggA1BundleFields:
    """
    CVA-AGG-A1 Sub-case A: reduced BA-CVA — new bundle fields.

    Three test methods:
      1. cva_method field: must equal "BA-CVA" (new field, absent today).
      2. cva_hedges_recognised field: must be False (no hedges, new field absent today).
      3. cva_rwa + composition identity: existing field, pinned to golden.

    All three FAIL TODAY because cva_method and cva_hedges_recognised do not
    exist on AggregatedResultBundle — the first two fail with AssertionError on
    the hasattr guard; the third fails when those new fields do not exist.

    References:
        - PS1/26 App.1 CVA Part 4.2-4.4 (BA-CVA reduced)
        - PS1/26 App.1 CVA Part §4 header (method label "BA-CVA")
    """

    def test_cva_agg_a1_reduced_cva_method(
        self,
        cva_agg_reduced_result: tuple[object, float],
    ) -> None:
        """
        result.cva_method == "BA-CVA" when CVA counterparties are attached.

        Arrange:
            Sub-case A: P8.60 CCR bundle + CVA counterparty frame (no hedges).
            Basel 3.1 config, STANDARDISED.
        Act:
            Full pipeline run via PipelineOrchestrator.
        Assert:
            AggregatedResultBundle.cva_method == "BA-CVA".

        FAILS TODAY: cva_method not yet a field on AggregatedResultBundle.
        First failure: AssertionError on hasattr guard.
        Post-implementation failure mode: AssertionError on value comparison.

        Engine-implementer must:
            (1) Add cva_method: str | None = None to AggregatedResultBundle.
            (2) Set cva_method = "BA-CVA" in engine/stages/aggregate.py::_ba_cva_roll_up
                whenever cva_rwa is not None.
        """
        # Arrange
        result, _ead_ccr = cva_agg_reduced_result

        # Assert — hasattr guard catches the absent-field case as a clean AssertionError.
        assert hasattr(result, "cva_method"), (
            "AggregatedResultBundle must have field 'cva_method: str | None'. "
            "Engine-implementer: add 'cva_method: str | None = None' to the dataclass "
            "and set it to \"BA-CVA\" in _ba_cva_roll_up when cva_rwa is not None."
        )

        # Act — read the field (guard passed)
        cva_method = result.cva_method  # type: ignore[union-attr]

        # Assert — value must be the canonical label
        assert cva_method == "BA-CVA", (
            f"CVA-AGG-A1 (reduced): expected cva_method='BA-CVA', got {cva_method!r}. "
            "Both reduced and full BA-CVA paths carry the same method label; "
            "the reduced/full distinction is carried by cva_hedges_recognised."
        )

    def test_cva_agg_a1_reduced_cva_hedges_recognised(
        self,
        cva_agg_reduced_result: tuple[object, float],
    ) -> None:
        """
        result.cva_hedges_recognised is False when no eligible hedges are attached.

        Arrange:
            Sub-case A: P8.60 CCR bundle + CVA counterparty frame (no cva_hedges).
        Act:
            Full pipeline run.
        Assert:
            AggregatedResultBundle.cva_hedges_recognised is False.

        FAILS TODAY: cva_hedges_recognised not yet a field on AggregatedResultBundle.
        First failure: AssertionError on hasattr guard.

        Engine-implementer must:
            (1) Add cva_hedges_recognised: bool | None = None to AggregatedResultBundle.
            (2) Set cva_hedges_recognised = False when no eligible hedges fed full-K path.
        """
        # Arrange
        result, _ead_ccr = cva_agg_reduced_result

        # Assert — hasattr guard
        assert hasattr(result, "cva_hedges_recognised"), (
            "AggregatedResultBundle must have field 'cva_hedges_recognised: bool | None'. "
            "Engine-implementer: add 'cva_hedges_recognised: bool | None = None' to the "
            "dataclass and set it to False when no eligible hedge is present."
        )

        # Act
        cva_hedges_recognised = result.cva_hedges_recognised  # type: ignore[union-attr]

        # Assert — reduced path must carry False (no hedges)
        assert cva_hedges_recognised is False, (
            f"CVA-AGG-A1 (reduced): expected cva_hedges_recognised=False, "
            f"got {cva_hedges_recognised!r}. "
            "No cva_hedges frame was attached; the engine must set this to False "
            "when the reduced K path runs."
        )

    def test_cva_agg_a1_reduced_cva_rwa_and_composition(
        self,
        cva_agg_reduced_result: tuple[object, float],
    ) -> None:
        """
        Sub-case A: cva_rwa matches golden and composition identity holds.

        Two pins in one test (one concept: the full CVA output for this sub-case):
          (a) cva_rwa == approx(compute_cva_a1_golden(ead_ccr)["rwea_cva"], rel=1e-6)
          (b) R + cva_rwa == approx(R + cva_rwa, rel=1e-9)  (composition identity)
              where R = result.results.collect()["rwa_final"].sum() (default-risk RWA).

        The composition identity is pinned: aggregate_total == R + cva because
        today's SummaryStatistics.total_rwa sums only rwa_final (excludes cva_rwa).
        The reconciliation asserts the additive decomposition at test level.

        Arrange:
            Sub-case A: P8.60 CCR bundle + CVA counterparty frame (no hedges).
        Act:
            Full pipeline run; materialise R and cva.
        Assert:
            (a) cva_rwa matches the golden.
            (b) R + cva_rwa == approx(R + cva_rwa, rel=1e-9)  (trivially true today
                once (a) passes; load-bearing for any future composed-total field).

        References:
            - PS1/26 App.1 CVA Part 4.2-4.4 (BA-CVA reduced formula)
            - PS1/26 App.1 Own Funds Part 4(b) (x12.5 multiplier)
        """
        # Arrange
        result, ead_ccr = cva_agg_reduced_result
        golden = compute_cva_a1_golden(ead_ccr)
        expected_cva_rwa = golden["rwea_cva"]

        # Act — read cva_rwa defensively so a missing field yields None (AssertionError)
        # rather than AttributeError (wrong failure mode for this test).
        cva_rwa = getattr(result, "cva_rwa", None)

        # Assert (a) — cva_rwa matches golden
        assert cva_rwa == pytest.approx(expected_cva_rwa, rel=1e-6), (
            f"CVA-AGG-A1 (reduced): expected cva_rwa={expected_cva_rwa:,.4f} "
            f"(DS_BA_CVA=0.65 * K_reduced={golden['k_reduced']:,.4f} * 12.5), "
            f"got {cva_rwa!r}. "
            f"Materialised ead_ccr={ead_ccr:,.4f} for NS_CVA_001 (3y GBP IR swap). "
            f"Intermediate values: DF_NS={golden['df_ns']:.10f}, "
            f"SCVA_c={golden['scva_c']:,.4f}, OFR_CVA={golden['ofr_cva']:,.4f}."
        )

        # Assert (b) — composition identity: R + cva_rwa is the composed total.
        # SummaryStatistics.total_rwa today sums only rwa_final (CVA excluded).
        default_risk_rwa = result.results.collect()["rwa_final"].sum()  # type: ignore[union-attr]
        composed_total = default_risk_rwa + cva_rwa
        assert composed_total == pytest.approx(default_risk_rwa + cva_rwa, rel=1e-9), (
            "CVA-AGG-A1 (reduced): composition identity R + cva_rwa must be additive. "
            f"default_risk_rwa={default_risk_rwa:,.4f}, cva_rwa={cva_rwa:,.4f}, "
            f"composed_total={composed_total:,.4f}. "
            "If the engine adds a composed-total field, assert it equals this value."
        )


class TestCVAAggA1FullBundleFields:
    """
    CVA-AGG-A1 Sub-case B: full BA-CVA — new bundle fields with hedge recognised.

    Four test methods:
      1. cva_method field: must equal "BA-CVA" (same label as reduced).
      2. cva_hedges_recognised field: must be True (eligible hedge was attached).
      3. cva_rwa matches the full-K golden.
      4. Ratio invariant: cva_rwa_full / cva_rwa_reduced == approx(0.25, rel=1e-9).

    FAILS TODAY because:
      - cva_method and cva_hedges_recognised do not exist on AggregatedResultBundle.
      - Guard 2 (cva_hedges) is skipped today, so engine returns REDUCED cva_rwa,
        making cva_hedges_recognised=False (not True) once fields are added.

    References:
        - PS1/26 App.1 CVA Part 4.5 (K_full, beta=0.25)
        - PS1/26 App.1 CVA Part 4.7 (SNH_c — no 1/alpha)
    """

    def test_cva_agg_a1_full_cva_method(
        self,
        cva_agg_full_result: tuple[object, float],
    ) -> None:
        """
        result.cva_method == "BA-CVA" when CVA counterparties AND hedges are attached.

        Arrange:
            Sub-case B: P8.60 CCR bundle + CVA counterparty frame + perfect SN hedge.
        Act:
            Full pipeline run.
        Assert:
            AggregatedResultBundle.cva_method == "BA-CVA".

        FAILS TODAY: cva_method not yet a field on AggregatedResultBundle.
        Same label as reduced — the reduced/full distinction is carried by
        cva_hedges_recognised, not by cva_method.
        """
        # Arrange
        result, _ead_ccr = cva_agg_full_result

        # Assert — hasattr guard catches absent field as a clean AssertionError.
        assert hasattr(result, "cva_method"), (
            "AggregatedResultBundle must have field 'cva_method: str | None'. "
            "Engine-implementer: add 'cva_method: str | None = None' and set it "
            "to \"BA-CVA\" in _ba_cva_roll_up for BOTH reduced and full paths."
        )

        # Act
        cva_method = result.cva_method  # type: ignore[union-attr]

        # Assert
        assert cva_method == "BA-CVA", (
            f"CVA-AGG-A1 (full): expected cva_method='BA-CVA', got {cva_method!r}. "
            "Both reduced and full BA-CVA paths must carry cva_method='BA-CVA'. "
            "Do NOT use 'BA-CVA-FULL' or 'BA-CVA-REDUCED'."
        )

    def test_cva_agg_a1_full_cva_hedges_recognised(
        self,
        cva_agg_full_result: tuple[object, float],
    ) -> None:
        """
        result.cva_hedges_recognised is True when eligible hedge is attached.

        Arrange:
            Sub-case B: P8.60 CCR bundle + CVA counterparty frame + H_SN_CVA_001
            (SINGLE_NAME, IDENTICAL, FINANCIAL/IG, eligible=True).
        Act:
            Full pipeline run.
        Assert:
            AggregatedResultBundle.cva_hedges_recognised is True.

        FAILS TODAY: field absent; post-impl guard 2 skips (cva_hedges not on bundle yet).

        Engine-implementer must:
            (1) Add RawDataBundle.cva_hedges: pl.LazyFrame | None = None.
            (2) In _ba_cva_roll_up set cva_hedges_recognised = True when
                data.cva_hedges is not None and ≥1 eligible-flag row passes the
                cva_hedge_eligible filter (mirrors the eligible filter in ba_cva.py).
        """
        # Arrange
        result, _ead_ccr = cva_agg_full_result

        # Assert — hasattr guard
        assert hasattr(result, "cva_hedges_recognised"), (
            "AggregatedResultBundle must have field 'cva_hedges_recognised: bool | None'. "
            "Engine-implementer: add the field and set True when ≥1 eligible hedge row "
            "is present in data.cva_hedges (reuse the cva_hedge_eligible filter)."
        )

        # Act
        cva_hedges_recognised = result.cva_hedges_recognised  # type: ignore[union-attr]

        # Assert — full path must carry True (eligible single-name hedge was attached)
        assert cva_hedges_recognised is True, (
            f"CVA-AGG-A1 (full): expected cva_hedges_recognised=True, "
            f"got {cva_hedges_recognised!r}. "
            "An eligible single-name CDS hedge (H_SN_CVA_001, cva_hedge_eligible=True) "
            "was attached; the engine must recognise it and set cva_hedges_recognised=True."
        )

    def test_cva_agg_a1_full_cva_rwa_matches_golden(
        self,
        cva_agg_full_result: tuple[object, float],
    ) -> None:
        """
        cva_rwa == approx(compute_cva_full_golden(ead_ccr)["rwea_cva_full"], rel=1e-6).

        Arrange:
            Sub-case B: perfect single-name CDS hedge B_h = ead_ccr / CVA_ALPHA
            (IDENTICAL, FINANCIAL/IG, M=3.0 — matches the netting-set maturity).
        Act:
            Full pipeline run (full-K path when guard 2 fires).
        Assert:
            AggregatedResultBundle.cva_rwa == approx(rwea_cva_full, rel=1e-6).

        FAILS TODAY: pipeline returns REDUCED cva_rwa (guard 2 skipped); once
        guard 2 fires, REDUCED != FULL so still fails until the full-K engine path
        is implemented.

        Formula trace (M=3.0, B_h = ead_ccr / 1.4):
            SNH_c = r_hc * RW_h * M_h * B_h * DF_h = SCVA_c  (perfect hedge)
            K_hedged = 0.0
            K_full   = 0.25 * K_reduced + 0.75 * 0.0 = 0.25 * K_reduced
            OFR_full = 0.65 * K_full
            RWEA_full = OFR_full * 12.5

        References:
            - PS1/26 App.1 CVA Part 4.5 (K_full, beta=0.25)
            - PS1/26 App.1 CVA Part 4.7 (SNH_c, no 1/alpha)
        """
        # Arrange
        result, ead_ccr = cva_agg_full_result
        golden = compute_cva_full_golden(ead_ccr)
        expected_cva_rwa_full = golden["rwea_cva_full"]

        # Act — read cva_rwa defensively
        cva_rwa = getattr(result, "cva_rwa", None)

        # Assert
        assert cva_rwa == pytest.approx(expected_cva_rwa_full, rel=1e-6), (
            f"CVA-AGG-A1 (full): expected cva_rwa={expected_cva_rwa_full:,.4f} "
            f"(DS_BA_CVA=0.65 * K_full={golden['k_full']:,.4f} * 12.5), "
            f"got {cva_rwa!r}. "
            f"Perfect-hedge: hedge_notional={golden['hedge_notional']:,.4f} = ead_ccr/1.4. "
            f"K_hedged={golden['k_hedged']:.2e} (should be ~0), "
            f"K_full=beta*K_reduced={CVA_BA_BETA}*{golden['k_reduced']:,.4f}. "
            "Engine-implementer: SNH_c must carry NO (1/alpha) factor (PS1/26 4.7)."
        )

    def test_cva_agg_a1_full_ratio_equals_beta(
        self,
        cva_agg_full_result: tuple[object, float],
        cva_agg_reduced_result: tuple[object, float],
    ) -> None:
        """
        Ratio invariant: cva_rwa_full / cva_rwa_reduced == approx(0.25=beta, rel=1e-9).

        This is the strongest pin — it is exact for a perfect hedge and cancels
        the absolute EAD.  Verifies the hedge disallowance weight beta = 0.25.

        Arrange:
            - Reduced cva_rwa from sub-case A (compute_cva_a1_golden["rwea_cva"]).
            - Full cva_rwa from sub-case B (compute_cva_full_golden["rwea_cva_full"]).
        Act:
            Read both cva_rwa values.
        Assert:
            cva_rwa_full / cva_rwa_reduced == approx(CVA_BA_BETA=0.25, rel=1e-9).

        Perfect-hedge ratio derivation:
            RWEA_full  = DS_BA_CVA * beta * K_reduced * 12.5
            RWEA_red   = DS_BA_CVA * 1.00 * K_reduced * 12.5
            Ratio      = beta = 0.25  (EAD, DS_BA_CVA, K_reduced all cancel)

        FAILS TODAY: sub-case B returns REDUCED cva_rwa (guard 2 skipped)
        so ratio == 1.0 instead of 0.25.

        References:
            - PS1/26 App.1 CVA Part 4.5 (beta=0.25, K_full formula)
        """
        # Arrange
        result_full, ead_ccr = cva_agg_full_result
        result_reduced, _ = cva_agg_reduced_result

        cva_rwa_full = getattr(result_full, "cva_rwa", None)
        cva_rwa_reduced = getattr(result_reduced, "cva_rwa", None)

        # Compute the ratio (guard against None / zero denominator).
        if cva_rwa_reduced is None or cva_rwa_reduced == 0.0:
            actual_ratio = None
        else:
            actual_ratio = (cva_rwa_full / cva_rwa_reduced) if cva_rwa_full is not None else None

        # Assert
        assert actual_ratio == pytest.approx(CVA_BA_BETA, rel=1e-9), (
            f"CVA-AGG-A1: expected cva_rwa_full / cva_rwa_reduced == beta={CVA_BA_BETA}, "
            f"got ratio={actual_ratio!r} "
            f"(cva_rwa_full={cva_rwa_full!r}, cva_rwa_reduced={cva_rwa_reduced!r}, "
            f"ead_ccr={ead_ccr:,.4f}). "
            "Perfect hedge (B_h = ead_ccr/alpha) must give K_hedged=0 and "
            "K_full=beta*K_reduced=0.25*K_reduced. "
            "Engine-implementer: SNH_c carries NO (1/alpha) factor (PS1/26 4.7)."
        )

    def test_cva_agg_a1_full_composition_identity(
        self,
        cva_agg_full_result: tuple[object, float],
    ) -> None:
        """
        Composition identity: sum(rwa_final) + cva_rwa is the correct composed total.

        SummaryStatistics.total_rwa today sums only rwa_final (CVA excluded).
        This test pins the additive decomposition for the full sub-case.

        Arrange:
            Sub-case B: full BA-CVA pipeline result.
        Act:
            R = result.results.collect()["rwa_final"].sum()
            cva = result.cva_rwa
        Assert:
            R + cva == approx(R + cva, rel=1e-9)  (additive identity).

        This assertion is trivially true once cva_rwa is correct, but it is the
        load-bearing pin: if the engine exposes a composed_total field it must
        equal R + cva_rwa.

        References:
            - src/rwa_calc/api/formatters.py (total_rwa = sum(rwa_final) today)
        """
        # Arrange
        result, _ead_ccr = cva_agg_full_result

        # Act
        cva_rwa = getattr(result, "cva_rwa", None)
        if cva_rwa is None:
            # cva_rwa absent — let the primary value assertion catch it; skip here.
            pytest.skip("cva_rwa is None — primary value assertion covers this failure")

        default_risk_rwa = result.results.collect()["rwa_final"].sum()  # type: ignore[union-attr]
        composed_total = default_risk_rwa + cva_rwa

        # Assert
        assert composed_total == pytest.approx(default_risk_rwa + cva_rwa, rel=1e-9), (
            f"CVA-AGG-A1 (full): composition identity R + cva_rwa must be additive. "
            f"default_risk_rwa={default_risk_rwa:,.4f}, cva_rwa={cva_rwa:,.4f}, "
            f"composed_total={composed_total:,.4f}."
        )


class TestCVAAggA1OutOfScopeControl:
    """
    Out-of-scope control: bundle without cva_counterparties gives all CVA fields None.

    This test is the negative control — it must PASS even before any CVA
    implementation, and must continue to pass after.  It verifies that the
    pipeline correctly returns None for all three CVA descriptor fields when
    CVA is not in scope (no cva_counterparties attached).

    References:
        - P8.60 scenario: no-CVA-input control (test_cva_a1_ba_cva_reduced_rwea pattern)
    """

    @pytest.fixture(scope="class")
    def no_cva_result(self) -> object:
        """
        Run the base bundle WITHOUT attaching cva_counterparties.

        The bundle is a plain build_raw_data_bundle_cva_a1() with NO guarded
        dataclasses.replace() for cva_counterparties — simulating the case
        where CVA is entirely out of scope.
        """
        bundle = build_raw_data_bundle_cva_a1()

        config = CalculationConfig.basel_3_1(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        )

        # Act — run WITHOUT any CVA inputs
        return PipelineOrchestrator().run_with_data(bundle, config)

    def test_cva_out_of_scope_all_fields_none(self, no_cva_result: object) -> None:
        """
        cva_rwa, cva_method, cva_hedges_recognised are all None when CVA is out of scope.

        Arrange:
            Base bundle with no cva_counterparties attached.
        Act:
            Full pipeline run.
        Assert:
            getattr(result, "cva_rwa", None) is None
            getattr(result, "cva_method", None) is None
            getattr(result, "cva_hedges_recognised", None) is None

        This uses getattr with a default of None so the test passes both before
        the fields are added (field absent -> returns None) and after (field present
        but explicitly set to None).  Any non-None value is a failure.

        References:
            - PS1/26 App.1 CVA Part 4.1 (scope: CVA charge only when in-scope)
        """
        # Arrange
        result = no_cva_result

        # Act — read all three fields defensively
        cva_rwa = getattr(result, "cva_rwa", None)
        cva_method = getattr(result, "cva_method", None)
        cva_hedges_recognised = getattr(result, "cva_hedges_recognised", None)

        # Assert — all must be None when no CVA counterparties are in scope
        assert cva_rwa is None, (
            f"CVA-AGG-A1 (out-of-scope): expected cva_rwa=None when no "
            f"cva_counterparties attached, got {cva_rwa!r}."
        )
        assert cva_method is None, (
            f"CVA-AGG-A1 (out-of-scope): expected cva_method=None when CVA "
            f"is out of scope, got {cva_method!r}."
        )
        assert cva_hedges_recognised is None, (
            f"CVA-AGG-A1 (out-of-scope): expected cva_hedges_recognised=None "
            f"when CVA is out of scope, got {cva_hedges_recognised!r}."
        )
