"""
P1.233: CRR Art. 197 -- corporate/PSE ``bond`` collateral routes to ``corp_bond``.

Pipeline position:
    RawDataBundle -> Full Pipeline -> AggregatedResultBundle

Scenario:
    One unrated corporate counterparty (CP-CORP-233) with three identical
    GBP 1,000,000 drawn term loans (LN-A/LN-B/LN-C), each fully collateralised
    by a single debt security with canonical ``collateral_type="bond"``. Each
    loan exercises a different Art. 197 issuer/CQS eligibility limb:

    - LN-A (Coll A): issuer_type="corporate", issuer_cqs=3 -- Art. 197(1)(d)
      ELIGIBLE (corporate debt securities eligible at CQS 1-3). Art. 224
      Table 1 corp-bond haircut applies (CQS 2-3, 1-5y band = 6%).
    - LN-B (Coll B): issuer_type="corporate", issuer_cqs=5 -- Art. 197(1)(d)
      INELIGIBLE (CQS 4-6/unrated corporate debt securities are excluded).
      The collateral must contribute zero CRM benefit.
    - LN-C (Coll C): issuer_type="pse", issuer_cqs=2 -- Art. 197(1)(c)
      ELIGIBLE (institution/PSE debt securities eligible at CQS 1-3). Same
      Table 1 band as LN-A (Table 1 groups CQS 2-3 together).

    ``_normalize_collateral_type_expr`` currently sends any non-sovereign
    ``collateral_type="bond"`` row to ``.otherwise("other_physical")``, which
    (a) never fires the Art. 197 CQS-eligibility gate, incorrectly granting
    CRM benefit to the ineligible CQS-5 bond (LN-B), and (b) applies the flat
    Art. 230(2) 40% "other" haircut to the eligible bonds (LN-A/LN-C) instead
    of the graduated 6% Art. 224 Table 1 corp-bond haircut, overstating RWA.

    Post-fix expected (RW = 1.00, unrated corporate, CRR Art. 122):
        LN-A: ead_final = rwa_final = 530,000.00 (6% haircut applied)
        LN-B: ead_final = rwa_final = 1,000,000.00 (collateral zeroed --
              ineligible under Art. 197(1)(d))
        LN-C: ead_final = rwa_final = 530,000.00 (6% haircut applied)

    Pre-fix (current buggy ``other_physical`` routing, 40% flat haircut, no
    Art. 197 gate):
        LN-A: rwa_final ~= 700,000.00 (40% haircut understates CRM benefit)
        LN-B: rwa_final ~= 520,000.00 (gate never fires -- GBP 480,000
              capital UNDERSTATEMENT relative to the correct 1,000,000)
        LN-C: rwa_final ~= 700,000.00

References:
    - CRR Art. 197(1)(c): institution/PSE debt securities eligible CQS 1-3.
    - CRR Art. 197(1)(d): corporate debt securities eligible CQS 1-3;
      CQS 4-6/unrated INELIGIBLE.
    - CRR Art. 224 Table 1: corp/institution bond haircuts by CQS x residual
      maturity (CQS 2-3, 1-5y = 6%).
    - CRR Art. 223(5) / Art. 228(1): FCCM E* reduction, SA EAD after CRM.
    - CRR Art. 122: unrated corporate 100% risk weight.
    - tests/fixtures/p1_233/p1_233.py: fixture hand-calc constants.
    - docs/plans/compliance-audit-crr-111-241-rectification.md Section 5 WS3
      (P1.233 L182-186, P1.236 L197-201).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.acceptance.conftest import find_exposure_rows, total_field
from tests.fixtures.p1_233.p1_233 import (
    EAD_A,
    EAD_B,
    EAD_C,
    LOAN_REF_A,
    LOAN_REF_B,
    LOAN_REF_C,
    PRE_FIX_EAD_A,
    PRE_FIX_EAD_B,
    PRE_FIX_EAD_C,
    RWA_A,
    RWA_B,
    RWA_C,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_233"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2026, 1, 1)
_ABS_TOL = 0.50  # GBP 0.50 on 6-figure EAD/RWA (~0.00005% relative error)
_RW_TOL = 1e-9  # tight tolerance for exact 100% risk weight

_RW_EXPECTED = 1.00  # unrated corporate, CRR Art. 122


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline_p1233() -> object:
    """Run the CRR SA pipeline with P1.233 scenario inputs.

    Loads counterparty, loan, and collateral from the p1_233 parquet
    fixtures. No facility parquet is loaded -- loans are registered directly
    to the pipeline (matching the p1_96 pattern for loan-only scenarios).
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


class TestP233Art197CorpBondCollateral:
    """
    P1.233 -- CRR Art. 197 corporate/PSE ``bond`` collateral must route to
    ``corp_bond`` (Art. 224 Table 1 haircut + Art. 197(1)(c)/(d) eligibility
    gate), not the flat 40% ``other_physical`` fallback.
    """

    @pytest.fixture(scope="class")
    def result(self):
        """Run the pipeline once; reuse across all tests in this class."""
        return _run_pipeline_p1233()

    # ------------------------------------------------------------------
    # LN-A -- eligible CQS-3 corporate bond (Art. 197(1)(d))
    # ------------------------------------------------------------------

    def test_loan_a_eligible_corporate_bond_rwa(self, result) -> None:
        """
        LN-A: rwa_final must equal 530,000.00 (Art. 224 Table 1, 6% haircut).

        Arrange: GBP 1,000,000 term loan, corporate bond collateral MV
                 500,000 (CQS 3, 4.0y residual, liquidation_period_days=10).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 530,000.00 (+/- GBP 0.50).

        Pre-fix (routed to other_physical, flat 40% haircut):
            rwa_final ~= 700,000.00.
        """
        rows = find_exposure_rows(result, LOAN_REF_A)
        assert rows, f"{LOAN_REF_A} not found in any result set"

        rwa = total_field(rows, "rwa_final")
        assert rwa == pytest.approx(RWA_A, abs=_ABS_TOL), (
            f"rwa_final {rwa:,.2f} != expected {RWA_A:,.2f}. "
            f"If rwa_final ~= {PRE_FIX_EAD_A:,.2f} the engine is still routing "
            f"collateral_type='bond' + issuer_type='corporate' to "
            f"'other_physical' (flat 40% haircut), violating CRR Art. 224 "
            f"Table 1 (corp-bond CQS 2-3, 1-5y haircut = 6%)."
        )

    def test_loan_a_risk_weight_is_100_pct_unrated_corporate(self, result) -> None:
        """LN-A: risk_weight must be 1.00 (unrated corporate, CRR Art. 122)."""
        rows = find_exposure_rows(result, LOAN_REF_A)
        assert rows, f"{LOAN_REF_A} not found in any result set"

        rw = total_field(rows, "risk_weight")
        assert rw == pytest.approx(_RW_EXPECTED, abs=_RW_TOL), (
            f"risk_weight {rw:.6f} != 1.0. Unrated corporate counterparty "
            f"(CP-CORP-233) must receive 100% RW under CRR Art. 122."
        )

    def test_loan_a_ead_final_reflects_6pct_haircut(self, result) -> None:
        """
        LN-A: ead_final must equal 530,000.00.

        E* = max(0, 1,000,000 - 500,000 x (1 - 0.06)) = 530,000.
        """
        rows = find_exposure_rows(result, LOAN_REF_A)
        assert rows, f"{LOAN_REF_A} not found in any result set"

        ead = total_field(rows, "ead_final")
        assert ead == pytest.approx(EAD_A, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} != expected {EAD_A:,.2f} "
            f"(E* = 1,000,000 - 500,000 x (1 - 0.06) = 530,000)."
        )

    # ------------------------------------------------------------------
    # LN-B -- ineligible CQS-5 corporate bond (Art. 197(1)(d) gate)
    # ------------------------------------------------------------------

    def test_loan_b_ineligible_corporate_bond_rwa(self, result) -> None:
        """
        LN-B: rwa_final must equal 1,000,000.00 (collateral zeroed).

        CRR Art. 197(1)(d) excludes CQS 4-6/unrated corporate debt
        securities entirely -- the CQS-5 bond must contribute NO CRM
        benefit, leaving the full drawn amount as the net exposure.

        Arrange: GBP 1,000,000 term loan, corporate bond collateral MV
                 800,000 (CQS 5, 4.0y residual, liquidation_period_days=10).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 1,000,000.00 (+/- GBP 0.50).

        Pre-fix (routed to other_physical, Art. 197 gate never fires):
            rwa_final ~= 520,000.00 -- a GBP 480,000 capital UNDERSTATEMENT.
        """
        rows = find_exposure_rows(result, LOAN_REF_B)
        assert rows, f"{LOAN_REF_B} not found in any result set"

        rwa = total_field(rows, "rwa_final")
        assert rwa == pytest.approx(RWA_B, abs=_ABS_TOL), (
            f"rwa_final {rwa:,.2f} != expected {RWA_B:,.2f}. "
            f"If rwa_final ~= {PRE_FIX_EAD_B:,.2f} the engine is still "
            f"granting CRM benefit to an ineligible CQS-5 corporate bond "
            f"because the Art. 197(1)(d) eligibility gate never fires for "
            f"'other_physical'-routed collateral -- a GBP 480,000 capital "
            f"understatement."
        )

    def test_loan_b_risk_weight_is_100_pct_unrated_corporate(self, result) -> None:
        """LN-B: risk_weight must be 1.00 (unrated corporate, CRR Art. 122)."""
        rows = find_exposure_rows(result, LOAN_REF_B)
        assert rows, f"{LOAN_REF_B} not found in any result set"

        rw = total_field(rows, "risk_weight")
        assert rw == pytest.approx(_RW_EXPECTED, abs=_RW_TOL), (
            f"risk_weight {rw:.6f} != 1.0. Unrated corporate counterparty "
            f"(CP-CORP-233) must receive 100% RW under CRR Art. 122."
        )

    def test_loan_b_ead_final_equals_full_drawn_amount(self, result) -> None:
        """LN-B: ead_final must equal the full drawn amount (1,000,000 -- no CRM benefit)."""
        rows = find_exposure_rows(result, LOAN_REF_B)
        assert rows, f"{LOAN_REF_B} not found in any result set"

        ead = total_field(rows, "ead_final")
        assert ead == pytest.approx(EAD_B, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} != expected {EAD_B:,.2f} "
            f"(ineligible collateral must not reduce net exposure)."
        )

    # ------------------------------------------------------------------
    # LN-C -- eligible CQS-2 PSE bond (Art. 197(1)(c))
    # ------------------------------------------------------------------

    def test_loan_c_eligible_pse_bond_rwa(self, result) -> None:
        """
        LN-C: rwa_final must equal 530,000.00 (Art. 224 Table 1, 6% haircut).

        Arrange: GBP 1,000,000 term loan, PSE bond collateral MV 500,000
                 (CQS 2, 4.0y residual, liquidation_period_days=10).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 530,000.00 (+/- GBP 0.50).

        Pre-fix (routed to other_physical, flat 40% haircut):
            rwa_final ~= 700,000.00.
        """
        rows = find_exposure_rows(result, LOAN_REF_C)
        assert rows, f"{LOAN_REF_C} not found in any result set"

        rwa = total_field(rows, "rwa_final")
        assert rwa == pytest.approx(RWA_C, abs=_ABS_TOL), (
            f"rwa_final {rwa:,.2f} != expected {RWA_C:,.2f}. "
            f"If rwa_final ~= {PRE_FIX_EAD_C:,.2f} the engine is still "
            f"routing collateral_type='bond' + issuer_type='pse' to "
            f"'other_physical' (flat 40% haircut), violating CRR Art. 224 "
            f"Table 1 (corp-bond CQS 2-3, 1-5y haircut = 6%, which also "
            f"covers PSE-issued debt securities under Art. 197(1)(c))."
        )

    def test_loan_c_risk_weight_is_100_pct_unrated_corporate(self, result) -> None:
        """LN-C: risk_weight must be 1.00 (unrated corporate, CRR Art. 122)."""
        rows = find_exposure_rows(result, LOAN_REF_C)
        assert rows, f"{LOAN_REF_C} not found in any result set"

        rw = total_field(rows, "risk_weight")
        assert rw == pytest.approx(_RW_EXPECTED, abs=_RW_TOL), (
            f"risk_weight {rw:.6f} != 1.0. Unrated corporate counterparty "
            f"(CP-CORP-233) must receive 100% RW under CRR Art. 122."
        )

    def test_loan_c_ead_final_reflects_6pct_haircut(self, result) -> None:
        """
        LN-C: ead_final must equal 530,000.00.

        E* = max(0, 1,000,000 - 500,000 x (1 - 0.06)) = 530,000.
        """
        rows = find_exposure_rows(result, LOAN_REF_C)
        assert rows, f"{LOAN_REF_C} not found in any result set"

        ead = total_field(rows, "ead_final")
        assert ead == pytest.approx(EAD_C, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} != expected {EAD_C:,.2f} "
            f"(E* = 1,000,000 - 500,000 x (1 - 0.06) = 530,000)."
        )

    # ------------------------------------------------------------------
    # Cross-loan directional check
    # ------------------------------------------------------------------

    def test_loan_b_rwa_exceeds_loan_a_and_loan_c_rwa(self, result) -> None:
        """
        LN-B rwa_final must exceed LN-A and LN-C rwa_final.

        After the fix:
            LN-A: 530,000.00 (eligible, 6% haircut)
            LN-B: 1,000,000.00 (ineligible, zero CRM benefit)
            LN-C: 530,000.00 (eligible, 6% haircut)

        This directional check confirms the eligibility gate correctly
        distinguishes the ineligible CQS-5 bond from the two eligible bonds,
        independent of the exact pre-fix/post-fix boundary values.
        """
        rows_a = find_exposure_rows(result, LOAN_REF_A)
        rows_b = find_exposure_rows(result, LOAN_REF_B)
        rows_c = find_exposure_rows(result, LOAN_REF_C)
        assert rows_a, f"{LOAN_REF_A} not found in any result set"
        assert rows_b, f"{LOAN_REF_B} not found in any result set"
        assert rows_c, f"{LOAN_REF_C} not found in any result set"

        rwa_a = total_field(rows_a, "rwa_final")
        rwa_b = total_field(rows_b, "rwa_final")
        rwa_c = total_field(rows_c, "rwa_final")
        assert rwa_b > rwa_a and rwa_b > rwa_c, (
            f"LN-B rwa_final {rwa_b:,.2f} is not greater than LN-A "
            f"{rwa_a:,.2f} / LN-C {rwa_c:,.2f}. The ineligible CQS-5 bond "
            f"(LN-B) must carry a strictly higher net exposure than the "
            f"eligible bonds (LN-A/LN-C) once the Art. 197 gate is enforced."
        )
