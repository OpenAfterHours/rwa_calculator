"""
OF 09.02: row 0150 is the sum of rows 0020, 0030 and 0060 on every Basel 3.1 run.

Pipeline position:
    RUNS (Basel 3.1, IRB permission) -> PipelineOrchestrator -> sealed ledger
        -> COREPGenerator -> COREPTemplateBundle.c09_02 ("TOTAL" + one per country)

Why this file exists (plan P5.60): the OF 09.02 layout used to carry the CRR row
0010 "Central banks and central governments", which the PRA's template does not
have — PS1/26 Annex II §3.4.2 starts at row 0020, and Art. 147A(1)(a) makes every
Art. 147(2)(a) exposure Standardised. Deleting the row removes one of the two
things that would have noticed a stray leg there: an unreported figure on a row
the taxonomy lacks, which the filing-mapping ratchet counts as unplaced. What is
left is row 0150, which counts EVERY leg of the IRB book — deliberately, so the
Bank's ``boe_b0786`` (ERROR) still breaks on a leg that no published row claims.
Restricting row 0150 to its three parts as well would let such a leg vanish from
the return with nothing raised (`.claude/LESSONS.md` B6). This file is the third
detector, and the exact one: on every registered Basel 3.1 run that has an IRB
book, the residual "row 0150 minus rows 0020 + 0030 + 0060" is 0.00 in every
column the rule covers, on every country sheet.

The identity is read from the Bank's rule book (LESSONS B3), never from the
layout or the generator: the total row, its parts and the columns are those of
``boe_b0786``'s expression and scope. The runs are read from the supervisory
gate's ``RUNS``, so a newly registered Basel 3.1 IRB portfolio joins this check
with no edit here. And the residual is computed, not inferred from the row list —
a leg of no published class is by definition in no row (B6).

Nothing here is a rounding question: the residual is taken on our unrounded
cells, where the gateway compares filed figures with a rounding allowance.

References:
- PRA PS1/26 Annex II §3.4.2, OF 09.02 row 0150 "the sum of rows 0020, 0030 and
  0060" (p.145 of ``ps1-26-annex-ii-reporting-instructions.pdf``)
- PRA PS1/26 Art. 147A(1)(a)
- Bank of England validation rule ``boe_b0786`` (v4.1.1, OF09.02.01.01, ERROR)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import RUNS, GateInput
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator

from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_filer.boe.catalogue import load_rulebook

if TYPE_CHECKING:
    from rwa_filer.boe.catalogue import Rule

FRAMEWORK = "BASEL_3_1"
MODULE = "PRA001"
RULE_BOOK = "banking_reporting-4.1.1.json"
RULE_ID = "boe_b0786"
TOTAL_SHEET = "TOTAL"
RWEA_COLUMN = "0110"
MONEY_TOLERANCE = 0.005

_IDENTITY = re.compile(
    r"^\{t: OF09\.02\.01\.01, r: (?P<total>\d{4}),.*?\} i= "
    r"isum\(\{t: OF09\.02\.01\.01, r: (?P<parts>[0-9; ]+),"
)
_SCOPE_COLUMNS = re.compile(r"c:\s*(?P<columns>[0-9; ]+),")


class Identity(NamedTuple):
    """``boe_b0786``: one total row, the rows it sums, and the columns it covers."""

    total: str
    parts: tuple[str, ...]
    columns: tuple[str, ...]


#: Every registered Basel 3.1 run with an IRB permission — the runs that have an
#: IRB book and so an OF 09.02 at all. A Standardised run emits no OF 09.02.
B31_IRB_RUNS: tuple[GateInput, ...] = tuple(
    run
    for run in RUNS
    if run.framework == FRAMEWORK and run.build_config().permission_mode == PermissionMode.IRB
)


@pytest.fixture(scope="module")
def identity() -> Identity:
    """The published identity, read from the Bank's rule book."""
    return _identity(_rule())


def test_the_published_identity_is_enforced_and_reads_as_annex_ii_states_it() -> None:
    """Adequacy: the rule is live ERROR for PRA001, and the parse found what
    Annex II p.145 says — row 0150 is "the sum of rows 0020, 0030 and 0060"."""
    # Arrange
    rule = _rule()

    # Act
    parsed = _identity(rule)

    # Assert
    assert rule.is_enforced(MODULE)
    assert rule.severities[MODULE] == "ERROR"
    assert (parsed.total, parsed.parts) == ("0150", ("0020", "0030", "0060"))
    assert RWEA_COLUMN in parsed.columns


def test_there_is_a_registered_basel_3_1_irb_run() -> None:
    """An empty parametrisation is a skip, not a failure — guard against it."""
    assert B31_IRB_RUNS, "no Basel 3.1 IRB run is registered in RUNS: the check is vacuous"


@pytest.mark.parametrize("run", B31_IRB_RUNS, ids=[run.portfolio for run in B31_IRB_RUNS])
def test_row_0150_is_the_sum_of_its_published_rows_on_every_sheet(
    run: GateInput, identity: Identity
) -> None:
    # Arrange
    result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
    sheets = COREPGenerator().generate_from_lazyframe(result.results, framework=FRAMEWORK).c09_02
    assert sheets and TOTAL_SHEET in sheets, f"{run.portfolio}: no OF 09.02 was emitted"
    assert _cell(sheets[TOTAL_SHEET], identity.total, RWEA_COLUMN) > 0.0, (
        f"{run.portfolio}: no IRB RWEA on OF 09.02 - the residual would be vacuous"
    )

    # Act
    residuals = _residuals(sheets, identity)

    # Assert
    assert residuals == {}, (
        f"{run.portfolio}: OF 09.02 row {identity.total} counts legs that rows "
        f"{' + '.join(identity.parts)} do not ((sheet, column): residual): {residuals}"
    )


def test_a_leg_of_no_published_row_is_counted_in_row_0150_and_caught(
    identity: Identity,
) -> None:
    """The negative control: the guard fires on the case it exists to catch.

    Synthetic on purpose — Art. 147A(1)(a) stops the pipeline producing a Basel
    3.1 IRB central-government leg, so only a hand-built ledger holds one. It
    also pins the design the guard relies on: row 0150 counts the leg although
    no row of the published layout claims it.
    """
    # Arrange
    stray_rwea = 300.0
    ledger = pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate", "central_govt_central_bank"],
            "ead_final": [1000.0, 1500.0],
            "ead_gross": [1200.0, 1700.0],
            "rwa_final": [700.0, stray_rwea],
            "cp_country_code": ["GB", "GB"],
            "default_status": [False, False],
            "pd_floored": [0.01, 0.008],
            "lgd_post_crm": [0.45, 0.45],
            "expected_loss": [4.5, 5.4],
        }
    )
    sheets = LedgerShimCorepGenerator().generate_from_lazyframe(ledger, framework=FRAMEWORK).c09_02

    # Act
    residuals = _residuals(sheets, identity)

    # Assert
    assert residuals[(TOTAL_SHEET, RWEA_COLUMN)] == pytest.approx(stray_rwea)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _rule() -> Rule:
    (rule,) = [r for r in load_rulebook(RULE_BOOK).rules if r.rule_id == RULE_ID]
    return rule


def _identity(rule: Rule) -> Identity:
    expression = _IDENTITY.match(rule.expression)
    scope = _SCOPE_COLUMNS.search(rule.scope or "")
    assert expression is not None, rule.expression
    assert scope is not None, rule.scope
    return Identity(
        total=expression["total"],
        parts=tuple(ref.strip() for ref in expression["parts"].split(";")),
        columns=tuple(ref.strip() for ref in scope["columns"].split(";")),
    )


def _residuals(sheets: dict[str, pl.DataFrame], identity: Identity) -> dict[tuple[str, str], float]:
    """``{(sheet, column): total - sum(parts)}`` wherever it is not 0.00."""
    residuals: dict[tuple[str, str], float] = {}
    for sheet_key, sheet in sheets.items():
        for column in identity.columns:
            residual = _cell(sheet, identity.total, column) - sum(
                _cell(sheet, part, column) for part in identity.parts
            )
            if abs(residual) > MONEY_TOLERANCE:
                residuals[(sheet_key, column)] = residual
    return residuals


def _cell(sheet: pl.DataFrame, row_ref: str, column: str) -> float:
    """One cell, with an absent row or an unreported (null) cell read as zero."""
    row = sheet.filter(pl.col("row_ref") == row_ref)
    if row.height == 0 or column not in sheet.columns:
        return 0.0
    value = row[column][0]
    return float(value) if value is not None else 0.0
