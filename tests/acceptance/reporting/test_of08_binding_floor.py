"""
A binding output floor leaves no add-on in any Basel 3.1 COREP template.

Pipeline position:
    registered Basel 3.1 portfolio (``RUNS``) -> PipelineOrchestrator
        -> COREPGenerator -> filing.build_canonical_return
        -> rwa_filer validate_return (the gateway engine, ``rwa_filer.boe``)
        and filing.checks.evaluate_all (the template-level engine)

PS1/26 Art. 92(2A)(a) makes the output floor a maximum over ENTITY totals —
"TREA = max {U-TREA; x . S-TREA + OF-ADJ}" — and Art. 92(3)(a) makes the
credit-risk part of U-TREA "the risk-weighted exposure amounts for credit risk
... calculated in accordance with Title II of Part Three". Annex II reports the
floor once, in OF 02.00 row 0010 column 0030 (p.29), and defines OF 08.01 col
0260 as col 0251 adjusted for cols 0252-0254 only (p.112). The engine spreads a
binding floor's shortfall over ``rwa_final`` (``engine/aggregator/_floor.py``);
every template RWEA reads the un-floored ``rwa_pre_floor`` instead.

``facility-share-binding`` is the one registered run whose floor binds (shortfall
453,708.71 on three F-IRB corporate legs). The three forced cases reach the
states no registered run does — slotting, A-IRB retail, defaulted, LFSE and
SA-CCR rows under a binding floor — by giving the firm an Art. 62(c) SA T2
credit (OF-ADJ = 12.5 x the credit), a real engine run with nothing edited.

Before the fix (measured 2026-11-16): OF 08.01 r0010 c0260 summed 1,559,200.00
against U-TREA 1,105,491.29 on facility-share-binding; STR007 on OF02.00.01.01 and
OF08.01.01.01; ``boe_b0621`` and ``boe_b0751`` FAILED on the gateway engine and
``boe_b0763`` on the template-level one.

References:
- PRA PS1/26 Appendix 1, Art. 92(2A) and 92(3) (pp.13-14)
- PRA PS1/26 Annex II, OF 02.00 row 0010 (p.29), OF 08.01 cols 0251-0260
  (pp.111-112), OF 08.06 col 0080 (p.129)
- PRA001 rules ``boe_b0621``, ``boe_b0751``, ``boe_b0763`` (taxonomy v4.1.1)
- tests/unit/reporting/corep/test_c08_output_floor_carrier.py
"""

from __future__ import annotations

import dataclasses
from datetime import date
from functools import cache
from typing import TYPE_CHECKING, NamedTuple

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import RUNS

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.c08_sheets import c08_class_sheets
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    build_canonical_return,
)
from rwa_calc.reporting.filing.checks import evaluate_all
from rwa_filer.boe.engine import STATUS_FAIL
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate import STATUS_FAIL as TEMPLATE_STATUS_FAIL
from rwa_filer.validate.returns import validate_return

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import OutputFloorSummary
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_filer.taxonomy.pack import TaxonomyPack

HEADER = ReturnHeader("5493001KJTIIGC8Y1R12", date(2027, 3, 31), FILING_MODULE)

#: The Basel 3.1 rules each operand of which reads an OF 08 RWEA figure.
OF08_RULES = frozenset({"boe_b0563", "boe_b0621", "boe_b0622", "boe_b0630", "boe_b0631"})


class _Run(NamedTuple):
    summary: OutputFloorSummary
    ledger: pl.DataFrame
    corep: COREPTemplateBundle


class _Verdicts(NamedTuple):
    str007: list[str]
    gateway_fail: frozenset[str]
    template_fail: frozenset[str]


@cache
def _run(portfolio: str, sa_t2_credit: float | None = None) -> _Run:
    """One registered Basel 3.1 portfolio through the engine and COREP, optionally
    with an Art. 62(c) SA T2 credit that makes its floor bind."""
    (run,) = [r for r in RUNS if r.framework == "BASEL_3_1" and r.portfolio == portfolio]
    config = run.build_config()
    if sa_t2_credit is not None:
        config = dataclasses.replace(
            config,
            output_floor=dataclasses.replace(config.output_floor, sa_t2_credit=sa_t2_credit),
        )
    result = PipelineOrchestrator().run_with_data(run.build_bundle(), config)
    assert result.output_floor_summary is not None, "the output floor did not run"
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework="BASEL_3_1",
        output_floor_summary=result.output_floor_summary,
    )
    return _Run(result.output_floor_summary, result.results.collect(), corep)


@cache
def _pack() -> TaxonomyPack:
    return resolve_release(FILING_MODULE, FILING_TAXONOMY).pack


def _verdicts(run: _Run) -> _Verdicts:
    """Structure findings and failing rules from both engines."""
    validation = validate_return(
        build_canonical_return(run.corep, HEADER, pack=_pack()).canonical, _pack()
    )
    assert validation.report is not None, "no rule book is packaged for PRA001"
    template = evaluate_all(run.corep, None, "BASEL_3_1")
    return _Verdicts(
        str007=sorted(f.subject for f in validation.structure if f.code == "STR007"),
        gateway_fail=frozenset(
            r.rule_id for r in validation.report.results if r.status == STATUS_FAIL
        ),
        template_fail=frozenset(
            o.rule_id for o in template.outcomes if o.status == TEMPLATE_STATUS_FAIL
        ),
    )


def _cell(frame: pl.DataFrame, row_ref: str, col_ref: str) -> float:
    (value,) = frame.filter(pl.col("row_ref") == row_ref)[col_ref].to_list()
    return float(value)


@pytest.fixture(scope="module")
def binding() -> _Run:
    run = _run("facility-share-binding")
    # Adequacy: on a non-binding floor the two carriers are equal and this
    # module proves nothing.
    assert run.summary.portfolio_floor_binding, "the floor does not bind"
    assert run.summary.shortfall > 400_000.0, "the shortfall is too small to see"
    return run


def test_irb_class_sheets_add_up_to_the_unfloored_modelled_rwea(binding: _Run) -> None:
    """Sum over the OF 08.01 class sheets of r0010 c0260 is U-TREA's modelled part
    (1,105,491.29), not the floored figure (1,559,200.00)."""
    # Act
    sheets = c08_class_sheets(binding.corep.c08_01)
    total = sum(_cell(sheet, "0010", "0260") for sheet in sheets.values())
    # Assert
    assert total == pytest.approx(binding.summary.u_trea)


def test_the_return_files_one_value_per_data_point_and_keeps_the_footing_rules(
    binding: _Run,
) -> None:
    # Act
    verdicts = _verdicts(binding)
    # Assert
    assert verdicts.str007 == []
    assert sorted(verdicts.gateway_fail & {"boe_b0621", "boe_b0751"}) == []
    assert sorted(verdicts.template_fail & {"boe_b0621", "boe_b0751", "boe_b0763"}) == []


def test_total_reported_rwa_does_not_move(binding: _Run) -> None:
    """The floor is still reported, once, where Annex II puts it: OF 02.00 r0010
    c0010 is U-TREA and c0030 the floor (0.60 x 2,740,000 - 800); the engine's
    ledger is untouched."""
    # Act
    c02 = binding.corep.c_02_00
    assert c02 is not None, "OF 02.00 was not generated"
    # Assert
    assert _cell(c02, "0010", "0010") == pytest.approx(1_245_491.2910688268)
    assert _cell(c02, "0010", "0030") == pytest.approx(1_643_200.0)
    assert float(binding.ledger["rwa_final"].sum()) == pytest.approx(1_699_200.0)


class _Forced(NamedTuple):
    portfolio: str
    sa_t2_credit: float
    rules: frozenset[str]


#: Registered books with the floor forced to bind (credits measured to bind).
FORCED = (
    pytest.param(
        _Forced("irb-shapes", 1_500_000.0, OF08_RULES | {"boe_b0751"}),
        id="irb-shapes",
    ),
    pytest.param(
        _Forced("rich", 6_000_000.0, OF08_RULES | {"boe_b0751"}),
        id="rich",
    ),
    pytest.param(
        _Forced("ccr", 400_000.0, frozenset({"boe_b0475", "boe_b0495"})),
        id="ccr",
    ),
)


@pytest.mark.parametrize("forced", FORCED)
def test_a_forced_binding_floor_leaves_no_add_on_in_any_template(forced: _Forced) -> None:
    # Arrange
    run = _run(forced.portfolio, forced.sa_t2_credit)
    assert run.summary.portfolio_floor_binding, "the floor does not bind: proves nothing"
    # Act
    verdicts = _verdicts(run)
    # Assert
    assert verdicts.str007 == []
    assert sorted(verdicts.gateway_fail & forced.rules) == []


@pytest.mark.parametrize("portfolio", ["irb-shapes", "rich"])
def test_a_forced_binding_floor_leaves_slotting_rwea_unfloored(portfolio: str) -> None:
    """OF 08.06 col 0080 ("See OF CR IRB 1 instructions for column 0260"): the two
    maturity Total rows of every SL-type sheet add up to the slotting legs' own
    RWEA."""
    # Arrange
    sa_t2 = {"irb-shapes": 1_500_000.0, "rich": 6_000_000.0}[portfolio]
    run = _run(portfolio, sa_t2)
    slotting = run.ledger.filter(pl.col("approach_applied") == "slotting")
    floored = float(slotting["rwa_final"].sum()) - float(slotting["rwa_pre_floor"].sum())
    assert floored > 0.0, "no add-on on the slotting legs: proves nothing"
    # Act
    reported = sum(
        float(sheet.filter(pl.col("row_ref").is_in(["0110", "0120"]))["0080"].fill_null(0.0).sum())
        for sheet in run.corep.c08_06.values()
    )
    # Assert
    assert reported == pytest.approx(float(slotting["rwa_pre_floor"].sum()))


def test_a_forced_binding_floor_leaves_counterparty_rwea_unfloored() -> None:
    """The add-on also lands on SA-CCR legs (floor-eligible in the engine). C 34.01
    col 0020 and OF 09.01 col 0090 (the all-countries total) report their own
    RWEA; OF 07.00 col 0220 joins them once c07.py takes ``own_rwea``."""
    # Arrange
    run = _run("ccr", 400_000.0)
    sa_ccr = run.ledger.filter(
        pl.col("exposure_reference").str.starts_with("ccr__") & (pl.col("risk_type") != "CCR_SFT")
    )
    floored = float(sa_ccr["rwa_final"].sum()) - float(sa_ccr["rwa_pre_floor"].sum())
    assert run.summary.portfolio_floor_binding, "the floor does not bind: proves nothing"
    assert floored > 0.0, "no add-on on the SA-CCR legs: proves nothing"
    assert run.corep.c34_01 is not None, "C 34.01 was not generated"
    assert run.corep.c09_01 is not None, "OF 09.01 was not generated"
    # Act
    c34_rwea = _cell(run.corep.c34_01, "0010", "0020")
    c09_rwea = _cell(run.corep.c09_01["TOTAL"], "0170", "0090")
    # Assert
    assert c34_rwea == pytest.approx(float(sa_ccr["rwa_pre_floor"].sum()))
    assert c09_rwea == pytest.approx(float(run.ledger["rwa_pre_floor"].sum()))
