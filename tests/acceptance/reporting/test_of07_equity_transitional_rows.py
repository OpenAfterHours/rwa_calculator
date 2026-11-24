"""
OF 07.00 for a standardised firm's equity under the PS1/26 transitional — the registered book.

Pipeline position:
    build_reporting_equity_transitional_bundle() -> PipelineOrchestrator (Basel 3.1,
        PermissionMode.STANDARDISED, 2027-06-01) -> COREPGenerator
        -> OF 07.00 sheet 0016 (class (p)) and the Total sheet
        -> filing.build_canonical_return -> rwa_filer.boe (the Bank's gateway rules)

What is asserted, and the text it is asserted from (PS1/26 Annex II,
ps1-26-annex-ii-reporting-instructions.pdf):

- ROW. p.95: equity "subject to the transitional provisions in Rules 4.1 to
  4.10 [...] shall be reported against the risk weights set out in Article 133
  [...] disregarding the transitional provisions. However, the RWEA shall still
  reflect the transitional provisions." p.96 names the rows: 0250 for an
  Article 133(1)-(2) equity exposure, 0261 for a higher risk equity exposure.
  So each 160% leg sits in row 0250 and each 220% leg in row 0261, and row 0280
  "Other risk weights" holds nothing.
- WHICH RUNG. Art. 133(4) and the Glossary: higher risk is "(1) not listed on a
  recognised exchange; and (2) [...] whose business has existed for a period of
  less than five years". A speculative flag that contradicts the row (a listed
  type, a ten-year business) leaves the leg in rows 0250 / 0372 (P1.207); an
  unlisted government-supported leg under five years is higher risk, rows
  0261 / 0371 (P1.393(c)); a higher-risk Art. 133(6)(c) significant investment
  is 250% in row 0250 and outside the memorandum rows (P1.393(b)).
- MEMORANDUM. p.97: "Institutions shall report all equity exposures to which the
  Standardised Transitional Approach for equities applies in these rows" — row
  0372 (rules 4.1 and 4.2, other equity) and row 0371 (rules 4.1 and 4.3, higher
  risk); ¶55A (p.79) confines rows 0371-0374 to class (p), which the Bank
  publishes on sheet 0016 alone.

The Bank's own placement rule is the cross-check: ``boe_b0458`` requires row
0280 (and every other off-ladder row) empty on sheet 0016, so the half-fixed
state — engine weights right, row read off the applied weight — fails it. The
template-level engine cannot evaluate that rule (unsupported grammar), so it is
read here from the gateway engine on the canonical return.

Not asserted here: ``boe_b1016`` / ``boe_b1031`` (ERROR) and ``boe_b0491`` /
``boe_b0506`` (WARNING) FAIL on this correct return because every transitional
weight is below its row's weight (publisher issue PI-01), and ``boe_b0710_2``
(ERROR) fails on rows 0371 / 0372 because an equity holding has no
off-balance-sheet conversion-factor breakdown. Those are register entries
(``validation_known_breaks.json`` and the filing-mapping baseline), not
properties of our figures.

References:
- PS1/26 Credit Risk: General Provisions (CRR) Part rules 4.1-4.3
- PS1/26 Art. 133(3)-(6); Annex II OF 07.00 rows 0240-0280, 0371-0374; ¶55A-55D
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.fixtures.reporting_equity_transitional_portfolio import (
    EQ_FLAGGED,
    EQ_FLAGGED_AGED,
    EQ_FLAGGED_LISTED,
    EQ_GOV_YOUNG,
    EQ_LISTED,
    EQ_SIG_YOUNG,
    EQ_SIGNIFICANT,
    EQ_SUB_DEBT,
    EQ_YOUNG,
    EQUITY_EXPOSURES,
    EXPOSURE_SUB_DEBT,
    RULE_4_2_REFERENCES,
    RULE_4_3_REFERENCES,
    build_reporting_equity_transitional_bundle,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    build_canonical_return,
)
from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS
from rwa_filer.boe.engine import STATUS_FAIL, STATUS_NOT_EVALUATED
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate.returns import validate_return

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle

#: The reporting date of the registered standardised runs (2027: rules 4.2(1) / 4.3(1)).
_REPORTING_DATE = date(2027, 6, 1)

#: The applied weights the registered book must hold (rules 4.2(1) / 4.3(1), 2027).
_RULE_4_2_2027: float = 1.60
_RULE_4_3_2027: float = 2.20

#: The applied weight of each equity leg in 2027 (see the portfolio's leg table).
_APPLIED: dict[str, float] = {
    **dict.fromkeys(RULE_4_2_REFERENCES, _RULE_4_2_2027),
    **dict.fromkeys(RULE_4_3_REFERENCES, _RULE_4_3_2027),
    EQ_SUB_DEBT: 1.50,  # Art. 133(5)
    EQ_SIGNIFICANT: 2.50,  # Art. 133(6)(c)
    EQ_SIG_YOUNG: 2.50,  # Art. 133(6)(c), although higher risk
}
_RWEA: dict[str, float] = {ref: EQUITY_EXPOSURES[ref] * _APPLIED[ref] for ref in _APPLIED}

#: The legs each Article 133 row holds (Annex II p.96).
_ROW_0250: tuple[str, ...] = (*RULE_4_2_REFERENCES, EQ_SIGNIFICANT, EQ_SIG_YOUNG)
_ROW_0261: tuple[str, ...] = RULE_4_3_REFERENCES


def _exposure(references: tuple[str, ...]) -> float:
    return sum(EQUITY_EXPOSURES[ref] for ref in references)


def _rwea(references: tuple[str, ...]) -> float:
    return sum(_RWEA[ref] for ref in references)


_BAND_ROWS: tuple[str, ...] = ("0240", "0250", "0261", "0280")
_MEMO_ROWS: tuple[str, ...] = ("0371", "0372", "0373", "0374")

#: A checksum-valid LEI, as the filing-mapping ratchet uses; the rules do not depend on it.
_ENTITY_IDENTIFIER = "5493001KJTIIGC8Y1R12"


@lru_cache(maxsize=2)
def _run(framework: str) -> tuple[pl.DataFrame, COREPTemplateBundle, object]:
    """The registered book through the pipeline, OF 07.00, and (Basel 3.1) the gateway rules."""
    if framework == "CRR":
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    else:
        config = CalculationConfig.basel_3_1(
            reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
        )
    result = PipelineOrchestrator().run_with_data(
        build_reporting_equity_transitional_bundle(), config
    )
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=framework,
        output_floor_summary=result.output_floor_summary,
    )
    report = None
    if framework == "BASEL_3_1":
        header = ReturnHeader(_ENTITY_IDENTIFIER, date(2027, 3, 31), FILING_MODULE)
        pack = resolve_release(FILING_MODULE, FILING_TAXONOMY).pack
        mapping = build_canonical_return(corep, header, pack=pack)
        report = validate_return(mapping.canonical, pack).report
    return result.results.collect(), corep, report


def _sheet_key(sheet_map: str, z_code: str) -> str:
    """The bundle key a published z-code names (LESSONS B3: not spelled here)."""
    keys = SHEET_INDEX_MAPS[sheet_map][z_code].bundle_keys
    assert len(keys) == 1, f"{sheet_map} z:{z_code} names {keys}"
    return keys[0]


def _cell(corep: COREPTemplateBundle, sheet: str, row_ref: str, column: str) -> float | None:
    assert sheet in corep.c07_00, f"sheet {sheet!r} not emitted; got {sorted(corep.c07_00)}"
    matched = corep.c07_00[sheet].filter(pl.col("row_ref") == row_ref)
    assert matched.height == 1, f"{sheet}: expected one row {row_ref}, got {matched.height}"
    return matched[column][0]


@pytest.fixture(scope="module")
def b31() -> tuple[pl.DataFrame, COREPTemplateBundle, object]:
    return _run("BASEL_3_1")


@pytest.fixture(scope="module")
def equity_sheet() -> str:
    return _sheet_key("of07", "0016")


@pytest.fixture(scope="module")
def total_sheet() -> str:
    return _sheet_key("of07", "0001")


# ---------------------------------------------------------------------------
# Adequacy (LESSONS C11): two legs the transitional moves, two it must not
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reference", "applied", "article_133"),
    [
        (EQ_LISTED, _RULE_4_2_2027, 2.50),
        (EQ_YOUNG, _RULE_4_3_2027, 4.00),
        (EQ_SUB_DEBT, 1.50, None),
        (EQ_SIGNIFICANT, 2.50, None),
        (EQ_FLAGGED, _RULE_4_3_2027, 4.00),
        (EQ_FLAGGED_LISTED, _RULE_4_2_2027, 2.50),
        (EQ_FLAGGED_AGED, _RULE_4_2_2027, 2.50),
        (EQ_GOV_YOUNG, _RULE_4_3_2027, 4.00),
        (EQ_SIG_YOUNG, 2.50, None),
    ],
)
def test_the_book_holds_legs_off_the_ladder_beside_legs_on_it(
    b31: tuple, reference: str, applied: float, article_133: float | None
) -> None:
    """Without an applied weight that is no row of the template, the row tests prove nothing."""
    results = b31[0]
    leg = results.filter(pl.col("exposure_reference") == reference)

    assert leg.height == 1, reference
    assert leg["risk_weight"][0] == pytest.approx(applied)
    assert leg["risk_weight_pre_equity_transitional"][0] == (
        None if article_133 is None else pytest.approx(article_133)
    )


# ---------------------------------------------------------------------------
# Sheet 0016: the Article 133 row, the transitional RWEA
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("row_ref", "exposure", "rwea"),
    [
        ("0240", EXPOSURE_SUB_DEBT, _RWEA[EQ_SUB_DEBT]),
        ("0250", _exposure(_ROW_0250), _rwea(_ROW_0250)),
        ("0261", _exposure(_ROW_0261), _rwea(_ROW_0261)),
    ],
)
def test_each_leg_is_reported_on_the_row_of_its_article_133_weight(
    b31: tuple, equity_sheet: str, row_ref: str, exposure: float, rwea: float
) -> None:
    corep = b31[1]

    assert _cell(corep, equity_sheet, row_ref, "0200") == pytest.approx(exposure)
    assert _cell(corep, equity_sheet, row_ref, "0220") == pytest.approx(rwea)


@pytest.mark.parametrize("column", ["0010", "0200", "0220"])
def test_nothing_is_reported_against_other_risk_weights(
    b31: tuple, equity_sheet: str, total_sheet: str, column: str
) -> None:
    corep = b31[1]

    assert _cell(corep, equity_sheet, "0280", column) is None
    assert _cell(corep, total_sheet, "0280", column) is None


@pytest.mark.parametrize("column", ["0200", "0220"])
def test_the_band_rows_foot_to_row_0010(b31: tuple, equity_sheet: str, column: str) -> None:
    corep = b31[1]
    banded = sum(float(_cell(corep, equity_sheet, ref, column) or 0.0) for ref in _BAND_ROWS)

    assert banded == pytest.approx(_cell(corep, equity_sheet, "0010", column))
    assert _cell(corep, equity_sheet, "0010", "0220") == pytest.approx(sum(_RWEA.values()))


@pytest.mark.parametrize("row_ref", ["0250", "0261"])
@pytest.mark.parametrize("column", ["0200", "0220"])
def test_the_total_sheet_carries_the_same_equity_rows(
    b31: tuple, equity_sheet: str, total_sheet: str, row_ref: str, column: str
) -> None:
    """Annex II ¶47: the Total sheet is the total across classes.

    Only class (p) is in these rows.
    """
    corep = b31[1]

    assert _cell(corep, total_sheet, row_ref, column) == pytest.approx(
        _cell(corep, equity_sheet, row_ref, column)
    )


# ---------------------------------------------------------------------------
# Sheet 0016: memorandum rows 0371-0374
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("row_ref", "exposure", "rwea"),
    [
        ("0371", _exposure(RULE_4_3_REFERENCES), _rwea(RULE_4_3_REFERENCES)),
        ("0372", _exposure(RULE_4_2_REFERENCES), _rwea(RULE_4_2_REFERENCES)),
    ],
)
def test_the_standardised_transitional_memorandum_rows_carry_the_moved_legs(
    b31: tuple, equity_sheet: str, row_ref: str, exposure: float, rwea: float
) -> None:
    """Only the moved legs: the Art. 133(6)(c) legs share row 0250 and are not in row 0372."""
    corep = b31[1]

    for column in ("0010", "0040", "0150", "0200"):
        assert _cell(corep, equity_sheet, row_ref, column) == pytest.approx(exposure), column
    assert _cell(corep, equity_sheet, row_ref, "0220") == pytest.approx(rwea)


@pytest.mark.parametrize("row_ref", ["0373", "0374"])
@pytest.mark.parametrize("column", ["0010", "0200", "0220"])
def test_the_irb_transitional_memorandum_rows_stay_empty(
    b31: tuple, equity_sheet: str, row_ref: str, column: str
) -> None:
    """¶55C: rows 0373 / 0374 are rules 4.4-4.8, for a firm WITH IRB permission.

    This firm has none.
    """
    assert _cell(b31[1], equity_sheet, row_ref, column) is None


@pytest.mark.parametrize("column", ["0010", "0200", "0220"])
def test_the_memorandum_rows_are_on_sheet_0016_alone(
    b31: tuple, equity_sheet: str, column: str
) -> None:
    corep = b31[1]
    for sheet, frame in corep.c07_00.items():
        if sheet == equity_sheet:
            continue
        memo = frame.filter(pl.col("row_ref").is_in(_MEMO_ROWS))
        populated = memo.select(pl.col(column).is_not_null().sum()).item()
        assert populated == 0, f"sheet {sheet!r} carries an equity memorandum figure in {column}"


# ---------------------------------------------------------------------------
# The Bank's placement rule, on the gateway engine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rule_id", ["boe_b0458", "boe_b0458_1"])
def test_the_banks_placement_rule_reaches_a_verdict_and_holds(b31: tuple, rule_id: str) -> None:
    """``boe_b0458``: rows 0140-0234 and 0280 empty on sheet 0016. Mis-rowed equity fails it."""
    report = b31[2]
    matched = [outcome for outcome in report.results if outcome.rule_id == rule_id]

    assert len(matched) == 1, f"expected one {rule_id} result, got {len(matched)}"
    assert matched[0].status not in (STATUS_FAIL, STATUS_NOT_EVALUATED), (
        f"{rule_id}: {matched[0].status} {matched[0].reason} {matched[0].detail}"
    )


# ---------------------------------------------------------------------------
# CRR arm: no transitional exists, the template is untouched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("column", ["0200", "0220"])
def test_under_crr_the_equity_sheet_foots_with_no_transitional_carrier(column: str) -> None:
    results, corep, _report = _run("CRR")
    sheet = _sheet_key("c07", "0016")
    band_rows = [ref for ref in corep.c07_00[sheet]["row_ref"].to_list() if "0140" <= ref <= "0280"]

    assert "risk_weight_pre_equity_transitional" not in results.columns
    banded = sum(float(_cell(corep, sheet, ref, column) or 0.0) for ref in band_rows)
    assert banded == pytest.approx(_cell(corep, sheet, "0010", column))
