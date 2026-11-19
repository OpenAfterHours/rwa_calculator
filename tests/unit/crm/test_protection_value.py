"""
Unit tests for the Art. 233 valuation of unfunded protection (``protection_value``).

Rule text relied on (PS1/26 Appendix 1, Art. 233; CRR Art. 233 reads the same
for paragraphs 1 and 2):

- 233(1): G is "the amount that the protection provider has undertaken to pay
  in the event of the default or non-payment of the borrower".
- 233(2): "In the case of credit derivatives which do not include as a credit
  event restructuring of the underlying obligation ... (a) where the amount
  that the protection provider has undertaken to pay is not higher than the
  exposure value, the institution shall reduce the value of the credit
  protection calculated under paragraph 1 by 40%; (b) where the amount that the
  protection provider has undertaken to pay is higher than the exposure value,
  the institution shall ensure that the value of the credit protection shall be
  no higher than 60% of the exposure value."
- 233(3): "G* = G (1 - Hfx) where ... G = the value of the credit protection as
  determined by paragraph 1 and 2". (CRR 233(3) names G "the nominal amount";
  the engine applies paragraph 2 first in both regimes, which is the more
  conservative order where they differ.)

E is the exposure value at the CCF=100% basis (``ead_for_crm``,
Art. 235(1)(a)). Every frame here sets ``ead_for_crm`` apart from
``ead_after_collateral`` so a test cannot pass by reading the wrong basis.

References:
    GT-05 / GT-06 (P1.202 / P1.201), GT-02 and GT-01 of the guarantees review.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.crm.guarantees import _resolve_guarantees_multi_level
from rwa_calc.engine.crm.protection_value import attach_shared_cap, value_unfunded_protection
from rwa_calc.rulebook import RulepackV0

_CRR = CalculationConfig.crr(reporting_date=date(2026, 6, 1))
_B31 = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 1))


def _exposures(**eads: float) -> pl.LazyFrame:
    """GBP exposures keyed by reference; ead_after_collateral is half E so it never matches."""
    return pl.LazyFrame(
        {
            "exposure_reference": list(eads),
            "ead_for_crm": list(eads.values()),
            "ead_after_collateral": [e / 2 for e in eads.values()],
            "currency": ["GBP"] * len(eads),
        }
    )


def _guarantees(*overrides: dict[str, Any]) -> pl.LazyFrame:
    base: dict[str, Any] = {
        "guarantee_reference": None,
        "beneficiary_reference": "L1",
        "guarantor": "GUAR",
        "amount_covered": None,
        "percentage_covered": None,
        "protection_type": "guarantee",
        "includes_restructuring": True,
        "currency": "GBP",
    }
    return pl.LazyFrame(
        [{**base, **o} for o in overrides],
        schema_overrides={
            "guarantee_reference": pl.String,
            "amount_covered": pl.Float64,
            "percentage_covered": pl.Float64,
            "includes_restructuring": pl.Boolean,
        },
    )


def _value(
    guarantees: pl.LazyFrame,
    exposures: pl.LazyFrame,
    config: CalculationConfig = _CRR,
) -> pl.DataFrame:
    pack = RulepackV0.from_config(config).pack
    names = exposures.collect_schema().names()
    return (
        value_unfunded_protection(attach_shared_cap(guarantees), exposures, names, pack=pack)
        .sort("beneficiary_reference")
        .collect()
    )


def _cds(**fields: Any) -> dict[str, Any]:
    """A credit derivative that does not include restructuring as a credit event."""
    return {"protection_type": "credit_derivative", "includes_restructuring": False, **fields}


# =============================================================================
# GT-05 / GT-06: Art. 233(2) restructuring exclusion
# =============================================================================


class TestRestructuringExclusion:
    """Paragraph 2 applies to every no-restructuring credit derivative."""

    @pytest.mark.parametrize("config", [_CRR, _B31], ids=["crr", "b31"])
    def test_percentage_cover_takes_the_40_percent_cut(self, config: CalculationConfig) -> None:
        """GT-05: 100% of E = 8 is G = 8 <= E, so 233(2)(a): 8 x 0.6 = 4.8.

        Before the fix the cut keyed on amount_covered only and recognised 8.
        """
        out = _value(_guarantees(_cds(percentage_covered=1.0)), _exposures(L1=8.0), config)

        assert out["amount_covered"][0] == pytest.approx(4.8)
        assert out["guarantee_restructuring_haircut"][0] == pytest.approx(0.40)

    @pytest.mark.parametrize("config", [_CRR, _B31], ids=["crr", "b31"])
    @pytest.mark.parametrize(
        ("notional", "expected"),
        [
            (16.0, 4.8),  # (b): G > E -> no higher than 0.6 x 8
            (8.5, 4.8),  # (b): just above E
            (8.0, 4.8),  # (a) boundary: G = E -> 0.6 x 8
            (6.0, 3.6),  # (a): 0.6 x 6
        ],
    )
    def test_oversized_cds_is_capped_at_60_percent_of_e(
        self, config: CalculationConfig, notional: float, expected: float
    ) -> None:
        """GT-06: 233(2)(b) caps at 0.6 E where G > E; (a) cuts 40% where G <= E.

        Before the fix 16 was cut to 9.6 and left for the cap at E to bring to 8.
        """
        out = _value(_guarantees(_cds(amount_covered=notional)), _exposures(L1=8.0), config)

        assert out["amount_covered"][0] == pytest.approx(expected)

    def test_cds_that_includes_restructuring_is_unchanged(self) -> None:
        out = _value(
            _guarantees(_cds(amount_covered=16.0, includes_restructuring=True)),
            _exposures(L1=8.0),
        )

        assert out["amount_covered"][0] == pytest.approx(16.0)
        assert out["guarantee_restructuring_haircut"][0] == pytest.approx(0.0)

    def test_null_restructuring_flag_is_permissive(self) -> None:
        """A null flag is read as 'includes restructuring' (the loader defaults it)."""
        out = _value(
            _guarantees(_cds(amount_covered=5.0, includes_restructuring=None)),
            _exposures(L1=8.0),
        )

        assert out["amount_covered"][0] == pytest.approx(5.0)

    def test_guarantee_with_restructuring_flag_false_is_unchanged(self) -> None:
        """Paragraph 2 is about credit derivatives only."""
        out = _value(
            _guarantees({"amount_covered": 5.0, "includes_restructuring": False}),
            _exposures(L1=8.0),
        )

        assert out["amount_covered"][0] == pytest.approx(5.0)

    def test_fx_haircut_applies_after_paragraph_2(self) -> None:
        """233(3): G* = (value after paragraph 2) x (1 - 0.08).

        EUR 16 on GBP E = 8: 0.6 x 8 = 4.8, then x 0.92 = 4.416. Applying Hfx
        first (16 x 0.92 = 14.72 > 8, then 0.6 x 8 = 4.8) would recognise more.
        """
        out = _value(_guarantees(_cds(amount_covered=16.0, currency="EUR")), _exposures(L1=8.0))

        assert out["amount_covered"][0] == pytest.approx(4.416)
        assert out["guarantee_fx_haircut"][0] == pytest.approx(0.08)


# =============================================================================
# GT-02: percentage with an amount cap
# =============================================================================


class TestPercentageWithAmountCap:
    """233(1): '50% of the exposure, up to 5' undertakes min(0.5 x E, 5)."""

    @pytest.mark.parametrize(
        ("amount", "percentage", "expected"),
        [
            (5.0, 0.5, 4.0),  # percentage binds: 0.5 x 8 = 4 < 5
            (3.0, 0.5, 3.0),  # amount binds
            (5.0, None, 5.0),  # amount only
            (None, 0.5, 4.0),  # percentage only
        ],
    )
    def test_g_is_the_smaller_undertaking(
        self, amount: float | None, percentage: float | None, expected: float
    ) -> None:
        out = _value(
            _guarantees({"amount_covered": amount, "percentage_covered": percentage}),
            _exposures(L1=8.0),
        )

        assert out["amount_covered"][0] == pytest.approx(expected)

    def test_percentage_column_is_consumed(self) -> None:
        """The split downstream reads one column: G* in amount_covered."""
        out = _value(
            _guarantees({"amount_covered": 5.0, "percentage_covered": 0.5}), _exposures(L1=8.0)
        )

        assert "percentage_covered" not in out.columns


# =============================================================================
# GT-01: one guarantee_reference, one cap
# =============================================================================


class TestSharedCap:
    """Rows sharing a reference share its amount, pro-rata to each row's demand."""

    def test_pool_cap_is_shared_pro_rata(self) -> None:
        """Cap 5 over loans of 8 and 6: 5 x 5/10 = 2.5 each (demand min(G, E) = 5, 5)."""
        out = _value(
            _guarantees(
                {
                    "guarantee_reference": "POOL",
                    "beneficiary_reference": "L1",
                    "amount_covered": 5.0,
                },
                {
                    "guarantee_reference": "POOL",
                    "beneficiary_reference": "L2",
                    "amount_covered": 5.0,
                },
            ),
            _exposures(L1=8.0, L2=6.0),
        )

        assert out["amount_covered"].to_list() == pytest.approx([2.5, 2.5])

    def test_pool_cap_on_percentage_cover(self) -> None:
        """50% up to 5 over loans of 8 and 6: demands 4 and 3 (7 > 5) -> 20/7 and 15/7."""
        rows = [
            {
                "guarantee_reference": "POOL",
                "beneficiary_reference": ref,
                "amount_covered": 5.0,
                "percentage_covered": 0.5,
            }
            for ref in ("L1", "L2")
        ]
        out = _value(_guarantees(*rows), _exposures(L1=8.0, L2=6.0))

        assert out["amount_covered"].to_list() == pytest.approx([20 / 7, 15 / 7])
        assert out["amount_covered"].sum() == pytest.approx(5.0)

    def test_demand_is_capped_at_e(self) -> None:
        """A row cannot claim more of the cap than its own exposure: demands 3 and 6."""
        out = _value(
            _guarantees(
                {
                    "guarantee_reference": "POOL",
                    "beneficiary_reference": "L1",
                    "amount_covered": 8.0,
                },
                {
                    "guarantee_reference": "POOL",
                    "beneficiary_reference": "L2",
                    "amount_covered": 8.0,
                },
            ),
            _exposures(L1=3.0, L2=6.0),
        )

        assert out["amount_covered"].to_list() == pytest.approx([8 * 3 / 9, 8 * 6 / 9])

    def test_cap_that_does_not_bind_leaves_g_unchanged(self) -> None:
        """Cap 10, demands 4 + 3 = 7: nothing to share."""
        rows = [
            {
                "guarantee_reference": "POOL",
                "beneficiary_reference": ref,
                "amount_covered": 10.0,
                "percentage_covered": 0.5,
            }
            for ref in ("L1", "L2")
        ]
        out = _value(_guarantees(*rows), _exposures(L1=8.0, L2=6.0))

        assert out["amount_covered"].to_list() == pytest.approx([4.0, 3.0])

    def test_inconsistent_rows_use_the_largest_amount(self) -> None:
        """Amounts 5 and 4 (CRM028): cap 5 over demands 5 and 4 -> 25/9 and 20/9."""
        out = _value(
            _guarantees(
                {
                    "guarantee_reference": "POOL",
                    "beneficiary_reference": "L1",
                    "amount_covered": 5.0,
                },
                {
                    "guarantee_reference": "POOL",
                    "beneficiary_reference": "L2",
                    "amount_covered": 4.0,
                },
            ),
            _exposures(L1=8.0, L2=6.0),
        )

        assert out["amount_covered"].to_list() == pytest.approx([25 / 9, 20 / 9])

    def test_null_references_are_separate_contracts(self) -> None:
        """No reference, no shared cap: 5 and 5."""
        out = _value(
            _guarantees(
                {"beneficiary_reference": "L1", "amount_covered": 5.0},
                {"beneficiary_reference": "L2", "amount_covered": 5.0},
            ),
            _exposures(L1=8.0, L2=6.0),
        )

        assert out["amount_covered"].to_list() == pytest.approx([5.0, 5.0])

    @pytest.mark.parametrize(
        ("row", "expected"),
        [
            # Percentage only: no amount, so no contract cap - pre-repair 4 + 4 = 8.
            ({"percentage_covered": 0.5}, 4.0),
            # Percentage with a cap of 5: 0.5 x 8 = 4, once - pre-repair 5 (cap-bound).
            ({"percentage_covered": 0.5, "amount_covered": 5.0}, 4.0),
            # CDS notional 16 on E = 8: 233(2)(b) on the one undertaking - pre-repair
            # 4.8 + 4.8 (the split later capped the sum at E = 8).
            (_cds(amount_covered=16.0), 4.8),
        ],
        ids=["percentage", "percentage-with-cap", "oversized-cds"],
    )
    def test_repeated_row_for_one_beneficiary_is_one_undertaking(
        self, row: dict[str, Any], expected: float
    ) -> None:
        """The same contract entered twice for L1 by the same guarantor counts once.

        Art. 233(1): G is "the amount that the protection provider has undertaken
        to pay" - one contract, one undertaking per obligation, however many rows
        state it (CRM028 names the repeat).
        """
        repeated = {"guarantee_reference": "DUP", "beneficiary_reference": "L1", **row}
        out = _value(_guarantees(repeated, repeated), _exposures(L1=8.0))

        assert out["amount_covered"].sum() == pytest.approx(expected)

    def test_repeated_reference_for_different_guarantors_keeps_both_rows(self) -> None:
        """Co-guarantors under one reference are not repeats: both rows share the cap of 5."""
        out = _value(
            _guarantees(
                {"guarantee_reference": "CO", "guarantor": "GUAR", "amount_covered": 5.0},
                {"guarantee_reference": "CO", "guarantor": "GUAR2", "amount_covered": 5.0},
            ),
            _exposures(L1=8.0),
        )

        assert out["amount_covered"].to_list() == pytest.approx([2.5, 2.5])

    def test_shared_cap_precedes_the_restructuring_cut(self) -> None:
        """Paragraph 1 (the contract's G) before paragraph 2: 2.5 x 0.6 = 1.5 each."""
        rows = [
            _cds(guarantee_reference="POOL", beneficiary_reference=ref, amount_covered=5.0)
            for ref in ("L1", "L2")
        ]
        out = _value(_guarantees(*rows), _exposures(L1=8.0, L2=6.0))

        assert out["amount_covered"].to_list() == pytest.approx([1.5, 1.5])


class TestSharedCapAcrossExpansion:
    """The contract's cap is read BEFORE multi-level expansion rescales amount_covered."""

    @staticmethod
    def _expand_and_value(guarantees: pl.LazyFrame) -> pl.DataFrame:
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "counterparty_reference": ["CP001", "CP001"],
                "ead_for_crm": [6.0, 4.0],
                "ead_after_collateral": [6.0, 4.0],
                "currency": ["GBP", "GBP"],
            }
        )
        pack = RulepackV0.from_config(_CRR).pack
        expanded = _resolve_guarantees_multi_level(attach_shared_cap(guarantees), exposures)
        return (
            value_unfunded_protection(
                expanded, exposures, exposures.collect_schema().names(), pack=pack
            )
            .sort("beneficiary_reference")
            .collect()
        )

    def test_counterparty_level_guarantee_keeps_its_full_amount(self) -> None:
        """10 over exposures of 6 and 4 expands to 6 and 4; the cap of 10 does not bind."""
        out = self._expand_and_value(
            _guarantees(
                {
                    "guarantee_reference": "GX",
                    "beneficiary_type": "counterparty",
                    "beneficiary_reference": "CP001",
                    "amount_covered": 10.0,
                }
            )
        )

        assert out["amount_covered"].to_list() == pytest.approx([6.0, 4.0])

    def test_same_contract_at_two_levels_is_not_double_counted(self) -> None:
        """The same 10 entered at counterparty AND loan level recognises at most 10 in total.

        Recognised cover is min(G, E) per exposure (Art. 235(1)(a): Eg = min{GA, E};
        the split caps G at E). On EXP001 the loan-level row (G = 10) and the
        expanded share (6) restate one undertaking, so only the larger is used:
        min(10, 6) + min(4, 4) = 10. Summing G alone would read 14 here.
        """
        exposure_value = {"EXP001": 6.0, "EXP002": 4.0}
        out = self._expand_and_value(
            _guarantees(
                {
                    "guarantee_reference": "GX",
                    "beneficiary_type": "counterparty",
                    "beneficiary_reference": "CP001",
                    "amount_covered": 10.0,
                },
                {
                    "guarantee_reference": "GX",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "EXP001",
                    "amount_covered": 10.0,
                },
            )
        )
        per_exposure = out.group_by("beneficiary_reference").agg(pl.col("amount_covered").sum())
        recognised = sum(
            min(g, exposure_value[ref])
            for ref, g in zip(
                per_exposure["beneficiary_reference"], per_exposure["amount_covered"], strict=True
            )
        )

        assert recognised == pytest.approx(10.0)
