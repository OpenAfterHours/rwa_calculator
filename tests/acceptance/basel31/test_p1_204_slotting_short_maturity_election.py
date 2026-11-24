"""
P1.204: a short-dated slotting leg end to end, with and without the PS1/26
Art. 153(5)(d) election — risk weight, EL, the output floor and the C 08.06 /
CR10 rows it lands in.

Pipeline position:
    RawDataBundle -> PipelineOrchestrator (classifier routes the leg to slotting)
        -> SlottingCalculator -> OutputAggregator (output floor) -> COREP / Pillar 3

One project-finance exposure, EAD GBP 10,000,000, 2.0 years to maturity at the
2027-06-30 reporting date, no provisions, slotting permitted by model. 'Strong'
unless a case names another grade.

Rule text (ps126app1.pdf pp.102-103, 107-108):
- Art. 153(5)(c): an institution "shall" assign column B to 'Strong' (70%).
- Art. 153(5)(d): it "may", if less than 2.5 years remain, assign column A (50%).
- Art. 158(6): EL uses the Table B cell in the "corresponding row and column to
  the risk weight value in Table A that the institution has assigned" — column B
  0.4%, column A 0%.
- UK CRR Art. 153(5) Table 1: "less than 2,5 years" row, Category 1 = 50%, a
  "shall"; Art. 158(6) Table B the same row, 0%.
- Table A gives 'Satisfactory' (115%), 'Weak' (250%) and 'Default' (0%) ONE
  column each — (d) offers a choice for 'Strong' and 'Good' only — so a
  short-dated leg of those grades has no column to elect, and its C 08.06 / CR10
  row is the one its remaining maturity names, election or not.

Output floor hand calculation (PS1/26 Art. 92 para 2A / para 5): 2027 floor
x = 60%. TREA = max(U-TREA, x * S-TREA + OF-ADJ), OF-ADJ = 12.5 * (IRB_T2 -
IRB_CET1 - GCRA + SA_T2). With no provisions the whole EL is a shortfall, so
IRB_CET1 = EL and IRB_T2 = 0; GCRA = SA_T2 = 0.

pre-operational PF (SA-equivalent 130%, S-TREA 13,000,000, x * S-TREA 7,800,000):
    column B (default): U-TREA 7,000,000; EL 40,000; OF-ADJ = 12.5 * -40,000
        = -500,000; threshold 7,300,000 > U-TREA -> binds; TREA 7,300,000.
    column A (elected): U-TREA 5,000,000; EL 0; OF-ADJ 0; threshold 7,800,000
        -> binds; TREA 7,800,000.
    The default RAISES U-TREA by 2,000,000 and LOWERS the floored TREA by
    500,000: where the floor binds, the EL limb of Art. 158(6) moves TREA the
    other way through OF-ADJ (the capital effect is the 40,000 CET1 deduction).
operational PF (SA-equivalent 100%, S-TREA 10,000,000, x * S-TREA 6,000,000):
    column B (default): threshold 6,000,000 - 500,000 = 5,500,000 < 7,000,000
        -> does not bind; TREA 7,000,000.
    column A (elected): threshold 6,000,000 > 5,000,000 -> binds; TREA 6,000,000.

References:
- PRA PS1/26 Art. 153(5)(c)-(d) Table A; Art. 158(6) Table B; Art. 92 para 2A, 5
- UK CRR Art. 153(5) Table 1; Art. 158(6) Table B
- PRA PS1/26 Annex II OF 08.06 rows ("in accordance with Article 153(5)");
  Annex XXIV UKB CR10 column c ("fixed column ... in accordance with Table A")
"""

from __future__ import annotations

from datetime import date
from functools import cache
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator
from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle

_REPORTING_DATE = date(2027, 6, 30)
_MATURITY = date(2029, 6, 30)  # 2.0 years remain
_EAD = 10_000_000.0
_MODEL_ID = "P1204_SLOTTING_MODEL"
_CP = "CP-P1204-PF"
_LOAN = "LOAN-P1204-PF-STRONG-SHORT"
_CARRIER = "slotting_short_maturity_rw_applied"


def _bundle(project_phase: str, category: str) -> RawDataBundle:
    """One short-dated project-finance loan of ``category`` with slotting permission."""
    counterparties = pl.LazyFrame(
        {
            "counterparty_reference": [_CP],
            "counterparty_name": ["Project SPV Ltd"],
            "entity_type": ["specialised_lending"],
            "country_code": ["GB"],
            "annual_revenue": [None],
            "total_assets": [500_000_000.0],
            "default_status": [False],
            "sector_code": ["42.11"],
            "apply_fi_scalar": [False],
            "is_managed_as_retail": [False],
        }
    )
    loans = pl.LazyFrame(
        {
            "loan_reference": [_LOAN],
            "product_type": ["PROJECT_FINANCE"],
            "book_code": ["SPECIALISED_LENDING"],
            "counterparty_reference": [_CP],
            "value_date": [date(2027, 1, 1)],
            "maturity_date": [_MATURITY],
            "currency": ["GBP"],
            "drawn_amount": [_EAD],
            "interest": [0.0],
            "lgd": [0.45],
            "beel": [0.0],
            "seniority": ["senior"],
        }
    )
    ratings = pl.LazyFrame(
        {
            "rating_reference": ["RTG-P1204"],
            "counterparty_reference": [_CP],
            "rating_type": ["internal"],
            "rating_agency": [None],
            "rating_value": [None],
            "cqs": pl.Series([None], dtype=pl.Int8),
            "pd": [0.005],  # slotting ignores PD
            "rating_date": [date(2027, 1, 1)],
            "is_solicited": [False],
            "model_id": [_MODEL_ID],
        }
    )
    specialised_lending = pl.LazyFrame(
        {
            "counterparty_reference": [_CP],
            "sl_type": ["project_finance"],
            "project_phase": [project_phase],
            "slotting_category": [category],
            "is_hvcre": [False],
        }
    )
    model_permissions = pl.LazyFrame(
        {
            "model_id": [_MODEL_ID],
            "exposure_class": [ExposureClass.SPECIALISED_LENDING.value],
            "approach": [ApproachType.SLOTTING.value],
        }
    )
    return make_raw_bundle(
        loans=loans,
        counterparties=counterparties,
        ratings=ratings,
        specialised_lending=specialised_lending,
        model_permissions=model_permissions,
    )


def _config(framework: str, elected: bool) -> CalculationConfig:
    if framework == "CRR":
        # The election is a Basel 3.1 keyword; CRR has no column choice to make.
        return CalculationConfig.crr(
            reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
        slotting_short_maturity_election=elected,
    )


@cache
def _result(
    framework: str, elected: bool, project_phase: str, category: str = "strong"
) -> AggregatedResultBundle:
    return PipelineOrchestrator().run_with_data(
        _bundle(project_phase, category), _config(framework, elected)
    )


def _leg(
    framework: str, elected: bool, project_phase: str = "operational", category: str = "strong"
) -> dict[str, object]:
    ledger = _result(framework, elected, project_phase, category).results.collect()
    legs = ledger.filter(pl.col("source_exposure_reference") == _LOAN)
    assert legs.height == 1, f"expected one leg for {_LOAN}, got {legs.height}"
    leg = legs.row(0, named=True)
    # Adequacy: the leg really is a short-dated slotting leg, or nothing below tests (d).
    assert leg["approach_applied"] == "slotting", "the leg did not reach the slotting branch"
    assert leg["is_short_maturity"] is True, "the leg is not short-dated"
    assert leg["slotting_category"] == category, "the leg is not the grade under test"
    return leg


ENGINE_CASES = [
    pytest.param("BASEL_3_1", False, 0.70, 40_000.0, False, id="b31-default-col-B"),
    pytest.param("BASEL_3_1", True, 0.50, 0.0, True, id="b31-elected-col-A"),
    pytest.param("CRR", False, 0.50, 0.0, True, id="crr-table-1-short-row"),
]


@pytest.mark.parametrize(
    ("framework", "elected", "expected_rw", "expected_el", "expected_applied"), ENGINE_CASES
)
def test_short_dated_strong_leg_weight_el_and_applied_column(
    framework: str,
    elected: bool,
    expected_rw: float,
    expected_el: float,
    expected_applied: bool,
) -> None:
    # Arrange / Act
    leg = _leg(framework, elected)

    # Assert
    assert leg["risk_weight"] == pytest.approx(expected_rw)
    assert leg["expected_loss"] == pytest.approx(expected_el, abs=0.01)
    assert leg[_CARRIER] is expected_applied


FLOOR_CASES = [
    # project_phase, elected, u_trea, s_trea, irb_cet1, of_adj, threshold, binding, trea
    pytest.param(
        "pre_operational",
        False,
        7_000_000.0,
        13_000_000.0,
        40_000.0,
        -500_000.0,
        7_300_000.0,
        True,
        7_300_000.0,
        id="binds-default-col-B",
    ),
    pytest.param(
        "pre_operational",
        True,
        5_000_000.0,
        13_000_000.0,
        0.0,
        0.0,
        7_800_000.0,
        True,
        7_800_000.0,
        id="binds-elected-col-A",
    ),
    pytest.param(
        "operational",
        False,
        7_000_000.0,
        10_000_000.0,
        40_000.0,
        -500_000.0,
        5_500_000.0,
        False,
        7_000_000.0,
        id="stops-binding-default-col-B",
    ),
    pytest.param(
        "operational",
        True,
        5_000_000.0,
        10_000_000.0,
        0.0,
        0.0,
        6_000_000.0,
        True,
        6_000_000.0,
        id="binds-elected-col-A-operational",
    ),
]


@pytest.mark.parametrize(
    (
        "project_phase",
        "elected",
        "u_trea",
        "s_trea",
        "irb_cet1",
        "of_adj",
        "threshold",
        "binding",
        "trea",
    ),
    FLOOR_CASES,
)
def test_basel_3_1_output_floor_follows_the_assigned_column(
    project_phase: str,
    elected: bool,
    u_trea: float,
    s_trea: float,
    irb_cet1: float,
    of_adj: float,
    threshold: float,
    binding: bool,
    trea: float,
) -> None:
    # Arrange
    result = _result("BASEL_3_1", elected, project_phase)
    summary = result.output_floor_summary
    assert summary is not None, "Basel 3.1 run produced no output floor summary"
    assert summary.floor_pct == pytest.approx(0.60), "2027 transitional floor is not 60%"

    # Act / Assert
    assert summary.u_trea == pytest.approx(u_trea)
    assert summary.s_trea == pytest.approx(s_trea)
    assert summary.irb_cet1_deduction == pytest.approx(irb_cet1)
    assert summary.irb_t2_credit == pytest.approx(0.0)
    assert summary.of_adj == pytest.approx(of_adj)
    assert summary.floor_threshold == pytest.approx(threshold)
    assert summary.portfolio_floor_binding is binding
    assert summary.total_rwa_post_floor == pytest.approx(trea)


ROW_CASES = [
    # framework, elected, grade, then for C 08.06 and for CR10: the category row
    # that holds the leg, the category row that must be empty, the Total row that
    # holds it and the Total row that must be empty; finally the leg's RWEA.
    pytest.param(
        "BASEL_3_1",
        False,
        "strong",
        ("0020", "0010", "0120", "0110"),
        ("2", "1", "12", "11"),
        7_000_000.0,
        id="b31-default-strong",
    ),
    pytest.param(
        "BASEL_3_1",
        True,
        "strong",
        ("0010", "0020", "0110", "0120"),
        ("1", "2", "11", "12"),
        5_000_000.0,
        id="b31-elected-strong",
    ),
    pytest.param(
        "CRR",
        False,
        "strong",
        ("0010", "0020", "0110", "0120"),
        ("1", "2", "11", "12"),
        5_000_000.0,
        id="crr-strong",
    ),
    # No column choice for these grades: the remaining maturity names the row,
    # with or without the (d) election.
    pytest.param(
        "BASEL_3_1",
        False,
        "satisfactory",
        ("0050", "0060", "0110", "0120"),
        ("5", "6", "11", "12"),
        11_500_000.0,
        id="b31-default-satisfactory",
    ),
    pytest.param(
        "BASEL_3_1",
        True,
        "satisfactory",
        ("0050", "0060", "0110", "0120"),
        ("5", "6", "11", "12"),
        11_500_000.0,
        id="b31-elected-satisfactory",
    ),
    pytest.param(
        "BASEL_3_1",
        False,
        "weak",
        ("0070", "0080", "0110", "0120"),
        ("7", "8", "11", "12"),
        25_000_000.0,
        id="b31-default-weak",
    ),
    pytest.param(
        "BASEL_3_1",
        False,
        "default",
        ("0090", "0100", "0110", "0120"),
        ("9", "10", "11", "12"),
        0.0,
        id="b31-default-default",
    ),
]


def _cell(frame: pl.DataFrame, row_ref: str, column: str) -> float | None:
    values = frame.filter(pl.col("row_ref") == row_ref)[column].to_list()
    assert len(values) == 1, f"row {row_ref} missing from the sheet"
    return values[0]


@pytest.mark.parametrize(
    ("framework", "elected", "category", "c0806_rows", "cr10_rows", "rwea"), ROW_CASES
)
def test_reported_rows_follow_the_applied_column(
    framework: str,
    elected: bool,
    category: str,
    c0806_rows: tuple[str, str, str, str],
    cr10_rows: tuple[str, str, str, str],
    rwea: float,
) -> None:
    """C 08.06 / OF 08.06 and CR10 cut a slotting grade by the Table A / Table 1
    column the leg was weighted on: a fixed display weight of 50% on the short
    Strong row must not hold a leg weighted at column B's 70%. Where Table A has
    one column for the grade (Satisfactory, Weak, Default) both rows carry the
    same fixed weight, so the remaining maturity the row labels state is the only
    key — and the Total split follows the category rows."""
    # Arrange
    result = _result(framework, elected, "operational", category)
    leg = _leg(framework, elected, category=category)
    c0806_row, c0806_empty, c0806_total, c0806_total_empty = c0806_rows
    cr10_row, cr10_empty, cr10_total, cr10_total_empty = cr10_rows

    # Act
    corep = COREPGenerator().generate_from_lazyframe(
        result.results, framework=framework, output_floor_summary=result.output_floor_summary
    )
    pillar3 = Pillar3Generator().generate_from_lazyframe(
        result.results, framework=framework, output_floor_summary=result.output_floor_summary
    )
    c0806 = corep.c08_06["project_finance"]
    cr10 = pillar3.cr10["project_finance"]

    # Assert
    assert _cell(c0806, c0806_row, "0040") == pytest.approx(_EAD)
    assert _cell(c0806, c0806_row, "0080") == pytest.approx(rwea)
    assert (_cell(c0806, c0806_empty, "0040") or 0.0) == pytest.approx(0.0)
    assert _cell(c0806, c0806_total, "0040") == pytest.approx(_EAD)
    assert (_cell(c0806, c0806_total_empty, "0040") or 0.0) == pytest.approx(0.0)
    assert _cell(cr10, cr10_row, "d") == pytest.approx(_EAD)
    assert _cell(cr10, cr10_row, "c") == pytest.approx(leg["risk_weight"] * 100.0)
    assert (_cell(cr10, cr10_empty, "d") or 0.0) == pytest.approx(0.0)
    assert _cell(cr10, cr10_total, "d") == pytest.approx(_EAD)
    assert (_cell(cr10, cr10_total_empty, "d") or 0.0) == pytest.approx(0.0)
