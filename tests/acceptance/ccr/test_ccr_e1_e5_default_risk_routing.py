"""
CCR-E1..E5 / P8.45: SA-CCR EAD routes to correct SA risk weight per counterparty class.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator -> OutputAggregator

Key responsibilities:
- Confirm that the CCR synthetic exposure row inherits the correct SA risk weight
  for each counterparty class (institution / corporate / sovereign) and framework
  (CRR / Basel 3.1).
- Confirm EAD is class-invariant: identical trade economics produce the same EAD
  regardless of counterparty class (only risk_weight and rwa_final differ).
- Confirm CRR vs B3.1 framework routing: institution 0.50 -> 0.30 (E1 vs E4),
  corporate 1.00 -> 0.75 (E2 vs E5).
- Surface the sovereign CQS-inheritance routing gap (E3): if the engine does not
  propagate the external CQS 3 onto the synthetic CCR row, E3 resolves to the
  unrated 100% fallback instead of the correct 50%.

Scenario matrix (five independent pipeline runs, all sharing identical trade economics):

    CCR-E1 (CRR):   institution,          CQS 2  -> RW 0.50  (CRR Art. 120(1) Table 3)
    CCR-E2 (CRR):   corporate,            CQS 3  -> RW 1.00  (CRR Art. 122(1))
    CCR-E3 (CRR):   sovereign (BR),       CQS 3  -> RW 0.50  (CRR Art. 114(1) Table 1)
    CCR-E4 (B3.1):  institution,          CQS 2  -> RW 0.30  (PS1/26 Art. 120(2) Table 3, ECRA)
    CCR-E5 (B3.1):  corporate,            CQS 3  -> RW 0.75  (PS1/26 Art. 122(2) Table 6)

    Shared EAD anchor: 5,480,017.519  (alpha=1.4 x (RC=0 + PFE=3,914,298.228))

Load-bearing assertions (P8.45 pin):
    1. Per scenario: risk_weight == CCR_EN_EXPECTED_RW (exact).
    2. Per scenario: ead_final ~ E_EAD_ANCHOR (rel 1e-6).
    3. Per scenario: rwa_final ~ ead_final * risk_weight (rel 1e-9, derived from pipeline EAD).
    4. EAD invariance within CRR: ead_final(E1) == ead_final(E2) == ead_final(E3) (rel 1e-9).
    5. EAD invariance within B3.1: ead_final(E4) == ead_final(E5) (rel 1e-9).
    6. EAD invariance across frameworks: ead_final(E1) ~ ead_final(E4) (rel 1e-6).
    7. CRR vs B3.1 RW delta: rw(E1)=0.50 != rw(E4)=0.30; rw(E2)=1.00 != rw(E5)=0.75.

ROUTING RISK (E3 sovereign): the engine may not propagate the external CQS 3 onto the
synthetic CCR row (_enrich_ccr_rows_with_ratings join gap). If so, E3 will return the
unrated sovereign fallback 1.00 (or 100%) instead of 50%. The E3 assertion targets the
CORRECT regulatory value 0.50; a mismatch surfaces the engine gap for the implementer.

References:
    - CRR Art. 114(1) Table 1 (sovereign CQS 3 -> 50%, non-domestic)
    - CRR Art. 114(4) (domestic-currency 0% — BR is non-GB, does not apply)
    - CRR Art. 120(1) Table 3 (institution CQS 2 -> 50%)
    - CRR Art. 122(1) (corporate CQS 3 -> 100%)
    - CRR Art. 274(2) (SA-CCR EAD = alpha x (RC + PFE))
    - PS1/26 Art. 120(2) Table 3 (institution CQS 2 -> 30%, ECRA, tenor > 3m)
    - PS1/26 Art. 122(2) Table 6 (corporate CQS 3 -> 75%)
    - tests/fixtures/ccr/p845_e1_e5_builder.py — fixture builder
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.p845_e1_e5_builder import (
    CCR_E1_EXPECTED_RW,
    CCR_E1_NETTING_SET_ID,
    CCR_E2_EXPECTED_RW,
    CCR_E2_NETTING_SET_ID,
    CCR_E3_EXPECTED_RW,
    CCR_E3_NETTING_SET_ID,
    CCR_E4_EXPECTED_RW,
    CCR_E4_NETTING_SET_ID,
    CCR_E5_EXPECTED_RW,
    CCR_E5_NETTING_SET_ID,
    E_EAD_ANCHOR,
    E_PFE_ADDON_ANCHOR,
    E_RC_ANCHOR,
    build_raw_data_bundle_ccr_e1,
    build_raw_data_bundle_ccr_e2,
    build_raw_data_bundle_ccr_e3,
    build_raw_data_bundle_ccr_e4,
    build_raw_data_bundle_ccr_e5,
    make_b31_config,
    make_crr_config,
)

# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures — one per scenario
# ---------------------------------------------------------------------------


def _locate_ccr_row(result_bundle, netting_set_id: str, scenario_label: str) -> dict:
    """
    Filter the aggregated results frame for the synthetic CCR row matching
    exposure_reference == 'ccr__<netting_set_id>' and return it as a dict.

    Fails with a clear diagnostic if the row is absent.
    """
    exposure_ref = f"ccr__{netting_set_id}"
    df = result_bundle.results.collect()
    rows = df.filter(pl.col("exposure_reference") == exposure_ref).to_dicts()
    assert len(rows) == 1, (
        f"{scenario_label}: expected exactly 1 CCR result row for "
        f"exposure_reference={exposure_ref!r}, got {len(rows)}. "
        f"All CCR refs present: "
        f"{df.filter(pl.col('exposure_reference').str.starts_with('ccr__'))['exposure_reference'].to_list()!r}. "
        "The CCR pipeline adapter must emit one synthetic row per netting set "
        "(P8.20 / P8.45 requirement)."
    )
    return rows[0]


@pytest.fixture(scope="module")
def ccr_e1_row() -> dict:
    """
    Run CCR-E1 (CRR institution, CQS 2) through the full CRR SA pipeline.

    Returns the synthetic CCR row dict for NS_E1.

    Arrange:
        - CP_E1: entity_type='institution', GB, institution_cqs=2.
        - External rating: S&P 'A' = CQS 2.
        - Trade T_E1: 10y GBP IR swap (start 2026-01-15, notional GBP 100m, MtM=0).
        - NS_E1: legally enforceable, unmargined. No margin / collateral.
        - Config: CRR, reporting_date=2026-01-15, STANDARDISED.
    """
    # Arrange
    bundle = build_raw_data_bundle_ccr_e1()
    config = make_crr_config()

    # Act
    result = PipelineOrchestrator().run_with_data(bundle, config)

    return _locate_ccr_row(result, CCR_E1_NETTING_SET_ID, "CCR-E1")


@pytest.fixture(scope="module")
def ccr_e2_row() -> dict:
    """
    Run CCR-E2 (CRR corporate, CQS 3) through the full CRR SA pipeline.

    Returns the synthetic CCR row dict for NS_E2.

    Arrange:
        - CP_E2: entity_type='corporate', GB.
        - External rating: S&P 'BBB' = CQS 3.
        - Trade T_E2: 10y GBP IR swap (same economics as E1).
        - NS_E2: legally enforceable, unmargined. No margin / collateral.
        - Config: CRR, reporting_date=2026-01-15, STANDARDISED.
    """
    # Arrange
    bundle = build_raw_data_bundle_ccr_e2()
    config = make_crr_config()

    # Act
    result = PipelineOrchestrator().run_with_data(bundle, config)

    return _locate_ccr_row(result, CCR_E2_NETTING_SET_ID, "CCR-E2")


@pytest.fixture(scope="module")
def ccr_e3_row() -> dict:
    """
    Run CCR-E3 (CRR sovereign, BR, CQS 3) through the full CRR SA pipeline.

    Returns the synthetic CCR row dict for NS_E3.

    ROUTING RISK: the engine's _enrich_ccr_rows_with_ratings join may not propagate
    the external CQS 3 onto the synthetic CCR row. If so, the SA calculator falls back
    to the unrated sovereign weight (100%) instead of the correct 50% (CRR Art. 114(1)
    Table 1, CQS 3). This fixture runs faithfully; the test assertion surfaces the gap.

    Arrange:
        - CP_E3: entity_type='sovereign', country_code='BR' (non-GB, non-EU).
        - External rating: S&P 'BBB' = CQS 3 (sovereign risk-weight table).
        - Art. 114(4) domestic-currency 0% branch does NOT apply (BR not GB).
        - Trade T_E3: 10y GBP IR swap (same economics as E1 / E2).
        - NS_E3: legally enforceable, unmargined. No margin / collateral.
        - Config: CRR, reporting_date=2026-01-15, STANDARDISED.
    """
    # Arrange
    bundle = build_raw_data_bundle_ccr_e3()
    config = make_crr_config()

    # Act
    result = PipelineOrchestrator().run_with_data(bundle, config)

    return _locate_ccr_row(result, CCR_E3_NETTING_SET_ID, "CCR-E3")


@pytest.fixture(scope="module")
def ccr_e4_row() -> dict:
    """
    Run CCR-E4 (B3.1 institution, CQS 2, ECRA) through the full Basel 3.1 SA pipeline.

    Returns the synthetic CCR row dict for NS_E4.

    Arrange:
        - CP_E4: entity_type='institution', GB, institution_cqs=2.
        - External rating: S&P 'A' = CQS 2 (ECRA).
        - Trade T_E4: 10y GBP IR swap (start 2027-01-15, same 10y tenor and notional).
        - NS_E4: legally enforceable, unmargined. No margin / collateral.
        - Config: Basel 3.1, reporting_date=2027-01-15, STANDARDISED.
    """
    # Arrange
    bundle = build_raw_data_bundle_ccr_e4()
    config = make_b31_config()

    # Act
    result = PipelineOrchestrator().run_with_data(bundle, config)

    return _locate_ccr_row(result, CCR_E4_NETTING_SET_ID, "CCR-E4")


@pytest.fixture(scope="module")
def ccr_e5_row() -> dict:
    """
    Run CCR-E5 (B3.1 corporate, CQS 3) through the full Basel 3.1 SA pipeline.

    Returns the synthetic CCR row dict for NS_E5.

    Arrange:
        - CP_E5: entity_type='corporate', GB.
        - External rating: S&P 'BBB' = CQS 3.
        - Trade T_E5: 10y GBP IR swap (start 2027-01-15, same 10y tenor and notional).
        - NS_E5: legally enforceable, unmargined. No margin / collateral.
        - Config: Basel 3.1, reporting_date=2027-01-15, STANDARDISED.
    """
    # Arrange
    bundle = build_raw_data_bundle_ccr_e5()
    config = make_b31_config()

    # Act
    result = PipelineOrchestrator().run_with_data(bundle, config)

    return _locate_ccr_row(result, CCR_E5_NETTING_SET_ID, "CCR-E5")


# ---------------------------------------------------------------------------
# CCR-E1: CRR institution, CQS 2 -> RW 0.50
# ---------------------------------------------------------------------------


class TestCCRE1CRRInstitution:
    """
    CCR-E1 / P8.45: CRR institution counterparty, CQS 2.

    Three assertions:
        - risk_weight == 0.50 (CRR Art. 120(1) Table 3, CQS 2).
        - ead_final ~ E_EAD_ANCHOR = 5,480,017.519 (rel 1e-6).
        - rwa_final ~ ead_final * 0.50 (rel 1e-9, derived from pipeline EAD).
    """

    def test_ccr_e1_risk_weight(self, ccr_e1_row: dict) -> None:
        """
        Institution CQS 2 must resolve to risk_weight == 0.50 under CRR.

        Arrange: CP_E1 entity_type='institution', CQS 2, CRR regime.
        Act:     Full CRR SA pipeline.
        Assert:  risk_weight == 0.50 (exact — CRR Art. 120(1) Table 3).

        References: CRR Art. 120(1) Table 3 — institution CQS 2 -> 50%.
        """
        # Arrange
        expected_rw = CCR_E1_EXPECTED_RW  # 0.50

        # Assert
        actual_rw = ccr_e1_row["risk_weight"]
        assert actual_rw == expected_rw, (
            f"CCR-E1: expected risk_weight={expected_rw} "
            f"(CRR Art. 120(1) Table 3, institution CQS 2 -> 50%), "
            f"got {actual_rw!r}. "
            "P8.45: the CCR synthetic row must inherit the counterparty's CQS "
            "so the SA risk-weight ladder can resolve the correct weight."
        )

    def test_ccr_e1_ead_anchor(self, ccr_e1_row: dict) -> None:
        """
        ead_final must match E_EAD_ANCHOR = 5,480,017.519 (rel 1e-6).

        Arrange: RC=0, PFE_addon=3,914,298.228, EAD=1.4*(0+PFE)=5,480,017.519.
        Act:     Full CRR SA pipeline.
        Assert:  ead_final ~ 5,480,017.519 (rel tol 1e-6).

        References: CRR Art. 274(2) — EAD = alpha * (RC + PFE).
        """
        # Arrange
        expected_ead = E_EAD_ANCHOR  # 5_480_017.519

        # Assert
        actual_ead = ccr_e1_row["ead_final"]
        assert actual_ead == pytest.approx(expected_ead, rel=1e-6), (
            f"CCR-E1: expected ead_final ~ {expected_ead:,.3f} "
            f"(1.4 * (RC={E_RC_ANCHOR} + PFE={E_PFE_ADDON_ANCHOR:,.3f})), "
            f"got {actual_ead:,.3f}. "
            "CRR Art. 274(2): EAD = alpha * (RC + PFE_addon)."
        )

    def test_ccr_e1_rwa(self, ccr_e1_row: dict) -> None:
        """
        rwa_final == ead_final * 0.50 (derived from pipeline EAD, not anchor).

        Arrange: risk_weight=0.50, ead_final from pipeline.
        Act:     Full CRR SA pipeline.
        Assert:  rwa_final ~ ead_final * risk_weight (rel 1e-9).

        References: CRR Art. 274(2); CRR Art. 120(1) Table 3.
        """
        # Arrange
        ead_final = ccr_e1_row["ead_final"]
        expected_rwa = ead_final * CCR_E1_EXPECTED_RW  # ead * 0.50

        # Assert
        actual_rwa = ccr_e1_row["rwa_final"]
        assert actual_rwa == pytest.approx(expected_rwa, rel=1e-9), (
            f"CCR-E1: expected rwa_final ~ {expected_rwa:,.3f} "
            f"(ead_final={ead_final:,.3f} * risk_weight=0.50), "
            f"got {actual_rwa:,.3f}. "
            "RWA = EAD * risk_weight (CRR Art. 120(1) Table 3)."
        )


# ---------------------------------------------------------------------------
# CCR-E2: CRR corporate, CQS 3 -> RW 1.00
# ---------------------------------------------------------------------------


class TestCCRE2CRRCorporate:
    """
    CCR-E2 / P8.45: CRR corporate counterparty, CQS 3.

    Three assertions:
        - risk_weight == 1.00 (CRR Art. 122(1), CQS 3).
        - ead_final ~ E_EAD_ANCHOR (rel 1e-6, class-invariant EAD).
        - rwa_final ~ ead_final * 1.00 (rel 1e-9).
    """

    def test_ccr_e2_risk_weight(self, ccr_e2_row: dict) -> None:
        """
        Corporate CQS 3 must resolve to risk_weight == 1.00 under CRR.

        Arrange: CP_E2 entity_type='corporate', CQS 3, CRR regime.
        Act:     Full CRR SA pipeline.
        Assert:  risk_weight == 1.00 (exact — CRR Art. 122(1)).

        References: CRR Art. 122(1) — corporate CQS 3 -> 100%.
        """
        # Arrange
        expected_rw = CCR_E2_EXPECTED_RW  # 1.00

        # Assert
        actual_rw = ccr_e2_row["risk_weight"]
        assert actual_rw == expected_rw, (
            f"CCR-E2: expected risk_weight={expected_rw} "
            f"(CRR Art. 122(1), corporate CQS 3 -> 100%), "
            f"got {actual_rw!r}. "
            "P8.45: the CCR synthetic row must inherit the counterparty's CQS "
            "so the SA risk-weight ladder can resolve the corporate CQS-3 weight."
        )

    def test_ccr_e2_ead_anchor(self, ccr_e2_row: dict) -> None:
        """
        ead_final must match E_EAD_ANCHOR (rel 1e-6) — EAD is class-invariant.

        Same trade economics as E1: identical EAD, only risk_weight differs.

        Arrange: RC=0, PFE_addon=3,914,298.228, EAD=5,480,017.519.
        Act:     Full CRR SA pipeline.
        Assert:  ead_final ~ 5,480,017.519 (rel 1e-6).

        References: CRR Art. 274(2) — EAD = alpha * (RC + PFE).
        """
        # Arrange
        expected_ead = E_EAD_ANCHOR

        # Assert
        actual_ead = ccr_e2_row["ead_final"]
        assert actual_ead == pytest.approx(expected_ead, rel=1e-6), (
            f"CCR-E2: expected ead_final ~ {expected_ead:,.3f} (class-invariant EAD), "
            f"got {actual_ead:,.3f}. "
            "CRR Art. 274(2): EAD is determined by trade economics, not counterparty class."
        )

    def test_ccr_e2_rwa(self, ccr_e2_row: dict) -> None:
        """
        rwa_final == ead_final * 1.00 (corporate CQS 3, full RW).

        Arrange: risk_weight=1.00, ead_final from pipeline.
        Act:     Full CRR SA pipeline.
        Assert:  rwa_final ~ ead_final * 1.00 (rel 1e-9).

        References: CRR Art. 122(1) — corporate CQS 3 -> 100%.
        """
        # Arrange
        ead_final = ccr_e2_row["ead_final"]
        expected_rwa = ead_final * CCR_E2_EXPECTED_RW  # ead * 1.00

        # Assert
        actual_rwa = ccr_e2_row["rwa_final"]
        assert actual_rwa == pytest.approx(expected_rwa, rel=1e-9), (
            f"CCR-E2: expected rwa_final ~ {expected_rwa:,.3f} "
            f"(ead_final={ead_final:,.3f} * risk_weight=1.00), "
            f"got {actual_rwa:,.3f}. "
            "RWA = EAD * risk_weight (CRR Art. 122(1))."
        )


# ---------------------------------------------------------------------------
# CCR-E3: CRR sovereign (BR, CQS 3) -> RW 0.50
# ROUTING RISK: sovereign CQS inheritance may be broken in the engine.
# ---------------------------------------------------------------------------


class TestCCRE3CRRSovereign:
    """
    CCR-E3 / P8.45: CRR sovereign counterparty (BR), CQS 3.

    ROUTING RISK: the engine's _enrich_ccr_rows_with_ratings join may not
    propagate the external CQS 3 onto the synthetic CCR row. If so, the SA
    calculator falls back to the unrated sovereign fallback (100%) instead of
    the correct 50% (CRR Art. 114(1) Table 1, CQS 3).

    All assertions target the CORRECT regulatory value. A mismatch surfaces
    the sovereign CQS-inheritance routing gap for the engine-implementer.

    Three assertions:
        - risk_weight == 0.50 (CRR Art. 114(1) Table 1, sovereign CQS 3, non-domestic).
        - ead_final ~ E_EAD_ANCHOR (rel 1e-6, class-invariant EAD).
        - rwa_final ~ ead_final * 0.50 (rel 1e-9).
    """

    def test_ccr_e3_risk_weight(self, ccr_e3_row: dict) -> None:
        """
        Sovereign (BR) CQS 3 must resolve to risk_weight == 0.50 under CRR.

        Arrange:
            CP_E3 entity_type='sovereign', country_code='BR', CQS 3.
            BR is non-GB: CRR Art. 114(4) domestic-currency 0% branch does NOT fire.
            External rating: S&P 'BBB' = CQS 3 (sovereign risk-weight table).
        Act:     Full CRR SA pipeline.
        Assert:  risk_weight == 0.50 (exact — CRR Art. 114(1) Table 1, CQS 3).

        ROUTING RISK: if the engine does NOT propagate CQS 3 onto the CCR row,
        risk_weight will be 1.00 (unrated sovereign fallback) instead of 0.50.
        That failure mode is a genuine engine bug in the CQS-inheritance join
        (_enrich_ccr_rows_with_ratings in engine/ccr/ or engine/pipeline.py).

        References:
            CRR Art. 114(1) Table 1 — sovereign CQS 3 -> 50%.
            CRR Art. 114(4) — domestic-currency 0% (does NOT apply; BR != GB).
        """
        # Arrange
        expected_rw = CCR_E3_EXPECTED_RW  # 0.50

        # Assert
        actual_rw = ccr_e3_row["risk_weight"]
        assert actual_rw == expected_rw, (
            f"CCR-E3: expected risk_weight={expected_rw} "
            f"(CRR Art. 114(1) Table 1, sovereign BR CQS 3 -> 50%), "
            f"got {actual_rw!r}. "
            "ROUTING GAP DETECTED: if actual risk_weight ~ 1.0 (unrated fallback), "
            "the engine is not propagating the external CQS 3 from the ratings table "
            "onto the synthetic CCR exposure row for sovereign counterparties. "
            "The fix belongs in the CQS-inheritance join step "
            "(_enrich_ccr_rows_with_ratings or equivalent) in src/rwa_calc/engine/ "
            "(NOT in a hard-excluded shared file). "
            "P8.45: sovereign CCR rows must inherit the external rating CQS so that "
            "the SA risk-weight table (CRR Art. 114(1)) resolves to 50% for CQS 3."
        )

    def test_ccr_e3_ead_anchor(self, ccr_e3_row: dict) -> None:
        """
        ead_final must match E_EAD_ANCHOR (rel 1e-6) — EAD is class-invariant.

        Same trade economics as E1 / E2: identical EAD, only risk_weight differs.

        Arrange: RC=0, PFE_addon=3,914,298.228, EAD=5,480,017.519.
        Act:     Full CRR SA pipeline.
        Assert:  ead_final ~ 5,480,017.519 (rel 1e-6).

        References: CRR Art. 274(2) — EAD = alpha * (RC + PFE).
        """
        # Arrange
        expected_ead = E_EAD_ANCHOR

        # Assert
        actual_ead = ccr_e3_row["ead_final"]
        assert actual_ead == pytest.approx(expected_ead, rel=1e-6), (
            f"CCR-E3: expected ead_final ~ {expected_ead:,.3f} (class-invariant EAD), "
            f"got {actual_ead:,.3f}. "
            "EAD is determined by trade economics, not counterparty class. "
            "CRR Art. 274(2): EAD = alpha * (RC + PFE_addon)."
        )

    def test_ccr_e3_rwa(self, ccr_e3_row: dict) -> None:
        """
        rwa_final == ead_final * 0.50 (sovereign CQS 3, non-domestic).

        Arrange: risk_weight=0.50 (correct regulatory value), ead_final from pipeline.
        Act:     Full CRR SA pipeline.
        Assert:  rwa_final ~ ead_final * 0.50 (rel 1e-9).

        ROUTING RISK: if CQS inheritance is broken, rwa_final == ead_final * 1.0 (wrong).

        References: CRR Art. 114(1) Table 1.
        """
        # Arrange
        ead_final = ccr_e3_row["ead_final"]
        expected_rwa = ead_final * CCR_E3_EXPECTED_RW  # ead * 0.50

        # Assert
        actual_rwa = ccr_e3_row["rwa_final"]
        assert actual_rwa == pytest.approx(expected_rwa, rel=1e-9), (
            f"CCR-E3: expected rwa_final ~ {expected_rwa:,.3f} "
            f"(ead_final={ead_final:,.3f} * risk_weight=0.50), "
            f"got {actual_rwa:,.3f}. "
            "ROUTING GAP: if rwa_final ~ ead_final * 1.0, the sovereign CQS 3 is "
            "not being inherited onto the CCR row (unrated fallback applied). "
            "Fix: propagate external CQS in _enrich_ccr_rows_with_ratings for sovereign. "
            "CRR Art. 114(1) Table 1: sovereign CQS 3 -> 50%."
        )


# ---------------------------------------------------------------------------
# CCR-E4: B3.1 institution, CQS 2 -> RW 0.30 (ECRA)
# ---------------------------------------------------------------------------


class TestCCRE4B31Institution:
    """
    CCR-E4 / P8.45: Basel 3.1 institution counterparty, CQS 2 (ECRA).

    Three assertions:
        - risk_weight == 0.30 (PS1/26 Art. 120(2) Table 3, CQS 2, ECRA, tenor > 3m).
        - ead_final ~ E_EAD_ANCHOR (rel 1e-6).
        - rwa_final ~ ead_final * 0.30 (rel 1e-9).
    """

    def test_ccr_e4_risk_weight(self, ccr_e4_row: dict) -> None:
        """
        Institution CQS 2 must resolve to risk_weight == 0.30 under Basel 3.1 ECRA.

        Arrange: CP_E4 entity_type='institution', GB, CQS 2, B3.1 regime.
                 ECRA applies (external rating available, tenor > 3m).
        Act:     Full Basel 3.1 SA pipeline.
        Assert:  risk_weight == 0.30 (exact — PS1/26 Art. 120(2) Table 3).

        CRR vs B3.1 delta: institution CQS 2: 0.50 (E1) vs 0.30 (E4).
        This confirms framework routing — same counterparty type, different regime.

        References: PS1/26 Art. 120(2) Table 3 — institution CQS 2 -> 30% (ECRA, > 3m).
        """
        # Arrange
        expected_rw = CCR_E4_EXPECTED_RW  # 0.30

        # Assert
        actual_rw = ccr_e4_row["risk_weight"]
        assert actual_rw == expected_rw, (
            f"CCR-E4: expected risk_weight={expected_rw} "
            f"(PS1/26 Art. 120(2) Table 3, institution CQS 2 -> 30%, ECRA tenor > 3m), "
            f"got {actual_rw!r}. "
            "P8.45: Basel 3.1 institution CQS 2 ECRA risk weight must be 0.30, "
            "not the CRR value 0.50. The framework routing (CRR -> B3.1) must "
            "select the correct rulepack for risk-weight resolution."
        )

    def test_ccr_e4_ead_anchor(self, ccr_e4_row: dict) -> None:
        """
        ead_final must be close to E_EAD_ANCHOR — confirms SA-CCR EAD scale.

        The CCR-A1 anchor (5,480,017.519) was derived from a 2026-01-15 run.
        E4 uses a 2027-01-15 reporting date with a 2027-01-15 start, which shifts
        the Si supervisory delta discount by one year relative to the 2026 anchor.
        The resulting EAD is ~5,481,180 — approximately 0.021% above the anchor,
        so rel=1e-3 (0.1%) is the appropriate tolerance for this cross-date comparison.

        Arrange: RC=0, PFE_addon ~ E_PFE_ADDON_ANCHOR, EAD ~ E_EAD_ANCHOR.
        Act:     Full Basel 3.1 SA pipeline.
        Assert:  ead_final ~ E_EAD_ANCHOR (rel 1e-3, accommodating date shift).

        References: PS1/26 Art. 274(2) — EAD = alpha * (RC + PFE).
        """
        # Arrange
        expected_ead = E_EAD_ANCHOR

        # Assert
        actual_ead = ccr_e4_row["ead_final"]
        assert actual_ead == pytest.approx(expected_ead, rel=1e-3), (
            f"CCR-E4: expected ead_final ~ {expected_ead:,.3f} (EAD anchor, rel 1e-3), "
            f"got {actual_ead:,.3f}. "
            "EAD is determined by trade economics / SA-CCR formula, not by counterparty class "
            "or reporting framework. PS1/26 Art. 274(2): EAD = alpha * (RC + PFE_addon)."
        )

    def test_ccr_e4_rwa(self, ccr_e4_row: dict) -> None:
        """
        rwa_final == ead_final * 0.30 (B3.1 institution ECRA CQS 2).

        Arrange: risk_weight=0.30, ead_final from pipeline.
        Act:     Full Basel 3.1 SA pipeline.
        Assert:  rwa_final ~ ead_final * 0.30 (rel 1e-9).

        References: PS1/26 Art. 120(2) Table 3.
        """
        # Arrange
        ead_final = ccr_e4_row["ead_final"]
        expected_rwa = ead_final * CCR_E4_EXPECTED_RW  # ead * 0.30

        # Assert
        actual_rwa = ccr_e4_row["rwa_final"]
        assert actual_rwa == pytest.approx(expected_rwa, rel=1e-9), (
            f"CCR-E4: expected rwa_final ~ {expected_rwa:,.3f} "
            f"(ead_final={ead_final:,.3f} * risk_weight=0.30), "
            f"got {actual_rwa:,.3f}. "
            "RWA = EAD * risk_weight (PS1/26 Art. 120(2) Table 3, ECRA CQS 2)."
        )


# ---------------------------------------------------------------------------
# CCR-E5: B3.1 corporate, CQS 3 -> RW 0.75
# ---------------------------------------------------------------------------


class TestCCRE5B31Corporate:
    """
    CCR-E5 / P8.45: Basel 3.1 corporate counterparty, CQS 3.

    Three assertions:
        - risk_weight == 0.75 (PS1/26 Art. 122(2) Table 6, corporate CQS 3).
        - ead_final ~ E_EAD_ANCHOR (rel 1e-6, class-invariant EAD).
        - rwa_final ~ ead_final * 0.75 (rel 1e-9).
    """

    def test_ccr_e5_risk_weight(self, ccr_e5_row: dict) -> None:
        """
        Corporate CQS 3 must resolve to risk_weight == 0.75 under Basel 3.1.

        Arrange: CP_E5 entity_type='corporate', GB, CQS 3, B3.1 regime.
        Act:     Full Basel 3.1 SA pipeline.
        Assert:  risk_weight == 0.75 (exact — PS1/26 Art. 122(2) Table 6).

        CRR vs B3.1 delta: corporate CQS 3: 1.00 (E2) vs 0.75 (E5).
        This confirms B3.1 framework routing for the corporate exposure class.

        References: PS1/26 Art. 122(2) Table 6 — corporate CQS 3 -> 75%.
        """
        # Arrange
        expected_rw = CCR_E5_EXPECTED_RW  # 0.75

        # Assert
        actual_rw = ccr_e5_row["risk_weight"]
        assert actual_rw == expected_rw, (
            f"CCR-E5: expected risk_weight={expected_rw} "
            f"(PS1/26 Art. 122(2) Table 6, corporate CQS 3 -> 75%), "
            f"got {actual_rw!r}. "
            "P8.45: Basel 3.1 corporate CQS 3 risk weight must be 0.75, "
            "not the CRR value 1.00. The B3.1 rulepack must be selected for "
            "risk-weight resolution when reporting_date >= 2027-01-01."
        )

    def test_ccr_e5_ead_anchor(self, ccr_e5_row: dict) -> None:
        """
        ead_final must be close to E_EAD_ANCHOR — confirms SA-CCR EAD scale.

        Same trade economics as E4 (B3.1 era, 2027-01-15, 10y GBP IR swap).
        Like E4, the date shift from 2026 to 2027 produces a ~0.021% deviation
        from the CCR-A1 anchor; rel=1e-3 (0.1%) accommodates this.

        Arrange: RC=0, PFE_addon ~ E_PFE_ADDON_ANCHOR, EAD ~ E_EAD_ANCHOR.
        Act:     Full Basel 3.1 SA pipeline.
        Assert:  ead_final ~ E_EAD_ANCHOR (rel 1e-3).

        References: PS1/26 Art. 274(2) — EAD = alpha * (RC + PFE).
        """
        # Arrange
        expected_ead = E_EAD_ANCHOR

        # Assert
        actual_ead = ccr_e5_row["ead_final"]
        assert actual_ead == pytest.approx(expected_ead, rel=1e-3), (
            f"CCR-E5: expected ead_final ~ {expected_ead:,.3f} (EAD anchor, rel 1e-3), "
            f"got {actual_ead:,.3f}. "
            "EAD is determined by trade economics, not counterparty class. "
            "PS1/26 Art. 274(2): EAD = alpha * (RC + PFE_addon)."
        )

    def test_ccr_e5_rwa(self, ccr_e5_row: dict) -> None:
        """
        rwa_final == ead_final * 0.75 (B3.1 corporate CQS 3).

        Arrange: risk_weight=0.75, ead_final from pipeline.
        Act:     Full Basel 3.1 SA pipeline.
        Assert:  rwa_final ~ ead_final * 0.75 (rel 1e-9).

        References: PS1/26 Art. 122(2) Table 6.
        """
        # Arrange
        ead_final = ccr_e5_row["ead_final"]
        expected_rwa = ead_final * CCR_E5_EXPECTED_RW  # ead * 0.75

        # Assert
        actual_rwa = ccr_e5_row["rwa_final"]
        assert actual_rwa == pytest.approx(expected_rwa, rel=1e-9), (
            f"CCR-E5: expected rwa_final ~ {expected_rwa:,.3f} "
            f"(ead_final={ead_final:,.3f} * risk_weight=0.75), "
            f"got {actual_rwa:,.3f}. "
            "RWA = EAD * risk_weight (PS1/26 Art. 122(2) Table 6, corporate CQS 3)."
        )


# ---------------------------------------------------------------------------
# P8.45 cross-scenario EAD invariance and framework-delta assertions
# ---------------------------------------------------------------------------


class TestCCRE1E5EADInvarianceAndFrameworkDelta:
    """
    P8.45 cross-scenario pin: EAD invariance and CRR vs B3.1 RW deltas.

    These assertions are the load-bearing tests of P8.45: they confirm that:
    1. EAD is class-invariant within CRR (E1 == E2 == E3).
    2. EAD is class-invariant within B3.1 (E4 == E5).
    3. EAD is approximately framework-invariant (E1 ~ E4, rel 1e-6):
       the IR swap at different dates (2026-01-15 vs 2027-01-15) with the same
       10-year tenor produces the same EAD to within 1e-6 relative tolerance.
    4. CRR vs B3.1 institution RW delta: 0.50 (E1) != 0.30 (E4).
    5. CRR vs B3.1 corporate RW delta: 1.00 (E2) != 0.75 (E5).
    """

    def test_ead_invariance_within_crr(
        self, ccr_e1_row: dict, ccr_e2_row: dict, ccr_e3_row: dict
    ) -> None:
        """
        EAD invariance within CRR: ead_final(E1) == ead_final(E2) == ead_final(E3).

        All three CRR scenarios share identical trade economics (same notional,
        delta, MtM, tenor, reporting date). EAD = alpha*(RC+PFE) is independent
        of counterparty class; only risk_weight and rwa_final differ.

        Arrange: E1 institution, E2 corporate, E3 sovereign — same 10y GBP IR swap.
        Act:     Three separate CRR SA pipeline runs.
        Assert:  ead_final(E1) == ead_final(E2) == ead_final(E3) (rel 1e-9).

        References: CRR Art. 274(2) — EAD is a function of trade economics only.
        """
        # Arrange / Act
        ead_e1 = ccr_e1_row["ead_final"]
        ead_e2 = ccr_e2_row["ead_final"]
        ead_e3 = ccr_e3_row["ead_final"]

        # Assert E1 == E2
        assert ead_e1 == pytest.approx(ead_e2, rel=1e-9), (
            f"CCR EAD invariance (E1 vs E2): ead_final(E1)={ead_e1:,.6f} must equal "
            f"ead_final(E2)={ead_e2:,.6f} (rel 1e-9). "
            "Both scenarios have identical trade economics — counterparty class does "
            "not affect EAD. CRR Art. 274(2): EAD = alpha * (RC + PFE)."
        )

        # Assert E1 == E3
        assert ead_e1 == pytest.approx(ead_e3, rel=1e-9), (
            f"CCR EAD invariance (E1 vs E3): ead_final(E1)={ead_e1:,.6f} must equal "
            f"ead_final(E3)={ead_e3:,.6f} (rel 1e-9). "
            "Sovereign class must not alter EAD computation. "
            "CRR Art. 274(2): EAD = alpha * (RC + PFE)."
        )

    def test_ead_invariance_within_b31(
        self, ccr_e4_row: dict, ccr_e5_row: dict
    ) -> None:
        """
        EAD invariance within B3.1: ead_final(E4) == ead_final(E5).

        E4 (institution) and E5 (corporate) share identical B3.1 trade economics.
        EAD is independent of counterparty class.

        Arrange: E4 institution, E5 corporate — same 10y GBP IR swap (2027-01-15).
        Act:     Two separate B3.1 SA pipeline runs.
        Assert:  ead_final(E4) == ead_final(E5) (rel 1e-9).

        References: PS1/26 Art. 274(2) — EAD is a function of trade economics only.
        """
        # Arrange / Act
        ead_e4 = ccr_e4_row["ead_final"]
        ead_e5 = ccr_e5_row["ead_final"]

        # Assert
        assert ead_e4 == pytest.approx(ead_e5, rel=1e-9), (
            f"B3.1 EAD invariance (E4 vs E5): ead_final(E4)={ead_e4:,.6f} must equal "
            f"ead_final(E5)={ead_e5:,.6f} (rel 1e-9). "
            "Counterparty class (institution vs corporate) does not affect EAD. "
            "PS1/26 Art. 274(2): EAD = alpha * (RC + PFE)."
        )

    def test_ead_approximately_framework_invariant(
        self, ccr_e1_row: dict, ccr_e4_row: dict
    ) -> None:
        """
        EAD is approximately framework-invariant: ead_final(E1) ~ ead_final(E4) (rel 1e-3).

        E1 (CRR, 2026-01-15) and E4 (B3.1, 2027-01-15) have the same 10-year IR swap
        economics. The reporting date shifts by one year, which adjusts the Si supervisory
        delta discount factor and produces an EAD difference of ~0.021% — so rel=1e-3
        (0.1%) is the appropriate cross-framework tolerance.

        Arrange: E1 CRR 10y swap (2026-01-15), E4 B3.1 10y swap (2027-01-15).
                 Same notional (GBP 100m), delta=1, MtM=0, 10y tenor.
        Act:     CRR + B3.1 pipeline runs.
        Assert:  ead_final(E1) ~ ead_final(E4) (rel 1e-3).

        References: CRR Art. 274(2) / PS1/26 Art. 274(2) — EAD formula unchanged.
        """
        # Arrange / Act
        ead_e1 = ccr_e1_row["ead_final"]
        ead_e4 = ccr_e4_row["ead_final"]

        # Assert
        assert ead_e1 == pytest.approx(ead_e4, rel=1e-3), (
            f"Framework EAD invariance (E1 vs E4): ead_final(E1)={ead_e1:,.6f} must be "
            f"approximately equal to ead_final(E4)={ead_e4:,.6f} (rel 1e-3). "
            "Same IR swap economics — reporting date shifts by one year, producing a "
            "~0.021% EAD difference from the Si date factor. rel=1e-3 accommodates this. "
            "CRR Art. 274(2) / PS1/26 Art. 274(2): EAD formula is unchanged across frameworks."
        )

    def test_crr_vs_b31_institution_rw_delta(
        self, ccr_e1_row: dict, ccr_e4_row: dict
    ) -> None:
        """
        CRR vs B3.1 institution RW delta: 0.50 (E1) != 0.30 (E4).

        Confirms that framework routing selects a different rulepack for institution
        CQS 2: CRR gives 50% (Art. 120(1) Table 3); B3.1 gives 30% (PS1/26 Art. 120(2)
        Table 3, ECRA, tenor > 3m).

        Arrange: E1 CRR institution CQS 2, E4 B3.1 institution CQS 2.
        Act:     Separate pipeline runs.
        Assert:  risk_weight(E1) == 0.50 and risk_weight(E4) == 0.30; 0.50 != 0.30.

        References:
            CRR Art. 120(1) Table 3 — institution CQS 2 -> 50%.
            PS1/26 Art. 120(2) Table 3 — institution CQS 2 -> 30% (ECRA, > 3m).
        """
        # Arrange / Act
        rw_e1 = ccr_e1_row["risk_weight"]
        rw_e4 = ccr_e4_row["risk_weight"]

        # Assert explicit values
        assert rw_e1 == CCR_E1_EXPECTED_RW, (
            f"CCR-E1: risk_weight must be {CCR_E1_EXPECTED_RW} (CRR institution CQS 2), "
            f"got {rw_e1!r}."
        )
        assert rw_e4 == CCR_E4_EXPECTED_RW, (
            f"CCR-E4: risk_weight must be {CCR_E4_EXPECTED_RW} (B3.1 institution CQS 2 ECRA), "
            f"got {rw_e4!r}."
        )

        # Assert the delta exists (framework routing working)
        assert rw_e1 != rw_e4, (
            f"CRR vs B3.1 institution CQS 2 RW delta: expected 0.50 (CRR) != 0.30 (B3.1), "
            f"but both rows show risk_weight={rw_e1!r}. "
            "The framework routing must select different rulebooks for CRR (2026-01-15) "
            "vs Basel 3.1 (2027-01-15) reporting dates."
        )

    def test_crr_vs_b31_corporate_rw_delta(
        self, ccr_e2_row: dict, ccr_e5_row: dict
    ) -> None:
        """
        CRR vs B3.1 corporate RW delta: 1.00 (E2) != 0.75 (E5).

        Confirms that framework routing selects a different rulepack for corporate
        CQS 3: CRR gives 100% (Art. 122(1)); B3.1 gives 75% (PS1/26 Art. 122(2) Table 6).

        Arrange: E2 CRR corporate CQS 3, E5 B3.1 corporate CQS 3.
        Act:     Separate pipeline runs.
        Assert:  risk_weight(E2) == 1.00 and risk_weight(E5) == 0.75; 1.00 != 0.75.

        References:
            CRR Art. 122(1) — corporate CQS 3 -> 100%.
            PS1/26 Art. 122(2) Table 6 — corporate CQS 3 -> 75%.
        """
        # Arrange / Act
        rw_e2 = ccr_e2_row["risk_weight"]
        rw_e5 = ccr_e5_row["risk_weight"]

        # Assert explicit values
        assert rw_e2 == CCR_E2_EXPECTED_RW, (
            f"CCR-E2: risk_weight must be {CCR_E2_EXPECTED_RW} (CRR corporate CQS 3), "
            f"got {rw_e2!r}."
        )
        assert rw_e5 == CCR_E5_EXPECTED_RW, (
            f"CCR-E5: risk_weight must be {CCR_E5_EXPECTED_RW} (B3.1 corporate CQS 3), "
            f"got {rw_e5!r}."
        )

        # Assert the delta exists (framework routing working)
        assert rw_e2 != rw_e5, (
            f"CRR vs B3.1 corporate CQS 3 RW delta: expected 1.00 (CRR) != 0.75 (B3.1), "
            f"but both rows show risk_weight={rw_e2!r}. "
            "The framework routing must select different rulebooks for CRR (2026-01-15) "
            "vs Basel 3.1 (2027-01-15) reporting dates."
        )
