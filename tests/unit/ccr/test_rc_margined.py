"""
Unit tests for compute_rc_margined (P8.11).

Pins the expected behaviour of the margined Replacement Cost formula per
CRR Art. 275(2):

    RC = max(V - C, TH + MTA - NICA, 0)

where:
    V   = net mark-to-market value of the netting set (``v_net``)
    C   = net collateral held (``c_net``)
    TH  = margin threshold (``margin_threshold``)
    MTA = minimum transfer amount (``minimum_transfer_amount``)
    NICA = net independent collateral amount (``nica``)

The function must return null for ``is_margined=False`` rows (pass-through).

Fixtures:
    make_rc_margined_frame() — 4-row LazyFrame from rc_margined_builder.py.
    EXPECTED_RC              — dict mapping netting_set_id -> expected float | None.

References:
- CRR Art. 275(2): margined RC = max(V - C, TH + MTA - NICA, 0)
- BCBS CRE52.11: RC formula for margined netting sets
"""

from __future__ import annotations

import polars as pl
import pytest
from tests.fixtures.ccr.rc_margined_builder import (
    EXPECTED_RC,
    NS_A_ID,
    NS_B_ID,
    NS_C_ID,
    NS_D_ID,
    make_rc_margined_frame,
)

# ---------------------------------------------------------------------------
# Subject under test — graceful import: None triggers clean TypeError on call
# ---------------------------------------------------------------------------
try:
    from rwa_calc.engine.ccr.rc import compute_rc_margined
except (ImportError, AttributeError):
    compute_rc_margined = None  # type: ignore[assignment]


# ===========================================================================
# 1. TH + MTA - NICA arm dominates (NS_A)
# ===========================================================================


def test_rc_margined_th_mta_nica_floor_wins() -> None:
    """NS_A: TH+MTA-NICA arm (300_000) dominates V-C arm (150_000).

    Arrange:
        NS_A row: v_net=2_000_000, c_net=1_850_000 -> V-C = 150_000.
                  TH=250_000, MTA=100_000, NICA=50_000 -> TH+MTA-NICA = 300_000.
        RC = max(150_000, 300_000, 0) = 300_000.

    Act: compute_rc_margined(lf).collect(), filter to NS_A.

    Assert: rc_margined == 300_000.0 (abs tolerance 1e-6).

    References: CRR Art. 275(2).
    """
    # Arrange
    lf = make_rc_margined_frame()

    # Act
    result = compute_rc_margined(lf).collect()

    # Assert
    row = result.filter(pl.col("netting_set_id") == NS_A_ID)
    actual = row["rc_margined"][0]
    assert actual == pytest.approx(EXPECTED_RC[NS_A_ID], abs=1e-6), (
        f"NS_A: expected rc_margined={EXPECTED_RC[NS_A_ID]}, got {actual!r}. "
        "TH+MTA-NICA arm (300k) should dominate V-C arm (150k). "
        "CRR Art. 275(2): RC = max(V-C, TH+MTA-NICA, 0)."
    )


# ===========================================================================
# 2. V - C arm dominates (NS_B)
# ===========================================================================


def test_rc_margined_current_exposure_wins() -> None:
    """NS_B: V-C arm (1_100_000) dominates TH+MTA-NICA arm (125_000).

    Arrange:
        NS_B row: v_net=1_500_000, c_net=400_000 -> V-C = 1_100_000.
                  TH=100_000, MTA=50_000, NICA=25_000 -> TH+MTA-NICA = 125_000.
        RC = max(1_100_000, 125_000, 0) = 1_100_000.

    Act: compute_rc_margined(lf).collect(), filter to NS_B.

    Assert: rc_margined == 1_100_000.0 (abs tolerance 1e-6).

    References: CRR Art. 275(2).
    """
    # Arrange
    lf = make_rc_margined_frame()

    # Act
    result = compute_rc_margined(lf).collect()

    # Assert
    row = result.filter(pl.col("netting_set_id") == NS_B_ID)
    actual = row["rc_margined"][0]
    assert actual == pytest.approx(EXPECTED_RC[NS_B_ID], abs=1e-6), (
        f"NS_B: expected rc_margined={EXPECTED_RC[NS_B_ID]}, got {actual!r}. "
        "V-C arm (1.1M) should dominate TH+MTA-NICA arm (125k). "
        "CRR Art. 275(2): RC = max(V-C, TH+MTA-NICA, 0)."
    )


# ===========================================================================
# 3. Zero-floor applies (NS_C)
# ===========================================================================


def test_rc_margined_zero_floor_wins() -> None:
    """NS_C: both arms are negative; zero floor applies.

    Arrange:
        NS_C row: v_net=-500_000, c_net=0 -> V-C = -500_000.
                  TH=50_000, MTA=10_000, NICA=200_000 -> TH+MTA-NICA = -140_000.
        RC = max(-500_000, -140_000, 0) = 0.

    Act: compute_rc_margined(lf).collect(), filter to NS_C.

    Assert: rc_margined == 0.0 (abs tolerance 1e-6).

    References: CRR Art. 275(2): RC is floored at zero.
    """
    # Arrange
    lf = make_rc_margined_frame()

    # Act
    result = compute_rc_margined(lf).collect()

    # Assert
    row = result.filter(pl.col("netting_set_id") == NS_C_ID)
    actual = row["rc_margined"][0]
    assert actual == pytest.approx(EXPECTED_RC[NS_C_ID], abs=1e-6), (
        f"NS_C: expected rc_margined={EXPECTED_RC[NS_C_ID]} (floor), got {actual!r}. "
        "Both arms negative; zero floor must apply. "
        "CRR Art. 275(2): RC = max(V-C, TH+MTA-NICA, 0)."
    )


# ===========================================================================
# 4. Unmargined row returns null (NS_D)
# ===========================================================================


def test_rc_margined_unmargined_row_returns_null() -> None:
    """NS_D: is_margined=False -> rc_margined must be null (pass-through).

    The margined RC formula applies only to ``is_margined=True`` netting sets.
    Unmargined sets are handled by compute_rc_unmargined (Art. 275(1)).

    Arrange:
        NS_D row: is_margined=False; margin parameters all null.

    Act: compute_rc_margined(lf).collect(), filter to NS_D.

    Assert: rc_margined is null.

    References: CRR Art. 275(2) — applies only when CSA/margin agreement present.
    """
    # Arrange
    lf = make_rc_margined_frame()

    # Act
    result = compute_rc_margined(lf).collect()

    # Assert
    row = result.filter(pl.col("netting_set_id") == NS_D_ID)
    actual = row["rc_margined"][0]
    assert actual is None, (
        f"NS_D (is_margined=False): expected rc_margined=None (null), got {actual!r}. "
        "Unmargined rows must be passed through with null rc_margined. "
        "CRR Art. 275(2) formula applies only to margined netting sets."
    )


# ===========================================================================
# 5. Return type — must be LazyFrame (no internal .collect())
# ===========================================================================


def test_rc_margined_returns_lazyframe() -> None:
    """compute_rc_margined must return a pl.LazyFrame without collecting internally.

    The pipeline's LazyFrame-first convention forbids calling .collect() inside
    engine functions — materialisation is the caller's responsibility.

    Arrange: four-row LazyFrame from make_rc_margined_frame().

    Act: call compute_rc_margined without calling .collect().

    Assert: return value is an instance of pl.LazyFrame.

    References: CLAUDE.md § Polars Conventions — LazyFrame first.
    """
    # Arrange
    lf = make_rc_margined_frame()

    # Act
    result = compute_rc_margined(lf)

    # Assert
    assert isinstance(result, pl.LazyFrame), (
        f"compute_rc_margined must return pl.LazyFrame, got {type(result).__name__!r}. "
        "Never call .collect() inside the function; the caller is responsible. "
        "CLAUDE.md § Polars Conventions."
    )


# ===========================================================================
# 6. Exactly one new column added; existing columns preserved
# ===========================================================================


def test_rc_margined_adds_only_one_column() -> None:
    """compute_rc_margined adds exactly the 'rc_margined' column and no others.

    Ensures no accidental side columns are introduced and that the existing
    schema columns from the input frame survive unchanged.

    Arrange: four-row LazyFrame; record input column set.

    Act: compute_rc_margined(lf).collect().

    Assert:
        - 'rc_margined' is present in output columns.
        - output column count == input column count + 1.
        - all input columns are present in output.

    References: CRR Art. 275(2) — function scope: one column only.
    """
    # Arrange
    lf = make_rc_margined_frame()
    input_cols = set(lf.collect_schema().names())

    # Act
    result = compute_rc_margined(lf).collect()
    output_cols = set(result.columns)

    # Assert
    assert "rc_margined" in output_cols, (
        "compute_rc_margined must add a 'rc_margined' column. CRR Art. 275(2)."
    )
    new_cols = output_cols - input_cols
    assert new_cols == {"rc_margined"}, (
        f"compute_rc_margined must add exactly one new column 'rc_margined', "
        f"but found new columns: {new_cols!r}. "
        "No extra columns should be introduced."
    )
    assert input_cols.issubset(output_cols), (
        f"All input columns must be preserved. Missing: {input_cols - output_cols!r}."
    )
