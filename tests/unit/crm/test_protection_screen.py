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
