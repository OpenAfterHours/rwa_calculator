"""
Unit tests — P1.179: get_firb_lgd_table() dispatch by is_basel_3_1 flag.

Today ``get_firb_lgd_table()`` accepts no arguments and always returns CRR
values.  A separate ``get_b31_firb_lgd_table()`` exists for Basel 3.1.  This
naming creates silent dispatch confusion: callers that forget to use the B31
function silently compute with CRR LGDs.

The engine-implementer's task (next wave) is to add an ``is_basel_3_1: bool =
False`` keyword to ``get_firb_lgd_table()`` so that a single entry point
dispatches to the correct table.

References:
    CRR Art. 161 / Art. 230 Table 5: CRR supervisory LGD values
    PRA PS1/26 Art. 161 / BCBS CRE32.9: Basel 3.1 revised supervisory LGDs
"""

from __future__ import annotations

import inspect

import polars as pl
import pytest

from rwa_calc.data.tables.firb_lgd import get_firb_lgd_table

# =============================================================================
# Helper
# =============================================================================


def _filter_receivables_senior(df: pl.DataFrame) -> pl.DataFrame:
    """Return the (receivables, senior) row from a firb-lgd DataFrame."""
    return df.filter(
        (pl.col("collateral_type") == "receivables") & (pl.col("seniority") == "senior")
    )


# =============================================================================
# Test 1 — default invocation returns CRR table
# =============================================================================


class TestDefaultInvocationReturnsCrrTable:
    """get_firb_lgd_table() with no args must return CRR Art. 230 Table 5 values.

    CRR Art. 230 Table 5 sets the receivables senior LGD at 35%.
    """

    def test_default_invocation_returns_crr_table(self) -> None:
        """get_firb_lgd_table() default returns CRR Art. 230 Table 5 (receivables senior = 0.35).

        CRR Art. 230 Table 5: supervisory LGD for exposures secured by
        eligible receivables (senior) = 35 %.

        Arrange: call get_firb_lgd_table() with no arguments.
        Act:     filter to (collateral_type == "receivables") & (seniority == "senior").
        Assert:  lgd == 0.35.
        """
        # Arrange / Act
        df = get_firb_lgd_table()
        row = _filter_receivables_senior(df)

        # Assert
        assert len(row) == 1, f"Expected exactly 1 row, got {len(row)}"
        lgd = row.get_column("lgd")[0]
        assert lgd == pytest.approx(0.35), (
            f"CRR Art. 230 Table 5: expected receivables senior LGD = 0.35, got {lgd}"
        )


# =============================================================================
# Test 2 — is_basel_3_1=True returns B31 table
# =============================================================================


class TestBasel31FlagReturnsB31Table:
    """get_firb_lgd_table(is_basel_3_1=True) must return PRA PS1/26 / CRE32.9 values.

    PRA PS1/26 Art. 161 / BCBS CRE32.9: receivables senior LGD reduced to 20%.
    """

    def test_basel_3_1_flag_returns_b31_table(self) -> None:
        """get_firb_lgd_table(is_basel_3_1=True) returns B31 table (receivables senior = 0.20).

        PRA PS1/26 Art. 161 / BCBS CRE32.9: supervisory LGD for exposures
        secured by eligible receivables (senior) reduced from 35% to 20%.

        Arrange: call get_firb_lgd_table(is_basel_3_1=True).
        Act:     filter to (collateral_type == "receivables") & (seniority == "senior").
        Assert:  lgd == 0.20.
        """
        # Arrange / Act
        try:
            df = get_firb_lgd_table(is_basel_3_1=True)
        except TypeError as e:
            pytest.fail(f"get_firb_lgd_table does not yet accept is_basel_3_1 kwarg: {e}")

        row = _filter_receivables_senior(df)

        # Assert
        assert len(row) == 1, f"Expected exactly 1 row, got {len(row)}"
        lgd = row.get_column("lgd")[0]
        assert lgd == pytest.approx(0.20), (
            f"PRA PS1/26 Art. 161 / CRE32.9: expected receivables senior LGD = 0.20, got {lgd}"
        )


# =============================================================================
# Test 3 — CRR and B31 tables differ on the discriminator row
# =============================================================================


class TestCrrAndB31TablesDifferOnDiscriminator:
    """CRR and B31 tables must diverge on (receivables, senior) lgd by exactly 0.15.

    This is a regression guard against silent dispatch fall-through: if both
    calls return the same table the delta would be 0.0, not 0.15.

    CRR: 0.35 (Art. 230 Table 5)
    B31: 0.20 (PRA PS1/26 Art. 161 / CRE32.9)
    Delta: 0.15
    """

    def test_crr_and_b31_tables_differ_on_discriminator(self) -> None:
        """CRR lgd minus B31 lgd for (receivables, senior) must equal exactly 0.15.

        Arrange: build both DataFrames via get_firb_lgd_table().
        Act:     extract (receivables, senior) lgd from each and subtract.
        Assert:  delta == 0.15 (CRR 35% minus B31 20%).
        """
        # Arrange / Act
        df_crr = get_firb_lgd_table()

        try:
            df_b31 = get_firb_lgd_table(is_basel_3_1=True)
        except TypeError as e:
            pytest.fail(f"get_firb_lgd_table does not yet accept is_basel_3_1 kwarg: {e}")

        lgd_crr = _filter_receivables_senior(df_crr).get_column("lgd")[0]
        lgd_b31 = _filter_receivables_senior(df_b31).get_column("lgd")[0]

        # Assert
        delta = lgd_crr - lgd_b31
        assert delta == pytest.approx(0.15), (
            f"Expected CRR-minus-B31 delta = 0.15, got {delta:.4f}. "
            "If delta == 0.0 then both calls are returning the same table — "
            "silent dispatch fall-through regression."
        )


# =============================================================================
# Test 4 — get_firb_lgd_table has is_basel_3_1 parameter with bool annotation
# =============================================================================


class TestFirbLgdTableSignature:
    """get_firb_lgd_table() must expose is_basel_3_1 with bool annotation and default False.

    Engine code must always supply an explicit framework flag rather than relying
    on an implicit default. This test guards that the parameter exists in the
    function signature so callers can pass it.

    Note: the architect's original test-4 spec called for an AST scan of
    engine call sites; however under Option-A scope the engine call sites use
    the dict helper (get_firb_lgd_table_for_framework), not get_firb_lgd_table
    directly — making the AST scan vacuously true today and trivially passing
    both before and after the fix. We therefore replace the AST scan with a
    signature introspection test that fails today (parameter absent) and passes
    post-fix (parameter present with correct annotation and default).
    """

    def test_engine_call_sites_pass_explicit_framework_flag(self) -> None:
        """get_firb_lgd_table must have is_basel_3_1: bool = False in its signature.

        Engine code must always pass an explicit is_basel_3_1 flag — no
        implicit-default usage.  This test confirms the parameter exists and is
        typed ``bool`` with a default of ``False`` so callers can opt in.

        Arrange: inspect.signature(get_firb_lgd_table).
        Act:     look up the 'is_basel_3_1' parameter.
        Assert:  parameter exists, annotation == bool, default == False.
        """
        # Arrange
        sig = inspect.signature(get_firb_lgd_table)
        params = sig.parameters

        # Assert — parameter must exist
        assert "is_basel_3_1" in params, (
            "get_firb_lgd_table does not have an 'is_basel_3_1' parameter. "
            "Engine-implementer must add: is_basel_3_1: bool = False (P1.179)."
        )

        param = params["is_basel_3_1"]

        # Assert — annotation must be bool
        assert param.annotation is bool, (
            f"'is_basel_3_1' annotation should be bool, got {param.annotation!r}"
        )

        # Assert — default must be False (not inspect.Parameter.empty)
        assert param.default is not inspect.Parameter.empty, (
            "'is_basel_3_1' must have a default value (False) so existing call sites "
            "remain backward-compatible."
        )
        assert param.default is False, (
            f"'is_basel_3_1' default should be False, got {param.default!r}"
        )
