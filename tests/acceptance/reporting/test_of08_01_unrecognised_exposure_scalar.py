"""
OF 08.01 column 0260 on F-IRB sheets at a non-zero unrecognised exposure scalar, through the gateway.

Pipeline position:
    registered Basel 3.1 portfolio (``RUNS``, ``irb-classes``) with a non-zero
    ``post_model_adjustments.unrecognised_exposure_scalar`` -> PipelineOrchestrator
        -> COREPGenerator -> filing.build_canonical_return
        -> rwa_filer trace_return (the gateway engine, ``rwa_filer.boe``)

The defect (P1.399). Since ``97b90fc`` an F-IRB or slotting sheet reports no
column 0254 (PS1/26 Annex II p.112: "This column shall not be reported for sheets
relating to the FIRB approach or the slotting approach"), but the engine still
multiplied the scalar into every formula-IRB leg's RWEA, F-IRB included. Column
0260 sums that RWEA, so on every F-IRB sheet it exceeded 0251 + 0252 + 0253 + 0254
by exactly the F-IRB uplift and the Bank's Error rule ``boe_b0751``
(``{OF08.01.01.01 c0260} i= isum({c0251;0252;0253;0254})``) failed. Measured on
this portfolio at a 5% scalar before the fix: 3,443,776.69 of F-IRB uplift, Total
F-IRB sheet 0002 out by that amount, ``boe_b0751`` FAIL 9 satisfied / 11
unsatisfied, every unsatisfied evaluation on sheet 0002, 0006 or 0012.

The engine was wrong, not the reporting: Art. 166D(6)(a)(ii) confines the
adjustment to facilities where "the institution would have applied the Advanced
IRB Approach in accordance with Article 147A". So the fix is in
``engine/irb/adjustments.py`` and this test holds both halves of it on a filed
return: no F-IRB leg carries the uplift, the A-IRB legs still do, and the rule
holds on every sheet it reads.

No registered run sets the scalar (its default is 0.0), which is why the register
and both ratchets were green over the defect. This module is the gate that sees
it.

References:
- PRA PS1/26 Art. 153(5A)(b), 154(4A)(c), 166D(6); Annex II §3.3.3 columns
  0251-0260 (pp.111-112)
- Bank of England taxonomy v4.1.1, table OF08.01.01.01; rule ``boe_b0751``
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from functools import cache
from typing import TYPE_CHECKING, NamedTuple

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import RUNS

from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.corep.irb_sheets import TOTAL_AIRB_KEY, TOTAL_FIRB_SLOTTING_KEY
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    build_canonical_return,
)
from rwa_filer.boe.engine import STATUS_PASS
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate.returns import trace_return

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_filer.boe.engine import Evaluation, RuleResult

HEADER = ReturnHeader("5493001KJTIIGC8Y1R12", date(2027, 3, 31), FILING_MODULE)
PORTFOLIO = "irb-classes"
RULE = "boe_b0751"
#: A non-zero firm election for the Art. 166D(6) adjustment.
SCALAR = Decimal("0.05")
#: The published codes of the F-IRB sheets this return files, with their Total.
FIRB_CODES = ("0002", "0006", "0012")
ADJUSTMENT = "unrecognised_exposure_adjustment"


class _Filed(NamedTuple):
    """The portfolio run at a non-zero scalar, generated and traced on the gateway."""

    ledger: pl.DataFrame
    corep: COREPTemplateBundle
    result: RuleResult
    evaluations: tuple[Evaluation, ...]


@cache
def _filed() -> _Filed:
    (run,) = [r for r in RUNS if r.framework == "BASEL_3_1" and r.portfolio == PORTFOLIO]
    config = run.build_config()
    config = replace(
        config,
        post_model_adjustments=replace(
            config.post_model_adjustments, unrecognised_exposure_scalar=SCALAR
        ),
    )
    outcome = PipelineOrchestrator().run_with_data(run.build_bundle(), config)
    corep = COREPGenerator().generate_from_lazyframe(
        outcome.results,
        framework=run.framework,
        output_floor_summary=outcome.output_floor_summary,
    )
    pack = resolve_release(FILING_MODULE, FILING_TAXONOMY).pack
    mapping = build_canonical_return(corep, HEADER, pack=pack)
    validation, trace = trace_return(mapping.canonical, pack)
    assert validation.report is not None and trace is not None, "no rule book for PRA001"
    (result,) = [r for r in validation.report.results if r.rule_id == RULE]
    evaluations = tuple(e for e in trace.evaluations if e.rule_id == RULE)
    return _Filed(outcome.results.collect(), corep, result, evaluations)


def _adjustment_by_approach(ledger: pl.DataFrame) -> dict[str, float]:
    return dict(ledger.group_by("approach_applied").agg(pl.col(ADJUSTMENT).sum()).iter_rows())


def _total_row(corep: COREPTemplateBundle, key: str) -> dict[str, float | None]:
    frame = corep.c08_01[key].filter(pl.col("row_ref") == "0010")
    return frame.select("0251", "0252", "0253", "0254", "0260").row(0, named=True)


def test_no_firb_leg_carries_the_uplift_and_the_airb_legs_still_do() -> None:
    # Arrange
    ledger = _filed().ledger
    firb = ledger.filter(pl.col("approach_applied") == ApproachType.FIRB.value)
    assert firb.height > 0 and firb["rwa_pre_adjustments"].sum() > 0, (
        "the portfolio holds no F-IRB RWEA: an F-IRB uplift could not be seen"
    )

    # Act
    by_approach = _adjustment_by_approach(ledger)

    # Assert
    assert by_approach[ApproachType.FIRB.value] == pytest.approx(0.0)
    assert by_approach[ApproachType.AIRB.value] > 0


def test_the_firb_total_sheet_rwea_foots_to_its_reported_components() -> None:
    # Arrange
    total = _total_row(_filed().corep, TOTAL_FIRB_SLOTTING_KEY)
    assert total["0260"], "the F-IRB Total sheet reports no RWEA: the identity is vacuous"

    # Act
    components = sum(total[column] or 0.0 for column in ("0251", "0252", "0253", "0254"))

    # Assert
    assert total["0254"] is None
    assert total["0260"] == pytest.approx(components)


def test_the_airb_total_sheet_still_reports_the_adjustment() -> None:
    # Arrange
    filed = _filed()
    on_airb_legs = _adjustment_by_approach(filed.ledger)[ApproachType.AIRB.value]

    # Act
    total = _total_row(filed.corep, TOTAL_AIRB_KEY)

    # Assert
    assert total["0254"] == pytest.approx(on_airb_legs)


def test_boe_b0751_holds_on_every_sheet_including_the_firb_ones() -> None:
    # Arrange
    filed = _filed()
    sheets = {dict(e.place).get("z") for e in filed.evaluations}
    assert sheets >= set(FIRB_CODES), (
        f"{RULE} was not evaluated on the F-IRB sheets {FIRB_CODES}: it read {sorted(sheets)}"
    )

    # Act
    broken = [(e.place, e.left_value, e.right_value) for e in filed.evaluations if not e.holds]

    # Assert
    assert broken == []
    assert filed.result.status == STATUS_PASS
