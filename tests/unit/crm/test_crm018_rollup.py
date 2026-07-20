"""
CRM018 rollup: one per-cause count warning, not one warning per gated row.

Why this matters:
    The P1.271 listing gate (CRR/PS1-26 Art. 197(1)(f)/198(1)(a)) rules equity
    collateral with unknown index membership / listing ineligible. On real
    portfolios that is thousands of rows; emitting one CRM018 per row floods
    the error channel (13k+ warnings at 100k-exposure scale) and turned the
    re_split stage's error dedup quadratic (~11s of a ~20s run). CRM018 now
    rolls up to a single count-carrying warning per run, following the
    splitter's RE002-RE004 idiom.

References:
    CRR Art. 197(1)(f): main-index equities eligible under all methods.
    CRR Art. 198(1)(a): non-main-index equities eligible only if listed.
"""

from __future__ import annotations

import polars as pl

from rwa_calc.contracts.errors import (
    ERROR_NON_MAIN_INDEX_EQUITY_INELIGIBLE,
    CalculationError,
    ErrorSeverity,
)
from rwa_calc.engine.crm.collateral import _record_non_main_index_equity_ineligible


def _collateral_frame(
    collateral_types: list[str],
    is_main_index: list[bool | None],
    is_listed: list[bool | None],
) -> pl.LazyFrame:
    """Minimal post-haircut collateral frame carrying the gate's signal columns."""
    n = len(collateral_types)
    return pl.LazyFrame(
        {
            "collateral_reference": [f"COLL{i}" for i in range(n)],
            "beneficiary_reference": [f"LOAN{i}" for i in range(n)],
            "collateral_type": collateral_types,
            "is_main_index": is_main_index,
            "is_listed": is_listed,
        },
        schema={
            "collateral_reference": pl.String,
            "beneficiary_reference": pl.String,
            "collateral_type": pl.String,
            "is_main_index": pl.Boolean,
            "is_listed": pl.Boolean,
        },
    )


class TestCrm018RollsUpToOneWarning:
    """CRM018 is one count-carrying warning per run, per the RE002 idiom."""

    def test_multiple_gated_rows_emit_single_warning(self) -> None:
        # Arrange: 3 gated equities, 1 main-index equity, 1 bond (both ungated).
        lf = _collateral_frame(
            collateral_types=["equity", "equity", "equity", "equity", "corp_bond"],
            is_main_index=[None, False, None, True, None],
            is_listed=[None, None, False, None, None],
        )
        errors: list[CalculationError] = []

        # Act
        _record_non_main_index_equity_ineligible(lf, errors)

        # Assert: exactly one rolled-up CRM018 carrying the gated-row count.
        assert len(errors) == 1
        warning = errors[0]
        assert warning.code == ERROR_NON_MAIN_INDEX_EQUITY_INELIGIBLE
        assert warning.severity == ErrorSeverity.WARNING
        assert "3" in warning.message
        assert warning.regulatory_reference == "CRR/PS1-26 Art. 197(1)(f)/198(1)(a)"

    def test_no_gated_rows_emit_nothing(self) -> None:
        # Arrange: main-index and listed equities plus a bond — nothing gated.
        lf = _collateral_frame(
            collateral_types=["equity", "equity", "corp_bond"],
            is_main_index=[True, False, None],
            is_listed=[None, True, None],
        )
        errors: list[CalculationError] = []

        # Act
        _record_non_main_index_equity_ineligible(lf, errors)

        # Assert
        assert errors == []

    def test_missing_signal_columns_is_a_no_op(self) -> None:
        # Arrange: legacy frame without is_main_index / is_listed — gate disabled.
        lf = pl.LazyFrame(
            {
                "collateral_reference": ["COLL0"],
                "beneficiary_reference": ["LOAN0"],
                "collateral_type": ["equity"],
            }
        )
        errors: list[CalculationError] = []

        # Act
        _record_non_main_index_equity_ineligible(lf, errors)

        # Assert
        assert errors == []
