"""
P1.151 — Basel 3.1 F-IRB Art. 161(1)(e)/(f)/(g) Purchased Receivables LGD Routing.

Validates that the engine selects the correct supervisory LGD for three distinct
purchased-receivable sub-types under Basel 3.1 F-IRB, driven by the
``purchased_receivables_subtype`` column rather than the generic ``seniority`` column.

Sub-type LGD rules (PRA PS1/26 Art. 161(1)):
    (e) Senior purchased corporate receivables:        LGD = 40%
    (f) Subordinated purchased corporate receivables:  LGD = 100%
    (g) Dilution risk of purchased receivables:        LGD = 100% (up from CRR 75%)

Without the purchased_receivables_subtype routing the engine falls through to the
generic F-IRB supervisory LGD table, giving:
    - LOAN_PR_SENIOR_001   → LGD = 40%  (coincidentally correct)
    - LOAN_PR_SUB_001      → LGD = 75%  (standard subordinated — understated by 25 pp)
    - LOAN_PR_DILUTION_001 → LGD = 40%  (seniority="senior" fallback — understated by 60 pp)

The critical design test: LOAN_PR_DILUTION_001 has seniority="senior" but
purchased_receivables_subtype="dilution_risk".  Pre-fix both the senior and dilution
rows receive LGD=0.40 via the seniority fallback.  Post-fix the dilution row receives
LGD=1.00 driven by its purchased_receivables_subtype.

Hand-calculation (from scenario-architect, B31 F-IRB):
    Counterparty: CP_PR_CORP_001 — corporate, GB, PD=0.01, non-SME
    Reporting date: 2027-12-31 (from fixture)
    M = 1.0 year (maturity_date=2028-12-31 − reporting_date=2027-12-31)
    PD floored = max(0.01, 0.0005) = 0.01   (B31 corporate floor = 0.05%)
    R = 0.19278368
    N[...] = 0.14025178
    MA = 1.00000000 (M=1.0y exactly)

    LOAN_PR_SENIOR_001 (EAD=1,000,000, LGD=0.40):
        K = (0.40×0.14025178 − 0.01×0.40)×1.0 = 0.05210071
        RW = 0.65125888   RWA = 651,258.88   EL = 4,000.00

    LOAN_PR_SUB_001 (EAD=500,000, LGD=1.00):
        K = (1.00×0.14025178 − 0.01×1.00)×1.0 = 0.13025178
        RW = 1.62814723   RWA = 814,073.61   EL = 5,000.00

    LOAN_PR_DILUTION_001 (EAD=200,000, LGD=1.00):
        K = same as SUB (same PD, same LGD) = 0.13025178
        RW = 1.62814723   RWA = 325,629.45   EL = 2,000.00

Pre-fix failure modes (current engine behaviour):
    LOAN_PR_SENIOR_001   → LGD=0.40   (coincidentally correct via seniority fallback)
    LOAN_PR_SUB_001      → LGD=0.75   (standard subordinated, NOT purchased receivables)
    LOAN_PR_DILUTION_001 → LGD=0.40   (seniority="senior" fallback, completely wrong)

Regulatory references:
    - PRA PS1/26 Art. 161(1)(e): senior purchased receivables LGD = 40%
    - PRA PS1/26 Art. 161(1)(f): subordinated purchased receivables LGD = 100%
    - PRA PS1/26 Art. 161(1)(g): dilution risk LGD = 100% (CRR was 75%)
    - PRA PS1/26 Art. 163(1)(a): corporate PD floor = 0.05%
    - BCBS CRE32.3–CRE32.5: purchased receivable F-IRB treatment overview

Code references (post-fix):
    - src/rwa_calc/data/tables/irb_lgd.py: purchased_receivables_subtype LGD dispatch
    - src/rwa_calc/engine/irb/namespace.py: F-IRB supervisory LGD selection
    - tests/fixtures/p1_151/p1_151.py: scenario constants and fixture builders
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_151.p1_151 import (
    COUNTERPARTY_REF,
    DRAWN_DILUTION,
    DRAWN_SENIOR,
    DRAWN_SUB,
    LGD_DILUTION,
    LGD_SENIOR,
    LGD_SUB,
    LOAN_REF_DILUTION,
    LOAN_REF_SENIOR,
    LOAN_REF_SUB,
    PD,
    REPORTING_DATE,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_151"

# ---------------------------------------------------------------------------
# Tolerances (from scenario-architect)
# ---------------------------------------------------------------------------

_ABS_TOL_LGD = 1e-6    # exact LGD comparison — supervisory scalars are hard-coded
_ABS_TOL_PD = 1e-6     # exact PD comparison
_ABS_TOL_RWA = 1e-2    # ±£0.01 on RWA (tight — matches scenario hand-calc exactly)
_ABS_TOL_EL = 1e-2     # ±£0.01 on expected loss

# ---------------------------------------------------------------------------
# Expected values (from scenario-architect hand-calculation)
# ---------------------------------------------------------------------------

# Common IRB intermediate values (all three rows share the same PD and R).
# Values computed at full f64 precision (the architect's prior rounded constants
# carried ~0.02% error against the engine's polars-normal-stats outputs).
_EXPECTED_R = 0.19278368
_EXPECTED_N_QUANTILE = 0.14027268
_EXPECTED_MA = 1.0

# LOAN_PR_SENIOR_001 — Art. 161(1)(e) LGD=40%
_EXPECTED_K_SENIOR = 0.05210907
_EXPECTED_RW_SENIOR = 0.65136339
_EXPECTED_RWA_SENIOR = 651_363.39
_EXPECTED_EL_SENIOR = 4_000.00

# LOAN_PR_SUB_001 — Art. 161(1)(f) LGD=100%
_EXPECTED_K_SUB = 0.13027268
_EXPECTED_RW_SUB = 1.62840847
_EXPECTED_RWA_SUB = 814_204.24
_EXPECTED_EL_SUB = 5_000.00

# LOAN_PR_DILUTION_001 — Art. 161(1)(g) LGD=100%
_EXPECTED_K_DILUTION = 0.13027268
_EXPECTED_RW_DILUTION = 1.62840847
_EXPECTED_RWA_DILUTION = 325_681.70
_EXPECTED_EL_DILUTION = 2_000.00

# Pre-fix wrong LGDs (what the engine currently returns without subtype routing)
_WRONG_LGD_SUB = 0.75       # standard subordinated, not purchased receivables
_WRONG_LGD_DILUTION = 0.40  # seniority="senior" fallback, not dilution_risk


# ---------------------------------------------------------------------------
# Pipeline runner — module-scoped so the pipeline runs once for all tests
# ---------------------------------------------------------------------------


def _run_pipeline_p1151() -> object:
    """
    Run the Basel 3.1 F-IRB pipeline with P1.151 scenario inputs.

    Loads counterparty, loan, rating, and model_permission from the p1_151 parquet
    fixtures.  Empty facilities, facility_mappings, and lending_mappings are
    provided with the minimum schema required by the loader.

    Reporting date = 2027-12-31 (from fixture REPORTING_DATE constant).
    Residual maturity for all loans: 2028-12-31 − 2027-12-31 = 365 days = 1.0 year.

    Returns the AggregatedResultBundle from PipelineOrchestrator.run_with_data().
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
    facilities = pl.LazyFrame(
        schema={
            "facility_reference": pl.String,
            "counterparty_reference": pl.String,
        }
    )

    bundle = RawDataBundle(
        facilities=facilities,
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        model_permissions=pl.scan_parquet(_FIXTURES_DIR / "model_permission.parquet"),
    )
    config = CalculationConfig.basel_3_1(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _find_irb_row(results: object, loan_ref: str) -> dict:
    """
    Return the single IRB result row for *loan_ref*.

    Asserts exactly one row matches — test-fails with a descriptive message if
    the exposure is missing (fixture or pipeline loading issue).
    """
    df = results.irb_results.collect()
    rows = df.filter(pl.col("exposure_reference") == loan_ref).to_dicts()
    assert len(rows) == 1, (
        f"Expected exactly 1 IRB result row for {loan_ref!r}, got {len(rows)}. "
        f"All exposure_references: {df['exposure_reference'].to_list()}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# P1.151 acceptance test class
# ---------------------------------------------------------------------------


class TestP1151Art161PurchasedReceivablesLGD:
    """
    P1.151: Basel 3.1 F-IRB Art. 161(1)(e)/(f)/(g) purchased receivables LGD routing.

    Three loans share the same counterparty (corporate, PD=1%) but differ only in
    purchased_receivables_subtype.  The engine must dispatch each to the correct
    supervisory LGD sub-key, not fall through to the generic seniority-based table.

    Key structural assertion: LOAN_PR_DILUTION_001 has seniority="senior" AND
    purchased_receivables_subtype="dilution_risk".  Pre-fix both dilution and senior
    rows get LGD=0.40 (same seniority fallback).  Post-fix they diverge:
        LOAN_PR_SENIOR_001   → LGD = 0.40  (Art. 161(1)(e))
        LOAN_PR_DILUTION_001 → LGD = 1.00  (Art. 161(1)(g)) ← diverges from seniority fallback
    """

    @pytest.fixture(scope="class")
    def pipeline_results(self) -> object:
        """
        Run the B31 F-IRB pipeline once and return AggregatedResultBundle.

        Arrange: three loans (senior/subordinated/dilution) on one corporate counterparty.
        Act:     PipelineOrchestrator.run_with_data with CalculationConfig.basel_3_1().
        Return:  AggregatedResultBundle for all assertion fixtures to query.
        """
        return _run_pipeline_p1151()

    @pytest.fixture(scope="class")
    def senior_row(self, pipeline_results: object) -> dict:
        """Result dict for LOAN_PR_SENIOR_001 (Art. 161(1)(e), EAD=1,000,000)."""
        return _find_irb_row(pipeline_results, LOAN_REF_SENIOR)

    @pytest.fixture(scope="class")
    def sub_row(self, pipeline_results: object) -> dict:
        """Result dict for LOAN_PR_SUB_001 (Art. 161(1)(f), EAD=500,000)."""
        return _find_irb_row(pipeline_results, LOAN_REF_SUB)

    @pytest.fixture(scope="class")
    def dilution_row(self, pipeline_results: object) -> dict:
        """Result dict for LOAN_PR_DILUTION_001 (Art. 161(1)(g), EAD=200,000)."""
        return _find_irb_row(pipeline_results, LOAN_REF_DILUTION)

    # =========================================================================
    # Test 1 — LOAN_PR_SENIOR_001: Art. 161(1)(e), LGD=40%
    # =========================================================================

    def test_b31_purchased_receivables_senior_lgd_40pct(
        self,
        senior_row: dict,
        dilution_row: dict,
    ) -> None:
        """
        P1.151 Art. 161(1)(e): senior purchased receivables LGD == 40%.

        Additionally verifies that the LGD routing key is purchased_receivables_subtype,
        not seniority: LOAN_PR_DILUTION_001 has the SAME seniority="senior" as
        LOAN_PR_SENIOR_001 but purchased_receivables_subtype="dilution_risk" and must
        receive LGD=1.00, not LGD=0.40.  Pre-fix both rows return LGD=0.40 (same
        seniority fallback), making this assertion fail.

        Arrange: LOAN_PR_SENIOR_001 — seniority="senior", subtype="senior", EAD=1,000,000.
                 LOAN_PR_DILUTION_001 — seniority="senior", subtype="dilution_risk", EAD=200,000.
        Act:     Basel 3.1 F-IRB pipeline.
        Assert:
            (1) LOAN_PR_SENIOR_001 lgd == 0.40  (Art. 161(1)(e))
            (2) LOAN_PR_DILUTION_001 lgd != 0.40  (Art. 161(1)(g) must diverge from seniority)
            (3) LOAN_PR_SENIOR_001 rwa ≈ 651,258.88 (±£0.01)

        Pre-fix failure mode (assertion 2):
            Both senior and dilution rows return lgd=0.40 via seniority="senior" fallback.
            dilution_lgd (0.40) == 0.40 → the != assertion fails.
            This confirms the engine is not reading purchased_receivables_subtype.

        References:
            PRA PS1/26 Art. 161(1)(e): senior purchased corporate receivables LGD = 40%.
            PRA PS1/26 Art. 161(1)(g): dilution risk LGD = 100% (must differ from senior).
        """
        # Arrange
        senior_lgd = senior_row["lgd"]
        dilution_lgd = dilution_row["lgd"]
        senior_rwa = senior_row["rwa"]

        # Assert (1): senior purchased receivables gets LGD = 40%
        assert senior_lgd == pytest.approx(LGD_SENIOR, abs=_ABS_TOL_LGD), (
            f"P1.151 Art. 161(1)(e): LOAN_PR_SENIOR_001 lgd should be {LGD_SENIOR:.2f} "
            f"(senior purchased receivables), got {senior_lgd}."
        )

        # Assert (2): dilution row (seniority=senior) MUST diverge from senior LGD
        # This is the load-bearing assertion — pre-fix both rows return lgd=0.40
        # because the engine uses seniority not purchased_receivables_subtype.
        assert dilution_lgd != pytest.approx(LGD_SENIOR, abs=_ABS_TOL_LGD), (
            f"P1.151: LOAN_PR_DILUTION_001 has seniority='senior' but "
            f"purchased_receivables_subtype='dilution_risk'. Its lgd ({dilution_lgd}) "
            f"must NOT equal the senior purchased receivables LGD ({LGD_SENIOR:.2f}). "
            f"The engine is using seniority as the LGD key instead of "
            f"purchased_receivables_subtype. "
            f"Post-fix: dilution_lgd should be {LGD_DILUTION:.2f} (Art. 161(1)(g))."
        )

        # Assert (3): senior RWA matches hand-calculation
        assert senior_rwa == pytest.approx(_EXPECTED_RWA_SENIOR, abs=_ABS_TOL_RWA), (
            f"P1.151 Art. 161(1)(e): LOAN_PR_SENIOR_001 rwa should be "
            f"{_EXPECTED_RWA_SENIOR:,.2f} "
            f"(LGD=0.40, K={_EXPECTED_K_SENIOR:.8f}, RW={_EXPECTED_RW_SENIOR:.8f}, "
            f"EAD={DRAWN_SENIOR:,.0f}), got {senior_rwa:,.2f}."
        )

    # =========================================================================
    # Test 2 — LOAN_PR_SUB_001: Art. 161(1)(f), LGD=100%
    # =========================================================================

    def test_b31_purchased_receivables_subordinated_lgd_100pct(
        self,
        sub_row: dict,
    ) -> None:
        """
        P1.151 Art. 161(1)(f): subordinated purchased receivables LGD == 100%.

        Without purchased_receivables_subtype routing the engine falls through to
        the standard F-IRB subordinated LGD = 75% (Art. 161(1)(b) CRR / B31 generic).

        Arrange: LOAN_PR_SUB_001 — seniority="subordinated", subtype="subordinated",
                 EAD=500,000, PD=1%, non-SME corporate, M≈1.0y.
        Act:     Basel 3.1 F-IRB pipeline.
        Assert:  lgd == 1.00 (Art. 161(1)(f)).
                 rwa ≈ 814,073.61 (±£0.01).
                 expected_loss ≈ 5,000.00 (PD × LGD × EAD = 0.01 × 1.00 × 500,000).

        Pre-fix failure mode:
            Engine returns lgd=0.75 (standard subordinated fallback).
            assert 0.75 == pytest.approx(1.00, abs=1e-6) → AssertionError.

        References:
            PRA PS1/26 Art. 161(1)(f): subordinated purchased receivables LGD = 100%.
        """
        # Arrange
        actual_lgd = sub_row["lgd"]
        actual_rwa = sub_row["rwa"]
        actual_el = sub_row["expected_loss"]

        # Assert — LGD (primary, will fail pre-fix)
        assert actual_lgd == pytest.approx(LGD_SUB, abs=_ABS_TOL_LGD), (
            f"P1.151 Art. 161(1)(f): LOAN_PR_SUB_001 lgd should be {LGD_SUB:.2f} "
            f"(subordinated purchased receivables), got {actual_lgd}. "
            f"Pre-fix: engine returns {_WRONG_LGD_SUB:.2f} (standard subordinated — "
            f"not the purchased receivables sub-type rule). "
            f"Fix: route purchased_receivables_subtype='subordinated' to LGD=1.00."
        )

        # Assert — RWA
        assert actual_rwa == pytest.approx(_EXPECTED_RWA_SUB, abs=_ABS_TOL_RWA), (
            f"P1.151 Art. 161(1)(f): LOAN_PR_SUB_001 rwa should be "
            f"{_EXPECTED_RWA_SUB:,.2f} "
            f"(LGD=1.00, K={_EXPECTED_K_SUB:.8f}, RW={_EXPECTED_RW_SUB:.8f}, "
            f"EAD={DRAWN_SUB:,.0f}), got {actual_rwa:,.2f}."
        )

        # Assert — EL = PD × LGD × EAD = 0.01 × 1.00 × 500,000 = 5,000
        assert actual_el == pytest.approx(_EXPECTED_EL_SUB, abs=_ABS_TOL_EL), (
            f"P1.151 Art. 161(1)(f): LOAN_PR_SUB_001 expected_loss should be "
            f"{_EXPECTED_EL_SUB:,.2f} "
            f"(PD={PD} × LGD=1.00 × EAD={DRAWN_SUB:,.0f}), got {actual_el:,.2f}."
        )

    # =========================================================================
    # Test 3 — LOAN_PR_DILUTION_001: Art. 161(1)(g), LGD=100%
    # =========================================================================

    def test_b31_dilution_risk_lgd_100pct(
        self,
        dilution_row: dict,
    ) -> None:
        """
        P1.151 Art. 161(1)(g): dilution risk of purchased receivables LGD == 100%.

        Basel 3.1 raises the dilution risk LGD from the CRR value of 75% to 100%.
        The exposure has seniority="senior" — confirming the routing must use
        purchased_receivables_subtype="dilution_risk", not the seniority column.

        Arrange: LOAN_PR_DILUTION_001 — seniority="senior", subtype="dilution_risk",
                 EAD=200,000, PD=1%, non-SME corporate, M≈1.0y.
        Act:     Basel 3.1 F-IRB pipeline.
        Assert:  lgd == 1.00 (Art. 161(1)(g)).
                 rwa ≈ 325,629.45 (±£0.01).
                 expected_loss ≈ 2,000.00 (PD × LGD × EAD = 0.01 × 1.00 × 200,000).

        Pre-fix failure mode:
            Engine returns lgd=0.40 (seniority="senior" fallback, Art. 161(1)(aa)).
            assert 0.40 == pytest.approx(1.00, abs=1e-6) → AssertionError.

        References:
            PRA PS1/26 Art. 161(1)(g): dilution risk purchased receivables LGD = 100%.
            PRA PS1/26 Art. 161(1)(aa): generic senior non-FSE LGD = 40% (B31).
            CRR Art. 161(1)(d): dilution risk LGD was 75% under CRR — B31 raises to 100%.
        """
        # Arrange
        actual_lgd = dilution_row["lgd"]
        actual_rwa = dilution_row["rwa"]
        actual_el = dilution_row["expected_loss"]

        # Assert — LGD (primary, will fail pre-fix)
        assert actual_lgd == pytest.approx(LGD_DILUTION, abs=_ABS_TOL_LGD), (
            f"P1.151 Art. 161(1)(g): LOAN_PR_DILUTION_001 lgd should be {LGD_DILUTION:.2f} "
            f"(dilution risk purchased receivables), got {actual_lgd}. "
            f"Pre-fix: engine returns {_WRONG_LGD_DILUTION:.2f} (seniority='senior' "
            f"fallback — Art. 161(1)(aa) non-FSE senior). "
            f"LOAN_PR_DILUTION_001 has seniority='senior' but subtype='dilution_risk': "
            f"the engine must route via purchased_receivables_subtype not seniority. "
            f"Fix: route purchased_receivables_subtype='dilution_risk' to LGD=1.00 "
            f"(Art. 161(1)(g)). Note: CRR value was 75% — B31 raises to 100%."
        )

        # Assert — RWA
        assert actual_rwa == pytest.approx(_EXPECTED_RWA_DILUTION, abs=_ABS_TOL_RWA), (
            f"P1.151 Art. 161(1)(g): LOAN_PR_DILUTION_001 rwa should be "
            f"{_EXPECTED_RWA_DILUTION:,.2f} "
            f"(LGD=1.00, K={_EXPECTED_K_DILUTION:.8f}, RW={_EXPECTED_RW_DILUTION:.8f}, "
            f"EAD={DRAWN_DILUTION:,.0f}), got {actual_rwa:,.2f}."
        )

        # Assert — EL = PD × LGD × EAD = 0.01 × 1.00 × 200,000 = 2,000
        assert actual_el == pytest.approx(_EXPECTED_EL_DILUTION, abs=_ABS_TOL_EL), (
            f"P1.151 Art. 161(1)(g): LOAN_PR_DILUTION_001 expected_loss should be "
            f"{_EXPECTED_EL_DILUTION:,.2f} "
            f"(PD={PD} × LGD=1.00 × EAD={DRAWN_DILUTION:,.0f}), got {actual_el:,.2f}."
        )

    # =========================================================================
    # Structural assertion: all three rows route to F-IRB, not SA
    # =========================================================================

    def test_b31_purchased_receivables_all_route_to_firb(
        self,
        pipeline_results: object,
    ) -> None:
        """
        All three P1.151 loans route to F-IRB (foundation_irb), not SA.

        Regression guard: confirms the model_permission fixture is active and the
        pipeline resolves all three loans to F-IRB via model_id=UK_CORP_FIRB_PR_01.

        Arrange: model_permission row — corporate, foundation_irb, no restrictions.
        Act:     Basel 3.1 F-IRB pipeline.
        Assert:  approach_applied == 'foundation_irb' for all three loans.
        """
        # Arrange
        df = pipeline_results.irb_results.collect()
        refs = [LOAN_REF_SENIOR, LOAN_REF_SUB, LOAN_REF_DILUTION]

        for loan_ref in refs:
            rows = df.filter(pl.col("exposure_reference") == loan_ref).to_dicts()
            assert len(rows) == 1, (
                f"P1.151: expected 1 IRB row for {loan_ref!r}, got {len(rows)}."
            )
            approach = rows[0].get("approach_applied") or rows[0].get("approach")
            assert approach == "foundation_irb", (
                f"P1.151: {loan_ref!r} should route to foundation_irb, got {approach!r}. "
                f"Check model_permission fixture (UK_CORP_FIRB_PR_01, corporate, foundation_irb)."
            )

    # =========================================================================
    # Regression guard: counterparty constant sanity
    # =========================================================================

    def test_b31_purchased_receivables_fixture_pd_sanity(self) -> None:
        """
        Fixture regression guard: PD=1% is above the B31 corporate PD floor (0.05%).

        Ensures the PD floor does not bind, so LGD is the only variable differentiating
        the three exposures. If PD were below 0.05% it would be floored and the EL
        assertions would fail for an unrelated reason.

        Assert: PD (0.01) > B31 corporate floor (0.0005).
        """
        _b31_corporate_pd_floor = 0.0005
        assert PD > _b31_corporate_pd_floor, (
            f"Fixture sanity: PD ({PD}) must exceed B31 corporate floor "
            f"({_b31_corporate_pd_floor}) so the PD floor does not bind "
            f"and obscure the LGD routing assertions."
        )
