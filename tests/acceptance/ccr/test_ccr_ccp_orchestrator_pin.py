"""
CCR-CCP-1 / CCR-CCP-2 / P8.39: apply_ccp_risk_weight wired into _run_ccr_stage.

Pipeline position:
    Loader -> HierarchyResolver -> CCRStage (apply_legal_enforceability_gate
    -> apply_wwr_gate -> **apply_ccp_risk_weight** -> ccr_rows_to_exposures)
    -> Classifier -> CRM -> SA Calculator -> OutputAggregator

Key responsibilities:
- Prove that apply_ccp_risk_weight is called in _run_ccr_stage in pipeline.py,
  keyed on counterparty_reference → is_qccp and netting_set_id → is_client_cleared.
- CCR-CCP-1 (is_qccp=True, is_client_cleared=False):
    risk_weight == 0.02 (CRR Art. 306(1)(a), proprietary QCCP trade exposure).
- CCR-CCP-2 (is_qccp=True, is_client_cleared=True):
    risk_weight == 0.04 (CRR Art. 306(1)(c), client-cleared trade exposure).
- Anti-degenerate baseline: without wiring, CQS-2 SA-Institution path gives 0.50
  (CRR Art. 120(1) Table 3). Both tests assert risk_weight != 0.50.
- Keyed-join regression guard: 2-counterparty book (1 QCCP + 1 non-QCCP) must
  produce exactly 2 CCR exposure rows (no cross-join fan-out) with the QCCP row
  pinned to 0.02 and the non-QCCP row falling through to SA 0.50.

Scenario (P8.39 fixture):
    Counterparty CP-QCCP-LCH: entity_type="ccp", is_qccp=True, institution_cqs=2.
    CRR Art. 120(1) Table 3: institution CQS 2 -> 50% SA RW (anti-degenerate baseline).

    Netting set NS-QCCP-01 (CP-QCCP-LCH, legally enforceable, unmargined).
    Trade T-QCCP-01: IR derivative, GBP 100m.
      CCR-CCP-1: is_client_cleared=False -> expected risk_weight=0.02
      CCR-CCP-2: is_client_cleared=True  -> expected risk_weight=0.04

    EAD invariant (load-bearing):
        EAD is computed by SA-CCR (Art. 274(2)) at the pipeline reporting date
        and must be identical for CCR-CCP-1 and CCR-CCP-2 — only risk_weight
        differs between the two scenarios.
        The hand-calculated EAD at Si=0 is P839_EAD = 4_750_088.326..., but the
        pipeline reporting date (2026-01-15) is before the trade start date
        (2027-01-01), so Si > 0 and the pipeline EAD differs from the hand calc.
        We assert EAD invariance (CCP-1 == CCP-2) and RWA = ead_final * rw,
        derived from the pipeline-computed EAD, not the hand-calc constant.

Expected post-wiring structure (load-bearing assertions):
    CCR-CCP-1: risk_weight == 0.02, != 0.50, rwa_final == ead_final * 0.02
    CCR-CCP-2: risk_weight == 0.04, != 0.50, rwa_final == ead_final * 0.04
    Both:      ead_final is identical (EAD invariant)
    2-CP book: exactly 2 CCR rows; QCCP row risk_weight == 0.02;
               non-QCCP row risk_weight == 0.50 (SA fallback, not pinned)

This test is RED on the unfixed pipeline because:
- CCR-CCP-2: apply_ccp_risk_weight is NOT wired, so is_client_cleared is not
  propagated → cp_is_ccp_client_cleared is null → SA calculator applies the
  proprietary 2% for both scenarios instead of 4% for client-cleared.
- Two-CP book: non-QCCP counterparty (is_qccp=False) has entity_type="ccp", so
  the SA calculator's entity_type == "ccp" branch gives 0.02 regardless of
  is_qccp. apply_ccp_risk_weight must use the keyed is_qccp flag to block this
  fan-through; without wiring the non-QCCP row gets 0.02 instead of 0.50.

References:
    - CRR Art. 306(1)(a) — 2% RW for clearing member's proprietary QCCP trades
    - CRR Art. 306(1)(c) — 4% RW for client-cleared QCCP trades
    - CRR Art. 306(4)    — RWA = Σ EAD × RW
    - CRR Art. 272 Def (88) — qualified central counterparty (QCCP)
    - CRR Art. 120(1) Table 3 — institution CQS 2 → 50% SA RW (anti-degenerate)
    - CRR Art. 274(2) — SA-CCR EAD = alpha × (RC + PFE)
    - src/rwa_calc/engine/ccr/ccp.py — apply_ccp_risk_weight (not yet wired)
    - src/rwa_calc/engine/pipeline.py — _run_ccr_stage (missing call to ccp)
    - tests/fixtures/ccr/p839_ccp_builder.py — CCR-CCP-1 / CCR-CCP-2 fixtures
    - tests/acceptance/ccr/test_ccr_wwr1_orchestrator_gate.py — orchestrator idiom
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.p839_ccp_builder import (
    P839_ANTI_DEGENERATE_RW,
    P839_CP_NON_QCCP_REF,
    P839_CP_QCCP_REF,
    P839_NS_NON_QCCP_ID,
    P839_RW_CLIENT_CLEARED,
    P839_RW_PROPRIETARY,
    build_p839_bundle,
    build_p839_two_counterparty_book,
)
from tests.fixtures.ccr.qccp_builder import QCCP_NS_ID

# ---------------------------------------------------------------------------
# Shared pipeline config
# ---------------------------------------------------------------------------

#: Reporting date used for all P8.39 orchestrator runs.
#: Must be CRR era (< 2027-01-01) so CRR SA risk weights apply.
_REPORTING_DATE: date = date(2026, 1, 15)


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccp1_result_bundle():
    """
    Run CCR-CCP-1 (is_client_cleared=False) through the full CRR SA pipeline.

    Returns the AggregatedResultBundle for structural assertions.
    Module-scoped: pipeline runs once; all CCR-CCP-1 tests reuse the result.

    Arrange:
        - Counterparty CP-QCCP-LCH: entity_type="ccp", is_qccp=True,
          institution_cqs=2
        - NS-QCCP-01: legally enforceable, unmargined, no CSA
        - Trade T-QCCP-01: GBP 100m IR derivative, is_client_cleared=False
    """
    # Arrange
    bundle = build_p839_bundle(is_client_cleared=False)
    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def ccp2_result_bundle():
    """
    Run CCR-CCP-2 (is_client_cleared=True) through the full CRR SA pipeline.

    Returns the AggregatedResultBundle for structural assertions.

    Arrange:
        - Same as CCR-CCP-1 except is_client_cleared=True on the trade.
    """
    # Arrange
    bundle = build_p839_bundle(is_client_cleared=True)
    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def two_cp_result_bundle():
    """
    Run the 2-counterparty keyed-join regression book through the pipeline.

    Returns the AggregatedResultBundle for structural assertions.

    Arrange:
        - CP-QCCP-LCH (is_qccp=True) → NS-QCCP-01 → T-QCCP-01, is_client_cleared=False
        - CP-NON-QCCP-01 (is_qccp=False) → NS-NON-QCCP-01 → T-NON-QCCP-01, is_client_cleared=False
    """
    # Arrange
    bundle = build_p839_two_counterparty_book()
    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def ccp1_ccr_row(ccp1_result_bundle) -> dict:
    """
    Locate the single CCR exposure row for CCR-CCP-1 (NS-QCCP-01).

    The exposure_reference is "ccr__NS-QCCP-01" for a netting set id "NS-QCCP-01".
    Fails clearly if the row is absent (pipeline returned no CCR rows).
    """
    df = ccp1_result_bundle.results.collect()
    ccr_rows = df.filter(
        pl.col("exposure_reference") == f"ccr__{QCCP_NS_ID}"
    ).to_dicts()
    assert len(ccr_rows) == 1, (
        f"CCR-CCP-1: expected exactly 1 CCR exposure row with "
        f"exposure_reference='ccr__{QCCP_NS_ID}', got {len(ccr_rows)}. "
        f"All exposure_references: "
        f"{df.filter(pl.col('exposure_reference').str.starts_with('ccr__'))['exposure_reference'].to_list()!r}. "
        "P8.39 fix: ensure _run_ccr_stage produces one row per netting set."
    )
    return ccr_rows[0]


@pytest.fixture(scope="module")
def ccp2_ccr_row(ccp2_result_bundle) -> dict:
    """
    Locate the single CCR exposure row for CCR-CCP-2 (NS-QCCP-01).

    Same netting set as CCR-CCP-1 — only the trade's is_client_cleared differs.
    """
    df = ccp2_result_bundle.results.collect()
    ccr_rows = df.filter(
        pl.col("exposure_reference") == f"ccr__{QCCP_NS_ID}"
    ).to_dicts()
    assert len(ccr_rows) == 1, (
        f"CCR-CCP-2: expected exactly 1 CCR exposure row with "
        f"exposure_reference='ccr__{QCCP_NS_ID}', got {len(ccr_rows)}. "
        f"All exposure_references: "
        f"{df.filter(pl.col('exposure_reference').str.starts_with('ccr__'))['exposure_reference'].to_list()!r}. "
        "P8.39 fix: ensure _run_ccr_stage produces one row per netting set."
    )
    return ccr_rows[0]


@pytest.fixture(scope="module")
def two_cp_ccr_rows(two_cp_result_bundle) -> list[dict]:
    """Return all CCR exposure rows from the 2-counterparty result."""
    df = two_cp_result_bundle.results.collect()
    return df.filter(
        pl.col("exposure_reference").str.starts_with("ccr__")
    ).to_dicts()


# ---------------------------------------------------------------------------
# CCR-CCP-1 acceptance tests (proprietary, expected risk_weight = 0.02)
# ---------------------------------------------------------------------------


class TestCCRCCP1Proprietary:
    """
    CCR-CCP-1 / P8.39: four acceptance assertions for the proprietary QCCP path.

    Pin 1 — risk_weight == 0.02  (CRR Art. 306(1)(a)).
    Pin 2 — risk_weight != 0.50  (anti-degenerate: CQS-2 SA fallback displaced).
    Pin 3 — EAD invariant: ead_final matches ead_ccr (not mutated by RW pin).
    Pin 4 — RWA == ead_final * 0.02 (CRR Art. 306(4)).

    All four tests are RED on the unfixed pipeline only if apply_ccp_risk_weight
    is not wired AND the current fallback gives 0.50.  Note: as of this writing
    the SA calculator's entity_type=="ccp" branch gives 0.02 for ALL ccp-type
    counterparties (because cp_is_ccp_client_cleared is null → fills False →
    proprietary).  Pin 1 may pass trivially.  Pin 2 passes trivially.
    The load-bearing failure for CCR-CCP-1 comes from CCR-CCP-2 (separate class)
    where 0.04 != 0.02.  Pin 1 and 2 are still written here for completeness
    and for future regression protection.
    """

    def test_ccr_ccp1_risk_weight_is_002(self, ccp1_ccr_row: dict) -> None:
        """
        Proprietary QCCP trade exposure must carry risk_weight == 0.02.

        Arrange:
            CP-QCCP-LCH (is_qccp=True), T-QCCP-01 (is_client_cleared=False).
        Act:
            Full CRR SA pipeline via PipelineOrchestrator.
        Assert:
            risk_weight == 0.02 (exact equality — regulatory scalar per CRR Art. 306(1)(a)).

        CRR Art. 306(1)(a): clearing member's own QCCP trade exposure -> 2% RW.
        BCBS CRE54.14: 2% supervisory factor.

        This assertion is load-bearing: if apply_ccp_risk_weight is not wired and
        the SA calculator falls through to the institution CQS-2 path, risk_weight
        would be 0.50 (CRR Art. 120(1) Table 3).

        References: CRR Art. 306(1)(a); BCBS CRE54.14.
        """
        # Arrange
        expected_rw = P839_RW_PROPRIETARY  # 0.02

        # Assert
        actual_rw = ccp1_ccr_row["risk_weight"]
        assert actual_rw == expected_rw, (
            f"CCR-CCP-1: expected risk_weight={expected_rw} (CRR Art. 306(1)(a): "
            f"proprietary QCCP trade exposure 2%), got {actual_rw!r}. "
            f"Anti-degenerate: without apply_ccp_risk_weight wiring, CQS-2 "
            f"institution SA path gives {P839_ANTI_DEGENERATE_RW} (50%). "
            "P8.39 fix: wire apply_ccp_risk_weight in pipeline.py::_run_ccr_stage "
            "keyed on counterparty_reference → is_qccp and netting_set_id → "
            "is_client_cleared (any() over trades per NS)."
        )

    def test_ccr_ccp1_risk_weight_is_not_sa_fallback(self, ccp1_ccr_row: dict) -> None:
        """
        Proprietary QCCP row must NOT carry the anti-degenerate SA fallback 0.50.

        This is the load-bearing anti-degenerate guard: CQS-2 institution SA
        weight (CRR Art. 120(1) Table 3) is the weight that would apply if
        apply_ccp_risk_weight is absent. The explicit != 0.50 assertion is a
        canary that fails immediately if the CCP pin is bypassed.

        References: CRR Art. 120(1) Table 3 (CQS-2 institution 50%); Art. 306(1)(a).
        """
        # Arrange
        anti_degenerate_rw = P839_ANTI_DEGENERATE_RW  # 0.50

        # Assert
        actual_rw = ccp1_ccr_row["risk_weight"]
        assert actual_rw != anti_degenerate_rw, (
            f"CCR-CCP-1: risk_weight must NOT be {anti_degenerate_rw} (the SA-Institution "
            f"CQS-2 fallback). Got {actual_rw!r}. "
            "CRR Art. 306(1)(a) mandates 2% for proprietary QCCP trade exposures, "
            "not the general institution CQS-2 weight. "
            "P8.39 fix: wire apply_ccp_risk_weight in _run_ccr_stage so the QCCP "
            "pin displaces the SA fallback before the classifier."
        )

    def test_ccr_ccp1_ead_equals_ead_ccr(self, ccp1_ccr_row: dict) -> None:
        """
        ead_final must equal ead_ccr — EAD is never mutated by apply_ccp_risk_weight.

        apply_ccp_risk_weight annotates risk_weight only; ead_ccr produced by the
        SA-CCR engine (Art. 274(2)) must pass through unchanged.

        References: CRR Art. 274(2) — SA-CCR EAD formula; CRR Art. 306(4) — RWA = EAD × RW.
        """
        # Arrange / Act
        ead_ccr = ccp1_ccr_row["ead_ccr"]
        ead_final = ccp1_ccr_row["ead_final"]

        # Assert
        assert ead_final == pytest.approx(ead_ccr, rel=1e-9), (
            f"CCR-CCP-1: ead_final ({ead_final!r}) must equal ead_ccr ({ead_ccr!r}). "
            "apply_ccp_risk_weight must never mutate ead_ccr. "
            "The SA-CCR EAD is computed upstream by the EAD engine and must pass "
            "through the CCP risk-weight annotation unchanged."
        )

    def test_ccr_ccp1_rwa_equals_ead_times_002(self, ccp1_ccr_row: dict) -> None:
        """
        rwa_final == ead_final * 0.02 (CRR Art. 306(4)).

        The RWA calculation is EAD × risk_weight. Using the pipeline-computed
        ead_final (reporting-date dependent) rather than the hand-calc P839_EAD
        constant avoids false failures from SA-CCR date sensitivity.

        References: CRR Art. 306(4) — RWA = EAD × 2% for proprietary QCCP exposures.
        """
        # Arrange
        ead_final = ccp1_ccr_row["ead_final"]
        expected_rwa = ead_final * P839_RW_PROPRIETARY  # ead * 0.02

        # Act
        actual_rwa = ccp1_ccr_row["rwa_final"]

        # Assert
        assert actual_rwa == pytest.approx(expected_rwa, rel=1e-9), (
            f"CCR-CCP-1: expected rwa_final={expected_rwa!r} (ead_final * 0.02), "
            f"got {actual_rwa!r}. "
            "CRR Art. 306(4): RWA = EAD × 2% for proprietary QCCP trade exposures."
        )


# ---------------------------------------------------------------------------
# CCR-CCP-2 acceptance tests (client-cleared, expected risk_weight = 0.04)
# ---------------------------------------------------------------------------


class TestCCRCCP2ClientCleared:
    """
    CCR-CCP-2 / P8.39: four acceptance assertions for the client-cleared QCCP path.

    Pin 1 — risk_weight == 0.04  (CRR Art. 306(1)(c)).
    Pin 2 — risk_weight != 0.50  (anti-degenerate: CQS-2 SA fallback displaced).
    Pin 3 — EAD invariant: ead_final identical to CCR-CCP-1 (same economics).
    Pin 4 — RWA == ead_final * 0.04 (CRR Art. 306(4)).

    Pins 1 and 4 are the primary RED-state assertions on the unfixed pipeline:
    without apply_ccp_risk_weight wiring the is_client_cleared flag is NOT
    propagated to cp_is_ccp_client_cleared, so both CCR-CCP-1 and CCR-CCP-2
    receive the proprietary weight 0.02 instead of 0.04 for client-cleared.

    Expected failure mode:
        assert 0.02 == 0.04  (actual proprietary fallback != expected client-cleared 4%)
    """

    def test_ccr_ccp2_risk_weight_is_004(self, ccp2_ccr_row: dict) -> None:
        """
        Client-cleared QCCP trade exposure must carry risk_weight == 0.04.

        Arrange:
            CP-QCCP-LCH (is_qccp=True), T-QCCP-01 (is_client_cleared=True).
        Act:
            Full CRR SA pipeline via PipelineOrchestrator.
        Assert:
            risk_weight == 0.04 (exact equality — regulatory scalar per CRR Art. 306(1)(c)).

        This is the primary load-bearing RED assertion on the unfixed pipeline.
        Without apply_ccp_risk_weight wiring, is_client_cleared on the trade frame
        is never surfaced to cp_is_ccp_client_cleared, so the SA calculator's
        fill_null(False) branch gives 0.02 (proprietary) for client-cleared trades.

        CRR Art. 306(1)(c): client-cleared trades through a clearing member -> 4% RW.
        BCBS CRE54.15: 4% supervisory factor for client-cleared exposures.

        References: CRR Art. 306(1)(c); BCBS CRE54.15.
        """
        # Arrange
        expected_rw = P839_RW_CLIENT_CLEARED  # 0.04

        # Assert
        actual_rw = ccp2_ccr_row["risk_weight"]
        assert actual_rw == expected_rw, (
            f"CCR-CCP-2: expected risk_weight={expected_rw} (CRR Art. 306(1)(c): "
            f"client-cleared QCCP trade exposure 4%), got {actual_rw!r}. "
            f"Anti-degenerate: without apply_ccp_risk_weight wiring, "
            f"cp_is_ccp_client_cleared is null → fill_null(False) → proprietary "
            f"weight 0.02 is applied instead of 0.04. "
            "P8.39 fix: wire apply_ccp_risk_weight in pipeline.py::_run_ccr_stage "
            "so that is_client_cleared (any() over trades for each netting_set_id) "
            "is joined onto the exposure rows before the classifier runs."
        )

    def test_ccr_ccp2_risk_weight_is_not_sa_fallback(self, ccp2_ccr_row: dict) -> None:
        """
        Client-cleared QCCP row must NOT carry the SA fallback 0.50.

        The anti-degenerate 50% weight (CRR Art. 120(1) Table 3 CQS-2) must never
        appear on a QCCP trade exposure row — CRR Art. 306(1) always overrides it.

        References: CRR Art. 120(1) Table 3; Art. 306(1)(c).
        """
        # Arrange
        anti_degenerate_rw = P839_ANTI_DEGENERATE_RW  # 0.50

        # Assert
        actual_rw = ccp2_ccr_row["risk_weight"]
        assert actual_rw != anti_degenerate_rw, (
            f"CCR-CCP-2: risk_weight must NOT be {anti_degenerate_rw} (SA-Institution "
            f"CQS-2 fallback). Got {actual_rw!r}. "
            "CRR Art. 306(1)(c) mandates 4% for client-cleared QCCP trade exposures."
        )

    def test_ccr_ccp2_ead_equals_ead_ccr(self, ccp2_ccr_row: dict) -> None:
        """
        ead_final must equal ead_ccr — apply_ccp_risk_weight must not mutate EAD.

        References: CRR Art. 274(2); CRR Art. 306(4).
        """
        # Arrange / Act
        ead_ccr = ccp2_ccr_row["ead_ccr"]
        ead_final = ccp2_ccr_row["ead_final"]

        # Assert
        assert ead_final == pytest.approx(ead_ccr, rel=1e-9), (
            f"CCR-CCP-2: ead_final ({ead_final!r}) must equal ead_ccr ({ead_ccr!r}). "
            "apply_ccp_risk_weight must never mutate ead_ccr."
        )

    def test_ccr_ccp2_ead_matches_ccp1_ead(
        self, ccp1_ccr_row: dict, ccp2_ccr_row: dict
    ) -> None:
        """
        CCR-CCP-1 and CCR-CCP-2 must have identical ead_final.

        The two scenarios share identical trade economics (same notional, MtM,
        tenor, counterparty). Only is_client_cleared differs.
        CRR Art. 274(2) EAD is independent of the risk-weight branch:
        EAD = alpha × (RC + PFE) is the same for both scenarios.

        This assertion is the EAD invariant of P8.39: apply_ccp_risk_weight
        may only annotate risk_weight; it must leave ead_ccr untouched.

        References: CRR Art. 274(2) — EAD formula; CRR Art. 306(4).
        """
        # Arrange / Act
        ead_ccp1 = ccp1_ccr_row["ead_final"]
        ead_ccp2 = ccp2_ccr_row["ead_final"]

        # Assert
        assert ead_ccp1 == pytest.approx(ead_ccp2, rel=1e-9), (
            f"CCR-CCP-1 and CCR-CCP-2 must share identical ead_final. "
            f"CCP-1 ead_final={ead_ccp1!r}, CCP-2 ead_final={ead_ccp2!r}. "
            "EAD (Art. 274(2)) is computed from trade economics, not from the "
            "QCCP risk-weight branch. apply_ccp_risk_weight must not mutate EAD."
        )

    def test_ccr_ccp2_rwa_equals_ead_times_004(self, ccp2_ccr_row: dict) -> None:
        """
        rwa_final == ead_final * 0.04 (CRR Art. 306(4)).

        Primary RED assertion alongside test_ccr_ccp2_risk_weight_is_004.
        On the unfixed pipeline, rwa_final == ead_final * 0.02 (wrong weight
        applied), so this asserts actual != expected with a clear mismatch.

        References: CRR Art. 306(4) — RWA = EAD × 4% for client-cleared QCCP exposures.
        """
        # Arrange
        ead_final = ccp2_ccr_row["ead_final"]
        expected_rwa = ead_final * P839_RW_CLIENT_CLEARED  # ead * 0.04

        # Act
        actual_rwa = ccp2_ccr_row["rwa_final"]

        # Assert
        assert actual_rwa == pytest.approx(expected_rwa, rel=1e-9), (
            f"CCR-CCP-2: expected rwa_final={expected_rwa!r} (ead_final * 0.04), "
            f"got {actual_rwa!r}. "
            f"Without apply_ccp_risk_weight wiring, rwa_final == ead_final * 0.02 "
            f"({ead_final * P839_RW_PROPRIETARY!r}) because client-cleared distinction "
            f"is lost. "
            "CRR Art. 306(4): RWA = EAD × 4% for client-cleared QCCP trade exposures."
        )


# ---------------------------------------------------------------------------
# Keyed-join regression guard (2-counterparty book)
# ---------------------------------------------------------------------------


class TestCCRCCPKeyedJoinGuard:
    """
    Keyed-join regression guard / P8.39: 2-counterparty book assertions.

    A single-trade / single-NS fixture (1×1×1) is degenerate for cross-join
    detection: a cross-join of 1×1×1 frames still produces 1 row, so the
    single-CP scenarios above do NOT catch a fan-out bug in apply_ccp_risk_weight.

    This 2-counterparty book (2 CPs × 2 NSes × 2 trades) is the regression guard:
    - A cross-join of counterparties × trades would produce 4 exposure rows
      instead of 2, failing the row-count pin.
    - Even if the cross-join happens to produce 2 rows, the wrong RW would
      appear on the non-QCCP row (is_qccp=False should give NULL → SA 0.50,
      not 0.02).

    Composition (both trades are proprietary, is_client_cleared=False):
        CP-QCCP-LCH   (is_qccp=True)  → NS-QCCP-01    → T-QCCP-01
        CP-NON-QCCP-01(is_qccp=False) → NS-NON-QCCP-01 → T-NON-QCCP-01

    Expected per-row risk_weight:
        NS-QCCP-01:     0.02  (QCCP proprietary, Art. 306(1)(a))
        NS-NON-QCCP-01: 0.50  (non-QCCP passes through to SA-Institution CQS-2)

    References:
        - CRR Art. 306(1)(a) — 2% for NS-QCCP-01 (QCCP proprietary)
        - CRR Art. 107(2)(a) — SA-institution routing for NS-NON-QCCP-01
        - CRR Art. 120(1) Table 3 — 50% fallback for CQS-2 non-QCCP institution
    """

    def test_two_cp_book_produces_exactly_two_ccr_rows(
        self, two_cp_ccr_rows: list[dict]
    ) -> None:
        """
        Exactly 2 CCR exposure rows must appear in the 2-counterparty book result.

        Arrange:
            2 counterparties, 2 netting sets, 2 trades.
        Act:
            Full CRR SA pipeline via PipelineOrchestrator.
        Assert:
            Exactly 2 rows with exposure_reference starting with "ccr__".

        A cross-join fan-out in apply_ccp_risk_weight would produce 4 rows
        (2 CP-flag rows × 2 trade-flag rows × 2 original rows = fan-out). This
        assertion distinguishes a correct keyed join from a cross-join bug.
        The 1-counterparty scenarios (CCR-CCP-1 / CCR-CCP-2) CANNOT catch this
        because 1×1×1 cross-join still yields 1 row.

        References: CRR Art. 271 — one EAD row per netting set.
        """
        # Arrange
        expected_count = 2

        # Assert
        actual_count = len(two_cp_ccr_rows)
        assert actual_count == expected_count, (
            f"CCR keyed-join guard: expected {expected_count} CCR exposure rows "
            f"(one per netting set), got {actual_count}. "
            f"NS IDs found: "
            f"{[r['source_netting_set_id'] for r in two_cp_ccr_rows]!r}. "
            "A cross-join in apply_ccp_risk_weight would produce "
            f"{expected_count * expected_count} rows for a {expected_count}-NS book "
            "— single-CP scenarios (1×1×1) cannot catch this fan-out bug. "
            "P8.39 fix: join counterparties keyed on counterparty_reference and "
            "trades (collapsed by any() per netting_set_id) keyed on "
            "source_netting_set_id."
        )

    def test_two_cp_book_qccp_row_risk_weight_is_002(
        self, two_cp_ccr_rows: list[dict]
    ) -> None:
        """
        QCCP netting set (NS-QCCP-01) must have risk_weight == 0.02.

        Arrange:
            CP-QCCP-LCH (is_qccp=True) → NS-QCCP-01, is_client_cleared=False.
        Act:
            Full pipeline.
        Assert:
            NS-QCCP-01 exposure row risk_weight == 0.02.

        References: CRR Art. 306(1)(a).
        """
        # Arrange: locate the QCCP NS row
        qccp_rows = [r for r in two_cp_ccr_rows if r["source_netting_set_id"] == QCCP_NS_ID]
        assert len(qccp_rows) == 1, (
            f"CCR keyed-join guard: expected 1 row for NS {QCCP_NS_ID!r}, "
            f"got {len(qccp_rows)}. "
            f"All NS IDs: {[r['source_netting_set_id'] for r in two_cp_ccr_rows]!r}."
        )

        # Assert
        actual_rw = qccp_rows[0]["risk_weight"]
        assert actual_rw == P839_RW_PROPRIETARY, (
            f"CCR keyed-join guard: NS-QCCP-01 expected risk_weight={P839_RW_PROPRIETARY} "
            f"(QCCP proprietary, Art. 306(1)(a)), got {actual_rw!r}. "
            "P8.39 fix: apply_ccp_risk_weight must key the QCCP join on "
            "counterparty_reference so only is_qccp=True CPs receive the pin."
        )

    def test_two_cp_book_non_qccp_row_risk_weight_is_sa_fallback(
        self, two_cp_ccr_rows: list[dict]
    ) -> None:
        """
        Non-QCCP netting set (NS-NON-QCCP-01) must have risk_weight == 0.50.

        Arrange:
            CP-NON-QCCP-01 (is_qccp=False, institution_cqs=2) → NS-NON-QCCP-01.
            apply_ccp_risk_weight leaves risk_weight NULL for non-QCCP rows
            (pass-through). The SA classifier resolves CQS-2 → 50% institution RW
            (CRR Art. 120(1) Table 3).
        Act:
            Full pipeline.
        Assert:
            NS-NON-QCCP-01 exposure row risk_weight == 0.50.

        This is the primary RED assertion of the keyed-join guard. Without proper
        keyed join:
        - If apply_ccp_risk_weight is absent: the SA calculator applies 0.02 to ALL
          entity_type="ccp" rows regardless of is_qccp (current unfixed state gives
          risk_weight=0.02 for non-QCCP CCP-type counterparty).
        - If apply_ccp_risk_weight is wired but uses a cross-join: is_qccp=True from
          the QCCP counterparty leaks into the non-QCCP exposure row, pinning it
          incorrectly to 0.02.

        Expected failure mode on unfixed pipeline:
            assert 0.02 == 0.50
            (SA calculator entity_type=="ccp" branch gives 0.02 for is_qccp=False CP)

        References:
            CRR Art. 120(1) Table 3 — institution CQS-2 → 50%.
            CRR Art. 107(2)(a) — non-QCCP CCP-type exposures routed as institution SA.
        """
        # Arrange: locate the non-QCCP NS row
        non_qccp_rows = [
            r for r in two_cp_ccr_rows
            if r["source_netting_set_id"] == P839_NS_NON_QCCP_ID
        ]
        assert len(non_qccp_rows) == 1, (
            f"CCR keyed-join guard: expected 1 row for NS {P839_NS_NON_QCCP_ID!r}, "
            f"got {len(non_qccp_rows)}. "
            f"All NS IDs: {[r['source_netting_set_id'] for r in two_cp_ccr_rows]!r}."
        )

        # Assert
        actual_rw = non_qccp_rows[0]["risk_weight"]
        assert actual_rw == P839_ANTI_DEGENERATE_RW, (
            f"CCR keyed-join guard: NS-NON-QCCP-01 expected risk_weight="
            f"{P839_ANTI_DEGENERATE_RW} (SA-Institution CQS-2 fallback per "
            f"CRR Art. 120(1) Table 3, entity_type=ccp is_qccp=False), "
            f"got {actual_rw!r}. "
            f"Without P8.39 wiring, the SA calculator's entity_type==\"ccp\" branch "
            f"applies {P839_RW_PROPRIETARY} (0.02) to ALL ccp-type CPs, ignoring "
            f"is_qccp=False. "
            "P8.39 fix: apply_ccp_risk_weight must use a keyed join on "
            "counterparty_reference and filter by is_qccp=True, setting risk_weight=NULL "
            "for is_qccp=False rows (pass-through to SA institution ladder)."
        )
