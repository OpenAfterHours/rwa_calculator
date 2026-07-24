"""
P2.33 / B31-D.CCF9 — UK residential-mortgage commitment 50% CCF override.

Scenario:
    PRA PS1/26 Art. 111(1) Table A1 Row 4(b) states that commitments to extend
    credit secured by residential property receive a 50% CCF.  Without an explicit
    flag-based override, a UK residential-mortgage commitment tagged as
    ``risk_type="OC"`` falls to the generic "other commitments" bucket (Row 5,
    40% CCF) under Basel 3.1 — under-capitalising the CCF.

    This scenario introduces a Boolean column
    ``is_uk_residential_mortgage_commitment`` on facility rows.  When True under
    a Basel 3.1 config, the CCF engine must apply 50% (the MR / Row 4(b) rate)
    instead of the OC 40% fall-through.

Exposures under test:

    FLAGGED  (B31-CCF9-RESI):
        risk_type="OC", is_uk_residential_mortgage_commitment=True
        Expected Basel 3.1:  ccf = 0.50,  ead_from_ccf = 500_000.00
        Pre-fix engine gives: ccf = 0.40,  ead_from_ccf = 400_000.00  (FAILS)

    CONTROL  (B31-CCF9-OC-CONTROL):
        risk_type="OC", is_uk_residential_mortgage_commitment=False
        Expected Basel 3.1:  ccf = 0.40,  ead_from_ccf = 400_000.00  (PASSES now)

Test strategy:
    Load the P2.33 facility parquet (which carries the new Boolean column) directly
    into ``CCFCalculator.apply_ccf()``.  The column survives schema enforcement
    because ``enforce_schema`` preserves extra columns; the CCF engine ignores the
    flag pre-fix, so the flagged row returns 0.40 instead of 0.50.

    The FLAGGED test (test_p2_33_b31_ccf9_flagged_*) MUST fail with AssertionError
    until the engine-implementer adds the Row 4(b) override.
    The CONTROL test (test_p2_33_b31_ccf9_control_*) passes immediately — it is a
    regression guard for the standard OC path.

References:
    - PRA PS1/26 Art. 111(1) Table A1: Row 4(b) residential-property commitment 50%
    - PRA PS1/26 Art. 111(1) Table A1: Row 5 "other commitments" (OC) 40%
    - src/rwa_calc/rulebook/packs/b31.py: "sa_ccf" LookupTable — OC=0.40, MR=0.50
    - src/rwa_calc/engine/ccf.py: CCFCalculator.apply_ccf
    - tests/fixtures/p2_33/p2_33.py: scenario constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.ccf import CCFCalculator
from tests.fixtures.p2_33.p2_33 import (
    CONTROL_FAC_REF,
    EXPECTED_CCF_CONTROL,
    EXPECTED_CCF_FLAGGED,
    EXPECTED_EAD_FROM_CCF_CONTROL,
    EXPECTED_EAD_FROM_CCF_FLAGGED,
    FLAGGED_FAC_REF,
    SCENARIO_ID,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p2_33"

# ---------------------------------------------------------------------------
# Module-scoped fixture: run CCF stage once for both test classes
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p2_33_ccf_results() -> pl.DataFrame:
    """
    Load P2.33 facility parquet and run it through CCFCalculator under Basel 3.1.

    The facility parquet includes the ``is_uk_residential_mortgage_commitment``
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

    The CCF calculator currently ignores the new flag, so:
        FLAGGED  row → ccf = 0.40  (wrong; expected 0.50 once fix lands)
        CONTROL  row → ccf = 0.40  (correct baseline — regression guard)

    Returns:
        Collected DataFrame with CCF output columns (ccf, ead_from_ccf, ead_pre_crm).
    """
    # Arrange — load scenario-local parquet (includes is_uk_residential_mortgage_commitment)
    # Add the columns the CCF stage expects (normally populated by HierarchyResolver).
    facilities_lf = pl.scan_parquet(_FIXTURES_DIR / "facility.parquet").with_columns(
        pl.col("limit").alias("nominal_amount"),
        pl.lit(0.0).alias("drawn_amount"),
    )

    config = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))
    calculator = CCFCalculator()

    # Act — apply CCF stage directly (no full pipeline needed for this CCF-only test)
    result_lf = calculator.apply_ccf(facilities_lf, config)

    return result_lf.collect()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _row(df: pl.DataFrame, fac_ref: str) -> dict:
    """Return the single result row for ``fac_ref``, or raise for a clear error."""
    rows = df.filter(pl.col("facility_reference") == fac_ref).to_dicts()
    assert len(rows) == 1, (
        f"{SCENARIO_ID}: expected exactly 1 row for facility_reference={fac_ref!r}, "
        f"got {len(rows)}. Available: {df['facility_reference'].to_list()}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# Test class — FLAGGED exposure (B31-CCF9-RESI)
# ---------------------------------------------------------------------------


class TestP233B31CCF9FlaggedResiMortgageCommitment:
    """
    P2.33 B31-D.CCF9 FLAGGED row: is_uk_residential_mortgage_commitment=True.

    Expected under Basel 3.1 (PRA PS1/26 Table A1 Row 4(b)):
        ccf = 0.50  (residential-property commitment override)
        ead_from_ccf = 1_000_000 × 0.50 = 500_000.00

    Pre-fix engine (ignores flag): ccf = 0.40, ead_from_ccf = 400_000.00
    Both assertions below FAIL until the engine is updated.
    """

    def test_p2_33_b31_ccf9_flagged_ccf_is_50_pct(
        self,
        p2_33_ccf_results: pl.DataFrame,
    ) -> None:
        """
        FLAGGED: ccf == 0.50 (Table A1 Row 4(b) residential-property commitment).

        Arrange: facility B31-CCF9-RESI, risk_type=OC,
                 is_uk_residential_mortgage_commitment=True, limit=1_000_000,
                 Basel 3.1 config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ccf == 0.50.

        Pre-fix failure: ccf == 0.40 (OC fall-through — flag ignored).

        References:
            PRA PS1/26 Art. 111(1) Table A1 Row 4(b): residential commitment → 50%.
        """
        # Arrange
        row = _row(p2_33_ccf_results, FLAGGED_FAC_REF)

        # Assert
        assert row["ccf"] == pytest.approx(EXPECTED_CCF_FLAGGED, abs=1e-6), (
            f"{SCENARIO_ID} FLAGGED ({FLAGGED_FAC_REF}): "
            f"expected ccf={EXPECTED_CCF_FLAGGED} "
            f"(PRA PS1/26 Table A1 Row 4(b) — residential-property commitment 50%), "
            f"got {row['ccf']:.4f}. "
            f"Engine does not yet apply the is_uk_residential_mortgage_commitment "
            f"override; OC fall-through gives 0.40 instead."
        )

    def test_p2_33_b31_ccf9_flagged_ead_from_ccf_is_500k(
        self,
        p2_33_ccf_results: pl.DataFrame,
    ) -> None:
        """
        FLAGGED: ead_from_ccf == 500_000.00 (1_000_000 × 0.50).

        Arrange: facility B31-CCF9-RESI, limit=1_000_000, drawn_amount=0,
                 is_uk_residential_mortgage_commitment=True,
                 Basel 3.1 config, expected ccf=0.50.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ead_from_ccf == 500_000.00.

        Pre-fix failure: ead_from_ccf == 400_000.00 (1_000_000 × 0.40).

        References:
            PRA PS1/26 Art. 111(1) Table A1 Row 4(b).
        """
        # Arrange
        row = _row(p2_33_ccf_results, FLAGGED_FAC_REF)

        # Assert
        assert row["ead_from_ccf"] == pytest.approx(EXPECTED_EAD_FROM_CCF_FLAGGED, rel=1e-4), (
            f"{SCENARIO_ID} FLAGGED ({FLAGGED_FAC_REF}): "
            f"expected ead_from_ccf={EXPECTED_EAD_FROM_CCF_FLAGGED:,.2f} "
            f"(1_000_000 × 0.50, Table A1 Row 4(b)), "
            f"got {row['ead_from_ccf']:,.2f}. "
            f"Engine still uses OC 40% → ead_from_ccf = 400_000."
        )


# ---------------------------------------------------------------------------
# Test class — CONTROL exposure (B31-CCF9-OC-CONTROL)
# ---------------------------------------------------------------------------


class TestP233B31CCF9ControlOCCommitment:
    """
    P2.33 B31-D.CCF9 CONTROL row: is_uk_residential_mortgage_commitment=False.

    Expected under Basel 3.1 (PRA PS1/26 Table A1 Row 5 OC fall-through):
        ccf = 0.40
        ead_from_ccf = 1_000_000 × 0.40 = 400_000.00

    These assertions PASS now (regression guards for the standard OC path).
    """

    def test_p2_33_b31_ccf9_control_ccf_is_40_pct(
        self,
        p2_33_ccf_results: pl.DataFrame,
    ) -> None:
        """
        CONTROL: ccf == 0.40 (Table A1 Row 5 — standard OC, no override).

        Regression guard: flag=False must NOT trigger the residential override.

        Arrange: facility B31-CCF9-OC-CONTROL, risk_type=OC,
                 is_uk_residential_mortgage_commitment=False, limit=1_000_000,
                 Basel 3.1 config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ccf == 0.40.

        References:
            PRA PS1/26 Art. 111(1) Table A1 Row 5: "other commitments" → 40%.
        """
        # Arrange
        row = _row(p2_33_ccf_results, CONTROL_FAC_REF)

        # Assert
        assert row["ccf"] == pytest.approx(EXPECTED_CCF_CONTROL, abs=1e-6), (
            f"{SCENARIO_ID} CONTROL ({CONTROL_FAC_REF}): "
            f"expected ccf={EXPECTED_CCF_CONTROL} (OC Table A1 Row 5 40%), "
            f"got {row['ccf']:.4f}."
        )

    def test_p2_33_b31_ccf9_control_ead_from_ccf_is_400k(
        self,
        p2_33_ccf_results: pl.DataFrame,
    ) -> None:
        """
        CONTROL: ead_from_ccf == 400_000.00 (1_000_000 × 0.40).

        Regression guard: standard OC path must produce 400k.

        Arrange: facility B31-CCF9-OC-CONTROL, limit=1_000_000,
                 drawn_amount=0, Basel 3.1 config.
        Act:     CCFCalculator.apply_ccf().
        Assert:  ead_from_ccf == 400_000.00.

        References:
            PRA PS1/26 Art. 111(1) Table A1 Row 5: OC CCF = 40%.
        """
        # Arrange
        row = _row(p2_33_ccf_results, CONTROL_FAC_REF)

        # Assert
        assert row["ead_from_ccf"] == pytest.approx(EXPECTED_EAD_FROM_CCF_CONTROL, rel=1e-4), (
            f"{SCENARIO_ID} CONTROL ({CONTROL_FAC_REF}): "
            f"expected ead_from_ccf={EXPECTED_EAD_FROM_CCF_CONTROL:,.2f} "
            f"(1_000_000 × 0.40, Table A1 Row 5), "
            f"got {row['ead_from_ccf']:,.2f}."
        )
