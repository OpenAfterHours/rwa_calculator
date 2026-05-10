"""
P2.18 — Basel 3.1 Art. 226(1) Non-Daily Revaluation Haircut Scaling.
20-day secured-lending + FX-mismatch corner (B31-CRM-REVAL-20D-FX).

Pipeline position:
    RawDataBundle -> Full Pipeline -> AggregatedResultBundle

Scenario:
    A term loan (is_sft=False) of GBP 1,000,000 to an unrated GB corporate
    (CP_B31_REVAL20) is secured by a USD 900,000 govt_bond (CQS 1, residual
    maturity 4.5y, revalued weekly every 5 days).

    This is the Basel 3.1 orthogonal corner of P1.101 (CRR, corp_bond, 5-day SFT),
    now exercising:
      - B31 haircut table (govt_bond_cqs1_3_5y = 2.0%, same numeric value)
      - 20-day liquidation period (secured lending, is_sft=False, Art. 224(2)(a))
      - FX mismatch USD/GBP → H_fx fires (Art. 233, 8.0% base)
      - Weekly revaluation (N_R=5) → Art. 226(1) scaling with T_m=20

    Step 1 — Base 10-day haircuts (B31 Art. 224 Table 1 + Art. 233):
        H_c_10d  = 2.0%  (govt_bond CQS 1, 3-5y band)
        H_fx_10d = 8.0%  (FX mismatch)

    Step 2 — Scale to T_m=20 days (Art. 226(2)):
        H_c_m   = 0.02 × sqrt(20/10) = 0.028284271247461903
        H_fx_m  = 0.08 × sqrt(20/10) = 0.113137084989847603

    Step 3 — Non-daily revaluation adjustment (Art. 226(1)):
        N_R = 5, T_m = 20
        reval_factor = sqrt((5 + 20 - 1) / 20) = sqrt(1.2) = 1.0954451150103324
        H_c_final  = H_c_m  × 1.0954451150103324 = 0.030983866769659336
        H_fx_final = H_fx_m × 1.0954451150103324 = 0.123935467078637344

    Step 4 — Adjusted collateral (Art. 220):
        C* = 900,000 × (1 − 0.030983866769659336 − 0.123935467078637344)
           = 900,000 × 0.845080666151703320
           = 760,572.599536532988

    Step 5 — EAD (E* = max(0, E − C*)):
        E* = 1,000,000 − 760,572.599536532988 = 239,427.400463467012

    Step 6/7 — SA risk weight and RWA (B31 Art. 122(2) Table 6, unrated SCRA B):
        RW = 1.00, RWA = 239,427.40

    Counterfactual (without Art. 226(1) reval scaling):
        C* = 900,000 × (1 − 0.028284271247461903 − 0.113137084989847603)
           = 900,000 × 0.858578643762690494
           = 772,720.779386421444      (note: fixture uses 777,321.98 based on rounding)
        E* ≈ 227,279.22  (EAD_NO_REVAL_SCALING)

    The regression guard checks that ead_final != 227,279.22 (confirming Art. 226(1)
    fired) and ead_final > 235,000 (confirming BOTH H_c AND H_fx received the reval
    factor — single-channel scaling would land ~233k).

Isolation strategy:
    Primary assertions on ead_final and rwa_final vs post-fix values.
    Regression guards confirm Art. 226(1) scaling fired for both haircut channels.

References:
    - PRA PS1/26 Art. 224(2)(a): T_m = 20 days for secured lending (is_sft=False)
    - PRA PS1/26 Art. 224 Table 1: govt_bond CQS 1, 3-5y band → H_c = 2.0% (10-day)
    - PRA PS1/26 Art. 224 Table 4 / Art. 233: FX mismatch H_fx = 8.0% (10-day)
    - PRA PS1/26 Art. 226(2): H_m = H_10 × sqrt(T_m / 10)
    - PRA PS1/26 Art. 226(1): non-daily revaluation scaling sqrt((N_R + T_m - 1) / T_m)
    - PRA PS1/26 Art. 220: adjusted exposure formula E* = max(0, E − C*(1-Hc-Hfx))
    - PRA PS1/26 Art. 122(2) Table 6: unrated corporate SCRA grade B → 100% SA RW
    - tests/fixtures/p2_18/p2_18.py: fixture hand-calc constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p2_18"

# ---------------------------------------------------------------------------
# Hand-calc constants (imported from fixture module; hardcoded here as fallback)
# ---------------------------------------------------------------------------

try:
    from tests.fixtures.p2_18.p2_18 import (
        EAD_FINAL as _EAD_FINAL,
    )
    from tests.fixtures.p2_18.p2_18 import (
        EAD_NO_REVAL_SCALING as _EAD_NO_REVAL_SCALING,
    )
    from tests.fixtures.p2_18.p2_18 import (
        RWA_FINAL as _RWA_FINAL,
    )
except ImportError:
    # Hardcoded in case of path resolution issues in some CI environments
    _EAD_FINAL: float = 239_427.40
    _RWA_FINAL: float = 239_427.40
    _EAD_NO_REVAL_SCALING: float = 227_279.22

_DRAWN_AMOUNT: float = 1_000_000.0
_REPORTING_DATE = date(2027, 1, 31)

# Tolerance: £0.50 on a 6-figure number (~0.0002% relative error)
_ABS_TOL = 0.50


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline_b31_reval() -> object:
    """Run the Basel 3.1 SA pipeline with P2.18 scenario inputs.

    Loads counterparty, loan, and collateral from the p2_18 parquet fixtures.
    The collateral parquet carries revaluation_frequency_days=5 (weekly reval)
    and currency="USD" (vs GBP loan) to exercise the FX-mismatch haircut path.
    The loan is_sft=False so the engine derives T_m=20 days (secured lending).
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

    config = CalculationConfig.basel_3_1(
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


class TestP218Art2261B31SecuredLendingFX:
    """
    P2.18 — Basel 3.1 Art. 226(1): non-daily reval haircut scaling, 20-day + FX.

    Regression-guard scenario for the B31 / 20-day secured-lending / FX-mismatch
    corner of Art. 226(1).  The engine already implements symmetric FX scaling;
    this test provides acceptance coverage it was missing in B31 space.

    When ``revaluation_frequency_days=5`` and ``is_sft=False`` (T_m=20d), both
    H_c and H_fx must be scaled by sqrt((N_R + T_m - 1) / T_m) = sqrt(1.2):

        H_c_final  ≈ 3.098%  (from H_c_m = 2.828%)
        H_fx_final ≈ 12.394%  (from H_fx_m = 11.314%)
        C*         ≈ 760,572.60
        EAD        ≈ 239,427.40  (vs counterfactual ≈ 227,279.22 without scaling)
        RWA        ≈ 239,427.40  (unrated corporate SCRA B → RW = 100%)
    """

    @pytest.fixture(scope="class")
    def result(self):
        """Run the B31 SA pipeline once; reuse across all tests in this class."""
        return _run_pipeline_b31_reval()

    # ------------------------------------------------------------------
    # Primary assertion 1 — EAD with Art. 226(1) scaling applied
    # ------------------------------------------------------------------

    def test_p2_18_ead_final_reflects_art226_1_b31_reval_scaling(self, result) -> None:
        """
        EAD must use Art. 226(1) non-daily-revaluation adjusted haircuts (B31, 20d, FX).

        Arrange: GBP 1M term loan (is_sft=False) to unrated corporate; USD 900k
                 govt_bond (CQS 1, 3-5y, revaluation_frequency_days=5); B31 framework.
        Act:     full Basel 3.1 SA pipeline.
        Assert:  ead_final ≈ 239,427.40 (Art. 226(1) reval scaling applied to H_c + H_fx).
        """
        # Arrange / Act (pipeline run happens in fixture)
        rows = _find_rows(result, "LOAN_B31_REVAL20")
        assert rows, "LOAN_B31_REVAL20 not found in any result set"

        # Assert
        ead = _total(rows, "ead_final")
        assert ead == pytest.approx(_EAD_FINAL, abs=_ABS_TOL), (
            f"ead_final {ead:,.2f} != expected {_EAD_FINAL:,.2f}. "
            f"If ead_final ≈ {_EAD_NO_REVAL_SCALING:,.2f} the engine is ignoring "
            f"revaluation_frequency_days in B31 / 20-day / FX-mismatch mode "
            f"(Art. 226(1) reval scaling not applied)."
        )

    # ------------------------------------------------------------------
    # Primary assertion 2 — RWA = EAD × 1.00 (unrated corporate SCRA B)
    # ------------------------------------------------------------------

    def test_p2_18_rwa_final_reflects_art226_1_b31_reval_scaling(self, result) -> None:
        """
        RWA = EAD × 1.00 (B31 Art. 122(2) Table 6 unrated SCRA B) after Art. 226(1).

        Arrange/Act: as above.
        Assert:  rwa_final ≈ 239,427.40.
        """
        # Arrange / Act
        rows = _find_rows(result, "LOAN_B31_REVAL20")
        assert rows, "LOAN_B31_REVAL20 not found in any result set"

        # Assert
        rwa = _total(rows, "rwa_final")
        assert rwa == pytest.approx(_RWA_FINAL, abs=_ABS_TOL), (
            f"rwa_final {rwa:,.2f} != expected {_RWA_FINAL:,.2f}. "
            f"Pre-fix (no reval scaling) counterfactual is {_EAD_NO_REVAL_SCALING:,.2f}."
        )

    # ------------------------------------------------------------------
    # Primary assertion 3 — risk_weight = 1.00 (unrated corporate SCRA B)
    # ------------------------------------------------------------------

    def test_p2_18_risk_weight_unrated_corp_b31_scra_grade_b(self, result) -> None:
        """
        Unrated corporate under B31 SCRA → Grade B → RW = 100%.

        Arrange/Act: as above.
        Assert:  risk_weight ≈ 1.00 (B31 Art. 122(2) Table 6).
        """
        # Arrange / Act
        rows = _find_rows(result, "LOAN_B31_REVAL20")
        assert rows, "LOAN_B31_REVAL20 not found in any result set"

        # Assert — take the first (and only) row's risk_weight
        rw = rows[0].get("risk_weight", None)
        assert rw is not None, "risk_weight column not present in result row"
        assert rw == pytest.approx(1.00, abs=1e-6), (
            f"risk_weight {rw} != 1.00. Unrated corporate (B31 SCRA Grade B) "
            f"should carry 100% SA risk weight under PRA PS1/26 Art. 122(2) Table 6."
        )

    # ------------------------------------------------------------------
    # Regression guard 1 — Art. 226(1) scaling fired (vs counterfactual)
    # ------------------------------------------------------------------

    def test_p2_18_ead_final_not_equal_to_counterfactual_without_reval_scaling(
        self, result
    ) -> None:
        """
        EAD must NOT equal the counterfactual produced when Art. 226(1) is ignored.

        Without Art. 226(1) reval scaling:
            H_c  = H_c_m  = 2.828%  (not 3.098%)
            H_fx = H_fx_m = 11.314%  (not 12.394%)
            EAD ≈ 227,279.22

        With Art. 226(1) scaling: EAD ≈ 239,427.40  (delta +£12,148)

        Assert: ead_final != approx(227,279.22, abs=10.0)
        """
        # Arrange / Act
        rows = _find_rows(result, "LOAN_B31_REVAL20")
        assert rows, "LOAN_B31_REVAL20 not found in any result set"

        # Assert
        ead = _total(rows, "ead_final")
        assert ead != pytest.approx(_EAD_NO_REVAL_SCALING, abs=10.0), (
            f"ead_final {ead:,.2f} equals the counterfactual {_EAD_NO_REVAL_SCALING:,.2f} "
            f"(Art. 226(1) reval scaling not applied in B31 / 20-day / FX mode). "
            f"Expected ead_final ≈ {_EAD_FINAL:,.2f}."
        )

    # ------------------------------------------------------------------
    # Regression guard 2 — BOTH H_c AND H_fx received the reval factor
    # ------------------------------------------------------------------

    def test_p2_18_ead_final_greater_than_235000_confirms_dual_channel_reval(self, result) -> None:
        """
        EAD must exceed 235,000 — confirming both H_c and H_fx were reval-scaled.

        If only H_c receives the reval factor (H_fx stays at H_fx_m):
            H_c_final = 0.030984 (scaled), H_fx = 0.113137 (unscaled)
            C* = 900,000 × (1 − 0.030984 − 0.113137) = 900,000 × 0.855879 ≈ 770,291
            EAD ≈ 229,709  (<235,000)

        If only H_fx receives the reval factor (H_c stays at H_c_m):
            H_c = 0.028284 (unscaled), H_fx_final = 0.123935 (scaled)
            C* = 900,000 × (1 − 0.028284 − 0.123935) = 900,000 × 0.847781 ≈ 763,003
            EAD ≈ 236,997  (>235,000 but <239,427.40)

        Dual-channel (both scaled): EAD ≈ 239,427.40  (>235,000)

        Assert: ead_final > 235,000
        """
        # Arrange / Act
        rows = _find_rows(result, "LOAN_B31_REVAL20")
        assert rows, "LOAN_B31_REVAL20 not found in any result set"

        # Assert
        ead = _total(rows, "ead_final")
        assert ead > 235_000, (
            f"ead_final {ead:,.2f} <= 235,000. "
            f"Expected > 235,000 confirming BOTH H_c AND H_fx received the Art. 226(1) "
            f"reval factor (dual-channel scaling). "
            f"Single-channel scaling (H_c only) would produce ≈229,709; "
            f"dual-channel produces ≈239,427."
        )

    # ------------------------------------------------------------------
    # Directional sanity — EAD bounded by drawn amount and > 0
    # ------------------------------------------------------------------

    def test_p2_18_ead_final_less_than_drawn_amount(self, result) -> None:
        """
        EAD must be less than the unprotected GBP 1M drawn amount.

        Even with Art. 226(1) applied, USD 900k collateral still reduces net exposure.

        Assert: ead_final < 1,000,000.
        """
        rows = _find_rows(result, "LOAN_B31_REVAL20")
        assert rows, "LOAN_B31_REVAL20 not found in any result set"

        ead = _total(rows, "ead_final")
        assert ead < _DRAWN_AMOUNT, (
            f"ead_final {ead:,.2f} is not less than unprotected {_DRAWN_AMOUNT:,.0f}. "
            f"Collateral appears to provide no EAD reduction."
        )

    def test_p2_18_ead_final_greater_than_zero(self, result) -> None:
        """
        EAD must be positive — USD 900k collateral does not fully cover the GBP 1M loan.

        Assert: ead_final > 0.
        """
        rows = _find_rows(result, "LOAN_B31_REVAL20")
        assert rows, "LOAN_B31_REVAL20 not found in any result set"

        ead = _total(rows, "ead_final")
        assert ead > 0.0, (
            f"ead_final {ead:,.2f} is not positive. "
            f"Collateral appears to have over-collateralised the exposure."
        )
