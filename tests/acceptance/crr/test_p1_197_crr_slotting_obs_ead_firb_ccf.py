"""
P1.197: CRR slotting OBS EAD must use Art. 166(8)(d) F-IRB CCF (75%), not SA CCF (50%).

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
        -> CCFCalculator [BUG HERE] -> SlottingCalculator -> Aggregator

Key responsibilities:
- Assert that a partially-undrawn project-finance slotting facility's OBS commitment
  row receives CCF=0.75 (CRR Art. 166(8)(d) F-IRB credit-line CCF) rather than the
  SA CCF of 0.50 that the pre-fix engine incorrectly routes slotting-approach exposures to.

Structure: The pipeline emits two slotting rows for a partially-undrawn facility:
  1. SL-LOAN-001 (on-BS drawn): ccf=0.0 (zero nominal → no CCF conversion), ead_final=4,000,000
  2. SL-FAC-001_UNDRAWN (OBS commitment): ccf=0.50 (buggy) / 0.75 (post-fix), ead_final=1,000,000 / 1,500,000

The load-bearing CCF and ead_from_ccf assertions are against the UNDRAWN row.
The portfolio EAD (sum of both rows) is 5,000,000 pre-fix / 5,500,000 post-fix.

Bug (pre-fix): `_compute_ccf` in `engine/ccf.py` branches only AIRB / FIRB.  The SLOTTING
approach falls to `.otherwise()` which returns `_sa_ccf_from_risk_type` (SA CCF 50% for MR).

Post-fix: SLOTTING under CRR must route to `_firb_ccf_from_risk_type` (Art. 166(8)(d) 75%).

Regulatory References:
- CRR Art. 166(8)(d): F-IRB CCF 75% for credit lines / NIFs / RUFs
- CRR Art. 147(8): specialised lending is a sub-class of corporate
- CRR Art. 151(5)/(8): IRB EAD per Art. 166
- CRR Art. 153(5): slotting approach risk weights (Table 1)

Scenario ID: P1.197 / CRR-E.CCF1
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_197"

# ---------------------------------------------------------------------------
# Scenario constants (mirrors p1_197.py — single source of truth)
# ---------------------------------------------------------------------------

_FACILITY_REF = "SL-FAC-001"
_LOAN_REF = "SL-LOAN-001"
_COUNTERPARTY_REF = "CP-SL-PF-01"

# The hierarchy resolver synthesises the OBS commitment row as "<FACILITY_REF>_UNDRAWN"
_UNDRAWN_EXPOSURE_REF = "SL-FAC-001_UNDRAWN"

# Scenario ID used in assertion messages
_SCENARIO_ID = "CRR-E.CCF1 (P1.197)"

# Expected post-fix values for the UNDRAWN OBS row (CRR Art. 166(8)(d))
_EXPECTED_CCF = 0.75  # F-IRB credit-line CCF (Art. 166(8)(d))
_EXPECTED_UNDRAWN_AMOUNT = 2_000_000.0  # facility_limit - drawn = 6m - 4m
_EXPECTED_EAD_FROM_CCF = 1_500_000.0  # undrawn × CCF = 2m × 0.75
_EXPECTED_UNDRAWN_EAD_FINAL = 1_500_000.0  # OBS row EAD (no CRM)

# For reference: on-BS loan row
_EXPECTED_ON_BS_EAD_FINAL = 4_000_000.0  # drawn=4m, interest=0

# Portfolio-level totals (both rows combined)
_EXPECTED_TOTAL_EAD = 5_500_000.0  # 4m on-BS + 1.5m OBS

# Risk weight on OBS row: CRR Art. 153(5) Table 1: PF Strong >=2.5yr = 70%
_EXPECTED_RISK_WEIGHT = 0.70

# RWA for OBS UNDRAWN row only (pre-1.06x scaling)
_EXPECTED_UNDRAWN_RWA = 1_050_000.0  # 1,500,000 × 0.70

# Portfolio RWA (both rows): 4,000,000 × 0.70 + 1,500,000 × 0.70 = 3,850,000
_EXPECTED_TOTAL_RWA = 3_850_000.0

# Regression sentinels — pre-fix (buggy) values for the UNDRAWN row
_BUGGY_CCF = 0.50  # SA CCF for MR — what the pre-fix engine returns
_BUGGY_EAD_FROM_CCF = 1_000_000.0  # 2,000,000 × 0.50
_BUGGY_UNDRAWN_EAD_FINAL = 1_000_000.0
_BUGGY_UNDRAWN_RWA = 700_000.0  # 1,000,000 × 0.70
_BUGGY_TOTAL_EAD = 5_000_000.0  # 4m + 1m
_BUGGY_TOTAL_RWA = 3_500_000.0  # (4m + 1m) × 0.70

# Tolerances
_CCF_TOL = 1e-6  # exact (CCF is a discrete lookup)
_EAD_TOL = 1.0  # absolute 1 GBP — purely floating-point accumulation
_RWA_TOL = 1.0  # absolute 1 GBP
_RW_TOL = 1e-6  # risk weight is a discrete lookup


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_197_slotting_results() -> dict[str, dict]:
    """
    Run the P1.197 fixture through the CRR pipeline and return both slotting rows.

    Module-scoped to run the pipeline once and share results across all tests.

    Arrange:
        - 1 counterparty: CP-SL-PF-01, entity_type=specialised_lending.
        - 1 specialised_lending metadata row: project_finance, strong, is_hvcre=False.
        - 1 facility: SL-FAC-001, limit=6,000,000, risk_type=MR, is_obs_commitment=True,
          maturity_date=2030-12-31 (6yr > 2.5yr threshold).
        - 1 loan: SL-LOAN-001, drawn_amount=4,000,000, interest=0.
        - 1 facility_mapping: SL-FAC-001 -> SL-LOAN-001.
        - Config: CRR, reporting_date=2024-12-31.
        - IRBPermissions.full_irb() (org-wide) so slotting is permitted without
          model_permissions or internal ratings (slotting needs no PD/LGD inputs).

    Returns:
        dict keyed by "undrawn" (OBS commitment row) and "loan" (on-BS drawn row).
    """
    # Arrange — load P1.197 parquets
    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet")
    facilities = pl.scan_parquet(_FIXTURES_DIR / "facility.parquet")
    loans = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet")
    facility_mappings = pl.scan_parquet(_FIXTURES_DIR / "facility_mapping.parquet")
    specialised_lending = pl.scan_parquet(_FIXTURES_DIR / "sl_metadata.parquet")

    bundle = make_raw_bundle(
        facilities=facilities,
        loans=loans,
        counterparties=counterparties,
        facility_mappings=facility_mappings,
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
        specialised_lending=specialised_lending,
    )

    # Config: CRR with org-wide slotting permissions via full_irb (no model_permissions
    # table needed — slotting exposures carry no PD/LGD so there are no internal ratings).
    # IRBPermissions.full_irb() includes SPECIALISED_LENDING -> SLOTTING, which the
    # classifier uses via the org-wide permission path when has_model_permissions=False.
    config = replace(
        CalculationConfig.crr(reporting_date=date(2024, 12, 31)),
        irb_permissions=IRBPermissions.full_irb(),
    )

    # Act — full pipeline
    result = PipelineOrchestrator().run_with_data(bundle, config)

    # Confirm slotting branch was populated
    assert result.slotting_results is not None, (
        f"{_SCENARIO_ID}: slotting_results is None — "
        "the exposure did not reach the slotting calculator"
    )

    slotting_df = result.slotting_results.collect()

    assert "exposure_reference" in slotting_df.columns, (
        f"{_SCENARIO_ID}: 'exposure_reference' column missing from slotting_results. "
        f"Columns: {slotting_df.columns}"
    )

    all_refs = slotting_df["exposure_reference"].to_list()

    # The hierarchy resolver creates the OBS commitment row with "_UNDRAWN" suffix.
    # Confirm both the loan row and undrawn row exist in slotting branch.
    undrawn_rows = slotting_df.filter(
        pl.col("exposure_reference") == _UNDRAWN_EXPOSURE_REF
    ).to_dicts()
    loan_rows = slotting_df.filter(pl.col("exposure_reference") == _LOAN_REF).to_dicts()

    assert len(undrawn_rows) == 1, (
        f"{_SCENARIO_ID}: expected exactly 1 slotting row for '{_UNDRAWN_EXPOSURE_REF}', "
        f"got {len(undrawn_rows)}. All exposure_references: {all_refs}"
    )
    assert len(loan_rows) == 1, (
        f"{_SCENARIO_ID}: expected exactly 1 slotting row for '{_LOAN_REF}', "
        f"got {len(loan_rows)}. All exposure_references: {all_refs}"
    )

    return {"undrawn": undrawn_rows[0], "loan": loan_rows[0]}


# ---------------------------------------------------------------------------
# P1.197 acceptance tests
# ---------------------------------------------------------------------------


class TestP1197CRRSlottingOBSEADFIRBCCF:
    """
    P1.197: CRR Art. 166(8)(d) — slotting OBS commitments must use F-IRB CCF (75%),
    not SA CCF (50%).

    The pipeline emits two slotting rows for the partially-undrawn facility:
      - SL-LOAN-001: on-BS drawn portion (ccf=0.0, no OBS conversion needed)
      - SL-FAC-001_UNDRAWN: OBS commitment row (the one affected by the bug)

    Pre-fix failures (on the UNDRAWN row — load-bearing assertions):
      - ccf: engine returns 0.50 (SA MR), expected 0.75 (F-IRB Art. 166(8)(d))
      - ead_from_ccf: engine returns 1,000,000 (2m × 0.50), expected 1,500,000 (2m × 0.75)

    Bug site: `engine/ccf.py:_compute_ccf` `.otherwise()` branch catches SLOTTING
    → routes to `_sa_ccf_from_risk_type` (SA 50%) instead of `_firb_ccf_from_risk_type`.
    """

    # ------------------------------------------------------------------
    # PRIMARY LOAD-BEARING ASSERTION — CCF must be 0.75, not 0.50
    # ------------------------------------------------------------------

    def test_p1197_slotting_obs_ccf_is_firb_not_sa(
        self, p1_197_slotting_results: dict[str, dict]
    ) -> None:
        """
        P1.197: CRR Art. 166(8)(d) — OBS slotting commitment CCF must be 0.75 (F-IRB).

        A partially-undrawn project-finance commitment with risk_type=MR and
        is_obs_commitment=True must receive the F-IRB credit-line CCF of 75%
        (CRR Art. 166(8)(d) / FIRB_CREDIT_LINE_CCF = 0.75) — not the SA CCF
        of 50% (SA_CCF_CRR["MR"]) that the pre-fix engine returns.

        Arrange: SL-FAC-001_UNDRAWN row, risk_type=MR, is_obs_commitment=True, slotting.
        Act:     Full CRR pipeline under CalculationConfig.crr(2024-12-31).
        Assert:  ccf == 0.75 (F-IRB Art. 166(8)(d)).
        """
        # Arrange — OBS commitment row (the row affected by the CCF bug)
        undrawn_row = p1_197_slotting_results["undrawn"]

        # Assert (primary load-bearing)
        actual_ccf = undrawn_row["ccf"]
        assert actual_ccf == pytest.approx(_EXPECTED_CCF, abs=_CCF_TOL), (
            f"{_SCENARIO_ID}: CCF on '{_UNDRAWN_EXPOSURE_REF}' must be {_EXPECTED_CCF} "
            f"(CRR Art. 166(8)(d) F-IRB credit-line CCF) for slotting OBS commitment "
            f"with risk_type=MR. Got {actual_ccf}. "
            f"Pre-fix engine returns {_BUGGY_CCF} (SA_CCF_CRR['MR'] from .otherwise() branch "
            f"in engine/ccf.py:_compute_ccf)."
        )

    def test_p1197_slotting_obs_ccf_is_not_sa_ccf_regression(
        self, p1_197_slotting_results: dict[str, dict]
    ) -> None:
        """
        P1.197 regression sentinel: slotting CCF must NOT be the SA MR value (0.50).

        Arrange: SL-FAC-001_UNDRAWN, MR commitment, slotting approach.
        Act:     Full CRR pipeline.
        Assert:  ccf != 0.50 (pre-fix bug value from SA_CCF_CRR["MR"]).
        """
        # Arrange
        undrawn_row = p1_197_slotting_results["undrawn"]

        # Assert — regression sentinel (must fail before fix, pass after)
        actual_ccf = undrawn_row["ccf"]
        assert actual_ccf != pytest.approx(_BUGGY_CCF, abs=_CCF_TOL), (
            f"{_SCENARIO_ID}: CCF on '{_UNDRAWN_EXPOSURE_REF}' must not be {_BUGGY_CCF} "
            f"(SA_CCF_CRR['MR']). Got {actual_ccf}. "
            f"The pre-fix engine incorrectly routes slotting OBS commitments to "
            f"_sa_ccf_from_risk_type (50%) instead of _firb_ccf_from_risk_type (75%)."
        )

    # ------------------------------------------------------------------
    # OBS EAD derivation (on the UNDRAWN row)
    # ------------------------------------------------------------------

    def test_p1197_slotting_ead_from_ccf(self, p1_197_slotting_results: dict[str, dict]) -> None:
        """
        P1.197: OBS EAD = undrawn_amount × CCF = 2,000,000 × 0.75 = 1,500,000.

        Arrange: SL-FAC-001_UNDRAWN, nominal_amount=2,000,000, ccf=0.75 (post-fix).
        Act:     Full CRR pipeline.
        Assert:  ead_from_ccf == 1,500,000 (pre-fix: 1,000,000 with ccf=0.50).
        """
        # Arrange
        undrawn_row = p1_197_slotting_results["undrawn"]

        # Assert
        actual = undrawn_row["ead_from_ccf"]
        assert actual == pytest.approx(_EXPECTED_EAD_FROM_CCF, abs=_EAD_TOL), (
            f"{_SCENARIO_ID}: ead_from_ccf on '{_UNDRAWN_EXPOSURE_REF}' must be "
            f"{_EXPECTED_EAD_FROM_CCF:,.0f} (2,000,000 undrawn × 0.75 F-IRB CCF). "
            f"Got {actual:,.0f}. "
            f"Pre-fix: {_BUGGY_EAD_FROM_CCF:,.0f} (2,000,000 × 0.50 SA CCF)."
        )

    # ------------------------------------------------------------------
    # OBS row EAD final (UNDRAWN row alone)
    # ------------------------------------------------------------------

    def test_p1197_slotting_undrawn_ead_final(
        self, p1_197_slotting_results: dict[str, dict]
    ) -> None:
        """
        P1.197: The UNDRAWN row's ead_final = ead_from_ccf = 1,500,000 (no on-BS component).

        The hierarchy resolver emits the OBS commitment as a standalone row with
        nominal_amount=2,000,000 and on_bs_for_ead=0. So ead_final = 0 + 1,500,000.

        Arrange: SL-FAC-001_UNDRAWN, nominal=2,000,000, ccf=0.75 (post-fix).
        Act:     Full CRR pipeline.
        Assert:  ead_final == 1,500,000 (pre-fix: 1,000,000).
        """
        # Arrange
        undrawn_row = p1_197_slotting_results["undrawn"]

        # Assert
        actual_ead = undrawn_row.get("ead_final") or undrawn_row.get("ead_pre_crm")
        assert actual_ead is not None, (
            f"{_SCENARIO_ID}: neither 'ead_final' nor 'ead_pre_crm' found in row. "
            f"Available columns: {list(undrawn_row.keys())}"
        )
        assert actual_ead == pytest.approx(_EXPECTED_UNDRAWN_EAD_FINAL, abs=_EAD_TOL), (
            f"{_SCENARIO_ID}: UNDRAWN row ead_final must be {_EXPECTED_UNDRAWN_EAD_FINAL:,.0f} "
            f"(= ead_from_ccf with zero on-BS component). "
            f"Got {actual_ead:,.0f}. "
            f"Pre-fix: {_BUGGY_UNDRAWN_EAD_FINAL:,.0f} (1m from SA CCF 0.50)."
        )

    # ------------------------------------------------------------------
    # Portfolio total EAD (both rows summed)
    # ------------------------------------------------------------------

    def test_p1197_slotting_total_ead(self, p1_197_slotting_results: dict[str, dict]) -> None:
        """
        P1.197: Portfolio EAD = on_bs_ead + ead_from_ccf = 4,000,000 + 1,500,000 = 5,500,000.

        Summing the LOAN row (4,000,000) and the UNDRAWN row (1,500,000 post-fix)
        gives the total EAD per the scenario proposal §4 hand-calculation.

        Arrange: SL-LOAN-001 ead_final=4,000,000; SL-FAC-001_UNDRAWN ead_final=1,500,000.
        Act:     Full CRR pipeline.
        Assert:  sum of ead_finals == 5,500,000 (pre-fix: 5,000,000).
        """
        # Arrange
        loan_row = p1_197_slotting_results["loan"]
        undrawn_row = p1_197_slotting_results["undrawn"]

        loan_ead = loan_row.get("ead_final") or loan_row.get("ead_pre_crm") or 0.0
        undrawn_ead = undrawn_row.get("ead_final") or undrawn_row.get("ead_pre_crm") or 0.0
        total_ead = loan_ead + undrawn_ead

        # Assert
        assert total_ead == pytest.approx(_EXPECTED_TOTAL_EAD, abs=_EAD_TOL), (
            f"{_SCENARIO_ID}: total EAD (loan + undrawn) must be {_EXPECTED_TOTAL_EAD:,.0f} "
            f"(4m drawn + 1.5m OBS at F-IRB CCF 0.75). "
            f"Got {total_ead:,.0f} (loan={loan_ead:,.0f}, undrawn={undrawn_ead:,.0f}). "
            f"Pre-fix: {_BUGGY_TOTAL_EAD:,.0f} (4m + 1m at SA CCF 0.50)."
        )

    # ------------------------------------------------------------------
    # Risk weight — CRR Art. 153(5) Table 1: PF Strong >=2.5yr = 70%
    # ------------------------------------------------------------------

    def test_p1197_slotting_risk_weight(self, p1_197_slotting_results: dict[str, dict]) -> None:
        """
        P1.197: Risk weight for PF Strong >=2.5yr must be 70% (CRR Art. 153(5) Table 1).

        Slotting category = strong, maturity = 2030-12-31 (6yr from 2024-12-31),
        is_hvcre = False. UK CRR Table 1 Strong >=2.5yr = 70%. Verified on the
        UNDRAWN row (non-load-bearing for the CCF bug but required for the RWA).

        Arrange: SL-FAC-001_UNDRAWN, slotting_category=strong, maturity>=2.5yr, CRR.
        Act:     Full CRR pipeline.
        Assert:  risk_weight == 0.70.
        """
        # Arrange
        undrawn_row = p1_197_slotting_results["undrawn"]

        # Assert
        actual_rw = undrawn_row["risk_weight"]
        assert actual_rw == pytest.approx(_EXPECTED_RISK_WEIGHT, abs=_RW_TOL), (
            f"{_SCENARIO_ID}: risk_weight on '{_UNDRAWN_EXPOSURE_REF}' must be "
            f"{_EXPECTED_RISK_WEIGHT} (CRR Art. 153(5) Table 1, PF Strong >=2.5yr). "
            f"Got {actual_rw}."
        )

    # ------------------------------------------------------------------
    # Portfolio RWA (both rows summed, pre-1.06x scaling)
    # ------------------------------------------------------------------

    def test_p1197_slotting_total_rwa_pre_scaling(
        self, p1_197_slotting_results: dict[str, dict]
    ) -> None:
        """
        P1.197: Portfolio slotting branch RWA = 5,500,000 × 0.70 = 3,850,000.

        Sums both slotting rows (LOAN + UNDRAWN) before the 1.06x CRR IRB scaling.
        The slotting_results field in AggregatedResultBundle is pre-1.06x.

        Arrange: LOAN rwa_final=2,800,000; UNDRAWN rwa_final=1,050,000 (post-fix).
        Act:     Full CRR pipeline; read result.slotting_results.
        Assert:  total rwa_final == 3,850,000 (pre-fix: 3,500,000 from SA CCF 0.50).
        """
        # Arrange
        loan_row = p1_197_slotting_results["loan"]
        undrawn_row = p1_197_slotting_results["undrawn"]

        loan_rwa = loan_row.get("rwa_final") or loan_row.get("rwa") or 0.0
        undrawn_rwa = undrawn_row.get("rwa_final") or undrawn_row.get("rwa") or 0.0
        total_rwa = loan_rwa + undrawn_rwa

        # Assert
        assert total_rwa == pytest.approx(_EXPECTED_TOTAL_RWA, abs=_RWA_TOL), (
            f"{_SCENARIO_ID}: total slotting branch RWA must be {_EXPECTED_TOTAL_RWA:,.0f} "
            f"(5,500,000 EAD × 0.70 RW, pre-1.06x scaling). "
            f"Got {total_rwa:,.0f} (loan={loan_rwa:,.0f}, undrawn={undrawn_rwa:,.0f}). "
            f"Pre-fix: {_BUGGY_TOTAL_RWA:,.0f} (5m × 0.70 using SA CCF 0.50)."
        )
