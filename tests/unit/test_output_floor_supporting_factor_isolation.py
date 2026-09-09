"""
The SA-equivalent RWA the Basel 3.1 output floor consumes is FACTOR-FREE.

Pipeline position:
    SACalculator.calculate_unified -> ``sa_rwa`` -> engine/aggregator/_floor.py
    (``TREA = max(U-TREA, x * S-TREA + OF-ADJ)``, PRA PS1/26 Art. 92 para 2A)

Why this needs its own module
-----------------------------
``engine/sa/calculator.py::calculate_unified`` runs the risk-weight pipeline
UNCONDITIONALLY, so every row — IRB and slotting included — carries an
SA-equivalent risk weight for the output floor (LESSONS D1). Anything that
lowers that SA-equivalent lowers the floor wherever it binds, which makes it
RWA-reducing across the whole book rather than on the SA rows alone.

A CRR supporting factor (Art. 501 / 501a) is exactly such a benefit multiplier,
and TWO independent mechanisms currently keep it out of the floor's input:

  (i)  ORDERING. ``sa_rwa`` is minted as ``ead_final x risk_weight`` BEFORE
       ``apply_supporting_factors`` runs, and the factor is applied to RWA
       rather than folded into ``risk_weight``. So the floor's input is
       pre-factor by construction.
  (ii) REGIME. A Basel 3.1 run resolves the b31 pack, where the
       ``supporting_factors`` Feature is disabled, so every factor is 1.0
       anyway. The two shipped packs never enable ``output_floor`` and
       ``supporting_factors`` together.

Mechanism (ii) is a property of the packs and is asserted directly below.
Mechanism (i) is a property of the CODE, and (ii) is precisely what stops any
ordinary test from seeing it: on a real B31 run every factor is 1.0, so
``sa_rwa`` and ``rwa_post_factor`` agree whatever the ordering is, and the
test would be green in both states — which guards nothing
(``/next-items`` C1.11).

``TestSaRwaIsPreFactor`` therefore drives ``calculate_unified`` with a HYBRID
rulepack — the CRR pack with ``output_floor`` flipped on — so the two
mechanisms are separated and (i) can be observed on its own. The hybrid pack is
a deliberate isolation device and not a configuration any run produces;
``test_no_shipped_pack_enables_both_features`` says so in an assertion rather
than in a comment, so the day a pack DOES enable both, the isolation stops
being hypothetical and this module's guard becomes load-bearing for a real run.

``TestTheGuardCanFail`` is the detector evidence: it puts a 0.75 benefit
multiplier into ``risk_weight`` at the point the mint reads it, and shows the
asserted quantity moves. Exactly one thing is varied — whether a benefit
multiplier is inside ``risk_weight`` when ``sa_rwa`` is minted.

References:
- PRA PS1/26 Art. 92 para 2A: ``TREA = max(U-TREA, x * S-TREA + OF-ADJ)``
- CRR Art. 501 / 501a: the supporting factors (CRR-only)
- src/rwa_calc/engine/sa/calculator.py: the ``sa_rwa`` mint and the
  ``apply_supporting_factors`` pipe that follows it
- src/rwa_calc/engine/aggregator/_floor.py: the floor's consumption of
  ``sa_rwa``
- LESSONS.md D1 (every ``engine/sa/`` transform is an indirect IRB consumer),
  C1.11 (a test green in both states guards nothing)
"""

from __future__ import annotations

import dataclasses
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa import calculator as sa_calculator_module
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.model import Feature
from rwa_calc.rulebook.resolve import ResolvedRulepack

_CRR_DATE = date(2024, 12, 31)
_B31_DATE = date(2028, 12, 31)

#: An unrated GB corporate on an infrastructure-named product: 100% RW under
#: CRR Art. 122, and eligible for the Art. 501a factor.
_EAD = 10_000_000.0
_EXPECTED_RW = 1.00
_EXPECTED_SA_RWA = _EAD * _EXPECTED_RW  # 10,000,000 — the floor's input
_EXPECTED_POST_FACTOR = 7_500_000.00  # 10,000,000 x 0.75
_EXPECTED_RELIEF = _EXPECTED_SA_RWA - _EXPECTED_POST_FACTOR  # 2,500,000

#: The mutation's multiplier in ``TestTheGuardCanFail`` — same magnitude as the
#: Art. 501a factor, so the mutant's ``sa_rwa`` lands exactly on the
#: post-factor figure the correct code must NOT produce.
_MUTANT_RW_MULTIPLIER = 0.75


def _crr_pack_with_output_floor() -> ResolvedRulepack:
    """The CRR pack with ``output_floor`` enabled — mechanisms (i) and (ii) split.

    Everything else is the shipped CRR pack, so the supporting factors keep
    their real values and the only difference from a production CRR run is that
    ``calculate_unified`` mints ``sa_rwa``.
    """
    crr_pack = RulepackV0.from_config(CalculationConfig.crr(reporting_date=_CRR_DATE)).pack
    floor_on = Feature(
        name="output_floor",
        enabled=True,
        citation=crr_pack.entry("output_floor").citation,
    )
    return dataclasses.replace(
        crr_pack, entries={**dict(crr_pack.entries), "output_floor": floor_on}
    )


def _infrastructure_corporate_row() -> pl.LazyFrame:
    """One SA corporate infrastructure exposure, shaped for ``calculate_unified``."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["OF-INFRA"],
            "counterparty_reference": ["OF-CP"],
            "lending_group_reference": [None],
            "approach": ["standardised"],
            "exposure_class": ["corporate"],
            "cqs": [None],
            "ead_final": [_EAD],
            "drawn_amount": [_EAD],
            "interest": [0.0],
            "residential_collateral_value": [0.0],
            "is_sme": [False],
            "is_infrastructure": [True],
            "is_buy_to_let": [False],
            "is_defaulted": [False],
        },
        schema_overrides={"lending_group_reference": pl.String, "cqs": pl.Int8},
    )


def _run_unified(pack: ResolvedRulepack) -> dict:
    """Run ``calculate_unified`` on the single row and return it as a dict."""
    config = CalculationConfig.crr(reporting_date=_CRR_DATE)
    out = SACalculator().calculate_unified(_infrastructure_corporate_row(), config, pack=pack)
    return out.collect().to_dicts()[0]


@pytest.fixture()
def floored_row() -> dict:
    """The row after ``calculate_unified`` under the hybrid output-floor pack."""
    return _run_unified(_crr_pack_with_output_floor())


class TestSaRwaIsPreFactor:
    """``sa_rwa`` is ``ead_final x risk_weight``, never the post-factor RWA."""

    def test_the_supporting_factor_actually_bites_on_this_row(self, floored_row: dict) -> None:
        """Adequacy: without a factor below 1.0 there is nothing to keep out.

        Stated first and separately because every assertion in this class is
        vacuous if the row happens not to attract a supporting factor — the two
        quantities would then be equal for an uninteresting reason and the
        module would pass in both states.
        """
        assert floored_row["supporting_factor"] == pytest.approx(0.75)
        assert floored_row["supporting_factor_applied"] is True

    def test_sa_rwa_is_minted_from_the_pre_factor_risk_weight(self, floored_row: dict) -> None:
        """The floor's input equals EAD x RW at an absolute value.

        Absolute rather than ``sa_rwa >= rwa_post_factor``: the relative form
        is satisfied by any factor at or below 1.0, including one that had been
        folded into ``risk_weight`` and then partially undone.
        """
        assert floored_row["risk_weight"] == pytest.approx(_EXPECTED_RW)
        assert floored_row["sa_rwa"] == pytest.approx(_EXPECTED_SA_RWA)
        assert floored_row["sa_rwa"] == pytest.approx(
            floored_row["ead_final"] * floored_row["risk_weight"]
        )

    def test_the_factor_relief_does_not_reach_the_floor_input(self, floored_row: dict) -> None:
        """``sa_rwa`` and ``rwa_post_factor`` differ by exactly the relief.

        The crossing amount is 2,500,000 and asserted non-zero: a test whose
        two sides agree cannot distinguish "the factor is excluded" from "the
        factor is included and happens to be 1.0" (LESSONS C2).
        """
        crossing = floored_row["sa_rwa"] - floored_row["rwa_post_factor"]

        assert floored_row["rwa_post_factor"] == pytest.approx(_EXPECTED_POST_FACTOR)
        assert crossing == pytest.approx(_EXPECTED_RELIEF)
        assert crossing > 0.0, (
            "sa_rwa and rwa_post_factor agree - this row cannot show whether the "
            "supporting factor reaches the output floor's input"
        )

    def test_sa_rwa_is_not_the_post_factor_rwa(self, floored_row: dict) -> None:
        """The inversion, named directly.

        7,500,000 is the value ``sa_rwa`` takes if the mint is moved below the
        factor application, or repointed at ``rwa_post_factor``. Asserting the
        wrong value is not produced makes the failure message name the defect
        rather than only the arithmetic.
        """
        assert floored_row["sa_rwa"] != pytest.approx(floored_row["rwa_post_factor"])
        assert floored_row["sa_rwa"] != pytest.approx(_EXPECTED_POST_FACTOR)


class TestTheGuardCanFail:
    """Detector evidence: the asserted quantity moves under one varied input."""

    def test_a_benefit_multiplier_inside_risk_weight_reaches_sa_rwa(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fold 0.75 into ``risk_weight`` before the mint — ``sa_rwa`` falls.

        ``apply_intragroup_zero_rw`` is the last transform in the risk-weight
        chain before ``sa_rwa`` is minted, so patching it is the cheapest way to
        put a benefit multiplier into ``risk_weight`` at exactly the point the
        mint reads it. That is the shape ``TestSaRwaIsPreFactor`` exists to
        reject: a refactor that treats the supporting factor as a risk-weight
        adjustment rather than an RWA adjustment silently lowers S-TREA for the
        whole book.

        Exactly one thing is varied. The mutation does NOT touch
        ``apply_supporting_factors``, the pipe order, or the mint; the mutant
        and the original differ only in the value of ``risk_weight`` when
        ``sa_rwa`` is computed. Both sides are asserted, so a mutation that
        silently failed to apply would show as an unchanged ``sa_rwa`` and fail
        here rather than reading as reassurance.
        """
        original = sa_calculator_module.apply_intragroup_zero_rw

        def _fold_benefit_into_rw(lf: pl.LazyFrame, *args: object, **kwargs: object):
            lf = original(lf, *args, **kwargs)
            return lf.with_columns(
                (pl.col("risk_weight") * _MUTANT_RW_MULTIPLIER).alias("risk_weight")
            )

        monkeypatch.setattr(sa_calculator_module, "apply_intragroup_zero_rw", _fold_benefit_into_rw)
        assert sa_calculator_module.apply_intragroup_zero_rw is not original

        mutant = _run_unified(_crr_pack_with_output_floor())

        assert mutant["sa_rwa"] == pytest.approx(_EXPECTED_POST_FACTOR), (
            "the mutation did not reach sa_rwa - this probe proves nothing about "
            "the guard above (LESSONS C12 mechanism 2/4)"
        )
        assert mutant["sa_rwa"] != pytest.approx(_EXPECTED_SA_RWA)

    def test_the_unmutated_run_returns_the_asserted_value(self) -> None:
        """The control for the probe above, on the same call path.

        A probe that reddens is only evidence if the unmutated run is green on
        the same inputs; running both is what separates "the guard detects the
        mutation" from "the guard fails on everything".
        """
        assert _run_unified(_crr_pack_with_output_floor())["sa_rwa"] == pytest.approx(
            _EXPECTED_SA_RWA
        )


class TestRegimeMechanism:
    """Mechanism (ii): the shipped packs never arm both features at once."""

    def test_the_basel_31_pack_disables_supporting_factors(self) -> None:
        """The regime that HAS an output floor has no supporting factors."""
        pack = RulepackV0.from_config(CalculationConfig.basel_3_1(reporting_date=_B31_DATE)).pack

        assert pack.feature("output_floor") is True
        assert pack.feature("supporting_factors") is False

    def test_the_crr_pack_disables_the_output_floor(self) -> None:
        """And the regime that HAS supporting factors has no output floor.

        Which is also why ``sa_rwa`` is not minted at all on a CRR run — the
        mint is gated on the ``output_floor`` Feature.
        """
        pack = RulepackV0.from_config(CalculationConfig.crr(reporting_date=_CRR_DATE)).pack

        assert pack.feature("supporting_factors") is True
        assert pack.feature("output_floor") is False

    def test_no_shipped_pack_enables_both_features(self) -> None:
        """Neither shipped pack arms ``output_floor`` and ``supporting_factors``.

        This is what makes the hybrid pack above an isolation device rather
        than a production configuration — and it is a claim with an expiry
        date, so it is asserted rather than written in a comment. If it ever
        fails, mechanism (ii) has gone and ``TestSaRwaIsPreFactor`` is the only
        thing left holding the supporting factor out of S-TREA.
        """
        packs = {
            "crr": RulepackV0.from_config(CalculationConfig.crr(reporting_date=_CRR_DATE)).pack,
            "b31": RulepackV0.from_config(
                CalculationConfig.basel_3_1(reporting_date=_B31_DATE)
            ).pack,
        }

        both_armed = {
            name
            for name, pack in packs.items()
            if pack.feature("output_floor") and pack.feature("supporting_factors")
        }

        assert both_armed == set()
