"""
P1.211 — CRR Art. 501a(1)(a): the infrastructure supporting factor is gated on
exposure class AND on non-default.

CRR Art. 501a(1), verbatim (``docs/assets/crr.pdf`` PAGE_INDEX 418):

    "Own funds requirements for credit risk calculated in accordance with Title
    II of Part III shall be multiplied by a factor of 0,75, provided that the
    exposure complies with all the following criteria:

    (a) the exposure is included either in the corporate exposure class or in
        the specialised lending exposures class, with the exclusion of
        exposures in default;
    ..."

``engine/classify/attributes.py`` derives ``is_infrastructure`` from a bare
substring match — ``pl.col("_pt_upper").str.contains("INFRASTRUCTURE")`` — so it
is an eligibility CANDIDATE flag and nothing more. Criterion (a) was never
applied: ``apply_factors`` multiplied by 0.75 on that flag alone, so any
exposure on an infrastructure-named product received the relief regardless of
its class or default status. That understates own funds.

Why the estate could not see it
-------------------------------
The whole fixture estate holds exactly TWO infrastructure exposures. A scan of
all 505 fixture parquets for ``product_type`` matching ``INFRASTRUCTURE`` (or a
``True`` ``is_infrastructure`` column) returns ``LOAN_INFRA_001`` and
``LOAN_SME_INFRA_001``, both in ``tests/fixtures/exposures/loans.parquet``.
Their counterparties — ``CORP_INFRA_001`` and ``CP_SME_INFRA_001``
(``tests/fixtures/counterparty/corporate.py``) — are both
``entity_type="corporate"`` with ``default_status=False``, so both are eligible
under criterion (a) and neither moves. No fixture has ever carried an
INELIGIBLE infrastructure exposure, which is exactly why the gap shipped: the
absence of a failing test was caused by the absence of the data, not by the
absence of a defect (LESSONS B5).

The seven legs
--------------
Every leg carries ``product_type="INFRASTRUCTURE_LOAN"``, so every leg is an
infrastructure CANDIDATE (``is_infrastructure=True``) and the four ineligible
ones can only stay at 1.0 by being gated. ``test_p1_211_every_leg_is_an_
infrastructure_candidate`` asserts that precondition, without which the four
negative legs would be vacuous.

    leg    class                 default  RW    pre-fix SF  post-fix SF  role
    CORP   corporate                no    1.00     0.75        0.75      SURVIVES (positive control)
    SME    corporate_sme            no    1.00     0.75        0.75      SURVIVES (positive control)
    SL     specialised_lending      no    1.00     0.75        0.75      SURVIVES (positive control)
    DFLT   corporate               YES    1.50     0.75        1.00      MOVES  (+1,875,000, the largest)
    INST   institution              no    1.00     0.75        1.00      MOVES  (+1,000,000)
    RETL   retail_other             no    0.75     0.75        1.00      MOVES  (+46,875)
    RRE    retail_mortgage          no    0.35     0.75        1.00      MOVES  (+35,000)

Portfolio RWEA: 26,452,500 correct vs 23,495,625 pre-fix — **2,956,875 of RWEA
was being removed with no eligibility basis**. Both figures are asserted, so the
magnitude is measured rather than narrated.

``DFLT`` is the leg a class-only gate would miss, and it is the largest mover.
A defaulted corporate keeps ``exposure_class == "corporate"`` in the engine —
the "defaulted exposures" C 07.00 sheet is a reporting-side derivation, not an
engine class — so criterion (a)'s "with the exclusion of exposures in default"
limb is INDEPENDENTLY necessary. ``test_p1_211_the_defaulted_leg_is_still_
classified_corporate`` pins that, so the leg cannot silently become a
class-limb test.

The three SURVIVES legs are not decoration. Without them this module would pass
against an implementation that removed the infrastructure factor altogether;
each one discriminates a different way of over-shooting:

- ``CORP``  — infra factor deleted outright would give 1.00, not 0.75.
- ``SME``   — the leg is eligible for BOTH factors, so a deleted infra factor
  falls back to the Art. 501 SME tier-1 0.7619 rather than to 1.00. It is the
  only leg that distinguishes "infra factor gone" from "infra factor kept".
- ``SL``    — criterion (a) names TWO classes. A gate written against corporate
  alone passes every other leg here and moves only this one.

Regime coverage: Art. 501a is CRR-only. Under Basel 3.1 the pack's
``supporting_factors`` Feature is disabled, so every leg returns 1.0 for a
SECOND, independent reason. ``TestP1211Basel31`` pins that, and is the reason
the CRR assertions above cannot be read as regime-invariant (LESSONS C7).

Why no parquet fixture
----------------------
``tests/fixtures/**/*.parquet`` are gitignored build artifacts. This module
builds its bundle from in-module DataFrame factories and runs the real
``PipelineOrchestrator``, so it needs no generation step on a fresh clone —
the same choice ``tests/fixtures/p1_316`` documents. The reporting-side view of
this defect (C 07.00 col 0035 / 0217) is NOT covered here and needs a registered
portfolio; that is P1.373's scope, not this module's.

References:
    - CRR Art. 501a(1)(a) (crr.pdf PAGE_INDEX 418) — the eligibility criteria.
    - CRR Art. 501 (crr.pdf PAGE_INDEX 417) — the SME factor, for the SME leg.
    - CRR Art. 127 — the defaulted 150% RW carried by the DFLT leg.
    - src/rwa_calc/engine/supporting_factors.py: ``apply_factors``.
    - src/rwa_calc/engine/classify/attributes.py: the ``is_infrastructure``
      substring derivation.
    - IMPLEMENTATION_PLAN.md: P1.211.
    - LESSONS.md B2/B3 (anchor to the enum), B5 (the coverage gap), C11
      (assert the fixture's adequacy).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl
import pytest
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import CRM_EXIT_EDGE
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.engine.supporting_factors import SupportingFactorCalculator
from rwa_calc.rulebook import RulepackV0

#: CRR Art. 501a(1), transcribed from the article text quoted in the module
#: docstring ("shall be multiplied by a factor of 0,75"). Deliberately hand-
#: written rather than read from the pack: the pack value is itself checked
#: against this in ``test_p1_211_pack_infrastructure_factor_matches_the_article``,
#: and sourcing both sides from the pack would make that check circular
#: (LESSONS B3).
INFRA_FACTOR_FROM_ARTICLE = 0.75

#: CRR Art. 501a(1)(a): "included either in the corporate exposure class or in
#: the specialised lending exposures class". Written as ``ExposureClass``
#: members, never as bare strings — a hand-written string list would drift with
#: a rename exactly as ``C02_00_SA_CLASS_MAP`` did (LESSONS B2).
ART_501A_ELIGIBLE_CLASSES: frozenset[ExposureClass] = frozenset(
    {
        ExposureClass.CORPORATE,
        ExposureClass.CORPORATE_SME,
        ExposureClass.SPECIALISED_LENDING,
    }
)

_VALUE_DATE = date(2024, 1, 1)
_MATURITY_DATE = date(2034, 1, 1)
_CRR_REPORTING_DATE = date(2024, 12, 31)
_B31_REPORTING_DATE = date(2028, 12, 31)

#: Every leg is on an infrastructure-named product. That is the whole point:
#: ``is_infrastructure`` is a substring match on ``product_type``, so it fires
#: on all seven and only criterion (a) can hold the four ineligible ones at 1.0.
_PRODUCT_TYPE = "INFRASTRUCTURE_LOAN"


@dataclass(frozen=True)
class Leg:
    """One P1.211 exposure leg with its hand-calc and its role."""

    label: str
    expected_class: ExposureClass
    drawn: float
    expected_rw: float
    expected_factor: float
    pre_fix_factor: float
    role: str
    counterparty: dict
    loan_extra: dict = None  # type: ignore[assignment]

    @property
    def cp_ref(self) -> str:
        return f"P1211-CP-{self.label}"

    @property
    def loan_ref(self) -> str:
        return f"P1211-LN-{self.label}"

    @property
    def facility_ref(self) -> str:
        return f"P1211-FAC-{self.label}"

    @property
    def expected_rwa_pre_factor(self) -> float:
        return self.drawn * self.expected_rw

    @property
    def expected_rwa_final(self) -> float:
        return self.expected_rwa_pre_factor * self.expected_factor

    @property
    def pre_fix_rwa_final(self) -> float:
        return self.expected_rwa_pre_factor * self.pre_fix_factor

    @property
    def moves(self) -> bool:
        return self.expected_factor != self.pre_fix_factor


LEGS: dict[str, Leg] = {
    leg.label: leg
    for leg in (
        Leg(
            label="CORP",
            expected_class=ExposureClass.CORPORATE,
            drawn=10_000_000.0,
            expected_rw=1.00,
            expected_factor=0.75,
            pre_fix_factor=0.75,
            role="SURVIVES - Art. 501a(1)(a) corporate limb; a deleted factor gives 1.00",
            counterparty={"entity_type": "corporate", "annual_revenue": 200_000_000.0},
        ),
        Leg(
            label="SME",
            expected_class=ExposureClass.CORPORATE_SME,
            drawn=1_500_000.0,
            expected_rw=1.00,
            expected_factor=0.75,
            pre_fix_factor=0.75,
            role="SURVIVES - eligible for BOTH factors; a deleted infra factor gives 0.7619",
            counterparty={"entity_type": "corporate", "annual_revenue": 30_000_000.0},
        ),
        Leg(
            label="SL",
            expected_class=ExposureClass.SPECIALISED_LENDING,
            drawn=8_000_000.0,
            expected_rw=1.00,
            expected_factor=0.75,
            pre_fix_factor=0.75,
            role="SURVIVES - the second class in criterion (a); a corporate-only gate moves it",
            counterparty={"entity_type": "corporate", "annual_revenue": 200_000_000.0},
        ),
        Leg(
            label="DFLT",
            expected_class=ExposureClass.CORPORATE,
            drawn=5_000_000.0,
            expected_rw=1.50,
            expected_factor=1.00,
            pre_fix_factor=0.75,
            role="MOVES - the 'exclusion of exposures in default' limb, and the largest mover",
            counterparty={
                "entity_type": "corporate",
                "annual_revenue": 200_000_000.0,
                "default_status": True,
            },
        ),
        Leg(
            label="INST",
            expected_class=ExposureClass.INSTITUTION,
            drawn=4_000_000.0,
            expected_rw=1.00,
            expected_factor=1.00,
            pre_fix_factor=0.75,
            role="MOVES - outside criterion (a)'s class limb",
            counterparty={
                "entity_type": "bank",
                "is_financial_sector_entity": True,
                "total_assets": 500_000_000.0,
            },
        ),
        Leg(
            label="RETL",
            expected_class=ExposureClass.RETAIL_OTHER,
            drawn=250_000.0,
            expected_rw=0.75,
            expected_factor=1.00,
            pre_fix_factor=0.75,
            role="MOVES - retail is outside criterion (a)",
            counterparty={
                "entity_type": "individual",
                "is_natural_person": True,
                "is_managed_as_retail": True,
            },
        ),
        Leg(
            label="RRE",
            expected_class=ExposureClass.RETAIL_MORTGAGE,
            drawn=400_000.0,
            expected_rw=0.35,
            expected_factor=1.00,
            pre_fix_factor=0.75,
            role="MOVES - a property-secured class, outside criterion (a)",
            counterparty={
                "entity_type": "individual",
                "is_natural_person": True,
                "is_managed_as_retail": True,
            },
            loan_extra={"property_type": "residential", "ltv": 0.60},
        ),
    )
}

EXPECTED_PORTFOLIO_RWA: float = sum(leg.expected_rwa_final for leg in LEGS.values())
PRE_FIX_PORTFOLIO_RWA: float = sum(leg.pre_fix_rwa_final for leg in LEGS.values())


# ---------------------------------------------------------------------------
# Portfolio factories
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """One counterparty per leg — the class axis is a counterparty property."""
    rows = []
    for leg in LEGS.values():
        row: dict = {
            "counterparty_reference": leg.cp_ref,
            "counterparty_name": f"P1.211 {leg.label}",
            "country_code": "GB",
            "local_currency": "GBP",
            "default_status": False,
            "apply_fi_scalar": False,
            "is_managed_as_retail": False,
        }
        row.update(leg.counterparty)
        rows.append(row)
    return pl.DataFrame(rows)


def _facilities() -> pl.DataFrame:
    """One fully-drawn parent facility per leg, all on the infrastructure product."""
    return pl.DataFrame(
        [
            {
                "facility_reference": leg.facility_ref,
                "product_type": _PRODUCT_TYPE,
                "book_code": "CORP_LENDING",
                "counterparty_reference": leg.cp_ref,
                "value_date": _VALUE_DATE,
                "maturity_date": _MATURITY_DATE,
                "currency": "GBP",
                "limit": leg.drawn,
                "committed": True,
                "lgd": 0.45,
                "beel": 0.0,
                "is_revolving": False,
                "seniority": "senior",
                "risk_type": "MR",
            }
            for leg in LEGS.values()
        ]
    )


def _loans() -> pl.DataFrame:
    """One fully-drawn GBP loan per leg. EAD = drawn_amount (interest is zero)."""
    rows = []
    for leg in LEGS.values():
        row: dict = {
            "loan_reference": leg.loan_ref,
            "counterparty_reference": leg.cp_ref,
            "product_type": _PRODUCT_TYPE,
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY_DATE,
            "drawn_amount": leg.drawn,
            "interest": 0.0,
            "seniority": "senior",
        }
        row.update(leg.loan_extra or {})
        rows.append(row)
    return pl.DataFrame(rows)


def _facility_mappings() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "parent_facility_reference": leg.facility_ref,
                "child_reference": leg.loan_ref,
                "child_type": "loan",
            }
            for leg in LEGS.values()
        ]
    )


def _specialised_lending() -> pl.DataFrame:
    """The SL row is what moves that leg into ``SPECIALISED_LENDING``."""
    return pl.DataFrame(
        [
            {
                "counterparty_reference": LEGS["SL"].cp_ref,
                "sl_type": "project_finance",
                "project_phase": "operational",
                "slotting_category": "strong",
                "is_hvcre": False,
            }
        ]
    )


def _collateral() -> pl.DataFrame:
    """Property collateral on the RRE leg.

    ``is_mortgage`` (engine/classify/attributes.py) reads the hierarchy's
    property-collateral aggregates, not the loan's ``property_type``/``ltv``,
    so without this row the RRE leg lands in ``RETAIL_OTHER`` and the module
    loses its property-secured class entirely.
    """
    return pl.DataFrame(
        [
            {
                "collateral_reference": "P1211-COLL-RRE",
                "collateral_type": "real_estate",
                "property_type": "residential",
                "market_value": 666_667.0,
                "property_ltv": 0.60,
                "beneficiary_type": "loan",
                "beneficiary_reference": LEGS["RRE"].loan_ref,
                "is_eligible_irb_collateral": True,
            }
        ]
    )


def _run(config: CalculationConfig) -> dict[str, dict]:
    """Run the seven legs through ``PipelineOrchestrator``, keyed by loan reference."""
    bundle = make_raw_bundle(
        counterparties=_counterparties(),
        facilities=_facilities(),
        loans=_loans(),
        facility_mappings=_facility_mappings(),
        specialised_lending=_specialised_lending(),
        collateral=_collateral(),
    )
    df = PipelineOrchestrator().run_with_data(bundle, config).results.collect()
    return {row["exposure_reference"]: row for row in df.iter_rows(named=True)}


@pytest.fixture(scope="module")
def crr_results() -> dict[str, dict]:
    """The seven legs under CRR, where Art. 501/501a are live."""
    return _run(CalculationConfig.crr(reporting_date=_CRR_REPORTING_DATE))


@pytest.fixture(scope="module")
def b31_results() -> dict[str, dict]:
    """The same seven legs under Basel 3.1, where supporting factors are withdrawn."""
    return _run(CalculationConfig.basel_3_1(reporting_date=_B31_REPORTING_DATE))


# ---------------------------------------------------------------------------
# Adequacy — without these the negative legs prove nothing
# ---------------------------------------------------------------------------


class TestP1211FixtureAdequacy:
    """The preconditions that stop this module being vacuous (LESSONS C11)."""

    def test_p1_211_every_leg_is_an_infrastructure_candidate(
        self, crr_results: dict[str, dict]
    ) -> None:
        """All seven rows must carry ``is_infrastructure=True``.

        This is the load-bearing precondition. ``is_infrastructure`` is derived
        from a ``product_type`` substring match with no class or default
        condition, so a row that failed to set it would sit at factor 1.0 for
        the WRONG reason and the four MOVES legs would pass under the pre-fix
        engine too.
        """
        flags = {
            label: crr_results[leg.loan_ref]["is_infrastructure"] for label, leg in LEGS.items()
        }

        assert all(flags.values()), (
            f"every leg must be an infrastructure candidate, got {flags} - a leg with "
            "is_infrastructure False or null is held at 1.0 by the flag, not by "
            "Art. 501a(1)(a), and proves nothing about the eligibility gate"
        )

    def test_p1_211_every_leg_lands_in_its_intended_class(
        self, crr_results: dict[str, dict]
    ) -> None:
        """Each leg reaches the ``exposure_class`` its role claims.

        The class axis is the thing under test, so a leg that silently
        reclassified would move this module's population without moving a
        single assertion in it.
        """
        actual = {label: crr_results[leg.loan_ref]["exposure_class"] for label, leg in LEGS.items()}
        expected = {label: leg.expected_class.value for label, leg in LEGS.items()}

        assert actual == expected

    def test_p1_211_the_portfolio_spans_both_sides_of_criterion_a(
        self, crr_results: dict[str, dict]
    ) -> None:
        """At least one eligible and one ineligible leg, per Art. 501a(1)(a).

        A portfolio entirely on one side of the gate cannot distinguish a
        correct gate from an absent one (eligible-only) or from one that
        disabled the factor (ineligible-only).
        """
        observed = {
            ExposureClass(crr_results[leg.loan_ref]["exposure_class"]) for leg in LEGS.values()
        }

        assert observed & ART_501A_ELIGIBLE_CLASSES, (
            "no eligible leg - the gate cannot be shown to pass anything"
        )
        assert observed - ART_501A_ELIGIBLE_CLASSES, (
            "no ineligible leg - the gate cannot be shown to stop anything"
        )

    def test_p1_211_the_defaulted_leg_is_still_classified_corporate(
        self, crr_results: dict[str, dict]
    ) -> None:
        """The DFLT leg is ``corporate`` AND defaulted — the class-only blind spot.

        This is why criterion (a)'s two limbs are independently necessary. The
        engine has no "defaulted" exposure class (``ExposureClass.DEFAULTED``
        exists but a defaulted corporate does not receive it — the C 07.00
        defaulted sheet is a reporting-side derivation), so a gate written on
        class alone lets the largest ineligible exposure in this portfolio
        through.
        """
        row = crr_results[LEGS["DFLT"].loan_ref]

        assert row["exposure_class"] == ExposureClass.CORPORATE.value
        assert row["is_defaulted"] is True
        assert ExposureClass(row["exposure_class"]) in ART_501A_ELIGIBLE_CLASSES, (
            "the defaulted leg must sit INSIDE the class limb, otherwise the class "
            "test alone would catch it and the default limb is untested here"
        )

    def test_p1_211_the_crr_run_raises_no_errors(self, crr_results: dict[str, dict]) -> None:
        """Sanity: seven rows in, seven rows out, none dropped by the pipeline.

        A vanished row is neither a result nor an error (LESSONS C9), and every
        leg lookup below would then ``KeyError`` rather than assert.
        """
        assert len(crr_results) == len(LEGS)
        assert set(crr_results) == {leg.loan_ref for leg in LEGS.values()}


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------


class TestP1211Art501aEligibilityGate:
    """Art. 501a(1)(a) applied end to end through ``PipelineOrchestrator``."""

    @pytest.mark.parametrize("label", sorted(LEGS))
    def test_p1_211_supporting_factor_per_leg(
        self, crr_results: dict[str, dict], label: str
    ) -> None:
        """Each leg's supporting factor, at an absolute expected value.

        Absolute rather than relative: a baseline comparison
        (``defaulted_rwa > performing_rwa``) is satisfied by the 150% default
        risk weight alone and would stay green with the factor still applied
        (LESSONS C1).
        """
        leg = LEGS[label]
        row = crr_results[leg.loan_ref]

        assert row["supporting_factor"] == pytest.approx(leg.expected_factor), leg.role

    @pytest.mark.parametrize("label", sorted(LEGS))
    def test_p1_211_rwa_final_per_leg(self, crr_results: dict[str, dict], label: str) -> None:
        """Each leg's RWEA, at an absolute expected value.

        Asserted alongside the factor because a fix that flags eligibility
        correctly but still multiplies would leave ``supporting_factor``
        right and ``rwa_final`` wrong.
        """
        leg = LEGS[label]
        row = crr_results[leg.loan_ref]

        assert row["ead_final"] == pytest.approx(leg.drawn)
        assert row["risk_weight"] == pytest.approx(leg.expected_rw)
        assert row["rwa_pre_factor"] == pytest.approx(leg.expected_rwa_pre_factor)
        assert row["rwa_final"] == pytest.approx(leg.expected_rwa_final), leg.role

    @pytest.mark.parametrize("label", sorted(LEGS))
    def test_p1_211_no_leg_publishes_a_null(self, crr_results: dict[str, dict], label: str) -> None:
        """Every money and flag cell in scope is non-null on every leg.

        A null and a legitimate zero are different claims, and absence is this
        project's dominant escape class (LESSONS B4). A gate implemented with
        an ``&`` over a nullable flag can turn a factor into a null rather than
        into 1.0, which reaches the submission as a missing RWEA.
        """
        row = crr_results[LEGS[label].loan_ref]
        cells = {
            name: row[name]
            for name in (
                "exposure_class",
                "is_infrastructure",
                "is_defaulted",
                "ead_final",
                "risk_weight",
                "rwa_pre_factor",
                "supporting_factor",
                "supporting_factor_applied",
                "rwa_final",
            )
        }

        assert all(value is not None for value in cells.values()), cells

    @pytest.mark.parametrize("label", sorted(LEGS))
    def test_p1_211_rwa_final_reconciles_to_the_factor(
        self, crr_results: dict[str, dict], label: str
    ) -> None:
        """``rwa_final == rwa_pre_factor x supporting_factor`` on every leg.

        Pins the two published quantities to each other, so neither can be
        corrected in isolation: a gate applied to the reported factor but not
        to the arithmetic (or the reverse) breaks this identity even where both
        cells look individually plausible.
        """
        row = crr_results[LEGS[label].loan_ref]

        assert row["rwa_final"] == pytest.approx(row["rwa_pre_factor"] * row["supporting_factor"])

    def test_p1_211_supporting_factor_applied_flag_tracks_the_gate(
        self, crr_results: dict[str, dict]
    ) -> None:
        """``supporting_factor_applied`` is True on exactly the three eligible legs.

        The flag is what COREP C 07.00 cols 0216/0217 read, so an ineligible
        row left flagged is a reporting defect even once its RWEA is right.
        """
        applied = {
            label
            for label, leg in LEGS.items()
            if crr_results[leg.loan_ref]["supporting_factor_applied"]
        }

        assert applied == {"CORP", "SME", "SL"}

    def test_p1_211_portfolio_rwea_is_measured_not_narrated(
        self, crr_results: dict[str, dict]
    ) -> None:
        """The portfolio total, and the pre-fix total it is NOT.

        26,452,500 correct vs 23,495,625 with criterion (a) unapplied — the
        ungated factor removed 2,956,875 of RWEA from a seven-exposure book, so
        own funds were understated. Asserting both ends stops the module
        reporting a direction it has not measured (LESSONS C8).
        """
        total = sum(row["rwa_final"] for row in crr_results.values())

        assert total == pytest.approx(EXPECTED_PORTFOLIO_RWA)
        assert total == pytest.approx(26_452_500.00)
        assert total != pytest.approx(PRE_FIX_PORTFOLIO_RWA)
        assert pytest.approx(2_956_875.00) == EXPECTED_PORTFOLIO_RWA - PRE_FIX_PORTFOLIO_RWA

    def test_p1_211_the_gate_is_not_a_blanket_withdrawal(
        self, crr_results: dict[str, dict]
    ) -> None:
        """Some relief must survive, or the gate has simply deleted the factor.

        The three eligible legs still receive 0.75, so the crossing amount
        between "gate applied" and "factor withdrawn" is non-zero and this
        module can tell the two apart (LESSONS C2).
        """
        relief = sum(row["rwa_pre_factor"] - row["rwa_final"] for row in crr_results.values())

        assert relief == pytest.approx(
            (10_000_000.0 + 1_500_000.0 + 8_000_000.0) * (1 - INFRA_FACTOR_FROM_ARTICLE)
        )
        assert relief == pytest.approx(4_875_000.00)


# ---------------------------------------------------------------------------
# The calculator in isolation — the whole class axis, anchored to the enum
# ---------------------------------------------------------------------------


def _one_row_frame(exposure_class: str, *, is_defaulted: bool = False) -> pl.LazyFrame:
    """A single non-SME infrastructure exposure in ``exposure_class``.

    ``is_sme=False`` throughout, so the Art. 501 limb is off and the observed
    factor is attributable to the Art. 501a limb alone.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["ONE"],
            "counterparty_reference": ["CP"],
            "lending_group_reference": [None],
            "exposure_class": [exposure_class],
            "ead_final": [1_000_000.0],
            "drawn_amount": [1_000_000.0],
            "interest": [0.0],
            "residential_collateral_value": [0.0],
            "rwa_pre_factor": [1_000_000.0],
            "is_sme": [False],
            "is_infrastructure": [True],
            "is_buy_to_let": [False],
            "is_defaulted": [is_defaulted],
        },
        schema_overrides={"lending_group_reference": pl.String},
    )


def _factor_for(frame: pl.LazyFrame, config: CalculationConfig) -> float:
    return (
        SupportingFactorCalculator().apply_factors(frame, config).collect()["supporting_factor"][0]
    )


class TestP1211ClassAxisAgainstTheEnum:
    """Every ``ExposureClass`` member through ``apply_factors``.

    Parametrised over ``ExposureClass`` itself rather than over a hand-written
    list of class strings: a list written from the implementation would share
    its assumptions and validate nothing, and would not notice a class added to
    the enum later (LESSONS B2/B3).
    """

    @pytest.fixture()
    def crr_config(self) -> CalculationConfig:
        return CalculationConfig.crr(reporting_date=_CRR_REPORTING_DATE)

    @pytest.mark.parametrize("member", list(ExposureClass), ids=lambda m: m.value)
    def test_p1_211_only_the_two_named_classes_receive_the_factor(
        self, crr_config: CalculationConfig, member: ExposureClass
    ) -> None:
        """0.75 on exactly the classes Art. 501a(1)(a) names, 1.0 on all others.

        Sixteen cases, of which three expect the factor. The thirteen negatives
        are the coverage the estate never had.
        """
        expected = INFRA_FACTOR_FROM_ARTICLE if member in ART_501A_ELIGIBLE_CLASSES else 1.0

        actual = _factor_for(_one_row_frame(member.value), crr_config)

        assert actual == pytest.approx(expected), (
            f"{member.value} is {'in' if member in ART_501A_ELIGIBLE_CLASSES else 'outside'} "
            "Art. 501a(1)(a)'s class limb"
        )

    @pytest.mark.parametrize(
        "member", sorted(ART_501A_ELIGIBLE_CLASSES, key=lambda m: m.value), ids=lambda m: m.value
    )
    def test_p1_211_default_excludes_an_otherwise_eligible_class(
        self, crr_config: CalculationConfig, member: ExposureClass
    ) -> None:
        """ "with the exclusion of exposures in default" — on each eligible class.

        Run on the class limb's own members, so the 1.0 can only come from the
        default limb. Paired with the previous test, which gives the same rows
        0.75 when performing, this isolates the default condition to one
        varied input.
        """
        performing = _factor_for(_one_row_frame(member.value), crr_config)
        defaulted = _factor_for(_one_row_frame(member.value, is_defaulted=True), crr_config)

        assert performing == pytest.approx(INFRA_FACTOR_FROM_ARTICLE)
        assert defaulted == pytest.approx(1.0)

    @pytest.mark.parametrize(
        "member", sorted(ART_501A_ELIGIBLE_CLASSES, key=lambda m: m.value), ids=lambda m: m.value
    )
    def test_p1_211_the_class_limb_is_case_insensitive(
        self, crr_config: CalculationConfig, member: ExposureClass
    ) -> None:
        """An UPPERCASE ``exposure_class`` reaches the same verdict as lowercase.

        Not decoration. The class limb is the only new consumer of
        ``exposure_class`` in this module, and every other comparison on that
        column in ``engine/sa/`` normalises case first —
        ``risk_weights.py:1044`` (``str.to_uppercase()``) and ``:1626``
        (``fill_null("").str.to_uppercase()``). A limb written as a bare
        ``is_in`` against the lowercase enum values would be the odd one out in
        its own package, and would silently DENY the factor to an eligible
        exposure whose class arrived in another case. The estate depends on the
        tolerance: 273 ``exposure_class="<UPPERCASE>"`` call sites across 21
        test files, all routed through
        ``tests/fixtures/single_exposure.py``.

        Measured: a bare lowercase ``is_in`` returned 1.0 here and broke
        ``test_crr_sa.py::TestInfrastructureSupportingFactor`` and
        ``::TestSupportingFactorPriority``.
        """
        lower = _factor_for(_one_row_frame(member.value), crr_config)
        upper = _factor_for(_one_row_frame(member.value.upper()), crr_config)

        assert lower == pytest.approx(INFRA_FACTOR_FROM_ARTICLE)
        assert upper == pytest.approx(lower), (
            f"{member.value.upper()} was denied the Art. 501a factor that "
            f"{member.value} received - the class limb is case-sensitive where its "
            "siblings in engine/sa/risk_weights.py are not"
        )

    def test_p1_211_an_ineligible_class_stays_ineligible_in_either_case(
        self, crr_config: CalculationConfig
    ) -> None:
        """Case-folding must not become a way IN for a class outside criterion (a).

        The mirror of the test above: a normalisation that widened the match —
        a substring test, or folding both sides to something that collides —
        would let ``institution`` through. Uses the largest ineligible class in
        the portfolio above.
        """
        for spelling in (
            ExposureClass.INSTITUTION.value,
            ExposureClass.INSTITUTION.value.upper(),
        ):
            assert _factor_for(_one_row_frame(spelling), crr_config) == pytest.approx(1.0), spelling

    def test_p1_211_eligible_classes_are_real_enum_members(self) -> None:
        """The eligible set is drawn from ``ExposureClass``, not from free text.

        Guards the module's own anchor: if a member is renamed,
        ``ART_501A_ELIGIBLE_CLASSES`` moves with it and this test stays green,
        whereas a string list would silently start matching nothing.
        """
        assert set(ExposureClass) > ART_501A_ELIGIBLE_CLASSES
        assert {m.value for m in ART_501A_ELIGIBLE_CLASSES} <= {m.value for m in ExposureClass}

    def test_p1_211_pack_infrastructure_factor_matches_the_article(self) -> None:
        """The rulepack's multiplier is the 0,75 CRR Art. 501a(1) states.

        The one place the pack value is checked against primary text, so the
        hand-written ``INFRA_FACTOR_FROM_ARTICLE`` used by every expectation
        above is not merely a restatement of the pack (LESSONS A4/B3).
        """
        pack = RulepackV0.from_config(
            CalculationConfig.crr(reporting_date=_CRR_REPORTING_DATE)
        ).pack

        value = pack.formula("supporting_factors_values").params["infrastructure_factor"]

        assert float(value) == pytest.approx(INFRA_FACTOR_FROM_ARTICLE)


class TestP1211ClassColumnIsAlwaysAvailable:
    """The class limb must bind in production, not fall back to "eligible"."""

    @pytest.mark.parametrize("column", ["exposure_class", "is_defaulted", "is_infrastructure"])
    def test_p1_211_criterion_a_inputs_are_required_crm_exit_columns(self, column: str) -> None:
        """Art. 501a(1)(a)'s inputs are all sealed, required ``crm_exit`` columns.

        ``apply_factors`` guards each of them for presence so minimal harness
        frames stay constructible. A presence guard on a column production
        never supplies is silent forever (LESSONS B1) — here the reverse must
        hold: the guard's permissive fallback must be unreachable from the
        pipeline. Anchored on the edge contract rather than on a pipeline run,
        because the contract is what makes it true for EVERY portfolio.
        """
        spec = CRM_EXIT_EDGE.columns.get(column)

        assert spec is not None, f"{column} is not on the crm_exit edge"
        assert spec.required, f"{column} is optional on crm_exit - the fallback is reachable"

    def test_p1_211_the_pipeline_frame_carries_criterion_a_inputs(
        self, crr_results: dict[str, dict]
    ) -> None:
        """And the columns are actually present on a real run's output."""
        row = next(iter(crr_results.values()))

        assert {"exposure_class", "is_defaulted", "is_infrastructure"} <= set(row)


# ---------------------------------------------------------------------------
# Regime control
# ---------------------------------------------------------------------------


class TestP1211Basel31:
    """Art. 501a is CRR-only; Basel 3.1 withdraws supporting factors entirely."""

    def test_p1_211_no_leg_receives_a_supporting_factor_under_basel_31(
        self, b31_results: dict[str, dict]
    ) -> None:
        """Every leg — eligible or not — sits at 1.0 under Basel 3.1.

        A second, independent reason the CRR figures above are regime-specific:
        the pack's ``supporting_factors`` Feature is off, so this cannot be read
        as evidence about criterion (a) (LESSONS C7).
        """
        factors = {
            label: b31_results[leg.loan_ref]["supporting_factor"] for label, leg in LEGS.items()
        }

        assert set(factors.values()) == {1.0}
        assert not any(
            b31_results[leg.loan_ref]["supporting_factor_applied"] for leg in LEGS.values()
        )

    def test_p1_211_basel_31_rwea_is_unreduced(self, b31_results: dict[str, dict]) -> None:
        """``rwa_final == rwa_pre_factor`` on every leg under Basel 3.1."""
        for leg in LEGS.values():
            row = b31_results[leg.loan_ref]
            assert row["rwa_final"] == pytest.approx(row["rwa_pre_factor"]), leg.label

    def test_p1_211_the_basel_31_pack_disables_supporting_factors(self) -> None:
        """The mechanism behind the two assertions above, stated at its source."""
        pack = RulepackV0.from_config(
            CalculationConfig.basel_3_1(reporting_date=_B31_REPORTING_DATE)
        ).pack

        assert pack.feature("supporting_factors") is False


# ---------------------------------------------------------------------------
# The IRB branch — same gate, different calculator
# ---------------------------------------------------------------------------
#
# Every leg above routes ``approach_applied="standardised"``, so on its own this
# module would be SA-only. ``apply_factors`` is called from THREE calculators —
# ``engine/sa/factors_output.py``, ``engine/irb/calculator.py`` and
# ``engine/slotting/calculator.py`` — and the wrongly-relieved population
# included an A-IRB row. So the branch is its own axis and gets its own
# portfolio rather than a re-parametrisation of the one above: adding model
# permissions to that bundle would re-route CORP / SME / SL to IRB and move
# every hand-calc in it.
#
# The slotting third of the triple is covered by the SL leg's class
# (``specialised_lending``) in the SA portfolio plus
# ``tests/unit/test_slotting_supporting_factors.py``, which drives
# ``SlottingCalculator.calculate_branch`` directly.
# ---------------------------------------------------------------------------

_MODEL_ID = "TEST_FULL_IRB"  # must match create_full_irb_model_permissions


@dataclass(frozen=True)
class IRBLeg:
    """One IRB-branch leg: expected approach, class and factor verdict."""

    label: str
    expected_class: ExposureClass
    expected_approach: str
    drawn: float
    internal_pd: float
    expected_factor: float
    pre_fix_factor: float
    role: str
    counterparty: dict
    loan_extra: dict

    @property
    def cp_ref(self) -> str:
        return f"P1211I-CP-{self.label}"

    @property
    def loan_ref(self) -> str:
        return f"P1211I-LN-{self.label}"


#: ``AIRBRET`` is the shape the golden reporting portfolio's ``RP-LN-AIRB-RET``
#: has: a retail obligor with a firm LGD estimate, routed A-IRB, landing in
#: ``retail_other`` — outside Art. 501a(1)(a). It reproduces that row's RWEA to
#: the cent (15,245.715359645234), which is how this portfolio is tied to the
#: production measurement rather than merely resembling it.
IRB_LEGS: dict[str, IRBLeg] = {
    leg.label: leg
    for leg in (
        IRBLeg(
            label="FIRB",
            expected_class=ExposureClass.CORPORATE,
            expected_approach="foundation_irb",
            drawn=50_000_000.0,
            internal_pd=0.0075,
            expected_factor=0.75,
            pre_fix_factor=0.75,
            role="SURVIVES - corporate under F-IRB is inside criterion (a)",
            counterparty={"entity_type": "corporate", "annual_revenue": 200_000_000.0},
            loan_extra={},
        ),
        IRBLeg(
            label="AIRB",
            expected_class=ExposureClass.CORPORATE_SME,
            expected_approach="advanced_irb",
            drawn=20_000_000.0,
            internal_pd=0.0100,
            expected_factor=0.75,
            pre_fix_factor=0.75,
            role="SURVIVES - corporate_sme under A-IRB is inside criterion (a)",
            counterparty={"entity_type": "corporate", "annual_revenue": 30_000_000.0},
            loan_extra={"lgd": 0.30, "has_sufficient_collateral_data": True},
        ),
        IRBLeg(
            label="AIRBRET",
            expected_class=ExposureClass.RETAIL_OTHER,
            expected_approach="advanced_irb",
            drawn=100_000.0,
            internal_pd=0.0050,
            expected_factor=1.00,
            pre_fix_factor=0.75,
            role="MOVES - the RP-LN-AIRB-RET shape; retail is outside criterion (a)",
            counterparty={
                "entity_type": "individual",
                "is_natural_person": True,
                "is_managed_as_retail": True,
            },
            loan_extra={"lgd": 0.20, "has_sufficient_collateral_data": True},
        ),
    )
}

#: Measured through ``PipelineOrchestrator``, not hand-derived: these are IRB
#: formula outputs (Art. 153 / 154), so the only honest source for them is a
#: run. The FACTOR verdicts above are the hand-derived part.
_AIRBRET_RWA_CORRECT = 15_245.715359645234
_AIRBRET_RWA_PRE_FIX = _AIRBRET_RWA_CORRECT * 0.75  # 11,434.29
_AIRBRET_RWA_RESTORED = _AIRBRET_RWA_CORRECT - _AIRBRET_RWA_PRE_FIX  # 3,811.43


def _irb_counterparties() -> pl.DataFrame:
    rows = []
    for leg in IRB_LEGS.values():
        row: dict = {
            "counterparty_reference": leg.cp_ref,
            "counterparty_name": f"P1.211 IRB {leg.label}",
            "country_code": "GB",
            "local_currency": "GBP",
            "default_status": False,
            "apply_fi_scalar": False,
            "is_managed_as_retail": False,
        }
        row.update(leg.counterparty)
        rows.append(row)
    return pl.DataFrame(rows)


def _irb_loans() -> pl.DataFrame:
    rows = []
    for leg in IRB_LEGS.values():
        row: dict = {
            "loan_reference": leg.loan_ref,
            "counterparty_reference": leg.cp_ref,
            "product_type": _PRODUCT_TYPE,
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY_DATE,
            "drawn_amount": leg.drawn,
            "interest": 0.0,
            "seniority": "senior",
        }
        row.update(leg.loan_extra)
        rows.append(row)
    return pl.DataFrame(rows)


def _irb_ratings() -> pl.DataFrame:
    """Internal PD + ``model_id`` — what routes each leg onto the IRB branch."""
    return pl.DataFrame(
        [
            {
                "rating_reference": f"P1211I-RTG-{leg.label}",
                "counterparty_reference": leg.cp_ref,
                "rating_type": "internal",
                "pd": leg.internal_pd,
                "model_id": _MODEL_ID,
            }
            for leg in IRB_LEGS.values()
        ]
    )


@pytest.fixture(scope="module")
def irb_crr_results() -> dict[str, dict]:
    """The three IRB legs under CRR."""
    bundle = make_raw_bundle(
        counterparties=_irb_counterparties(),
        loans=_irb_loans(),
        ratings=_irb_ratings(),
        model_permissions=create_full_irb_model_permissions(),
    )
    df = (
        PipelineOrchestrator()
        .run_with_data(bundle, CalculationConfig.crr(reporting_date=_CRR_REPORTING_DATE))
        .results.collect()
    )
    return {row["exposure_reference"]: row for row in df.iter_rows(named=True)}


class TestP1211IRBBranch:
    """Criterion (a) binds on ``engine/irb/calculator.py`` too."""

    def test_p1_211_irb_legs_actually_route_to_the_irb_branch(
        self, irb_crr_results: dict[str, dict]
    ) -> None:
        """Adequacy: no leg silently fell back to SA.

        Without model permissions or an internal PD these rows route
        ``standardised``, which would make this class a duplicate of the SA
        portfolio above wearing different references — green, and proving
        nothing about ``engine/irb/calculator.py``.
        """
        approaches = {
            label: irb_crr_results[leg.loan_ref]["approach_applied"]
            for label, leg in IRB_LEGS.items()
        }

        assert approaches == {label: leg.expected_approach for label, leg in IRB_LEGS.items()}
        assert "standardised" not in set(approaches.values())

    def test_p1_211_every_irb_leg_is_an_infrastructure_candidate(
        self, irb_crr_results: dict[str, dict]
    ) -> None:
        """The same load-bearing precondition as the SA portfolio."""
        flags = {
            label: irb_crr_results[leg.loan_ref]["is_infrastructure"]
            for label, leg in IRB_LEGS.items()
        }

        assert all(flags.values()), flags

    @pytest.mark.parametrize("label", sorted(IRB_LEGS))
    def test_p1_211_irb_supporting_factor_per_leg(
        self, irb_crr_results: dict[str, dict], label: str
    ) -> None:
        """Class and default verdicts are identical on the IRB branch."""
        leg = IRB_LEGS[label]
        row = irb_crr_results[leg.loan_ref]

        assert row["exposure_class"] == leg.expected_class.value
        assert row["supporting_factor"] == pytest.approx(leg.expected_factor), leg.role

    @pytest.mark.parametrize("label", sorted(IRB_LEGS))
    def test_p1_211_irb_rwa_final_reconciles_to_the_factor(
        self, irb_crr_results: dict[str, dict], label: str
    ) -> None:
        """``rwa_final == rwa_pre_factor x supporting_factor``, non-null throughout.

        The identity rather than a hand-calc: ``rwa_pre_factor`` here is an
        Art. 153/154 formula output, so re-deriving it in the test would only
        restate the engine. What this module owns is the FACTOR, and the
        identity is what ties the factor to the published RWEA.
        """
        row = irb_crr_results[IRB_LEGS[label].loan_ref]

        assert row["rwa_pre_factor"] is not None
        assert row["supporting_factor"] is not None
        assert row["rwa_final"] is not None
        assert row["rwa_final"] == pytest.approx(row["rwa_pre_factor"] * row["supporting_factor"])

    def test_p1_211_the_airb_retail_leg_reproduces_the_production_row(
        self, irb_crr_results: dict[str, dict]
    ) -> None:
        """AIRBRET ties to ``RP-LN-AIRB-RET``, the sixth wrongly-relieved row.

        The golden reporting portfolio's A-IRB retail row, measured with every
        loan on an infrastructure product, carries RWEA 15,245.715359645234 and
        was being relieved to 11,434.29 — 3,811.43 of capital removed from one
        retail exposure with no eligibility basis. Asserting the absolute figure
        AND the figure it must not be is what makes this leg a reproduction of
        that row rather than something merely shaped like it.
        """
        row = irb_crr_results[IRB_LEGS["AIRBRET"].loan_ref]

        assert row["supporting_factor"] == pytest.approx(1.0)
        assert row["rwa_final"] == pytest.approx(_AIRBRET_RWA_CORRECT)
        assert row["rwa_final"] != pytest.approx(_AIRBRET_RWA_PRE_FIX)
        assert pytest.approx(3_811.43, abs=0.01) == _AIRBRET_RWA_RESTORED

    def test_p1_211_the_irb_gate_is_not_a_blanket_withdrawal(
        self, irb_crr_results: dict[str, dict]
    ) -> None:
        """Two of three IRB legs keep the factor — the branch's positive control.

        Without this, an implementation that skipped ``apply_factors`` on the
        IRB branch entirely would satisfy every other assertion in this class.
        """
        applied = {
            label
            for label, leg in IRB_LEGS.items()
            if irb_crr_results[leg.loan_ref]["supporting_factor_applied"]
        }

        assert applied == {"FIRB", "AIRB"}
