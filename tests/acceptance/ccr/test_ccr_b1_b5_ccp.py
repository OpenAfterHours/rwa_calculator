"""
CCR-B5 / P8.42: non-QCCP CCP trade exposure at CQS-1 -> 20% institution risk weight.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator -> OutputAggregator

Key responsibilities:
- Validate that a CCP-type counterparty with is_qccp=False is demoted to the
  corporate SA risk-weight ladder (CRR Art. 107(2)(b); CC-11) and assigned the
  CQS-1 risk weight of 20% (CRR Art. 122(1) Table 6, as Art. 120(1) Table 3).
- Validate that the EAD is byte-identical to CCR-A1 (same trade economics),
  loaded from tests/expected_outputs/ccr/CCR-A1.json to avoid transcription drift.
- Validate anti-degenerate guards: the QCCP-specific weights (2%/4%) and the
  CQS-2 fallback (50%) must NOT appear.

Scenario (P8.42 / NS-NONQCCP-B5):
    Counterparty CP-NONQCCP-B5: entity_type="ccp", is_qccp=False, institution_cqs=1.
    Netting set NS-NONQCCP-B5: legally enforceable, unmargined.
    Trade T-NONQCCP-B5: 10y GBP IR swap, GBP 100m, MtM=0, delta=1 (same as CCR-A1).

    EAD invariant (load-bearing):
        SA-CCR inputs are byte-identical to CCR-A1, so ead_final must equal
        CCR-A1.json["ead_final"] = 5_480_017.519 (rel=1e-6).
        The literal is NOT transcribed here; it is loaded from the JSON at test time.

Note — B1-B4 / QCCP paths are covered by separate files:
    CCR-CCP-1 / CCR-CCP-2 (2% / 4% QCCP paths):
        tests/acceptance/ccr/test_ccr_ccp_orchestrator_pin.py
    CCR-B2 / CCR-B3 / CCR-B4 (default fund, Art. 308/309):
        tests/acceptance/ccr/test_ccr_b2_b4_default_fund.py
    Only the CCR-B5 (non-QCCP CQS-1 -> 20%) pin is asserted here.

Expected outcome (green-on-arrival regression guard):
    The non-QCCP demotion path is the same engine code path as the CQS-2 -> 50%
    guard in the P8.39 two-counterparty book (test_ccr_ccp_orchestrator_pin.py).
    CQS-1 -> 20% is a different band of the same table, so the engine is expected
    to produce risk_weight == 0.20 without any new implementation.

References:
    - CRR Art. 107(2)(b) — non-QCCP CCP exposure treated as corporate (SA)
    - CRR Art. 120(1) Table 3 — institution CQS-1 -> 20% SA risk weight
    - CRR Art. 272 Def (88) — QCCP definition (NOT met; is_qccp=False)
    - CRR Art. 274(2) — EAD = alpha * (RC + PFE), alpha=1.4
    - tests/expected_outputs/ccr/CCR-A1.json — EAD invariant anchor (ead_final)
    - tests/fixtures/ccr/p842_nonqccp_b5_builder.py — CCR-B5 bundle factory
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.p842_nonqccp_b5_builder import (
    NONQCCP_B5_EXPECTED_RW,
    NONQCCP_B5_INSTITUTION_CQS,
    NONQCCP_B5_NS_ID,
    build_nonqccp_b5_bundle,
)

# ---------------------------------------------------------------------------
# CCR-A1 golden EAD — single source of truth (do NOT transcribe the literal).
# ---------------------------------------------------------------------------

_CCR_A1_JSON_PATH: Path = (
    Path(__file__).parent.parent.parent / "expected_outputs" / "ccr" / "CCR-A1.json"
)
_CCR_A1_EXPECTED = json.loads(_CCR_A1_JSON_PATH.read_text())

#: EAD from CCR-A1.json — loaded at import time so the literal is never duplicated.
_CCR_A1_EAD_FINAL: float = _CCR_A1_EXPECTED["ead_final"]

# ---------------------------------------------------------------------------
# Reporting date and exposure-reference derivation.
# ---------------------------------------------------------------------------

#: Must be CRR era (< 2027-01-01) so CRR SA risk weights apply.
_REPORTING_DATE: date = date(2026, 1, 15)

#: exposure_reference for the CCR-B5 netting set (pipeline convention: "ccr__" + ns_id).
_EXPOSURE_REF: str = f"ccr__{NONQCCP_B5_NS_ID}"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_b5_result_bundle():
    """
    Run the CCR-B5 (non-QCCP CQS-1) bundle through the full CRR SA pipeline.

    Returns the AggregatedResultBundle for structural assertions.
    Module-scoped: pipeline runs once; all CCR-B5 tests reuse the result.

    Arrange:
        - Counterparty CP-NONQCCP-B5: entity_type="ccp", is_qccp=False,
          institution_cqs=1 -> CRR Art. 120(1) Table 3 CQS-1 -> 20% RW.
        - NS-NONQCCP-B5: legally enforceable, unmargined, no CSA.
        - Trade T-NONQCCP-B5: 10y GBP IR swap, notional 100m, MtM=0, delta=1.
          (Byte-identical economics to CCR-A1.)
    """
    # Arrange
    bundle = build_nonqccp_b5_bundle()
    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def ccr_b5_row(ccr_b5_result_bundle) -> dict:
    """
    Locate the single CCR exposure row for CCR-B5 (NS-NONQCCP-B5).

    The exposure_reference is "ccr__NS-NONQCCP-B5" (pipeline convention).
    Fails with a clear message if the row is absent (pipeline produced no CCR rows).
    """
    df = ccr_b5_result_bundle.results.collect()
    ccr_rows = df.filter(pl.col("exposure_reference") == _EXPOSURE_REF).to_dicts()
    assert len(ccr_rows) == 1, (
        f"CCR-B5: expected exactly 1 CCR exposure row with "
        f"exposure_reference={_EXPOSURE_REF!r}, got {len(ccr_rows)}. "
        f"All CCR exposure_references: "
        f"{df.filter(pl.col('exposure_reference').str.starts_with('ccr__'))['exposure_reference'].to_list()!r}. "
        "Ensure _run_ccr_stage produces one row per netting set."
    )
    return ccr_rows[0]


# ---------------------------------------------------------------------------
# CCR-B5 acceptance tests (non-QCCP CQS-1, expected risk_weight = 0.20)
# ---------------------------------------------------------------------------


class TestCCRB5NonQCCPInstitutionCQS1:
    """
    CCR-B5 / P8.42: five acceptance assertions for the non-QCCP CQS-1 institution path.

    Pin 1 — risk_weight == 0.20  (CRR Art. 120(1) Table 3, institution CQS-1).
    Pin 2 — ead_final ~ CCR-A1.json ead_final (rel=1e-6; EAD invariant).
    Pin 3 — exposure_class == "corporate" (Art. 107(2)(b); CC-11 corrected (a)).
    Pin 4 — rwa_final ~ ead_final * 0.20 (rel=1e-9, derived from pipeline EAD).
    Pin 5 — anti-degenerate guards: risk_weight not in {0.02, 0.04, 0.50, 0.40, 1.0, 12.5}.

    This is expected to be a green-on-arrival regression guard: the non-QCCP
    institution demotion path is the same engine code path used by the P8.39
    two-counterparty book (CQS-2 -> 50%). CQS-1 -> 20% is the same table at a
    different band; no new engine work is required.

    institution_cqs == NONQCCP_B5_INSTITUTION_CQS (1) is checked as a fixture
    smoke-guard to confirm the builder wired the right CQS value.

    References:
        CRR Art. 107(2)(b) — non-QCCP CCP exposure treated as corporate SA.
        CRR Art. 120(1) Table 3 — institution CQS-1 -> 20% risk weight.
        CRR Art. 274(2) — EAD = alpha * (RC + PFE).
        CRR Art. 306(4) — RWA = EAD * risk_weight.
    """

    def test_ccr_b5_risk_weight_is_020(self, ccr_b5_row: dict) -> None:
        """
        Non-QCCP CCP trade exposure at institution CQS-1 must carry risk_weight == 0.20.

        Arrange:
            CP-NONQCCP-B5 (is_qccp=False, institution_cqs=1, entity_type="ccp").
            T-NONQCCP-B5 (is_client_cleared=False, 10y GBP IR swap, MtM=0).
        Act:
            Full CRR SA pipeline via PipelineOrchestrator.
        Assert:
            risk_weight == 0.20 (exact equality — regulatory scalar per
            CRR Art. 120(1) Table 3, institution CQS-1).

        The anti-degenerate baseline (CQS-2 -> 50%) would apply if the engine
        read institution_cqs=2 instead of institution_cqs=1. The fixture builder
        sets institution_cqs=1 explicitly, so 20% must result.

        References:
            CRR Art. 120(1) Table 3 — institution CQS-1 -> 20% risk weight.
            CRR Art. 107(2)(b) — non-QCCP CCP exposure treated as corporate SA.
        """
        # Arrange
        expected_rw = NONQCCP_B5_EXPECTED_RW  # 0.20

        # Assert
        actual_rw = ccr_b5_row["risk_weight"]
        assert actual_rw == expected_rw, (
            f"CCR-B5: expected risk_weight={expected_rw} "
            f"(CRR Art. 120(1) Table 3: institution CQS-{NONQCCP_B5_INSTITUTION_CQS} -> 20%), "
            f"got {actual_rw!r}. "
            "CRR Art. 107(2)(b): non-QCCP CCP exposure is treated as a corporate "
            "exposure under SA — apply the CQS-1 weight from Table 3 (20%), not the "
            "QCCP-specific 2%/4% weights (Art. 306(1)) and not the CQS-2 weight (50%)."
        )

    def test_ccr_b5_ead_matches_ccr_a1(self, ccr_b5_row: dict) -> None:
        """
        ead_final must match CCR-A1.json ead_final to rel=1e-6.

        The CCR-B5 trade economics are byte-identical to CCR-A1 (same notional,
        start/maturity dates, MtM=0, delta=1, asset class=IR). The only difference
        is the counterparty. SA-CCR EAD (CRR Art. 274(2)) is independent of the
        counterparty's risk-weight class, so the EAD must be identical.

        Arrange:
            T-NONQCCP-B5 with byte-identical parameters to T_001 in CCR-A1.
        Act:
            Full pipeline; ead_final read from the result row.
        Assert:
            ead_final == pytest.approx(CCR-A1.json["ead_final"], rel=1e-6).

        References:
            CRR Art. 274(2) — EAD = alpha * (RC + PFE); EAD is counterparty-agnostic.
            tests/expected_outputs/ccr/CCR-A1.json — anchor (ead_final 5_480_017.519).
        """
        # Arrange
        expected_ead = _CCR_A1_EAD_FINAL  # loaded from CCR-A1.json, not transcribed

        # Act
        actual_ead = ccr_b5_row["ead_final"]

        # Assert
        assert actual_ead == pytest.approx(expected_ead, rel=1e-6), (
            f"CCR-B5: expected ead_final ~ {expected_ead:,.3f} "
            f"(CCR-A1.json anchor, byte-identical trade economics), "
            f"got {actual_ead:,.3f}. "
            "CRR Art. 274(2): EAD = 1.4 * (RC + PFE) depends only on trade "
            "economics (notional, tenor, MtM), not on the counterparty's QCCP status "
            "or CQS band. The fixture uses the same trade parameters as CCR-A1 so "
            "the SA-CCR EAD must match."
        )

    def test_ccr_b5_exposure_class_is_corporate(self, ccr_b5_row: dict) -> None:
        """
        Classifier must route CP-NONQCCP-B5 to exposure_class "corporate".

        CC-11 (2026-11 review) corrected this pin, which asserted "institution"
        on a citation of Art. 107(2)(a) — the QUALIFYING-CCP limb. CRR Art.
        107(2) = PS1/26 Art. 107(2): "For all other types of exposures to a
        central counterparty, institutions shall treat those exposures as
        follows: (a) as exposures to an institution for other types of exposures
        to a qualifying CCP; (b) as exposures to a corporate for other types of
        exposures to a non-qualifying CCP." For the trade exposure itself, CCR
        (CRR) Part Art. 306(1)(b) applies "the risk weight used for the
        Standardised Approach to credit risk as set out in Article 107(2)(b)".
        The risk weight pinned above does not move: CQS 1 is 20% on both the
        Art. 120 institution and the Art. 122 corporate ladder.

        Arrange:
            CP-NONQCCP-B5: entity_type="ccp", is_qccp=False.
        Act:
            Full pipeline.
        Assert:
            exposure_class == "corporate" (case-insensitive).

        References:
            CRR Art. 107(2)(b); CCR (CRR) Part Art. 306(1)(b).
        """
        # Arrange
        expected_class = "corporate"

        # Act
        actual_class = ccr_b5_row["exposure_class"]

        # Assert
        assert actual_class.lower() == expected_class, (
            f"CCR-B5: expected exposure_class={expected_class!r} "
            f"(CRR Art. 107(2)(b): exposures to a non-qualifying CCP are corporate), "
            f"got {actual_class!r}."
        )

    def test_ccr_b5_rwa_equals_ead_times_020(self, ccr_b5_row: dict) -> None:
        """
        rwa_final == ead_final * 0.20 (derived from the pipeline EAD, rel=1e-9).

        The RWA formula is EAD * risk_weight.  We use the pipeline-computed ead_final
        (not the CCR-A1.json anchor) so that SA-CCR recalibrations propagate correctly
        without needing to update this assertion.

        Arrange:
            ead_final from the pipeline result row.
            risk_weight = NONQCCP_B5_EXPECTED_RW (0.20).
        Act:
            Compute expected_rwa = ead_final * 0.20.
        Assert:
            rwa_final == pytest.approx(ead_final * 0.20, rel=1e-9).

        References:
            CRR Art. 120(1) Table 3 — institution CQS-1 -> 20% risk weight.
            CRR Art. 113(1) — RWA = EAD * risk_weight.
        """
        # Arrange
        ead_final = ccr_b5_row["ead_final"]
        expected_rwa = ead_final * NONQCCP_B5_EXPECTED_RW  # ead * 0.20

        # Act
        actual_rwa = ccr_b5_row["rwa_final"]

        # Assert
        assert actual_rwa == pytest.approx(expected_rwa, rel=1e-9), (
            f"CCR-B5: expected rwa_final={expected_rwa:,.3f} (ead_final * 0.20), "
            f"got {actual_rwa:,.3f}. "
            f"Pipeline ead_final={ead_final:,.3f}. "
            "CRR Art. 113(1): RWA = EAD * RW; "
            "CRR Art. 120(1) Table 3: institution CQS-1 -> 20% risk weight."
        )

    def test_ccr_b5_risk_weight_anti_degenerate_guards(self, ccr_b5_row: dict) -> None:
        """
        risk_weight must not be any of the known-wrong values.

        The anti-degenerate guards protect against:
        - 0.02: QCCP proprietary weight (Art. 306(1)(a)) — wrong; is_qccp=False.
        - 0.04: QCCP client-cleared weight (Art. 306(1)(c)) — wrong; is_qccp=False.
        - 0.50: SA institution CQS-2 fallback — wrong CQS band (fixture uses CQS-1).
        - 0.40: Unrated institution fallback — wrong; fixture provides institution_cqs=1.
        - 1.0:  Corporate fallback — wrong exposure class (must be institution).
        - 12.5: Art. 309 non-QCCP default-fund weight — wrong risk type (derivative, not DFC).

        References:
            CRR Art. 120(1) Table 3 — institution CQS bands.
            CRR Art. 306(1) — QCCP weights (not applicable; is_qccp=False).
            CRR Art. 309 — non-QCCP default-fund weight (not applicable; derivative).
        """
        # Arrange
        actual_rw = ccr_b5_row["risk_weight"]

        # Assert — each forbidden value with a targeted message.
        assert actual_rw != 0.02, (
            f"CCR-B5: risk_weight must NOT be 0.02 (QCCP proprietary, Art. 306(1)(a)). "
            f"CP-NONQCCP-B5 has is_qccp=False — the QCCP branch is unreachable. "
            f"Got {actual_rw!r}."
        )
        assert actual_rw != 0.04, (
            f"CCR-B5: risk_weight must NOT be 0.04 (QCCP client-cleared, Art. 306(1)(c)). "
            f"CP-NONQCCP-B5 has is_qccp=False — the QCCP branch is unreachable. "
            f"Got {actual_rw!r}."
        )
        assert actual_rw != 0.50, (
            f"CCR-B5: risk_weight must NOT be 0.50 (SA institution CQS-2 fallback). "
            f"Fixture uses institution_cqs={NONQCCP_B5_INSTITUTION_CQS} (CQS-1 -> 20%). "
            f"Got {actual_rw!r}."
        )
        assert actual_rw != 0.40, (
            f"CCR-B5: risk_weight must NOT be 0.40 (unrated institution fallback). "
            f"Fixture provides institution_cqs={NONQCCP_B5_INSTITUTION_CQS}; "
            f"CQS-1 must yield 20% per CRR Art. 120(1) Table 3. "
            f"Got {actual_rw!r}."
        )
        assert actual_rw != 1.0, (
            f"CCR-B5: risk_weight must NOT be 1.0 (corporate fallback). "
            f"CQS-1 is 20% on the Art. 122 corporate ladder (Art. 107(2)(b)), "
            f"never the unrated corporate 100%. Got {actual_rw!r}."
        )
        assert actual_rw != 12.5, (
            f"CCR-B5: risk_weight must NOT be 12.5 (Art. 309 non-QCCP default-fund). "
            f"T-NONQCCP-B5 is a derivative (risk_type=CCR_DERIVATIVE), not a "
            f"default-fund contribution. Got {actual_rw!r}."
        )
