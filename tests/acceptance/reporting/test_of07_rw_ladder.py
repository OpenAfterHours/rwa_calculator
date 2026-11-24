"""
C 07.00 / OF 07.00 risk-weight rungs that no other registered run reaches — the ladder book.

Pipeline position:
    build_reporting_rw_ladder_bundle() -> PipelineOrchestrator (``rw_ladder_config``)
        -> COREPGenerator -> C 07.00 / OF 07.00 rows 0140-0280
        -> rwa_filer's template-level rules (both regimes) and, under Basel 3.1,
           the gateway rules on the filed return

What is asserted, and the text it is asserted from:

- WEIGHT. Each leg's applied weight is the rung it exists for (PS1/26 Art. 121
  SCRA grade A 40%; Art. 129(5)(aa)/(b) 15% / 25%; Art. 122(6)(a)/(b) 65% /
  135%; Art. 122B(4) / (2)(c) 80% / 130%; Art. 123(3)(a) transactor 45%;
  Art. 124G Table 6B 40% / 105%; Art. 133(6)(c) 250%; Art. 132(2) 1250%; and
  their CRR counterparts). Without that, every assertion below is about a
  different book (LESSONS C11).
- ROW. Annex II rows 0140-0280 (PS1/26 Annex II pp.94-96; CRR Annex II C 07.00)
  name one weight each. A leg is reported on the row of its weight. The row
  carries col 0200 = the legs' exposure and col 0220 = col 0200 x the weight
  the row's LABEL names. The weights below come from the labels, not from the
  pack, so a pack value and a row placement cannot drift together (LESSONS B3).
- WHAT MUST NOT BE THERE. Row 0280 "Other risk weights" "is not available for
  the exposure classes Government, Corporates, Institutions and Retail" (both
  Annex IIs), and the Bank's ``boe_b0445`` closes it on the real-estate sheet
  too. Under Basel 3.1 the Bank's applicable-weights rules (``boe_b0440``,
  ``b0441``, ``b0442``, ``b0445``, ``b0450``, ``b0458`` and their ``_1`` twins)
  must hold on the filed return. That proves every leg sits on a row the Bank
  permits on its sheet. The template-level engine cannot evaluate those isNull
  rules, so they are read from the gateway engine.
- BINDING. Each rung rule this book exists for reaches a real PASS on a figure,
  not ``0 = 0``: the reason the book is in ``RUNS`` (LESSONS B5).

Not asserted: ``RWL-LN-RE-105``'s CRR row. CRR blends the Art. 125 part and the
remainder into one weight, which lands in row 0280 of the real-estate sheet.
Plan item P2.87 owns that placement, and this file stays off every cell the leg
could reach so it pins neither reading (LESSONS C1).

References:
- PS1/26 Annex II OF 07.00 rows 0140-0280; CRR Annex II C 07.00 rows 0140-0280
- tests/fixtures/reporting_rw_ladder_portfolio.py (the legs and ``LADDER``)
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import RUNS
from tests.fixtures.reporting_rw_ladder_portfolio import (
    EXPOSURE,
    LADDER,
    LN_RE_105,
    build_reporting_rw_ladder_bundle,
    rw_ladder_config,
)

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    build_canonical_return,
)
from rwa_calc.reporting.filing.checks import evaluate_all
from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS
from rwa_calc.reporting.pillar3.generator import Pillar3Generator
from rwa_filer.boe.engine import STATUS_FAIL as GATEWAY_FAIL
from rwa_filer.boe.engine import STATUS_PASS as GATEWAY_PASS
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate.evaluate import STATUS_PASS
from rwa_filer.validate.returns import validate_return

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_filer.validate.checker import ValidationReport

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FRAMEWORKS: tuple[str, ...] = ("CRR", "BASEL_3_1")
_REGIME_KEY: dict[str, str] = {"CRR": "crr", "BASEL_3_1": "b31"}
_SHEET_MAP: dict[str, str] = {"CRR": "c07", "BASEL_3_1": "of07"}
_TOTAL_Z = "0001"

#: The weight each Annex II row LABEL names (rows 0140-0280). Independent of the
#: pack on purpose.
_ROW_WEIGHT: dict[str, float] = {
    "0171": 0.15,
    "0180": 0.20,
    "0181": 0.25,
    "0190": 0.35,
    "0191": 0.40,
    "0192": 0.45,
    "0202": 0.65,
    "0220": 0.75,
    "0221": 0.80,
    "0230": 1.00,
    "0231": 1.05,
    "0233": 1.30,
    "0234": 1.35,
    "0250": 2.50,
    "0270": 12.50,
}

#: CRR cells ``RWL-LN-RE-105`` could reach once P2.87 splits its Art. 125 blend:
#: its own sheet, the retail rung its remainder could take, and the Total rows of
#: both. Unasserted here so the file pins neither reading.
_CRR_UNASSERTED: frozenset[tuple[str, str]] = frozenset(
    {("0010", row) for row in _ROW_WEIGHT}
    | {("0009", "0220"), (_TOTAL_Z, "0190"), (_TOTAL_Z, "0220")}
)

#: The rung rules this book exists to bind, per regime: the rules that were
#: VACUOUS on every other registered run. Basel 3.1 has two families, the
#: equality on the class sheets and ``>=`` on the Total, retail and real-estate
#: sheets.
_TARGET_RULES: dict[str, tuple[str, ...]] = {
    "CRR": ("v0327_m", "v0328_m"),
    "BASEL_3_1": (
        "boe_b0493",  # 15% r0171, sheet 0013
        "boe_b0494",  # 25% r0181, sheet 0013
        "boe_b0496",  # 40% r0191, sheet 0007
        "boe_b0499",  # 65% r0202, sheet 0008
        "boe_b0500",  # 80% r0221, sheet 0008
        "boe_b0504",  # 130% r0233, sheet 0008
        "boe_b0505",  # 135% r0234, sheet 0008
        "boe_b1018",  # >= 15%
        "boe_b1019",  # >= 25%
        "boe_b1021",  # >= 40%
        "boe_b1022",  # >= 45%, retail sheet 0009
        "boe_b1024",  # >= 65%
        "boe_b1025",  # >= 80%
        "boe_b1027",  # >= 105%, real-estate sheet 0010
        "boe_b1029",  # >= 130%
        "boe_b1030",  # >= 135%
    ),
}

#: Sheets on which row 0280 must hold nothing: Annex II's Government, Corporates,
#: Institutions and Retail in both regimes, plus real estate under Basel 3.1
#: (``boe_b0445``). The class sheets with a rung in this book.
_ROW_0280_CLOSED: dict[str, tuple[str, ...]] = {
    "CRR": ("0007", "0008", "0009"),
    "BASEL_3_1": ("0007", "0008", "0009", "0010"),
}

#: The Bank's applicable-weights rules over the OF 07.00 sheets this book fills.
_APPLICABLE_WEIGHT_RULES: tuple[str, ...] = (
    "boe_b0440",
    "boe_b0440_1",
    "boe_b0441",
    "boe_b0441_1",
    "boe_b0442",
    "boe_b0442_1",
    "boe_b0445",
    "boe_b0445_1",
    "boe_b0450",
    "boe_b0450_1",
    "boe_b0458",
    "boe_b0458_1",
)

#: A checksum-valid LEI, as the filing-mapping ratchet uses; no rule reads it.
_ENTITY_IDENTIFIER = "5493001KJTIIGC8Y1R12"

_MONEY_TOLERANCE = 1e-6


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@lru_cache(maxsize=2)
def _run(framework: str) -> tuple[pl.DataFrame, COREPTemplateBundle, ValidationReport]:
    """The book through the pipeline, C 07.00 / OF 07.00, and the template-level rules."""
    result = PipelineOrchestrator().run_with_data(
        build_reporting_rw_ladder_bundle(), rw_ladder_config(framework)
    )
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=framework,
        output_floor_summary=result.output_floor_summary,
    )
    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)
    return result.results.collect(), corep, evaluate_all(corep, pillar3, framework)


@lru_cache(maxsize=1)
def _gateway_statuses() -> dict[str, str]:
    """Rule id -> the gateway engine's status on the filed Basel 3.1 return."""
    _results, corep, _report = _run("BASEL_3_1")
    header = ReturnHeader(_ENTITY_IDENTIFIER, date(2027, 3, 31), FILING_MODULE)
    pack = resolve_release(FILING_MODULE, FILING_TAXONOMY).pack
    report = validate_return(build_canonical_return(corep, header, pack=pack).canonical, pack)
    assert report.report is not None, "no PRA001 rule book is packaged: nothing would be checked"
    return {result.rule_id: result.status for result in report.report.results}


def _sheet(framework: str, z_code: str) -> str:
    """The bundle key the publisher's z-code names (LESSONS B3: not spelled here)."""
    keys = SHEET_INDEX_MAPS[_SHEET_MAP[framework]][z_code].bundle_keys
    assert len(keys) == 1, f"{framework} z:{z_code} names {keys}"
    return keys[0]


def _cells(corep: COREPTemplateBundle, sheet: str, row_ref: str) -> dict[str, float | None]:
    """One row's cells on one emitted sheet; empty when the row is absent."""
    assert sheet in corep.c07_00, f"sheet {sheet!r} not emitted; got {sorted(corep.c07_00)}"
    matched = corep.c07_00[sheet].filter(pl.col("row_ref") == row_ref)
    return {} if matched.height == 0 else matched.row(0, named=True)


def _rung_cases() -> list[tuple[str, str, str]]:
    """(framework, z-code, row) for every rung a leg lands on, and its Total row."""
    cases: set[tuple[str, str, str]] = set()
    for framework in _FRAMEWORKS:
        for leg in LADDER.values():
            _weight, row = leg.crr if framework == "CRR" else leg.b31
            if row is None:
                continue
            for z_code in (leg.z_code, _TOTAL_Z):
                if framework == "CRR" and (z_code, row) in _CRR_UNASSERTED:
                    continue
                cases.add((framework, z_code, row))
    return sorted(cases)


def _expected_exposure(framework: str, z_code: str, row: str) -> float:
    """The exposure value the legs put on one (sheet, row): the hand calculation."""
    return sum(
        EXPOSURE[reference]
        for reference, leg in LADDER.items()
        if (leg.crr if framework == "CRR" else leg.b31)[1] == row
        and z_code in (leg.z_code, _TOTAL_Z)
    )


# ---------------------------------------------------------------------------
# Registration: the book is in the gate, under the config that lights it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("framework", _FRAMEWORKS)
def test_the_ladder_is_registered_in_the_supervisory_gate_with_its_own_config(
    framework: str,
) -> None:
    """LESSONS B5, third form: registered against ``_sa_config`` the 65% / 135% rows go dark."""
    # Arrange
    registered = [
        run
        for run in RUNS
        if run.framework == framework and run.build_bundle is build_reporting_rw_ladder_bundle
    ]

    # Act
    config = registered[0].build_config() if len(registered) == 1 else None

    # Assert
    assert len(registered) == 1, (
        f"the ladder is registered {len(registered)} time(s) under {framework}"
    )
    assert registered[0].regime == _REGIME_KEY[framework]
    assert registered[0].portfolio == "rw-ladder"
    assert registered[0].build_prior_config is None, "SA-only: a prior frame buys nothing"
    assert config is not None
    assert config.use_investment_grade_assessment is (framework == "BASEL_3_1")


# ---------------------------------------------------------------------------
# Adequacy (LESSONS C11): each leg takes the weight of its rung, unsplit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("framework", _FRAMEWORKS)
@pytest.mark.parametrize("reference", sorted(LADDER))
def test_each_leg_takes_the_weight_of_its_rung_on_one_unsplit_row(
    framework: str, reference: str
) -> None:
    """Without the weight, the row assertions below are about a different book."""
    # Arrange
    results = _run(framework)[0]
    weight, _row = LADDER[reference].crr if framework == "CRR" else LADDER[reference].b31

    # Act
    leg = results.filter(pl.col("exposure_reference") == reference)

    # Assert
    assert leg.height == 1, f"{reference}: {leg.height} result rows, expected one unsplit leg"
    assert leg["ead_final"][0] == pytest.approx(EXPOSURE[reference])
    assert leg["risk_weight"][0] == pytest.approx(weight)
    assert leg["rwa_final"][0] == pytest.approx(EXPOSURE[reference] * weight)


def test_the_re_105_leg_is_past_the_crr_art_125_clamp() -> None:
    """The row P2.87 asks for: a CRR residential leg whose LTV is above 80%."""
    # Arrange
    results = _run("CRR")[0]

    # Act
    leg = results.filter(pl.col("exposure_reference") == LN_RE_105)

    # Assert
    assert leg["ltv"][0] > 0.80
    assert leg["risk_weight"][0] > _ROW_WEIGHT["0190"], "no remainder above the clamp"


# ---------------------------------------------------------------------------
# The rows: each rung carries its legs at the weight its label names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("framework", "z_code", "row"), _rung_cases())
def test_each_targeted_rung_reports_its_exposure_at_its_own_weight(
    framework: str, z_code: str, row: str
) -> None:
    """Annex II: col 0220 = col 0200 x the row's weight, on a figure, absolute."""
    # Arrange
    corep = _run(framework)[1]
    expected = _expected_exposure(framework, z_code, row)

    # Act
    cells = _cells(corep, _sheet(framework, z_code), row)

    # Assert
    assert expected > 0, "the case names a rung no leg reaches"
    assert cells.get("0200") == pytest.approx(expected, abs=_MONEY_TOLERANCE)
    assert cells.get("0220") == pytest.approx(expected * _ROW_WEIGHT[row], abs=_MONEY_TOLERANCE)


@pytest.mark.parametrize(
    ("framework", "z_code"),
    [(framework, z_code) for framework in _FRAMEWORKS for z_code in _ROW_0280_CLOSED[framework]],
)
def test_row_0280_holds_nothing_on_a_sheet_annex_ii_closes_it(framework: str, z_code: str) -> None:
    """A leg off every rung would fall to row 0280; on these sheets that row does not exist."""
    # Arrange
    corep = _run(framework)[1]

    # Act
    cells = _cells(corep, _sheet(framework, z_code), "0280")

    # Assert
    assert cells.get("0200") is None
    assert cells.get("0220") is None


# ---------------------------------------------------------------------------
# The rules: each target binds on a figure; the Bank's placement rules hold
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("framework", "rule_id"),
    [(framework, rule_id) for framework in _FRAMEWORKS for rule_id in _TARGET_RULES[framework]],
)
def test_each_targeted_rung_rule_passes_on_a_figure(framework: str, rule_id: str) -> None:
    """PASS, not VACUOUS: the rule tests a reported figure rather than ``0 = 0``."""
    # Arrange
    report = _run(framework)[2]

    # Act
    statuses = {outcome.status for outcome in report.outcomes if outcome.rule_id == rule_id}

    # Assert
    assert statuses == {STATUS_PASS}


@pytest.mark.parametrize("rule_id", _APPLICABLE_WEIGHT_RULES)
def test_the_bank_permits_every_row_the_ladder_fills(rule_id: str) -> None:
    """``boe_b0440``-``b0458``: each leg sits on a row its sheet is allowed to carry."""
    # Arrange / Act
    status = _gateway_statuses().get(rule_id)

    # Assert
    assert status is not None, f"{rule_id} is not in the packaged PRA001 rule book"
    assert status != GATEWAY_FAIL


def test_the_gateway_evaluates_the_basel_3_1_rung_rules_on_figures() -> None:
    """The filed return carries every targeted rung: the gateway PASSes each rule."""
    # Arrange / Act
    statuses = _gateway_statuses()

    # Assert
    assert {rule: statuses.get(rule) for rule in _TARGET_RULES["BASEL_3_1"]} == dict.fromkeys(
        _TARGET_RULES["BASEL_3_1"], GATEWAY_PASS
    )
