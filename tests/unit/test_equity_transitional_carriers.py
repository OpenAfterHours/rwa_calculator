"""
The three equity-transitional carriers the equity calculator writes.

``equity_transitional_approach``, ``equity_higher_risk`` and
``risk_weight_pre_equity_transitional`` tell the reporting layer which legs had
their weight set under PS1/26 Credit Risk: General Provisions rules 4.1-4.3 (the
Standardised Transitional Approach for equities), whether each is higher risk
equity, and the Article 133 weight the leg would otherwise carry. OF 07.00
needs all three: Annex II p.95 says such exposures "shall be reported against
the risk weights set out in Article 133 [...] disregarding the transitional
provisions. However, the RWEA shall still reflect the transitional provisions",
and memorandum rows 0371 / 0372 hold "all equity exposures to which the
Standardised Transitional Approach for equities applies" (p.97), split by
higher risk (0371, rules 4.1 and 4.3) and other (0372, rules 4.1 and 4.2).

The contract pinned here:

- the label is ``"sa_transitional"`` ONLY on a leg whose weight rule 4.2 or 4.3
  set: never on subordinated debt (Art. 133(5)), a CIU (Arts. 132-132C), the
  central-bank type, an Art. 133(6)(c) significant investment, a firm that had
  IRB permission on 31 December 2026 (rule 4.1), or a reporting date outside
  1 January 2027 - 31 December 2029 (Annex II p.97: "Institutions shall not
  report values in these rows for reporting dates of 1 January 2030 or later");
- ``equity_higher_risk`` is true exactly when the Article 133 weight the leg was
  assigned is the Art. 133(4) rung — the same predicate that assigned it, never
  a second one — and null wherever the label is null;
- ``risk_weight_pre_equity_transitional`` is that Article 133 weight, null
  wherever the label is null;
- under Basel 3.1 all three are always emitted (typed nulls when nothing is in
  scope); under CRR, which has no transitional, none is.

Before this was written the calculator stamped ``"sa_transitional"`` on every
row (subordinated debt, CIUs, IRB firms, 2030) and derived ``equity_higher_risk``
from a narrower predicate than the one that assigned 400%, so it read False on
equity weighted at 400%. This module replaces
``tests/unit/reporting/corep/test_cross.py::TestEquityTransitionalColumns``,
which called the private floor method on a hand-built frame whose
``risk_weight`` contradicted its ``is_speculative`` flag and so could only pin
the second predicate. Every case here goes through ``calculate_branch``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import EquityType, PermissionMode
from rwa_calc.engine.equity.calculator import EquityCalculator
from rwa_calc.rulebook.resolve import resolve

# The Art. 133(4) rung, read from the pack the engine weights with.
_HIGHER_RISK_RUNG = float(
    resolve("b31", date(2027, 1, 1))
    .lookup("equity_sa_risk_weights")
    .entries[EquityType.SPECULATIVE]
)

_CARRIERS = (
    "equity_transitional_approach",
    "equity_higher_risk",
    "risk_weight_pre_equity_transitional",
)
_CARRIER_DTYPES = {
    "equity_transitional_approach": pl.String,
    "equity_higher_risk": pl.Boolean,
    "risk_weight_pre_equity_transitional": pl.Float64,
}

_IN_SCOPE: dict[str, dict[str, Any]] = {
    "listed": {"equity_type": "listed", "is_exchange_traded": True},
    "government_supported": {"equity_type": "government_supported"},
    "unlisted_age_unknown": {"equity_type": "other"},
    "speculative_flag": {"equity_type": "other", "is_speculative": True},
    # P1.207: the flag cannot contradict a listing -- standard, not higher risk.
    "speculative_flag_on_listed": {"equity_type": "listed", "is_speculative": True},
    "speculative_type_without_flag": {"equity_type": "speculative"},
    "unlisted_age_2": {"equity_type": "other", "business_age_years": 2.0},
    "private_equity_age_unknown": {"equity_type": "private_equity"},
    "private_equity_age_8": {"equity_type": "private_equity", "business_age_years": 8.0},
}

_OUT_OF_SCOPE: dict[str, dict[str, Any]] = {
    "subordinated_debt": {"equity_type": "subordinated_debt"},
    "central_bank": {"equity_type": "central_bank"},
    "ciu_fallback": {"equity_type": "ciu", "ciu_approach": "fallback"},
    "ciu_mandate": {"equity_type": "ciu", "ciu_approach": "mandate_based", "ciu_mandate_rw": 0.75},
    "significant_investment": {
        "equity_type": "listed",
        "is_exchange_traded": True,
        "is_significant_investment": True,
    },
}

_SCHEMA: dict[str, pl.DataType] = {
    "exposure_reference": pl.String(),
    "ead_final": pl.Float64(),
    "equity_type": pl.String(),
    "is_speculative": pl.Boolean(),
    "is_exchange_traded": pl.Boolean(),
    "is_significant_investment": pl.Boolean(),
    "business_age_years": pl.Float64(),
    "ciu_approach": pl.String(),
    "ciu_mandate_rw": pl.Float64(),
}


def _run(config: CalculationConfig) -> dict[str, dict[str, Any]]:
    rows = [
        {
            "exposure_reference": ref,
            "ead_final": 1_000.0,
            "is_speculative": False,
            "is_exchange_traded": False,
            "is_significant_investment": False,
            **spec,
        }
        for ref, spec in {**_IN_SCOPE, **_OUT_OF_SCOPE}.items()
    ]
    frame = pl.DataFrame(rows, schema=_SCHEMA).lazy()
    out = EquityCalculator().calculate_branch(frame, config).collect()
    return {r["exposure_reference"]: r for r in out.to_dicts()}


def _b31(on: date, permission_mode: PermissionMode = PermissionMode.STANDARDISED) -> dict:
    config = CalculationConfig.basel_3_1(reporting_date=on, permission_mode=permission_mode)
    return _run(config)


class TestLabelScope:
    """The label marks exactly the legs whose weight rule 4.2 or 4.3 set."""

    @pytest.mark.parametrize("ref", sorted(_IN_SCOPE))
    def test_in_scope_leg_is_labelled(self, ref: str) -> None:
        # Act
        row = _b31(date(2027, 6, 30))[ref]

        # Assert
        assert row["equity_transitional_approach"] == "sa_transitional"

    @pytest.mark.parametrize("ref", sorted(_OUT_OF_SCOPE))
    def test_out_of_scope_leg_carries_no_carrier(self, ref: str) -> None:
        # Act
        row = _b31(date(2027, 6, 30))[ref]

        # Assert
        assert {c: row[c] for c in _CARRIERS} == dict.fromkeys(_CARRIERS)

    def test_last_day_of_the_period_is_labelled(self) -> None:
        # Act
        row = _b31(date(2029, 12, 31))["listed"]

        # Assert
        assert row["equity_transitional_approach"] == "sa_transitional"

    def test_end_state_date_carries_no_label_but_keeps_the_columns(self) -> None:
        # Act
        rows = _b31(date(2030, 1, 1))

        # Assert
        assert all(set(_CARRIERS) <= set(row) for row in rows.values())
        assert {row["equity_transitional_approach"] for row in rows.values()} == {None}

    def test_firm_with_irb_permission_is_never_labelled_sa_transitional(self) -> None:
        # Act
        rows = _b31(date(2027, 6, 30), PermissionMode.IRB)

        # Assert
        assert {row["equity_transitional_approach"] for row in rows.values()} == {None}


class TestHigherRiskFollowsTheAssignedWeight:
    """``equity_higher_risk`` is the predicate that assigned the Art. 133(4) rung."""

    @pytest.mark.parametrize("ref", sorted(_IN_SCOPE))
    def test_flag_equals_whether_the_article_133_weight_is_the_400_percent_rung(
        self, ref: str
    ) -> None:
        # Act
        row = _b31(date(2027, 6, 30))[ref]

        # Assert
        pre = row["risk_weight_pre_equity_transitional"]
        assert pre is not None
        assert row["equity_higher_risk"] is (pre == _HIGHER_RISK_RUNG)

    def test_both_kinds_of_leg_are_present(self) -> None:
        # Adequacy: the invariant above is vacuous unless both values occur.
        rows = _b31(date(2027, 6, 30))
        flags = {rows[ref]["equity_higher_risk"] for ref in _IN_SCOPE}
        assert flags == {True, False}


class TestPreTransitionalWeight:
    """``risk_weight_pre_equity_transitional`` is the Article 133 weight."""

    def test_standard_leg_records_250_percent(self) -> None:
        # Act
        row = _b31(date(2028, 6, 30))["listed"]

        # Assert
        assert row["risk_weight_pre_equity_transitional"] == pytest.approx(2.50)
        assert row["risk_weight"] == pytest.approx(1.90)

    def test_higher_risk_leg_records_400_percent(self) -> None:
        # Act
        row = _b31(date(2028, 6, 30))["unlisted_age_2"]

        # Assert
        assert row["risk_weight_pre_equity_transitional"] == pytest.approx(4.00)
        assert row["risk_weight"] == pytest.approx(2.80)


class TestCarrierPresenceByRegime:
    """Basel 3.1 always emits the carriers, typed; CRR has no transitional to carry."""

    @pytest.mark.parametrize("on", [date(2027, 6, 30), date(2030, 1, 1)], ids=str)
    def test_basel_3_1_emits_typed_carriers(self, on: date) -> None:
        # Arrange
        config = CalculationConfig.basel_3_1(reporting_date=on)
        frame = pl.DataFrame(
            {"exposure_reference": ["X"], "ead_final": [1.0], "equity_type": ["subordinated_debt"]}
        ).lazy()

        # Act
        schema = EquityCalculator().calculate_branch(frame, config).collect_schema()

        # Assert
        assert {c: schema[c] for c in _CARRIERS} == _CARRIER_DTYPES

    def test_crr_emits_no_carrier(self) -> None:
        # Arrange
        config = CalculationConfig.crr(reporting_date=date(2026, 6, 30))
        frame = pl.DataFrame(
            {"exposure_reference": ["X"], "ead_final": [1.0], "equity_type": ["listed"]}
        ).lazy()

        # Act
        names = EquityCalculator().calculate_branch(frame, config).collect_schema().names()

        # Assert
        assert not set(_CARRIERS) & set(names)
