"""
C 07.00 / OF 07.00 row 0015 on the real pipeline: reported where Annex II names, blank elsewhere.

Pipeline position:
    RawDataBundle -> PipelineOrchestrator (SA or IRB config, both regimes)
        -> COREPGenerator -> C 07.00 / OF 07.00 sheets
        -> filing.build_canonical_return -> rwa_filer.boe (the Bank's gateway rules)
        -> filing.checks.evaluate_all (the template-level register engine)

What is asserted, and the text it is asserted from:

- PS1/26 Annex II, OF 07.00 row 0015 (ps1-26-annex-ii-reporting-instructions.pdf
  p.88): "Only exposures in exposure classes 'exposures associated with
  particularly high risk', 'subordinated debt, equity and other own funds
  instruments', and 'exposures in the form of units or shares in collective
  investment undertakings ('CIUs')' shall be reported in this row if they are
  in default."
- CRR COREP Annex II, C 07.00 row 0015 (crr-annex-ii-reporting-instructins.pdf
  p.91): "This row shall only be reported in exposure classes 'Items associated
  with a particular high risk' and 'Equity exposures'."

A defaulted corporate leg belongs to the "exposures in default" class (j), so
row 0015 must be blank on that sheet and on the Total; a defaulted high-risk leg
under Basel 3.1 keeps class (k), so it is reported there and summed into the
Total. Until O-05 the row keyed on the defaulted flag alone and lit on the
"in default" sheet and the Total in both regimes (``crr/rich`` and ``b31/rich``:
1,000,000 / 1,500,000), failing ``boe_b0431`` / ``boe_b1069`` at the gateway
and ``v4721_m`` in the register.

Two books:

1. ``rich`` (the registered golden portfolio, both regimes). Its one defaulted
   leg is a 1,000,000 corporate loan at 150%. The control is memorandum row 0320,
   which the row 0015 scope must not touch: on the default sheet under CRR, and
   under Basel 3.1 on the Total and the corporates sheet — the class before default
   (Annex II ¶54-55; table OF07.00.01.03 has no row 0320 on sheet 0011; O-15,
   ``corep/c07_sheet_scope.py``).
2. A three-loan book this file owns, SA config: a performing corporate
   (5,000,000), a defaulted corporate (1,000,000 at 150%) and a defaulted
   high-risk obligor (2,000,000 at 150%). No registered portfolio emits a
   high-risk sheet, so without this book the surviving leg — the one that tells
   a scoped row from a row blanked everywhere — would be asserted nowhere
   (LESSONS B5). Under CRR the high-risk class does not exist (Art. 128 was
   omitted from the onshored CRR; the classifier folds it to "other", then to
   default), so both defaulted legs land on the default sheet and row 0015 is
   blank everywhere.

References:
- CRR Art. 112(1)(j)/(k)/(p), Art. 127; PS1/26 Art. 112(2) Table A2
- COREP Annex II C 07.00 row 0015; PS1/26 Annex II OF 07.00 row 0015, ¶54-55
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.acceptance.reporting.test_reporting_golden import _b31_config, _crr_config
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.fixtures.reporting_portfolio import build_reporting_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    build_canonical_return,
)
from rwa_calc.reporting.filing.checks import evaluate_all
from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS
from rwa_filer.boe.engine import STATUS_PASS
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate.returns import validate_return

if TYPE_CHECKING:
    from collections.abc import Callable

    from rwa_calc.contracts.bundles import RawDataBundle
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_filer.boe.engine import RuleResult
    from rwa_filer.validate.checker import RuleOutcome

_DEFAULTED_ROW: str = "0015"
_TOTAL_ROW: str = "0010"
_MEMO_DEFAULTED_ROW: str = "0320"
_LABEL_COLS: frozenset[str] = frozenset({"row_ref", "row_name"})

# The z-codes the rows are asserted on (resolved through SHEET_INDEX_MAPS).
_Z_TOTAL: str = "0001"
_Z_DEFAULTED: str = "0011"
_Z_HIGH_RISK: str = "0012"
_Z_CORPORATE: str = "0008"

# Where ``rich``'s memorandum row 0320 is reported (see the module docstring).
_MEMO_Z_CODES: dict[str, tuple[str, ...]] = {
    "crr": (_Z_DEFAULTED,),
    "b31": (_Z_TOTAL, _Z_CORPORATE),
}

# ``rich``: its one defaulted leg (RP-LN-DEFAULT), a corporate loan at 150%.
_RICH_DEFAULTED_EAD: float = 1_000_000.0
_RICH_DEFAULTED_RWEA: float = 1_500_000.0

# The book this file owns.
_PERFORMING_EAD: float = 5_000_000.0
_DEFAULTED_CORPORATE_EAD: float = 1_000_000.0
_DEFAULTED_HIGH_RISK_EAD: float = 2_000_000.0
_DEFAULTED_RW: float = 1.50  # Art. 127 / Art. 128: both defaulted legs at 150%
_HIGH_RISK_REF: str = "O05-LN-HR-DEF"

#: A checksum-valid LEI, as the filing-mapping ratchet uses; the rules do not depend on it.
_ENTITY_IDENTIFIER: str = "5493001KJTIIGC8Y1R12"

#: The Bank's must-be-blank rules over row 0015 (OF 07.00.01.01 / .02), and the
#: upper bound ``r0015 <= r0010`` on the sheets that may carry it.
_GATEWAY_SCOPE_RULES: tuple[str, ...] = ("boe_b0431", "boe_b1069")
_GATEWAY_UPPER_BOUND_RULE: str = "boe_b0536"
#: OF 07.00 r0015 c0010 on z0012 = OF 09.01 r0110 c0020 — the high-risk tie.
_GATEWAY_HIGH_RISK_TIE_RULE: str = "boe_b0264"
#: The EBA must-be-blank rule over row 0015 (C 07.00.a).
_EBA_SCOPE_RULE: str = "v4721_m"

_FRAMEWORKS: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}


# ---------------------------------------------------------------------------
# 1. rich: the defaulted corporate leaves row 0015 blank on the default sheet
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", sorted(_FRAMEWORKS))
def test_rich_default_sheet_reports_its_leg_on_row_0010_and_not_on_row_0015(regime: str) -> None:
    # Arrange
    corep = _rich(regime)
    sheet = _sheet(corep, regime, _Z_DEFAULTED)

    # Assert - adequacy: the sheet holds the defaulted leg, so blank means scope
    assert _cell(sheet, _TOTAL_ROW, "0010") == pytest.approx(_RICH_DEFAULTED_EAD)
    assert _cell(sheet, _TOTAL_ROW, "0220") == pytest.approx(_RICH_DEFAULTED_RWEA)
    assert not _populated(sheet, _DEFAULTED_ROW), f"[{regime}] row 0015 on the default sheet"


@pytest.mark.parametrize("regime", sorted(_FRAMEWORKS))
def test_rich_memorandum_row_0320_is_untouched_by_the_row_0015_scope(regime: str) -> None:
    """The control: the defaulted leg's row 0320 is still reported where it belongs."""
    corep = _rich(regime)

    for z_code in _MEMO_Z_CODES[regime]:
        sheet = _sheet(corep, regime, z_code)
        assert _cell(sheet, _MEMO_DEFAULTED_ROW, "0200") == pytest.approx(_RICH_DEFAULTED_EAD), (
            z_code
        )


@pytest.mark.parametrize("regime", sorted(_FRAMEWORKS))
def test_rich_total_sheet_leaves_row_0015_blank(regime: str) -> None:
    sheet = _sheet(_rich(regime), regime, _Z_TOTAL)

    assert not _populated(sheet, _DEFAULTED_ROW), f"[{regime}] row 0015 on the Total"


@pytest.mark.parametrize("rule_id", _GATEWAY_SCOPE_RULES)
def test_rich_b31_return_passes_the_banks_row_0015_scope_rules(rule_id: str) -> None:
    result = _gateway(_rich("b31"))[rule_id]

    assert (result.status, result.unsatisfied) == (STATUS_PASS, 0), _describe(result)
    assert result.satisfied == 1


def test_rich_crr_register_rule_v4721_m_is_vacuous_not_failing() -> None:
    """A must-be-blank guard is VACUOUS while the row is blank; PASS is unreachable."""
    outcome = _register(_rich("crr"), "CRR")[_EBA_SCOPE_RULE]

    assert outcome.status == "VACUOUS", (outcome.status, outcome.reason, outcome.coordinates)


# ---------------------------------------------------------------------------
# 2. The book this file owns: a defaulted high-risk leg survives the scope
# ---------------------------------------------------------------------------


def test_own_book_b31_holds_a_defaulted_high_risk_leg_at_150_percent() -> None:
    """Adequacy (LESSONS C11): without this leg the survival tests prove nothing."""
    results, _corep = _own_book("b31")
    leg = results.filter(pl.col("exposure_reference") == _HIGH_RISK_REF)

    assert leg.height == 1
    assert leg["reporting_class_origin"][0] == "high_risk"
    assert leg["risk_weight"][0] == pytest.approx(_DEFAULTED_RW)


def test_own_book_b31_high_risk_sheet_reports_the_defaulted_leg_on_row_0015() -> None:
    _results, corep = _own_book("b31")
    sheet = _sheet(corep, "b31", _Z_HIGH_RISK)

    assert _cell(sheet, _DEFAULTED_ROW, "0010") == pytest.approx(_DEFAULTED_HIGH_RISK_EAD)
    assert _cell(sheet, _DEFAULTED_ROW, "0200") == pytest.approx(_DEFAULTED_HIGH_RISK_EAD)
    assert _cell(sheet, _DEFAULTED_ROW, "0220") == pytest.approx(
        _DEFAULTED_HIGH_RISK_EAD * _DEFAULTED_RW
    )


def test_own_book_b31_default_sheet_reports_row_0010_and_not_row_0015() -> None:
    _results, corep = _own_book("b31")
    sheet = _sheet(corep, "b31", _Z_DEFAULTED)

    assert _cell(sheet, _TOTAL_ROW, "0010") == pytest.approx(_DEFAULTED_CORPORATE_EAD)
    assert not _populated(sheet, _DEFAULTED_ROW)


def test_own_book_b31_total_row_0015_is_the_high_risk_leg_alone() -> None:
    _results, corep = _own_book("b31")
    sheet = _sheet(corep, "b31", _Z_TOTAL)

    assert _cell(sheet, _DEFAULTED_ROW, "0010") == pytest.approx(_DEFAULTED_HIGH_RISK_EAD)
    assert _cell(sheet, _DEFAULTED_ROW, "0200") == pytest.approx(_DEFAULTED_HIGH_RISK_EAD)
    assert _cell(sheet, _DEFAULTED_ROW, "0220") == pytest.approx(
        _DEFAULTED_HIGH_RISK_EAD * _DEFAULTED_RW
    )


@pytest.mark.parametrize("rule_id", (*_GATEWAY_SCOPE_RULES, _GATEWAY_UPPER_BOUND_RULE))
def test_own_book_b31_return_passes_the_banks_row_0015_rules(rule_id: str) -> None:
    _results, corep = _own_book("b31")
    result = _gateway(corep)[rule_id]

    assert (result.status, result.unsatisfied) == (STATUS_PASS, 0), _describe(result)


def test_own_book_b31_high_risk_row_0015_ties_to_of_09_01() -> None:
    """``boe_b0264`` evaluated, not vacuous: the reported leg meets OF 09.01 r0110."""
    _results, corep = _own_book("b31")
    result = _gateway(corep)[_GATEWAY_HIGH_RISK_TIE_RULE]

    assert (result.status, result.satisfied, result.unsatisfied) == (STATUS_PASS, 1, 0), _describe(
        result
    )


def test_own_book_crr_folds_the_high_risk_leg_onto_the_default_sheet() -> None:
    _results, corep = _own_book("crr")
    sheet = _sheet(corep, "crr", _Z_DEFAULTED)
    defaulted = _DEFAULTED_CORPORATE_EAD + _DEFAULTED_HIGH_RISK_EAD

    assert _sheet_key("crr", _Z_HIGH_RISK) not in corep.c07_00
    assert _cell(sheet, _TOTAL_ROW, "0010") == pytest.approx(defaulted)
    assert _cell(sheet, _TOTAL_ROW, "0220") == pytest.approx(defaulted * _DEFAULTED_RW)
    assert not _populated(sheet, _DEFAULTED_ROW)


def test_own_book_crr_total_leaves_row_0015_blank() -> None:
    _results, corep = _own_book("crr")

    assert not _populated(_sheet(corep, "crr", _Z_TOTAL), _DEFAULTED_ROW)


def test_own_book_crr_register_rule_v4721_m_is_vacuous_not_failing() -> None:
    _results, corep = _own_book("crr")
    outcome = _register(corep, "CRR")[_EBA_SCOPE_RULE]

    assert outcome.status == "VACUOUS", (outcome.status, outcome.reason, outcome.coordinates)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@lru_cache(maxsize=2)
def _rich(regime: str) -> COREPTemplateBundle:
    config_factory: Callable[[], CalculationConfig] = (
        _crr_config if regime == "crr" else _b31_config
    )
    result = PipelineOrchestrator().run_with_data(build_reporting_bundle(), config_factory())
    return COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=_FRAMEWORKS[regime],
        output_floor_summary=result.output_floor_summary,
    )


@lru_cache(maxsize=2)
def _own_book(regime: str) -> tuple[pl.DataFrame, COREPTemplateBundle]:
    if regime == "crr":
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    else:
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.STANDARDISED
        )
    result = PipelineOrchestrator().run_with_data(_own_bundle(), config)
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=_FRAMEWORKS[regime],
        output_floor_summary=result.output_floor_summary,
    )
    return result.results.collect(), corep


def _own_bundle() -> RawDataBundle:
    """Performing corporate + defaulted corporate + defaulted high-risk obligor."""
    counterparties = pl.DataFrame(
        [
            _counterparty("O05-CP-PERF", "corporate", defaulted=False),
            _counterparty("O05-CP-DEF", "corporate", defaulted=True),
            _counterparty("O05-CP-HR-DEF", "high_risk", defaulted=True),
        ]
    )
    loans = pl.DataFrame(
        [
            _loan("O05-LN-PERF", "O05-CP-PERF", _PERFORMING_EAD, defaulted=False),
            _loan("O05-LN-DEF", "O05-CP-DEF", _DEFAULTED_CORPORATE_EAD, defaulted=True),
            _loan(_HIGH_RISK_REF, "O05-CP-HR-DEF", _DEFAULTED_HIGH_RISK_EAD, defaulted=True),
        ]
    )
    return make_raw_bundle(loans=loans, counterparties=counterparties)


def _counterparty(reference: str, entity_type: str, *, defaulted: bool) -> dict[str, object]:
    row: dict[str, object] = {
        "counterparty_reference": reference,
        "entity_type": entity_type,
        "country_code": "GB",
        "default_status": defaulted,
    }
    if entity_type == "corporate":
        row["annual_revenue"] = 200_000_000.0  # a large corporate: no SME limb
    return row


def _loan(
    reference: str, counterparty: str, amount: float, *, defaulted: bool
) -> dict[str, object]:
    return {
        "loan_reference": reference,
        "counterparty_reference": counterparty,
        "drawn_amount": amount,
        "currency": "GBP",
        "maturity_date": date(2030, 12, 31),
        "seniority": "senior",
        "is_defaulted": defaulted,
    }


def _gateway(corep: COREPTemplateBundle) -> dict[str, RuleResult]:
    header = ReturnHeader(_ENTITY_IDENTIFIER, date(2027, 3, 31), FILING_MODULE)
    pack = resolve_release(FILING_MODULE, FILING_TAXONOMY).pack
    mapping = build_canonical_return(corep, header, pack=pack)
    report = validate_return(mapping.canonical, pack).report
    return {result.rule_id: result for result in report.results}


def _register(corep: COREPTemplateBundle, framework: str) -> dict[str, RuleOutcome]:
    """The template-level verdicts. No Pillar 3 bundle: the rules read C 07.00 only."""
    report = evaluate_all(corep, None, framework)
    return {outcome.rule_id: outcome for outcome in report.outcomes}


def _sheet_key(regime: str, z_code: str) -> str:
    """The bundle key a published z-code names (LESSONS B3: never spelled here)."""
    keys = SHEET_INDEX_MAPS["c07" if regime == "crr" else "of07"][z_code].bundle_keys
    assert len(keys) == 1, f"z{z_code} names {keys}"
    return keys[0]


def _sheet(corep: COREPTemplateBundle, regime: str, z_code: str) -> pl.DataFrame:
    key = _sheet_key(regime, z_code)
    assert key in corep.c07_00, f"[{regime}] sheet {key!r} not emitted: {sorted(corep.c07_00)}"
    return corep.c07_00[key]


def _cell(sheet: pl.DataFrame, row_ref: str, column: str) -> float | None:
    row = sheet.filter(pl.col("row_ref") == row_ref)
    assert row.height == 1, f"row {row_ref} appears {row.height} times"
    return row[column][0]


def _populated(sheet: pl.DataFrame, row_ref: str) -> dict[str, object]:
    row = sheet.filter(pl.col("row_ref") == row_ref)
    assert row.height == 1, f"row {row_ref} appears {row.height} times"
    return {
        column: value
        for column, value in row.row(0, named=True).items()
        if column not in _LABEL_COLS and value is not None
    }


def _describe(result: RuleResult) -> str:
    return f"{result.rule_id}: {result.status} {result.satisfied}/{result.unsatisfied}"
