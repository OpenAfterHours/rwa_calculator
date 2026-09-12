"""Isolating mutation: C 07.00 row 0040 loses its exposure-class scope.

``_terms_for_row`` returns row 0040 as two terms — the sheet key (Annex II's
"Only reported in exposure class 'Secured by mortgages on immovable property'")
and the data term ``property_type == "residential"``. This strips the SHEET term
from every row that carries one and leaves everything else alone, which is the
pre-fix predicate exactly: before ``_SHEET_KEY_COL``, row 0040 matched no branch
at all and fell through to ``return None``, so it rendered all-null on every
sheet; with a bare data term it renders on every sheet that holds a
residential-property-secured leg.

Exactly ONE thing changes. The mutation does not restate ``_terms_for_row``, does
not touch the frame the sheet key is materialised on, and does not alter the data
term — so a red test is attributable to the scope and to nothing else (the
2026-08-29 graduation-ledger row: a mutation that reddens for the wrong reason
manufactures false confidence).

It also reports whether it was APPLIED and whether it was VACUOUS, because a
green run under a mutation is a claim about the test only if both are known
(``README.md``, mechanisms 2 and 4). A session in which no call ever lost a term
fails rather than passing quietly.

Measured red set: see ``README.md``, "The C 07.00 row-scope set".

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> \
      -p mutate_row_0040_is_not_sheet_scoped
"""

from __future__ import annotations

from pathlib import Path

import pytest

_STRIPPED_CALLS: list[str] = []
_APPLIED: list[str] = []


#: SESSION scope, and it is load-bearing rather than an optimisation. pytest sets
#: broader-scoped fixtures up FIRST, so a function-scoped patch lands AFTER any
#: module- or session-scoped fixture has already built its bundles — and
#: ``test_supervisory_validations.py`` builds all 26 runs in a ``scope="module"``
#: fixture. Measured: under a function-scoped version of this plugin that whole
#: register reported "0 call(s) lost a sheet term", i.e. it ran UNMUTATED while
#: looking green. The vacuity line below is what caught it.
@pytest.fixture(autouse=True, scope="session")
def _row_terms_carry_no_sheet_scope():
    import rwa_calc.reporting.corep.c07 as module

    original = module._terms_for_row
    sheet_key = module._SHEET_KEY_COL

    def _unscoped(section_index, ref, name, cols):  # noqa: ANN001, ANN202
        terms = original(section_index, ref, name, cols)
        if terms is None:
            return None
        stripped = tuple(pair for pair in terms if pair[0] != sheet_key)
        if len(stripped) != len(terms):
            _STRIPPED_CALLS.append(ref)
        return stripped

    module._terms_for_row = _unscoped
    # Mechanism 2: the replacement is a different object, so a patch that silently
    # did not apply cannot read as green.
    assert module._terms_for_row is not original, "the mutation did not apply"
    # Mechanism 3: the mutated module is the one under test, not a sibling
    # checkout reached through a stale editable install.
    assert Path(module.__file__).is_relative_to(Path.cwd()), (
        f"mutating {module.__file__}, which is outside {Path.cwd()}"
    )
    _APPLIED.append(module.__file__)
    try:
        yield
    finally:
        module._terms_for_row = original


def pytest_terminal_summary(terminalreporter) -> None:  # noqa: ANN001
    """Report the mutation's own colour alongside pytest's."""
    if not _APPLIED:
        terminalreporter.write_line(
            "mutate_row_0040_is_not_sheet_scoped: NOT APPLIED - no test used the fixture"
        )
        return
    terminalreporter.write_line(
        f"mutate_row_0040_is_not_sheet_scoped: applied to {_APPLIED[0]}; "
        f"{len(_STRIPPED_CALLS)} call(s) lost a sheet term, on rows "
        f"{sorted(set(_STRIPPED_CALLS)) or '(none)'}"
    )
    if not _STRIPPED_CALLS:
        terminalreporter.write_line(
            "mutate_row_0040_is_not_sheet_scoped: VACUOUS - no call carried a sheet "
            "term, so mutant and original returned the same terms on every call the "
            "suite makes; a green run here is evidence about the MUTATION, not the test"
        )
