"""
P1.96: CRR Art. 197 — covered-bond ineligibility for non-SFT exposures.

Pipeline position:
    RawDataBundle -> Full Pipeline -> AggregatedResultBundle

Scenario:
    Two paired CRR runs exercise the Art. 197 / Art. 207(2) eligibility split
    for covered-bond collateral under the Financial Collateral Comprehensive
    Method (FCSM, CRR Art. 223-226).

    Run A — non-repo term loan (FAC_P196_A / LOAN_P196_A, is_sft=False):
        Covered bonds are NOT listed as eligible financial collateral under
        CRR Art. 197 for non-SFT exposures.  The client row sets
        ``is_eligible_financial_collateral=True`` but the engine must override
        this to False for non-SFT paths.  With no eligible collateral, the
        FCSM does not apply and the full drawn amount is the net exposure (E*).

        Post-fix expected:
            ead_final = 1,000,000.00  (collateral INELIGIBLE under Art. 197)
            risk_weight = 1.00  (unrated corporate, CRR Art. 122)
            rwa_final = 1,000,000.00

        Current bug (pre-fix): engine does not check Art. 197 eligibility for
        covered_bond on a non-SFT path; it applies FCSM with corp-bond haircut
        (4% base, CQS 1, 1-5y, scaled to 20 days):
            H_m = 0.04 × sqrt(20/10) = 0.05656854
            C_adj = 600,000 × (1 - 0.05656854) = 566,057.14
            E* = 1,000,000 - 566,057.14 ≈ 433,942.86
        This test's primary assertion (ead_final == 1,000,000) fails with that
        value until Art. 197 eligibility enforcement is implemented.

    Run B — repo (FAC_P196_B / LOAN_P196_B, is_sft=True):
        Under CRR Art. 207(2), repos may use covered bonds as eligible
        collateral.  The engine must route this to FCSM with the SFT 5-day
        supervisory liquidation period (Art. 224(2)(c)).

        Hand-calc (Art. 224 Table 1, covered_bond → corp-bond CQS 1, 1-5y):
            H_n = 4% (base 10-day haircut)
            T_m = 5 days (SFT period, Art. 224(2)(c))
            H_m = 0.04 × sqrt(5/10) = 0.04 × 0.70710678 = 0.02828427
            FX haircut = 0 (GBP/GBP)
            C_adj = 600,000 × (1 − 0.02828427) = 583,029.44
            E* = max(0, 1,000,000 − 583,029.44) = 416,970.56

        Post-fix expected:
            ead_final = 416,970.56
            risk_weight = 1.00
            rwa_final = 416,970.56

Coexistence note:
    The older test ``test_p1_96_covered_bond_haircut_routing.py`` pinned the
    pre-fix repo-only scenario with an inline (non-parquet) fixture where the
    haircut routing from ``other_physical`` to the corp-bond band was the
    primary fix.  That test asserts ead_final ≈ 416,970.56 on a repo-only
    fixture (LOAN_CRM_D15) and will continue to pass unchanged.  This new test
    is the canonical Art. 197 eligibility test driven by the p1_96 parquet
    fixtures.  The engine-implementer wave will migrate / delete the old test
    when the Art. 197 enforcement is added.

References:
    - CRR Art. 197:    Eligible financial collateral (non-SFT)
    - CRR Art. 207(2): Extended eligible collateral for SFTs (repos)
    - CRR Art. 223:    Financial Collateral Comprehensive Method (FCSM)
    - CRR Art. 224 Table 1: Supervisory haircut schedule
    - CRR Art. 224(2)(c): 5-day liquidation period for SFTs
    - CRR Art. 226:    Liquidation-period scaling sqrt(T_m / 10)
    - CRR Art. 122:    SA corporate risk weights (unrated → 100%)
    - tests/fixtures/p1_96/p1_96.py: fixture hand-calc constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.acceptance.conftest import find_exposure_rows, total_field
from tests.fixtures.p1_96.p1_96 import (
    LOAN_REF_A,
    LOAN_REF_B,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_96"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2026, 1, 1)
_ABS_TOL = 0.50  # £0.50 on 6-figure EAD (~0.00005% relative error)
_RW_TOL = 1e-9  # tight tolerance for exact 100% risk weight

# Post-fix expected values from the scenario proposal (NOT from the fixture
# builder's EAD_FINAL_A which encodes the current buggy FCSM behaviour).
#
# Run A (term_loan, is_sft=False): covered_bond INELIGIBLE under Art. 197.
#     No CRM reduction → ead_final = full drawn amount = 1,000,000.
_EAD_EXPECTED_A = 1_000_000.00
_RW_EXPECTED_A = 1.00
_RWA_EXPECTED_A = 1_000_000.00

# Run A pre-fix value (FCSM with corp-bond haircut applied unconditionally):
#   H_m = 0.04 × sqrt(20/10) ≈ 0.05656854
#   C_adj = 600,000 × (1 − 0.05656854) ≈ 566,057.14
#   E* ≈ 433,942.86
_EAD_PRE_FIX_A = 433_942.86

# Run B (repo, is_sft=True): covered_bond ELIGIBLE under Art. 207(2).
#   H_m = 0.04 × sqrt(5/10) ≈ 0.02828427
#   C_adj = 600,000 × (1 − 0.02828427) ≈ 583,029.44
#   E* = max(0, 1,000,000 − 583,029.44) = 416,970.56
_EAD_EXPECTED_B = 416_970.56
_RW_EXPECTED_B = 1.00
_RWA_EXPECTED_B = 416_970.56

# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline_p196() -> object:
    """Run the CRR SA pipeline with P1.96 scenario inputs.

    Loads counterparty, loan, and collateral from the p1_96 parquet fixtures.
    No facility parquet is loaded — loans are registered directly to the
    pipeline (matching the p1_186 pattern for loan-only scenarios).
    """
    lending_mappings = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )
    facility_mappings = pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        }
    )

    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet")
    loans = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet")
    collateral = pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet")

    bundle = make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=loans,
        counterparties=counterparties,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        collateral=collateral,
    )
    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestP196Art197CoveredBondEligibility:
    """
    P1.96 — CRR Art. 197 must exclude covered bonds from FCSM for non-SFT
    exposures; CRR Art. 207(2) must permit them for repos.

    Run A (term_loan, is_sft=False):
        covered_bond is NOT eligible financial collateral under Art. 197.
        The engine must NOT apply FCSM — ead_final must equal the full drawn
        amount (1,000,000).

        Pre-fix: engine ignores Art. 197 and applies FCSM unconditionally,
        yielding ead_final ≈ 433,942.86.

    Run B (repo, is_sft=True):
        covered_bond IS eligible under Art. 207(2).
        FCSM applies with the 5-day SFT liquidation period.
        ead_final = 416,970.56.
    """

    @pytest.fixture(scope="class")
    def result(self):
        """Run the pipeline once; reuse across all tests in this class."""
        return _run_pipeline_p196()

    # ------------------------------------------------------------------
    # Run A — term_loan, is_sft=False: collateral INELIGIBLE (Art. 197)
    # ------------------------------------------------------------------

    def test_run_a_ead_final_equals_full_drawn_amount(self, result) -> None:
        """
        Run A (term_loan): ead_final must equal 1,000,000 (collateral INELIGIBLE).

        CRR Art. 197 does not list covered bonds as eligible financial collateral
        for non-SFT exposures. Despite the collateral row carrying
        ``is_eligible_financial_collateral=True``, the engine must override this
        to False for the non-SFT path, meaning no FCSM reduction is applied.

        Arrange: £1M term loan (is_sft=False), covered bond MV 600k (CQS 1,
                 2y residual, liquidation_period_days=20), GBP/GBP no FX.
        Act:     full CRR SA pipeline.
        Assert:  ead_final == 1,000,000.00 (±£0.50).

        Pre-fix (Art. 197 not enforced): ead_final ≈ 433,942.86.
        """
        # Arrange / Act (pipeline run in fixture)
        rows = find_exposure_rows(result, LOAN_REF_A)
        assert rows, f"{LOAN_REF_A} not found in any result set"

        # Assert
        ead = total_field(rows, "ead_final")
        assert ead == pytest.approx(_EAD_EXPECTED_A, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} != expected {_EAD_EXPECTED_A:,.2f}. "
            f"If ead_final ≈ {_EAD_PRE_FIX_A:,.2f} the engine is applying FCSM "
            f"to a covered_bond on a non-SFT path, violating CRR Art. 197 "
            f"(covered bonds are not in the Art. 197 eligible list). "
            f"The engine must override is_eligible_financial_collateral=False "
            f"for covered_bond + is_sft=False and skip the FCSM reduction."
        )

    def test_run_a_risk_weight_is_100_pct_unrated_corporate(self, result) -> None:
        """
        Run A (term_loan): risk_weight must be 1.00 (unrated corporate, Art. 122).

        Arrange/Act: as above.
        Assert: risk_weight == 1.0 (tolerance 1e-9).
        """
        rows = find_exposure_rows(result, LOAN_REF_A)
        assert rows, f"{LOAN_REF_A} not found in any result set"

        rw = total_field(rows, "risk_weight")
        assert rw == pytest.approx(_RW_EXPECTED_A, abs=_RW_TOL), (
            f"risk_weight {rw:.6f} != 1.0. "
            f"Unrated corporate counterparty (CP_P196) must receive 100% RW "
            f"under CRR Art. 122."
        )

    def test_run_a_rwa_equals_full_drawn_amount(self, result) -> None:
        """
        Run A (term_loan): rwa_final must equal 1,000,000 (ead_final × 1.0).

        Arrange/Act: as above.
        Assert: rwa_final == 1,000,000.00 (±£0.50).
        """
        rows = find_exposure_rows(result, LOAN_REF_A)
        assert rows, f"{LOAN_REF_A} not found in any result set"

        rwa = total_field(rows, "rwa_final")
        assert rwa == pytest.approx(_RWA_EXPECTED_A, abs=_ABS_TOL), (
            f"rwa_final {rwa:,.2f} != expected {_RWA_EXPECTED_A:,.2f} "
            f"(= ead_final × 1.0 for unrated corporate with no FCSM)."
        )

    def test_run_a_ead_not_equal_to_pre_fix_fcsm_value(self, result) -> None:
        """
        Run A (term_loan): ead_final must NOT match the pre-fix FCSM value.

        Pre-fix: engine ignores Art. 197 and applies FCSM unconditionally.
            H_m = 0.04 × sqrt(20/10) ≈ 0.05656854
            C_adj = 600,000 × (1 - 0.05656854) ≈ 566,057.14
            ead_final ≈ 433,942.86

        Post-fix: Art. 197 exclusion applied → ead_final = 1,000,000.

        Arrange/Act: as above.
        Assert: ead_final ≉ 433,942.86 (abs tolerance ±0.50).
        """
        rows = find_exposure_rows(result, LOAN_REF_A)
        assert rows, f"{LOAN_REF_A} not found in any result set"

        ead = total_field(rows, "ead_final")
        assert ead != pytest.approx(_EAD_PRE_FIX_A, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} matches pre-fix FCSM value {_EAD_PRE_FIX_A:,.2f}. "
            f"The engine is still applying FCSM to covered_bond on a non-SFT path, "
            f"violating CRR Art. 197. Expected ead_final = 1,000,000 after fix."
        )

    # ------------------------------------------------------------------
    # Run B — repo, is_sft=True: collateral ELIGIBLE (Art. 207(2))
    # ------------------------------------------------------------------

    def test_run_b_ead_final_reflects_art_207_fcsm_5_day(self, result) -> None:
        """
        Run B (repo): ead_final must equal 416,970.56 (Art. 207(2) FCSM, 5-day).

        CRR Art. 207(2) permits covered bonds as eligible collateral for repos.
        FCSM applies with the 5-day SFT supervisory liquidation period
        (Art. 224(2)(c)):
            H_m = 0.04 × sqrt(5/10) ≈ 0.02828427
            C_adj = 600,000 × (1 − 0.02828427) ≈ 583,029.44
            E* = 1,000,000 − 583,029.44 = 416,970.56

        Arrange: £1M repo (is_sft=True), covered bond MV 600k (CQS 1, 2y
                 residual, liquidation_period_days=5), GBP/GBP no FX.
        Act:     full CRR SA pipeline.
        Assert:  ead_final ≈ 416,970.56 (±£0.50).
        """
        rows = find_exposure_rows(result, LOAN_REF_B)
        assert rows, f"{LOAN_REF_B} not found in any result set"

        ead = total_field(rows, "ead_final")
        assert ead == pytest.approx(_EAD_EXPECTED_B, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} != expected {_EAD_EXPECTED_B:,.2f}. "
            f"Repo exposure (is_sft=True) with covered_bond collateral should use "
            f"FCSM with 5-day liquidation period (CRR Art. 207(2), Art. 224(2)(c))."
        )

    def test_run_b_risk_weight_is_100_pct_unrated_corporate(self, result) -> None:
        """
        Run B (repo): risk_weight must be 1.00 (unrated corporate, Art. 122).

        Arrange/Act: as above.
        Assert: risk_weight == 1.0 (tolerance 1e-9).
        """
        rows = find_exposure_rows(result, LOAN_REF_B)
        assert rows, f"{LOAN_REF_B} not found in any result set"

        rw = total_field(rows, "risk_weight")
        assert rw == pytest.approx(_RW_EXPECTED_B, abs=_RW_TOL), (
            f"risk_weight {rw:.6f} != 1.0. "
            f"Unrated corporate counterparty (CP_P196) must receive 100% RW "
            f"under CRR Art. 122."
        )

    def test_run_b_rwa_equals_ead_for_100pct_rw(self, result) -> None:
        """
        Run B (repo): rwa_final must equal ead_final (risk_weight = 1.0).

        Arrange/Act: as above.
        Assert: rwa_final ≈ 416,970.56 (±£0.50).
        """
        rows = find_exposure_rows(result, LOAN_REF_B)
        assert rows, f"{LOAN_REF_B} not found in any result set"

        rwa = total_field(rows, "rwa_final")
        assert rwa == pytest.approx(_RWA_EXPECTED_B, abs=_ABS_TOL), (
            f"rwa_final {rwa:,.2f} != expected {_RWA_EXPECTED_B:,.2f} "
            f"(= ead_final × 1.0 for unrated corporate)."
        )

    def test_run_b_ead_less_than_unprotected(self, result) -> None:
        """
        Run B (repo): ead_final must be less than the unprotected EAD (1,000,000).

        Covered bond MV 600k must reduce the net exposure via FCSM.
        If ead_final = 1M the CRM processor ignored the collateral.

        Arrange/Act: as above.
        Assert: ead_final < 1,000,000.
        """
        rows = find_exposure_rows(result, LOAN_REF_B)
        assert rows, f"{LOAN_REF_B} not found in any result set"

        ead = total_field(rows, "ead_final")
        assert ead < 1_000_000.0, (
            f"ead_final {ead:,.2f} is not less than unprotected 1M. "
            f"Covered bond collateral (MV 600k) is providing no EAD reduction "
            f"on the repo path (is_sft=True, Art. 207(2) eligible)."
        )

    # ------------------------------------------------------------------
    # Cross-run directional check
    # ------------------------------------------------------------------

    def test_run_a_ead_greater_than_run_b_ead(self, result) -> None:
        """
        Run A ead_final must exceed Run B ead_final.

        After the fix:
            Run A: 1,000,000 (no FCSM, Art. 197 ineligible)
            Run B:   416,970.56 (FCSM applied, Art. 207(2))

        This directional check confirms the eligibility split is correctly
        implemented: the non-SFT path must yield a higher (or equal) net
        exposure than the SFT path when both have the same collateral.

        Arrange/Act: as above.
        Assert: run_a_ead > run_b_ead.
        """
        rows_a = find_exposure_rows(result, LOAN_REF_A)
        rows_b = find_exposure_rows(result, LOAN_REF_B)
        assert rows_a, f"{LOAN_REF_A} not found in any result set"
        assert rows_b, f"{LOAN_REF_B} not found in any result set"

        ead_a = total_field(rows_a, "ead_final")
        ead_b = total_field(rows_b, "ead_final")
        assert ead_a > ead_b, (
            f"Run A ead_final {ead_a:,.2f} is not greater than Run B ead_final "
            f"{ead_b:,.2f}. "
            f"After fixing Art. 197 enforcement, Run A (term_loan, Art. 197 "
            f"ineligible) must have ead_final=1,000,000 while Run B (repo, "
            f"Art. 207(2) eligible) has ead_final≈416,970.56."
        )
