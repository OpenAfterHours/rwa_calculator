"""
P1.186: CRR Art. 224(2)(a) — FX collateral haircut liquidation-period default for secured lending.

Pipeline position:
    RawDataBundle -> Full Pipeline -> AggregatedResultBundle

Scenario:
    One corporate counterparty (CP_P186, unrated, GB) secures two loans.

    LOAN_P186_SL  (is_sft=False):
        Art. 224(2)(a) mandates a 20-day liquidation period for secured lending
        when ``liquidation_period_days`` is not explicitly set on the collateral row.

    LOAN_P186_SFT (is_sft=True):
        Art. 224(2)(c) mandates a 5-day liquidation period for repo-style SFTs.

    Both loans are collateralised by an EUR-denominated government bond (CQS 1,
    residual maturity 2y, market_value=600,000) pledged directly to each loan.
    The collateral carries ``liquidation_period_days=None`` — the load-bearing
    input that forces the engine to derive T_m from the exposure's is_sft flag.

    Because the exposure currency is GBP and the collateral currency is EUR, the
    FX haircut (H_fx = 8%, CRR Art. 233) also fires and must be scaled together
    with the collateral haircut (H_c = 2%, CRR Art. 224 Table 1):

        H_m = H_10 × sqrt(T_m / 10)   (Art. 226(2))

    SL loan (20-day):
        H_c = 2% × sqrt(2) ≈ 2.8284%
        H_fx = 8% × sqrt(2) ≈ 11.3137%
        C* = 600,000 × (1 − 0.1414) ≈ 515,147.19
        EAD = 1,000,000 − 515,147.19 ≈ 484,852.81

    SFT loan (5-day):
        H_c = 2% × sqrt(0.5) ≈ 1.4142%
        H_fx = 8% × sqrt(0.5) ≈ 5.6569%
        C* = 600,000 × (1 − 0.0707) ≈ 557,573.59
        EAD = 1,000,000 − 557,573.59 ≈ 442,426.41

Engine bug (pre-fix):
    engine/crm/haircuts.py applies ``fill_null(10)`` on ``liquidation_period_days``,
    defaulting every exposure to a 10-day period regardless of ``is_sft``.
    This yields a flat H_c + H_fx = 2% + 8% = 10% and:
        C* = 600,000 × 0.90 = 540,000
        EAD (LOAN_P186_SL) = 1,000,000 − 540,000 = 460,000  ← PRE_FIX_EAD_SL

    The correct 20-day result is 484,852.81 — higher because the larger haircut
    reduces C* further.

References:
    - CRR Art. 224(2)(a): 20-day liquidation period — secured lending default
    - CRR Art. 224(2)(c): 5-day liquidation period — repo-style SFT default
    - CRR Art. 226(2): H_m = H_10 × sqrt(T_m / 10) scaling
    - CRR Art. 233: FX mismatch haircut (8% at 10 days)
    - CRR Art. 197(1)(b): eligible financial collateral — govt bond CQS 1
    - CRR Art. 122: SA corporate risk weights (unrated → 100%)
    - tests/fixtures/p1_186/p1_186.py: fixture hand-calc constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.acceptance.conftest import find_exposure_rows, total_field
from tests.fixtures.p1_186.p1_186 import (
    EXPECTED_EAD_SFT,
    EXPECTED_EAD_SL,
    LOAN_REF_SFT,
    LOAN_REF_SL,
    PRE_FIX_EAD_SL,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_186"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2025, 12, 31)
_ABS_TOL = 0.50  # £0.50 on a 6-figure EAD (~0.0001% relative error)
_RW_TOL = 1e-9  # tight tolerance for exact 100% risk weight

# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline_p186() -> object:
    """Run the CRR SA pipeline with P1.186 scenario inputs.

    Loads counterparty, loan, and collateral from the p1_186 parquet fixtures.
    The collateral parquet carries ``liquidation_period_days=None`` on both rows,
    forcing the engine to derive T_m from each exposure's ``is_sft`` flag.
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


class TestP1186Art2242FxHaircutSecuredLendingDefault:
    """
    P1.186 — CRR Art. 224(2)(a): when ``liquidation_period_days`` is None on
    the collateral row, the engine must derive the liquidation period from the
    exposure's ``is_sft`` flag:
        is_sft=False → 20 days  (secured lending, Art. 224(2)(a))
        is_sft=True  → 5 days   (repo-style SFT, Art. 224(2)(c))

    Both haircuts — collateral (H_c) and FX mismatch (H_fx) — must be scaled
    by sqrt(T_m / 10) (Art. 226(2)).

    Pre-fix: engine applies ``fill_null(10)`` → both exposures get 10-day haircuts.
        LOAN_P186_SL.ead_final ≈ 460,000  (flat 10-day, no scaling)
    Post-fix:
        LOAN_P186_SL.ead_final ≈ 484,852.81  (20-day scaled)
        LOAN_P186_SFT.ead_final ≈ 442,426.41  (5-day scaled)
    """

    @pytest.fixture(scope="class")
    def result(self):
        """Run the pipeline once; reuse across all tests in this class."""
        return _run_pipeline_p186()

    # ------------------------------------------------------------------
    # Primary assertions — LOAN_P186_SL (secured lending, 20-day)
    # ------------------------------------------------------------------

    def test_sl_ead_final_reflects_20_day_liquidation_period(self, result) -> None:
        """
        E* for the secured-lending loan must use the 20-day haircut scaling.

        Art. 224(2)(a) requires a 20-day liquidation period for secured lending
        when the collateral row does not specify ``liquidation_period_days``.

        Arrange: £1M corporate loan (is_sft=False), EUR govt bond collateral
                 (CQS 1, 2y residual, MV=600k), liquidation_period_days=None.
        Act:     full CRR SA pipeline.
        Assert:  ead_final ≈ 484,852.81 (±£0.50).

        Pre-fix (10-day flat): ead_final ≈ 460,000.00.
        """
        # Arrange / Act (pipeline run in fixture)
        rows = find_exposure_rows(result, LOAN_REF_SL)
        assert rows, f"{LOAN_REF_SL} not found in any result set"

        # Assert
        ead = total_field(rows, "ead_final")
        assert ead == pytest.approx(EXPECTED_EAD_SL, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} != expected {EXPECTED_EAD_SL:,.2f}. "
            f"If ead_final ≈ {PRE_FIX_EAD_SL:,.2f} the engine is applying the flat "
            f"10-day default (fill_null(10)) instead of deriving T_m=20 from "
            f"is_sft=False (CRR Art. 224(2)(a))."
        )

    def test_sl_risk_weight_is_100_pct_unrated_corporate(self, result) -> None:
        """
        Risk weight for LOAN_P186_SL must be 1.0 (unrated corporate, CRR Art. 122).

        Arrange/Act: as above.
        Assert: risk_weight ≈ 1.0 (tolerance 1e-9).
        """
        rows = find_exposure_rows(result, LOAN_REF_SL)
        assert rows, f"{LOAN_REF_SL} not found in any result set"

        rw = total_field(rows, "risk_weight")
        assert rw == pytest.approx(1.0, abs=_RW_TOL), (
            f"risk_weight {rw:.6f} != 1.0. "
            f"Unrated corporate counterparty (CP_P186) must receive 100% RW "
            f"under CRR Art. 122."
        )

    def test_sl_rwa_equals_ead_for_100pct_rw(self, result) -> None:
        """
        RWA for LOAN_P186_SL must equal ead_final (risk_weight = 1.0).

        Arrange/Act: as above.
        Assert: rwa_final ≈ 484,852.81 (±£0.50).
        """
        rows = find_exposure_rows(result, LOAN_REF_SL)
        assert rows, f"{LOAN_REF_SL} not found in any result set"

        rwa = total_field(rows, "rwa_final")
        assert rwa == pytest.approx(EXPECTED_EAD_SL, abs=_ABS_TOL), (
            f"rwa_final {rwa:,.2f} != expected {EXPECTED_EAD_SL:,.2f} "
            f"(= ead_final × 1.0 for unrated corporate)."
        )

    # ------------------------------------------------------------------
    # Primary assertions — LOAN_P186_SFT (SFT, 5-day)
    # ------------------------------------------------------------------

    def test_sft_ead_final_reflects_5_day_liquidation_period(self, result) -> None:
        """
        E* for the SFT loan must use the 5-day haircut scaling.

        Art. 224(2)(c) requires a 5-day liquidation period for repo-style SFTs
        when the collateral row does not specify ``liquidation_period_days``.

        Arrange: £1M corporate loan (is_sft=True), EUR govt bond collateral
                 (CQS 1, 2y residual, MV=600k), liquidation_period_days=None.
        Act:     full CRR SA pipeline.
        Assert:  ead_final ≈ 442,426.41 (±£0.50).
        """
        rows = find_exposure_rows(result, LOAN_REF_SFT)
        assert rows, f"{LOAN_REF_SFT} not found in any result set"

        ead = total_field(rows, "ead_final")
        assert ead == pytest.approx(EXPECTED_EAD_SFT, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} != expected {EXPECTED_EAD_SFT:,.2f}. "
            f"is_sft=True must derive T_m=5 (CRR Art. 224(2)(c))."
        )

    def test_sft_risk_weight_is_100_pct_unrated_corporate(self, result) -> None:
        """
        Risk weight for LOAN_P186_SFT must be 1.0 (unrated corporate, CRR Art. 122).

        Arrange/Act: as above.
        Assert: risk_weight ≈ 1.0 (tolerance 1e-9).
        """
        rows = find_exposure_rows(result, LOAN_REF_SFT)
        assert rows, f"{LOAN_REF_SFT} not found in any result set"

        rw = total_field(rows, "risk_weight")
        assert rw == pytest.approx(1.0, abs=_RW_TOL), (
            f"risk_weight {rw:.6f} != 1.0. "
            f"Unrated corporate counterparty (CP_P186) must receive 100% RW "
            f"under CRR Art. 122."
        )

    def test_sft_rwa_equals_ead_for_100pct_rw(self, result) -> None:
        """
        RWA for LOAN_P186_SFT must equal ead_final (risk_weight = 1.0).

        Arrange/Act: as above.
        Assert: rwa_final ≈ 442,426.41 (±£0.50).
        """
        rows = find_exposure_rows(result, LOAN_REF_SFT)
        assert rows, f"{LOAN_REF_SFT} not found in any result set"

        rwa = total_field(rows, "rwa_final")
        assert rwa == pytest.approx(EXPECTED_EAD_SFT, abs=_ABS_TOL), (
            f"rwa_final {rwa:,.2f} != expected {EXPECTED_EAD_SFT:,.2f} "
            f"(= ead_final × 1.0 for unrated corporate)."
        )

    # ------------------------------------------------------------------
    # Regression guards — pre-fix 10-day default must NOT appear
    # ------------------------------------------------------------------

    def test_sl_ead_final_not_equal_to_pre_fix_10_day_value(self, result) -> None:
        """
        LOAN_P186_SL.ead_final must NOT match the pre-fix 10-day flat value.

        Pre-fix: fill_null(10) → H_c=2%, H_fx=8%, C*=540,000, EAD=460,000.
        Post-fix: T_m=20 scaled → EAD ≈ 484,852.81.

        This assertion fails when the engine still applies the 10-day default.

        Arrange/Act: as above.
        Assert: ead_final ≉ 460,000.00 (abs tolerance ±0.50).
        """
        rows = find_exposure_rows(result, LOAN_REF_SL)
        assert rows, f"{LOAN_REF_SL} not found in any result set"

        ead = total_field(rows, "ead_final")
        assert ead != pytest.approx(PRE_FIX_EAD_SL, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} matches pre-fix 10-day value {PRE_FIX_EAD_SL:,.2f}. "
            f"The engine is still applying fill_null(10) instead of deriving T_m=20 "
            f"from is_sft=False (CRR Art. 224(2)(a))."
        )

    def test_sl_ead_final_exceeds_pre_fix_by_more_than_1_unit(self, result) -> None:
        """
        LOAN_P186_SL.ead_final must be strictly greater than PRE_FIX_EAD_SL + 1.

        The 20-day liquidation period produces larger haircuts (H_c + H_fx = 14.14%)
        than the 10-day flat default (H_c + H_fx = 10%), reducing C* further and
        raising EAD from 460,000 to 484,852.81.

        This strict inequality is only satisfied when the engine scales to 20 days.

        Arrange/Act: as above.
        Assert: ead_final > 460,001.00.
        """
        rows = find_exposure_rows(result, LOAN_REF_SL)
        assert rows, f"{LOAN_REF_SL} not found in any result set"

        ead = total_field(rows, "ead_final")
        assert ead > PRE_FIX_EAD_SL + 1.0, (
            f"ead_final {ead:,.2f} is not strictly greater than "
            f"PRE_FIX_EAD_SL + 1.0 = {PRE_FIX_EAD_SL + 1.0:,.2f}. "
            f"Expected post-fix EAD to exceed the pre-fix 10-day value by ~24,852."
        )

    # ------------------------------------------------------------------
    # Directional sanity checks
    # ------------------------------------------------------------------

    def test_sl_ead_final_less_than_unprotected(self, result) -> None:
        """
        LOAN_P186_SL.ead_final must be less than the unprotected EAD (1,000,000).

        Collateral with EUR govt bond (600k MV) must reduce the net exposure.
        If ead_final = 1M the CRM processor ignored the collateral entirely.

        Arrange/Act: as above.
        Assert: ead_final < 1,000,000.
        """
        rows = find_exposure_rows(result, LOAN_REF_SL)
        assert rows, f"{LOAN_REF_SL} not found in any result set"

        ead = total_field(rows, "ead_final")
        assert ead < 1_000_000.0, (
            f"ead_final {ead:,.2f} is not less than unprotected 1M. "
            f"Collateral appears to be providing no EAD reduction."
        )

    def test_sl_ead_greater_than_sft_ead(self, result) -> None:
        """
        LOAN_P186_SL.ead_final must exceed LOAN_P186_SFT.ead_final.

        The 20-day SL haircut is larger than the 5-day SFT haircut, so the
        adjusted collateral value is smaller for SL → higher net exposure.

        Expected: 484,852.81 > 442,426.41.

        Arrange/Act: as above.
        Assert: sl_ead > sft_ead.
        """
        sl_rows = find_exposure_rows(result, LOAN_REF_SL)
        sft_rows = find_exposure_rows(result, LOAN_REF_SFT)
        assert sl_rows, f"{LOAN_REF_SL} not found in any result set"
        assert sft_rows, f"{LOAN_REF_SFT} not found in any result set"

        sl_ead = total_field(sl_rows, "ead_final")
        sft_ead = total_field(sft_rows, "ead_final")
        assert sl_ead > sft_ead, (
            f"LOAN_P186_SL.ead_final {sl_ead:,.2f} is not greater than "
            f"LOAN_P186_SFT.ead_final {sft_ead:,.2f}. "
            f"20-day liquidation (SL) must produce a larger haircut and higher EAD "
            f"than 5-day liquidation (SFT)."
        )
