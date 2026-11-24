"""
Unit tests for the unfunded-protection eligibility screen (``protection_screen``).

The screen runs on the raw guarantee rows, before multi-level expansion, and
drops protection the risk-weight substitution method may not use. Each test
names the rule it relies on, quoted from the text:

- PS1/26 Art. 234(1) (CRR Art. 234 to the same effect): "Where an institution
  transfers a part of the risk of a loan in one or more tranches, the
  institution shall comply with the requirements set out in Chapter 5 of
  Title II of Part Three of CRR."
- PS1/26 Art. 235(2) (CRR Art. 235(2) to the same effect): "Where the protected
  amount (GA) is less than the exposure (E), the institution may apply the
  formula specified in paragraphs 1 and 1A only where the protected and
  unprotected parts of the exposure are of equal seniority."
- CRR / PS1/26 Art. 215(1)(b): "the guarantee is an explicitly documented
  obligation assumed by the guarantor".
- CRR / PS1/26 Art. 233(1): G is "the amount that the protection provider has
  undertaken to pay" — one contract, one undertaking.

References:
    GT-03 (CRM027), GT-07 (CRM029, CRM030), GT-01 (CRM028) of the guarantees review.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import (
    ERROR_GUARANTEE_REFERENCE_INCONSISTENT,
    ERROR_INELIGIBLE_UNFUNDED_PROTECTION,
    ERROR_NOT_ELIGIBLE_PROTECTION_TYPE,
    ERROR_PROTECTION_TYPE_MISMATCH,
    ERROR_TRANCHED_PROTECTION_NOT_RECOGNISED,
    CalculationError,
)
from rwa_calc.engine.crm.protection_screen import screen_unfunded_protection
from rwa_calc.rulebook import RulepackV0

_CRR = CalculationConfig.crr(reporting_date=date(2026, 6, 1))
_B31 = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 1))


def _rows(*overrides: dict[str, Any]) -> pl.LazyFrame:
    """Raw guarantee rows: one per override, on a plain 5-unit guarantee of L1."""
    base: dict[str, Any] = {
        "guarantee_reference": "G1",
        "guarantee_type": "guarantee",
        "guarantor": "GUAR",
        "beneficiary_type": "loan",
        "beneficiary_reference": "L1",
        "amount_covered": 5.0,
        "percentage_covered": None,
        "protection_type": "guarantee",
        "includes_restructuring": True,
        "attachment_amount": None,
        "detachment_amount": None,
    }
    return pl.LazyFrame(
        [{**base, **o} for o in overrides],
        schema_overrides={
            "amount_covered": pl.Float64,
            "percentage_covered": pl.Float64,
            "attachment_amount": pl.Float64,
            "detachment_amount": pl.Float64,
            "protection_type": pl.String,
            "guarantee_type": pl.String,
        },
    )


def _screen(
    guarantees: pl.LazyFrame, config: CalculationConfig = _CRR
) -> tuple[pl.DataFrame, list[CalculationError]]:
    errors: list[CalculationError] = []
    pack = RulepackV0.from_config(config).pack
    kept = screen_unfunded_protection(guarantees, pack, errors).collect()
    return kept, errors


def _codes(errors: list[CalculationError]) -> list[str]:
    return [e.code for e in errors]


# =============================================================================
# GT-03: tranched protection is not recognised (CRM027)
# =============================================================================


class TestTranchedProtection:
    """Art. 234 / 235(2): a band of the loss is not an equal-seniority share."""

    @pytest.mark.parametrize("config", [_CRR, _B31], ids=["crr", "b31"])
    def test_attachment_above_zero_is_dropped_with_crm027(self, config: CalculationConfig) -> None:
        """A mezzanine band [2, 6) is tranched: dropped, one CRM027 naming it."""
        kept, errors = _screen(_rows({"attachment_amount": 2.0, "detachment_amount": 6.0}), config)

        assert kept.height == 0
        assert _codes(errors) == [ERROR_TRANCHED_PROTECTION_NOT_RECOGNISED]
        assert "'G1'" in errors[0].message
        assert errors[0].exposure_reference == "L1"

    def test_detachment_alone_marks_a_first_loss_band(self) -> None:
        """Protection of [0, d) covers the junior band only: still tranched."""
        kept, errors = _screen(_rows({"detachment_amount": 4.0}))

        assert kept.height == 0
        assert _codes(errors) == [ERROR_TRANCHED_PROTECTION_NOT_RECOGNISED]

    @pytest.mark.parametrize("attachment", [None, 0.0], ids=["attachment-null", "attachment-zero"])
    def test_no_band_is_a_pro_rata_share_and_is_kept(self, attachment: float | None) -> None:
        """No detachment and no attachment above zero: equal seniority, kept, no error."""
        kept, errors = _screen(_rows({"attachment_amount": attachment}))

        assert kept.height == 1
        assert errors == []

    def test_tranching_columns_absent_is_not_tranched(self) -> None:
        """An input that omits both columns states no band: kept."""
        guarantees = _rows({}).drop("attachment_amount", "detachment_amount")

        kept, errors = _screen(guarantees)

        assert kept.height == 1
        assert errors == []


# =============================================================================
# GT-07: letters of comfort and keepwells (CRM029); type mismatch (CRM030)
# =============================================================================


class TestGuaranteeType:
    """Art. 215(1)(b): only an explicitly documented obligation to pay is a guarantee."""

    @pytest.mark.parametrize(
        "guarantee_type",
        ["letter_of_comfort", "Letter of Comfort", "comfort-letter", "keepwell", " KEEPWELL "],
    )
    def test_comfort_letters_and_keepwells_are_dropped_with_crm029(
        self, guarantee_type: str
    ) -> None:
        """Spelling is folded (case, spaces, hyphens) before matching."""
        kept, errors = _screen(_rows({"guarantee_type": guarantee_type}))

        assert kept.height == 0
        assert _codes(errors) == [ERROR_NOT_ELIGIBLE_PROTECTION_TYPE]

    @pytest.mark.parametrize(
        "guarantee_type", ["guarantee", "bank_guarantee", "standby_letter_of_credit", None]
    )
    def test_other_guarantee_types_are_kept(self, guarantee_type: str | None) -> None:
        """Free-text types outside the two families are descriptors only."""
        kept, errors = _screen(_rows({"guarantee_type": guarantee_type}))

        assert kept.height == 1
        assert errors == []

    @pytest.mark.parametrize("protection_type", ["guarantee", None])
    def test_credit_derivative_type_overrides_protection_type_with_crm030(
        self, protection_type: str | None
    ) -> None:
        """guarantee_type 'credit_derivative' makes the row a credit derivative."""
        kept, errors = _screen(
            _rows({"guarantee_type": "credit_derivative", "protection_type": protection_type})
        )

        assert kept["protection_type"].to_list() == ["credit_derivative"]
        assert _codes(errors) == [ERROR_PROTECTION_TYPE_MISMATCH]

    def test_consistent_credit_derivative_raises_nothing(self) -> None:
        """Both columns agree: no CRM030."""
        kept, errors = _screen(
            _rows({"guarantee_type": "cds", "protection_type": "credit_derivative"})
        )

        assert kept["protection_type"].to_list() == ["credit_derivative"]
        assert errors == []

    def test_null_protection_type_defaults_to_guarantee(self) -> None:
        """protection_type null and no credit-derivative guarantee_type: 'guarantee'."""
        kept, _ = _screen(_rows({"protection_type": None}))

        assert kept["protection_type"].to_list() == ["guarantee"]

    def test_dropped_row_raises_no_crm030(self) -> None:
        """A tranched CDS is dropped: CRM027 only, no mismatch warning for a row not used."""
        _, errors = _screen(
            _rows({"guarantee_type": "credit_derivative", "attachment_amount": 1.0})
        )

        assert _codes(errors) == [ERROR_TRANCHED_PROTECTION_NOT_RECOGNISED]


# =============================================================================
# Art. 213(1)(c)(i): unilateral cancel / change (CRM012) — moved, regime-gated
# =============================================================================


class TestUnilateralProtection:
    """Cancel limb in both regimes; the change limb is Basel 3.1 only (pack Feature)."""

    @pytest.mark.parametrize("config", [_CRR, _B31], ids=["crr", "b31"])
    def test_cancellable_is_dropped_in_both_regimes(self, config: CalculationConfig) -> None:
        kept, errors = _screen(_rows({"is_unilaterally_cancellable": True}), config)

        assert kept.height == 0
        assert _codes(errors) == [ERROR_INELIGIBLE_UNFUNDED_PROTECTION]

    @pytest.mark.parametrize(
        ("config", "dropped"), [(_CRR, False), (_B31, True)], ids=["crr", "b31"]
    )
    def test_changeable_is_dropped_only_under_basel_31(
        self, config: CalculationConfig, dropped: bool
    ) -> None:
        kept, errors = _screen(_rows({"is_unilaterally_changeable": True}), config)

        assert kept.height == (0 if dropped else 1)
        assert _codes(errors) == ([ERROR_INELIGIBLE_UNFUNDED_PROTECTION] if dropped else [])

    def test_b31_change_limb_message_uses_the_c_i_words(self) -> None:
        """The CRM012 text quotes (c)(i), not the (c)(ii) cost-increase limb."""
        _, errors = _screen(_rows({"is_unilaterally_changeable": True}), _B31)

        assert "in a way that would adversely impact the institution" in errors[0].message
        assert "effective cost" not in errors[0].message


# =============================================================================
# PS1/26 rule 4.11: pre-2027 protection keeps the CRR (c)(i) to 30 June 2028
# =============================================================================


def _b31_on(reporting_date: date) -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=reporting_date)


def _dated(
    inception: date | None, *, cancellable: bool = False, changeable: bool = True
) -> pl.LazyFrame:
    """One raw row with an explicit (possibly null) Date inception."""
    return _rows(
        {
            "is_unilaterally_cancellable": cancellable,
            "is_unilaterally_changeable": changeable,
            "protection_inception_date": inception,
        }
    ).with_columns(pl.col("protection_inception_date").cast(pl.Date))


class TestRule411Transitional:
    """Rule 4.11: "or change" is omitted for protection "entered into prior to
    1 January 2027", "During the period beginning with 1 January 2027 and ending
    with 30 June 2028". Only the change limb is omitted; the cancel limb stays."""

    @pytest.mark.parametrize(
        ("reporting_date", "inception", "kept_rows"),
        [
            (date(2026, 12, 31), date(2026, 6, 1), 0),  # before the window
            (date(2027, 1, 1), date(2026, 6, 1), 1),  # "beginning with" (inclusive)
            (date(2027, 6, 30), date(2026, 6, 1), 1),
            (date(2028, 6, 30), date(2026, 6, 1), 1),  # "ending with" (inclusive)
            (date(2028, 7, 1), date(2026, 6, 1), 0),  # after the window
            (date(2027, 6, 30), date(2026, 12, 31), 1),  # last day "prior to"
            (date(2027, 6, 30), date(2027, 1, 1), 0),  # the cut-off is strict
            (date(2027, 6, 30), date(2027, 2, 1), 0),
            (date(2027, 6, 30), None, 0),  # a missing date is not grandfathered
        ],
        ids=[
            "before-window",
            "window-first-day",
            "inside",
            "window-last-day",
            "after-window",
            "inception-eve",
            "inception-on-cutoff",
            "inception-2027",
            "inception-null-in-window",
        ],
    )
    def test_changeable_only_row_is_kept_only_inside_the_window_when_pre_2027(
        self, reporting_date: date, inception: date | None, kept_rows: int
    ) -> None:
        kept, errors = _screen(_dated(inception), _b31_on(reporting_date))

        assert kept.height == kept_rows
        assert _codes(errors) == ([] if kept_rows else [ERROR_INELIGIBLE_UNFUNDED_PROTECTION])

    def test_cancel_limb_survives_for_pre_2027_protection_in_the_window(self) -> None:
        kept, errors = _screen(
            _dated(date(2026, 6, 1), cancellable=True, changeable=True), _b31_on(date(2027, 6, 30))
        )

        assert kept.height == 0
        assert _codes(errors) == [ERROR_INELIGIBLE_UNFUNDED_PROTECTION]
        assert "4.11" not in errors[0].message

    def test_absent_inception_column_is_not_grandfathered(self) -> None:
        """An input with no inception column at all states no pre-2027 date."""
        guarantees = _rows({"is_unilaterally_changeable": True})
        assert "protection_inception_date" not in guarantees.collect_schema().names()

        kept, errors = _screen(guarantees, _b31_on(date(2027, 6, 30)))

        assert kept.height == 0
        assert _codes(errors) == [ERROR_INELIGIBLE_UNFUNDED_PROTECTION]

    @pytest.mark.parametrize(
        ("inception", "reason"),
        [(None, "is null"), (date(2027, 2, 1), "is not before 2027-01-01")],
        ids=["null", "2027"],
    )
    def test_in_window_drop_says_why_rule_4_11_does_not_apply(
        self, inception: date | None, reason: str
    ) -> None:
        _, errors = _screen(_dated(inception), _b31_on(date(2027, 6, 30)))

        assert "4.11" in errors[0].message
        assert f"protection_inception_date {reason}" in errors[0].message

    def test_out_of_window_drop_does_not_mention_rule_4_11(self) -> None:
        _, errors = _screen(_dated(date(2026, 6, 1)), _b31_on(date(2028, 7, 1)))

        assert "4.11" not in errors[0].message

    def test_crr_keeps_changeable_only_protection_whatever_the_inception(self) -> None:
        kept, errors = _screen(_dated(date(2027, 2, 1)), _CRR)

        assert kept.height == 1
        assert errors == []

    def test_inception_column_is_preserved_on_kept_rows(self) -> None:
        kept, _ = _screen(_dated(date(2026, 6, 1)), _b31_on(date(2027, 6, 30)))

        assert kept.get_column("protection_inception_date").to_list() == [date(2026, 6, 1)]


# =============================================================================
# GT-01: one guarantee_reference is one contract (CRM028)
# =============================================================================


class TestSharedReference:
    """Rows sharing a reference are one undertaking; only inconsistent entry warns."""

    def test_consistent_pool_across_beneficiaries_raises_nothing(self) -> None:
        """The documented pool shape: same reference, same amount, two loans."""
        kept, errors = _screen(
            _rows(
                {"guarantee_reference": "POOL", "beneficiary_reference": "L1"},
                {"guarantee_reference": "POOL", "beneficiary_reference": "L2"},
            )
        )

        assert kept.height == 2
        assert errors == []

    def test_different_amounts_raise_one_crm028(self) -> None:
        """Rows disagree on the cap: one warning naming the reference and the cap used."""
        _, errors = _screen(
            _rows(
                {"guarantee_reference": "POOL", "beneficiary_reference": "L1"},
                {
                    "guarantee_reference": "POOL",
                    "beneficiary_reference": "L2",
                    "amount_covered": 4.0,
                },
            )
        )

        assert _codes(errors) == [ERROR_GUARANTEE_REFERENCE_INCONSISTENT]
        assert "'POOL'" in errors[0].message
        assert "capped at 5.0" in errors[0].message

    def test_repeated_beneficiary_raises_one_crm028(self) -> None:
        """The same contract entered twice on one loan."""
        _, errors = _screen(
            _rows(
                {"guarantee_reference": "DUP", "beneficiary_reference": "L1"},
                {"guarantee_reference": "DUP", "beneficiary_reference": "L1"},
            )
        )

        assert _codes(errors) == [ERROR_GUARANTEE_REFERENCE_INCONSISTENT]
        assert "more than once for the same beneficiary" in errors[0].message

    def test_null_reference_never_groups(self) -> None:
        """Rows with no reference are separate contracts: no CRM028."""
        _, errors = _screen(
            _rows(
                {"guarantee_reference": None, "beneficiary_reference": "L1"},
                {"guarantee_reference": None, "beneficiary_reference": "L1", "amount_covered": 1.0},
            )
        )

        assert errors == []

    def test_screened_out_row_does_not_count_towards_the_reference(self) -> None:
        """A dropped row cannot make the surviving rows look inconsistent."""
        _, errors = _screen(
            _rows(
                {"guarantee_reference": "POOL", "beneficiary_reference": "L1"},
                {
                    "guarantee_reference": "POOL",
                    "beneficiary_reference": "L2",
                    "amount_covered": 4.0,
                    "guarantee_type": "keepwell",
                },
            )
        )

        assert _codes(errors) == [ERROR_NOT_ELIGIBLE_PROTECTION_TYPE]


def test_no_error_channel_screens_without_collecting_messages() -> None:
    """errors=None still drops the ineligible row (the screen is not message-only)."""
    pack = RulepackV0.from_config(_CRR).pack

    kept = screen_unfunded_protection(
        _rows({"attachment_amount": 2.0}, {"guarantee_reference": "G2"}), pack, None
    ).collect()

    assert kept["guarantee_reference"].to_list() == ["G2"]
