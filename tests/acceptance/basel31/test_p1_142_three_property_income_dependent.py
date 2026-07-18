"""
P1.142 — Basel 3.1 Art. 124E three-property limit → Art. 124G income-dependent RW routing.

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor → SACalculator → Aggregator

Scenario design:
    Basel 3.1 Art. 124E(1)(b) limits the preferential owner-occupied residential
    treatment (Art. 124F loan-split + Art. 124L) to borrowers whose total residential
    RE exposure is secured on no more than THREE residential properties (including
    the financed one).  When the limit is BREACHED (count > 3), the exposure is
    re-routed to the income-producing residential whole-loan track (Art. 124G,
    Table 6B).

    Two obligors are tested:

    BREACH row (CP_P1142_BREACH, qualifying_property_count=4):
        qualifying_property_count > 3  →  Art. 124E limit breached.
        Engine must derive materially_dependent = False (income-producing route).
        Art. 124G Table 6B, LTV band 70%-80% → RW = 0.50.
        EAD = 200,000  →  RWA = 200,000 × 0.50 = 100,000.00.

    CONTROL row (CP_P1142_CTRL, qualifying_property_count=3):
        qualifying_property_count = 3 ≤ 3  →  limit met.
        Engine keeps Art. 124F owner-occupied loan-split treatment.
        secured_share = min(1, 0.55 / 0.75) = 0.73333...
        blended RW = 0.20 × 0.73333... + 0.75 × 0.26667... = 0.34667...
        EAD = 200,000  →  RWA = 200,000 × 0.34667... = 69,333.33.

Pre-fix (current) behaviour without qualifying_property_count derivation:
    The engine does not read qualifying_property_count and cannot derive the
    income-producing flag from it.  Both rows fall through to the default
    owner-occupied Art. 124F loan-split track, producing RWA ≈ 69,333.33 for
    BOTH rows.  The BREACH assertion (RWA == 100,000) therefore FAILS.

Post-fix expected behaviour:
    Engine reads qualifying_property_count from the counterparty row.
    BREACH row: count=4 > 3  →  is_income_producing derived True  →  Art. 124G
    whole-loan 50% RW  →  RWA = 100,000.
    CONTROL row: count=3 ≤ 3  →  loan-split retained  →  RWA ≈ 69,333.33.

Regulatory references:
    - PRA PS1/26 Art. 124E(1)(b): three-property limit for owner-occupied RE.
    - PRA PS1/26 Art. 124E(2): exclusion from owner-occupied path when limit breached.
    - PRA PS1/26 Art. 124F: owner-occupied residential loan-split (20% / 75%).
    - PRA PS1/26 Art. 124G Table 6B: income-producing residential RW = 0.50 (70-80% LTV).
    - PRA PS1/26 Art. 124L(a): residual/unsecured portion RW = 75%.
    - tests/fixtures/p1_142/p1_142.py: fixture constants and builder functions.
    - IMPLEMENTATION_PLAN.md: P1.142 entry.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_142.p1_142 import (
    EXPECTED_RW_BREACH,
    EXPECTED_RW_CTRL,
    EXPECTED_RWA_BREACH,
    EXPECTED_RWA_CTRL,
    LOAN_BREACH_REF,
    LOAN_CTRL_REF,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_142"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle from P1.142 parquets.

    The counterparty parquet carries the new qualifying_property_count column
    which is not yet declared in COUNTERPARTY_SCHEMA.  The loader passes
    extra columns through silently (ensure_columns only ADDS missing optional
    columns — it does not drop unknown ones), so the parquet loads cleanly.
    The engine-implementer must add the schema field and read the column.

    Collateral is_income_producing is null on both rows — the engine must
    derive the income-producing flag from counterparty qualifying_property_count.
    """
    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={
                "facility_reference": pl.String,
                "product_type": pl.String,
                "counterparty_reference": pl.String,
            }
        ),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.scan_parquet(_FIXTURES_DIR / "facility_mapping.parquet"),
        lending_mappings=pl.scan_parquet(_FIXTURES_DIR / "lending_mapping.parquet"),
        org_mappings=None,
        collateral=pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet"),
    )


def _b31_config() -> CalculationConfig:
    """Basel 3.1 SA-only config with reporting_date=2027-01-02 (post-go-live)."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 1, 2),
        permission_mode=PermissionMode.STANDARDISED,
    )


# ---------------------------------------------------------------------------
# Module-scoped SA results fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_142_sa_results() -> pl.DataFrame:
    """
    Run P1.142 fixtures through the Basel 3.1 SA pipeline and return SA results.

    Arrange: BREACH obligor (qualifying_property_count=4) and CTRL obligor
             (qualifying_property_count=3), both natural persons, residential
             mortgage EAD=200,000, LTV=0.75, is_income_producing=null.
             B31 SA-only config, 2027-01-02.
    Act:     PipelineOrchestrator().run_with_data(bundle, config).sa_results.
    Return:  Collected SA results DataFrame for all assertions.
    """
    bundle = _build_bundle()
    config = _b31_config()
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None, (
        "SA results should not be None — check PermissionMode.STANDARDISED config"
    )
    return results.sa_results.collect()


def _get_breach_rows(df: pl.DataFrame) -> pl.DataFrame:
    """
    Return all rows derived from LN_P1142_BREACH (including loan-split sub-rows).

    Post-fix: single income-producing row (no loan-splitting when Art. 124G fires).
    Pre-fix:  one or two loan-split rows (residential_mortgage class).
    """
    return df.filter(
        (pl.col("exposure_reference") == LOAN_BREACH_REF)
        | (pl.col("split_parent_id") == LOAN_BREACH_REF)
    )


def _get_ctrl_rows(df: pl.DataFrame) -> pl.DataFrame:
    """
    Return all rows derived from LN_P1142_CTRL (including loan-split sub-rows).

    Loan-split produces two sub-rows (secured + unsecured portions).
    """
    return df.filter(
        (pl.col("exposure_reference") == LOAN_CTRL_REF)
        | (pl.col("split_parent_id") == LOAN_CTRL_REF)
    )


# ---------------------------------------------------------------------------
# P1.142 acceptance test class
# ---------------------------------------------------------------------------


class TestB31P1142ThreePropertyIncomeDependentRouting:
    """
    P1.142: Basel 3.1 Art. 124E three-property limit → income-producing RE routing.

    When qualifying_property_count > 3, the borrower's collateral exceeds the
    Art. 124E(1)(b) three-property limit and the exposure must be reclassified
    as income-producing residential RE (Art. 124G, Table 6B).

    The discriminating row (BREACH, count=4) must produce:
        risk_weight  = 0.50  (Art. 124G Table 6B, LTV 70%-80%)
        rwa_final    = 100,000.00

    The control row (CTRL, count=3) stays on the Art. 124F loan-split track:
        blended_rw  ≈ 0.34667  (pytest.approx — recurring decimal)
        rwa_final   ≈ 69,333.33

    Pre-fix (current): both rows fall to the default loan-split track and produce
    rwa_final ≈ 69,333.33. The BREACH assertions FAIL with AssertionError.
    """

    # -------------------------------------------------------------------------
    # DISCRIMINATING ASSERTIONS — FAIL pre-fix (BREACH obligor)
    # -------------------------------------------------------------------------

    def test_p1_142_breach_total_rwa_is_100k(self, p1_142_sa_results: pl.DataFrame) -> None:
        """
        P1.142 DISCRIMINATING: BREACH obligor total rwa_final = 100,000.00.

        Art. 124G Table 6B (PRA PS1/26): income-producing residential RE, LTV
        70%-80% → RW = 0.50.  EAD = 200,000 → RWA = 100,000.

        Pre-fix (current): qualifying_property_count not read by engine → BREACH
        obligor stays on Art. 124F loan-split track → total rwa ≈ 69,333.33.
        This test FAILS pre-fix with AssertionError.

        Post-fix expected: is_income_producing derived True → Art. 124G 50% path
        → rwa_final = 100,000.

        Arrange: B31 SA-only config, LN_P1142_BREACH, EAD=200,000, LTV=0.75,
                 qualifying_property_count=4 on counterparty, is_income_producing=null.
        Act:     Sum rwa_final across all rows derived from LN_P1142_BREACH.
        Assert:  total rwa_final == 100,000.00 (abs=1e-2).
        """
        # Arrange
        breach_rows = _get_breach_rows(p1_142_sa_results)
        total_rwa = breach_rows["rwa_final"].sum()

        # Assert — FAILS pre-fix (engine returns ≈ 69,333.33)
        assert total_rwa == pytest.approx(EXPECTED_RWA_BREACH, abs=1e-2), (
            f"P1.142: BREACH obligor total rwa_final should be {EXPECTED_RWA_BREACH:,.2f} "
            f"(EAD 200,000 × Art. 124G Table 6B 50% RW, LTV 70%-80%). "
            f"Got {total_rwa:,.2f}. "
            f"Pre-fix value ≈ 69,333.33: qualifying_property_count not yet read by "
            f"engine — BREACH obligor (count=4) stays on Art. 124F loan-split track "
            f"instead of routing to Art. 124G income-producing 50% RW. "
            f"Engine-implementer must add qualifying_property_count to "
            f"COUNTERPARTY_SCHEMA and derive is_income_producing from count > 3."
        )

    def test_p1_142_breach_risk_weight_is_50_pct(self, p1_142_sa_results: pl.DataFrame) -> None:
        """
        P1.142 DISCRIMINATING: BREACH obligor risk_weight = 0.50.

        Art. 124G Table 6B: income-producing residential RE, LTV 70%-80% → RW = 50%.
        Post-fix: single whole-loan row with risk_weight = 0.50.
        Pre-fix:  loan-split rows with blended RW ≈ 0.34667 — no row has 0.50.

        Arrange: B31 SA-only config, LN_P1142_BREACH, LTV=0.75, count=4.
        Act:     Retrieve exposure_reference == LN_P1142_BREACH (post-fix single row).
        Assert:  risk_weight ≈ 0.50 (abs=1e-6).
        """
        # Arrange — post-fix: single unsplit row; pre-fix: split sub-rows exist
        rows = p1_142_sa_results.filter(pl.col("exposure_reference") == LOAN_BREACH_REF).to_dicts()

        assert len(rows) == 1, (
            f"P1.142: expected exactly 1 unsplit row for {LOAN_BREACH_REF} "
            f"(Art. 124G income-producing path does not split). "
            f"Got {len(rows)} rows. "
            f"Pre-fix: loan is RE-split into sub-rows → no unsplit row remains."
        )
        row = rows[0]

        # Assert
        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_BREACH, abs=1e-6), (
            f"P1.142: BREACH obligor risk_weight should be {EXPECTED_RW_BREACH:.4f} "
            f"(Art. 124G Table 6B, income-producing residential, LTV 70%-80% = 50%). "
            f"Got {row['risk_weight']:.6f}. "
            f"Pre-fix value ≈ 0.34667: loan-split track applied (count=4 not read)."
        )

    def test_p1_142_breach_ead_is_200k(self, p1_142_sa_results: pl.DataFrame) -> None:
        """
        P1.142: BREACH obligor EAD = 200,000 (fully drawn mortgage, interest=0).

        Arrange: LN_P1142_BREACH, drawn_amount=200,000, interest=0.
        Act:     ead_final from the unsplit BREACH row (post-fix).
        Assert:  ead_final ≈ 200,000 (abs=1e-2).
        """
        rows = p1_142_sa_results.filter(pl.col("exposure_reference") == LOAN_BREACH_REF).to_dicts()

        assert len(rows) == 1, (
            f"P1.142: expected exactly 1 unsplit row for {LOAN_BREACH_REF}. Got {len(rows)} rows."
        )
        row = rows[0]

        assert row["ead_final"] == pytest.approx(200_000.0, abs=1e-2), (
            f"P1.142: BREACH ead_final should be 200,000. Got {row['ead_final']:,.2f}."
        )

    # -------------------------------------------------------------------------
    # CONTROL ASSERTIONS — pass both pre-fix and post-fix (regression guard)
    # -------------------------------------------------------------------------

    def test_p1_142_ctrl_total_rwa_is_69333(self, p1_142_sa_results: pl.DataFrame) -> None:
        """
        P1.142 CONTROL (regression guard): CTRL obligor total rwa_final ≈ 69,333.33.

        Art. 124F loan-split: secured_share = min(1, 0.55/0.75) = 0.73333...
        blended RW = 0.20 × 0.73333... + 0.75 × 0.26667... = 0.34667...
        EAD = 200,000  →  RWA = 69,333.33 (recurring decimal).

        This assertion PASSES on the current unmodified engine — the CTRL obligor
        (count=3) already routes to the Art. 124F loan-split track by default.
        It is a regression guard: the fix must NOT change the behaviour for
        count ≤ 3 obligors. Proving it passes confirms the threshold is > 3,
        not >= 3 (i.e. 3 is within the limit, 4 is not).

        Arrange: B31 SA-only config, LN_P1142_CTRL, EAD=200,000, LTV=0.75,
                 qualifying_property_count=3 on counterparty, is_income_producing=null.
        Act:     Sum rwa_final across all rows derived from LN_P1142_CTRL.
        Assert:  total rwa_final ≈ 69,333.33 (abs=1e-2).
        """
        # Arrange
        ctrl_rows = _get_ctrl_rows(p1_142_sa_results)
        total_rwa = ctrl_rows["rwa_final"].sum()

        # Assert — passes pre-fix (loan-split default) and post-fix (count=3 ≤ 3)
        assert total_rwa == pytest.approx(EXPECTED_RWA_CTRL, abs=1e-2), (
            f"P1.142: CTRL obligor total rwa_final should be ≈{EXPECTED_RWA_CTRL:,.2f} "
            f"(EAD 200,000 × blended RW {EXPECTED_RW_CTRL:.5f} from Art. 124F loan-split). "
            f"Got {total_rwa:,.2f}. "
            f"count=3 is within the Art. 124E(1)(b) limit (≤ 3) — engine must "
            f"keep the owner-occupied loan-split track for this obligor."
        )

    def test_p1_142_ctrl_blended_risk_weight(self, p1_142_sa_results: pl.DataFrame) -> None:
        """
        P1.142 CONTROL: CTRL obligor blended risk_weight ≈ 0.34667 (Art. 124F).

        The loan-split produces two sub-rows (secured + unsecured portions).
        The effective blended RW across both sub-rows = rwa_final_total / ead_total.

        Arrange: B31 SA-only config, LN_P1142_CTRL, count=3, LTV=0.75.
        Act:     Sum rwa_final and ead_final across CTRL sub-rows; compute ratio.
        Assert:  blended RW ≈ 0.34667 (abs=1e-4 — recurring decimal).
        """
        # Arrange
        ctrl_rows = _get_ctrl_rows(p1_142_sa_results)
        total_rwa = float(ctrl_rows["rwa_final"].sum())
        total_ead = float(ctrl_rows["ead_final"].sum())

        assert total_ead > 0, (
            f"P1.142: CTRL obligor has zero EAD — fixture may not be loaded correctly. "
            f"Rows: {ctrl_rows.to_dicts()}"
        )
        blended_rw = total_rwa / total_ead

        # Assert — recurring decimal 0.34666... → use pytest.approx
        assert blended_rw == pytest.approx(EXPECTED_RW_CTRL, abs=1e-4), (
            f"P1.142: CTRL obligor blended RW should be ≈{EXPECTED_RW_CTRL:.5f} "
            f"(Art. 124F: 0.20×0.73333 + 0.75×0.26667). "
            f"Got {blended_rw:.6f}. "
            f"count=3 ≤ 3 → loan-split track must be retained."
        )

    # -------------------------------------------------------------------------
    # BOUNDARY INVARIANT — threshold is > 3, not >= 3
    # -------------------------------------------------------------------------

    def test_p1_142_threshold_is_strictly_greater_than_3(
        self, p1_142_sa_results: pl.DataFrame
    ) -> None:
        """
        P1.142 boundary invariant: count=3 stays on loan-split; count=4 routes to
        income-producing.  Proves the threshold gate is count > 3 (strictly).

        This assertion is load-bearing: if the engine mistakenly uses count >= 3
        as the breach condition, the CTRL obligor (count=3) would also produce
        rwa = 100,000 and this test would fail.

        Arrange: both BREACH (count=4) and CTRL (count=3) results available.
        Act:     compare total rwa_final for each obligor.
        Assert:  CTRL rwa_final < BREACH rwa_final (i.e. 69,333.33 < 100,000).
        """
        breach_rwa = _get_breach_rows(p1_142_sa_results)["rwa_final"].sum()
        ctrl_rwa = _get_ctrl_rows(p1_142_sa_results)["rwa_final"].sum()

        assert ctrl_rwa < breach_rwa, (
            f"P1.142 boundary: CTRL rwa ({ctrl_rwa:,.2f}) must be less than BREACH "
            f"rwa ({breach_rwa:,.2f}). The Art. 124E(1)(b) threshold is count > 3 "
            f"(strictly). count=3 must NOT trigger the income-producing re-route. "
            f"If ctrl_rwa == breach_rwa, the engine may be using count >= 3."
        )
