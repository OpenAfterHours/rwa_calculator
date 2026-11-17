"""
CRR C 08.06 column 0070 is printed information, not a reported figure.

Pipeline position:
    c08_06 frames -> build_template_index (the CRR "C 08.06" binding)
        -> rwa_filer.validate (template-level engine)

Key responsibilities:
- Pin that the CRR ``C 08.06`` binding governs only the template's data-point
  columns. Column 0070 is Table 1 of Art. 153(5) printed onto the template
  ("This is a fixed column for information purposes. It shall not be altered.",
  Annex II p.115). It has no DPM data point, so no published rule reaches it.
- Pin the consequence for ``v09783_m``, the EBA summation
  ``{r0120} = {r0020} + {r0040} + {r0060} + {r0080} + {r0100}`` over every
  column. On 0070 its right-hand side is a sum of five fixed category weights
  (0.7 + 0.9 + 1.15 + 2.5 + 0 = 5.25), which no Total value can meet. Evaluating
  the rule there reported a break against a cell the EBA's own XBRL rule never
  sees.

The evidence that 0070 is not a data point is indirect, because the EBA DPM is
not held here. The EBA's generated sign rules on C 08.06 (``v10309_s`` /
``v10310_s``) list every column except 0070, while the same family elsewhere
covers percentage and parameter columns. No EBA rule in any release addresses
C 08.06 c0070.

References:
- Regulation (EU) 2021/451 Annex II, C 08.06 col 0070 (PDF p.115) and rows
  0010-0120 (p.116)
- CRR Art. 153(5) Table 1
- src/rwa_calc/reporting/filing/bindings.py — the binding under test
"""

from __future__ import annotations

from rwa_filer.rules.catalogue import RuleSet, load_rules
from rwa_filer.validate import STATUS_FAIL, STATUS_PASS, RuleOutcome, evaluate_index
from rwa_filer.validate.index import ABSENT_CELL

from ._builders import build_frame, build_index

_SHEET = "project_finance"

#: Table 1 of Art. 153(5), as the category rows of CRR C 08.06 print it.
_TABLE_1_WEIGHTS = {
    "0010": 0.5,
    "0020": 0.7,
    "0030": 0.7,
    "0040": 0.9,
    "0050": 1.15,
    "0060": 1.15,
    "0070": 2.5,
    "0080": 2.5,
    "0090": 0.0,
    "0100": 0.0,
}

#: The C 08.06 columns that ARE reported figures.
_DATA_POINT_COLUMNS = ("0010", "0020", "0030", "0040", "0050", "0060", "0080", "0090", "0100")


def _footing_sheet(*, total_long_rwea: float = 52_500_000.0) -> dict[str, dict[str, float | None]]:
    """A CRR project-finance sheet whose additive columns foot.

    One strong, >= 2.5-year leg of 75m at 70% (the ``rich`` portfolio's shape).
    Row 0120 is the sum of the >= 2.5-year category rows on every data-point
    column. Col 0070 carries the Table 1 weight on each category row and is
    blank on both Total rows.
    """
    empty = dict.fromkeys(_DATA_POINT_COLUMNS, 0.0)
    sheet = {row: {**empty, "0070": weight} for row, weight in _TABLE_1_WEIGHTS.items()}
    live = {
        **empty,
        "0010": 75_000_000.0,
        "0020": 75_000_000.0,
        "0040": 75_000_000.0,
        "0080": 52_500_000.0,
        "0090": 300_000.0,
    }
    sheet["0020"] = {**live, "0070": 0.7}
    sheet["0110"] = {**empty, "0070": None}
    sheet["0120"] = {**live, "0080": total_long_rwea, "0070": None}
    return sheet


def _evaluate_v09783_m(sheet: dict[str, dict[str, float | None]]) -> RuleOutcome:
    """Run the packaged ``v09783_m`` alone against one C 08.06 sheet."""
    packaged = load_rules("CRR")
    rule = next(r for r in packaged.rules if r.rule_id == "v09783_m")
    ruleset = RuleSet(
        framework=packaged.framework,
        publisher=packaged.publisher,
        source=packaged.source,
        rules=(rule,),
    )
    index = build_index(c08_06={_SHEET: build_frame(sheet)})
    (outcome,) = evaluate_index(index, ruleset).outcomes
    return outcome


def test_the_fixed_risk_weight_column_is_not_a_governed_c08_06_column() -> None:
    """The binding reads every data-point column and never column 0070."""
    # Arrange
    index = build_index(c08_06={_SHEET: build_frame(_footing_sheet())})

    # Act
    refs = index.column_refs("C 08.06", _SHEET)
    information_cell = index.cell("C 08.06", _SHEET, "0020", "0070")

    # Assert
    assert refs == _DATA_POINT_COLUMNS
    assert information_cell == ABSENT_CELL


def test_v09783_m_does_not_judge_the_fixed_risk_weight_column() -> None:
    """A sheet that foots on every data point passes ``v09783_m``.

    Before the binding was restricted, the rule failed at
    ``C 08.06[project_finance][c0070]`` with 0.0 against 5.25, the sum of the
    long-maturity Table 1 weights.
    """
    # Arrange
    sheet = _footing_sheet()

    # Act
    outcome = _evaluate_v09783_m(sheet)

    # Assert: evaluated (a live leg on several columns), and no break.
    assert outcome.status == STATUS_PASS, outcome.coordinates
    assert outcome.passed >= 1


def test_v09783_m_still_judges_the_data_point_columns() -> None:
    """The restriction narrows the rule; it does not switch it off.

    Control for the test above: a Total that does not foot on RWEA (col 0080)
    still breaks the rule, at that column.
    """
    # Arrange
    sheet = _footing_sheet(total_long_rwea=52_000_000.0)

    # Act
    outcome = _evaluate_v09783_m(sheet)

    # Assert
    assert outcome.status == STATUS_FAIL
    assert outcome.coordinates == ("C 08.06[project_finance][c0080]",)
