"""
The Basel 3.1 equity weight chain: who reaches the Art. 133(4) rung, and who never does.

Pipeline position:
    EquityCalculator.calculate_branch -> _apply_b31_equity_weights_sa
        -> _apply_standardised_equity_transitional (rules 4.2 / 4.3, 2027-2029)

What the rule says (ps126app1.pdf, read verbatim):

- Art. 133(3): "An equity exposure shall be assigned a risk weight of 250%, unless
  the exposure is a higher risk equity exposure, in which case the treatment in
  paragraph 4 applies, or is within scope of paragraph 6, in which case the
  treatment referred to in paragraph 6 applies."
- Art. 133(4): "A higher risk equity exposure shall be assigned a risk weight of
  400%, unless the exposure is within the scope of paragraph 6 [...]".
- Art. 133(6)(c): within scope of paragraph 6 are "exposures assigned a risk weight
  of 250% in accordance with paragraph 4 of Own Funds (CRR) Part Article 48".
- Glossary (p.5): "higher risk equity exposure means an equity exposure that is:
  (1) not listed on a recognised exchange; and (2) to an undertaking ('A') whose
  business has existed for a period of less than five years [...]". There is no
  speculative tier and no government-supported carve-out.
- Art. 112(2) / Table A2: an exposure meeting two classes takes the higher row;
  row (2), CIUs (Arts. 132-132C), sits above row (3), equity (Art. 133).
- Rules 4.2 / 4.3 (pp.20-21): equity "that [is] not higher risk equity exposures
  or within the scope of paragraph 6" 160% in 2027; higher risk 220% in 2027.

What this module pins, one leg per test so each can fail on its own:

- P1.207. The ``is_speculative`` flag and the ``speculative`` type are the firm's
  assertion that the Glossary test holds. They may supply a fact the row does
  not evidence, never contradict one it does: a leg that is LISTED
  (``is_exchange_traded`` or ``equity_type`` listed / exchange_traded) or whose
  business age is evidenced at five years or more is not higher risk, flag or
  no flag. A listed-type leg is listed for the Glossary limb as well. Five
  years exactly is not "less than five years": flagged, speculative-type,
  unflagged and private-equity legs aged 5.0 all take the standard rung.
- P1.393(a). A CIU takes its Art. 132-132C weight even when flagged speculative.
- P1.393(b). An ``is_significant_investment`` leg (Art. 133(6)(c)) takes 250%
  on every date, never the 400% rung and never a rules 4.2 / 4.3 weight;
  subordinated debt keeps its Art. 133(5) 150%.
- P1.393(c). Government-supported equity has no exemption from the Glossary
  test: unlisted with an evidenced business age under five years is higher risk.
  Unknown age stays standard (the non-private-equity route).
- CRR has no higher-risk tier; the same legs keep their CRR weights.

References:
- PS1/26 Art. 133(3), (4), (6)(c); Glossary "higher risk equity exposure"
- PS1/26 Art. 112(2) Table A2; Art. 132(2)
- PS1/26 Credit Risk: General Provisions rules 4.1-4.3
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.equity.calculator import EquityCalculator

_END_STATE = date(2031, 6, 30)
_TRANSITIONAL_2027 = date(2027, 6, 30)

#: Art. 133(3) / (4) weights, and rules 4.2(1) / 4.3(1) for 2027.
_WEIGHTS: dict[date, dict[str, float]] = {
    _END_STATE: {"standard": 2.50, "higher_risk": 4.00},
    _TRANSITIONAL_2027: {"standard": 1.60, "higher_risk": 2.20},
}
_ARTICLE_133 = _WEIGHTS[_END_STATE]

# ---------------------------------------------------------------------------
# The legs. Each in-scope leg names its Art. 133 rung; each out-of-scope leg
# its fixed weight (rules 4.2 / 4.3 never reach it).
# ---------------------------------------------------------------------------

#: P1.207: the flag or type contradicted by the row's own evidence. 400% at HEAD.
_FLAG_DEFEATED: dict[str, dict[str, Any]] = {
    "flag_exchange_traded": {
        "equity_type": "other",
        "is_speculative": True,
        "is_exchange_traded": True,
    },
    "flag_aged_10": {"equity_type": "other", "is_speculative": True, "business_age_years": 10.0},
    "speculative_type_exchange_traded": {"equity_type": "speculative", "is_exchange_traded": True},
    "speculative_type_aged_10": {"equity_type": "speculative", "business_age_years": 10.0},
    "listed_type_flag": {"equity_type": "listed", "is_speculative": True},
    "listed_type_age_2": {"equity_type": "listed", "business_age_years": 2.0},
    "exchange_traded_type_age_2": {"equity_type": "exchange_traded", "business_age_years": 2.0},
    "private_equity_flag_aged_10": {
        "equity_type": "private_equity",
        "is_speculative": True,
        "business_age_years": 10.0,
    },
    # The Glossary boundary: "less than five years", so exactly 5.0 is not young.
    "flag_aged_exactly_5": {
        "equity_type": "other",
        "is_speculative": True,
        "business_age_years": 5.0,
    },
    "speculative_type_aged_exactly_5": {"equity_type": "speculative", "business_age_years": 5.0},
}

#: Higher risk before and after the fix: the flag supplies a fact nothing contradicts.
_HIGHER_RISK_KEPT: dict[str, dict[str, Any]] = {
    "flag_age_unknown": {"equity_type": "other", "is_speculative": True},
    "flag_age_4": {"equity_type": "other", "is_speculative": True, "business_age_years": 4.0},
    "speculative_type_age_unknown": {"equity_type": "speculative"},
    "unlisted_age_2": {"equity_type": "other", "business_age_years": 2.0},
    "private_equity_age_unknown": {"equity_type": "private_equity"},
}

#: Standard before and after the fix.
_STANDARD_KEPT: dict[str, dict[str, Any]] = {
    "listed": {"equity_type": "listed", "is_exchange_traded": True},
    "unlisted_age_unknown": {"equity_type": "other"},
    "government_supported_age_unknown": {"equity_type": "government_supported"},
    "government_supported_aged_7": {
        "equity_type": "government_supported",
        "business_age_years": 7.0,
    },
    "government_supported_listed_age_2": {
        "equity_type": "government_supported",
        "is_exchange_traded": True,
        "business_age_years": 2.0,
    },
    # The Glossary boundary: "less than five years", so exactly 5.0 is not young.
    "unlisted_aged_exactly_5": {"equity_type": "other", "business_age_years": 5.0},
    "private_equity_aged_exactly_5": {"equity_type": "private_equity", "business_age_years": 5.0},
}

#: P1.393(c): the Glossary test reaches government-supported equity. 250% at HEAD.
_GOVERNMENT_SUPPORTED_HIGHER_RISK: dict[str, dict[str, Any]] = {
    "government_supported_age_2": {
        "equity_type": "government_supported",
        "business_age_years": 2.0,
    },
    "government_supported_flag_age_2": {
        "equity_type": "government_supported",
        "is_government_supported": True,
        "business_age_years": 2.0,
    },
}

#: P1.393(a): a flagged CIU keeps its Art. 132 weight. 400% at HEAD.
_CIU_FLAGGED: dict[str, tuple[dict[str, Any], float]] = {
    "ciu_fallback_flag": (
        {"equity_type": "ciu", "ciu_approach": "fallback", "is_speculative": True},
        12.50,
    ),
    "ciu_look_through_flag": (
        {
            "equity_type": "ciu",
            "ciu_approach": "look_through",
            "ciu_look_through_rw": 0.50,
            "is_speculative": True,
        },
        0.50,
    ),
    "ciu_mandate_flag": (
        {
            "equity_type": "ciu",
            "ciu_approach": "mandate_based",
            "ciu_mandate_rw": 0.75,
            "is_speculative": True,
        },
        0.75,
    ),
    "ciu_fallback_age_2": (
        {"equity_type": "ciu", "ciu_approach": "fallback", "business_age_years": 2.0},
        12.50,
    ),
}

#: P1.393(b): Art. 133(6)(c) gives Art. 48(4)'s 250%. 400% at HEAD for all but the control.
_SIGNIFICANT_INVESTMENT: dict[str, tuple[dict[str, Any], float]] = {
    "significant_unlisted_age_2": (
        {"equity_type": "other", "business_age_years": 2.0, "is_significant_investment": True},
        2.50,
    ),
    "significant_flag": (
        {"equity_type": "other", "is_speculative": True, "is_significant_investment": True},
        2.50,
    ),
    "significant_speculative_type": (
        {"equity_type": "speculative", "is_significant_investment": True},
        2.50,
    ),
    "significant_private_equity_age_unknown": (
        {"equity_type": "private_equity", "is_significant_investment": True},
        2.50,
    ),
    "significant_listed": (
        {"equity_type": "listed", "is_exchange_traded": True, "is_significant_investment": True},
        2.50,
    ),
    # Art. 133(5) runs first: SI-flagged subordinated debt keeps 150%.
    "significant_subordinated_debt": (
        {"equity_type": "subordinated_debt", "is_significant_investment": True},
        1.50,
    ),
}

_IN_SCOPE_RUNG: dict[str, str] = {
    **dict.fromkeys(_FLAG_DEFEATED, "standard"),
    **dict.fromkeys(_HIGHER_RISK_KEPT, "higher_risk"),
    **dict.fromkeys(_STANDARD_KEPT, "standard"),
    **dict.fromkeys(_GOVERNMENT_SUPPORTED_HIGHER_RISK, "higher_risk"),
}
_FIXED_WEIGHT: dict[str, float] = {
    **{ref: weight for ref, (_spec, weight) in _CIU_FLAGGED.items()},
    **{ref: weight for ref, (_spec, weight) in _SIGNIFICANT_INVESTMENT.items()},
}
_ALL_SPECS: dict[str, dict[str, Any]] = {
    **_FLAG_DEFEATED,
    **_HIGHER_RISK_KEPT,
    **_STANDARD_KEPT,
    **_GOVERNMENT_SUPPORTED_HIGHER_RISK,
    **{ref: spec for ref, (spec, _weight) in _CIU_FLAGGED.items()},
    **{ref: spec for ref, (spec, _weight) in _SIGNIFICANT_INVESTMENT.items()},
}

_SCHEMA: dict[str, pl.DataType] = {
    "exposure_reference": pl.String(),
    "ead_final": pl.Float64(),
    "equity_type": pl.String(),
    "is_speculative": pl.Boolean(),
    "is_exchange_traded": pl.Boolean(),
    "is_government_supported": pl.Boolean(),
    "is_significant_investment": pl.Boolean(),
    "business_age_years": pl.Float64(),
    "ciu_approach": pl.String(),
    "ciu_mandate_rw": pl.Float64(),
    "ciu_look_through_rw": pl.Float64(),
}

_CARRIERS = (
    "equity_transitional_approach",
    "equity_higher_risk",
    "risk_weight_pre_equity_transitional",
)


def _run(config: CalculationConfig) -> dict[str, dict[str, Any]]:
    rows = [
        {
            "exposure_reference": ref,
            "ead_final": 1_000.0,
            "is_speculative": False,
            "is_exchange_traded": False,
            "is_government_supported": False,
            "is_significant_investment": False,
            **spec,
        }
        for ref, spec in _ALL_SPECS.items()
    ]
    frame = pl.DataFrame(rows, schema=_SCHEMA).lazy()
    out = EquityCalculator().calculate_branch(frame, config).collect()
    return {r["exposure_reference"]: r for r in out.to_dicts()}


@lru_cache(maxsize=4)
def _b31(on: date) -> dict[str, dict[str, Any]]:
    """The whole book through the Basel 3.1 chain for a firm without IRB permission."""
    config = CalculationConfig.basel_3_1(
        reporting_date=on, permission_mode=PermissionMode.STANDARDISED
    )
    return _run(config)


@lru_cache(maxsize=1)
def _crr() -> dict[str, dict[str, Any]]:
    """The whole book through the CRR Art. 133 chain (a Standardised firm)."""
    config = CalculationConfig.crr(
        reporting_date=date(2026, 6, 30), permission_mode=PermissionMode.STANDARDISED
    )
    return _run(config)


def _assert_on_rung(ref: str, rung: str, on: date) -> None:
    row = _b31(on)[ref]
    assert row["risk_weight"] == pytest.approx(_WEIGHTS[on][rung]), (
        f"{ref} on {on}: expected the {rung} weight"
    )
    if on == _TRANSITIONAL_2027:
        assert row["equity_higher_risk"] is (rung == "higher_risk"), ref
        assert row["risk_weight_pre_equity_transitional"] == pytest.approx(_ARTICLE_133[rung])


_DATES = [_END_STATE, _TRANSITIONAL_2027]


class TestFlagCannotContradictTheRowsOwnEvidence:
    """P1.207: listed, or business age evidenced at 5y+, is not higher risk whatever the flag."""

    @pytest.mark.parametrize("on", _DATES, ids=str)
    @pytest.mark.parametrize("ref", sorted(_FLAG_DEFEATED))
    def test_leg_takes_the_standard_weight(self, ref: str, on: date) -> None:
        _assert_on_rung(ref, "standard", on)


class TestHigherRiskLegsKeepTheRung:
    """Guards: the flag still supplies a fact the row does not evidence."""

    @pytest.mark.parametrize("on", _DATES, ids=str)
    @pytest.mark.parametrize("ref", sorted(_HIGHER_RISK_KEPT))
    def test_leg_takes_the_higher_risk_weight(self, ref: str, on: date) -> None:
        _assert_on_rung(ref, "higher_risk", on)


class TestStandardLegsStayStandard:
    """Guards: nothing here is higher risk before or after the fix."""

    @pytest.mark.parametrize("on", _DATES, ids=str)
    @pytest.mark.parametrize("ref", sorted(_STANDARD_KEPT))
    def test_leg_takes_the_standard_weight(self, ref: str, on: date) -> None:
        _assert_on_rung(ref, "standard", on)


class TestGovernmentSupportedEquityMeetsTheGlossaryTest:
    """P1.393(c): unlisted, business under five years -> higher risk, no carve-out."""

    @pytest.mark.parametrize("on", _DATES, ids=str)
    @pytest.mark.parametrize("ref", sorted(_GOVERNMENT_SUPPORTED_HIGHER_RISK))
    def test_leg_takes_the_higher_risk_weight(self, ref: str, on: date) -> None:
        _assert_on_rung(ref, "higher_risk", on)


class TestWeightsOutsideTheArticle133Ladder:
    """P1.393(a) / (b): CIUs and Art. 133(6)(c) holdings take a fixed weight on every date."""

    @pytest.mark.parametrize("on", _DATES, ids=str)
    @pytest.mark.parametrize("ref", sorted(_FIXED_WEIGHT))
    def test_leg_takes_its_own_weight(self, ref: str, on: date) -> None:
        row = _b31(on)[ref]

        assert row["risk_weight"] == pytest.approx(_FIXED_WEIGHT[ref])

    @pytest.mark.parametrize("ref", sorted(_FIXED_WEIGHT))
    def test_rules_4_2_and_4_3_do_not_reach_it(self, ref: str) -> None:
        row = _b31(_TRANSITIONAL_2027)[ref]

        assert {c: row[c] for c in _CARRIERS} == dict.fromkeys(_CARRIERS)


class TestTheBookIsAdequate:
    """LESSONS C11: the rung tests are vacuous unless both rungs occur among in-scope legs."""

    def test_both_rungs_occur_in_the_end_state(self) -> None:
        rows = _b31(_END_STATE)
        weights = {round(rows[ref]["risk_weight"], 4) for ref in _IN_SCOPE_RUNG}

        assert weights == {2.50, 4.00}

    def test_every_leg_is_in_the_output(self) -> None:
        assert set(_b31(_END_STATE)) == set(_ALL_SPECS)


class TestCrrHasNoHigherRiskTier:
    """CRR Art. 133(2): 100%, Art. 48(4) 250%, CIUs under Art. 132. Unchanged by these fixes."""

    _CRR_CIU = {ref: weight for ref, (_spec, weight) in _CIU_FLAGGED.items()}
    _CRR_SIGNIFICANT = dict.fromkeys(_SIGNIFICANT_INVESTMENT, 2.50)

    @pytest.mark.parametrize("ref", sorted(_ALL_SPECS))
    def test_crr_weight(self, ref: str) -> None:
        expected = {**dict.fromkeys(_ALL_SPECS, 1.00), **self._CRR_CIU, **self._CRR_SIGNIFICANT}

        row = _crr()[ref]

        assert row["risk_weight"] == pytest.approx(expected[ref])
