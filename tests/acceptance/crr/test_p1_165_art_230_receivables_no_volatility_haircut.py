"""
P1.165: CRR Art. 230 receivables collateral — no Art. 224 volatility haircut.

CRR Art. 224 Tables 1-4 list eligible financial-collateral instrument categories
(debt securities by CQS/maturity, equities, gold, units in CIUs, cash).
Receivables are NOT listed. Per CRR Art. 199(5), receivables are non-financial
collateral eligible under F-IRB only, and their entire regulatory treatment is
governed by CRR Art. 230 (Foundation Collateral Method):

    - LGDS = 35% (senior) / 65% (subordinated)    — Art. 230 Table 5
    - Overcollateralisation ratio = 1.25x          — Art. 230(2)
    - No separate volatility haircut Hc

The pre-fix engine carries an ad-hoc entry COLLATERAL_HAIRCUTS["receivables"] =
Decimal("0.20") in src/rwa_calc/data/tables/haircuts.py, which causes a
double-count: the engine first discounts the collateral value by 20%, then
applies the Art. 230 OC divisor of 1.25x.  That reduces the effectively-secured
portion from the correct 640,000 to 512,000 and inflates LGD* from 0.386 to
approximately 0.499.

Pipeline position:
    RawDataBundle -> Loader -> Classifier -> CRMProcessor -> IRBCalculator -> Aggregator

Hand calculation (with Hc = 0, the post-fix expectation):
    EAD                         = 1,000,000.00   (on-BS, CCF = 100%)
    Hc                          = 0.0            (Art. 224 has no receivables row)
    Hfx                         = 0.0            (GBP/GBP, same currency)
    value_after_haircut         = 800,000 × (1 - 0 - 0) = 800,000.00
    adjusted_value              = 800,000.00      (no maturity mismatch)
    effectively_secured         = 800,000 / 1.25 = 640,000.00
    secured_portion LGD (LGDS)  = 35%
    unsecured_portion LGD (LGDU)= 45%  (Art. 161(1)(a), senior corporate non-FSE)
    LGD*                        = (0.35 × 640,000 + 0.45 × 360,000) / 1,000,000 = 0.386

Pre-fix LGD* (with Hc = 0.20):
    value_after_haircut         = 800,000 × 0.80 = 640,000.00
    effectively_secured         = 640,000 / 1.25 = 512,000.00
    LGD*                        = (0.35 × 512,000 + 0.45 × 488,000) / 1,000,000 ≈ 0.4988

References:
    - CRR Art. 199(5): receivables eligible as non-financial collateral (F-IRB only)
    - CRR Art. 224 Tables 1-4: supervisory volatility haircuts (receivables NOT listed)
    - CRR Art. 230(1)-(2): Foundation Collateral Method — LGDS, OC ratio 1.25x
    - CRR Art. 230 Table 5: senior LGDS 35%, subordinated 65%, OC 1.25x
    - CRR Art. 153(1): F-IRB capital requirement K formula, 1.06 scaling factor
    - CRR Art. 161(1)(a): LGDU senior unsecured corporate non-FSE = 45%
    - src/rwa_calc/data/tables/haircuts.py: COLLATERAL_HAIRCUTS (offending receivables = 0.20 pre-fix)
    - IMPLEMENTATION_PLAN.md: P1.165
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p1_165.p1_165 import (
    COUNTERPARTY_REF,
    EXPECTED_LGD_STAR,
    LOAN_REF,
    MODEL_ID,
    PD,
    REPORTING_DATE,
)

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.haircuts import (
    BASEL31_COLLATERAL_HAIRCUTS,
    COLLATERAL_HAIRCUTS,
    lookup_collateral_haircut,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_165"

# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline_p165() -> object:
    """
    Run the full CRR F-IRB pipeline for the P1.165 receivables scenario.

    Loads all six parquet files from fixtures/p1_165/ and assembles a
    RawDataBundle.  The model_permission row steers CRR-P1165-CP1 to F-IRB,
    which causes the Art. 230 LGD* path to execute.
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

    bundle = RawDataBundle(
        facilities=pl.scan_parquet(_FIXTURES_DIR / "facility.parquet"),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        collateral=pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet"),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        model_permissions=pl.scan_parquet(_FIXTURES_DIR / "model_permission.parquet"),
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
    )
    config = CalculationConfig.crr(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _find_loan_rows(results: object, loan_ref: str) -> list[dict]:
    """
    Return all result rows containing *loan_ref* in exposure_reference.

    Searches sa_results, irb_results, and slotting_results (whichever are
    non-None) to be agnostic about the routing branch.
    """
    rows: list[dict] = []
    for lf in [results.sa_results, results.irb_results, results.slotting_results]:
        if lf is None:
            continue
        df = lf.filter(pl.col("exposure_reference").str.contains(loan_ref)).collect()
        rows.extend(df.to_dicts())
    return rows


def _sum_field(rows: list[dict], field: str) -> float:
    """Sum *field* across all result rows (handles guarantee sub-row splits)."""
    return sum(r.get(field) or 0.0 for r in rows)


def _first(rows: list[dict], field: str):
    """Return the first non-null value of *field* from the result rows."""
    for r in rows:
        v = r.get(field)
        if v is not None:
            return v
    return None


# ---------------------------------------------------------------------------
# §1 — Module-level / table-level pin tests
# These three tests assert directly on the data-layer constants WITHOUT running
# the pipeline.  The first two will FAIL until the engine-implementer sets
# COLLATERAL_HAIRCUTS["receivables"] = Decimal("0").
# ---------------------------------------------------------------------------


class TestP1165HaircutsTablePins:
    """
    P1.165: Pin the CRR and Basel 3.1 receivables haircut constants.

    test_crr_collateral_haircuts_receivables_is_zero and
    test_lookup_collateral_haircut_crr_receivables_is_zero will FAIL until
    the engine-implementer removes the erroneous 0.20 entry from
    COLLATERAL_HAIRCUTS["receivables"].

    test_b31_collateral_haircuts_receivables_unchanged is a regression GUARD
    that must PASS before and after the fix — it locks the B31 path (0.40) so
    the engine-implementer cannot accidentally touch it.
    """

    def test_crr_collateral_haircuts_receivables_is_zero(self) -> None:
        """
        CRR Art. 224 has no receivables row — COLLATERAL_HAIRCUTS["receivables"] must be 0.

        CRR Art. 224 Tables 1-4 enumerate eligible financial collateral types only.
        Receivables are non-financial collateral per Art. 199(5) and have no Art. 224
        haircut.  The CRR treatment is entirely via Art. 230 Foundation Collateral
        Method (LGDS 35%, OC 1.25x).

        Arrange: import COLLATERAL_HAIRCUTS from rwa_calc.data.tables.haircuts.
        Act:     read COLLATERAL_HAIRCUTS["receivables"].
        Assert:  value == Decimal("0").

        Pre-fix: COLLATERAL_HAIRCUTS["receivables"] == Decimal("0.20").
        Post-fix: Decimal("0") (or key removed, but engine references it by key).
        """
        # Arrange / Act
        actual = COLLATERAL_HAIRCUTS["receivables"]

        # Assert
        assert actual == Decimal("0"), (
            f"P1.165: COLLATERAL_HAIRCUTS['receivables'] must be Decimal('0') "
            f"per CRR Art. 224 (no receivables row in Tables 1-4). "
            f"Got {actual!r}. "
            f"Pre-fix value is Decimal('0.20') — an ad-hoc approximation with no "
            f"regulatory basis. The Art. 230 OC mechanism (1.25x) already captures "
            f"the regulatory recognition limitation."
        )

    def test_lookup_collateral_haircut_crr_receivables_is_zero(self) -> None:
        """
        lookup_collateral_haircut("receivables", is_basel_3_1=False) must return Decimal("0").

        This is the function-level companion to the table test above.  The lookup
        function must return 0 (not 0.20) for CRR receivables.

        Arrange: call lookup_collateral_haircut with is_basel_3_1=False.
        Act:     inspect the return value.
        Assert:  return value == Decimal("0").

        Pre-fix: returns Decimal("0.20").
        """
        # Arrange / Act
        result = lookup_collateral_haircut("receivables", is_basel_3_1=False)

        # Assert
        assert result == Decimal("0"), (
            f"P1.165: lookup_collateral_haircut('receivables', is_basel_3_1=False) "
            f"must return Decimal('0'). "
            f"Got {result!r}. "
            f"CRR Art. 224 has no receivables row — Hc=0 for the CRR path."
        )

    def test_b31_collateral_haircuts_receivables_unchanged(self) -> None:
        """
        REGRESSION GUARD: Basel 3.1 receivables haircut must stay at 0.40.

        PRA PS1/26 Art. 230(2) explicitly sets HC=40% for receivables in the
        LGD* formula (different from CRR Art. 230 which has no HC).  This scenario
        does NOT change the Basel 3.1 behaviour — this test locks it.

        Arrange: import BASEL31_COLLATERAL_HAIRCUTS from rwa_calc.data.tables.haircuts.
        Act:     read BASEL31_COLLATERAL_HAIRCUTS["receivables"] and
                 call lookup_collateral_haircut("receivables", is_basel_3_1=True).
        Assert:  both values == Decimal("0.40").

        This test must PASS before and after the P1.165 fix is applied.
        """
        # Arrange / Act
        table_value = BASEL31_COLLATERAL_HAIRCUTS["receivables"]
        lookup_value = lookup_collateral_haircut("receivables", is_basel_3_1=True)

        # Assert — table
        assert table_value == Decimal("0.40"), (
            f"P1.165 regression guard: BASEL31_COLLATERAL_HAIRCUTS['receivables'] "
            f"must remain Decimal('0.40') (PRA PS1/26 Art. 230(2)). "
            f"Got {table_value!r}. "
            f"P1.165 only removes the CRR haircut; the Basel 3.1 path is correct."
        )

        # Assert — lookup
        assert lookup_value == Decimal("0.40"), (
            f"P1.165 regression guard: lookup_collateral_haircut('receivables', "
            f"is_basel_3_1=True) must return Decimal('0.40'). "
            f"Got {lookup_value!r}."
        )


# ---------------------------------------------------------------------------
# §2 — End-to-end pipeline test
# The pipeline test will FAIL until the engine-implementer removes the 0.20 haircut.
# ---------------------------------------------------------------------------


class TestP1165ReceivablesPipelineNoHaircut:
    """
    P1.165 end-to-end: CRR F-IRB pipeline with receivables collateral produces
    LGD* = 0.386 (not 0.4988), confirming Hc=0 is used throughout.

    The class-scoped pipeline fixture runs the full PipelineOrchestrator once and
    caches the result.  Individual tests then query the IRB result rows for
    loan_reference="CRR-P1165-L1".
    """

    @pytest.fixture(scope="class")
    def pipeline_result(self):
        """
        Run the CRR F-IRB pipeline for P1.165 once and cache the result.

        Returns the AggregatedResultBundle from PipelineOrchestrator.run_with_data.
        """
        return _run_pipeline_p165()

    @pytest.fixture(scope="class")
    def loan_rows(self, pipeline_result) -> list[dict]:
        """
        All result rows for CRR-P1165-L1.

        Looks in sa_results, irb_results, and slotting_results to be routing-agnostic.
        """
        rows = _find_loan_rows(pipeline_result, LOAN_REF)
        assert rows, (
            f"P1.165: no pipeline result rows found for loan_reference='{LOAN_REF}'. "
            f"Check fixture routing — counterparty {COUNTERPARTY_REF} must be steered "
            f"to F-IRB by model_permission row model_id='{MODEL_ID}'."
        )
        return rows

    # ------------------------------------------------------------------
    # EAD assertions — must pass before and after the fix
    # ------------------------------------------------------------------

    def test_crr_p1165_receivables_ead_gross(self, loan_rows: list[dict]) -> None:
        """
        P1.165: ead_gross == 1,000,000.00 (on-BS, CCF=100%, no EAD reduction on F-IRB).

        Arrange: CRR-P1165-L1, drawn_amount=1,000,000, F-IRB path.
        Act:     full CRR F-IRB pipeline (Art. 230 LGD* path).
        Assert:  ead_gross == 1,000,000.00.

        F-IRB does not net EAD via collateral; collateral effect is only on LGD*.
        """
        # Arrange (rows from class fixture)
        ead = _sum_field(loan_rows, "ead_gross")

        # Assert
        assert ead == pytest.approx(1_000_000.00, abs=0.01), (
            f"P1.165: expected ead_gross=1,000,000, got {ead:,.2f}."
        )

    def test_crr_p1165_receivables_ead_final(self, loan_rows: list[dict]) -> None:
        """
        P1.165: ead_final == 1,000,000.00 (F-IRB collateral does not reduce EAD).

        Arrange: CRR-P1165-L1, F-IRB path, collateral_type=receivables.
        Act:     full CRR F-IRB pipeline.
        Assert:  ead_final == 1,000,000.00.
        """
        # Arrange (rows from class fixture)
        ead = _sum_field(loan_rows, "ead_final")

        # Assert
        assert ead == pytest.approx(1_000_000.00, abs=0.01), (
            f"P1.165: expected ead_final=1,000,000 for F-IRB (collateral only "
            f"affects LGD*, not EAD). Got {ead:,.2f}."
        )

    # ------------------------------------------------------------------
    # PD assertion — must pass before and after the fix
    # ------------------------------------------------------------------

    def test_crr_p1165_receivables_irb_pd_adjusted(self, loan_rows: list[dict]) -> None:
        """
        P1.165: pd_floored == 0.02 (above CRR corporate PD floor 0.0003).

        Confirm the F-IRB path executed and used the rating-fixture PD=2%.
        The pipeline stores the post-floor PD in the "pd_floored" column of irb_results.

        Arrange: rating fixture pd=0.02, model_id=UK_CORP_FIRB_P1165.
        Act:     full CRR F-IRB pipeline.
        Assert:  pd_floored ≈ 0.02 (within 1e-6).
        """
        # Arrange
        pd_floored = _first(loan_rows, "pd_floored")

        # Assert
        assert pd_floored is not None, (
            f"P1.165: pd_floored not found in result rows for '{LOAN_REF}'. "
            f"Loan may not have been routed to IRB — check model_permissions fixture."
        )
        assert pd_floored == pytest.approx(PD, abs=1e-6), (
            f"P1.165: expected pd_floored={PD} (from rating fixture, above 0.0003 floor), "
            f"got {pd_floored}."
        )

    # ------------------------------------------------------------------
    # Load-bearing LGD* assertion — FAILS pre-fix, passes post-fix
    # ------------------------------------------------------------------

    def test_crr_p1165_receivables_pipeline_no_haircut(self, loan_rows: list[dict]) -> None:
        """
        P1.165 LOAD-BEARING: lgd_floored == 0.386 (Art. 230 LGD* without Hc).

        The pipeline stores the post-CRM, post-floor blended LGD* in the
        "lgd_floored" column of irb_results (which equals lgd_post_crm for
        performing exposures above the floor).

        This test FAILS today because the pre-fix engine applies Hc=0.20 to the
        receivables collateral, which reduces value_after_haircut from 800,000 to
        640,000 (= 800,000 × 0.80) BEFORE the Art. 230 OC divisor (1.25x).
        The double-reduction gives:

            collateral_receivables_value (pre-fix) = 800,000 × 0.80 = 640,000
                (scaled by 20-day liquidation: actual pre-fix ≈ 573,725 due to
                 Art. 226 sqrt(20/10) = sqrt(2) scaling of the 20% base haircut)
            effectively_secured (pre-fix) = 573,725 / 1.25 ≈ 458,980
            lgd_floored (pre-fix) ≈ (0.35 × 458,980 + 0.45 × 541,020) / 1,000,000 ≈ 0.4041

        After the fix (Hc=0):
            collateral_receivables_value = 800,000 × (1 - 0 - 0) = 800,000
            effectively_secured = 800,000 / 1.25 = 640,000
            lgd_floored (post-fix) = (0.35 × 640,000 + 0.45 × 360,000) / 1,000,000 = 0.386

        Arrange: CRR-P1165-L1, receivables collateral MV=800,000, F-IRB path, CRR framework.
        Act:     full CRR F-IRB pipeline (PipelineOrchestrator.run_with_data).
        Assert:  lgd_floored == 0.386 ± 1e-3.

        Pre-fix engine produces ≈ 0.4041 → assertion fails with AssertionError.
        """
        # Arrange
        lgd_floored = _first(loan_rows, "lgd_floored")

        # Assert
        assert lgd_floored is not None, (
            f"P1.165: lgd_floored not found in result rows for '{LOAN_REF}'. "
            f"Loan may not have been routed to IRB — check model_permissions fixture."
        )
        assert lgd_floored == pytest.approx(EXPECTED_LGD_STAR, abs=1e-3), (
            f"P1.165: expected lgd_floored={EXPECTED_LGD_STAR:.4f} "
            f"(Art. 230: (0.35 × 640,000 + 0.45 × 360,000) / 1,000,000). "
            f"Got {lgd_floored:.6f}. "
            f"If ≈ 0.4041 the engine is still applying Hc=0.20 (20-day scaled) to "
            f"receivables: COLLATERAL_HAIRCUTS['receivables'] must be set to "
            f"Decimal('0') per CRR Art. 224 (receivables not listed in Tables 1-4). "
            f"The Art. 230 OC mechanism (1.25x) is the only applicable reduction."
        )

    # ------------------------------------------------------------------
    # Regression sentinel — pre-fix LGD* must NOT appear post-fix
    # ------------------------------------------------------------------

    def test_crr_p1165_receivables_lgd_not_pre_fix_value(self, loan_rows: list[dict]) -> None:
        """
        P1.165 regression sentinel: lgd_floored must NOT be ≈ 0.4041 post-fix.

        Pre-fix: Hc=0.20 (20-day scaled ≈ 0.2828) reduces collateral_receivables_value
                 to ≈573,725; effectively_secured ≈ 458,980 → lgd_floored ≈ 0.4041.
        Post-fix: Hc=0 → collateral_receivables_value=800,000;
                  effectively_secured=640,000 → lgd_floored=0.386.

        This guard fails if the engine reverts to applying a receivables haircut.

        Arrange: same as test_crr_p1165_receivables_pipeline_no_haircut.
        Act:     full CRR F-IRB pipeline.
        Assert:  lgd_floored != 0.4041 (tolerance ±1e-3).
        """
        # Arrange
        lgd_floored = _first(loan_rows, "lgd_floored")
        if lgd_floored is None:
            pytest.skip("lgd_floored not available — routing issue")

        pre_fix_lgd = 0.4041

        # Assert
        assert lgd_floored != pytest.approx(pre_fix_lgd, abs=1e-3), (
            f"P1.165 regression: lgd_floored is still ≈ {pre_fix_lgd:.4f} "
            f"(pre-fix value produced by Hc=0.20 on receivables). "
            f"Expected ≈ 0.386 after removing the erroneous receivables haircut."
        )
