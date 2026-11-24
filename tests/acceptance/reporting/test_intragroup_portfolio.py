"""
Acceptance: the Art. 113(6) intragroup 0% as a core-UK-group member reports it.

Pipeline position:
    RUNS ``intragroup`` entries (test_supervisory_validations.py) -> each entry's
        own builder and config -> PipelineOrchestrator -> COREPGenerator ->
        C 07.00 / OF 07.00 institutions and corporates sheets
        -> (Basel 3.1) filing.build_canonical_return -> rwa_filer.boe

Why it exists (P1.364, LESSONS B4 / B5). The intragroup 0% fires only on a
scoped individual-basis run, and until ``reporting_intragroup_portfolio`` was
registered no run of the supervisory matrix set a scope, so row 0140 (0%) of the
class sheets never carried an intragroup figure and its column 0210 ("of which:
arising from counterparty credit risk") never carried the derivative and SFT legs
P1.364 brought into the permission. The register sees those cells only through
the Bank's PI-05 rules, which it banks as WARNINGs; this module asserts the cells
themselves, by value, so a change that empties the row or moves a leg off it is
red here whatever the register says.

Hand calculation (reporting_intragroup_portfolio.py): row 0140 of the
institutions sheet holds the 1m senior loan to BANK_B, the SA-CCR netting set
NS_IG_BANK and the 10m cash-lent SFT; column 0210 is the last two. Row 0140 of
the corporates sheet holds the 1m senior loan to the parent GRP and the netting
set NS_IG_GRP; column 0210 is the netting set. RWEA on row 0140 is zero. The
subordinated intragroup loan is an own-funds item the permission excludes, so it
sits on its class row instead: CRR 100% (row 0230, Art. 121 Table 5) and Basel
3.1 150% (row 0240, PS1/26 Art. 133(5)). The netting sets' exposure value is read
from the ledger (SA-CCR alpha x (RC + PFE) is not the subject here) and asserted
non-zero first, so a vanished leg cannot pass as a zero.

Basel 3.1 also files the return: a CORRECT return of this book breaks the Bank's
PI-05 rules (``boe_b0440`` / ``boe_b0441`` close OF 07.00.01.01 row 0140 on the
institutions / corporates sheets, ``boe_b0440_1`` / ``boe_b0441_1`` close
OF 07.00.01.02 row 0140 column 0210). Annex II paras 66-68 put an intragroup
exposure in its counterparty's own class and Art. 113(6) gives it 0%, so the rule
is the publisher's issue, never a figure to move; the test pins that the breaks
are those four rules and that rwa-filer's publisher-issue register names PI-05
for each.

References:
- CRR Art. 113(6); PS1/26 Art. 113(6)-(7); PS1/26 Art. 133(5); CRR Art. 121
- CRR / PS1/26 Annex II paras 66-68 and 126; OF 07.00 row 0140, column 0210
- docs/rwa-filer/publisher-issues.md PI-05
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import RUNS, GateInput
from tests.fixtures.reporting_intragroup_portfolio import (
    LOAN_AMOUNT,
    REPORTING_ENTITY,
    SFT_CASH_LENT,
)

from rwa_calc.domain.enums import ReportingBasis
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_filer.boe.engine import STATUS_FAIL
from rwa_filer.boe.issues import issues_for

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle

_PORTFOLIO = "intragroup"
_ZERO_ROW = "0140"
_EXPOSURE_VALUE = "0200"
_OF_WHICH_CCR = "0210"
_RWEA = "0220"

#: The row the subordinated intragroup loan sits on, and its weight: CRR 100%
#: (Art. 121 Table 5, unrated institution, unrated sovereign); Basel 3.1 150%
#: (PS1/26 Art. 133(5)).
_SUBORDINATED_ROW = {"CRR": ("0230", 1.0), "BASEL_3_1": ("0240", 1.5)}

#: The PI-05 rules a correct Basel 3.1 return of this book breaks.
_PI05_RULES = ("boe_b0440", "boe_b0440_1", "boe_b0441", "boe_b0441_1")
_PI05 = "PI-05"
_ISSUE_RELEASE = "4.1.1"
_ISSUE_MODULE = "PRA001"


class _Run(NamedTuple):
    """One registered intragroup run: its entry, ledger and COREP bundle."""

    entry: GateInput
    ledger: pl.DataFrame
    corep: COREPTemplateBundle


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module", params=["crr", "b31"])
def run(request: pytest.FixtureRequest) -> _Run:
    """The registered run for one regime, from the RUNS entry's OWN builder and config."""
    entry = _registered(request.param)
    result = PipelineOrchestrator().run_with_data(entry.build_bundle(), entry.build_config())
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=entry.framework,
        output_floor_summary=result.output_floor_summary,
    )
    return _Run(entry, result.results.collect(), corep)


# =============================================================================
# The registration itself
# =============================================================================


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_registered_run_is_scoped_to_the_member_individual_basis(regime: str) -> None:
    """Adequacy: unscoped, every leg would take its full weight (LESSONS B5, third form)."""
    # Arrange
    entry = _registered(regime)

    # Act
    config = entry.build_config()

    # Assert
    assert config.reporting_entity == REPORTING_ENTITY
    assert config.reporting_basis is ReportingBasis.INDIVIDUAL


# =============================================================================
# Row 0140 (0%) and its column 0210 (of which: CCR)
# =============================================================================


class TestZeroPercentRow:
    """The intragroup legs land on row 0140 of their counterparty's class sheet."""

    def test_institutions_row_holds_the_loan_the_netting_set_and_the_sft(self, run: _Run) -> None:
        # Arrange
        netting_set = _ead(run.ledger, "ccr__NS_IG_BANK")
        sft = _ead(run.ledger, "ccr__SFT_NS_IG")

        # Act
        cells = _row(run.corep, "institution", _ZERO_ROW)

        # Assert
        assert sft == pytest.approx(SFT_CASH_LENT), "the SFT's E* is the cash lent"
        assert cells[_EXPOSURE_VALUE] == pytest.approx(LOAN_AMOUNT + netting_set + sft)
        assert cells[_OF_WHICH_CCR] == pytest.approx(netting_set + sft)
        assert cells[_RWEA] == pytest.approx(0.0)

    def test_corporates_row_holds_the_parent_loan_and_netting_set(self, run: _Run) -> None:
        """The parent is a financial institution in the corporate class (Annex II para 68)."""
        # Arrange
        netting_set = _ead(run.ledger, "ccr__NS_IG_GRP")

        # Act
        cells = _row(run.corep, "corporate", _ZERO_ROW)

        # Assert
        assert cells[_EXPOSURE_VALUE] == pytest.approx(LOAN_AMOUNT + netting_set)
        assert cells[_OF_WHICH_CCR] == pytest.approx(netting_set)
        assert cells[_RWEA] == pytest.approx(0.0)

    def test_subordinated_intragroup_loan_sits_on_its_class_row(self, run: _Run) -> None:
        """The own-funds carve-out: CRR 100% (row 0230), Basel 3.1 150% (row 0240)."""
        # Arrange
        row, weight = _SUBORDINATED_ROW[run.entry.framework]

        # Act
        cells = _row(run.corep, "institution", row)

        # Assert
        assert cells[_EXPOSURE_VALUE] == pytest.approx(LOAN_AMOUNT)
        assert cells[_OF_WHICH_CCR] == pytest.approx(0.0)
        assert cells[_RWEA] == pytest.approx(LOAN_AMOUNT * weight)

    def test_external_legs_stay_on_the_hundred_percent_row(self, run: _Run) -> None:
        """Control: the same products to an external corporate keep their 100% weight."""
        # Arrange
        external = _ead(run.ledger, "LN_EXT")
        netting_set = _ead(run.ledger, "ccr__NS_EXT")
        sft = _ead(run.ledger, "ccr__SFT_NS_EXT")

        # Act
        cells = _row(run.corep, "corporate", "0230")

        # Assert
        assert cells[_EXPOSURE_VALUE] == pytest.approx(external + netting_set + sft)
        assert cells[_OF_WHICH_CCR] == pytest.approx(netting_set + sft)
        assert cells[_RWEA] == pytest.approx(external + netting_set + sft)


# =============================================================================
# The filed Basel 3.1 return: PI-05
# =============================================================================


def test_correct_basel_3_1_return_breaks_exactly_the_pi05_rules_on_row_0140() -> None:
    """The four PI-05 rules break at the gateway, each named PI-05 in rwa-filer's register."""
    # Arrange — imported here as the register does: filing_mapping_report imports RUNS.
    from scripts.filing_mapping_report import file_on_gateway

    entry = _registered("b31")
    result = PipelineOrchestrator().run_with_data(entry.build_bundle(), entry.build_config())
    corep = COREPGenerator().generate_from_lazyframe(
        result.results, framework=entry.framework, output_floor_summary=result.output_floor_summary
    )

    # Act
    _mapping, validation = file_on_gateway(corep)
    assert validation.report is not None, "no PRA001 rule book packaged: nothing was checked"
    broken = {
        outcome.rule_id: outcome
        for outcome in validation.report.results
        if outcome.status == STATUS_FAIL and outcome.rule_id in _PI05_RULES
    }

    # Assert
    assert sorted(broken) == sorted(_PI05_RULES)
    assert {outcome.severity for outcome in broken.values()} == {"WARNING"}
    for rule_id in _PI05_RULES:
        named = [issue.id for issue in issues_for(_ISSUE_RELEASE, _ISSUE_MODULE, rule_id)]
        assert _PI05 in named, f"{rule_id} is not recorded under {_PI05}: {named}"


# =============================================================================
# Helpers
# =============================================================================


def _registered(regime: str) -> GateInput:
    (entry,) = [r for r in RUNS if r.portfolio == _PORTFOLIO and r.regime == regime]
    return entry


def _ead(ledger: pl.DataFrame, reference: str) -> float:
    rows = ledger.filter(pl.col("exposure_reference") == reference)
    assert rows.height == 1, f"{reference}: expected one ledger row, found {rows.height}"
    ead = float(rows["ead_final"][0])
    assert ead > 0.0, f"{reference} carries no exposure, so its cell would prove nothing"
    return ead


def _row(corep: COREPTemplateBundle, sheet: str, row_ref: str) -> dict[str, float]:
    frame = corep.c07_00[sheet]
    rows = frame.filter(pl.col("row_ref") == row_ref)
    assert rows.height == 1, f"{sheet} sheet: row {row_ref} not emitted"
    cells = rows.select(_EXPOSURE_VALUE, _OF_WHICH_CCR, _RWEA).row(0, named=True)
    missing = [column for column, value in cells.items() if value is None]
    assert not missing, f"{sheet} sheet row {row_ref}: no figure in column(s) {missing}"
    return cells
