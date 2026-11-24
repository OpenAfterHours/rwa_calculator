"""
P1.375 — CRR Art. 501a(1)(h): a subordinated obligation does not receive the
infrastructure supporting factor.

CRR Art. 501a(1), verbatim (legislation.gov.uk point-in-time text, as printed by
``scripts/regulation_text.py show "CRR 501a"``):

    "Own funds requirements for credit risk calculated in accordance with Title
    II of Part III shall be multiplied by a factor of 0,75, provided that the
    exposure complies with all the following criteria:
    ...
    (h) the obligation is senior to all other claims other than statutory
        claims and claims from derivatives counterparties;
    ..."

The factor is a conditional grant — "provided that the exposure complies with
ALL the following criteria". ``engine/supporting_factors.py::apply_factors``
tested limb (a) only (class and default, P1.211), so a subordinated loan on an
infrastructure-named product received 0.75 on every branch: SA, F-IRB, A-IRB
and slotting. ``seniority`` is a real input (loans, facilities, contingents;
default ``"senior"``; validated against ``{"senior", "subordinated"}``) and
survives to ``crm_exit``, so limb (h) is enforceable today as a one-way DENIAL.
It is not a full test of (h) — ``"senior"`` does not prove seniority to every
non-statutory claim — but a row whose input says it is NOT senior cannot meet
(h) on any reading.

Two readings this module pins, each easy to reverse in one predicate
(``engine/supporting_factors.py::_art_501a_seniority_permits``):

- **Null counts as senior.** An absent column is filled with ``"senior"`` at
  load; a column that is present but null stays null to the calculators. Both
  keep the factor, so a firm that leaves the field null (missing) is not
  silently re-priced. An empty string is not null and is denied. The NULL
  leg is the present-null shape — the only one that tells
  ``is_null() | (... == "senior")`` apart from a null-propagating
  ``~(... == "subordinated")`` term, which would route null to factor 1.0.
- **Anything that is not "senior" (case-folded) is denied** — ``"subordinated"``
  in any case, and out-of-domain values such as ``"junior"``, ``""`` or a
  whitespace-padded ``" senior"`` (not stripped). Validation only
  warns on those (DQ006) and lets them through, and (h) is a requirement the
  input has to evidence, so a value that does not say "senior" does not.

The legs
--------
Every leg is on ``product_type="INFRASTRUCTURE_LOAN"`` (so ``is_infrastructure``
is True), performing, and inside Art. 501a(1)(a)'s class limb, so seniority is
the ONLY varied input and limb (h) the only thing that can hold a leg at 1.0.
``TestP1375FixtureAdequacy`` asserts all three.

    leg      branch     class                seniority       pre  post  role
    SNR      SA         corporate            "senior"        0.75 0.75  SURVIVES (control)
    NULL     SA         corporate            null (present)  0.75 0.75  SURVIVES (null = senior)
    SUB      SA         corporate            "subordinated"  0.75 1.00  MOVES +1,500,000
    SUBCAP   SA         corporate            "Subordinated"  0.75 1.00  MOVES +1,000,000
    JUNIOR   SA         corporate            "junior"        0.75 1.00  MOVES   +500,000
    SLSUB    SA         specialised_lending  "subordinated"  0.75 1.00  MOVES +2,000,000
    SMESUB   SA         corporate_sme        "subordinated"  0.75 0.7619 MOVES   +17,850
    FIRBSNR  F-IRB      corporate            "senior"        0.75 0.75  SURVIVES
    FIRBSUB  F-IRB      corporate            "subordinated"  0.75 1.00  MOVES
    AIRBSUB  A-IRB      corporate            "subordinated"  0.75 1.00  MOVES
    SLOTSNR  slotting   specialised_lending  "senior"        0.75 0.75  SURVIVES
    SLOTSUB  slotting   specialised_lending  "subordinated"  0.75 1.00  MOVES +1,225,000

SMESUB keeps the Art. 501 SME factor: Art. 501 has no seniority condition, so
denying Art. 501a must leave the SME arm of ``min(sme, infra)`` binding. That
leg is also where the open P2.56 reporting misattribution widens — C 07.00
books its SME relief in the infrastructure column 0217 and of-which row 0035,
because the reporting predicates key on the raw ``is_infrastructure`` flag — so
the C 07.00 attribution assertion for it is ``xfail(strict=True)`` with
``OWNER: P2.56``.

Regime coverage: Art. 501a is CRR-only. Basel 3.1 has no supporting factors
(the b31 pack's ``supporting_factors`` Feature is disabled) and no Art. 501a in
PS1/26 or its reporting annex, so ``TestP1375Basel31`` pins that every leg stays
at 1.0 there for that independent reason.

References:
    - CRR Art. 501a(1)(h) — seniority; Art. 501a(1)(a) — the class limb (P1.211)
    - CRR Art. 501 — the SME factor, for the SMESUB leg
    - CRR Annex II C 07.00 row 0035, cols 0216/0217
    - src/rwa_calc/engine/supporting_factors.py: ``apply_factors``
    - IMPLEMENTATION_PLAN.md: P1.375 (slice A), P2.56 (the reporting owner)
    - LESSONS.md B1 (null vs absent), C1 (absolute assertions), C11 (adequacy)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

import polars as pl
import pytest
from tests.fixtures.irb_test_helpers import (
    create_full_irb_model_permissions,
    create_slotting_only_model_permissions,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import CRM_EXIT_EDGE
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.engine.supporting_factors import SupportingFactorCalculator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.rulebook import RulepackV0

#: CRR Art. 501a(1): "shall be multiplied by a factor of 0,75". Hand-written
#: from the article, and checked against the pack below, so the expectations
#: are not a restatement of the value under test (LESSONS B3).
INFRA_FACTOR_FROM_ARTICLE = 0.75

#: CRR Art. 501(1)(a): "multiplied by the factor 0,7619" for the part of the
#: exposure up to EUR 2,5 million. Every SME leg here is wholly inside tier 1.
SME_TIER1_FACTOR_FROM_ARTICLE = 0.7619

#: Art. 501a(1)(a)'s class limb, as enum members (LESSONS B2).
ART_501A_ELIGIBLE_CLASSES: frozenset[ExposureClass] = frozenset(
    {ExposureClass.CORPORATE, ExposureClass.CORPORATE_SME, ExposureClass.SPECIALISED_LENDING}
)

_VALUE_DATE = date(2024, 1, 1)
_MATURITY_DATE = date(2034, 1, 1)
_CRR_REPORTING_DATE = date(2024, 12, 31)
_B31_REPORTING_DATE = date(2028, 12, 31)
_PRODUCT_TYPE = "INFRASTRUCTURE_LOAN"
_MODEL_ID = "TEST_FULL_IRB"  # must match tests/fixtures/irb_test_helpers.py
_LARGE_CORPORATE_REVENUE = 200_000_000.0
_SME_REVENUE = 30_000_000.0

#: CRR Art. 153(5) Table 1: "strong", remaining maturity >= 2.5 years.
_SLOTTING_STRONG_RW = 0.70

_OWNER_P2_56 = (
    "OWNER: P2.56 - C 07.00 keys col 0216/0217 and row 0035 on the RAW "
    "is_infrastructure flag, so an infrastructure-named SME row that Art. 501a "
    "denies (here by limb (h)) has its Art. 501 SME relief booked in the "
    "infrastructure column and of-which row. Remove this xfail when P2.56 makes "
    "apply_factors emit the dedicated per-factor applied flags."
)


@dataclass(frozen=True)
class Leg:
    """One P1.375 exposure leg: its input, its branch and its hand-calc."""

    label: str
    run: str  # "sa" | "irb" | "slotting"
    seniority: str | None
    drawn: float
    expected_class: ExposureClass
    expected_approach: str
    expected_factor: float
    pre_fix_factor: float
    role: str
    revenue: float = _LARGE_CORPORATE_REVENUE
    specialised: bool = False
    loan_extra: dict = field(default_factory=dict)

    @property
    def cp_ref(self) -> str:
        return f"P1375-CP-{self.label}"

    @property
    def loan_ref(self) -> str:
        return f"P1375-LN-{self.label}"

    @property
    def moves(self) -> bool:
        return self.expected_factor != self.pre_fix_factor


def _sa(label: str, seniority: str | None, drawn: float, factor: float, role: str, **kw) -> Leg:
    return Leg(
        label=label,
        run="sa",
        seniority=seniority,
        drawn=drawn,
        expected_class=kw.pop("expected_class", ExposureClass.CORPORATE),
        expected_approach="standardised",
        expected_factor=factor,
        pre_fix_factor=INFRA_FACTOR_FROM_ARTICLE,
        role=role,
        **kw,
    )


LEGS: dict[str, Leg] = {
    leg.label: leg
    for leg in (
        _sa("SNR", "senior", 10_000_000.0, 0.75, "SURVIVES - positive control"),
        _sa("NULL", None, 3_000_000.0, 0.75, "SURVIVES - a present-but-null seniority is senior"),
        _sa("SUB", "subordinated", 6_000_000.0, 1.0, "MOVES - limb (h), the plain case"),
        _sa("SUBCAP", "Subordinated", 4_000_000.0, 1.0, "MOVES - limb (h) is case-insensitive"),
        _sa("JUNIOR", "junior", 2_000_000.0, 1.0, "MOVES - an out-of-domain value is not senior"),
        _sa(
            "SLSUB",
            "subordinated",
            8_000_000.0,
            1.0,
            "MOVES - limb (h) binds on the second class of limb (a)",
            expected_class=ExposureClass.SPECIALISED_LENDING,
            specialised=True,
        ),
        _sa(
            "SMESUB",
            "subordinated",
            1_500_000.0,
            SME_TIER1_FACTOR_FROM_ARTICLE,
            "MOVES - Art. 501a denied, the Art. 501 SME factor (no seniority limb) binds",
            expected_class=ExposureClass.CORPORATE_SME,
            revenue=_SME_REVENUE,
        ),
        Leg(
            label="FIRBSNR",
            run="irb",
            seniority="senior",
            drawn=50_000_000.0,
            expected_class=ExposureClass.CORPORATE,
            expected_approach="foundation_irb",
            expected_factor=0.75,
            pre_fix_factor=0.75,
            role="SURVIVES - the IRB branch's positive control",
        ),
        Leg(
            label="FIRBSUB",
            run="irb",
            seniority="subordinated",
            drawn=20_000_000.0,
            expected_class=ExposureClass.CORPORATE,
            expected_approach="foundation_irb",
            expected_factor=1.0,
            pre_fix_factor=0.75,
            role="MOVES - limb (h) on engine/irb/calculator.py (F-IRB)",
        ),
        Leg(
            label="AIRBSUB",
            run="irb",
            seniority="subordinated",
            drawn=15_000_000.0,
            expected_class=ExposureClass.CORPORATE,
            expected_approach="advanced_irb",
            expected_factor=1.0,
            pre_fix_factor=0.75,
            role="MOVES - limb (h) on engine/irb/calculator.py (A-IRB)",
            loan_extra={"lgd": 0.30, "has_sufficient_collateral_data": True},
        ),
        Leg(
            label="SLOTSNR",
            run="slotting",
            seniority="senior",
            drawn=8_000_000.0,
            expected_class=ExposureClass.SPECIALISED_LENDING,
            expected_approach="slotting",
            expected_factor=0.75,
            pre_fix_factor=0.75,
            role="SURVIVES - the slotting branch's positive control",
            specialised=True,
        ),
        Leg(
            label="SLOTSUB",
            run="slotting",
            seniority="subordinated",
            drawn=7_000_000.0,
            expected_class=ExposureClass.SPECIALISED_LENDING,
            expected_approach="slotting",
            expected_factor=1.0,
            pre_fix_factor=0.75,
            role="MOVES - limb (h) on engine/slotting/calculator.py",
            specialised=True,
        ),
    )
}

_RUNS: tuple[str, ...] = ("sa", "irb", "slotting")


def _legs(run: str) -> tuple[Leg, ...]:
    return tuple(leg for leg in LEGS.values() if leg.run == run)


# ---------------------------------------------------------------------------
# Portfolio factories
# ---------------------------------------------------------------------------


def _bundle(legs: tuple[Leg, ...], run: str):
    """A raw bundle for ``legs`` routed onto ``run``'s branch."""
    counterparties = pl.DataFrame(
        [
            {
                "counterparty_reference": leg.cp_ref,
                "counterparty_name": f"P1.375 {leg.label}",
                "entity_type": "corporate",
                "annual_revenue": leg.revenue,
                "country_code": "GB",
                "local_currency": "GBP",
                "default_status": False,
                "apply_fi_scalar": False,
                "is_managed_as_retail": False,
            }
            for leg in legs
        ]
    )
    # ``seniority`` is a typed String column holding a real null on the NULL
    # leg — the present-null shape, which the loader does NOT fill (only an
    # absent column is defaulted to "senior"). LESSONS B1.
    loans = pl.DataFrame(
        [
            {
                "loan_reference": leg.loan_ref,
                "counterparty_reference": leg.cp_ref,
                "product_type": _PRODUCT_TYPE,
                "currency": "GBP",
                "value_date": _VALUE_DATE,
                "maturity_date": _MATURITY_DATE,
                "drawn_amount": leg.drawn,
                "interest": 0.0,
                "seniority": leg.seniority,
                "lgd": leg.loan_extra.get("lgd"),
                "has_sufficient_collateral_data": leg.loan_extra.get(
                    "has_sufficient_collateral_data", False
                ),
            }
            for leg in legs
        ],
        schema_overrides={"seniority": pl.String, "lgd": pl.Float64},
    )
    specialised = [leg for leg in legs if leg.specialised]
    tables: dict = {"counterparties": counterparties, "loans": loans}
    if specialised:
        tables["specialised_lending"] = pl.DataFrame(
            [
                {
                    "counterparty_reference": leg.cp_ref,
                    "sl_type": "project_finance",
                    "project_phase": "operational",
                    "slotting_category": "strong",
                    "is_hvcre": False,
                }
                for leg in specialised
            ]
        )
    if run != "sa":
        tables["ratings"] = pl.DataFrame(
            [
                {
                    "rating_reference": f"P1375-RTG-{leg.label}",
                    "counterparty_reference": leg.cp_ref,
                    "rating_type": "internal",
                    "pd": 0.0075,
                    "model_id": _MODEL_ID,
                }
                for leg in legs
            ]
        )
        tables["model_permissions"] = (
            create_full_irb_model_permissions()
            if run == "irb"
            else create_slotting_only_model_permissions()
        )
    return make_raw_bundle(**tables)


@lru_cache(maxsize=8)
def _run(run: str, regime: str) -> dict[str, dict]:
    """One branch's legs through ``PipelineOrchestrator``, keyed by loan reference."""
    config = (
        CalculationConfig.crr(reporting_date=_CRR_REPORTING_DATE)
        if regime == "crr"
        else CalculationConfig.basel_3_1(reporting_date=_B31_REPORTING_DATE)
    )
    result = PipelineOrchestrator().run_with_data(_bundle(_legs(run), run), config)
    df = result.results.collect()
    return {row["exposure_reference"]: row for row in df.iter_rows(named=True)}


def _row(label: str, regime: str = "crr") -> dict:
    leg = LEGS[label]
    return _run(leg.run, regime)[leg.loan_ref]


# ---------------------------------------------------------------------------
# Adequacy — without these the MOVES legs prove nothing (LESSONS C11)
# ---------------------------------------------------------------------------


class TestP1375FixtureAdequacy:
    """Seniority is the only varied input, and it reaches the calculators."""

    @pytest.mark.parametrize("run", _RUNS)
    def test_p1_375_no_leg_is_dropped(self, run: str) -> None:
        """Every leg in, every leg out — a vanished row is neither a result nor an error."""
        results = _run(run, "crr")

        assert set(results) == {leg.loan_ref for leg in _legs(run)}

    @pytest.mark.parametrize("label", sorted(LEGS))
    def test_p1_375_every_leg_passes_limb_a(self, label: str) -> None:
        """Infrastructure candidate, performing, inside limb (a)'s class set.

        A leg failing any of these is held at 1.0 by the flag or by limb (a),
        not by limb (h), and its MOVES verdict would pass on the unfixed engine.
        """
        leg = LEGS[label]
        row = _row(label)

        assert row["is_infrastructure"] is True, leg.role
        assert row["is_defaulted"] is False, leg.role
        assert row["exposure_class"] == leg.expected_class.value, leg.role
        assert leg.expected_class in ART_501A_ELIGIBLE_CLASSES

    @pytest.mark.parametrize("label", sorted(LEGS))
    def test_p1_375_every_leg_routes_to_its_branch(self, label: str) -> None:
        """``apply_factors`` has three call sites; each branch must really be hit."""
        leg = LEGS[label]

        assert _row(label)["approach_applied"] == leg.expected_approach

    @pytest.mark.parametrize("label", sorted(LEGS))
    def test_p1_375_seniority_reaches_the_calculators_unchanged(self, label: str) -> None:
        """The input value survives to the results — including a real null.

        The NULL leg must arrive as None, not as a loader-filled "senior";
        otherwise it cannot tell a null-safe predicate from one that denies
        null (LESSONS B1). SUBCAP and JUNIOR must arrive unnormalised, or they
        test nothing about case-folding or the out-of-domain reading.
        """
        leg = LEGS[label]

        assert _row(label)["seniority"] == leg.seniority

    def test_p1_375_seniority_is_a_required_crm_exit_column(self) -> None:
        """The column ``apply_factors`` reads is sealed on the edge it reads from.

        So the absent-column fallback in ``apply_factors`` (typed null, i.e.
        senior) is reachable only from minimal harness frames, never from the
        pipeline.
        """
        spec = CRM_EXIT_EDGE.columns.get("seniority")

        assert spec is not None
        assert spec.required


# ---------------------------------------------------------------------------
# Limb (h) end to end, all three calculators
# ---------------------------------------------------------------------------


class TestP1375SeniorityLimb:
    """Art. 501a(1)(h) applied through ``PipelineOrchestrator``."""

    @pytest.mark.parametrize("label", sorted(LEGS))
    def test_p1_375_supporting_factor_per_leg(self, label: str) -> None:
        """Each leg's factor at an absolute value (LESSONS C1)."""
        leg = LEGS[label]

        assert _row(label)["supporting_factor"] == pytest.approx(leg.expected_factor), leg.role

    @pytest.mark.parametrize("label", sorted(LEGS))
    def test_p1_375_rwa_final_reconciles_to_the_factor(self, label: str) -> None:
        """``rwa_final == rwa_pre_factor x supporting_factor``, non-null, on every leg."""
        row = _row(label)

        assert row["rwa_pre_factor"] is not None
        assert row["rwa_final"] is not None
        assert row["rwa_final"] == pytest.approx(
            row["rwa_pre_factor"] * LEGS[label].expected_factor
        )

    @pytest.mark.parametrize("label", sorted(leg.label for leg in _legs("sa")))
    def test_p1_375_sa_rwa_final_per_leg(self, label: str) -> None:
        """SA hand-calc: unrated CRR corporate / SL at 100%, times the factor."""
        leg = LEGS[label]
        row = _row(label)

        assert row["risk_weight"] == pytest.approx(1.0)
        assert row["rwa_final"] == pytest.approx(leg.drawn * leg.expected_factor), leg.role

    @pytest.mark.parametrize("label", sorted(leg.label for leg in _legs("slotting")))
    def test_p1_375_slotting_rwa_final_per_leg(self, label: str) -> None:
        """Slotting hand-calc: CRR "strong", >= 2.5 years, 70%, times the factor."""
        leg = LEGS[label]
        row = _row(label)

        assert row["risk_weight"] == pytest.approx(_SLOTTING_STRONG_RW)
        assert row["rwa_final"] == pytest.approx(
            leg.drawn * _SLOTTING_STRONG_RW * leg.expected_factor
        ), leg.role

    @pytest.mark.parametrize("run", _RUNS)
    def test_p1_375_supporting_factor_applied_tracks_the_gate(self, run: str) -> None:
        """The applied flag (what COREP reads) is set on exactly the relieved legs."""
        applied = {
            leg.label
            for leg in _legs(run)
            if _run(run, "crr")[leg.loan_ref]["supporting_factor_applied"]
        }

        assert applied == {leg.label for leg in _legs(run) if leg.expected_factor < 1.0}

    def test_p1_375_sa_portfolio_rwea_is_measured(self) -> None:
        """30,892,850 with limb (h) vs 25,875,000 without — 5,017,850 restored.

        Both ends asserted, so the direction and size are measured (LESSONS C8).
        """
        total = sum(row["rwa_final"] for row in _run("sa", "crr").values())
        pre_fix = sum(leg.drawn * leg.pre_fix_factor for leg in _legs("sa"))

        assert total == pytest.approx(30_892_850.0)
        assert pre_fix == pytest.approx(25_875_000.0)
        assert total - pre_fix == pytest.approx(5_017_850.0)

    @pytest.mark.parametrize("run", _RUNS)
    def test_p1_375_the_gate_is_not_a_blanket_withdrawal(self, run: str) -> None:
        """Each branch keeps the factor on its senior leg, so the denial is (h), not a deletion."""
        survivors = [leg for leg in _legs(run) if leg.expected_factor == INFRA_FACTOR_FROM_ARTICLE]

        assert survivors, f"{run}: no surviving leg - the branch has no positive control"
        for leg in survivors:
            assert _row(leg.label)["supporting_factor"] == pytest.approx(
                INFRA_FACTOR_FROM_ARTICLE
            ), leg.role


# ---------------------------------------------------------------------------
# The predicate in isolation — the seniority vocabulary
# ---------------------------------------------------------------------------


def _one_row_frame(seniority: object, *, is_sme: bool = False, with_column: bool = True):
    """One performing corporate infrastructure row; ``seniority`` is the only knob."""
    data: dict = {
        "exposure_reference": ["ONE"],
        "counterparty_reference": ["CP"],
        "lending_group_reference": [None],
        "exposure_class": ["corporate_sme" if is_sme else "corporate"],
        "ead_final": [1_000_000.0],
        "drawn_amount": [1_000_000.0],
        "interest": [0.0],
        "residential_collateral_value": [0.0],
        "rwa_pre_factor": [1_000_000.0],
        "cp_annual_revenue": [_SME_REVENUE if is_sme else _LARGE_CORPORATE_REVENUE],
        "is_sme": [is_sme],
        "is_infrastructure": [True],
        "is_buy_to_let": [False],
        "is_defaulted": [False],
    }
    overrides: dict = {"lending_group_reference": pl.String}
    if with_column:
        data["seniority"] = [seniority]
        overrides["seniority"] = pl.String
    return pl.LazyFrame(data, schema_overrides=overrides)


def _factor_for(frame: pl.LazyFrame) -> float:
    config = CalculationConfig.crr(reporting_date=_CRR_REPORTING_DATE)
    return (
        SupportingFactorCalculator().apply_factors(frame, config).collect()["supporting_factor"][0]
    )


class TestP1375SeniorityVocabulary:
    """Which ``seniority`` values keep the factor, pinned value by value."""

    @pytest.mark.parametrize("seniority", ["senior", "SENIOR", "Senior", None])
    def test_p1_375_senior_or_null_keeps_the_factor(self, seniority: str | None) -> None:
        """ "senior" in any case, or a typed null, is not a limb (h) denial."""
        assert _factor_for(_one_row_frame(seniority)) == pytest.approx(INFRA_FACTOR_FROM_ARTICLE)

    @pytest.mark.parametrize(
        "seniority",
        [
            "subordinated",
            "SUBORDINATED",
            "Subordinated",
            "junior",
            "mezzanine",
            "",
            " senior",
            "senior ",
        ],
    )
    def test_p1_375_anything_not_senior_is_denied(self, seniority: str) -> None:
        """Limb (h) requires the obligation to BE senior; any other value fails it.

        The empty string is not null, so it does not get the null reading.
        Whitespace is not stripped: validation does not strip either, so a
        padded ``" senior"`` is already an out-of-domain DQ006 value, and
        denying it is the conservative direction.
        """
        assert _factor_for(_one_row_frame(seniority)) == pytest.approx(1.0)

    def test_p1_375_an_absent_column_keeps_the_factor(self) -> None:
        """Minimal harness frames without ``seniority`` keep the P1.211 behaviour."""
        assert _factor_for(_one_row_frame(None, with_column=False)) == pytest.approx(
            INFRA_FACTOR_FROM_ARTICLE
        )

    def test_p1_375_an_all_null_column_keeps_the_factor_on_every_row(self) -> None:
        """An all-null String column must neither raise nor deny (``~`` on all-null raises)."""
        frame = pl.concat([_one_row_frame(None), _one_row_frame(None)])

        factors = (
            SupportingFactorCalculator()
            .apply_factors(frame, CalculationConfig.crr(reporting_date=_CRR_REPORTING_DATE))
            .collect()["supporting_factor"]
            .to_list()
        )

        assert factors == pytest.approx([INFRA_FACTOR_FROM_ARTICLE] * 2)

    def test_p1_375_a_null_dtype_column_keeps_the_factor(self) -> None:
        """A harness column built from ``[None]`` alone is ``pl.Null``, not String.

        ``str.to_lowercase`` raises on that dtype, so the predicate must cast
        before folding case rather than crash a frame production never builds.
        """
        frame = _one_row_frame(None, with_column=False).with_columns(seniority=pl.lit(None))

        assert frame.collect_schema()["seniority"] == pl.Null
        assert _factor_for(frame) == pytest.approx(INFRA_FACTOR_FROM_ARTICLE)

    @pytest.mark.parametrize("seniority", ["senior", "subordinated", None])
    def test_p1_375_seniority_does_not_touch_the_sme_factor(self, seniority: str | None) -> None:
        """Art. 501 has no seniority condition: a non-infrastructure SME keeps 0.7619."""
        frame = _one_row_frame(seniority, is_sme=True).with_columns(
            pl.lit(False).alias("is_infrastructure")
        )

        assert _factor_for(frame) == pytest.approx(SME_TIER1_FACTOR_FROM_ARTICLE)

    def test_p1_375_pack_factors_match_the_articles(self) -> None:
        """The hand-written article values are the pack's values (LESSONS A4/B3)."""
        pack = RulepackV0.from_config(
            CalculationConfig.crr(reporting_date=_CRR_REPORTING_DATE)
        ).pack
        params = pack.formula("supporting_factors_values").params

        assert float(params["infrastructure_factor"]) == pytest.approx(INFRA_FACTOR_FROM_ARTICLE)
        assert float(params["sme_factor_under_threshold"]) == pytest.approx(
            SME_TIER1_FACTOR_FROM_ARTICLE
        )


# ---------------------------------------------------------------------------
# COREP C 07.00 — row 0035 / cols 0216-0217
# ---------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _c07_corporate(labels: tuple[str, ...]) -> pl.DataFrame:
    """The C 07.00 corporate sheet for a CRR SA run of ``labels`` alone."""
    legs = tuple(LEGS[label] for label in labels)
    result = PipelineOrchestrator().run_with_data(
        _bundle(legs, "sa"), CalculationConfig.crr(reporting_date=_CRR_REPORTING_DATE)
    )
    corep = COREPGenerator().generate_from_lazyframe(result.results, framework="CRR")
    assert "corporate" in corep.c07_00, (
        f"C 07.00 corporate sheet not emitted: {sorted(corep.c07_00)}"
    )
    return corep.c07_00["corporate"]


def _cell(sheet: pl.DataFrame, row_ref: str, col_ref: str) -> float | None:
    matched = sheet.filter(pl.col("row_ref") == row_ref)
    assert matched.height == 1, f"expected one row {row_ref}, got {matched.height}"
    return matched[col_ref][0]


class TestP1375C0700:
    """Row 0035 is "only exposures which meet the requirements of Article 501a"."""

    def test_p1_375_a_subordinated_leg_leaves_row_0035(self) -> None:
        """SNR + SUB: row 0035 and col 0217 hold SNR alone.

        Pre-fix SUB is relieved too, so row 0035 col 0010 reads 16,000,000 and
        col 0217 -4,000,000. SUB gets no factor of either kind, so P2.56's
        attribution question does not arise on this pair.
        """
        sheet = _c07_corporate(("SNR", "SUB"))

        assert _cell(sheet, "0010", "0010") == pytest.approx(16_000_000.0)
        assert _cell(sheet, "0035", "0010") == pytest.approx(10_000_000.0)
        assert _cell(sheet, "0035", "0217") == pytest.approx(-2_500_000.0)
        assert _cell(sheet, "0010", "0217") == pytest.approx(-2_500_000.0)

    @pytest.mark.xfail(strict=True, reason=_OWNER_P2_56)
    def test_p1_375_a_subordinated_sme_leg_is_reported_as_sme_relief(self) -> None:
        """SMESUB's relief is Art. 501 relief: col 0216, not col 0217 or row 0035."""
        sheet = _c07_corporate(("SMESUB",))
        relief = 1_500_000.0 * (1.0 - SME_TIER1_FACTOR_FROM_ARTICLE)

        assert _cell(sheet, "0030", "0010") == pytest.approx(1_500_000.0)
        assert _cell(sheet, "0010", "0216") == pytest.approx(-relief)
        assert (_cell(sheet, "0010", "0217") or 0.0) == pytest.approx(0.0)
        assert _cell(sheet, "0035", "0010") is None


# ---------------------------------------------------------------------------
# Regime control
# ---------------------------------------------------------------------------


class TestP1375Basel31:
    """Art. 501a is CRR-only; Basel 3.1 withdraws supporting factors entirely."""

    @pytest.mark.parametrize("label", sorted(leg.label for leg in _legs("sa")))
    def test_p1_375_no_leg_is_relieved_under_basel_31(self, label: str) -> None:
        """Every leg — senior or not — sits at 1.0 with ``rwa_final == rwa_pre_factor``."""
        row = _row(label, "b31")

        assert row["supporting_factor"] == pytest.approx(1.0)
        assert row["supporting_factor_applied"] is False
        assert row["rwa_final"] == pytest.approx(row["rwa_pre_factor"])

    def test_p1_375_the_basel_31_pack_disables_supporting_factors(self) -> None:
        """The mechanism behind the assertion above, at its source."""
        pack = RulepackV0.from_config(
            CalculationConfig.basel_3_1(reporting_date=_B31_REPORTING_DATE)
        ).pack

        assert pack.feature("supporting_factors") is False
