"""
CCR-IRB-1: single 5-year GBP vanilla IR swap, unmargined,
foundation-IRB corporate counterparty (CRR Art. 153(1)).

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> IRBCalculator -> OutputAggregator

Scenario (P8.31 / CCR-IRB-1):
    CP_IRB_001: corporate, GB, internal_pd=0.0150, model_id=MOD_CORP_FIRB.
    NS_IRB_001: unmargined, legally enforceable (CRR Art. 295).
    T_IRB_001: 5y GBP IR swap, notional GBP 100m, MtM=0.0, delta=1.0.
    No CSA, no CCR collateral.

Key responsibilities:
- Confirm SA-CCR computes ead_ccr for a 5-year unmargined IR derivative.
- Confirm ead_final == ead_ccr (no CRM adjustment for this scenario).
- Confirm approach_applied == 'foundation_irb' (LOAD-BEARING: today 'standardised').
- Confirm pd, lgd, irb_maturity_m, k, risk_weight, rwa_final match IRB formula.

Hand-calculation reference (CCR-IRB-1.json):
    ead_ccr   = 3_068_443.870  (SA-CCR pipeline output: alpha=1.4 * PFE_5y)
    ead_final = 3_068_443.870  (no CRM; EAD passes through unchanged)
    PD        = max(0.0150, 0.0003) = 0.0150  (CRR Art. 163 floor)
    LGD       = 0.45  (CRR Art. 161(1)(a) F-IRB senior unsecured)
    M         = clip(5.0, 1, 5) = 5.0  (CRR Art. 162(2)(b))
    k         approx 0.069078  (pre-MA, pre-scaling; engine column 'k')
    MA        approx 1.594361
    scaling   = 1.06  (CRR)
    risk_weight = k * 12.5 * 1.06 * MA approx 1.459292 (approx 145.93%)
    rwa_final   = risk_weight * ead_ccr approx 4_477_756.046

TODAY'S BEHAVIOUR (pre-fix):
    approach_applied = 'standardised'  — the pipeline does not carry model_id
    through to the CCR synthetic row, so the classifier cannot route to F-IRB.
    The load-bearing assertion MUST fail until P8.31 engine fix lands.

References:
    - CRR Art. 153(1): corporate IRB K formula
    - CRR Art. 161(1)(a): F-IRB senior unsecured LGD = 45%
    - CRR Art. 162(2)(b): non-IMM derivative maturity (1y floor, 5y cap)
    - CRR Art. 163: PD floor 0.03%
    - CRR Art. 274(2): SA-CCR EAD = alpha * (RC + PFE)
    - CRR Art. 275(1): unmargined RC = max(V - C, 0)
    - CRR Art. 295: contractual netting recognition
    - tests/fixtures/ccr/golden_ccr_irb1.py: fixture builder
    - tests/expected_outputs/ccr/CCR-IRB-1.json: expected values
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.golden_ccr_irb1 import (
    build_raw_data_bundle_ccr_irb1,
    create_ccr_irb1_model_permission,
)

# ---------------------------------------------------------------------------
# Expected output (single source of truth — loaded from CCR-IRB-1.json)
# ---------------------------------------------------------------------------

_EXPECTED_OUTPUTS_PATH = (
    Path(__file__).parent.parent.parent / "expected_outputs" / "ccr" / "CCR-IRB-1.json"
)
_EXPECTED = json.loads(_EXPECTED_OUTPUTS_PATH.read_text())

_EXPOSURE_REF: str = _EXPECTED["exposure_reference"]  # "ccr__NS_IRB_001"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_irb1_result() -> dict:
    """
    Run the CCR-IRB-1 bundle through the CRR IRB pipeline and return the
    single CCR synthetic row for ccr__NS_IRB_001 as a dict.

    Module-scoped: runs the pipeline once and reuses results across all tests.

    Arrange:
        - bundle from build_raw_data_bundle_ccr_irb1() with model_permissions injected
        - model_permissions: MOD_CORP_FIRB -> corporate -> foundation_irb (GB)
        - PermissionMode.IRB so the classifier can route to foundation_irb
        - 1 trade (T_IRB_001): 5y GBP IR swap, notional GBP 100m, MtM=0, delta=1
        - 1 netting set (NS_IRB_001): CP_IRB_001, legally enforceable, unmargined
        - CP_IRB_001: corporate, GB, internal_pd=0.0150, model_id=MOD_CORP_FIRB
        - No CSA, no CCR collateral, no traditional lending

    The fixture injects model_permissions as a LazyFrame into RawDataBundle via
    dataclasses.replace() so that the pipeline's HierarchyResolver and Classifier
    can resolve MOD_CORP_FIRB -> foundation_irb for CP_IRB_001.
    """
    # Arrange
    base_bundle = build_raw_data_bundle_ccr_irb1()
    model_permissions_lf = create_ccr_irb1_model_permission().lazy()
    bundle = dataclasses.replace(base_bundle, model_permissions=model_permissions_lf)

    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 15),
        permission_mode=PermissionMode.IRB,
    )

    # Act — run the full CRR IRB pipeline
    results = PipelineOrchestrator().run_with_data(bundle, config)

    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == _EXPOSURE_REF).to_dicts()
    assert len(rows) == 1, (
        f"CCR-IRB-1: expected exactly 1 result row for "
        f"exposure_reference={_EXPOSURE_REF!r}, got {len(rows)}. "
        "The CCR pipeline adapter must emit one synthetic row per netting set."
    )
    return rows[0]


# ---------------------------------------------------------------------------
# CCR-IRB-1 acceptance tests
# ---------------------------------------------------------------------------


class TestCCRIRB1FoundationIRBRouting:
    """
    CCR-IRB-1: 5y GBP IR swap, corporate F-IRB — six acceptance assertions.

    Tests verify:
      - approach_applied == 'foundation_irb'  (LOAD-BEARING, today 'standardised')
      - ead_final == ead_ccr  (EAD passthrough, no CRM)
      - exposure_class == 'corporate'
      - pd approx 0.0150, lgd == 0.45, irb_maturity_m == 5.0
      - k approx 0.069078  (pre-MA pre-scaling, CRR Art. 153(1))
      - risk_weight approx 1.459292  (k * 12.5 * 1.06 * MA)
      - rwa_final approx 4_477_756.046  (risk_weight * ead_ccr)

    All expected values are sourced from tests/expected_outputs/ccr/CCR-IRB-1.json.
    The ead_ccr value was generated by running the current (unmodified) SA-CCR
    pipeline, which is routing-invariant.  The IRB outputs represent POST-FIX
    expected behaviour.
    """

    def test_ccr_irb1_approach_applied(self, ccr_irb1_result: dict) -> None:
        """
        LOAD-BEARING: approach_applied must be 'foundation_irb' post P8.31 fix.

        Today the row routes through SA (approach_applied='standardised') because
        the CCR pipeline adapter does not carry model_id onto the synthetic
        exposure row, so the classifier cannot resolve MOD_CORP_FIRB.

        Arrange: CP_IRB_001 corporate with internal_pd=0.0150, model MOD_CORP_FIRB
                 -> foundation_irb (GB). Bundle supplied with PermissionMode.IRB.
        Act:     full CRR F-IRB pipeline (CCRAdapter + IRBCalculator).
        Assert:  approach_applied == 'foundation_irb' (fails today with 'standardised').

        References:
            CRR Art. 153(1): corporate F-IRB K formula.
            MOD_CORP_FIRB model permission: exposure_class='corporate',
            approach='foundation_irb', country_codes='GB'.
        """
        # Arrange
        row = ccr_irb1_result
        expected = _EXPECTED["approach_applied"]  # "foundation_irb"

        # Assert — FAILS today: approach_applied == 'standardised', not 'foundation_irb'
        assert row["approach_applied"] == expected, (
            f"CCR-IRB-1 (P8.31): expected approach_applied={expected!r} "
            f"(F-IRB routing via MOD_CORP_FIRB model permission), "
            f"got {row['approach_applied']!r}. "
            "The CCR pipeline adapter must propagate model_id to the synthetic "
            "exposure row so the Classifier can resolve foundation_irb "
            "for CCR counterparties with IRB model permissions."
        )

    def test_ccr_irb1_ead_passthrough(self, ccr_irb1_result: dict) -> None:
        """
        ead_final must equal ead_ccr (no CRM adjustment for this scenario).

        Arrange: no CCR collateral, no guarantees, no on-balance-sheet netting.
        Act:     full CRR F-IRB pipeline.
        Assert:  ead_final == ead_ccr (abs tol 1e-6).

        References: CRR Art. 274(2): EAD = alpha * (RC + PFE).
        """
        # Arrange
        row = ccr_irb1_result
        expected_ead_ccr = _EXPECTED["ead_ccr"]
        expected_ead_final = _EXPECTED["ead_final"]

        # Assert EAD identity — ead_final == ead_ccr (no CRM)
        assert row["ead_final"] == pytest.approx(expected_ead_final, rel=1e-6), (
            f"CCR-IRB-1: expected ead_final approx {expected_ead_final:,.3f} "
            f"(=ead_ccr, no CRM), got {row['ead_final']:,.3f}. "
            "No CCR collateral or guarantees in this scenario."
        )
        assert row["ead_ccr"] == pytest.approx(expected_ead_ccr, rel=1e-6), (
            f"CCR-IRB-1: expected ead_ccr approx {expected_ead_ccr:,.3f}, "
            f"got {row['ead_ccr']:,.3f}. "
            "CRR Art. 274(2): EAD_ccr = 1.4 * (RC + PFE_5y)."
        )

    def test_ccr_irb1_exposure_class(self, ccr_irb1_result: dict) -> None:
        """
        Classifier routes CP_IRB_001 (entity_type='corporate') to exposure_class 'corporate'.

        Arrange: CP_IRB_001 entity_type='corporate', GB, non-SME (no annual_revenue).
        Act:     full CRR F-IRB pipeline.
        Assert:  exposure_class == 'corporate' (case-insensitive).

        References: CRR Art. 112(g) — corporate exposure class.
        """
        # Arrange
        row = ccr_irb1_result
        expected = _EXPECTED["exposure_class"]  # "corporate"

        # Assert
        assert row["exposure_class"].lower() == expected.lower(), (
            f"CCR-IRB-1: expected exposure_class={expected!r}, "
            f"got {row['exposure_class']!r}. "
            "CRR Art. 112(g): corporate entity_type -> corporate exposure class."
        )

    def test_ccr_irb1_irb_parameters(self, ccr_irb1_result: dict) -> None:
        """
        IRB parameters: pd approx 0.0150, lgd == 0.45, irb_maturity_m == 5.0.

        Arrange: internal_pd=0.0150 (above CRR Art. 163 floor 0.03%),
                 F-IRB senior unsecured LGD=45% (Art. 161(1)(a)),
                 M=clip(5.0,1,5)=5.0 (Art. 162(2)(b)).
        Act:     full CRR F-IRB pipeline.
        Assert:  pd approx 0.0150, lgd approx 0.45, irb_maturity_m approx 5.0.

        References:
            CRR Art. 161(1)(a): F-IRB senior unsecured LGD = 45%.
            CRR Art. 162(2)(b): derivative M = weighted-avg remaining, 1y-5y clip.
            CRR Art. 163: PD floor 0.03%.
        """
        # Arrange
        row = ccr_irb1_result
        expected_pd = _EXPECTED["pd"]  # 0.015
        expected_lgd = _EXPECTED["lgd"]  # 0.45
        expected_m = _EXPECTED["irb_maturity_m"]  # 5.0

        # Assert
        assert row["pd"] == pytest.approx(expected_pd, rel=1e-6), (
            f"CCR-IRB-1: expected pd={expected_pd} (CRR Art. 163 floor: "
            f"max(0.0150, 0.0003)=0.0150), got {row['pd']}."
        )
        assert row["lgd"] == pytest.approx(expected_lgd, abs=1e-9), (
            f"CCR-IRB-1: expected lgd={expected_lgd} "
            f"(CRR Art. 161(1)(a) F-IRB senior unsecured), got {row['lgd']}."
        )
        assert row["irb_maturity_m"] == pytest.approx(expected_m, abs=1e-6), (
            f"CCR-IRB-1: expected irb_maturity_m={expected_m} "
            f"(CRR Art. 162(2)(b): clip(5.0,1,5)), got {row['irb_maturity_m']}."
        )

    def test_ccr_irb1_k_value(self, ccr_irb1_result: dict) -> None:
        """
        Capital requirement k approx 0.069078 (pre-MA, pre-scaling, CRR Art. 153(1)).

        K = LGD * N[(G(PD) + sqrt(R)*G(0.999)) / sqrt(1-R)] - LGD * PD
        with PD=0.0150, LGD=0.45, R=0.176684 (corporate correlation).

        Arrange: corporate F-IRB, PD=0.0150, LGD=0.45, non-SME.
        Act:     full CRR F-IRB pipeline.
        Assert:  k approx 0.069078 (rel tol 1e-4, allowing for floating-point diff).

        References: CRR Art. 153(1): corporate K = LGD * N(inner) - LGD * PD.
        """
        # Arrange
        row = ccr_irb1_result
        expected_k = _EXPECTED["k"]  # 0.06907799

        # Assert
        assert row["k"] == pytest.approx(expected_k, rel=1e-4), (
            f"CCR-IRB-1: expected k approx {expected_k:.6f} "
            f"(CRR Art. 153(1) corporate K, PD=0.0150, LGD=0.45, pre-MA pre-scaling), "
            f"got {row['k']}."
        )

    def test_ccr_irb1_risk_weight_and_rwa(self, ccr_irb1_result: dict) -> None:
        """
        risk_weight approx 1.459292 (145.93%) and rwa_final = risk_weight * ead_ccr.

        risk_weight = k * 12.5 * 1.06 * MA
        = 0.069078 * 12.5 * 1.06 * 1.594361 approx 1.459292

        rwa_final = risk_weight * ead_ccr
        approx 1.459292 * 3_068_443.870 approx 4_477_756.046

        Arrange: F-IRB corporate, k=0.069078, MA=1.594361, scaling=1.06,
                 ead_ccr=3_068_443.870.
        Act:     full CRR F-IRB pipeline.
        Assert:  risk_weight approx 1.459292 (rel 1e-4),
                 rwa_final approx 4_477_756.046 (rel 1e-4).

        References:
            CRR Art. 153(1): risk_weight = K * 12.5 * 1.06 * MA.
            CRR Art. 274(2): rwa_final = risk_weight * EAD_ccr.
        """
        # Arrange
        row = ccr_irb1_result
        expected_rw = _EXPECTED["risk_weight"]  # 1.45929215
        expected_rwa = _EXPECTED["rwa_final"]  # 4477756.045762

        # Assert
        assert row["risk_weight"] == pytest.approx(expected_rw, rel=1e-4), (
            f"CCR-IRB-1: expected risk_weight approx {expected_rw:.6f} "
            f"(k * 12.5 * 1.06 * MA, CRR Art. 153(1)), got {row['risk_weight']}."
        )
        assert row["rwa_final"] == pytest.approx(expected_rwa, rel=1e-4), (
            f"CCR-IRB-1: expected rwa_final approx {expected_rwa:,.3f} "
            f"(= risk_weight * ead_ccr), got {row['rwa_final']:,.3f}."
        )
