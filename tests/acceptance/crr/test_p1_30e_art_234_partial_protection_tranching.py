"""
P1.30(e): CRR Art. 234 mezzanine partial-protection tranching.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Confirm that a guarantee with attachment_amount > 0 produces THREE post-CRM rows:
    1. first-loss retained tranche  [0, a)      EAD=200,000  no guarantor  RW=100%
    2. protected mezzanine tranche  [a, d)      EAD=400,000  CP-INST-1     RW=50%
    3. senior retained tranche      [d, EAD]    EAD=400,000  no guarantor  RW=100%
- Confirm EAD conservation: sum of three tranche EADs equals original EAD (1,000,000).
- Confirm exactly ONE row carries guarantor_reference=CP-INST-1.
- Confirm the two retained rows each have guarantor_reference=null.
- Confirm the retained row EADs are 200,000 (first-loss) and 400,000 (senior), NOT
  the current buggy single 600,000 remainder.

Defect under test (pre-fix):
    Today's engine attaches every guarantee at FIRST LOSS: the guaranteed row covers
    [0, 400k) and the remainder covers [400k, 1,000k)=600,000 as a single row.
    CRR Art. 234 requires attachment at a=200,000: the mezzanine row covers [200k,600k)=400,000;
    the borrower retains BOTH [0,200k)=200,000 (first-loss) and [600k,1,000k)=400,000 (senior).

    Total RWA coincidentally equals 800,000 in both interpretations because the obligor
    risk weight (100%) is uniform across both retained tranches.  A test that only asserts
    ΣRWA=800,000 would FALSELY PASS.  This test asserts the three-row tranche structure,
    which today's engine does NOT produce (it produces two rows, not three).

Hand calculation (CRR Art. 234 + Art. 235 RWSM):
    EAD = 1,000,000   a = 200,000   d = 600,000
    first-loss [0, a)   = 200,000 @ obligor 100%   → RWA = 200,000
    protected  [a, d)   = 400,000 @ guarantor 50%  → RWA = 200,000  (beneficial: 50% < 100%)
    senior     [d, EAD] = 400,000 @ obligor 100%   → RWA = 400,000
    ΣEAD = 1,000,000   ΣRWA = 800,000   blended RW = 0.80

References:
    - CRR Art. 234: tranching of credit protection with attachment/detachment
    - CRR Art. 233A: proportional coverage (contrast case — not exercised here)
    - CRR Art. 235: SA risk-weight substitution method (RWSM)
    - CRR Art. 213: beneficial substitution condition (guarantor RW < obligor RW)
    - CRR Art. 120 Table 3: institution CQS 2 = 50% SA RW
    - CRR Art. 122 Table 5: corporate unrated = 100% SA RW
    - CRR Art. 237(2)(a): original_maturity_years >= 1y eligibility (5.0y satisfied)
    - tests/fixtures/p1_30e/p1_30e.py: fixture builder and scenario constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_30e"

# ---------------------------------------------------------------------------
# Constants from the fixture builder
# ---------------------------------------------------------------------------

from tests.fixtures.p1_30e.p1_30e import (  # noqa: E402
    ATTACHMENT_AMOUNT,
    BORROWER_RW,
    DETACHMENT_AMOUNT,
    EXPECTED_BLENDED_RW,
    EXPECTED_RWA_TOTAL,
    FIRST_LOSS_WIDTH,
    GUARANTEE_AMOUNT_COVERED,
    GUARANTOR_REF,
    GUARANTOR_RW,
    LOAN_EAD,
    LOAN_REF,
    PROTECTED_WIDTH,
    SENIOR_WIDTH,
)
from tests.fixtures.raw_bundle import make_raw_bundle  # noqa: E402

# ---------------------------------------------------------------------------
# Reporting date: 2026-06-01 — within CRR validity (to 31 Dec 2026);
# loan residual from value_date 2026-01-02 to maturity 2031-01-02 ≈ 5y.
# Guarantee original_maturity_years=5.0 => no Art. 239(3) mismatch.
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2026, 6, 1)

# ---------------------------------------------------------------------------
# Expected tranche dimensions
# ---------------------------------------------------------------------------

_EXPECTED_ROW_COUNT = 3  # three-way Art. 234 split
_EXPECTED_EAD_TOTAL = LOAN_EAD  # 1,000,000 — conservation
_EXPECTED_EAD_FIRST_LOSS = FIRST_LOSS_WIDTH  # 200,000
_EXPECTED_EAD_PROTECTED = PROTECTED_WIDTH  # 400,000
_EXPECTED_EAD_SENIOR = SENIOR_WIDTH  # 400,000

_EXPECTED_GUARANTEED_PORTION = GUARANTEE_AMOUNT_COVERED  # 400,000 on mezzanine row
_EXPECTED_UNGUARANTEED_FL = FIRST_LOSS_WIDTH  # 200,000 on first-loss row
_EXPECTED_UNGUARANTEED_SEN = SENIOR_WIDTH  # 400,000 on senior row

_EXPECTED_RWA_TOTAL = EXPECTED_RWA_TOTAL  # 800,000
_EXPECTED_BLENDED_RW = EXPECTED_BLENDED_RW  # 0.80

_EXPECTED_GUARANTOR_RW = GUARANTOR_RW  # 0.50 on mezzanine row
_EXPECTED_BORROWER_RW = BORROWER_RW  # 1.00 on retained rows


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------


def _make_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle for the P1.30(e) scenario.

    Loads all four parquet fixtures from tests/fixtures/p1_30e/.
    The guarantee parquet carries attachment_amount=200,000 and
    detachment_amount=600,000 alongside the standard guarantee columns.

    Returns:
        RawDataBundle ready for pipeline execution.
    """
    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={
                "facility_reference": pl.String,
                "counterparty_reference": pl.String,
            }
        ),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        guarantees=pl.scan_parquet(_FIXTURES_DIR / "guarantee.parquet"),
    )


def _run_pipeline() -> pl.DataFrame:
    """
    Run the full CRR SA pipeline for the P1.30(e) scenario.

    Returns the SA results DataFrame (all rows, including all guarantee sub-rows).
    """
    bundle = _make_bundle()
    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None, "SA results must not be None for SA-only config"
    return results.sa_results.collect()


# ---------------------------------------------------------------------------
# Acceptance tests — P1.30(e) CRR Art. 234 mezzanine tranching
# ---------------------------------------------------------------------------


class TestP130eArt234PartialProtectionTranching:
    """
    P1.30(e): CRR Art. 234 — guarantee with non-zero attachment_amount must produce
    a THREE-row tranche structure (first-loss retained, mezzanine protected, senior retained).

    Today's engine (pre-fix) produces TWO rows:
        EXP-234-1__G_CP-INST-1  EAD=400,000  guarantor=CP-INST-1
        EXP-234-1__REM          EAD=600,000  guarantor=null

    The correct three-row structure required by Art. 234:
        EXP-234-1__REM_FL      EAD=200,000  guarantor=null       RW=100%
        EXP-234-1__G_CP-INST-1 EAD=400,000  guarantor=CP-INST-1  RW= 50%
        EXP-234-1__REM_SEN     EAD=400,000  guarantor=null       RW=100%

    Note: ΣRWA=800,000 and blended RW=0.80 are IDENTICAL between the buggy and
    correct engine because the obligor RW (100%) is uniform across both retained
    tranches.  The discriminating assertion is the three-row structure with correct
    per-tranche EADs.
    """

    # -----------------------------------------------------------------------
    # Class-scoped pipeline result — single run for all tests in this class
    # -----------------------------------------------------------------------

    @pytest.fixture(scope="class")
    def sa_results_df(self) -> pl.DataFrame:
        """
        Full SA results DataFrame from the CRR SA pipeline for P1.30(e).

        Collected once per class; individual tests filter it as needed.
        """
        return _run_pipeline()

    @pytest.fixture(scope="class")
    def tranche_rows(self, sa_results_df: pl.DataFrame) -> pl.DataFrame:
        """
        All SA result rows belonging to EXP-234-1 (filtered by parent_exposure_reference).

        Under Art. 234 this must contain exactly three rows (the three tranches).
        """
        rows = sa_results_df.filter(pl.col("parent_exposure_reference") == LOAN_REF)
        return rows

    # -----------------------------------------------------------------------
    # Structure: three rows, not two
    # -----------------------------------------------------------------------

    def test_p1_30e_art_234_produces_three_tranche_rows(self, tranche_rows: pl.DataFrame) -> None:
        """
        CRR Art. 234: mezzanine guarantee must split EXP-234-1 into EXACTLY three rows.

        Arrange: EXP-234-1 (GBP 1M corporate) + G-234-1 (attachment=200k, detachment=600k).
        Act:     full CRR SA pipeline.
        Assert:  exactly 3 rows with parent_exposure_reference=EXP-234-1.

        TODAY THIS FAILS: the engine produces 2 rows (guaranteed + single remainder),
        not 3 (first-loss retained + mezzanine guaranteed + senior retained).
        """
        # Arrange
        expected_count = _EXPECTED_ROW_COUNT  # 3

        # Assert
        assert tranche_rows.height == expected_count, (
            f"P1.30e Art. 234: expected exactly {expected_count} tranche rows for {LOAN_REF}, "
            f"got {tranche_rows.height}. "
            f"Art. 234 requires a first-loss retained tranche [0,{ATTACHMENT_AMOUNT:,.0f}), "
            f"a mezzanine guaranteed tranche [{ATTACHMENT_AMOUNT:,.0f},{DETACHMENT_AMOUNT:,.0f}), "
            f"and a senior retained tranche [{DETACHMENT_AMOUNT:,.0f},{LOAN_EAD:,.0f}]. "
            f"Current engine produces only 2 rows (first-loss attach). "
            f"exposure_references: {tranche_rows['exposure_reference'].to_list()}"
        )

    # -----------------------------------------------------------------------
    # Guarantor row: exactly one row has guarantor_reference=CP-INST-1
    # -----------------------------------------------------------------------

    def test_p1_30e_art_234_exactly_one_guarantor_row(self, tranche_rows: pl.DataFrame) -> None:
        """
        CRR Art. 234: exactly ONE tranche row carries guarantor_reference=CP-INST-1.

        Arrange: G-234-1 attaches at 200k, detaches at 600k (mezzanine band only).
        Act:     full CRR SA pipeline.
        Assert:  count of rows where guarantor_reference=CP-INST-1 is exactly 1.

        THIS TEST FAILS TODAY: the engine produces 1 guaranteed row with EAD=400k
        (correct count) but two rows total — the row-count assertion above fails first
        so this is a belt-and-braces check for the mezzanine row specifically.
        """
        # Arrange
        guaranteed_rows = tranche_rows.filter(pl.col("guarantor_reference") == GUARANTOR_REF)

        # Assert
        assert guaranteed_rows.height == 1, (
            f"P1.30e Art. 234: expected exactly 1 row with guarantor_reference='{GUARANTOR_REF}', "
            f"got {guaranteed_rows.height}"
        )

    def test_p1_30e_art_234_mezzanine_guaranteed_portion_is_400k(
        self, tranche_rows: pl.DataFrame
    ) -> None:
        """
        CRR Art. 234: the mezzanine guaranteed row must carry guaranteed_portion=400,000.

        Arrange: protected width = d - a = 600k - 200k = 400k.
        Act:     full CRR SA pipeline.
        Assert:  the row with guarantor_reference=CP-INST-1 has guaranteed_portion=400,000.

        THIS TEST FAILS TODAY because there are <1 guaranteed row found when tranche_rows
        only has 2 rows (both parent=EXP-234-1); the row with guarantor=CP-INST-1 does
        exist (at EAD=400k) so the portion assertion would pass — the row_count assertion
        (above) is the primary discriminator.
        """
        # Arrange
        guaranteed_rows = tranche_rows.filter(pl.col("guarantor_reference") == GUARANTOR_REF)
        # If no guaranteed row exists at all, this will produce an empty filter;
        # but if exactly one row passes (from the buggy 2-row output), it exists.
        # The primary failure point is the row-count test above.
        # This assertion adds specificity on the protected portion amount.
        if guaranteed_rows.height == 0:
            pytest.fail(
                f"P1.30e Art. 234: no guaranteed row with guarantor_reference='{GUARANTOR_REF}' "
                f"found. Cannot assert guaranteed_portion."
            )

        # Assert
        mez_guaranteed_portion = guaranteed_rows["guaranteed_portion"][0]
        assert mez_guaranteed_portion == pytest.approx(_EXPECTED_GUARANTEED_PORTION, rel=1e-6), (
            f"P1.30e Art. 234: mezzanine row guaranteed_portion expected "
            f"{_EXPECTED_GUARANTEED_PORTION:,.0f} (= d - a = {DETACHMENT_AMOUNT:,.0f} - "
            f"{ATTACHMENT_AMOUNT:,.0f}), got {mez_guaranteed_portion:,.2f}"
        )

    # -----------------------------------------------------------------------
    # Retained rows: two rows with guarantor_reference=null
    # -----------------------------------------------------------------------

    def test_p1_30e_art_234_two_retained_rows_with_null_guarantor(
        self, tranche_rows: pl.DataFrame
    ) -> None:
        """
        CRR Art. 234: exactly TWO retained rows must have guarantor_reference=null.

        Arrange: first-loss [0,200k) and senior [600k,1000k) are both borrower-retained.
        Act:     full CRR SA pipeline.
        Assert:  exactly 2 rows with guarantor_reference=null.

        TODAY THIS FAILS: the buggy engine produces only ONE remainder row (EAD=600k),
        so only 1 null-guarantor row exists instead of 2.
        """
        # Arrange
        retained_rows = tranche_rows.filter(pl.col("guarantor_reference").is_null())

        # Assert
        assert retained_rows.height == 2, (
            f"P1.30e Art. 234: expected exactly 2 retained rows (first-loss + senior) "
            f"with guarantor_reference=null, got {retained_rows.height}. "
            f"Current engine merges both retained tranches into a single __REM row "
            f"of EAD=600,000 instead of splitting into __REM_FL (200k) and __REM_SEN (400k)."
        )

    def test_p1_30e_art_234_first_loss_retained_ead_is_200k(
        self, tranche_rows: pl.DataFrame
    ) -> None:
        """
        CRR Art. 234: first-loss retained tranche must have EAD=200,000.

        Arrange: first-loss tranche = [0, a) = [0, 200k) → width 200k.
        Act:     full CRR SA pipeline.
        Assert:  the smallest retained row has ead_final=200,000.

        TODAY THIS FAILS: the single remainder row (EAD=600k) cannot match 200k.
        Even if the row count assertion (above) passes first, this provides specificity
        on which retained row corresponds to first-loss.
        """
        # Arrange
        retained_rows = tranche_rows.filter(pl.col("guarantor_reference").is_null()).sort(
            "ead_final"
        )

        if retained_rows.height == 0:
            pytest.fail("P1.30e Art. 234: no retained rows found with guarantor_reference=null.")

        # Take the row with smaller EAD as the first-loss tranche
        first_loss_ead = retained_rows["ead_final"][0]

        # Assert
        assert first_loss_ead == pytest.approx(_EXPECTED_EAD_FIRST_LOSS, rel=1e-6), (
            f"P1.30e Art. 234: first-loss retained tranche ead_final expected "
            f"{_EXPECTED_EAD_FIRST_LOSS:,.0f} (= attachment_amount = {ATTACHMENT_AMOUNT:,.0f}), "
            f"got {first_loss_ead:,.2f}. "
            f"Current engine has single retained row EAD={600_000:,.0f} (first-loss attach)."
        )

    def test_p1_30e_art_234_senior_retained_ead_is_400k(self, tranche_rows: pl.DataFrame) -> None:
        """
        CRR Art. 234: senior retained tranche must have EAD=400,000.

        Arrange: senior tranche = [d, EAD] = [600k, 1000k) → width 400k.
        Act:     full CRR SA pipeline.
        Assert:  the larger retained row has ead_final=400,000.

        TODAY THIS FAILS: the single remainder row has EAD=600,000, not 400,000.
        """
        # Arrange
        retained_rows = tranche_rows.filter(pl.col("guarantor_reference").is_null()).sort(
            "ead_final"
        )

        if retained_rows.height == 0:
            pytest.fail("P1.30e Art. 234: no retained rows found with guarantor_reference=null.")

        if retained_rows.height < 2:
            pytest.fail(
                f"P1.30e Art. 234: expected 2 retained rows but got {retained_rows.height}. "
                f"Cannot assert senior tranche EAD independently."
            )

        # Take the row with larger EAD as the senior tranche
        senior_ead = retained_rows["ead_final"][1]

        # Assert
        assert senior_ead == pytest.approx(_EXPECTED_EAD_SENIOR, rel=1e-6), (
            f"P1.30e Art. 234: senior retained tranche ead_final expected "
            f"{_EXPECTED_EAD_SENIOR:,.0f} (= EAD - detachment_amount = "
            f"{LOAN_EAD:,.0f} - {DETACHMENT_AMOUNT:,.0f}), "
            f"got {senior_ead:,.2f}."
        )

    # -----------------------------------------------------------------------
    # EAD conservation
    # -----------------------------------------------------------------------

    def test_p1_30e_art_234_ead_conservation(self, tranche_rows: pl.DataFrame) -> None:
        """
        EAD conservation: sum of all tranche EADs must equal original EAD (1,000,000).

        Arrange: three tranches (200k + 400k + 400k) must sum to 1,000,000.
        Act:     full CRR SA pipeline.
        Assert:  sum(ead_final) across all parent=EXP-234-1 rows == 1,000,000.

        This assertion PASSES today (2-row engine sums to 400k+600k=1,000k correctly)
        but is included as a regression pin: once the three-row fix is in, ΣEAD must
        still equal 1,000,000.
        """
        # Arrange / Act
        total_ead = tranche_rows["ead_final"].sum()

        # Assert
        assert total_ead == pytest.approx(_EXPECTED_EAD_TOTAL, rel=1e-6), (
            f"P1.30e Art. 234: ΣEAD across all tranches expected {_EXPECTED_EAD_TOTAL:,.0f} "
            f"(EAD conservation — no EAD lost or gained in tranche split), "
            f"got {total_ead:,.2f}"
        )

    # -----------------------------------------------------------------------
    # Mezzanine row: risk weight and is_guaranteed flag
    # -----------------------------------------------------------------------

    def test_p1_30e_art_234_mezzanine_row_risk_weight_is_50_pct(
        self, tranche_rows: pl.DataFrame
    ) -> None:
        """
        CRR Art. 234 + Art. 235 RWSM: mezzanine guaranteed tranche risk weight = 50%.

        Arrange: guarantor CP-INST-1 is institution CQS 2 → CRR Art. 120 Table 3 = 50%.
                 Substitution is beneficial (50% < obligor 100%) per Art. 213.
        Act:     full CRR SA pipeline.
        Assert:  the guaranteed row has risk_weight = 0.50.

        This assertion PASSES today (the existing guaranteed row does carry 50% RW)
        and is retained as a regression pin to confirm the mezzanine fix preserves the
        correct substituted risk weight on the guaranteed sub-row.
        """
        # Arrange
        guaranteed_rows = tranche_rows.filter(pl.col("guarantor_reference") == GUARANTOR_REF)

        if guaranteed_rows.height == 0:
            pytest.fail(
                f"P1.30e Art. 234: no guaranteed row with guarantor_reference='{GUARANTOR_REF}' found."
            )

        # Assert
        mez_rw = guaranteed_rows["risk_weight"][0]
        assert mez_rw == pytest.approx(_EXPECTED_GUARANTOR_RW, rel=1e-6), (
            f"P1.30e Art. 234: mezzanine row risk_weight expected {_EXPECTED_GUARANTOR_RW:.2f} "
            f"(institution CQS 2, CRR Art. 120 Table 3), got {mez_rw:.4f}"
        )

    def test_p1_30e_art_234_mezzanine_row_is_guaranteed_true(
        self, tranche_rows: pl.DataFrame
    ) -> None:
        """
        CRR Art. 234: the mezzanine protected row must have is_guaranteed=True.

        Arrange: G-234-1 covers the mezzanine band [200k, 600k).
        Act:     full CRR SA pipeline.
        Assert:  the row with guarantor_reference=CP-INST-1 has is_guaranteed=True.

        This assertion PASSES today (regression pin).
        """
        # Arrange
        guaranteed_rows = tranche_rows.filter(pl.col("guarantor_reference") == GUARANTOR_REF)

        if guaranteed_rows.height == 0:
            pytest.fail(
                f"P1.30e Art. 234: no guaranteed row with guarantor_reference='{GUARANTOR_REF}' found."
            )

        # Assert
        is_guar = guaranteed_rows["is_guaranteed"][0]
        assert is_guar is True, (
            f"P1.30e Art. 234: mezzanine row expected is_guaranteed=True, got {is_guar}"
        )

    # -----------------------------------------------------------------------
    # Aggregate scalar checks (pass today; regression pins post-fix)
    # -----------------------------------------------------------------------

    def test_p1_30e_art_234_total_rwa_is_800k(self, tranche_rows: pl.DataFrame) -> None:
        """
        CRR Art. 234: ΣRWA across all three tranches == 800,000.

        Arrange: 200k×100% + 400k×50% + 400k×100% = 200k + 200k + 400k = 800k.
        Act:     full CRR SA pipeline.
        Assert:  sum(rwa_final) == 800,000.

        NOTE: this assertion PASSES today (coincidentally, as the buggy 2-row engine
        also produces ΣRWA=800k). It is included as a regression pin.
        """
        # Arrange / Act
        total_rwa = tranche_rows["rwa_final"].sum()

        # Assert
        assert total_rwa == pytest.approx(_EXPECTED_RWA_TOTAL, rel=1e-6), (
            f"P1.30e Art. 234: ΣRWA expected {_EXPECTED_RWA_TOTAL:,.0f}, got {total_rwa:,.2f}"
        )

    def test_p1_30e_art_234_blended_risk_weight_is_80_pct(self, tranche_rows: pl.DataFrame) -> None:
        """
        CRR Art. 234: blended post-CRM risk weight == 0.80 (80%).

        Arrange: ΣRWA / ΣEAD = 800,000 / 1,000,000 = 0.80.
        Act:     full CRR SA pipeline.
        Assert:  sum(rwa_final) / sum(ead_final) == 0.80.

        NOTE: this also PASSES today (regression pin).
        """
        # Arrange / Act
        total_rwa = float(tranche_rows["rwa_final"].sum())
        total_ead = float(tranche_rows["ead_final"].sum())
        blended_rw = total_rwa / total_ead

        # Assert
        assert blended_rw == pytest.approx(_EXPECTED_BLENDED_RW, rel=1e-6), (
            f"P1.30e Art. 234: blended RW expected {_EXPECTED_BLENDED_RW:.2f} "
            f"(ΣRWA/ΣEAD = {_EXPECTED_RWA_TOTAL:,.0f}/{_EXPECTED_EAD_TOTAL:,.0f}), "
            f"got {blended_rw:.6f}"
        )
