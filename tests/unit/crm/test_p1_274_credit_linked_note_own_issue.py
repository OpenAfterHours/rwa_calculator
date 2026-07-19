"""
P1.274 — CRR/PS1-26 Art. 218: a credit-linked note is treated as cash collateral
only when it is issued by the LENDING institution itself.

Why this matters:
    Art. 218 grants cash-collateral treatment to investments in credit-linked
    notes ISSUED BY THE LENDING INSTITUTION (to the extent of cash funding),
    provided the embedded credit default swap qualifies as eligible unfunded
    protection. A CLN issued by a THIRD PARTY is not covered by Art. 218: its
    value is materially correlated with the reference entity (typically the
    obligor — Art. 194(4) wrong-way risk), so it is not clean cash collateral.

    The engine previously mapped every ``credit_linked_note`` row to cash (0%
    haircut, full EAD/LGD* offset) with no issuer check, so a third-party CLN
    received full own-issue cash treatment (anti-conservative). The fix gates the
    cash treatment on an ``is_own_issued_cln`` attestation; a CLN that is not
    attested own-issued (False or null) is ineligible funded protection — its
    value is zeroed and ``is_eligible_financial_collateral`` cleared — mirroring
    the P1.271 non-main-index-equity eligibility gate.

References:
    CRR Art. 218 / PS1-26 Art. 218 (retained): own-issued CLN → cash collateral.
    CRR/PS1-26 Art. 194(4): funded protection ineligible when materially
        positively correlated with the obligor (a third-party CLN's reference).
    IMPLEMENTATION_PLAN.md: P1.274.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.crm.haircuts import (
    HaircutCalculator,
    credit_linked_note_ineligible_expr,
)

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

_REPORTING_DATE = date(2025, 12, 31)


def _build_cln_collateral(
    *,
    is_own_issued_cln: bool | None,
    market_value: float = 100_000.0,
) -> pl.LazyFrame:
    """Build a minimal credit-linked-note collateral LazyFrame."""
    schema: dict[str, PolarsDataType] = {
        "collateral_reference": pl.String,
        "collateral_type": pl.String,
        "currency": pl.String,
        "exposure_currency": pl.String,
        "maturity_date": pl.Date,
        "market_value": pl.Float64,
        "nominal_value": pl.Float64,
        "pledge_percentage": pl.Float64,
        "beneficiary_type": pl.String,
        "beneficiary_reference": pl.String,
        "issuer_cqs": pl.Int8,
        "issuer_type": pl.String,
        "residual_maturity_years": pl.Float64,
        "original_maturity_years": pl.Float64,
        "is_eligible_financial_collateral": pl.Boolean,
        "is_eligible_irb_collateral": pl.Boolean,
        "is_own_issued_cln": pl.Boolean,
        "valuation_date": pl.Date,
        "valuation_type": pl.String,
        "liquidation_period_days": pl.Int32,
        "qualifies_for_zero_haircut": pl.Boolean,
    }
    return pl.LazyFrame(
        {
            "collateral_reference": ["CLN1"],
            "collateral_type": ["credit_linked_note"],
            "currency": ["GBP"],
            "exposure_currency": ["GBP"],
            "maturity_date": [None],
            "market_value": [market_value],
            "nominal_value": [market_value],
            "pledge_percentage": [None],
            "beneficiary_type": ["loan"],
            "beneficiary_reference": ["LOAN1"],
            "issuer_cqs": [None],
            "issuer_type": ["institution"],
            "residual_maturity_years": [None],
            "original_maturity_years": [None],
            "is_eligible_financial_collateral": [True],
            "is_eligible_irb_collateral": [True],
            "is_own_issued_cln": [is_own_issued_cln],
            "valuation_date": [_REPORTING_DATE],
            "valuation_type": ["market"],
            "liquidation_period_days": [10],
            "qualifies_for_zero_haircut": [None],
        },
        schema=schema,
    )


def _apply(collateral: pl.LazyFrame, *, is_basel_3_1: bool = False) -> dict:
    calc = HaircutCalculator()
    config = (
        CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE)
        if is_basel_3_1
        else CalculationConfig.crr(reporting_date=_REPORTING_DATE)
    )
    return calc.apply_haircuts(collateral, config).collect().to_dicts()[0]


class TestCreditLinkedNoteOwnIssueGate:
    """Art. 218: only an own-issued CLN earns cash-collateral treatment."""

    def test_own_issued_cln_gets_cash_treatment_crr(self) -> None:
        """is_own_issued_cln=True → cash 0% haircut, full value retained (CRR)."""
        row = _apply(_build_cln_collateral(is_own_issued_cln=True))
        assert row["collateral_haircut"] == pytest.approx(0.0)
        assert row["value_after_haircut"] == pytest.approx(100_000.0)
        assert row["is_eligible_financial_collateral"] is True

    def test_own_issued_cln_gets_cash_treatment_b31(self) -> None:
        """is_own_issued_cln=True → cash 0% haircut, full value retained (B31)."""
        row = _apply(_build_cln_collateral(is_own_issued_cln=True), is_basel_3_1=True)
        assert row["value_after_haircut"] == pytest.approx(100_000.0)
        assert row["is_eligible_financial_collateral"] is True

    def test_null_attestation_cln_is_ineligible_crr(self) -> None:
        """LOAD-BEARING: null is_own_issued_cln → value zeroed, eligibility cleared."""
        row = _apply(_build_cln_collateral(is_own_issued_cln=None))
        assert row["value_after_haircut"] == pytest.approx(0.0)
        assert row["is_eligible_financial_collateral"] is False

    def test_explicit_third_party_cln_is_ineligible_crr(self) -> None:
        """is_own_issued_cln=False → third-party CLN zeroed (CRR)."""
        row = _apply(_build_cln_collateral(is_own_issued_cln=False))
        assert row["value_after_haircut"] == pytest.approx(0.0)
        assert row["is_eligible_financial_collateral"] is False

    def test_third_party_cln_is_ineligible_b31(self) -> None:
        """Art. 218 is regime-identical: third-party CLN zeroed under Basel 3.1 too."""
        row = _apply(_build_cln_collateral(is_own_issued_cln=None), is_basel_3_1=True)
        assert row["value_after_haircut"] == pytest.approx(0.0)
        assert row["is_eligible_financial_collateral"] is False


class TestCreditLinkedNoteIneligibleExpr:
    """The shared predicate driving the value-zeroing gate."""

    def test_predicate_fires_for_non_own_issued_cln(self) -> None:
        df = pl.DataFrame(
            {
                "collateral_type": ["credit_linked_note", "credit_linked_note", "cln", "cash"],
                "is_own_issued_cln": [None, False, None, None],
            }
        ).lazy()
        gate = credit_linked_note_ineligible_expr(df.collect_schema().names())
        result = df.with_columns(gate.alias("_ineligible")).collect()
        # CLN rows without an own-issue attestation are ineligible; cash is not.
        assert result["_ineligible"].to_list() == [True, True, False, False]

    def test_predicate_false_for_own_issued_cln(self) -> None:
        df = pl.DataFrame(
            {"collateral_type": ["credit_linked_note"], "is_own_issued_cln": [True]}
        ).lazy()
        gate = credit_linked_note_ineligible_expr(df.collect_schema().names())
        assert df.with_columns(gate.alias("_x")).collect()["_x"].to_list() == [False]

    def test_predicate_noop_when_column_absent(self) -> None:
        """Backward compatibility: no is_own_issued_cln column → predicate is a no-op."""
        df = pl.DataFrame({"collateral_type": ["credit_linked_note"]}).lazy()
        gate = credit_linked_note_ineligible_expr(df.collect_schema().names())
        assert df.with_columns(gate.alias("_x")).collect()["_x"].to_list() == [False]
