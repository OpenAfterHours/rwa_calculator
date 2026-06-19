"""
P8.44 regression pin: engine always applies full SA-CCR — Simplified (Art. 281)
and OEM (Art. 282) fall-through guards.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator -> OutputAggregator

Key responsibilities:
- Pin that ``ccr_method == "sa_ccr"`` for all three CCR-D scenarios (not
  "simplified_sa_ccr" or "oem").
- Pin that unmargined at-par swaps yield pfe_multiplier == 1.0 (cap binds)
  and rc_unmargined == 0.0, exactly as full SA-CCR requires.
- Pin the LOAD-BEARING CCR-D3 discriminator: an OTM margined swap whose
  pfe_multiplier drops to 0.20816907251400474.  Simplified SA-CCR (Art. 281)
  forces the multiplier to 1.0, which would produce ead_final = 4,794,005.256
  instead of 3,492,231.049275926 — the wrong value is asserted NOT to match.

Scenarios:
    CCR-D1: unmargined 10-year GBP IR swap, MtM=0  (mirrors CCR-A1 economics)
    CCR-D2: unmargined 1-year USD/GBP FX forward, MtM=0  (mirrors CCR-A2)
    CCR-D3: margined 10-year GBP IR swap, MtM=-4m  (mirrors CCR-A13, load-bearing)

Shared counterparty CP-D-001: institution, GB, CQS 2 → 50% SA risk weight.

Note — green-on-arrival regression guard:
    The P8.1-P8.40 CCR engine already applies full SA-CCR with no Simplified/OEM
    branch.  All tests in this module are expected to PASS on first run.  They
    become RED if a developer inadvertently introduces an Art.281 / Art.282 branch
    that changes pfe_multiplier, EAD, or RWA.

References:
    - CRR Art. 273a(1)/(2) — Simplified SA-CCR eligibility (absent from engine)
    - CRR Art. 274(2)      — EAD = alpha × (RC + PFE), alpha = 1.4
    - CRR Art. 275(1)      — unmargined RC = max(V - C, 0)
    - CRR Art. 275(2)      — margined RC = max(V - C, TH + MTA - NICA, 0)
    - CRR Art. 278(3)      — PFE multiplier (sub-unity for OTM positions)
    - CRR Art. 279b        — PFE add-on (IR + FX asset classes)
    - CRR Art. 279c(1)     — unmargined MF = sqrt(min(M, 1y) / 1y)
    - CRR Art. 281         — Simplified SA-CCR (NOT applied — multiplier stays sub-unity)
    - CRR Art. 282         — OEM (NOT applied)
    - CRR Art. 120(1) Table 3 — institution CQS 2 → 50% SA risk weight
    - tests/fixtures/ccr/golden_ccr_d1_d3.py — CCR-D1/D2/D3 fixture builders
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.golden_ccr_d1_d3 import (
    CCR_D1_EXPECTED_CCR_METHOD,
    CCR_D1_EXPECTED_EAD,
    CCR_D1_EXPECTED_PFE_ADDON,
    CCR_D1_EXPECTED_PFE_MULTIPLIER,
    CCR_D1_EXPECTED_RC_UNMARGINED,
    CCR_D1_EXPECTED_RWA,
    CCR_D1_EXPOSURE_REFERENCE,
    CCR_D2_EXPECTED_CCR_METHOD,
    CCR_D2_EXPECTED_EAD,
    CCR_D2_EXPECTED_PFE_ADDON,
    CCR_D2_EXPECTED_PFE_MULTIPLIER,
    CCR_D2_EXPECTED_RWA,
    CCR_D2_EXPOSURE_REFERENCE,
    CCR_D3_EXPECTED_CCR_METHOD,
    CCR_D3_EXPECTED_EAD,
    CCR_D3_EXPECTED_PFE_ADDON,
    CCR_D3_EXPECTED_PFE_MULTIPLIER,
    CCR_D3_EXPECTED_RC_MARGINED,
    CCR_D3_EXPECTED_RWA,
    CCR_D3_EXPOSURE_REFERENCE,
    CCR_D3_WRONG_SIMPLIFIED_EAD,
    build_raw_data_bundle_ccr_d1,
    build_raw_data_bundle_ccr_d2,
    build_raw_data_bundle_ccr_d3,
)

# ---------------------------------------------------------------------------
# Shared pipeline config
# ---------------------------------------------------------------------------

#: Reporting date — CRR era, matches CCR-A1/A2/A13 confirmed runs.
_REPORTING_DATE: date = date(2026, 1, 15)


def _make_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures
# ---------------------------------------------------------------------------


def _locate_ccr_row(result_bundle, exposure_ref: str, scenario_label: str) -> dict:
    """
    Locate the single synthetic CCR exposure row for the given netting-set reference.

    The pipeline emits one row per netting set keyed:
        exposure_reference == "ccr__<netting_set_id>"

    Fails with a clear assertion message if the row is absent or duplicated.
    """
    df = result_bundle.results.collect()
    rows = df.filter(pl.col("exposure_reference") == exposure_ref).to_dicts()
    assert len(rows) == 1, (
        f"{scenario_label}: expected exactly 1 CCR exposure row with "
        f"exposure_reference={exposure_ref!r}, got {len(rows)}. "
        f"All ccr__ references present: "
        f"{df.filter(pl.col('exposure_reference').str.starts_with('ccr__'))['exposure_reference'].to_list()!r}. "
        "The CCR pipeline adapter must emit one synthetic row per netting set."
    )
    return rows[0]


@pytest.fixture(scope="module")
def ccr_d1_result() -> dict:
    """
    Run the CCR-D1 bundle through the CRR SA pipeline and return the single
    CCR synthetic row for ccr__NS-D1-001 as a dict.

    Module-scoped to run the pipeline once and reuse results across all D1 tests.

    Arrange:
        - 1 trade (T-D1-001): 10y GBP IR swap, notional GBP 100m, MtM=0.0, delta=1
        - 1 netting set (NS-D1-001): CP-D-001, legally enforceable, unmargined
        - CP-D-001: institution, CQS 2, GB (entity_type="institution")
        - External rating: S&P "A" = CQS 2
        - No margin agreement, no CCR collateral
    """
    # Arrange
    bundle = build_raw_data_bundle_ccr_d1()
    config = _make_config()

    # Act — run the full pipeline
    results = PipelineOrchestrator().run_with_data(bundle, config)
    return _locate_ccr_row(results, CCR_D1_EXPOSURE_REFERENCE, "CCR-D1")


@pytest.fixture(scope="module")
def ccr_d2_result() -> dict:
    """
    Run the CCR-D2 bundle through the CRR SA pipeline and return the single
    CCR synthetic row for ccr__NS-D2-001 as a dict.

    Module-scoped to run the pipeline once and reuse results across all D2 tests.

    Arrange:
        - 1 trade (T-D2-001): 1y USD/GBP FX forward, notional USD 100m / GBP 80m,
          MtM=0.0, delta=1
        - 1 netting set (NS-D2-001): CP-D-001, legally enforceable, unmargined
        - fx_rates: USD->GBP = 0.80
        - No margin agreement, no CCR collateral
    """
    # Arrange
    bundle = build_raw_data_bundle_ccr_d2()
    config = _make_config()

    # Act — run the full pipeline
    results = PipelineOrchestrator().run_with_data(bundle, config)
    return _locate_ccr_row(results, CCR_D2_EXPOSURE_REFERENCE, "CCR-D2")


@pytest.fixture(scope="module")
def ccr_d3_result() -> dict:
    """
    Run the CCR-D3 bundle through the CRR SA pipeline and return the single
    CCR synthetic row for ccr__NS-D3-001 as a dict.

    Module-scoped to run the pipeline once and reuse results across all D3 tests.

    Arrange:
        - 1 trade (T-D3-001): 10y GBP IR swap, notional GBP 100m, MtM=-4m, delta=1
        - 1 netting set (NS-D3-001): CP-D-001, legally enforceable, margined
          (TH=2m, MTA=0.5m, NICA=0.25m, MPOR=10d, margin_agreement_id=MA-D3-001)
        - 1 margin agreement (MA-D3-001): identical margin parameters
        - No CCR collateral (c_net = 0)
    """
    # Arrange
    bundle = build_raw_data_bundle_ccr_d3()
    config = _make_config()

    # Act — run the full pipeline
    results = PipelineOrchestrator().run_with_data(bundle, config)
    return _locate_ccr_row(results, CCR_D3_EXPOSURE_REFERENCE, "CCR-D3")


# ---------------------------------------------------------------------------
# CCR-D1: unmargined IR swap — full SA-CCR guards
# ---------------------------------------------------------------------------


class TestCCRD1UnmarginedIR:
    """
    CCR-D1 regression pins: unmargined 10y GBP IR swap routed through full SA-CCR.

    Seven assertions:
      1. ccr_method == "sa_ccr"      (not simplified or OEM)
      2. pfe_multiplier approx 1.0   (cap binds: MtM=0 -> no sub-unity reduction)
      3. rc_unmargined == 0.0        (max(0-0, 0) = 0)
      4. pfe_addon approx 3,914,298.228
      5. ead_final approx 5,480,017.519
      6. risk_weight == 0.50         (institution CQS 2, CRR Art. 120(1) Table 3)
      7. rwa_final approx 2,740,008.759

    Go-RED trigger: any Art.281 / Art.282 branch that overrides these values.
    """

    def test_ccr_d1_ccr_method_is_sa_ccr(self, ccr_d1_result: dict) -> None:
        """
        ccr_method == "sa_ccr": engine does not route CCR-D1 through Simplified/OEM.

        Arrange: unmargined 10y GBP IR swap, MtM=0, legally enforceable NS.
        Act:     full CRR SA+CCR pipeline.
        Assert:  ccr_method == "sa_ccr" (not "simplified_sa_ccr" or "oem").

        References: CRR Art. 273a(1)/(2) — Simplified SA-CCR eligibility threshold
                    (absent from engine); Art. 274(2) full SA-CCR applies.
        """
        # Arrange
        row = ccr_d1_result

        # Assert
        assert row["ccr_method"] == CCR_D1_EXPECTED_CCR_METHOD, (
            f"CCR-D1: expected ccr_method={CCR_D1_EXPECTED_CCR_METHOD!r}, "
            f"got {row['ccr_method']!r}. "
            "Full SA-CCR must be applied (CRR Art. 274(2)); "
            "Simplified SA-CCR (Art. 281) and OEM (Art. 282) are not implemented."
        )

    def test_ccr_d1_pfe_multiplier(self, ccr_d1_result: dict) -> None:
        """
        pfe_multiplier == 1.0: cap binds for at-par swap (MtM=0, no sub-unity reduction).

        Arrange: MtM=0 (at-par), no collateral, unmargined NS.
                 Art.278(3): multiplier = min(1, floor + (1-floor)*exp(…)) = 1.0 when V>=0.
        Act:     full CRR SA+CCR pipeline.
        Assert:  pfe_multiplier approx 1.0 (abs=1e-9).

        References: CRR Art. 278(3) — PFE multiplier formula.
        """
        # Arrange
        row = ccr_d1_result

        # Assert
        assert row["pfe_multiplier"] == pytest.approx(CCR_D1_EXPECTED_PFE_MULTIPLIER, abs=1e-9), (
            f"CCR-D1: expected pfe_multiplier={CCR_D1_EXPECTED_PFE_MULTIPLIER} (cap binds, MtM=0), "
            f"got {row['pfe_multiplier']!r}. "
            "CRR Art. 278(3): multiplier = min(1, floor+(1-floor)*exp(V-C/(2*AddOn_agg))) = 1.0 "
            "when V-C >= 0."
        )

    def test_ccr_d1_rc_unmargined(self, ccr_d1_result: dict) -> None:
        """
        rc_unmargined == 0.0: max(V-C, 0) = max(0-0, 0) = 0.

        Arrange: MtM=0 (V=0), no CCR collateral (C=0), unmargined NS.
        Act:     full CRR SA+CCR pipeline.
        Assert:  rc_unmargined == 0.0 (abs=1e-6).

        References: CRR Art. 275(1) — RC = max(V - C, 0).
        """
        # Arrange
        row = ccr_d1_result

        # Assert
        assert row["rc_unmargined"] == pytest.approx(CCR_D1_EXPECTED_RC_UNMARGINED, abs=1e-6), (
            f"CCR-D1: expected rc_unmargined={CCR_D1_EXPECTED_RC_UNMARGINED} (max(0-0, 0)=0), "
            f"got {row['rc_unmargined']!r}. "
            "CRR Art. 275(1): unmargined RC = max(V - C, 0)."
        )

    def test_ccr_d1_pfe_addon(self, ccr_d1_result: dict) -> None:
        """
        pfe_addon approx 3,914,298.228: full Art.279b IR add-on.

        Arrange: 10y GBP IR swap, notional GBP 100m, SF_IR=0.5%, MF=1.0 (full-year),
                 multiplier=1.0; PFE = multiplier * AddOn_aggregate.
        Act:     full CRR SA+CCR pipeline.
        Assert:  pfe_addon approx 3,914,298.228 (rel=1e-6).

        References: CRR Art. 278/279b/280a — PFE add-on for IR swaps.
        """
        # Arrange
        row = ccr_d1_result

        # Assert
        assert row["pfe_addon"] == pytest.approx(CCR_D1_EXPECTED_PFE_ADDON, rel=1e-6), (
            f"CCR-D1: expected pfe_addon approx {CCR_D1_EXPECTED_PFE_ADDON:,.3f}, "
            f"got {row['pfe_addon']:,.3f}. "
            "CRR Art. 278: PFE = multiplier * AddOn_aggregate; "
            "Art. 280a: SF_IR = 0.5%."
        )

    def test_ccr_d1_ead(self, ccr_d1_result: dict) -> None:
        """
        ead_final approx 5,480,017.519: EAD = 1.4 * (RC + PFE) = 1.4 * (0 + 3,914,298.228).

        Arrange: alpha=1.4 (Art. 274(2)), RC=0.0, PFE=3,914,298.228.
        Act:     full CRR SA+CCR pipeline.
        Assert:  ead_final approx 5,480,017.519 (rel=1e-6).

        References: CRR Art. 274(2) — EAD = alpha * (RC + PFE).
        """
        # Arrange
        row = ccr_d1_result

        # Assert
        assert row["ead_final"] == pytest.approx(CCR_D1_EXPECTED_EAD, rel=1e-6), (
            f"CCR-D1: expected ead_final approx {CCR_D1_EXPECTED_EAD:,.3f}, "
            f"got {row['ead_final']:,.3f}. "
            "CRR Art. 274(2): EAD = 1.4 * (0 + 3_914_298.228) = 5_480_017.519."
        )

    def test_ccr_d1_risk_weight(self, ccr_d1_result: dict) -> None:
        """
        risk_weight == 0.50: institution CQS 2 → 50% SA risk weight.

        Arrange: CP-D-001 entity_type='institution', CQS 2, GB.
        Act:     full CRR SA+CCR pipeline.
        Assert:  risk_weight (or sa_risk_weight) == 0.50 (abs=1e-9).

        References: CRR Art. 120(1) Table 3 — institution CQS 2 → 50%.
        """
        # Arrange
        row = ccr_d1_result
        # The aggregated result frame exposes risk_weight or sa_risk_weight.
        actual_rw = row.get("risk_weight") or row.get("sa_risk_weight") or 0.0

        # Assert
        assert actual_rw == pytest.approx(0.50, abs=1e-9), (
            f"CCR-D1: expected risk_weight=0.50 (institution CQS 2, CRR Art. 120(1) Table 3), "
            f"got {actual_rw!r}."
        )

    def test_ccr_d1_rwa(self, ccr_d1_result: dict) -> None:
        """
        rwa_final approx 2,740,008.759: RWA = EAD * RW = 5,480,017.519 * 0.50.

        Arrange: EAD=5,480,017.519, RW=0.50.
        Act:     full CRR SA+CCR pipeline.
        Assert:  rwa_final approx 2,740,008.759 (rel=1e-6).

        References: CRR Art. 120(1) Table 3 — institution CQS 2 → 50% risk weight.
        """
        # Arrange
        row = ccr_d1_result

        # Assert
        assert row["rwa_final"] == pytest.approx(CCR_D1_EXPECTED_RWA, rel=1e-6), (
            f"CCR-D1: expected rwa_final approx {CCR_D1_EXPECTED_RWA:,.3f}, "
            f"got {row['rwa_final']:,.3f}. "
            "RWA = EAD * RW = 5_480_017.519 * 0.50 (CRR Art. 120(1) Table 3, CQS 2)."
        )


# ---------------------------------------------------------------------------
# CCR-D2: unmargined FX forward — full SA-CCR guards
# ---------------------------------------------------------------------------


class TestCCRD2UnmarginedFX:
    """
    CCR-D2 regression pins: unmargined 1y USD/GBP FX forward routed through full SA-CCR.

    Five assertions:
      1. ccr_method == "sa_ccr"      (not simplified or OEM)
      2. pfe_multiplier approx 1.0   (cap binds: MtM=0)
      3. pfe_addon approx 3,198,904.672
      4. ead_final approx 4,478,466.541
      5. rwa_final approx 2,239,233.271

    Go-RED trigger: any Art.281 / Art.282 branch that overrides these values.
    """

    def test_ccr_d2_ccr_method_is_sa_ccr(self, ccr_d2_result: dict) -> None:
        """
        ccr_method == "sa_ccr": engine does not route CCR-D2 through Simplified/OEM.

        Arrange: unmargined 1y USD/GBP FX forward, MtM=0, legally enforceable NS.
        Act:     full CRR SA+CCR pipeline.
        Assert:  ccr_method == "sa_ccr".

        References: CRR Art. 274(2) — full SA-CCR; Art. 273a not implemented.
        """
        # Arrange
        row = ccr_d2_result

        # Assert
        assert row["ccr_method"] == CCR_D2_EXPECTED_CCR_METHOD, (
            f"CCR-D2: expected ccr_method={CCR_D2_EXPECTED_CCR_METHOD!r}, "
            f"got {row['ccr_method']!r}. "
            "Full SA-CCR must be applied; Simplified (Art. 281) and OEM (Art. 282) not implemented."
        )

    def test_ccr_d2_pfe_multiplier(self, ccr_d2_result: dict) -> None:
        """
        pfe_multiplier approx 1.0: cap binds for at-par FX forward (MtM=0).

        Arrange: MtM=0, no collateral, unmargined NS.
        Act:     full CRR SA+CCR pipeline.
        Assert:  pfe_multiplier approx 1.0 (abs=1e-9).

        References: CRR Art. 278(3) — PFE multiplier = min(1, …) = 1.0 when V >= 0.
        """
        # Arrange
        row = ccr_d2_result

        # Assert
        assert row["pfe_multiplier"] == pytest.approx(CCR_D2_EXPECTED_PFE_MULTIPLIER, abs=1e-9), (
            f"CCR-D2: expected pfe_multiplier={CCR_D2_EXPECTED_PFE_MULTIPLIER} (cap binds, MtM=0), "
            f"got {row['pfe_multiplier']!r}. "
            "CRR Art. 278(3): multiplier = 1.0 when V-C >= 0."
        )

    def test_ccr_d2_pfe_addon(self, ccr_d2_result: dict) -> None:
        """
        pfe_addon approx 3,198,904.672: full Art.279b FX add-on.

        Arrange: 1y USD/GBP FX forward, USD 100m notional, spot rate 0.80,
                 SF_FX=4%, MF=1.0 (min(1y, 1y)/1y), multiplier=1.0.
        Act:     full CRR SA+CCR pipeline.
        Assert:  pfe_addon approx 3,198,904.672 (rel=1e-6).

        References: CRR Art. 278/279b(1)(b) — FX add-on calculation.
        """
        # Arrange
        row = ccr_d2_result

        # Assert
        assert row["pfe_addon"] == pytest.approx(CCR_D2_EXPECTED_PFE_ADDON, rel=1e-6), (
            f"CCR-D2: expected pfe_addon approx {CCR_D2_EXPECTED_PFE_ADDON:,.3f}, "
            f"got {row['pfe_addon']:,.3f}. "
            "CRR Art. 278/279b: FX add-on with SF_FX=4%, adjusted notional=USD100m*0.80=GBP80m."
        )

    def test_ccr_d2_ead(self, ccr_d2_result: dict) -> None:
        """
        ead_final approx 4,478,466.541: EAD = 1.4 * (RC + PFE) = 1.4 * (0 + 3,198,904.672).

        Arrange: alpha=1.4, RC=0.0, PFE=3,198,904.672.
        Act:     full CRR SA+CCR pipeline.
        Assert:  ead_final approx 4,478,466.541 (rel=1e-6).

        References: CRR Art. 274(2) — EAD = alpha * (RC + PFE).
        """
        # Arrange
        row = ccr_d2_result

        # Assert
        assert row["ead_final"] == pytest.approx(CCR_D2_EXPECTED_EAD, rel=1e-6), (
            f"CCR-D2: expected ead_final approx {CCR_D2_EXPECTED_EAD:,.3f}, "
            f"got {row['ead_final']:,.3f}. "
            "CRR Art. 274(2): EAD = 1.4 * (0 + 3_198_904.672) = 4_478_466.541."
        )

    def test_ccr_d2_rwa(self, ccr_d2_result: dict) -> None:
        """
        rwa_final approx 2,239,233.271: RWA = EAD * RW = 4,478,466.541 * 0.50.

        Arrange: EAD=4,478,466.541, RW=0.50 (institution CQS 2).
        Act:     full CRR SA+CCR pipeline.
        Assert:  rwa_final approx 2,239,233.271 (rel=1e-6).

        References: CRR Art. 120(1) Table 3 — institution CQS 2 → 50%.
        """
        # Arrange
        row = ccr_d2_result

        # Assert
        assert row["rwa_final"] == pytest.approx(CCR_D2_EXPECTED_RWA, rel=1e-6), (
            f"CCR-D2: expected rwa_final approx {CCR_D2_EXPECTED_RWA:,.3f}, "
            f"got {row['rwa_final']:,.3f}. "
            "RWA = EAD * RW = 4_478_466.541 * 0.50 (CRR Art. 120(1) Table 3, CQS 2)."
        )


# ---------------------------------------------------------------------------
# CCR-D3: margined OTM IR swap — LOAD-BEARING full SA-CCR guards
# ---------------------------------------------------------------------------


class TestCCRD3MarginedOTMIR:
    """
    CCR-D3 regression pins — LOAD-BEARING: margined OTM 10y GBP IR swap.

    The primary discriminator is pfe_multiplier = 0.20816907251400474 (sub-unity).
    CCR-D3 is margined daily-remargin, so the margined MF=0.30 (Art. 279c(2)/285)
    scales the add-on to 1,174,289.468 (P8.54). Simplified SA-CCR (Art. 281) would
    force the multiplier to 1.0, yielding:
        wrong_ead = 1.4 * (2_250_000 + 1_174_289.468) = 4_794_005.256

    The full SA-CCR formula yields:
        correct_ead = 1.4 * (2_250_000 + 244_450.749) = 3_492_231.049275926

    Six assertions:
      1. ccr_method == "sa_ccr"
      2. pfe_multiplier approx 0.20816907251400474   <- PRIMARY PIN (rel=1e-9)
      3. rc_margined approx 2,250,000.0               (TH+MTA-NICA floor arm)
      4. pfe_addon approx 244,450.7494828046
      5. ead_final approx 3,492,231.049275926 AND ead_final != 4,794,005.256
      6. rwa_final approx 1,746,115.524637963

    Go-RED trigger: any Art.281 branch that sets pfe_multiplier=1.0 for margined
    OTM netting sets, causing ead_final to match CCR_D3_WRONG_SIMPLIFIED_EAD.
    """

    def test_ccr_d3_ccr_method_is_sa_ccr(self, ccr_d3_result: dict) -> None:
        """
        ccr_method == "sa_ccr": engine routes CCR-D3 through full SA-CCR, not Simplified.

        Arrange: margined 10y GBP IR swap, MtM=-4m, legally enforceable NS.
        Act:     full CRR SA+CCR pipeline.
        Assert:  ccr_method == "sa_ccr".

        References: CRR Art. 273a(1)/(2) — Simplified threshold (absent from engine);
                    Art. 274(2) — full SA-CCR EAD formula.
        """
        # Arrange
        row = ccr_d3_result

        # Assert
        assert row["ccr_method"] == CCR_D3_EXPECTED_CCR_METHOD, (
            f"CCR-D3: expected ccr_method={CCR_D3_EXPECTED_CCR_METHOD!r}, "
            f"got {row['ccr_method']!r}. "
            "Full SA-CCR must be applied; Simplified SA-CCR (Art. 281) would force "
            "pfe_multiplier=1.0 and produce wrong EAD."
        )

    def test_ccr_d3_pfe_multiplier_sub_unity(self, ccr_d3_result: dict) -> None:
        """
        PRIMARY PIN: pfe_multiplier == 0.20816907251400474 (sub-unity, not 1.0).

        This is the critical discriminator between full SA-CCR and Simplified Art. 281.
        Simplified SA-CCR forces pfe_multiplier = 1.0 for all margined netting sets.
        Full SA-CCR Art. 278(3) computes:
            multiplier = min(1, 0.05 + 0.95 * exp((V-C) / (2 * 0.95 * AddOn_agg)))
        CCR-D3 is margined daily-remargin, so the margined MF=0.30 (Art. 279c(2)/285)
        scales the add-on: AddOn_agg = 3_914_298.228 * 0.30 = 1,174,289.468 (P8.54).
        With V-C = -4,000,000 and AddOn_agg = 1,174,289.468:
            multiplier = min(1, 0.05 + 0.95 * exp(-4m / (2 * 0.95 * 1_174_289.468)))
                       = 0.20816907251400474

        Arrange: MtM=-4m (OTM, V-C=-4m), C=0, AddOn_agg approx 1,174,289.468.
        Act:     full CRR SA+CCR pipeline.
        Assert:  pfe_multiplier approx 0.20816907251400474 (rel=1e-9).

        References: CRR Art. 278(3) — PFE multiplier formula (sub-unity for OTM).
                    CRR Art. 281   — Simplified SA-CCR would force multiplier = 1.0.
        """
        # Arrange
        row = ccr_d3_result

        # Assert (PRIMARY PIN — rel=1e-9 for full precision)
        assert row["pfe_multiplier"] == pytest.approx(CCR_D3_EXPECTED_PFE_MULTIPLIER, rel=1e-9), (
            f"CCR-D3 PRIMARY PIN: expected pfe_multiplier={CCR_D3_EXPECTED_PFE_MULTIPLIER!r} "
            f"(sub-unity: full SA-CCR Art. 278(3)), "
            f"got {row['pfe_multiplier']!r}. "
            "Simplified SA-CCR (Art. 281) would force multiplier=1.0 — this test is the "
            "regression guard against that branch being introduced."
        )

    def test_ccr_d3_rc_margined(self, ccr_d3_result: dict) -> None:
        """
        rc_margined == 2,250,000.0: TH+MTA-NICA floor arm binds.

        RC = max(V-C, TH+MTA-NICA, 0) = max(-4m, 2.25m, 0) = 2,250,000 (floor arm).

        Arrange: V=-4m, C=0, TH=2m, MTA=0.5m, NICA=0.25m -> TH+MTA-NICA=2.25m.
        Act:     full CRR SA+CCR pipeline.
        Assert:  rc_margined == 2,250,000.0 (abs=1e-6).

        References: CRR Art. 275(2) — margined RC = max(V-C, TH+MTA-NICA, 0).
        """
        # Arrange
        row = ccr_d3_result
        # Fall back gracefully if column is named rc_margined or rc.
        actual_rc = row.get("rc_margined") or row.get("rc") or 0.0

        # Assert
        assert actual_rc == pytest.approx(CCR_D3_EXPECTED_RC_MARGINED, abs=1e-6), (
            f"CCR-D3: expected rc_margined={CCR_D3_EXPECTED_RC_MARGINED:,.1f} "
            f"(CRR Art. 275(2): max(-4m, 2.25m, 0) = 2_250_000), "
            f"got {actual_rc!r}. "
            "TH+MTA-NICA = 2_000_000 + 500_000 - 250_000 = 2_250_000 (floor arm binds)."
        )

    def test_ccr_d3_pfe_addon(self, ccr_d3_result: dict) -> None:
        """
        pfe_addon approx 244,450.7494828046: multiplier * AddOn_aggregate.

        PFE = pfe_multiplier * AddOn_agg = 0.2082... * 1,174,289.468 = 244,450.749.

        Arrange: pfe_multiplier=0.20816907251400474, AddOn_agg approx 1,174,289.468.
        Act:     full CRR SA+CCR pipeline.
        Assert:  pfe_addon approx 244,450.7494828046 (rel=1e-6).

        References: CRR Art. 278 — PFE = multiplier * AddOn_aggregate.
        """
        # Arrange
        row = ccr_d3_result

        # Assert
        assert row["pfe_addon"] == pytest.approx(CCR_D3_EXPECTED_PFE_ADDON, rel=1e-6), (
            f"CCR-D3: expected pfe_addon approx {CCR_D3_EXPECTED_PFE_ADDON:,.8f}, "
            f"got {row['pfe_addon']!r}. "
            "CRR Art. 278: PFE = multiplier * AddOn_agg = 0.2082... * 1_174_289.468."
        )

    def test_ccr_d3_ead_correct_not_simplified(self, ccr_d3_result: dict) -> None:
        """
        ead_final approx 3,492,231.049275926 AND ead_final != 4,794,005.256.

        The correct (full SA-CCR) EAD:
            EAD = 1.4 * (rc_margined + pfe_addon)
                = 1.4 * (2_250_000 + 244_450.7494828046)
                = 3_492_231.049275926

        The wrong (Simplified Art.281) EAD would be:
            simplified_ead = 1.4 * (2_250_000 + 1_174_289.468) = 4_794_005.256
            (because Art.281 forces multiplier=1.0, so pfe_addon = 1.0 * AddOn_agg)

        Arrange: rc_margined=2_250_000, pfe_addon=244_450.749.
        Act:     full CRR SA+CCR pipeline.
        Assert:  ead_final approx 3,492,231.049275926 (rel=1e-9).
        Assert:  ead_final != CCR_D3_WRONG_SIMPLIFIED_EAD (4,794,005.256).

        References: CRR Art. 274(2) — EAD = alpha * (RC + PFE);
                    CRR Art. 281   — Simplified SA-CCR (NOT applied here).
        """
        # Arrange
        row = ccr_d3_result

        # Assert — correct full SA-CCR EAD (PRIMARY load-bearing value)
        assert row["ead_final"] == pytest.approx(CCR_D3_EXPECTED_EAD, rel=1e-9), (
            f"CCR-D3: expected ead_final approx {CCR_D3_EXPECTED_EAD:,.9f} "
            f"(full SA-CCR: 1.4 * (2_250_000 + 244_450.749)), "
            f"got {row['ead_final']!r}. "
            f"Simplified Art.281 would produce ead_final={CCR_D3_WRONG_SIMPLIFIED_EAD:,.3f}."
        )

        # Assert — must NOT match the simplified EAD (explicit negative guard)
        assert row["ead_final"] != pytest.approx(CCR_D3_WRONG_SIMPLIFIED_EAD, rel=1e-3), (
            f"CCR-D3: ead_final={row['ead_final']!r} matches the WRONG Simplified SA-CCR "
            f"EAD={CCR_D3_WRONG_SIMPLIFIED_EAD:,.3f}. "
            "This means an Art.281 branch is forcing pfe_multiplier=1.0 — regression detected."
        )

    def test_ccr_d3_rwa(self, ccr_d3_result: dict) -> None:
        """
        rwa_final approx 1,746,115.524637963: RWA = EAD * RW = 3,492,231.049 * 0.50.

        Arrange: EAD=3,492,231.049275926, RW=0.50 (institution CQS 2).
        Act:     full CRR SA+CCR pipeline.
        Assert:  rwa_final approx 1,746,115.524637963 (rel=1e-9).

        References: CRR Art. 120(1) Table 3 — institution CQS 2 → 50% risk weight.
        """
        # Arrange
        row = ccr_d3_result

        # Assert
        assert row["rwa_final"] == pytest.approx(CCR_D3_EXPECTED_RWA, rel=1e-9), (
            f"CCR-D3: expected rwa_final approx {CCR_D3_EXPECTED_RWA:,.9f}, "
            f"got {row['rwa_final']!r}. "
            "RWA = EAD * RW = 3_492_231.049275926 * 0.50 "
            "(CRR Art. 120(1) Table 3, institution CQS 2)."
        )
