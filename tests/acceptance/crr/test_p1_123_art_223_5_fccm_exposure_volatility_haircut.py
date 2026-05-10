"""
P1.123: CRR Art. 223(5) — FCCM missing exposure volatility haircut (HE) for SFT exposures.

Pipeline position:
    RawDataBundle -> Full Pipeline -> AggregatedResultBundle

Scenario:
    One unrated corporate counterparty (CRR-P1123-CP1, GB) secures three loans under
    the CRR SA pipeline.  All loans are collateralised by a GBP govt bond
    (CQS 1, MV=950,000) pledged directly.  CTRL collateral uses
    residual_maturity_years=4.99 to eliminate any Art. 238 mismatch with the 5-year
    CTRL exposure; BIND and RUNB collateral use residual_maturity_years=2.0
    (well above the ~0.5yr SFT exposures).

    CRR-P1123-L-CTRL (is_sft=False, no exposure security, maturity 2030-12-31):
        HE = 0 (exposure is a loan, not a debt security) per CRR Art. 223(5).
        T_m = 20 days (Art. 224(2)(a), secured lending).
        HC = 2% × sqrt(2) = 2.8284%.  HFX = 0 (GBP/GBP).
        No Art. 238 mismatch: collateral residual_maturity_years=4.99 >= exposure T≈5y.
        E* = max(0, 1,000,000 − 950,000 × (1 − 0.028284)) = 76,869.65

    CRR-P1123-L-BIND (is_sft=True, corp_bond CQS 2, 4-year residual maturity,
                       exposure maturity 2026-06-30 ≈ 0.5yr from value date):
        HE = 6% × sqrt(0.5) = 4.2426% for corp_bond CQS 2-3, 1-5yr band.
        T_m = 5 days (Art. 224(2)(c), SFT).
        HC = 2% × sqrt(0.5) = 1.4142%.  HFX = 0 (GBP/GBP).
        Collateral t_coll=2.0 >= T_exposure≈0.5 → no maturity mismatch for BIND.
        E(1+HE)  = 1,000,000 × 1.042426 = 1,042,426.41
        C*(1−HC) = 950,000  × 0.985858  =   936,565.03
        E*       = max(0, 1,042,426.41 − 936,565.03) = 105,861.38

    CRR-P1123-L-RUNB (is_sft=True, cash exposure, maturity 2026-06-30):
        HE = 0 (cash has 0% exposure volatility haircut).
        T_m = 5 days (Art. 224(2)(c)).
        HC = 2% × sqrt(0.5) = 1.4142%.  HFX = 0.
        No maturity mismatch (same as BIND).
        E* = max(0, 1,000,000 − 936,565.03) = 63,434.97

Engine bug (pre-fix):
    engine/crm/collateral.py omits the (1+HE) gross-up on the exposure side.
    For CRR-P1123-L-BIND the engine currently computes:
        E* = max(0, E − C*(1−HC)) = max(0, 1,000,000 − 936,565.03) = 63,434.97
    The correct Art. 223(5) result is 105,861.38 — a 40.28% understatement of
    the net exposure for this bond-vs-bond SFT position.

References:
    - CRR Art. 223(5): E* = max(0, E(1+HE) - CVA(1-HC-HFX))
    - CRR Art. 224 Table 1: supervisory haircuts for debt securities (10-day base)
    - CRR Art. 224(2)(a): 20-day liquidation period for secured lending
    - CRR Art. 224(2)(c): 5-day liquidation period for repo-style SFTs
    - CRR Art. 226(2): H_m = H_n × sqrt(T_m / 10) liquidation-period scaling
    - CRR Art. 238: maturity mismatch adjustment Pa = (t − t*) / (T − t*)
    - CRR Art. 122: corporate SA risk weights (unrated → 100%)
    - tests/fixtures/p1_123/p1_123.py: fixture hand-calc constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p1_123.p1_123 import (
    EXPECTED_EAD_BIND,
    EXPECTED_EAD_CTRL,
    EXPECTED_EAD_RUNB,
    EXPECTED_RWA_BIND,
    EXPECTED_RWA_CTRL,
    EXPECTED_RWA_RUNB,
    LOAN_REF_BIND,
    LOAN_REF_CTRL,
    LOAN_REF_RUNB,
    PRE_FIX_EAD_BIND,
)

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_123"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2025, 12, 31)
_ABS_TOL = 0.50  # £0.50 on a 6-figure EAD (~0.0001% relative error)
_RW_TOL = 1e-9  # tight tolerance for exact 100% risk weight

# Cross-row invariant: the HE gross-up on BIND adds E × HE to E*
# E × HE = 1,000,000 × 4.2426% = 42,426.41
_BIND_HE_INCREMENT = EXPECTED_EAD_BIND - EXPECTED_EAD_RUNB  # ≈ 42,426.41

# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline_p1123() -> object:
    """Run the CRR SA pipeline with P1.123 scenario inputs.

    Loads counterparty, loans, and collateral from the p1_123 parquet fixtures.
    The loan parquet carries three extra columns
    (exposure_collateral_type, exposure_security_cqs,
    exposure_security_residual_maturity_years) that encode the exposure security
    characteristics used to derive HE under Art. 223(5).  These columns are not
    yet registered in LOAN_SCHEMA — the loader's non-strict enforce_schema pass
    preserves them as passthrough columns for the CRM engine to consume post-fix.

    The collateral parquet carries ``liquidation_period_days=None`` on all three
    rows, so the engine derives T_m from each exposure's ``is_sft`` flag:
        is_sft=False → 20 days (Art. 224(2)(a))
        is_sft=True  →  5 days (Art. 224(2)(c))
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

    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparties.parquet")
    loans = pl.scan_parquet(_FIXTURES_DIR / "loans.parquet")
    collateral = pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet")

    bundle = RawDataBundle(
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


def _find_rows(results: object, loan_ref: str) -> list[dict]:
    """Return all result rows whose exposure_reference contains *loan_ref*."""
    rows: list[dict] = []
    for lf in [results.sa_results, results.irb_results, results.slotting_results]:
        if lf is None:
            continue
        df = lf.filter(pl.col("exposure_reference").str.contains(loan_ref)).collect()
        rows.extend(df.to_dicts())
    return rows


def _total(rows: list[dict], field: str) -> float:
    """Sum *field* across all rows (handles guarantee sub-row splits)."""
    return sum(r.get(field, 0.0) or 0.0 for r in rows)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestP1123Art2235FccmExposureVolatilityHaircut:
    """
    P1.123 — CRR Art. 223(5): when the exposure is an SFT where the firm lends
    out a debt security, the FCCM formula must gross up the exposure by (1+HE):

        E* = max(0, E(1+HE) − CVA(1−HC−HFX))

    HE is drawn from CRR Art. 224 Table 1 — the same table as HC — applied to
    the *exposure* security's characteristics (type, CQS, residual maturity).
    For cash or standard loan exposures HE = 0.

    Pre-fix: engine omits (1+HE), computing E* = max(0, E − CVA(1−HC−HFX)).
        CRR-P1123-L-BIND.ead_final ≈ 63,435 (wrong — equal to RUNB, not 105,861).
    Post-fix:
        CRR-P1123-L-CTRL.ead_final ≈ 76,870 (non-SFT, HE=0; no maturity mismatch
            — collateral residual_maturity_years=4.99 >= exposure T≈5y)
        CRR-P1123-L-BIND.ead_final ≈ 105,861 (HE gross-up applied, load-bearing)
        CRR-P1123-L-RUNB.ead_final ≈  63,435 (cash exposure, HE=0, unchanged)

    The CTRL collateral uses residual_maturity_years=5.0 (1-5yr band, HC=2%,
    because CRR band lookup uses <= 5.0 for 1_5y) so that t_coll >= T_exposure
    with no Art. 238 adjustment needed.
    """

    @pytest.fixture(scope="class")
    def result(self):
        """Run the pipeline once; reuse across all tests in this class."""
        return _run_pipeline_p1123()

    # ------------------------------------------------------------------
    # Primary assertions — CRR-P1123-L-CTRL (control: non-SFT, HE=0)
    # ------------------------------------------------------------------

    def test_ctrl_ead_final_non_sft_he_zero_no_maturity_mismatch(self, result) -> None:
        """
        E* for the control loan (is_sft=False) must reflect zero HE with no Art. 238
        maturity mismatch adjustment.

        CRR Art. 223(5) HE = 0 for non-SFT exposures (loan not a debt security).
        T_m = 20 days (Art. 224(2)(a)).  HC = 2% × sqrt(2) = 2.8284%.  HFX = 0.
        No Art. 238 mismatch: collateral residual_maturity_years=5.0 >= exposure T≈4.999y.
        E* = max(0, 1,000,000 - 950,000 × (1 - 0.028284)) = 76,869.65

        Arrange: £1M loan (is_sft=False, maturity 2030-12-31), GBP govt_bond CQS 1
                 collateral (residual_maturity_years=5.0, MV=950k,
                 liquidation_period_days=None).
        Act:     full CRR SA pipeline.
        Assert:  ead_final ≈ 76,870 (±£0.50).
        """
        # Arrange / Act (pipeline run in fixture)
        rows = _find_rows(result, LOAN_REF_CTRL)
        assert rows, f"{LOAN_REF_CTRL} not found in any result set"

        # Assert
        ead = _total(rows, "ead_final")
        assert ead == pytest.approx(EXPECTED_EAD_CTRL, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} != expected {EXPECTED_EAD_CTRL:,.2f}. "
            f"CTRL (is_sft=False) must use T_m=20d (Art. 224(2)(a)) with HE=0 "
            f"and no Art. 238 mismatch (collateral t=5.0y >= exposure T≈4.999y)."
        )

    def test_ctrl_risk_weight_is_100_pct_unrated_corporate(self, result) -> None:
        """
        Risk weight for CRR-P1123-L-CTRL must be 1.0 (unrated corporate, CRR Art. 122).

        Arrange/Act: as above.
        Assert: risk_weight ≈ 1.0 (tolerance 1e-9).
        """
        rows = _find_rows(result, LOAN_REF_CTRL)
        assert rows, f"{LOAN_REF_CTRL} not found in any result set"

        rw = _total(rows, "risk_weight")
        assert rw == pytest.approx(1.0, abs=_RW_TOL), (
            f"risk_weight {rw:.6f} != 1.0. "
            f"Unrated corporate counterparty must receive 100% RW "
            f"under CRR Art. 122."
        )

    def test_ctrl_rwa_equals_ead_for_100pct_rw(self, result) -> None:
        """
        RWA for CRR-P1123-L-CTRL must equal ead_final (risk_weight = 1.0).

        Arrange/Act: as above.
        Assert: rwa_final ≈ 76,870 (±£0.50).
        """
        rows = _find_rows(result, LOAN_REF_CTRL)
        assert rows, f"{LOAN_REF_CTRL} not found in any result set"

        rwa = _total(rows, "rwa_final")
        assert rwa == pytest.approx(EXPECTED_RWA_CTRL, abs=_ABS_TOL), (
            f"rwa_final {rwa:,.2f} != expected {EXPECTED_RWA_CTRL:,.2f} "
            f"(= ead_final × 1.0 for unrated corporate, no maturity mismatch)."
        )

    # ------------------------------------------------------------------
    # Primary assertions — CRR-P1123-L-BIND (load-bearing: SFT, corp_bond exposure)
    # ------------------------------------------------------------------

    def test_bind_ead_final_reflects_he_gross_up(self, result) -> None:
        """
        E* for the BIND loan must include the (1+HE) exposure gross-up per Art. 223(5).

        HE = 6% × sqrt(0.5) = 4.2426% for corp_bond CQS 2, 1-5yr residual maturity
        (CRR Art. 224 Table 1, 10-day base scaled to 5 days for SFT).

        E(1+HE) = 1,000,000 × 1.042426 = 1,042,426.41
        C*(1−HC) = 950,000 × 0.985858 = 936,565.03
        E* = max(0, 1,042,426.41 − 936,565.03) = 105,861.38

        No maturity mismatch: collateral t=2.0y ≥ BIND exposure T≈0.5y.

        Arrange: £1M SFT (is_sft=True), corp_bond exposure (CQS 2, 4yr),
                 GBP govt_bond CQS 1 collateral (MV=950k), liquidation_period_days=None.
        Act:     full CRR SA pipeline.
        Assert:  ead_final ≈ 105,861 (±£0.50).

        Pre-fix (HE omitted): ead_final ≈ 63,435 (equal to RUNB — indistinguishable).
        """
        # Arrange / Act (pipeline run in fixture)
        rows = _find_rows(result, LOAN_REF_BIND)
        assert rows, f"{LOAN_REF_BIND} not found in any result set"

        # Assert — THIS IS THE LOAD-BEARING ASSERTION: must fail pre-fix
        ead = _total(rows, "ead_final")
        assert ead == pytest.approx(EXPECTED_EAD_BIND, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} != expected {EXPECTED_EAD_BIND:,.2f}. "
            f"If ead_final ≈ {PRE_FIX_EAD_BIND:,.2f} the engine is omitting the "
            f"(1+HE) gross-up on the exposure side (Art. 223(5)). "
            f"HE = 6% × sqrt(0.5) = 4.2426% for corp_bond CQS 2 SFT exposure."
        )

    def test_bind_risk_weight_is_100_pct_unrated_corporate(self, result) -> None:
        """
        Risk weight for CRR-P1123-L-BIND must be 1.0 (unrated corporate, CRR Art. 122).

        Arrange/Act: as above.
        Assert: risk_weight ≈ 1.0 (tolerance 1e-9).
        """
        rows = _find_rows(result, LOAN_REF_BIND)
        assert rows, f"{LOAN_REF_BIND} not found in any result set"

        rw = _total(rows, "risk_weight")
        assert rw == pytest.approx(1.0, abs=_RW_TOL), (
            f"risk_weight {rw:.6f} != 1.0. "
            f"Unrated corporate counterparty must receive 100% RW "
            f"under CRR Art. 122."
        )

    def test_bind_rwa_equals_ead_for_100pct_rw(self, result) -> None:
        """
        RWA for CRR-P1123-L-BIND must equal ead_final (risk_weight = 1.0).

        Arrange/Act: as above.
        Assert: rwa_final ≈ 105,861 (±£0.50).

        Pre-fix: rwa_final ≈ 63,435 (engine omits HE gross-up).
        """
        rows = _find_rows(result, LOAN_REF_BIND)
        assert rows, f"{LOAN_REF_BIND} not found in any result set"

        rwa = _total(rows, "rwa_final")
        assert rwa == pytest.approx(EXPECTED_RWA_BIND, abs=_ABS_TOL), (
            f"rwa_final {rwa:,.2f} != expected {EXPECTED_RWA_BIND:,.2f} "
            f"(= ead_final × 1.0 for unrated corporate, Art. 223(5) HE gross-up applied)."
        )

    # ------------------------------------------------------------------
    # Primary assertions — CRR-P1123-L-RUNB (SFT, cash exposure, HE=0)
    # ------------------------------------------------------------------

    def test_runb_ead_final_cash_exposure_he_zero(self, result) -> None:
        """
        E* for the RUNB loan (SFT, cash exposure) must not include any HE gross-up.

        Cash has 0% exposure volatility haircut under CRR Art. 224 Table 1.
        T_m = 5 days (Art. 224(2)(c)).  HC = 2% × sqrt(0.5) = 1.4142%.  HFX = 0.
        No maturity mismatch: collateral t=2.0y ≥ RUNB exposure T≈0.5y.
        E* = max(0, 1,000,000 − 936,565.03) = 63,434.97

        Arrange: £1M SFT (is_sft=True), cash exposure,
                 GBP govt_bond CQS 1 collateral (MV=950k).
        Act:     full CRR SA pipeline.
        Assert:  ead_final ≈ 63,435 (±£0.50).
        """
        rows = _find_rows(result, LOAN_REF_RUNB)
        assert rows, f"{LOAN_REF_RUNB} not found in any result set"

        ead = _total(rows, "ead_final")
        assert ead == pytest.approx(EXPECTED_EAD_RUNB, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} != expected {EXPECTED_EAD_RUNB:,.2f}. "
            f"Cash exposure (RUNB) must have HE=0, T_m=5d (Art. 224(2)(c))."
        )

    def test_runb_risk_weight_is_100_pct_unrated_corporate(self, result) -> None:
        """
        Risk weight for CRR-P1123-L-RUNB must be 1.0 (unrated corporate, CRR Art. 122).

        Arrange/Act: as above.
        Assert: risk_weight ≈ 1.0 (tolerance 1e-9).
        """
        rows = _find_rows(result, LOAN_REF_RUNB)
        assert rows, f"{LOAN_REF_RUNB} not found in any result set"

        rw = _total(rows, "risk_weight")
        assert rw == pytest.approx(1.0, abs=_RW_TOL), (
            f"risk_weight {rw:.6f} != 1.0. "
            f"Unrated corporate counterparty must receive 100% RW "
            f"under CRR Art. 122."
        )

    def test_runb_rwa_equals_ead_for_100pct_rw(self, result) -> None:
        """
        RWA for CRR-P1123-L-RUNB must equal ead_final (risk_weight = 1.0).

        Arrange/Act: as above.
        Assert: rwa_final ≈ 63,435 (±£0.50).
        """
        rows = _find_rows(result, LOAN_REF_RUNB)
        assert rows, f"{LOAN_REF_RUNB} not found in any result set"

        rwa = _total(rows, "rwa_final")
        assert rwa == pytest.approx(EXPECTED_RWA_RUNB, abs=_ABS_TOL), (
            f"rwa_final {rwa:,.2f} != expected {EXPECTED_RWA_RUNB:,.2f} "
            f"(= ead_final × 1.0 for unrated corporate)."
        )

    # ------------------------------------------------------------------
    # Pre-fix regression guards — BIND must NOT equal RUNB pre-fix
    # ------------------------------------------------------------------

    def test_bind_ead_final_not_equal_to_pre_fix_no_he_value(self, result) -> None:
        """
        CRR-P1123-L-BIND.ead_final must NOT match the pre-fix value (63,434.97).

        Pre-fix: engine omits (1+HE) → E* = max(0, E − C*(1−HC)) = 63,434.97.
        Post-fix: E* = max(0, E(1+HE) − C*(1−HC)) = 105,861.38.

        This assertion fails when the engine still omits the HE gross-up.

        Arrange/Act: as above.
        Assert: ead_final ≉ 63,434.97 (abs tolerance ±0.50).
        """
        rows = _find_rows(result, LOAN_REF_BIND)
        assert rows, f"{LOAN_REF_BIND} not found in any result set"

        ead = _total(rows, "ead_final")
        assert ead != pytest.approx(PRE_FIX_EAD_BIND, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} matches pre-fix no-HE value {PRE_FIX_EAD_BIND:,.2f}. "
            f"The engine is still omitting the (1+HE) gross-up on the exposure side "
            f"(CRR Art. 223(5)). BIND must differ from RUNB by E×HE ≈ 42,426."
        )

    def test_bind_ead_exceeds_runb_ead_by_he_increment(self, result) -> None:
        """
        CRR-P1123-L-BIND.ead_final must exceed CRR-P1123-L-RUNB.ead_final by ≈ 42,426.

        The HE gross-up adds E × HE = 1,000,000 × 4.2426% = 42,426.41 to E* for BIND.
        This cross-row invariant is only satisfied when the engine applies (1+HE).

        Arrange/Act: as above.
        Assert: |bind_ead − runb_ead − _BIND_HE_INCREMENT| < 1.0 (±£1.00).
        """
        bind_rows = _find_rows(result, LOAN_REF_BIND)
        runb_rows = _find_rows(result, LOAN_REF_RUNB)
        assert bind_rows, f"{LOAN_REF_BIND} not found in any result set"
        assert runb_rows, f"{LOAN_REF_RUNB} not found in any result set"

        bind_ead = _total(bind_rows, "ead_final")
        runb_ead = _total(runb_rows, "ead_final")
        gap = bind_ead - runb_ead
        assert gap == pytest.approx(_BIND_HE_INCREMENT, abs=1.0), (
            f"BIND.ead_final − RUNB.ead_final = {gap:,.2f}, "
            f"expected ≈ {_BIND_HE_INCREMENT:,.2f} (= E × HE = 1M × 4.2426%). "
            f"Gap is 0 pre-fix (BIND treated same as RUNB, HE omitted)."
        )

    # ------------------------------------------------------------------
    # Cross-row directional checks
    # ------------------------------------------------------------------

    def test_bind_ead_exceeds_runb_ead(self, result) -> None:
        """
        CRR-P1123-L-BIND.ead_final must exceed CRR-P1123-L-RUNB.ead_final.

        BIND ≈ 105,861  >  RUNB ≈ 63,435

        Both are SFT with identical collateral; BIND's HE gross-up is the only
        difference.  This invariant collapses to 0 pre-fix.

        Arrange/Act: as above.
        Assert: rwa(BIND) > rwa(RUNB).
        """
        bind_rows = _find_rows(result, LOAN_REF_BIND)
        runb_rows = _find_rows(result, LOAN_REF_RUNB)
        assert bind_rows, f"{LOAN_REF_BIND} not found in any result set"
        assert runb_rows, f"{LOAN_REF_RUNB} not found in any result set"

        bind_ead = _total(bind_rows, "ead_final")
        runb_ead = _total(runb_rows, "ead_final")

        assert bind_ead > runb_ead, (
            f"BIND.ead_final {bind_ead:,.2f} is not greater than "
            f"RUNB.ead_final {runb_ead:,.2f}. "
            f"HE gross-up on BIND must raise E* above the cash-exposure RUNB value."
        )

    def test_all_exposures_collateral_reduces_below_drawn_amount(self, result) -> None:
        """
        BIND and RUNB EADs must be less than the £1M unprotected drawn amount.

        Collateral (govt_bond MV=950k) must always reduce the net exposure.
        If any EAD = 1,000,000 the CRM processor ignored the collateral.

        Note: CTRL is excluded from this check because the maturity mismatch
        adjustment reduces the effective collateral value to ~340,150 (Pa=0.368),
        so the CTRL EAD (659,850) is well below 1M anyway — but the intent of
        the assertion is different from the SFT-related HE mechanics.

        Arrange/Act: as above.
        Assert: ead_final < 1,000,000 for BIND and RUNB.
        """
        for loan_ref in (LOAN_REF_BIND, LOAN_REF_RUNB):
            rows = _find_rows(result, loan_ref)
            assert rows, f"{loan_ref} not found in any result set"
            ead = _total(rows, "ead_final")
            assert ead < 1_000_000.0, (
                f"{loan_ref}.ead_final {ead:,.2f} is not less than unprotected 1M. "
                f"Collateral (govt_bond MV=950k) appears to be providing no EAD reduction."
            )
