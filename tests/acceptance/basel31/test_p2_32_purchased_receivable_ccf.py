"""
P2.32 / B31-D.CCF10 — Purchased-Receivables Undrawn-Commitment CCF override.

Scenario:
    PRA PS1/26 Art. 166E(5) states that undrawn purchase commitments for
    *revolving* purchased-receivables facilities receive a specific CCF:
        - 40% by default (Art. 111(1) Table A1 Row 5 "Other Commitments").
        - 10% when the commitment also satisfies the UCC criteria (Row 7 / LR).

    Without an explicit flag-based override, a revolving purchased-receivables
    commitment tagged as ``risk_type="MR"`` falls to the generic MR bucket
    (50% CCF) under Basel 3.1 — over-capitalising the CCF relative to the
    Art. 166E(5) ceiling.

    This scenario introduces a Boolean column
    ``is_purchased_receivable_commitment`` on facility rows.  When True AND
    ``is_revolving=True`` under a Basel 3.1 config, the CCF engine must:
        - Apply CCF = 0.40 for risk_type="OC" (main limb, Art. 166E(5))
        - Apply CCF = 0.10 for risk_type="LR" (UCC exception, Art. 166E(5))
        - Apply CCF = 0.40 for risk_type="MR" (override; generic MR=0.50 is
          wrong — LOAD-BEARING discriminator)

    Under CRR, the flag is a Basel-3.1-gated no-op: the CRR control row must
    NOT receive the purchased-receivable override and must resolve via the
    existing CRR OC CCF path.

Exposures under test (Basel 3.1 rows):

    PR_COMMIT_40 (B31-D.CCF10-OC):
        risk_type="OC", is_purchased_receivable_commitment=True, is_revolving=True
        Expected Basel 3.1:  ccf = 0.40,  ead_from_ccf = 400_000.00

    PR_COMMIT_10 (B31-D.CCF10-LR):
        risk_type="LR", is_purchased_receivable_commitment=True, is_revolving=True
        Expected Basel 3.1:  ccf = 0.10,  ead_from_ccf = 100_000.00

    PR_COMMIT_MR (B31-D.CCF10-MR) — LOAD-BEARING DISCRIMINATOR:
        risk_type="MR", is_purchased_receivable_commitment=True, is_revolving=True
        Expected Basel 3.1:  ccf = 0.40,  ead_from_ccf = 400_000.00
        Pre-fix engine gives: ccf = 0.50,  ead_from_ccf = 500_000.00  (FAILS)

    PR_COMMIT_40_CRR (CRR control):
        risk_type="OC", is_purchased_receivable_commitment=True, is_revolving=True
        Under CRR: flag is no-op; resolves via CRR OC path (not 400_000 Basel-3.1 result)

Test strategy:
    Load the P2.32 facility parquet directly into ``CCFCalculator.apply_ccf()``.
    The column ``is_purchased_receivable_commitment`` is present in the parquet
    but NOT yet in FACILITY_SCHEMA (engine-implementer adds it); it is preserved
    as an extra column because ``enforce_schema`` only casts known columns.

    The load-bearing MR test (test_p2_32_b31_ccf10_mr_row_*) MUST fail with
    AssertionError until the engine-implementer adds the Art. 166E(5) override
    in engine/ccf.py.  The OC/LR tests also fail.  The CRR control test passes
    now (regression guard).

References:
    - PRA PS1/26 App 1 Art. 166E(5): CCF on undrawn purchase commitments for
      revolving purchased receivables.
    - Art. 111(1) Table A1 Row 5 (OC = 40%) and Row 7 (LR/UCC = 10%).
    - src/rwa_calc/data/tables/ccf.py: SA_CCF_B31 — OC=0.40, LR=0.10, MR=0.50
    - src/rwa_calc/engine/ccf.py: CCFCalculator.apply_ccf
    - tests/fixtures/p2_32/p2_32.py: scenario constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.ccf import CCFCalculator
from tests.fixtures.p2_32.p2_32 import (
    EXPECTED_CCF_LR,
    EXPECTED_CCF_MR,
    EXPECTED_CCF_OC,
    EXPECTED_EAD_LR,
    EXPECTED_EAD_MR,
    EXPECTED_EAD_OC,
    FAC_REF_CRR,
    FAC_REF_LR,
    FAC_REF_MR,
    FAC_REF_OC,
    PRE_FIX_EAD_MR,
    SCENARIO_ID_B31,
    SCENARIO_ID_CRR,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p2_32"

# ---------------------------------------------------------------------------
# Module-scoped fixtures: run CCF stage once per config
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p2_32_b31_ccf_results() -> pl.DataFrame:
    """
    Load P2.32 facility parquet and run it through CCFCalculator under Basel 3.1.

    The facility parquet includes the ``is_purchased_receivable_commitment``
    Boolean column written directly by the fixture builder.  The column is NOT
    yet in FACILITY_SCHEMA (engine-implementer's wave), but it is preserved as
    an extra column on the LazyFrame because ``enforce_schema`` only casts known
    columns — it does not drop unknown ones.

    Pre-pipeline column setup:
        The CCF calculator expects ``nominal_amount`` and ``drawn_amount``, which
        the hierarchy stage normally derives from facility ``limit`` and drawn
        child exposures.  For this CCF-stage-isolated test we map them directly:
            nominal_amount = limit  (fully undrawn commitment)
            drawn_amount   = 0.0   (no drawn portion)

    Pre-fix behaviour (engine ignores the flag):
        PR_COMMIT_MR row  → ccf = 0.50  (wrong; expected 0.40 once fix lands)

    Returns:
        Collected DataFrame with CCF output columns (ccf, ead_from_ccf, ead_pre_crm).
    """
    # Arrange — load scenario-local parquet (includes is_purchased_receivable_commitment)
    # Filter out CRR control row; only Basel 3.1 rows in this fixture.
    facilities_lf = (
        pl.scan_parquet(_FIXTURES_DIR / "facility.parquet")
        .filter(pl.col("facility_reference") != FAC_REF_CRR)
        .with_columns(
            pl.col("limit").alias("nominal_amount"),
            pl.lit(0.0).alias("drawn_amount"),
        )
    )

    config = CalculationConfig.basel_3_1(reporting_date=date(2027, 12, 31))
    calculator = CCFCalculator()

    # Act — apply CCF stage directly (no full pipeline needed for this CCF-only test)
    result_lf = calculator.apply_ccf(facilities_lf, config)

    return result_lf.collect()


@pytest.fixture(scope="module")
def p2_32_crr_ccf_results() -> pl.DataFrame:
    """
    Load P2.32 CRR control row and run it through CCFCalculator under CRR.

    Under CRR the ``is_purchased_receivable_commitment`` flag must be a no-op:
    the row resolves via the existing CRR OC CCF path (0.50 for long maturities,
    or 0.20 for short maturities <= 365 days).  The B3.1 override (0.40) must
    NOT fire.

    Returns:
        Collected DataFrame with CCF output columns for the CRR control row.
    """
    # Arrange — load only the CRR control row
    facilities_lf = (
        pl.scan_parquet(_FIXTURES_DIR / "facility.parquet")
        .filter(pl.col("facility_reference") == FAC_REF_CRR)
        .with_columns(
            pl.col("limit").alias("nominal_amount"),
            pl.lit(0.0).alias("drawn_amount"),
        )
    )

    config = CalculationConfig.crr(reporting_date=date(2027, 12, 31))
    calculator = CCFCalculator()

    # Act
    result_lf = calculator.apply_ccf(facilities_lf, config)

    return result_lf.collect()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _row(df: pl.DataFrame, fac_ref: str, scenario_id: str) -> dict:
    """Return the single result row for ``fac_ref``, or raise for a clear error."""
    rows = df.filter(pl.col("facility_reference") == fac_ref).to_dicts()
    assert len(rows) == 1, (
        f"{scenario_id}: expected exactly 1 row for facility_reference={fac_ref!r}, "
        f"got {len(rows)}. Available: {df['facility_reference'].to_list()}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# Test class — OC row (PR_COMMIT_40)
# ---------------------------------------------------------------------------


class TestP232B31CCF10OCRow:
    """
    P2.32 B31-D.CCF10 OC row: risk_type="OC", is_purchased_receivable_commitment=True.

    Expected under Basel 3.1 (PRA PS1/26 Art. 166E(5) main limb):
        ccf = 0.40  (Table A1 Row 5 OC rate)
        ead_from_ccf = 1_000_000 × 0.40 = 400_000.00

    Pre-fix: ccf = 0.40 happens to match (OC fall-through) — but for the wrong
    reason (flag is ignored). This test passes pre-fix only by coincidence; the
    engine-implementer must ensure it passes FOR the right reason.
    """

    def test_p2_32_b31_ccf10_oc_row_ccf_is_40_pct(
        self,
        p2_32_b31_ccf_results: pl.DataFrame,
    ) -> None:
        """
        OC row: ccf == 0.40 (Art. 166E(5) main limb — Table A1 Row 5 OC rate).

        Arrange: PR_COMMIT_40, risk_type=OC, is_purchased_receivable_commitment=True,
                 is_revolving=True, limit=1_000_000, Basel 3.1 config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ccf == 0.40.

        References:
            PRA PS1/26 Art. 166E(5): undrawn purchase commitments for revolving
            purchased receivables → 40% by default.
        """
        # Arrange
        row = _row(p2_32_b31_ccf_results, FAC_REF_OC, SCENARIO_ID_B31)

        # Assert
        assert row["ccf"] == pytest.approx(EXPECTED_CCF_OC, abs=1e-6), (
            f"{SCENARIO_ID_B31} OC row ({FAC_REF_OC}): "
            f"expected ccf={EXPECTED_CCF_OC} "
            f"(PRA PS1/26 Art. 166E(5) main limb — OC 40%), "
            f"got {row['ccf']:.4f}."
        )

    def test_p2_32_b31_ccf10_oc_row_ead_is_400k(
        self,
        p2_32_b31_ccf_results: pl.DataFrame,
    ) -> None:
        """
        OC row: ead_from_ccf == 400_000.00 (1_000_000 × 0.40).

        Arrange: PR_COMMIT_40, limit=1_000_000, drawn_amount=0,
                 is_purchased_receivable_commitment=True, Basel 3.1 config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ead_from_ccf == 400_000.00.

        References:
            PRA PS1/26 Art. 166E(5): OC default CCF = 40%.
        """
        # Arrange
        row = _row(p2_32_b31_ccf_results, FAC_REF_OC, SCENARIO_ID_B31)

        # Assert
        assert row["ead_from_ccf"] == pytest.approx(EXPECTED_EAD_OC, rel=1e-4), (
            f"{SCENARIO_ID_B31} OC row ({FAC_REF_OC}): "
            f"expected ead_from_ccf={EXPECTED_EAD_OC:,.2f} "
            f"(1_000_000 × 0.40, Art. 166E(5)), "
            f"got {row['ead_from_ccf']:,.2f}."
        )


# ---------------------------------------------------------------------------
# Test class — LR / UCC row (PR_COMMIT_10)
# ---------------------------------------------------------------------------


class TestP232B31CCF10LRRow:
    """
    P2.32 B31-D.CCF10 LR row: risk_type="LR", is_purchased_receivable_commitment=True.

    Expected under Basel 3.1 (PRA PS1/26 Art. 166E(5) UCC exception):
        ccf = 0.10  (Table A1 Row 7 UCC / LR rate)
        ead_from_ccf = 1_000_000 × 0.10 = 100_000.00

    Pre-fix: SA_CCF_B31["LR"] = 0.10 by coincidence (LR fall-through) — but the
    engine should apply it through the Art. 166E(5) routing path.
    """

    def test_p2_32_b31_ccf10_lr_row_ccf_is_10_pct(
        self,
        p2_32_b31_ccf_results: pl.DataFrame,
    ) -> None:
        """
        LR row: ccf == 0.10 (Art. 166E(5) UCC exception — Table A1 Row 7).

        Arrange: PR_COMMIT_10, risk_type=LR, is_purchased_receivable_commitment=True,
                 is_revolving=True, limit=1_000_000, Basel 3.1 config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ccf == 0.10.

        References:
            PRA PS1/26 Art. 166E(5): UCC / LR exception → 10%.
        """
        # Arrange
        row = _row(p2_32_b31_ccf_results, FAC_REF_LR, SCENARIO_ID_B31)

        # Assert
        assert row["ccf"] == pytest.approx(EXPECTED_CCF_LR, abs=1e-6), (
            f"{SCENARIO_ID_B31} LR row ({FAC_REF_LR}): "
            f"expected ccf={EXPECTED_CCF_LR} "
            f"(PRA PS1/26 Art. 166E(5) UCC exception — LR 10%), "
            f"got {row['ccf']:.4f}."
        )

    def test_p2_32_b31_ccf10_lr_row_ead_is_100k(
        self,
        p2_32_b31_ccf_results: pl.DataFrame,
    ) -> None:
        """
        LR row: ead_from_ccf == 100_000.00 (1_000_000 × 0.10).

        Arrange: PR_COMMIT_10, limit=1_000_000, drawn_amount=0,
                 is_purchased_receivable_commitment=True, Basel 3.1 config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ead_from_ccf == 100_000.00.

        References:
            PRA PS1/26 Art. 166E(5): UCC/LR CCF = 10%.
        """
        # Arrange
        row = _row(p2_32_b31_ccf_results, FAC_REF_LR, SCENARIO_ID_B31)

        # Assert
        assert row["ead_from_ccf"] == pytest.approx(EXPECTED_EAD_LR, rel=1e-4), (
            f"{SCENARIO_ID_B31} LR row ({FAC_REF_LR}): "
            f"expected ead_from_ccf={EXPECTED_EAD_LR:,.2f} "
            f"(1_000_000 × 0.10, Art. 166E(5) UCC exception), "
            f"got {row['ead_from_ccf']:,.2f}."
        )


# ---------------------------------------------------------------------------
# Test class — MR row (PR_COMMIT_MR) — LOAD-BEARING DISCRIMINATOR
# ---------------------------------------------------------------------------


class TestP232B31CCF10MRRow:
    """
    P2.32 B31-D.CCF10 MR row: risk_type="MR", is_purchased_receivable_commitment=True.

    LOAD-BEARING: This is the only non-coincidental discriminator.  Without the
    Art. 166E(5) override, risk_type="MR" resolves to SA_CCF_B31["MR"] = 0.50,
    giving EAD = 500_000.  With the override, the flag routes the row to 0.40,
    giving EAD = 400_000.

    Expected under Basel 3.1 (PRA PS1/26 Art. 166E(5)):
        ccf = 0.40  (override: generic MR=0.50 → purchased-receivable OC default)
        ead_from_ccf = 1_000_000 × 0.40 = 400_000.00

    Pre-fix engine (ignores flag): ccf = 0.50, ead_from_ccf = 500_000.00
    Both assertions below FAIL until the engine is updated.
    """

    def test_p2_32_b31_ccf10_mr_row_ccf_is_40_pct(
        self,
        p2_32_b31_ccf_results: pl.DataFrame,
    ) -> None:
        """
        MR row (LOAD-BEARING): ccf == 0.40 (Art. 166E(5) override of generic MR=0.50).

        Arrange: PR_COMMIT_MR, risk_type=MR, is_purchased_receivable_commitment=True,
                 is_revolving=True, limit=1_000_000, Basel 3.1 config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ccf == 0.40.

        Pre-fix failure: ccf == 0.50 (SA_CCF_B31["MR"] — flag ignored).

        References:
            PRA PS1/26 Art. 166E(5): undrawn purchase commitments for revolving
            purchased receivables → 40% (main limb), regardless of risk_type.
        """
        # Arrange
        row = _row(p2_32_b31_ccf_results, FAC_REF_MR, SCENARIO_ID_B31)

        # Assert — LOAD-BEARING: pre-fix gives 0.50, expected 0.40
        assert row["ccf"] == pytest.approx(EXPECTED_CCF_MR, abs=1e-6), (
            f"{SCENARIO_ID_B31} MR row ({FAC_REF_MR}): "
            f"expected ccf={EXPECTED_CCF_MR} "
            f"(PRA PS1/26 Art. 166E(5) override — purchased-receivable OC 40%), "
            f"got {row['ccf']:.4f}. "
            f"Engine does not yet apply the is_purchased_receivable_commitment override; "
            f"generic MR fall-through gives 0.50 instead."
        )

    def test_p2_32_b31_ccf10_mr_row_ead_is_400k(
        self,
        p2_32_b31_ccf_results: pl.DataFrame,
    ) -> None:
        """
        MR row (LOAD-BEARING): ead_from_ccf == 400_000.00 (1_000_000 × 0.40).

        Arrange: PR_COMMIT_MR, risk_type=MR, limit=1_000_000, drawn_amount=0,
                 is_purchased_receivable_commitment=True, Basel 3.1 config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ead_from_ccf == 400_000.00.

        Pre-fix failure: ead_from_ccf == 500_000.00 (1_000_000 × 0.50, MR fall-through).

        References:
            PRA PS1/26 Art. 166E(5): override routes MR → OC default CCF = 40%.
        """
        # Arrange
        row = _row(p2_32_b31_ccf_results, FAC_REF_MR, SCENARIO_ID_B31)

        # Assert — LOAD-BEARING: pre-fix gives 500_000, expected 400_000
        assert row["ead_from_ccf"] == pytest.approx(EXPECTED_EAD_MR, rel=1e-4), (
            f"{SCENARIO_ID_B31} MR row ({FAC_REF_MR}): "
            f"expected ead_from_ccf={EXPECTED_EAD_MR:,.2f} "
            f"(1_000_000 × 0.40, Art. 166E(5) purchased-receivable override), "
            f"got {row['ead_from_ccf']:,.2f}. "
            f"Pre-fix EAD = {PRE_FIX_EAD_MR:,.2f} (generic MR=0.50 × 1_000_000)."
        )


# ---------------------------------------------------------------------------
# Test class — CRR control (PR_COMMIT_40_CRR)
# ---------------------------------------------------------------------------


class TestP232CRRControlRow:
    """
    P2.32 CRR-D.CCF9 CRR control: is_purchased_receivable_commitment=True, CRR config.

    The Art. 166E(5) override is Basel-3.1-gated.  Under CRR the flag is a no-op
    and the row must resolve via the existing CRR OC CCF path.

    Under CRR SA with long maturity (> 365 days): SA_CCF_CRR["OC"] = 0.50.
    EAD = 1_000_000 × 0.50 = 500_000.

    Anti-assertion: the CRR EAD must NOT equal the B3.1 purchased-receivable
    result of 400_000 — i.e. the flag must not leak into CRR behaviour.
    """

    def test_p2_32_crr_control_ead_is_not_b31_purchased_receivable_result(
        self,
        p2_32_crr_ccf_results: pl.DataFrame,
    ) -> None:
        """
        CRR control: EAD != 400_000 (flag must not leak B3.1 OC purchased-receivable
        CCF into CRR path).

        Robustness anti-assertion: we do NOT pin the exact CRR EAD value because
        the CRR OC path may apply a maturity-dependent override (0.50 for >365d,
        0.20 for ≤365d), and the exact value may differ across config variants.
        The only requirement is that the B3.1 40% purchased-receivable EAD (400_000)
        does NOT appear under CRR.

        Arrange: PR_COMMIT_40_CRR, risk_type=OC, is_purchased_receivable_commitment=True,
                 is_revolving=True, limit=1_000_000, CRR config (reporting_date=2027-12-31,
                 maturity_date=2030-06-30 → > 365 days → long maturity → CRR OC 0.50).
        Act:     CCFCalculator.apply_ccf() with CalculationConfig.crr().
        Assert:  ead_from_ccf != 400_000.00  (the B3.1 purchased-receivable result).

        References:
            CRR Art. 111: SA CCF categories — OC 50% (>1yr) or 20% (≤1yr).
            PRA PS1/26 Art. 166E(5): Basel-3.1-only — flag is no-op under CRR.
        """
        # Arrange
        row = _row(p2_32_crr_ccf_results, FAC_REF_CRR, SCENARIO_ID_CRR)
        b31_purchased_receivable_ead = EXPECTED_EAD_OC  # 400_000 — the B3.1 result

        # Assert — anti-assertion: CRR must NOT return the B3.1 purchased-receivable EAD
        assert row["ead_from_ccf"] != pytest.approx(b31_purchased_receivable_ead, rel=1e-4), (
            f"{SCENARIO_ID_CRR} CRR control ({FAC_REF_CRR}): "
            f"ead_from_ccf == {b31_purchased_receivable_ead:,.2f} suggests the "
            f"is_purchased_receivable_commitment flag has leaked into the CRR path. "
            f"Art. 166E(5) is Basel-3.1-only; CRR must resolve via the OC CCF path. "
            f"Got ead_from_ccf = {row['ead_from_ccf']:,.2f}."
        )
