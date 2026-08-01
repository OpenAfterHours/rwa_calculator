"""
Unit tests for the raw-input non-finite scrub (DQ011).

A NaN/±inf in any float column of a raw input table propagates through the
guarantee split and the IRB formula into ``rwa_final`` (surfacing only later as
an aggregator AGG001 error), and under Basel 3.1 poisons the portfolio-level
output floor. The scrub runs at the pipeline entry (``run_with_data``): it
replaces every non-finite float value with null — the documented degradation
path ("typed nulls degrade per downstream null semantics") — and appends one
DQ011 ``CalculationError`` per affected (table, column) so the correction is
visible, never silent.

References:
- rwa_calc.contracts.validation.scrub_non_finite_values (unit under test)
- AGG001/AGG002 aggregator safety net: engine/aggregator/aggregator.py
"""

from __future__ import annotations

import math

import polars as pl
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.errors import ERROR_NON_FINITE_RAW_INPUT, ErrorSeverity
from rwa_calc.contracts.validation import scrub_non_finite_values

NAN = float("nan")
INF = float("inf")


def _bundle(**tables: pl.LazyFrame):
    """Minimal sealed bundle: required tables default to empty sealed frames."""
    return make_raw_bundle(**tables)


class TestScrubReplacesNonFinite:
    """Non-finite float values become null; finite and null values survive."""

    def test_nan_guarantee_amount_nulled_and_flagged(self) -> None:
        """A NaN amount_covered is nulled and flagged as DQ011 naming the table/column."""
        bundle = _bundle(
            guarantees=pl.LazyFrame(
                {
                    "guarantee_reference": ["GTE_BAD", "GTE_OK"],
                    "guarantor": ["CP_G", "CP_G"],
                    "beneficiary_type": ["loan", "loan"],
                    "beneficiary_reference": ["L1", "L2"],
                    "amount_covered": [NAN, 1_000_000.0],
                }
            )
        )

        scrubbed = scrub_non_finite_values(bundle)

        assert scrubbed.guarantees is not None
        amounts = scrubbed.guarantees.collect().get_column("amount_covered")
        assert amounts[0] is None, "NaN amount_covered should be nulled"
        assert amounts[1] == 1_000_000.0, "finite values must survive untouched"

        dq011 = [e for e in scrubbed.errors if e.code == ERROR_NON_FINITE_RAW_INPUT]
        assert len(dq011) == 1
        err = dq011[0]
        assert err.field_name == "amount_covered"
        assert "guarantees" in err.message
        assert "GTE_BAD" in err.message, "sample reference should aid triage"
        assert err.severity == ErrorSeverity.ERROR

    def test_infinities_nulled_nulls_not_counted(self) -> None:
        """±inf are nulled like NaN; pre-existing nulls are not flagged."""
        bundle = _bundle(
            loans=pl.LazyFrame(
                {
                    "loan_reference": ["L_INF", "L_NEGINF", "L_OK", "L_NULL"],
                    "counterparty_reference": ["CP"] * 4,
                    "drawn_amount": [INF, -INF, 5.0, None],
                }
            )
        )

        scrubbed = scrub_non_finite_values(bundle)

        drawn = scrubbed.loans.collect().get_column("drawn_amount")
        assert drawn[0] is None and drawn[1] is None
        assert drawn[2] == 5.0
        assert drawn[3] is None

        dq011 = [e for e in scrubbed.errors if e.code == ERROR_NON_FINITE_RAW_INPUT]
        assert len(dq011) == 1
        assert dq011[0].actual_value == "2", "only the two infinities count — nulls do not"

    def test_one_error_per_affected_column(self) -> None:
        """Each affected (table, column) yields exactly one aggregate DQ011."""
        bundle = _bundle(
            loans=pl.LazyFrame(
                {
                    "loan_reference": ["L1", "L2"],
                    "counterparty_reference": ["CP", "CP"],
                    "drawn_amount": [NAN, 1.0],
                    "effective_maturity": [NAN, NAN],
                }
            )
        )

        scrubbed = scrub_non_finite_values(bundle)

        dq011 = {e.field_name: e for e in scrubbed.errors if e.code == ERROR_NON_FINITE_RAW_INPUT}
        assert set(dq011) == {"drawn_amount", "effective_maturity"}
        assert dq011["drawn_amount"].actual_value == "1"
        assert dq011["effective_maturity"].actual_value == "2"


class TestScrubNoOpPaths:
    """Clean bundles pass through untouched — no rebuild, no errors."""

    def test_clean_bundle_returns_same_object(self) -> None:
        """A bundle with only finite/null floats is returned identically."""
        bundle = _bundle(
            loans=pl.LazyFrame(
                {
                    "loan_reference": ["L1"],
                    "counterparty_reference": ["CP"],
                    "drawn_amount": [100.0],
                }
            )
        )

        assert scrub_non_finite_values(bundle) is bundle

    def test_existing_errors_preserved(self) -> None:
        """Pre-existing loader errors survive alongside the appended DQ011."""
        bundle = _bundle(
            loans=pl.LazyFrame(
                {
                    "loan_reference": ["L1"],
                    "counterparty_reference": ["CP"],
                    "drawn_amount": [NAN],
                }
            )
        )
        prior = list(bundle.errors)

        scrubbed = scrub_non_finite_values(bundle)

        assert prior == scrubbed.errors[: len(prior)]
        assert any(e.code == ERROR_NON_FINITE_RAW_INPUT for e in scrubbed.errors)

    def test_scrubbed_frames_stay_sealed(self) -> None:
        """The rebuilt bundle passes RawDataBundle brand validation and re-scrubs no-op."""
        bundle = _bundle(
            loans=pl.LazyFrame(
                {
                    "loan_reference": ["L1"],
                    "counterparty_reference": ["CP"],
                    "drawn_amount": [NAN],
                }
            )
        )

        # Construction inside scrub_non_finite_values runs __post_init__ brand
        # validation — reaching here without raising proves the reseal.
        scrubbed = scrub_non_finite_values(bundle)
        rescrubbed = scrub_non_finite_values(scrubbed)

        assert rescrubbed is scrubbed, "a scrubbed bundle carries no non-finite values"
        assert not math.isnan(scrubbed.loans.collect().get_column("drawn_amount").fill_null(0.0)[0])
