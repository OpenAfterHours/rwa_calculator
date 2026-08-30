"""Isolating mutation: the drill-down reads a frame the matrix did not.

The matrix's counts and the list under it are aggregations of ONE frame
(``_migration_pairs``), so they cannot disagree about how many legs a cell holds
or what they are worth. This gives ``migration_legs`` — and only
``migration_legs`` — a frame one row short, which is the observable shape of a
separately-derived listing that has drifted from the counts above it. This page
has already produced that defect once: a cell reporting a 221,000 difference
rendered 50 rows of exact agreement.

WHAT IT PROVES AND WHAT IT DOES NOT. It does NOT prove the two share a
computation — no mutation can, because the sharing is structural and a mutation
is a behaviour change. Mutate the SHARED frame and both move together and every
assertion stays green, which is the guarantee working. What it proves is
narrower and worth having: something asserts each cell's count and both its
money figures against the list beneath it, so a future refactor that gives the
drill-down its own reader cannot land green while the two disagree.

Changes ONE thing: the frame ``migration_legs`` receives. Discriminated by the
CALLER rather than by patching the function itself, deliberately — patching
``module.migration_legs`` reaches only importers that resolve it through the
module, and ``tests/unit/analysis/test_return_recon.py`` binds the name at
import time, so its census would have run the ORIGINAL and gone green for a
reason that has nothing to do with the drill-down (README mechanism 2). A
module-global lookup inside the function body reaches every caller.

Run with::

    PYTHONPATH=<this dir> uv run pytest <tests> -p mutate_drill_list_drops_a_leg
"""

from __future__ import annotations

import sys

import pytest

#: Calls made from the drill-down, and calls where the mutation actually removed
#: something. The second is the vacuity proof (README mechanism 4): a corpus of
#: empty groups would make mutant and original agree on every call.
_CALLS = [0]
_DIVERGED = [0]


@pytest.fixture(autouse=True)
def _the_list_reads_a_shorter_frame():
    import rwa_calc.analysis.return_recon as module

    original = module._migration_pairs

    def _short(recon, template_id, sheet, predicate_key, money_column):  # noqa: ANN001, ANN202
        frame = original(recon, template_id, sheet, predicate_key, money_column)
        if sys._getframe(1).f_code.co_name != "migration_legs":  # noqa: SLF001
            return frame
        _CALLS[0] += 1
        if frame.height == 0:
            return frame
        _DIVERGED[0] += 1
        return frame.head(frame.height - 1)

    module._migration_pairs = _short
    assert module._migration_pairs is not original, "the patch did not take"
    try:
        yield
    finally:
        module._migration_pairs = original


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001, ARG001
    """Fail the session unless the mutation changed a real answer."""
    if not _DIVERGED[0]:
        session.exitstatus = 1
        print(  # noqa: T201 - the plugin's own verdict, read off the summary
            f"\nmutate_drill_list_drops_a_leg: VACUOUS - {_CALLS[0]} drill-down call(s), "
            "none over a frame with a row to drop, so its colour means nothing."
        )
